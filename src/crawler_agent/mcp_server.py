from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from crawler_agent.change_detection.detector import upcoming_changes
from crawler_agent.db.models import ChangeEvent, LayoutVersion, RegulationItem, Site
from crawler_agent.db.session import get_session
from crawler_agent.sites.loader import REGISTRY_PATH, load_registry

try:
    from mcp.server.mcpserver import MCPServer
except ImportError as exc:  # pragma: no cover - exercised only without the extra installed
    raise ImportError(
        "the 'mcp' package is not installed; install the 'mcp' extra: pip install -e '.[mcp]'"
    ) from exc

server = MCPServer(
    name="regulatory-crawler",
    description=(
        "Read-only access to regulatory items, deduced upcoming changes, and "
        "crawl history collected by the self-evolving regulatory crawler agent. "
        "Does not expose any write/approval action -- site discovery and "
        "feedback-driven prompt changes stay gated behind human approval in "
        "the CLI/dashboard, never reachable through this server."
    ),
)


# --- Serialization helpers -------------------------------------------------


def _isoformat(value: dt.date | dt.datetime | None) -> str | None:
    return value.isoformat() if value else None


def _site_label(session: Session, site_id: int) -> str:
    site = session.get(Site, site_id)
    return site.slug if site else str(site_id)


def _regulation_item_to_dict(session: Session, item: RegulationItem) -> dict:
    return {
        "id": item.id,
        "site": _site_label(session, item.site_id),
        "title": item.title,
        "summary": item.summary,
        "document_number": item.document_number,
        "document_type": item.document_type,
        "status": item.status,
        "publication_date": _isoformat(item.publication_date),
        "effective_date": _isoformat(item.effective_date),
        "source_url": item.source_url,
        "first_seen_at": _isoformat(item.first_seen_at),
        "last_seen_at": _isoformat(item.last_seen_at),
    }


# --- Session-injectable query functions -------------------------------------
# Each takes an explicit `session` so it's directly unit-testable against an
# in-memory DB, same pattern as the rest of this codebase (e.g.
# change_detection.detector, discovery.revalidate). Each `@server.tool()`
# wrapper below just opens a real session and delegates to one of these.


def query_regulation_items(
    session: Session,
    country: str | None = None,
    site: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = 50,
) -> list[RegulationItem]:
    query = select(RegulationItem).join(Site).order_by(RegulationItem.last_seen_at.desc())
    if country:
        query = query.where(Site.country == country)
    if site:
        query = query.where(Site.slug == site)
    if status:
        query = query.where(RegulationItem.status == status)
    if search:
        query = query.where(RegulationItem.title.ilike(f"%{search}%"))
    query = query.limit(limit)
    return list(session.scalars(query))


def query_regulation_item(session: Session, item_id: int) -> RegulationItem | None:
    return session.get(RegulationItem, item_id)


def query_sites(session: Session) -> list[Site]:
    return list(session.scalars(select(Site)))


def sites_to_dicts(session: Session, registry_path=REGISTRY_PATH) -> list[dict]:
    # "enabled" is a registry.yaml concept (SiteConfig.enabled), not a column
    # on the DB's Site row -- the DB only ever records sites that have
    # actually been crawled at least once. Look it up by slug; a DB site no
    # longer present in the registry (removed by hand) reports enabled=None
    # rather than guessing.
    enabled_by_slug = {config.id: config.enabled for config in load_registry(registry_path)}
    return [
        {
            "id": s.id,
            "slug": s.slug,
            "name": s.name,
            "country": s.country,
            "fetch_mode": s.fetch_mode,
            "enabled": enabled_by_slug.get(s.slug),
        }
        for s in query_sites(session)
    ]


def query_layout_events(
    session: Session, site: str | None = None, limit: int = 50
) -> list[LayoutVersion]:
    query = select(LayoutVersion).order_by(LayoutVersion.first_seen_at.desc())
    if site:
        site_row = session.scalar(select(Site).where(Site.slug == site))
        if site_row is None:
            return []
        query = query.where(LayoutVersion.site_id == site_row.id)
    query = query.limit(limit)
    return list(session.scalars(query))


def query_change_events(
    session: Session, site: str | None = None, event_type: str | None = None, limit: int = 50
) -> list[ChangeEvent]:
    query = select(ChangeEvent).order_by(ChangeEvent.detected_at.desc())
    if site:
        site_row = session.scalar(select(Site).where(Site.slug == site))
        if site_row is None:
            return []
        query = query.where(ChangeEvent.site_id == site_row.id)
    if event_type:
        query = query.where(ChangeEvent.type == event_type)
    query = query.limit(limit)
    return list(session.scalars(query))


# --- MCP tools ---------------------------------------------------------------


@server.tool()
def list_regulation_items(
    country: str | None = None,
    site: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List tracked regulatory items, optionally filtered by country code,
    site slug, status (enacted/proposed/upcoming/amended/unknown), or a
    case-insensitive title search. Capped at `limit` (default 50)."""
    with get_session() as session:
        items = query_regulation_items(
            session, country=country, site=site, status=status, search=search, limit=limit
        )
        return [_regulation_item_to_dict(session, item) for item in items]


@server.tool()
def get_regulation_item(item_id: int) -> dict | None:
    """Get full detail for one regulation item by its id, or null if no such
    item exists."""
    with get_session() as session:
        item = query_regulation_item(session, item_id)
        if item is None:
            return None
        return _regulation_item_to_dict(session, item)


@server.tool()
def list_upcoming_changes(country: str | None = None) -> list[dict]:
    """List regulatory items deduced to not yet be in force: a future
    effective date, or an explicit proposed/upcoming status. Optionally
    filter by country code."""
    with get_session() as session:
        items = upcoming_changes(session, country=country)
        return [_regulation_item_to_dict(session, item) for item in items]


@server.tool()
def list_sites() -> list[dict]:
    """List all registered regulatory sites and whether each is currently
    enabled for crawling."""
    with get_session() as session:
        return sites_to_dicts(session)


@server.tool()
def list_layout_events(site: str | None = None, limit: int = 50) -> list[dict]:
    """List the agent's layout-learning history: each row is a distinct
    page-structure fingerprint ever learned for a site. Optionally filter by
    site slug."""
    with get_session() as session:
        return [
            {
                "id": v.id,
                "site": _site_label(session, v.site_id),
                "fingerprint_hash": v.fingerprint_hash,
                "first_seen_at": _isoformat(v.first_seen_at),
                "sample_url": v.sample_url,
            }
            for v in query_layout_events(session, site=site, limit=limit)
        ]


@server.tool()
def list_change_events(
    site: str | None = None, event_type: str | None = None, limit: int = 50
) -> list[dict]:
    """List the general change-event audit log (new/updated regulation
    items, layout changes, access-blocked events, self-corrections).
    Optionally filter by site slug or event type."""
    with get_session() as session:
        return [
            {
                "id": e.id,
                "detected_at": _isoformat(e.detected_at),
                "type": e.type,
                "site": _site_label(session, e.site_id),
                "details": e.details_json,
            }
            for e in query_change_events(session, site=site, event_type=event_type, limit=limit)
        ]


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
