from __future__ import annotations

from dataclasses import dataclass

from crawler_agent.agent.assess import ContentAssessor, LlmContentAssessor
from crawler_agent.agent.graph import UrlCrawlResult, build_crawl_agent, run_url
from crawler_agent.extraction.schemas import Extractor
from crawler_agent.extraction.llm_extractor import LlmExtractor
from crawler_agent.fetch.browser_fetcher import BrowserFetcher
from crawler_agent.fetch.http_fetcher import HttpFetcher


def build_probe_agent(
    assessor: ContentAssessor | None = None, extractor: Extractor | None = None
):
    """The same agent construction `pipeline/run.py` uses for a real crawl --
    probing and crawling must use identical logic, or "this URL works" would
    not actually predict "a real crawl of this URL will work"."""
    return build_crawl_agent(
        http_fetcher=HttpFetcher(),
        browser_fetcher=BrowserFetcher(),
        assessor=assessor or LlmContentAssessor(),
        extractor=extractor or LlmExtractor(),
    )


@dataclass
class ProbeResult:
    url: str
    fetch_mode: str
    works: bool
    item_count: int
    reason: str | None = None


def probe_candidate(agent, url: str, fetch_mode: str) -> ProbeResult:
    """Is this URL actually a good seed? Reuses the real crawl pipeline
    (fetch -> assess-for-block-pages -> escalate-or-give-up -> extract) as the
    oracle, rather than a separate probing implementation -- a URL only
    counts as "working" if the exact same pipeline a real crawl would use
    extracts at least one real item from it.
    """
    result: UrlCrawlResult = run_url(agent, url, fetch_mode=fetch_mode)
    works = result.status == "extracted" and len(result.items) > 0
    return ProbeResult(
        url=url,
        fetch_mode=result.fetch_mode_used,
        works=works,
        item_count=len(result.items),
        reason=result.reason if not works else None,
    )
