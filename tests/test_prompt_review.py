import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from crawler_agent.change_detection.detector import classify_and_upsert
from crawler_agent.db.models import Base, PromptVersion, Site
from crawler_agent.extraction.prompts import SYSTEM_PROMPT
from crawler_agent.extraction.prompt_review import (
    approve_draft,
    build_prompt_draft,
    diff_against_deployed,
    get_deployed_system_prompt,
    list_reviewed_drafts,
    reject_draft,
)
from crawler_agent.extraction.schemas import ExtractedRegulationItem
from crawler_agent.feedback.store import record_feedback


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    db: Session = SessionLocal()
    yield db
    db.close()


@pytest.fixture
def regulation_item(session: Session):
    site = Site(slug="test_site", name="Test Site", country="US", base_url="https://example.gov")
    session.add(site)
    session.flush()
    item = ExtractedRegulationItem(
        title="Rule on Widget Safety",
        url="https://example.gov/doc/1",
        summary="A rule about widgets.",
        status="enacted",
    )
    result = classify_and_upsert(session, site, item)
    return result.regulation_item


def give_corrective_feedback(session: Session, regulation_item) -> None:
    record_feedback(
        session,
        regulation_item.id,
        rating="down",
        corrected_summary="This rule requires safety labels on widgets.",
        comment="too vague",
    )


def test_deployed_prompt_is_base_prompt_with_nothing_approved(session: Session):
    assert get_deployed_system_prompt(session) == SYSTEM_PROMPT


def test_no_feedback_means_no_draft(session: Session):
    assert build_prompt_draft(session) is None


def test_feedback_produces_a_draft_not_an_immediate_change(session: Session, regulation_item):
    give_corrective_feedback(session, regulation_item)

    draft = build_prompt_draft(session)

    assert draft is not None
    assert draft.status == "draft"
    assert "too vague" in draft.system_prompt
    # Crucially: the deployed prompt (what crawls use) is UNCHANGED.
    assert get_deployed_system_prompt(session) == SYSTEM_PROMPT


def test_approving_draft_deploys_it(session: Session, regulation_item):
    give_corrective_feedback(session, regulation_item)
    draft = build_prompt_draft(session)

    approve_draft(session, draft.id)

    assert get_deployed_system_prompt(session) == draft.system_prompt
    assert "too vague" in get_deployed_system_prompt(session)


def test_rejecting_draft_leaves_deployed_prompt_unchanged(session: Session, regulation_item):
    give_corrective_feedback(session, regulation_item)
    draft = build_prompt_draft(session)

    reject_draft(session, draft.id)

    assert get_deployed_system_prompt(session) == SYSTEM_PROMPT


def test_rebuilding_draft_replaces_existing_pending_one(session: Session, regulation_item):
    give_corrective_feedback(session, regulation_item)
    first_draft = build_prompt_draft(session)

    record_feedback(session, regulation_item.id, rating="down", comment="also missed the deadline")
    second_draft = build_prompt_draft(session)

    assert second_draft.id == first_draft.id  # same row, updated in place
    assert "also missed the deadline" in second_draft.system_prompt
    all_drafts = session.scalars(
        select(PromptVersion).where(PromptVersion.status == "draft")
    ).all()
    assert len(all_drafts) == 1


def test_diff_shows_the_feedback_addition(session: Session, regulation_item):
    give_corrective_feedback(session, regulation_item)
    draft = build_prompt_draft(session)

    diff = diff_against_deployed(session, draft)

    assert "too vague" in diff
    assert diff.strip() != ""


def test_approving_already_reviewed_draft_raises(session: Session, regulation_item):
    give_corrective_feedback(session, regulation_item)
    draft = build_prompt_draft(session)
    approve_draft(session, draft.id)

    with pytest.raises(ValueError):
        approve_draft(session, draft.id)


def test_approve_records_feedback_comment(session: Session, regulation_item):
    give_corrective_feedback(session, regulation_item)
    draft = build_prompt_draft(session)

    approve_draft(session, draft.id, comment="good catch, deploying")

    assert draft.review_comment == "good catch, deploying"


def test_reject_records_feedback_comment(session: Session, regulation_item):
    give_corrective_feedback(session, regulation_item)
    draft = build_prompt_draft(session)

    reject_draft(session, draft.id, comment="too narrow a fix, want more examples first")

    assert draft.review_comment == "too narrow a fix, want more examples first"


def test_list_reviewed_drafts_excludes_pending_draft(session: Session, regulation_item):
    give_corrective_feedback(session, regulation_item)
    draft = build_prompt_draft(session)
    approve_draft(session, draft.id, comment="deployed")

    reviewed = list_reviewed_drafts(session)

    assert len(reviewed) == 1
    assert reviewed[0].review_comment == "deployed"


def test_list_reviewed_drafts_empty_when_only_a_pending_draft_exists(
    session: Session, regulation_item
):
    give_corrective_feedback(session, regulation_item)
    build_prompt_draft(session)

    assert list_reviewed_drafts(session) == []
