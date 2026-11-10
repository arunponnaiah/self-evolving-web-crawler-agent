from __future__ import annotations

import json

import pandas as pd
import streamlit as st
from sqlalchemy import select

from crawler_agent.change_detection.detector import upcoming_changes
from crawler_agent.db.models import ChangeEvent, RegulationItem, Site
from crawler_agent.db.session import get_session

st.set_page_config(page_title="Regulatory Crawler Agent", layout="wide")
st.title("Self-Evolving Regulatory Crawler Agent")


@st.cache_data(ttl=10)
def load_sites() -> pd.DataFrame:
    with get_session() as session:
        rows = session.scalars(select(Site)).all()
        return pd.DataFrame(
            [
                {
                    "id": s.id,
                    "slug": s.slug,
                    "name": s.name,
                    "country": s.country,
                    "fetch_mode": s.fetch_mode,
                }
                for s in rows
            ]
        )


REGULATION_ITEM_COLUMNS = [
    "site",
    "country",
    "title",
    "document_number",
    "status",
    "document_type",
    "publication_date",
    "effective_date",
    "source_url",
    "summary",
    "first_seen_at",
    "last_seen_at",
]


@st.cache_data(ttl=10)
def load_regulation_items() -> pd.DataFrame:
    with get_session() as session:
        rows = session.scalars(
            select(RegulationItem).order_by(RegulationItem.last_seen_at.desc())
        ).all()
        site_by_id = {s.id: s for s in session.scalars(select(Site)).all()}
        # Always declare columns, even with zero rows: pd.DataFrame([]) has no
        # columns at all, and a later `df["site"]` filter would raise KeyError
        # once a filter (country/site/status) narrows the result to nothing.
        return pd.DataFrame(
            [
                {
                    "site": site_by_id[r.site_id].slug if r.site_id in site_by_id else r.site_id,
                    "country": site_by_id[r.site_id].country if r.site_id in site_by_id else None,
                    "title": r.title,
                    "document_number": r.document_number,
                    "status": r.status,
                    "document_type": r.document_type,
                    "publication_date": r.publication_date,
                    "effective_date": r.effective_date,
                    "source_url": r.source_url,
                    "summary": r.summary,
                    "first_seen_at": r.first_seen_at,
                    "last_seen_at": r.last_seen_at,
                }
                for r in rows
            ],
            columns=REGULATION_ITEM_COLUMNS,
        )


@st.cache_data(ttl=10)
def load_change_events() -> pd.DataFrame:
    with get_session() as session:
        rows = session.scalars(
            select(ChangeEvent).order_by(ChangeEvent.detected_at.desc()).limit(500)
        ).all()
        site_by_id = {s.id: s for s in session.scalars(select(Site)).all()}
        records = []
        for e in rows:
            details = {}
            if e.details_json:
                try:
                    details = json.loads(e.details_json)
                except json.JSONDecodeError:
                    details = {"raw": e.details_json}
            records.append(
                {
                    "detected_at": e.detected_at,
                    "site": site_by_id[e.site_id].slug if e.site_id in site_by_id else e.site_id,
                    "type": e.type,
                    "details": details,
                }
            )
        return pd.DataFrame(records, columns=["detected_at", "site", "type", "details"])


UPCOMING_COLUMNS = [
    "site",
    "country",
    "title",
    "document_number",
    "status",
    "effective_date",
    "publication_date",
    "summary",
    "source_url",
]


@st.cache_data(ttl=10)
def load_upcoming(country: str | None) -> pd.DataFrame:
    with get_session() as session:
        rows = upcoming_changes(session, country=country or None)
        site_by_id = {s.id: s for s in session.scalars(select(Site)).all()}
        return pd.DataFrame(
            [
                {
                    "site": site_by_id[r.site_id].slug if r.site_id in site_by_id else r.site_id,
                    "country": site_by_id[r.site_id].country if r.site_id in site_by_id else None,
                    "title": r.title,
                    "document_number": r.document_number,
                    "status": r.status,
                    "effective_date": r.effective_date,
                    "publication_date": r.publication_date,
                    "summary": r.summary,
                    "source_url": r.source_url,
                }
                for r in rows
            ],
            columns=UPCOMING_COLUMNS,
        )


sites_df = load_sites()

if sites_df.empty:
    st.info("No sites found. Run `crawler-agent init-db` and `crawler-agent crawl --all` first.")
    st.stop()

with st.sidebar:
    st.header("Filters")
    if st.button("Refresh data"):
        st.cache_data.clear()
    country_options = ["All"] + sorted(sites_df["country"].unique().tolist())
    selected_country = st.selectbox("Country", country_options)
    site_options = ["All"] + sorted(sites_df["slug"].unique().tolist())
    selected_site = st.selectbox("Site", site_options)

country_filter = None if selected_country == "All" else selected_country

tab_overview, tab_upcoming, tab_items, tab_layouts, tab_events = st.tabs(
    ["Overview", "Upcoming Changes", "All Regulation Items", "Layout History", "Change Log"]
)

with tab_overview:
    st.subheader("Registered sites")
    st.dataframe(sites_df, width="stretch", hide_index=True)
    items_df = load_regulation_items()
    col1, col2, col3 = st.columns(3)
    col1.metric("Total regulation items tracked", len(items_df))
    col2.metric(
        "Upcoming / proposed",
        len(items_df[items_df["status"].isin(["proposed", "upcoming"])]),
    )
    col3.metric("Sites crawled", len(sites_df))
    if not items_df.empty:
        st.subheader("Items by site")
        st.bar_chart(items_df["site"].value_counts())

with tab_upcoming:
    st.subheader("Deduced upcoming regulatory changes")
    st.caption("Items with a future effective date, or an explicit proposed/upcoming status.")
    upcoming_df = load_upcoming(country_filter)
    if selected_site != "All":
        upcoming_df = upcoming_df[upcoming_df["site"] == selected_site]
    st.dataframe(
        upcoming_df,
        width="stretch",
        hide_index=True,
        column_config={
            "title": st.column_config.TextColumn(width="medium"),
            "summary": st.column_config.TextColumn(width="large"),
        },
    )

with tab_items:
    st.subheader("All tracked regulation items")
    items_df = load_regulation_items()
    if country_filter:
        items_df = items_df[items_df["country"] == country_filter]
    if selected_site != "All":
        items_df = items_df[items_df["site"] == selected_site]
    status_options = sorted(items_df["status"].dropna().unique().tolist())
    selected_statuses = st.multiselect("Status", status_options, default=status_options)
    if selected_statuses:
        items_df = items_df[items_df["status"].isin(selected_statuses)]
    search = st.text_input("Search title")
    if search:
        items_df = items_df[items_df["title"].str.contains(search, case=False, na=False)]
    st.caption(f"{len(items_df)} item(s)")
    st.dataframe(
        items_df,
        width="stretch",
        hide_index=True,
        column_config={
            "title": st.column_config.TextColumn(width="medium"),
            "summary": st.column_config.TextColumn(width="large"),
        },
    )
    selected_title = st.selectbox(
        "View details for", ["(none)"] + items_df["title"].tolist()
    )
    if selected_title != "(none)":
        row = items_df[items_df["title"] == selected_title].iloc[0]
        st.markdown(f"#### {row['title']}")
        meta_bits = [
            f"**Status:** {row['status']}",
            f"**Document type:** {row['document_type'] or '_unknown_'}",
            f"**Document number:** {row['document_number'] or '_unknown_'}",
            f"**Published:** {row['publication_date'] or '_unknown_'}",
            f"**Effective:** {row['effective_date'] or '_unknown_'}",
        ]
        st.markdown(" &nbsp;|&nbsp; ".join(meta_bits))
        st.write(row["summary"] or "_(no summary extracted)_")
        st.write(row["source_url"])

with tab_layouts:
    st.subheader("Layout-learning history")
    st.caption(
        "Each row is a distinct page-structure fingerprint the agent has ever learned "
        "for a site. New rows over time mean the site changed its layout."
    )
    events_df = load_change_events()
    layout_events = events_df[events_df["type"] == "layout_relearned"] if not events_df.empty else events_df
    if selected_site != "All" and not layout_events.empty:
        layout_events = layout_events[layout_events["site"] == selected_site]
    if layout_events.empty:
        st.info("No layout-change events recorded yet.")
    else:
        display_df = layout_events.copy()
        display_df["sample_url"] = display_df["details"].apply(lambda d: d.get("sample_url"))
        display_df["fingerprint"] = display_df["details"].apply(
            lambda d: (d.get("fingerprint") or "")[:16] + "..."
        )
        st.dataframe(
            display_df[["detected_at", "site", "sample_url", "fingerprint"]],
            width="stretch",
            hide_index=True,
        )

with tab_events:
    st.subheader("Full change-event log")
    events_df = load_change_events()
    if selected_site != "All" and not events_df.empty:
        events_df = events_df[events_df["site"] == selected_site]
    type_options = sorted(events_df["type"].unique().tolist()) if not events_df.empty else []
    selected_types = st.multiselect("Event type", type_options, default=type_options)
    if selected_types:
        events_df = events_df[events_df["type"].isin(selected_types)]
    display_df = events_df.copy()
    if not display_df.empty:
        display_df["details"] = display_df["details"].apply(json.dumps)
    st.dataframe(display_df, width="stretch", hide_index=True)
