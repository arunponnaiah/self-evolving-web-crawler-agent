from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent.parent


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str | None
    db_path: Path
    user_agent: str
    default_delay_seconds: float
    max_pages_per_run: int
    llm_model: str


def load_settings() -> Settings:
    db_path = Path(os.environ.get("CRAWLER_DB_PATH", "./data/crawler.sqlite3")).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        db_path=db_path,
        user_agent=os.environ.get(
            "CRAWLER_USER_AGENT",
            "SelfEvolvingRegCrawler/0.1 (contact: set CRAWLER_USER_AGENT)",
        ),
        default_delay_seconds=float(os.environ.get("CRAWLER_DEFAULT_DELAY_SECONDS", "5")),
        max_pages_per_run=int(os.environ.get("CRAWLER_MAX_PAGES_PER_RUN", "25")),
        llm_model=os.environ.get("CRAWLER_LLM_MODEL", "claude-sonnet-5"),
    )


settings = load_settings()
