import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from crawler_agent.change_detection.detector import classify_and_upsert
from crawler_agent.db.models import Base, Site
from crawler_agent.extraction.schemas import ExtractedRegulationItem
from crawler_agent.feedback.store import record_feedback, recent_feedback_examples


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


@pytest.fixture
def regulation_item(session: Session, site: Site):
    item = ExtractedRegulationItem(
        title="Rule on Widget Safety",
        url="https://example.gov/doc/1",
        summary="A rule about widgets.",
        status="enacted",
    )
    result = classify_and_upsert(session, site, item)
    return result.regulation_item


def test_record_feedback_rejects_invalid_rating(session: Session, regulation_item):
    with pytest.raises(ValueError):
        record_feedback(session, regulation_item.id, rating="sideways")


def test_plain_thumbs_up_is_not_a_feedback_example(session: Session, regulation_item):
    """A bare 'up' with no comment/correction has nothing to teach -- it
    should not clutter the prompt as an 'example' with no corrective signal."""
    record_feedback(session, regulation_item.id, rating="up")
    examples = recent_feedback_examples(session)
    assert examples == []


def test_corrected_summary_is_a_feedback_example(session: Session, regulation_item):
    record_feedback(
        session,
        regulation_item.id,
        rating="down",
        corrected_summary="This rule requires widget manufacturers to use safety labels.",
        comment="too vague",
    )
    examples = recent_feedback_examples(session)
    assert len(examples) == 1
    assert examples[0].original_summary == "A rule about widgets."
    assert examples[0].corrected_summary == "This rule requires widget manufacturers to use safety labels."
    assert examples[0].comment == "too vague"


def test_down_rating_with_comment_but_no_correction_is_a_feedback_example(
    session: Session, regulation_item
):
    record_feedback(session, regulation_item.id, rating="down", comment="missed the key requirement")
    examples = recent_feedback_examples(session)
    assert len(examples) == 1
    assert examples[0].corrected_summary is None
    assert examples[0].comment == "missed the key requirement"


def test_down_rating_with_no_comment_is_not_a_feedback_example(session: Session, regulation_item):
    record_feedback(session, regulation_item.id, rating="down")
    examples = recent_feedback_examples(session)
    assert examples == []


def test_recent_feedback_examples_respects_limit(session: Session, regulation_item):
    for i in range(15):
        record_feedback(session, regulation_item.id, rating="down", comment=f"issue {i}")
    examples = recent_feedback_examples(session, limit=5)
    assert len(examples) == 5
