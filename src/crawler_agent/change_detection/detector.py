from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from crawler_agent.db.models import ChangeEvent, RegulationItem, Site, utcnow
from crawler_agent.extraction.schemas import ExtractedRegulationItem

ClassificationType = Literal["new_item", "updated_item", "unchanged"]


@dataclass
class Classification:
    type: ClassificationType
    regulation_item: RegulationItem


# Fields that represent the actual regulation. Deliberately excludes `summary`:
# it's free-text prose the LLM can reword slightly between identical crawls, and
# hashing it would flag a re-worded-but-unchanged regulation as "updated" every run.
MATERIAL_FIELDS = (
    "title",
    "status",
    "publication_date",
    "effective_date",
    "document_type",
    "document_number",
)


_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_title(title: str) -> str:
    """Collapse whitespace and drop a trailing sentence-final period.

    Source prose sometimes puts a citation at the end of a sentence (e.g.
    "...(OJ L 69, 13.3.2013, p. 1)."), and the LLM inconsistently includes or
    drops that trailing period when copying the title between otherwise
    identical extractions. That alone must not register as the regulation
    having changed.
    """
    collapsed = _WHITESPACE_RE.sub(" ", title).strip()
    return collapsed.rstrip(".")


def _content_hash(item: ExtractedRegulationItem) -> str:
    payload = item.model_dump(mode="json", include=set(MATERIAL_FIELDS))
    payload["title"] = _normalize_title(payload["title"])
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def classify_and_upsert(
    session: Session, site: Site, item: ExtractedRegulationItem
) -> Classification:
    """Compare one extracted item against stored state and persist the result.

    New source_url -> new_item. Known source_url but content changed -> updated_item
    (this is how a regulation moving from "proposed" to "enacted", or a shifted
    effective date, gets surfaced). Otherwise unchanged (last_seen_at still bumped
    so we know the agent is still successfully tracking it).
    """
    content_hash = _content_hash(item)
    existing = session.scalar(
        select(RegulationItem).where(
            RegulationItem.site_id == site.id,
            RegulationItem.source_url == item.url,
        )
    )

    if existing is None:
        record = RegulationItem(
            site_id=site.id,
            source_url=item.url,
            title=item.title,
            summary=item.summary,
            publication_date=item.publication_date,
            effective_date=item.effective_date,
            status=item.status,
            document_type=item.document_type,
            document_number=item.document_number,
            content_hash=content_hash,
            raw_extraction_json=json.dumps(item.model_dump(mode="json")),
        )
        session.add(record)
        session.flush()
        session.add(
            ChangeEvent(
                type="new_item",
                site_id=site.id,
                regulation_item_id=record.id,
                details_json=json.dumps({"title": item.title, "status": item.status}),
            )
        )
        return Classification(type="new_item", regulation_item=record)

    existing.last_seen_at = utcnow()
    if existing.content_hash == content_hash:
        # Material fields are unchanged -- refresh the free-text summary/raw
        # extraction in place (keeps stored text current) without logging a
        # change event or counting it as an update.
        existing.summary = item.summary
        existing.raw_extraction_json = json.dumps(item.model_dump(mode="json"))
        return Classification(type="unchanged", regulation_item=existing)

    details = {
        "title": item.title,
        "old_status": existing.status,
        "new_status": item.status,
        "old_effective_date": str(existing.effective_date) if existing.effective_date else None,
        "new_effective_date": str(item.effective_date) if item.effective_date else None,
    }
    existing.title = item.title
    existing.summary = item.summary
    existing.publication_date = item.publication_date
    existing.effective_date = item.effective_date
    existing.status = item.status
    existing.document_type = item.document_type
    existing.document_number = item.document_number
    existing.content_hash = content_hash
    existing.raw_extraction_json = json.dumps(item.model_dump(mode="json"))
    session.flush()
    session.add(
        ChangeEvent(
            type="updated_item",
            site_id=site.id,
            regulation_item_id=existing.id,
            details_json=json.dumps(details),
        )
    )
    return Classification(type="updated_item", regulation_item=existing)


def upcoming_changes(session: Session, country: str | None = None) -> list[RegulationItem]:
    """Items the agent has deduced are not yet in force: a future effective date,
    or a status that explicitly marks them as proposed/upcoming."""
    today = dt.date.today()
    query = select(RegulationItem).join(Site).where(
        (RegulationItem.effective_date.is_not(None) & (RegulationItem.effective_date > today))
        | RegulationItem.status.in_(["proposed", "upcoming"])
    )
    if country:
        query = query.where(Site.country == country)
    return list(session.scalars(query))
