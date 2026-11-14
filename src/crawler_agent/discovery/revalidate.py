from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from crawler_agent.db.models import ChangeEvent, Site
from crawler_agent.discovery.probe import ProbeResult, build_probe_agent, probe_candidate
from crawler_agent.discovery.resolver import resolve_seed_url
from crawler_agent.fetch.base import Fetcher
from crawler_agent.fetch.browser_fetcher import BrowserFetcher
from crawler_agent.fetch.http_fetcher import HttpFetcher
from crawler_agent.sites.loader import (
    REGISTRY_PATH,
    SiteConfig,
    load_registry,
    update_site_enabled,
    update_site_seed_urls,
)

logger = logging.getLogger(__name__)

# Best-effort generic fallbacks when a site's seed URL stops working and it
# has no declared seed_resolver. These are patterns observed to work on real
# government sites in this project (e.g. UK's /uksi -> /uksi/data.feed) --
# not guaranteed to work generally, hence "best-effort".
GENERIC_SEED_VARIANTS = ["{base}/data.feed?sort=published", "{base}.json", "{base}/rss"]


@dataclass
class RevalidationResult:
    site_id: str
    still_working: bool
    corrected_to: str | None = None
    tried: list[ProbeResult] = field(default_factory=list)
    was_disabled: bool = False
    reenabled: bool = False


def _fetcher_for(fetch_mode: str) -> Fetcher:
    return BrowserFetcher() if fetch_mode == "browser" else HttpFetcher()


def revalidate_site(
    session: Session, config: SiteConfig, agent=None, registry_path: Path = REGISTRY_PATH
) -> RevalidationResult:
    """Re-check whether a registered site's seed URL still yields real items,
    and self-correct the registry if it doesn't.

    A site with a `seed_resolver` (e.g. EU's "find today's OJ issue") always
    uses that as the primary strategy, since its static seed is known-weak.
    Otherwise the existing static seed_urls are probed first; on failure, a
    small set of generic variants are tried as a best-effort fallback.

    `agent` is injectable (defaults to a real `build_probe_agent()`) so
    callers revalidating many sites can share one agent instead of rebuilding
    it per site, and so tests can pass a fake-backed agent.
    """
    agent = agent or build_probe_agent()
    result = RevalidationResult(site_id=config.id, still_working=False)

    if config.seed_resolver:
        # A resolver-driven site's registry seed_urls entry is just a static
        # placeholder/base, never the thing actually crawled -- the resolver
        # computes the real URL fresh every run (see pipeline/run.py). So a
        # successful resolve+probe here is "still healthy," never a
        # "correction" to persist; there's nothing to write back for a site
        # that's already correcting itself dynamically on every crawl.
        try:
            resolved_url = resolve_seed_url(config.seed_resolver, _fetcher_for(config.fetch_mode))
        except Exception as exc:  # noqa: BLE001
            logger.warning("seed_resolver '%s' failed for %s: %s", config.seed_resolver, config.id, exc)
            return result
        probe = probe_candidate(agent, resolved_url, fetch_mode=config.fetch_mode)
        result.tried.append(probe)
        result.still_working = probe.works
        return result

    for url in config.seed_urls:
        probe = probe_candidate(agent, url, fetch_mode=config.fetch_mode)
        result.tried.append(probe)
        if probe.works:
            result.still_working = True
            return result

    base = config.seed_urls[0].rstrip("/") if config.seed_urls else config.base_url.rstrip("/")
    for template in GENERIC_SEED_VARIANTS:
        variant = template.format(base=base)
        probe = probe_candidate(agent, variant, fetch_mode=config.fetch_mode)
        result.tried.append(probe)
        if probe.works:
            result.still_working = True
            result.corrected_to = variant
            _persist_correction(
                session, config, old_urls=config.seed_urls, new_urls=[variant], registry_path=registry_path
            )
            return result

    return result


def _persist_correction(
    session: Session,
    config: SiteConfig,
    old_urls: list[str],
    new_urls: list[str],
    registry_path: Path = REGISTRY_PATH,
) -> None:
    update_site_seed_urls(config.id, new_urls, path=registry_path)
    site = session.query(Site).filter(Site.slug == config.id).one_or_none()
    if site is not None:
        session.add(
            ChangeEvent(
                type="seed_url_self_corrected",
                site_id=site.id,
                details_json=json.dumps({"old_urls": old_urls, "new_urls": new_urls}),
            )
        )
        session.flush()


def revalidate_all(
    session: Session,
    site_id: str | None = None,
    agent=None,
    registry_path: Path = REGISTRY_PATH,
) -> list[RevalidationResult]:
    """Revalidate every registered site, including disabled ones.

    Disabled sites are still probed -- the probe itself is safe even for a
    site disabled over a robots.txt block, since fetching still goes through
    the same RobotsChecker and simply fails cleanly if the disallow is still
    in place. If a disabled site's probe now succeeds (e.g. the site's
    robots.txt policy changed back), it's auto re-enabled -- that's a safe
    thing to automate, since re-enabling only ever follows a real passing
    probe. A site that's enabled but stops working is NOT auto-disabled;
    that's left for a human to decide, same as the robots.txt-wide-block
    case that prompted this feature.
    """
    configs = load_registry(path=registry_path)
    if site_id:
        configs = [c for c in configs if c.id == site_id]
    agent = agent or build_probe_agent()

    results = []
    for config in configs:
        result = revalidate_site(session, config, agent=agent, registry_path=registry_path)
        result.was_disabled = not config.enabled
        if not config.enabled and result.still_working:
            update_site_enabled(config.id, True, path=registry_path)
            result.reenabled = True
            site = session.query(Site).filter(Site.slug == config.id).one_or_none()
            if site is not None:
                session.add(
                    ChangeEvent(
                        type="site_reenabled",
                        site_id=site.id,
                        details_json=json.dumps({"reason": "revalidation probe succeeded"}),
                    )
                )
                session.flush()
        results.append(result)
    return results
