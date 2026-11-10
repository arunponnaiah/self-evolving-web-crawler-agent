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

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    detected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    type: Mapped[str] = mapped_column(String(32))  # new_item | updated_item | layout_relearned
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    regulation_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("regulation_items.id"), nullable=True
    )
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
