from dataclasses import dataclass

from crawler_agent.agent.assess import ContentAssessment
from crawler_agent.agent.graph import build_crawl_agent, run_url
from crawler_agent.extraction.schemas import ExtractedRegulationItem, ExtractionResult
from crawler_agent.fetch.base import FetchResult


@dataclass
class FakeFetcher:
    html: str
    status_code: int = 200
    markdown: str | None = None
    raises: Exception | None = None
    calls: int = 0

    def fetch(self, url: str) -> FetchResult:
        self.calls += 1
        if self.raises:
            raise self.raises
        return FetchResult(
            url=url, status_code=self.status_code, html=self.html, markdown=self.markdown
        )


@dataclass
class ScriptedAssessor:
    """Returns a scripted sequence of assessments, one per call."""

    responses: list[ContentAssessment]
    calls: int = 0

    def assess(self, *, page_text: str, page_url: str, fetch_mode: str) -> ContentAssessment:
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


class FakeExtractor:
    def __init__(self, items: list[ExtractedRegulationItem]):
        self.items = items
        self.received_page_text: str | None = None

    def extract(self, *, page_text: str, page_url: str) -> ExtractionResult:
        self.received_page_text = page_text
        return ExtractionResult(items=self.items)


def make_item(**overrides) -> ExtractedRegulationItem:
    defaults = dict(title="Rule X", url="https://example.gov/doc/1", status="enacted")
    defaults.update(overrides)
    return ExtractedRegulationItem(**defaults)


def test_normal_extraction_path():
    http_fetcher = FakeFetcher(html="<div class='item'>Rule X</div>")
    browser_fetcher = FakeFetcher(html="<div>unused</div>")
    assessor = ScriptedAssessor(
        responses=[ContentAssessment(content_ok=True, action="extract", reason="looks real")]
    )
    extractor = FakeExtractor([make_item()])

    agent = build_crawl_agent(
        http_fetcher=http_fetcher, browser_fetcher=browser_fetcher, assessor=assessor, extractor=extractor
    )
    result = run_url(agent, "https://example.gov/listing", fetch_mode="http")

    assert result.status == "extracted"
    assert result.fetch_mode_used == "http"
    assert result.attempts == 1
    assert [i.title for i in result.items] == ["Rule X"]
    assert http_fetcher.calls == 1
    assert browser_fetcher.calls == 0


def test_blocked_with_browser_already_gives_up():
    http_fetcher = FakeFetcher(html="unused")
    browser_fetcher = FakeFetcher(html="<div>Please complete the CAPTCHA</div>")
    assessor = ScriptedAssessor(
        responses=[ContentAssessment(content_ok=False, action="skip_blocked", reason="captcha wall")]
    )
    extractor = FakeExtractor([])

    agent = build_crawl_agent(
        http_fetcher=http_fetcher, browser_fetcher=browser_fetcher, assessor=assessor, extractor=extractor
    )
    result = run_url(agent, "https://example.gov/listing", fetch_mode="browser")

    assert result.status == "blocked"
    assert result.reason == "captcha wall"
    assert browser_fetcher.calls == 1
    assert http_fetcher.calls == 0


def test_http_blocked_escalates_to_browser_and_succeeds():
    http_fetcher = FakeFetcher(html="<div>Request Access - CAPTCHA</div>")
    browser_fetcher = FakeFetcher(html="<div class='item'>Rule X</div>")
    assessor = ScriptedAssessor(
        responses=[
            ContentAssessment(content_ok=False, action="retry_browser", reason="bot check"),
            ContentAssessment(content_ok=True, action="extract", reason="looks real now"),
        ]
    )
    extractor = FakeExtractor([make_item()])

    agent = build_crawl_agent(
        http_fetcher=http_fetcher, browser_fetcher=browser_fetcher, assessor=assessor, extractor=extractor
    )
    result = run_url(agent, "https://example.gov/listing", fetch_mode="http")

    assert result.status == "extracted"
    assert result.fetch_mode_used == "browser"
    assert result.attempts == 2
    assert http_fetcher.calls == 1
    assert browser_fetcher.calls == 1


def test_fetcher_markdown_is_preferred_over_html_cleaning():
    """A fetcher's own markdown (e.g. crawl4ai's pruned output) is only set
    when it demonstrably removed boilerplate the generic HTML cleaner can't --
    extraction must use it directly rather than re-deriving text from raw HTML."""
    http_fetcher = FakeFetcher(
        html="<div class='noise'>lots of chrome</div><div class='item'>Rule X</div>",
        markdown="Rule X (clean, pre-filtered markdown)",
    )
    browser_fetcher = FakeFetcher(html="unused")
    assessor = ScriptedAssessor(
        responses=[ContentAssessment(content_ok=True, action="extract", reason="looks real")]
    )
    extractor = FakeExtractor([make_item()])

    agent = build_crawl_agent(
        http_fetcher=http_fetcher, browser_fetcher=browser_fetcher, assessor=assessor, extractor=extractor
    )
    result = run_url(agent, "https://example.gov/listing", fetch_mode="http")

    assert result.status == "extracted"
    assert extractor.received_page_text == "Rule X (clean, pre-filtered markdown)"


def test_fetch_exception_is_treated_as_blocked_not_a_crash():
    http_fetcher = FakeFetcher(html="", raises=RuntimeError("robots.txt disallows this URL"))
    browser_fetcher = FakeFetcher(html="unused")
    assessor = ScriptedAssessor(responses=[ContentAssessment(content_ok=False, action="skip_blocked", reason="n/a")])
    extractor = FakeExtractor([])

    agent = build_crawl_agent(
        http_fetcher=http_fetcher, browser_fetcher=browser_fetcher, assessor=assessor, extractor=extractor
    )
    result = run_url(agent, "https://example.gov/listing", fetch_mode="http")

    assert result.status in ("blocked", "error")
    assert "robots.txt" in (result.reason or "")
