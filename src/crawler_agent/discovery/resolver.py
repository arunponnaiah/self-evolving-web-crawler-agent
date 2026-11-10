from __future__ import annotations

import re
from typing import Callable

from crawler_agent.fetch.base import Fetcher
from crawler_agent.utils.html_clean import to_text

EU_HUB_URL = "https://eur-lex.europa.eu/oj/direct-access.html"

# Matches the first (most recent, since the hub page lists dates newest-first)
# L-series daily-view link, e.g.:
#   Display 4 act(s)
#   (https://eur-lex.europa.eu/oj/daily-view/L-series/default.html?&ojDate=09112026)
_L_SERIES_LINK_RE = re.compile(
    r"\(https://eur-lex\.europa\.eu/oj/daily-view/L-series/default\.html\?[^\s)]*\)"
)


def eurlex_latest_oj(fetcher: Fetcher) -> str:
    """Resolve EU's real current seed URL: today's L-series daily issue.

    `direct-access.html` is a static hub page with no real per-document rows
    of its own -- the actual content lives on a dated daily-view page that
    changes every day. This fetches the hub, finds the most recent dated
    L-series link (the hub lists dates newest-first), and returns that as
    the seed URL to actually crawl this cycle.
    """
    result = fetcher.fetch(EU_HUB_URL)
    text = to_text(result.html, base_url=EU_HUB_URL, max_chars=20_000)
    match = _L_SERIES_LINK_RE.search(text)
    if not match:
        raise RuntimeError(f"could not find a daily-view link on {EU_HUB_URL}")
    return match.group(0).strip("()")


SEED_URL_RESOLVERS: dict[str, Callable[[Fetcher], str]] = {
    "eurlex_latest_oj": eurlex_latest_oj,
}


def resolve_seed_url(resolver_name: str, fetcher: Fetcher) -> str:
    resolver = SEED_URL_RESOLVERS.get(resolver_name)
    if resolver is None:
        raise ValueError(f"unknown seed_resolver '{resolver_name}'")
    return resolver(fetcher)
