from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from langgraph.graph import END, StateGraph

from crawler_agent.agent.assess import ContentAssessor
from crawler_agent.agent.state import AgentState
from crawler_agent.extraction.schemas import Extractor, ExtractedRegulationItem
from crawler_agent.fetch.base import Fetcher
from crawler_agent.layout.fingerprint import compute_fingerprint
from crawler_agent.utils.html_clean import to_text

logger = logging.getLogger(__name__)

UrlStatus = Literal["extracted", "blocked", "error"]

# Large enough that a structured listing page's records don't get cut off
# mid-record -- a truncated record (e.g. a JSON object missing its closing
# fields) made extraction non-deterministic near the cut point, which showed
# up as spurious "updated" change events on an otherwise-unchanged page.
EXTRACT_MAX_CHARS = 45_000


@dataclass
class UrlCrawlResult:
    status: UrlStatus
    items: list[ExtractedRegulationItem] = field(default_factory=list)
    html: str | None = None
    fingerprint: str | None = None
    fetch_mode_used: str = "http"
    attempts: int = 0
    reason: str | None = None


def build_crawl_agent(
    *,
    http_fetcher: Fetcher,
    browser_fetcher: Fetcher,
    assessor: ContentAssessor,
    extractor: Extractor,
    max_attempts: int = 2,
):
    """One site page, run through an agent loop instead of a fixed pipeline.

    fetch -> assess ("is this real content or a block/CAPTCHA page?") ->
    either escalate to a real browser and retry (bounded by max_attempts), give
    up as blocked, or proceed to fingerprint + LLM extraction. This is what
    lets the agent react to a site's anti-bot behavior instead of silently
    storing an empty/garbage crawl as if it succeeded.
    """

    def fetcher_for(mode: str) -> Fetcher:
        return browser_fetcher if mode == "browser" else http_fetcher

    def fetch_node(state: AgentState) -> dict:
        mode = state["fetch_mode"]
        try:
            result = fetcher_for(mode).fetch(state["url"])
        except Exception as exc:  # noqa: BLE001 - surfaced via state, not a crash
            logger.warning("fetch failed for %s (%s): %s", state["url"], mode, exc)
            return {"html": None, "markdown": None, "error": str(exc), "attempts": state["attempts"] + 1}
        return {
            "html": result.html,
            "markdown": result.markdown,
            "status_code": result.status_code,
            "error": None,
            "attempts": state["attempts"] + 1,
        }

    def page_text_for(state: AgentState, max_chars: int) -> str:
        # A fetcher's own markdown is only set when its content-filtering
        # demonstrably removed boilerplate (see browser_fetcher.py) -- prefer
        # it when present; otherwise fall back to the general-purpose cleaner.
        text = state.get("markdown") or to_text(state["html"], base_url=state["url"])
        return text[:max_chars]

    def assess_node(state: AgentState) -> dict:
        if state.get("error") or not state.get("html"):
            return {
                "assessment_action": "skip_blocked",
                "assessment_reason": state.get("error") or "empty response body",
            }
        page_text = page_text_for(state, max_chars=3000)
        assessment = assessor.assess(
            page_text=page_text, page_url=state["url"], fetch_mode=state["fetch_mode"]
        )
        return {"assessment_action": assessment.action, "assessment_reason": assessment.reason}

    def escalate_node(state: AgentState) -> dict:
        logger.info("escalating %s from http to browser fetch after a blocked attempt", state["url"])
        return {"fetch_mode": "browser"}

    def fingerprint_node(state: AgentState) -> dict:
        return {"fingerprint": compute_fingerprint(state["html"])}

    def extract_node(state: AgentState) -> dict:
        page_text = page_text_for(state, max_chars=EXTRACT_MAX_CHARS)
        result = extractor.extract(page_text=page_text, page_url=state["url"])
        return {"extracted_items": result.items}

    def route_after_assess(state: AgentState) -> str:
        action = state["assessment_action"]
        if action == "extract":
            return "fingerprint"
        can_escalate = (
            action == "retry_browser"
            and state["fetch_mode"] != "browser"
            and state["attempts"] < max_attempts
        )
        return "escalate" if can_escalate else "end_blocked"

    graph = StateGraph(AgentState)
    graph.add_node("fetch", fetch_node)
    graph.add_node("assess", assess_node)
    graph.add_node("escalate", escalate_node)
    graph.add_node("fingerprint", fingerprint_node)
    graph.add_node("extract", extract_node)

    graph.set_entry_point("fetch")
    graph.add_edge("fetch", "assess")
    graph.add_conditional_edges(
        "assess",
        route_after_assess,
        {"fingerprint": "fingerprint", "escalate": "escalate", "end_blocked": END},
    )
    graph.add_edge("escalate", "fetch")
    graph.add_edge("fingerprint", "extract")
    graph.add_edge("extract", END)

    return graph.compile()


def run_url(agent, url: str, fetch_mode: str) -> UrlCrawlResult:
    initial: AgentState = {
        "url": url,
        "fetch_mode": fetch_mode,
        "attempts": 0,
        "extracted_items": [],
    }
    final_state: AgentState = agent.invoke(initial)

    if final_state.get("assessment_action") == "extract":
        return UrlCrawlResult(
            status="extracted",
            items=final_state.get("extracted_items", []),
            html=final_state.get("html"),
            fingerprint=final_state.get("fingerprint"),
            fetch_mode_used=final_state["fetch_mode"],
            attempts=final_state["attempts"],
        )

    return UrlCrawlResult(
        status="blocked" if final_state.get("assessment_action") == "skip_blocked" else "error",
        fetch_mode_used=final_state["fetch_mode"],
        attempts=final_state["attempts"],
        reason=final_state.get("assessment_reason") or final_state.get("error"),
    )
