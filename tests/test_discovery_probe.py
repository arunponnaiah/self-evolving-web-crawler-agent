from crawler_agent.agent.assess import ContentAssessment
from crawler_agent.agent.graph import build_crawl_agent
from crawler_agent.discovery.probe import probe_candidate
from crawler_agent.extraction.schemas import ExtractedRegulationItem, ExtractionResult
from tests.test_agent_graph import FakeFetcher, ScriptedAssessor


class FakeExtractor:
    def __init__(self, items):
        self.items = items

    def extract(self, *, page_text: str, page_url: str) -> ExtractionResult:
        return ExtractionResult(items=self.items)


def make_item(**overrides) -> ExtractedRegulationItem:
    defaults = dict(title="Rule X", url="https://example.gov/doc/1", status="enacted")
    defaults.update(overrides)
    return ExtractedRegulationItem(**defaults)


def test_probe_reports_working_candidate():
    http_fetcher = FakeFetcher(html="<div class='item'>Rule X</div>")
    browser_fetcher = FakeFetcher(html="unused")
    assessor = ScriptedAssessor(
        responses=[ContentAssessment(content_ok=True, action="extract", reason="looks real")]
    )
    agent = build_crawl_agent(
        http_fetcher=http_fetcher,
        browser_fetcher=browser_fetcher,
        assessor=assessor,
        extractor=FakeExtractor([make_item()]),
    )

    result = probe_candidate(agent, "https://example.gov/listing", fetch_mode="http")

    assert result.works is True
    assert result.item_count == 1
    assert result.reason is None


def test_probe_reports_blocked_candidate_as_not_working():
    http_fetcher = FakeFetcher(html="unused")
    browser_fetcher = FakeFetcher(html="<div>CAPTCHA</div>")
    assessor = ScriptedAssessor(
        responses=[ContentAssessment(content_ok=False, action="skip_blocked", reason="captcha wall")]
    )
    agent = build_crawl_agent(
        http_fetcher=http_fetcher,
        browser_fetcher=browser_fetcher,
        assessor=assessor,
        extractor=FakeExtractor([]),
    )

    result = probe_candidate(agent, "https://example.gov/listing", fetch_mode="browser")

    assert result.works is False
    assert result.item_count == 0
    assert result.reason == "captcha wall"


def test_probe_reports_zero_items_as_not_working():
    """Even if the page isn't flagged as blocked, zero extracted items is
    not a working seed -- an empty listing page shouldn't get registered."""
    http_fetcher = FakeFetcher(html="<div>empty listing</div>")
    browser_fetcher = FakeFetcher(html="unused")
    assessor = ScriptedAssessor(
        responses=[ContentAssessment(content_ok=True, action="extract", reason="looks real")]
    )
    agent = build_crawl_agent(
        http_fetcher=http_fetcher,
        browser_fetcher=browser_fetcher,
        assessor=assessor,
        extractor=FakeExtractor([]),
    )

    result = probe_candidate(agent, "https://example.gov/listing", fetch_mode="http")

    assert result.works is False
    assert result.item_count == 0
