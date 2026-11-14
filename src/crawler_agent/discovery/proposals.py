from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from crawler_agent.db.models import SiteProposal, utcnow
from crawler_agent.sites.loader import REGISTRY_PATH, SiteConfig, append_site


def create_proposal(
    session: Session,
    slug: str,
    name: str,
    country: str,
    base_url: str,
    seed_urls: list[str],
    fetch_mode: str,
) -> SiteProposal:
    proposal = SiteProposal(
        slug=slug,
        name=name,
        country=country,
        base_url=base_url,
        seed_urls_json=json.dumps(seed_urls),
        fetch_mode=fetch_mode,
        status="pending",
    )
    session.add(proposal)
    session.flush()
    return proposal


def list_pending_proposals(session: Session) -> list[SiteProposal]:
    return list(
        session.scalars(
            select(SiteProposal)
            .where(SiteProposal.status == "pending")
            .order_by(SiteProposal.created_at.desc())
        )
    )


def approve_proposal(
    session: Session,
    proposal_id: int,
    registry_path: Path = REGISTRY_PATH,
    comment: str | None = None,
) -> SiteProposal:
    """The only path that ever registers a discovered site -- requires an
    explicit human decision, never automatic."""
    proposal = session.get(SiteProposal, proposal_id)
    if proposal is None:
        raise ValueError(f"no proposal with id {proposal_id}")
    if proposal.status != "pending":
        raise ValueError(f"proposal {proposal_id} is already {proposal.status}")

    append_site(
        SiteConfig(
            id=proposal.slug,
            name=proposal.name,
            country=proposal.country,
            base_url=proposal.base_url,
            seed_urls=json.loads(proposal.seed_urls_json),
            fetch_mode=proposal.fetch_mode,
        ),
        path=registry_path,
    )
    proposal.status = "approved"
    proposal.reviewed_at = utcnow()
    proposal.review_comment = comment
    session.flush()
    return proposal


def reject_proposal(
    session: Session, proposal_id: int, comment: str | None = None
) -> SiteProposal:
    proposal = session.get(SiteProposal, proposal_id)
    if proposal is None:
        raise ValueError(f"no proposal with id {proposal_id}")
    if proposal.status != "pending":
        raise ValueError(f"proposal {proposal_id} is already {proposal.status}")
    proposal.status = "rejected"
    proposal.reviewed_at = utcnow()
    proposal.review_comment = comment
    session.flush()
    return proposal


def list_reviewed_proposals(session: Session, limit: int = 20) -> list[SiteProposal]:
    """Recently approved/rejected proposals, for the dashboard's decision
    history -- so the reasoning behind a past call isn't lost."""
    return list(
        session.scalars(
            select(SiteProposal)
            .where(SiteProposal.status != "pending")
            .order_by(SiteProposal.reviewed_at.desc())
            .limit(limit)
        )
    )
