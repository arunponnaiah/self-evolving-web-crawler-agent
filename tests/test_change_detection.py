import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from crawler_agent.change_detection.detector import classify_and_upsert, upcoming_changes
from crawler_agent.db.models import Base, Site
from crawler_agent.extraction.schemas import ExtractedRegulationItem


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    db: Session = SessionLocal()
    yield db
    db.close()


@pytest.fixture
def site(session: Session) -> Site:
    s = Site(slug="test_site", name="Test Site", country="US", base_url="https://example.gov")
    session.add(s)
    session.flush()
    return s


def make_item(**overrides) -> ExtractedRegulationItem:
    defaults = dict(
        title="Rule on Widget Safety",
        url="https://example.gov/doc/1",
        summary="A rule about widgets.",
        publication_date=dt.date(2026, 1, 1),
        effective_date=None,
        status="enacted",
        document_type="rule",
    )
    defaults.update(overrides)
    return ExtractedRegulationItem(**defaults)


def test_first_seen_item_is_new(session: Session, site: Site):
    result = classify_and_upsert(session, site, make_item())
    assert result.type == "new_item"


def test_identical_item_second_time_is_unchanged(session: Session, site: Site):
    classify_and_upsert(session, site, make_item())
    result = classify_and_upsert(session, site, make_item())
    assert result.type == "unchanged"


def test_reworded_summary_alone_is_not_counted_as_updated(session: Session, site: Site):
    """LLM extraction can reword free-text summary slightly between identical
    crawls; that alone must not be treated as the regulation having changed."""
    classify_and_upsert(session, site, make_item(summary="A rule about widgets."))
    result = classify_and_upsert(
        session, site, make_item(summary="This rule concerns widget safety requirements.")
    )
    assert result.type == "unchanged"
    assert result.regulation_item.summary == "This rule concerns widget safety requirements."


def test_trailing_title_punctuation_alone_is_not_counted_as_updated(session: Session, site: Site):
    """Source prose sometimes puts a citation at the end of a sentence, and the
    LLM inconsistently includes/drops the trailing period between identical
    extractions. That alone must not be treated as the regulation changing."""
    classify_and_upsert(session, site, make_item(title="Council Regulation (EU) No 216/2013."))
    result = classify_and_upsert(
        session, site, make_item(title="Council Regulation (EU) No 216/2013")
    )
    assert result.type == "unchanged"


def test_changed_status_is_updated(session: Session, site: Site):
    classify_and_upsert(session, site, make_item(status="proposed"))
    result = classify_and_upsert(session, site, make_item(status="enacted"))
    assert result.type == "updated_item"
    assert result.regulation_item.status == "enacted"


def test_document_number_is_persisted_and_material(session: Session, site: Site):
    """document_number is a verbatim, stable citation -- treated like
    document_type: persisted on first sight, and a genuine change in it
    counts as a real update (e.g. a draft citation replaced by its final one)."""
    result = classify_and_upsert(session, site, make_item(document_number="2026-12345"))
    assert result.regulation_item.document_number == "2026-12345"

    unchanged = classify_and_upsert(session, site, make_item(document_number="2026-12345"))
    assert unchanged.type == "unchanged"

    updated = classify_and_upsert(session, site, make_item(document_number="2026-99999"))
    assert updated.type == "updated_item"
    assert updated.regulation_item.document_number == "2026-99999"


def test_upcoming_changes_surfaces_future_effective_date(session: Session, site: Site):
    future = dt.date.today() + dt.timedelta(days=30)
    classify_and_upsert(
        session,
        site,
        make_item(url="https://example.gov/doc/future", status="enacted", effective_date=future),
    )
    classify_and_upsert(
        session,
        site,
        make_item(url="https://example.gov/doc/past", status="enacted", effective_date=None),
    )
    results = upcoming_changes(session)
    urls = {item.source_url for item in results}
    assert "https://example.gov/doc/future" in urls
    assert "https://example.gov/doc/past" not in urls


def test_upcoming_changes_surfaces_proposed_status_even_without_date(
    session: Session, site: Site
):
    classify_and_upsert(
        session,
        site,
        make_item(url="https://example.gov/doc/proposed", status="proposed", effective_date=None),
    )
    results = upcoming_changes(session)
    urls = {item.source_url for item in results}
    assert "https://example.gov/doc/proposed" in urls
