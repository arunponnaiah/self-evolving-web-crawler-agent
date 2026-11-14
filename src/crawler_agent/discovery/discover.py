from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from crawler_agent.discovery.authentic_domains import is_authentic_domain
from crawler_agent.discovery.candidate_suggester import CandidateSuggester, LlmCandidateSuggester
from crawler_agent.discovery.probe import ProbeResult, build_probe_agent, probe_candidate
from crawler_agent.discovery.proposals import create_proposal

logger = logging.getLogger(__name__)

FETCH_MODES_TO_TRY = ("http", "browser")


@dataclass
class DiscoveryReport:
    country: str
    tried: list[ProbeResult] = field(default_factory=list)
    rejected_unauthentic: list[str] = field(default_factory=list)
    proposal_id: int | None = None


def _slug_for(country: str, url: str) -> str:
    from urllib.parse import urlparse

    domain = urlparse(url).netloc.replace("www.", "")
    base = re.sub(r"[^a-z0-9]+", "_", f"{country.lower()}_{domain}").strip("_")
    return base


def discover_site(
    session: Session,
    country: str,
    suggester: CandidateSuggester | None = None,
    max_candidates: int = 5,
    agent=None,
) -> DiscoveryReport:
    """Discover a working regulatory site candidate for `country` and queue
    it for human approval -- never registers it directly.

    Gates every candidate through the domain allowlist before ever fetching
    it, then only proposes a candidate that actually yields real extracted
    items when run through the exact same pipeline a real crawl would use
    (discovery/probe.py). Never falls back to "just use what the LLM said" --
    a candidate that fails either check is discarded, not proposed. A
    candidate that passes both checks still isn't registered automatically:
    it becomes a pending SiteProposal, and only
    `discovery/proposals.approve_proposal()` -- triggered by a human running
    `crawler-agent approve-site` -- ever writes it into the registry.
    """
    report = DiscoveryReport(country=country)
    suggestions = (suggester or LlmCandidateSuggester()).suggest(country=country)

    agent = agent or build_probe_agent()
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
                proposal = create_proposal(
                    session,
                    slug=_slug_for(country, candidate.url),
                    name=f"{country} regulatory register ({candidate.url})",
                    country=country,
                    base_url=candidate.url,
                    seed_urls=[candidate.url],
                    fetch_mode=fetch_mode,
                )
                report.proposal_id = proposal.id
                return report

    return report
