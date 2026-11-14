from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    country: Mapped[str] = mapped_column(String(64))
    base_url: Mapped[str] = mapped_column(String(512))
    fetch_mode: Mapped[str] = mapped_column(String(16), default="http")
    crawl_interval_hours: Mapped[int] = mapped_column(Integer, default=24)

    layout_versions: Mapped[list["LayoutVersion"]] = relationship(back_populates="site")
    regulation_items: Mapped[list["RegulationItem"]] = relationship(back_populates="site")


class LayoutVersion(Base):
    """A distinct structural fingerprint ever observed for a site.

    A new row here represents the agent "learning" a new page layout.
    """

    __tablename__ = "layout_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    fingerprint_hash: Mapped[str] = mapped_column(String(64), index=True)
    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sample_url: Mapped[str] = mapped_column(String(1024))

    site: Mapped[Site] = relationship(back_populates="layout_versions")

    __table_args__ = (UniqueConstraint("site_id", "fingerprint_hash"),)


class PageSnapshot(Base):
    __tablename__ = "page_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    url: Mapped[str] = mapped_column(String(1024))
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    content_hash: Mapped[str] = mapped_column(String(64))
    layout_version_id: Mapped[int] = mapped_column(ForeignKey("layout_versions.id"))


class RegulationItem(Base):
    __tablename__ = "regulation_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    source_url: Mapped[str] = mapped_column(String(1024), index=True)
    title: Mapped[str] = mapped_column(String(1024))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    effective_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="unknown")
    document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw_extraction_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    site: Mapped[Site] = relationship(back_populates="regulation_items")

    __table_args__ = (UniqueConstraint("site_id", "source_url"),)


class ChangeEvent(Base):
    __tablename__ = "change_events"

    # type values: new_item | updated_item | layout_relearned | access_blocked |
    # seed_url_self_corrected | site_reenabled
    # (SiteProposal and PromptVersion approvals are audited by their own
    # status/reviewed_at fields, not ChangeEvent -- neither has a Site row to
    # attach to at approval time: a proposal's Site doesn't exist until its
    # first crawl, and a prompt isn't tied to any one site at all.)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    detected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    type: Mapped[str] = mapped_column(String(32))
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    regulation_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("regulation_items.id"), nullable=True
    )
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class SummaryFeedback(Base):
    """Human feedback on an extracted summary.

    This is the "self-learning from feedback" mechanism: rows here get read
    back by `feedback/store.py` and spliced into the extraction prompt as
    examples, so accumulated corrections actually change future summaries --
    no fine-tuning required.
    """

    __tablename__ = "summary_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    regulation_item_id: Mapped[int] = mapped_column(
        ForeignKey("regulation_items.id"), index=True
    )
    rating: Mapped[str] = mapped_column(String(8))  # "up" | "down"
    corrected_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SiteProposal(Base):
    """A discovered site candidate awaiting human approval.

    discovery/discover.py creates one of these when it finds a URL that
    passes the domain-authenticity gate and actually extracts real content --
    but it never registers it into sites/registry.yaml itself. Only
    discovery/proposals.py's approve_proposal() does that, and only a human
    calling `crawler-agent approve-site` triggers it.
    """

    __tablename__ = "site_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    country: Mapped[str] = mapped_column(String(64))
    base_url: Mapped[str] = mapped_column(String(512))
    seed_urls_json: Mapped[str] = mapped_column(Text)
    fetch_mode: Mapped[str] = mapped_column(String(16), default="http")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|approved|rejected
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Why the reviewer approved or denied it -- shown in the dashboard's
    # "recent decisions" summary so the reasoning behind a decision isn't lost.
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class PromptVersion(Base):
    """A version of the extraction system prompt (base + feedback splice).

    extraction/prompt_review.py's get_deployed_system_prompt() -- what real
    crawls actually use -- only ever reads the latest row with
    status="approved". build_prompt_draft() creates a "draft" row when
    accumulated feedback would change the prompt; it takes effect only once
    a human approves it via `crawler-agent approve-prompt`.
    """

    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    system_prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|approved|rejected
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
