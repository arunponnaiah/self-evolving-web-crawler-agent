from __future__ import annotations

import anthropic

from crawler_agent.config import settings
from crawler_agent.extraction.prompts import (
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    render_feedback_section,
)
from crawler_agent.extraction.schemas import ExtractionResult

TOOL_NAME = "record_regulation_items"

_TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": "Record the regulatory items extracted from the page.",
    "input_schema": ExtractionResult.model_json_schema(),
}


class LlmExtractor:
    """Extracts structured regulation records from page text via the Anthropic API.

    Uses tool-use to force the model to return JSON matching ExtractionResult,
    so a malformed response is a visible exception rather than a silent parse
    failure.

    `feedback_examples`, if given, gets spliced into the system prompt once
    at construction time -- this is how accumulated human corrections to
    past summaries (feedback/store.py) actually change future extractions,
    without any fine-tuning. Prefer passing `system_prompt` directly instead
    (e.g. `extraction/prompt_review.get_deployed_system_prompt()`'s output)
    when feedback-driven changes should only take effect after human review
    -- it takes precedence over `feedback_examples` when both are given.
    """

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        feedback_examples: list | None = None,
        system_prompt: str | None = None,
    ):
        self.model = model or settings.llm_model
        self.client = anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key)
        self.system_prompt = system_prompt or (
            SYSTEM_PROMPT + render_feedback_section(feedback_examples or [])
        )

    def extract(self, *, page_text: str, page_url: str) -> ExtractionResult:
        message = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=self.system_prompt,
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[
                {
                    "role": "user",
                    "content": USER_PROMPT_TEMPLATE.format(page_url=page_url, page_text=page_text),
                }
            ],
        )
        for block in message.content:
            if block.type == "tool_use" and block.name == TOOL_NAME:
                return ExtractionResult.model_validate(block.input)
        raise RuntimeError("LLM did not return a tool_use block with extracted items")
