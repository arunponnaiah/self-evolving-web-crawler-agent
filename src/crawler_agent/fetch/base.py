from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class FetchResult:
    url: str
    status_code: int
    html: str
    # Pre-cleaned markdown, set only when a fetcher's own content-filtering
    # demonstrably removed boilerplate (see browser_fetcher.py). None means
    # "no better signal than the raw HTML" -- callers fall back to to_text().
    markdown: str | None = None


class Fetcher(Protocol):
    def fetch(self, url: str) -> FetchResult: ...
