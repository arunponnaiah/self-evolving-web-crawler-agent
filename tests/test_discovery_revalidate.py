import pytest
import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from crawler_agent.agent.assess import ContentAssessment
from crawler_agent.agent.graph import build_crawl_agent
from crawler_agent.db.models import Base, ChangeEvent, Site
from crawler_agent.discovery.revalidate import revalidate_all
from crawler_agent.extraction.schemas import ExtractedRegulationItem, ExtractionResult
from crawler_agent.sites.loader import SiteConfig
from tests.test_agent_graph import FakeFetcher, ScriptedAssessor


class FakeExtractor:
    def __init__(self, items):
        self.items = items

    def extract(self, *, page_text: str, page_url: str) -> ExtractionResult:
        return ExtractionResult(items=self.items)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    db: Session = SessionLocal()
    yield db
    db.close()


@pytest.fixture
def disabled_site_db_row(session: Session) -> Site:
    site = Site(
        slug="test_disabled_site",
        name="Test Disabled Site",
        country="US",
        base_url="https://example.gov",
        fetch_mode="http",
    )
    session.add(site)
    session.flush()
    return site


def write_registry(tmp_path, enabled: bool):
    path = tmp_path / "registry.yaml"
    config = SiteConfig(
        id="test_disabled_site",
        name="Test Disabled Site",
        country="US",
        base_url="https://example.gov",
        seed_urls=["https://example.gov/listing"],
        fetch_mode="http",
        enabled=enabled,
    )
    path.write_text(yaml.safe_dump([config.model_dump()]))
    return path


def working_agent():
    http_fetcher = FakeFetcher(html="<div class='item'>Rule X</div>")
    browser_fetcher = FakeFetcher(html="unused")
    assessor = ScriptedAssessor(
        responses=[ContentAssessment(content_ok=True, action="extract", reason="looks real")]
    )
    return build_crawl_agent(
        http_fetcher=http_fetcher,
        browser_fetcher=browser_fetcher,
        assessor=assessor,
        extractor=FakeExtractor(
            [ExtractedRegulationItem(title="Rule X", url="https://example.gov/doc/1", status="enacted")]
        ),
    )


def broken_agent():
    http_fetcher = FakeFetcher(html="<div>still blocked</div>")
    browser_fetcher = FakeFetcher(html="unused")
    assessor = ScriptedAssessor(
        responses=[ContentAssessment(content_ok=False, action="skip_blocked", reason="still blocked")]
    )
    return build_crawl_agent(
        http_fetcher=http_fetcher,
        browser_fetcher=browser_fetcher,
        assessor=assessor,
        extractor=FakeExtractor([]),
    )


def test_disabled_site_auto_reenabled_when_probe_succeeds(
    tmp_path, session: Session, disabled_site_db_row: Site
):
    registry_path = write_registry(tmp_path, enabled=False)

    results = revalidate_all(session, agent=working_agent(), registry_path=registry_path)

    assert len(results) == 1
    assert results[0].reenabled is True
    assert results[0].was_disabled is True

    persisted = yaml.safe_load(registry_path.read_text())
    assert persisted[0]["enabled"] is True

    events = session.scalars(
        select(ChangeEvent).where(ChangeEvent.type == "site_reenabled")
    ).all()
    assert len(events) == 1
    assert events[0].site_id == disabled_site_db_row.id


def test_disabled_site_stays_disabled_when_still_blocked(
    tmp_path, session: Session, disabled_site_db_row: Site
):
    registry_path = write_registry(tmp_path, enabled=False)

    results = revalidate_all(session, agent=broken_agent(), registry_path=registry_path)

    assert results[0].reenabled is False
    assert results[0].still_working is False

    persisted = yaml.safe_load(registry_path.read_text())
    assert persisted[0]["enabled"] is False

    events = session.scalars(
        select(ChangeEvent).where(ChangeEvent.type == "site_reenabled")
    ).all()
    assert events == []
