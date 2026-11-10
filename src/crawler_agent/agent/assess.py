from __future__ import annotations

from typing import Protocol

import anthropic
from pydantic import BaseModel

from crawler_agent.agent.state import AssessmentAction
from crawler_agent.config import settings

SYSTEM_PROMPT = """You inspect text content fetched from a government or regulatory \
website page and decide whether it is genuine regulatory content or a bot-mitigation \
page (access-denied, CAPTCHA, "verify you are human", empty JS-only shell).

Decide one action:
- "extract": this looks like real regulatory content -- a listing of regulations
  /rules/documents, a single document page, or structured data (e.g. JSON).
- "retry_browser": this looks like a bot-check/CAPTCHA/JS-required placeholder,
  AND the page was fetched with a plain HTTP client (not a browser) -- a real
  browser might render the actual content.
- "skip_blocked": this looks like an access-denied/blocked page and it was
  already fetched with a browser (so retrying won't help), or it's an
  unrelated error page.
"""

USER_TEMPLATE = """Page URL: {page_url}
Fetched with: {fetch_mode}

Page text content (may be truncated):
---
{page_text}
---

Classify this page using the `assess_page` tool."""

TOOL_NAME = "assess_page"


class ContentAssessment(BaseModel):
    content_ok: bool
    action: AssessmentAction
    reason: str


_TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": "Record whether this page is real content or a bot-mitigation/block page.",
    "input_schema": ContentAssessment.model_json_schema(),
}


class ContentAssessor(Protocol):
    def assess(self, *, page_text: str, page_url: str, fetch_mode: str) -> ContentAssessment: ...


class LlmContentAssessor:
    """The agent's "notice something is wrong" step.

    This exists because real sites don't just 404 when they don't want to be
    scraped -- they return a 200/202 with a CAPTCHA or access-denied page that
    looks structurally fine but contains no real data. Without this step the
    pipeline would silently treat a block page as "zero items this crawl" and
    (worse) as a newly "learned" layout.
    """

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or settings.llm_model
        self.client = anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key)

    def assess(self, *, page_text: str, page_url: str, fetch_mode: str) -> ContentAssessment:
        message = self.client.messages.create(
            model=self.model,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[
                {
                    "role": "user",
                    "content": USER_TEMPLATE.format(
                        page_url=page_url, fetch_mode=fetch_mode, page_text=page_text[:3000]
                    ),
                }
            ],
        )
        for block in message.content:
            if block.type == "tool_use" and block.name == TOOL_NAME:
                return ContentAssessment.model_validate(block.input)
        raise RuntimeError("LLM did not return a tool_use block for assessment")
