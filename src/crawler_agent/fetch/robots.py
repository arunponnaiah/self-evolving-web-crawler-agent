from __future__ import annotations

import requests
from protego import Protego

from crawler_agent.config import settings


class RobotsDisallowedError(Exception):
    pass


class RobotsChecker:
    """Shared robots.txt cache so every fetcher (http or browser) honors it.

    Uses `protego` (RFC 9309 compliant) rather than the stdlib `urllib.robotparser`,
    which mis-parses some real-world robots.txt files: a blank line *within* a
    `User-agent: *` block (legal per RFC 9309 -- only a new `User-agent:` line
    starts a new group) causes robotparser to silently drop every `Disallow:`
    line after the blank line. That previously let this crawler fetch paths a
    site had explicitly disallowed (e.g. federalregister.gov's `/documents/search`).
    """

    def __init__(self, user_agent: str | None = None):
        self.user_agent = user_agent or settings.user_agent
        self._cache: dict[str, Protego] = {}

    def _parser_for(self, url: str) -> Protego:
        from urllib.parse import urlparse

        domain = urlparse(url).netloc
        if domain not in self._cache:
            robots_url = f"{urlparse(url).scheme}://{domain}/robots.txt"
            try:
                resp = requests.get(robots_url, headers={"User-Agent": self.user_agent}, timeout=10)
                text = resp.text if resp.ok else ""
            except requests.RequestException:
                text = ""
            self._cache[domain] = Protego.parse(text)
        return self._cache[domain]

    def ensure_allowed(self, url: str) -> None:
        if not self._parser_for(url).can_fetch(url, self.user_agent):
            raise RobotsDisallowedError(f"robots.txt disallows fetching {url}")
