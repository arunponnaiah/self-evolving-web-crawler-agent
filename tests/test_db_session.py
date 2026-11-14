from sqlalchemy import create_engine, inspect, text

from crawler_agent.db import session as db_session
from crawler_agent.db.models import Base


def test_add_missing_columns_adds_a_column_to_an_existing_table(monkeypatch):
    """Mirrors what actually happened in this project: review_comment was
    added to SiteProposal/PromptVersion after some installs already had
    those tables -- create_all() alone would never add it to an existing
    table, only to a brand-new one."""
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(db_session, "_engine", engine)

    # Create site_proposals with every column EXCEPT review_comment, as if
    # from before that column was added to the model.
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE site_proposals (
                    id INTEGER PRIMARY KEY,
                    slug VARCHAR(64),
                    name VARCHAR(255),
                    country VARCHAR(64),
                    base_url VARCHAR(512),
                    seed_urls_json TEXT,
                    fetch_mode VARCHAR(16),
                    status VARCHAR(16),
                    created_at DATETIME,
                    reviewed_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO site_proposals (id, slug, name, country, base_url, "
                "seed_urls_json, fetch_mode, status) VALUES "
                "(1, 'x', 'X', 'US', 'https://x.gov', '[]', 'http', 'pending')"
            )
        )

    db_session.init_db()

    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("site_proposals")}
    assert "review_comment" in columns

    # The pre-existing row survived the migration.
    with engine.connect() as conn:
        row = conn.execute(text("SELECT slug, review_comment FROM site_proposals WHERE id=1")).fetchone()
        assert row[0] == "x"
        assert row[1] is None
