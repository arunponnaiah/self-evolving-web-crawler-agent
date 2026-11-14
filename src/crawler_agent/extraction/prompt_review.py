from __future__ import annotations

import difflib

from sqlalchemy import select
from sqlalchemy.orm import Session

from crawler_agent.db.models import PromptVersion, utcnow
from crawler_agent.extraction.prompts import SYSTEM_PROMPT, render_feedback_section
from crawler_agent.feedback.store import recent_feedback_examples


def _latest(session: Session, status: str) -> PromptVersion | None:
    return session.scalar(
        select(PromptVersion)
        .where(PromptVersion.status == status)
        .order_by(PromptVersion.created_at.desc())
    )


def get_deployed_system_prompt(session: Session) -> str:
    """What real crawls actually use -- the latest *approved* prompt, or the
    bare base prompt if nothing has ever been approved. Never reads feedback
    live; a crawl only ever sees feedback that passed through an explicit
    human approval via `approve_draft`."""
    approved = _latest(session, "approved")
    return approved.system_prompt if approved else SYSTEM_PROMPT


def build_prompt_draft(session: Session) -> PromptVersion | None:
    """Compute what the prompt *would* look like with current feedback
    applied, and queue it for review if it differs from what's deployed.

    Replaces any existing pending draft rather than accumulating them, so
    there's only ever at most one draft awaiting a decision at a time.
    Returns None if there's nothing new to review (current feedback already
    matches what's deployed).
    """
    candidate_text = SYSTEM_PROMPT + render_feedback_section(recent_feedback_examples(session))
    if candidate_text == get_deployed_system_prompt(session):
        return None

    existing_draft = _latest(session, "draft")
    if existing_draft is not None:
        existing_draft.system_prompt = candidate_text
        existing_draft.created_at = utcnow()
        session.flush()
        return existing_draft

    draft = PromptVersion(system_prompt=candidate_text, status="draft")
    session.add(draft)
    session.flush()
    return draft


def diff_against_deployed(session: Session, draft: PromptVersion) -> str:
    deployed = get_deployed_system_prompt(session)
    return "\n".join(
        difflib.unified_diff(
            deployed.splitlines(),
            draft.system_prompt.splitlines(),
            fromfile="deployed",
            tofile="draft",
            lineterm="",
        )
    )


def approve_draft(session: Session, draft_id: int, comment: str | None = None) -> PromptVersion:
    draft = session.get(PromptVersion, draft_id)
    if draft is None:
        raise ValueError(f"no prompt draft with id {draft_id}")
    if draft.status != "draft":
        raise ValueError(f"prompt version {draft_id} is already {draft.status}")
    draft.status = "approved"
    draft.reviewed_at = utcnow()
    draft.review_comment = comment
    session.flush()
    return draft


def reject_draft(session: Session, draft_id: int, comment: str | None = None) -> PromptVersion:
    draft = session.get(PromptVersion, draft_id)
    if draft is None:
        raise ValueError(f"no prompt draft with id {draft_id}")
    if draft.status != "draft":
        raise ValueError(f"prompt version {draft_id} is already {draft.status}")
    draft.status = "rejected"
    draft.reviewed_at = utcnow()
    draft.review_comment = comment
    session.flush()
    return draft


def list_reviewed_drafts(session: Session, limit: int = 20) -> list[PromptVersion]:
    """Recently approved/rejected prompt drafts, for the dashboard's decision
    history -- so the reasoning behind a past call isn't lost."""
    return list(
        session.scalars(
            select(PromptVersion)
            .where(PromptVersion.status != "draft")
            .order_by(PromptVersion.reviewed_at.desc())
            .limit(limit)
        )
    )
