from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from crawler_agent.discovery.authentic_domains import is_authentic_domain
from crawler_agent.discovery.candidate_suggester import CandidateSuggester, LlmCandidateSuggester
from crawler_agent.discovery.probe import ProbeResult, build_probe_agent, probe_candidate
from crawler_agent.sites.loader import SiteConfig, append_site

logger = logging.getLogger(__name__)

FETCH_MODES_TO_TRY = ("http", "browser")


@dataclass
class DiscoveryReport:
    country: str
    tried: list[ProbeResult] = field(default_factory=list)
    rejected_unauthentic: list[str] = field(default_factory=list)
    registered_site_id: str | None = None


def _slug_for(country: str, url: str) -> str:
    from urllib.parse import urlparse

    domain = urlparse(url).netloc.replace("www.", "")
    base = re.sub(r"[^a-z0-9]+", "_", f"{country.lower()}_{domain}").strip("_")
    return base


def discover_site(
    country: str,
    suggester: CandidateSuggester | None = None,
    max_candidates: int = 5,
) -> DiscoveryReport:
    """Discover and register a working regulatory site for `country`.

    Gates every candidate through the domain allowlist before ever fetching
    it, then only registers a candidate that actually yields real extracted
    items when run through the exact same pipeline a real crawl would use
    (discovery/probe.py). Never falls back to "just use what the LLM said" --
    a candidate that fails either check is rejected, not registered.
    """
    report = DiscoveryReport(country=country)
    suggestions = (suggester or LlmCandidateSuggester()).suggest(country=country)

    agent = build_probe_agent()
    candidates_checked = 0
    for candidate in suggestions.candidates:
        if candidates_checked >= max_candidates:
            break
        if not is_authentic_domain(country, candidate.url):
            report.rejected_unauthentic.append(candidate.url)
            continue
        candidates_checked += 1

        for fetch_mode in FETCH_MODES_TO_TRY:
            probe = probe_candidate(agent, candidate.url, fetch_mode=fetch_mode)
            report.tried.append(probe)
            if probe.works:
                site_id = _slug_for(country, candidate.url)
                append_site(
                    SiteConfig(
                        id=site_id,
                        name=f"{country} regulatory register ({candidate.url})",
                        country=country,
                        base_url=candidate.url,
                        seed_urls=[candidate.url],
                        fetch_mode=fetch_mode,
                    )
                )
                report.registered_site_id = site_id
                return report

    return report
