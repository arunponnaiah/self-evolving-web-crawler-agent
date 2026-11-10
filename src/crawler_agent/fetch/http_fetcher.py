from __future__ import annotations

import time
from urllib.parse import urlparse

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from crawler_agent.config import settings
from crawler_agent.fetch.base import FetchResult
from crawler_agent.fetch.robots import RobotsChecker


class HttpFetcher:
    """Polite requests-based fetcher.

    Honors robots.txt per domain, enforces a minimum delay between requests to the
    same domain, and sends a descriptive User-Agent. GET-only, no auth bypass.
    """

    def __init__(self, delay_seconds: float | None = None, user_agent: str | None = None):
        self.delay_seconds = delay_seconds if delay_seconds is not None else settings.default_delay_seconds
        self.user_agent = user_agent or settings.user_agent
        self.robots = RobotsChecker(self.user_agent)
        self._last_request_at: dict[str, float] = {}

    def _respect_rate_limit(self, url: str) -> None:
        domain = urlparse(url).netloc
        last = self._last_request_at.get(domain)
        if last is not None:
            elapsed = time.monotonic() - last
            remaining = self.delay_seconds - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at[domain] = time.monotonic()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=15))
    def fetch(self, url: str) -> FetchResult:
        self.robots.ensure_allowed(url)
        self._respect_rate_limit(url)
        resp = requests.get(url, headers={"User-Agent": self.user_agent}, timeout=20)
        resp.raise_for_status()
        return FetchResult(url=url, status_code=resp.status_code, html=resp.text)
