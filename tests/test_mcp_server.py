import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from crawler_agent.change_detection.detector import classify_and_upsert
from crawler_agent.db.models import Base, ChangeEvent, LayoutVersion, Site
from crawler_agent.extraction.schemas import ExtractedRegulationItem
from crawler_agent.mcp_server import (
    _regulation_item_to_dict,
    _site_label,
    query_change_events,
    query_layout_events,
    query_regulation_item,
    query_regulation_items,
    query_sites,
    sites_to_dicts,
)
from crawler_agent.sites.loader import SiteConfig, append_site


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
def other_country_site(session: Session) -> Site:
    s = Site(slug="other_site", name="Other Site", country="GB", base_url="https://example.gov.uk")
    session.add(s)
    session.flush()
    return s


def make_item(**overrides) -> ExtractedRegulationItem:
    defaults = dict(
        title="Rule on Widget Safety",
        url="https://example.gov/doc/1",
        summary="A rule about widgets.",
        publication_date=dt.date(2026, 1, 1),
        status="enacted",
        document_type="rule",
    )
    defaults.update(overrides)
    return ExtractedRegulationItem(**defaults)


def test_query_regulation_items_filters_by_country(session: Session, site: Site, other_country_site: Site):
    classify_and_upsert(session, site, make_item(url="https://example.gov/doc/1"))
    classify_and_upsert(session, other_country_site, make_item(url="https://example.gov.uk/doc/1"))

    results = query_regulation_items(session, country="US")

    assert len(results) == 1
    assert results[0].source_url == "https://example.gov/doc/1"


def test_query_regulation_items_filters_by_site(session: Session, site: Site, other_country_site: Site):
    classify_and_upsert(session, site, make_item(url="https://example.gov/doc/1"))
    classify_and_upsert(session, other_country_site, make_item(url="https://example.gov.uk/doc/1"))

    results = query_regulation_items(session, site="other_site")

    assert len(results) == 1
    assert results[0].source_url == "https://example.gov.uk/doc/1"


def test_query_regulation_items_filters_by_status(session: Session, site: Site):
    classify_and_upsert(session, site, make_item(url="https://example.gov/doc/1", status="enacted"))
    classify_and_upsert(session, site, make_item(url="https://example.gov/doc/2", status="proposed"))

    results = query_regulation_items(session, status="proposed")

    assert len(results) == 1
    assert results[0].status == "proposed"


def test_query_regulation_items_search_is_case_insensitive(session: Session, site: Site):
    classify_and_upsert(session, site, make_item(url="https://example.gov/doc/1", title="Widget Safety Rule"))
    classify_and_upsert(session, site, make_item(url="https://example.gov/doc/2", title="Unrelated Thing"))

    results = query_regulation_items(session, search="widget")

    assert len(results) == 1
    assert results[0].title == "Widget Safety Rule"


def test_query_regulation_items_respects_limit(session: Session, site: Site):
    for i in range(5):
        classify_and_upsert(session, site, make_item(url=f"https://example.gov/doc/{i}"))

    results = query_regulation_items(session, limit=2)

    assert len(results) == 2


def test_query_regulation_item_returns_none_for_unknown_id(session: Session):
    assert query_regulation_item(session, 99999) is None


def test_query_regulation_item_returns_the_item(session: Session, site: Site):
    result = classify_and_upsert(session, site, make_item())
    item_id = result.regulation_item.id

    found = query_regulation_item(session, item_id)

    assert found is not None
    assert found.id == item_id


def test_regulation_item_to_dict_serializes_dates_and_site_slug(session: Session, site: Site):
    result = classify_and_upsert(session, site, make_item())

    data = _regulation_item_to_dict(session, result.regulation_item)

    assert data["site"] == "test_site"
    assert data["publication_date"] == "2026-01-01"
    assert data["title"] == "Rule on Widget Safety"


def test_query_sites_returns_all(session: Session, site: Site, other_country_site: Site):
    results = query_sites(session)
    assert {s.slug for s in results} == {"test_site", "other_site"}


def test_sites_to_dicts_looks_up_enabled_from_registry_not_db(session: Session, site: Site, tmp_path):
    """Site (the DB model) has no 'enabled' column -- it's a registry.yaml
    concept (SiteConfig.enabled). This locks in a real bug found via live
    testing: list_sites previously assumed `Site.enabled` existed and the
    tool crashed on every call."""
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text("[]")
    append_site(
        SiteConfig(
            id="test_site", name="Test Site", country="US", base_url="https://example.gov",
            enabled=False,
        ),
        path=registry_path,
    )

    results = sites_to_dicts(session, registry_path=registry_path)

    assert len(results) == 1
    assert results[0]["slug"] == "test_site"
    assert results[0]["enabled"] is False


def test_sites_to_dicts_reports_none_when_site_missing_from_registry(
    session: Session, site: Site, tmp_path
):
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text("[]")

    results = sites_to_dicts(session, registry_path=registry_path)

    assert results[0]["enabled"] is None


def test_site_label_falls_back_to_id_for_unknown_site(session: Session):
    assert _site_label(session, 99999) == "99999"


def test_query_layout_events_filters_by_site(session: Session, site: Site, other_country_site: Site):
    session.add(LayoutVersion(site_id=site.id, fingerprint_hash="abc", sample_url="https://x"))
    session.add(LayoutVersion(site_id=other_country_site.id, fingerprint_hash="def", sample_url="https://y"))
    session.flush()

    results = query_layout_events(session, site="test_site")

    assert len(results) == 1
    assert results[0].fingerprint_hash == "abc"


def test_query_layout_events_unknown_site_returns_empty(session: Session):
    assert query_layout_events(session, site="nonexistent") == []


def test_query_change_events_filters_by_type(session: Session, site: Site):
    session.add(ChangeEvent(type="layout_relearned", site_id=site.id))
    session.add(ChangeEvent(type="access_blocked", site_id=site.id))
    session.flush()

    results = query_change_events(session, event_type="access_blocked")

    assert len(results) == 1
    assert results[0].type == "access_blocked"


def test_query_change_events_respects_limit(session: Session, site: Site):
    for _ in range(5):
        session.add(ChangeEvent(type="layout_relearned", site_id=site.id))
    session.flush()

    results = query_change_events(session, limit=2)

    assert len(results) == 2
