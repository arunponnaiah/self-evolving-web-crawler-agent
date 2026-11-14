import pytest
import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from crawler_agent.agent.assess import ContentAssessment
from crawler_agent.agent.graph import build_crawl_agent
from crawler_agent.db.models import Base, SiteProposal
from crawler_agent.discovery.candidate_suggester import CandidateSuggestion, CandidateSuggestions
from crawler_agent.discovery.discover import discover_site
from crawler_agent.discovery.proposals import (
    approve_proposal,
    create_proposal,
    list_pending_proposals,
    list_reviewed_proposals,
    reject_proposal,
)
from crawler_agent.extraction.schemas import ExtractedRegulationItem, ExtractionResult
from crawler_agent.sites.loader import load_registry
from tests.test_agent_graph import FakeFetcher, ScriptedAssessor


class FakeExtractor:
    def __init__(self, items):
        self.items = items

    def extract(self, *, page_text: str, page_url: str) -> ExtractionResult:
        return ExtractionResult(items=self.items)


class FakeSuggester:
    def __init__(self, urls: list[str]):
        self.urls = urls

    def suggest(self, *, country: str) -> CandidateSuggestions:
        return CandidateSuggestions(
            candidates=[CandidateSuggestion(url=u, reason="test") for u in self.urls]
        )


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    db: Session = SessionLocal()
    yield db
    db.close()


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


def test_discover_site_creates_pending_proposal_not_a_registry_write(session: Session, tmp_path):
    suggester = FakeSuggester(["https://example.gov/listing"])

    report = discover_site(session, "US", suggester=suggester, agent=working_agent())

    assert report.proposal_id is not None
    proposal = session.get(SiteProposal, report.proposal_id)
    assert proposal.status == "pending"
    assert proposal.base_url == "https://example.gov/listing"


def test_discover_site_rejects_unauthentic_domain_without_fetching():
    suggester = FakeSuggester(["https://totally-fake-gov-lookalike.com/listing"])

    class ExplodingFetcher:
        def fetch(self, url: str):
            raise AssertionError("should never fetch an unauthentic domain")

    from crawler_agent.agent.graph import build_crawl_agent as _build

    agent = _build(
        http_fetcher=ExplodingFetcher(),
        browser_fetcher=ExplodingFetcher(),
        assessor=ScriptedAssessor(responses=[]),
        extractor=FakeExtractor([]),
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    report = discover_site(session, "US", suggester=suggester, agent=agent)

    assert report.proposal_id is None
    assert "https://totally-fake-gov-lookalike.com/listing" in report.rejected_unauthentic


def test_approve_proposal_registers_into_real_registry_file(session: Session, tmp_path):
    proposal = create_proposal(
        session,
        slug="test_new_site",
        name="Test New Site",
        country="US",
        base_url="https://example.gov",
        seed_urls=["https://example.gov/listing"],
        fetch_mode="http",
    )
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(yaml.safe_dump([]))

    approve_proposal(session, proposal.id, registry_path=registry_path)

    assert proposal.status == "approved"
    registered = load_registry(path=registry_path)
    assert len(registered) == 1
    assert registered[0].id == "test_new_site"


def test_reject_proposal_never_touches_registry(session: Session, tmp_path):
    proposal = create_proposal(
        session,
        slug="test_new_site",
        name="Test New Site",
        country="US",
        base_url="https://example.gov",
        seed_urls=["https://example.gov/listing"],
        fetch_mode="http",
    )
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(yaml.safe_dump([]))

    reject_proposal(session, proposal.id)

    assert proposal.status == "rejected"
    assert load_registry(path=registry_path) == []


def test_list_pending_proposals_excludes_reviewed_ones(session: Session):
    p1 = create_proposal(
        session, slug="a", name="A", country="US", base_url="https://a.gov",
        seed_urls=["https://a.gov"], fetch_mode="http",
    )
    create_proposal(
        session, slug="b", name="B", country="US", base_url="https://b.gov",
        seed_urls=["https://b.gov"], fetch_mode="http",
    )
    reject_proposal(session, p1.id)

    pending = list_pending_proposals(session)
    assert len(pending) == 1
    assert pending[0].slug == "b"


def test_approving_already_reviewed_proposal_raises(session: Session, tmp_path):
    proposal = create_proposal(
        session, slug="a", name="A", country="US", base_url="https://a.gov",
        seed_urls=["https://a.gov"], fetch_mode="http",
    )
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(yaml.safe_dump([]))
    reject_proposal(session, proposal.id)

    with pytest.raises(ValueError):
        approve_proposal(session, proposal.id, registry_path=registry_path)


def test_approve_records_feedback_comment(session: Session, tmp_path):
    proposal = create_proposal(
        session, slug="a", name="A", country="US", base_url="https://a.gov",
        seed_urls=["https://a.gov"], fetch_mode="http",
    )
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(yaml.safe_dump([]))

    approve_proposal(session, proposal.id, registry_path=registry_path, comment="looks legit")

    assert proposal.review_comment == "looks legit"


def test_reject_records_feedback_comment(session: Session):
    proposal = create_proposal(
        session, slug="a", name="A", country="US", base_url="https://a.gov",
        seed_urls=["https://a.gov"], fetch_mode="http",
    )

    reject_proposal(session, proposal.id, comment="wrong country's gazette")

    assert proposal.review_comment == "wrong country's gazette"


def test_list_reviewed_proposals_excludes_pending_and_includes_comment(session: Session, tmp_path):
    pending = create_proposal(
        session, slug="pending", name="Pending", country="US", base_url="https://p.gov",
        seed_urls=["https://p.gov"], fetch_mode="http",
    )
    approved = create_proposal(
        session, slug="approved", name="Approved", country="US", base_url="https://a.gov",
        seed_urls=["https://a.gov"], fetch_mode="http",
    )
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(yaml.safe_dump([]))
    approve_proposal(session, approved.id, registry_path=registry_path, comment="good find")

    reviewed = list_reviewed_proposals(session)

    assert pending.id not in [p.id for p in reviewed]
    assert len(reviewed) == 1
    assert reviewed[0].review_comment == "good find"
