from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from crawler_agent.agent.assess import ContentAssessor, LlmContentAssessor
from crawler_agent.agent.graph import build_crawl_agent, run_url
from crawler_agent.change_detection.detector import classify_and_upsert
from crawler_agent.config import settings
from crawler_agent.db.models import ChangeEvent, PageSnapshot, Site
from crawler_agent.discovery.resolver import resolve_seed_url
from crawler_agent.extraction.schemas import Extractor
from crawler_agent.fetch.base import Fetcher
from crawler_agent.fetch.browser_fetcher import BrowserFetcher
from crawler_agent.fetch.http_fetcher import HttpFetcher
from crawler_agent.layout.diff import resolve_layout_version
from crawler_agent.sites.loader import SiteConfig

logger = logging.getLogger(__name__)


@dataclass
class CrawlRunSummary:
    site_id: str
    pages_fetched: int = 0
    blocked_pages: int = 0
    layout_relearned: bool = False
    new_items: int = 0
    updated_items: int = 0
    unchanged_items: int = 0
    errors: list[str] = field(default_factory=list)


def _get_or_create_site(session: Session, config: SiteConfig) -> Site:
    site = session.scalar(select(Site).where(Site.slug == config.id))
    if site is None:
        site = Site(
            slug=config.id,
            name=config.name,
            country=config.country,
            base_url=config.base_url,
            fetch_mode=config.fetch_mode,
            crawl_interval_hours=config.crawl_interval_hours,
        )
        session.add(site)
        session.flush()
    return site


def run_crawl(
    session: Session,
    config: SiteConfig,
    extractor: Extractor,
    assessor: ContentAssessor | None = None,
    max_pages: int | None = None,
) -> CrawlRunSummary:
    """One crawl cycle for a site, driven by the LangGraph agent in `agent/graph.py`
    for each seed URL: fetch -> assess (real content vs. a block page) -> escalate
    to a browser or give up blocked -> fingerprint/diff -> LLM extract ->
    change-detect -> persist. Returns a summary for reporting."""
    site = _get_or_create_site(session, config)
    http_fetcher: Fetcher = HttpFetcher()
    browser_fetcher: Fetcher = BrowserFetcher()
    agent = build_crawl_agent(
        http_fetcher=http_fetcher,
        browser_fetcher=browser_fetcher,
        assessor=assessor or LlmContentAssessor(),
        extractor=extractor,
    )
    summary = CrawlRunSummary(site_id=config.id)
    limit = max_pages if max_pages is not None else settings.max_pages_per_run

    if config.seed_resolver:
        resolver_fetcher = browser_fetcher if config.fetch_mode == "browser" else http_fetcher
        try:
            seed_urls = [resolve_seed_url(config.seed_resolver, resolver_fetcher)]
        except Exception as exc:  # noqa: BLE001
            logger.warning("seed_resolver '%s' failed for %s: %s", config.seed_resolver, config.id, exc)
            summary.errors.append(f"seed_resolver:{config.seed_resolver}:{exc}")
            seed_urls = []
    else:
        seed_urls = config.seed_urls

    for url in seed_urls[:limit]:
        result = run_url(agent, url, fetch_mode=config.fetch_mode)

        if result.status != "extracted":
            summary.blocked_pages += 1
            logger.warning("blocked/error for %s: %s", url, result.reason)
            session.add(
                ChangeEvent(
                    type="access_blocked",
                    site_id=site.id,
                    details_json=json.dumps(
                        {"url": url, "reason": result.reason, "fetch_mode": result.fetch_mode_used}
                    ),
                )
            )
            session.flush()
            continue

        summary.pages_fetched += 1
        content_hash = hashlib.sha256(result.html.encode("utf-8")).hexdigest()
        diff = resolve_layout_version(session, site, result.fingerprint, sample_url=url)
        session.add(
            PageSnapshot(
                site_id=site.id,
                url=url,
                content_hash=content_hash,
                layout_version_id=diff.layout_version.id,
            )
        )
        if diff.is_new_layout:
            summary.layout_relearned = True
            session.add(
                ChangeEvent(
                    type="layout_relearned",
                    site_id=site.id,
                    details_json=json.dumps({"sample_url": url, "fingerprint": result.fingerprint}),
                )
            )
        session.flush()

        for item in result.items:
            classification = classify_and_upsert(session, site, item)
            if classification.type == "new_item":
                summary.new_items += 1
            elif classification.type == "updated_item":
                summary.updated_items += 1
            else:
                summary.unchanged_items += 1

    return summary
