from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from ruamel.yaml import YAML

REGISTRY_PATH = Path(__file__).resolve().parent / "registry.yaml"

# A round-trip-preserving loader: plain PyYAML discards comments the moment
# it parses a file, so any load -> modify -> dump cycle through it silently
# destroys every explanatory comment in registry.yaml (robots.txt findings,
# why a site needs fetch_mode: browser, why one is disabled, etc). ruamel
# keeps comments attached to their nodes through that cycle, as long as
# writes mutate the existing structure in place rather than rebuilding it
# from scratch.
_yaml = YAML()
_yaml.preserve_quotes = True


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
    # False means "don't crawl this" -- e.g. the site's robots.txt now
    # disallows the whole domain. The config (seed_urls, seed_resolver,
    # comments) is kept rather than deleted, in case the site's policy
    # changes back later; flip this to true to reactivate.
    enabled: bool = True


def _load_raw(path: Path):
    if not path.exists():
        return _yaml.load("[]")
    with path.open() as f:
        return _yaml.load(f) or _yaml.load("[]")


def _dump_raw(raw, path: Path) -> None:
    with path.open("w") as f:
        _yaml.dump(raw, f)


def load_registry(path: Path = REGISTRY_PATH) -> list[SiteConfig]:
    raw = _load_raw(path)
    return [SiteConfig.model_validate(dict(entry)) for entry in raw]


def get_site(site_id: str, path: Path = REGISTRY_PATH) -> SiteConfig | None:
    for site in load_registry(path):
        if site.id == site_id:
            return site
    return None


def append_site(config: SiteConfig, path: Path = REGISTRY_PATH) -> None:
    """Register a new site config without touching any code."""
    raw = _load_raw(path)
    if any(dict(entry).get("id") == config.id for entry in raw):
        raise ValueError(f"site id '{config.id}' already registered")
    raw.append(config.model_dump())
    _dump_raw(raw, path)


def update_site_enabled(site_id: str, enabled: bool, path: Path = REGISTRY_PATH) -> None:
    """Flip a site's enabled flag (e.g. auto re-enabling one that was
    disabled for a robots.txt block, once revalidation confirms it works
    again)."""
    raw = _load_raw(path)
    found = False
    for entry in raw:
        if dict(entry).get("id") == site_id:
            entry["enabled"] = enabled
            found = True
            break
    if not found:
        raise ValueError(f"site id '{site_id}' not found in registry")
    _dump_raw(raw, path)


def update_site_seed_urls(
    site_id: str, new_seed_urls: list[str], path: Path = REGISTRY_PATH
) -> None:
    """Persist a self-corrected seed URL list for an already-registered site.

    Used by discovery/revalidate.py when a site's configured seed URL stops
    yielding real items and a working replacement is found -- the correction
    is written back to the registry so future crawls use it automatically.
    """
    raw = _load_raw(path)
    found = False
    for entry in raw:
        if dict(entry).get("id") == site_id:
            entry["seed_urls"] = list(new_seed_urls)
            found = True
            break
    if not found:
        raise ValueError(f"site id '{site_id}' not found in registry")
    _dump_raw(raw, path)
