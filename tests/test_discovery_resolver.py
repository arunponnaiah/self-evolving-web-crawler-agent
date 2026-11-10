from pathlib import Path

import pytest

from crawler_agent.discovery.resolver import eurlex_latest_oj
from crawler_agent.fetch.base import FetchResult

FIXTURES = Path(__file__).parent / "fixtures"


class FakeFetcher:
    def __init__(self, html: str):
        self.html = html

    def fetch(self, url: str) -> FetchResult:
        return FetchResult(url=url, status_code=200, html=self.html)


def test_resolves_most_recent_l_series_link():
    html = (FIXTURES / "eurlex_hub_sample.html").read_text()
    resolved = eurlex_latest_oj(FakeFetcher(html))
    assert resolved == (
        "https://eur-lex.europa.eu/oj/daily-view/L-series/default.html?&ojDate=10112026"
    )


def test_raises_if_no_daily_view_link_found():
    with pytest.raises(RuntimeError):
        eurlex_latest_oj(FakeFetcher("<html><body>nothing here</body></html>"))
