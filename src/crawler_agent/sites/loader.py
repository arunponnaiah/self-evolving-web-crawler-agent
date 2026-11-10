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
