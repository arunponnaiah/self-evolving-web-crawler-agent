from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from crawler_agent.db.models import RegulationItem, SummaryFeedback


@dataclass
class FeedbackExample:
    original_summary: str
    corrected_summary: str | None
    comment: str | None
    rating: str


def record_feedback(
    session: Session,
    regulation_item_id: int,
    rating: str,
    corrected_summary: str | None = None,
    comment: str | None = None,
) -> SummaryFeedback:
    if rating not in ("up", "down"):
        raise ValueError(f"rating must be 'up' or 'down', got {rating!r}")
    feedback = SummaryFeedback(
        regulation_item_id=regulation_item_id,
        rating=rating,
        corrected_summary=corrected_summary,
        comment=comment,
    )
    session.add(feedback)
    session.flush()
    return feedback


def recent_feedback_examples(session: Session, limit: int = 10) -> list[FeedbackExample]:
    """The examples worth splicing into the extraction prompt.

    Prioritizes rows that carry an actual corrective signal -- an explicit
    before/after rewrite, or a "down" rating with a comment explaining what
    was wrong -- over plain thumbs-up, which say nothing about how to
    improve. A bare "up" with no comment is not returned as an example: it
    has nothing to teach the model to do differently.
    """
    rows = session.scalars(
        select(SummaryFeedback)
        .where(
            (SummaryFeedback.corrected_summary.is_not(None))
            | ((SummaryFeedback.rating == "down") & (SummaryFeedback.comment.is_not(None)))
        )
        .order_by(SummaryFeedback.created_at.desc())
        .limit(limit)
    ).all()

    item_by_id = {
        item.id: item
        for item in session.scalars(
            select(RegulationItem).where(
                RegulationItem.id.in_([r.regulation_item_id for r in rows])
            )
        ).all()
    }

    examples = []
    for row in rows:
        item = item_by_id.get(row.regulation_item_id)
        original = item.summary if item else ""
        examples.append(
            FeedbackExample(
                original_summary=original or "",
                corrected_summary=row.corrected_summary,
                comment=row.comment,
                rating=row.rating,
            )
        )
    return examples
