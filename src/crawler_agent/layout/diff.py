from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from crawler_agent.db.models import LayoutVersion, Site


@dataclass
class LayoutDiffResult:
    layout_version: LayoutVersion
    is_new_layout: bool


def resolve_layout_version(
    session: Session, site: Site, fingerprint_hash: str, sample_url: str
) -> LayoutDiffResult:
    """Look up, or create, the LayoutVersion matching this fingerprint for the site.

    A fingerprint never seen before for this site means the agent has just
    learned a new layout -- the caller should log a `layout_relearned`
    ChangeEvent when `is_new_layout` is True.
    """
    existing = session.scalar(
        select(LayoutVersion).where(
            LayoutVersion.site_id == site.id,
            LayoutVersion.fingerprint_hash == fingerprint_hash,
        )
    )
    if existing is not None:
        return LayoutDiffResult(layout_version=existing, is_new_layout=False)

    new_version = LayoutVersion(
        site_id=site.id, fingerprint_hash=fingerprint_hash, sample_url=sample_url
    )
    session.add(new_version)
    session.flush()
    return LayoutDiffResult(layout_version=new_version, is_new_layout=True)
