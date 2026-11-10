from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

REGISTRY_PATH = Path(__file__).resolve().parent / "registry.yaml"


class SiteConfig(BaseModel):
    id: str
    name: str
    country: str
    base_url: str
    seed_urls: list[str] = Field(default_factory=list)
    fetch_mode: str = "http"
    crawl_interval_hours: int = 24
    # Optional name of a resolver in discovery/resolver.py that computes the
    # real seed URL at crawl time (e.g. "find today's OJ issue") instead of
    # using a static seed_urls entry verbatim. None means use seed_urls as-is.
    seed_resolver: str | None = None


def load_registry(path: Path = REGISTRY_PATH) -> list[SiteConfig]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text()) or []
    return [SiteConfig.model_validate(entry) for entry in raw]


def get_site(site_id: str, path: Path = REGISTRY_PATH) -> SiteConfig | None:
    for site in load_registry(path):
        if site.id == site_id:
            return site
    return None


def append_site(config: SiteConfig, path: Path = REGISTRY_PATH) -> None:
    """Register a new site config without touching any code."""
    entries = load_registry(path)
    if any(s.id == config.id for s in entries):
        raise ValueError(f"site id '{config.id}' already registered")
    entries.append(config)
    path.write_text(yaml.safe_dump([e.model_dump() for e in entries], sort_keys=False))


def update_site_seed_urls(
    site_id: str, new_seed_urls: list[str], path: Path = REGISTRY_PATH
) -> None:
    """Persist a self-corrected seed URL list for an already-registered site.

    Used by discovery/revalidate.py when a site's configured seed URL stops
    yielding real items and a working replacement is found -- the correction
    is written back to the registry so future crawls use it automatically.
    """
    entries = load_registry(path)
    found = False
    for entry in entries:
        if entry.id == site_id:
            entry.seed_urls = new_seed_urls
            found = True
            break
    if not found:
        raise ValueError(f"site id '{site_id}' not found in registry")
    path.write_text(yaml.safe_dump([e.model_dump() for e in entries], sort_keys=False))
