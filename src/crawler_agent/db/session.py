from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from crawler_agent.config import settings
from crawler_agent.db.models import Base

_engine = create_engine(f"sqlite:///{settings.db_path}", future=True)
SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(_engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Minimal migration path: create_all() only adds brand-new tables, never
    a new column on a table that already exists -- so an existing DB file
    would silently keep missing any column added to a model after the fact
    (e.g. SiteProposal/PromptVersion's review_comment). There's no Alembic
    here, so this does the one thing that's actually needed: add any
    declared-but-missing nullable column via ALTER TABLE. Not a general
    migration tool -- it can't rename/drop/retype a column, only add one."""
    inspector = inspect(_engine)
    existing_tables = set(inspector.get_table_names())
    with _engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_columns = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                col_type = column.type.compile(dialect=_engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))


@contextmanager
def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
