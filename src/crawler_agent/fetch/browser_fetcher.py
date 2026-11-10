from __future__ import annotations

import asyncio

from crawler_agent.config import settings
from crawler_agent.fetch.base import FetchResult
from crawler_agent.fetch.robots import RobotsChecker

# Pruning-based markdown is NOT trusted by default. A simple "did it shrink"
# or "did it keep most links" check cannot reliably tell a genuine win (a
# dense article-like page, where pruning drops real nav/cookie/footer chrome)
# from a regression (a link-list/index page, where the real content IS the
# sparse links and pruning's density heuristic discards them while keeping
# denser-but-irrelevant prose). Measured on two real EUR-Lex pages: pruning
# correctly kept the real per-document rows on a daily-issue listing page,
# but on the index/hub page it did the opposite -- it kept ambiguous "about
# this site" prose and discarded the one part of the page with real document
# links, both while shrinking by a similar ratio and losing a similar
# fraction of links. Enabling this for a given site requires verifying
# extraction quality on that site's actual pages, not a blind heuristic --
# so `select_markdown` stays available but unused until that's done per site.
_PRUNING_BENEFIT_RATIO = 0.9


def select_markdown(raw_markdown: str, fit_markdown: str) -> str | None:
    """Decide whether pruned markdown is worth using over the raw-HTML cleaner.

    Not currently called by BrowserFetcher by default -- see module docstring
    above. Kept as a tested building block for a future, per-site opt-in.
    """
    if fit_markdown and raw_markdown and len(fit_markdown) < _PRUNING_BENEFIT_RATIO * len(raw_markdown):
        return fit_markdown
    return None


class BrowserFetcher:
    """Crawl4AI-based fetcher for JS-rendered or bot-protected pages.

    Requires the optional `browser` extra (`pip install .[browser]`, which
    installs crawl4ai, then `playwright install chromium`). Imported lazily so
    the base package works without it installed.
    """

    def __init__(self, user_agent: str | None = None):
        self.user_agent = user_agent or settings.user_agent
        self.robots = RobotsChecker(self.user_agent)

    def fetch(self, url: str, page_timeout_ms: int = 20_000) -> FetchResult:
        self.robots.ensure_allowed(url)
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
        except ImportError as exc:
            raise RuntimeError(
                "crawl4ai is not installed; install the 'browser' extra to use "
                "fetch_mode: browser"
            ) from exc

        browser_cfg = BrowserConfig(headless=True, user_agent=self.user_agent)
        run_cfg = CrawlerRunConfig(wait_until="networkidle", page_timeout=page_timeout_ms)

        async def _run() -> FetchResult:
            async with AsyncWebCrawler(config=browser_cfg) as crawler:
                result = await crawler.arun(url=url, config=run_cfg)
                # markdown stays None: extraction uses the proven to_text()
                # cleaning pipeline for every browser-fetched page by default.
                return FetchResult(
                    url=url,
                    status_code=result.status_code or 0,
                    html=result.html or "",
                )

        return asyncio.run(_run())
