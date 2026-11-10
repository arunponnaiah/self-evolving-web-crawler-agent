from __future__ import annotations

from typing import Protocol

import anthropic
from pydantic import BaseModel, Field

from crawler_agent.config import settings

SYSTEM_PROMPT = """You know about government and regulatory publishing systems \
worldwide. Given a country, suggest candidate URLs for that country's primary \
official regulatory gazette, statutory instrument register, or law/rule \
publication website -- the kind of site that publishes new and proposed \
regulations.

Rules:
- Only suggest official government domains for that country (the kind of
  domain a citizen would trust as authoritative), never a news site, law
  firm summary, or third-party aggregator.
- Prefer a sanctioned bulk-access path if you know one exists for that
  country (a public API, an Atom/RSS feed, a data export) over a plain HTML
  page, since those tend to be more reliable to crawl.
- Rank candidates by confidence, most likely first.
- If you are not confident any such official site exists or you don't know
  one, return an empty list rather than guessing -- a wrong URL here is
  worse than no suggestion, because nothing is verified until it's probed
  by fetching it for real.
- This is a starting point only: every candidate will be independently
  checked against a known-domain allowlist and will not be used unless it
  also returns real content when actually fetched.
"""

USER_TEMPLATE = """Country: {country}

Suggest candidate URLs using the `suggest_candidates` tool."""

TOOL_NAME = "suggest_candidates"


class CandidateSuggestion(BaseModel):
    url: str
    reason: str = Field(description="Why this is likely the right site, briefly.")


class CandidateSuggestions(BaseModel):
    candidates: list[CandidateSuggestion] = Field(default_factory=list)


_TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": "Record candidate regulatory gazette URLs for a country, ranked by confidence.",
    "input_schema": CandidateSuggestions.model_json_schema(),
}


class CandidateSuggester(Protocol):
    def suggest(self, *, country: str) -> CandidateSuggestions: ...


class LlmCandidateSuggester:
    """Where new site candidates come from for a never-seen country.

    This is knowledge-sourcing, not web search -- no search tool is wired
    into this agent, so suggestions come from the model's general knowledge
    and can be wrong or stale. That's exactly why nothing here is trusted
    directly: every suggestion still has to pass the domain-allowlist gate
    (discovery/authentic_domains.py) and then actually be fetched and shown
    to extract real content (discovery/probe.py) before it's ever registered.
    """

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or settings.llm_model
        self.client = anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key)

    def suggest(self, *, country: str) -> CandidateSuggestions:
        message = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[{"role": "user", "content": USER_TEMPLATE.format(country=country)}],
        )
        for block in message.content:
            if block.type == "tool_use" and block.name == TOOL_NAME:
                return CandidateSuggestions.model_validate(block.input)
        raise RuntimeError("LLM did not return a tool_use block for candidate suggestions")
