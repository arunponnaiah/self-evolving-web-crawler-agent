from __future__ import annotations

from typing import Literal, TypedDict

from crawler_agent.extraction.schemas import ExtractedRegulationItem

AssessmentAction = Literal["extract", "retry_browser", "skip_blocked"]


class AgentState(TypedDict, total=False):
    url: str
    fetch_mode: str
    attempts: int
    status_code: int | None
    html: str | None
    markdown: str | None
    error: str | None
    fingerprint: str | None
    assessment_action: AssessmentAction | None
    assessment_reason: str | None
    extracted_items: list[ExtractedRegulationItem]
