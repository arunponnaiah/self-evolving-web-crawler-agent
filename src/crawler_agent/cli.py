from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import typer
import yaml

from sqlalchemy import select

from crawler_agent.db.models import ChangeEvent, Site, SummaryFeedback
from crawler_agent.db.session import get_session, init_db
from crawler_agent.discovery.discover import discover_site
from crawler_agent.discovery.revalidate import revalidate_all
from crawler_agent.extraction.llm_extractor import LlmExtractor
from crawler_agent.change_detection.detector import upcoming_changes
from crawler_agent.feedback.store import recent_feedback_examples
from crawler_agent.pipeline.run import run_crawl
from crawler_agent.sites.loader import SiteConfig, append_site, load_registry

app = typer.Typer(help="Self-evolving regulatory web crawler agent")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@app.command("init-db")
def init_db_cmd() -> None:
    """Create the local SQLite database and tables."""
    init_db()
    typer.echo("Database initialized.")


@app.command("crawl")
def crawl_cmd(
    site: str = typer.Option(None, "--site", help="Site id from the registry to crawl"),
    all_sites: bool = typer.Option(False, "--all", help="Crawl every registered site"),
    max_pages: int = typer.Option(None, "--max-pages", help="Override max pages for this run"),
) -> None:
    """Run one crawl cycle for a site (or all sites)."""
    init_db()
    registry = load_registry()
    if all_sites:
        targets = registry
    elif site:
        targets = [s for s in registry if s.id == site]
        if not targets:
            typer.echo(f"No such site '{site}' in registry.", err=True)
            raise typer.Exit(1)
    else:
        typer.echo("Pass --site <id> or --all.", err=True)
        raise typer.Exit(1)

    with get_session() as session:
        feedback_examples = recent_feedback_examples(session)
        extractor = LlmExtractor(feedback_examples=feedback_examples)
        for config in targets:
            typer.echo(f"Crawling {config.id} ({config.name})...")
            summary = run_crawl(session, config, extractor, max_pages=max_pages)
            typer.echo(
                f"  pages_fetched={summary.pages_fetched} blocked_pages={summary.blocked_pages} "
                f"layout_relearned={summary.layout_relearned} "
                f"new={summary.new_items} updated={summary.updated_items} "
                f"unchanged={summary.unchanged_items} errors={len(summary.errors)}"
            )
            for err in summary.errors:
                typer.echo(f"  ! {err}")


@app.command("list-upcoming")
def list_upcoming_cmd(
    country: str = typer.Option(None, "--country", help="Filter by country code"),
) -> None:
    """Show regulation items the agent has deduced are not yet in force."""
    with get_session() as session:
        items = upcoming_changes(session, country=country)
        if not items:
            typer.echo("No upcoming changes found.")
            return
        for item in items:
            eff = item.effective_date.isoformat() if item.effective_date else "unknown"
            doc_num = f" ({item.document_number})" if item.document_number else ""
            typer.echo(f"[{item.status}] effective={eff} {item.title}{doc_num}")
            if item.summary:
                typer.echo(f"  {item.summary}")
            typer.echo(f"  {item.source_url}")


@app.command("list-layout-events")
def list_layout_events_cmd() -> None:
    """Show the agent's layout-learning history (when it detected a new layout)."""
    with get_session() as session:
        events = session.scalars(
            select(ChangeEvent)
            .where(ChangeEvent.type == "layout_relearned")
            .order_by(ChangeEvent.detected_at.desc())
        ).all()
        if not events:
            typer.echo("No layout-change events recorded yet.")
            return
        for event in events:
            site = session.get(Site, event.site_id)
            site_label = site.slug if site else event.site_id
            typer.echo(f"{event.detected_at.isoformat()} [{site_label}] {event.details_json}")


@app.command("add-site")
def add_site_cmd(config_path: Path) -> None:
    """Register a new site from a YAML file without touching any code."""
    data = yaml.safe_load(config_path.read_text())
    config = SiteConfig.model_validate(data)
    append_site(config)
    typer.echo(f"Registered site '{config.id}'.")


@app.command("discover-site")
def discover_site_cmd(
    country: str = typer.Option(..., "--country", help="Country code/name to discover a site for"),
) -> None:
    """Self-learning site discovery: suggest, validate, and register a
    working regulatory site for a country not yet in the registry."""
    report = discover_site(country)
    for probe in report.tried:
        status = "OK" if probe.works else f"failed ({probe.reason})"
        typer.echo(f"  tried [{probe.fetch_mode}] {probe.url} -> {status}")
    for url in report.rejected_unauthentic:
        typer.echo(f"  rejected (not an authentic {country} domain): {url}")
    if report.registered_site_id:
        typer.echo(f"Registered new site '{report.registered_site_id}'.")
    else:
        typer.echo(f"No working site found for '{country}'.")


@app.command("revalidate-sites")
def revalidate_sites_cmd(
    site: str = typer.Option(None, "--site", help="Only revalidate this site id"),
) -> None:
    """Self-learning site maintenance: re-check each registered site's seed
    URL still yields real items, and self-correct the registry if not."""
    init_db()
    with get_session() as session:
        results = revalidate_all(session, site_id=site)
        for result in results:
            if result.corrected_to:
                typer.echo(f"{result.site_id}: self-corrected seed URL -> {result.corrected_to}")
            elif result.still_working:
                typer.echo(f"{result.site_id}: still working, no change needed.")
            else:
                typer.echo(f"{result.site_id}: NO WORKING SEED FOUND -- needs manual attention.")
            for probe in result.tried:
                status = "OK" if probe.works else f"failed ({probe.reason})"
                typer.echo(f"  tried [{probe.fetch_mode}] {probe.url} -> {status}")


@app.command("list-feedback")
def list_feedback_cmd(
    item_id: int = typer.Option(None, "--item", help="Only show feedback for this regulation item id"),
) -> None:
    """Show recorded summary feedback."""
    with get_session() as session:
        query = select(SummaryFeedback).order_by(SummaryFeedback.created_at.desc())
        if item_id is not None:
            query = query.where(SummaryFeedback.regulation_item_id == item_id)
        rows = session.scalars(query).all()
        if not rows:
            typer.echo("No feedback recorded yet.")
            return
        for row in rows:
            typer.echo(
                f"[item {row.regulation_item_id}] {row.rating} "
                f"{row.created_at.isoformat()}"
            )
            if row.corrected_summary:
                typer.echo(f"  corrected: {row.corrected_summary}")
            if row.comment:
                typer.echo(f"  comment: {row.comment}")


@app.command("ui")
def ui_cmd(
    port: int = typer.Option(8501, "--port", help="Port to serve the dashboard on"),
) -> None:
    """Launch the local Streamlit dashboard to browse crawled content."""
    init_db()
    app_path = Path(__file__).resolve().parent / "ui" / "app.py"
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(app_path),
                "--server.port",
                str(port),
                "--server.headless",
                "true",
                "--browser.gatherUsageStats",
                "false",
            ],
            check=True,
        )
    except FileNotFoundError as exc:
        typer.echo(
            "streamlit is not installed; install the 'ui' extra: pip install -e '.[ui]'",
            err=True,
        )
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    app()
