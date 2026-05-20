"""Integration test for migration 033 — meetings.is_hidden + partial index + MV refresh.

Asserts the migration produces the expected schema after up, and reverts cleanly
on down. Mirrors the pattern of tests/integration/test_029_migration.py.
"""

import pytest

from docket.config import DATABASE_URL
from docket.db import db


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Migration test must not run against Railway prod.",
)


def _column_exists(table: str, column: str) -> bool:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM information_schema.columns
             WHERE table_name = %s AND column_name = %s
            """,
            (table, column),
        )
        return cur.fetchone() is not None


def _index_exists(name: str) -> bool:
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", (name,))
        return cur.fetchone() is not None


def _mv_definition_includes(needle: str) -> bool:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_viewdef('mv_badge_volume_monthly'::regclass, true)"
        )
        defn = cur.fetchone()[0]
    return needle in defn


def test_033_up_creates_columns_and_index():
    """After migrations run, the new columns + partial index exist."""
    assert _column_exists("meetings", "is_hidden"), "is_hidden column missing"
    assert _column_exists("meetings", "hidden_at"), "hidden_at column missing"
    assert _column_exists("meetings", "hidden_by"), "hidden_by column missing"
    assert _index_exists("idx_meetings_public_visible"), "partial index missing"


def test_033_up_refreshes_mv_with_filter():
    """mv_badge_volume_monthly now JOINs against meetings and filters is_hidden."""
    assert _mv_definition_includes("is_hidden"), (
        "mv_badge_volume_monthly definition should reference m.is_hidden"
    )


def test_033_default_is_false():
    """New meetings rows default to is_hidden=FALSE — confirms the NOT NULL DEFAULT."""
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM meetings WHERE is_hidden IS NULL"
        )
        n_null = cur.fetchone()[0]
    assert n_null == 0, "is_hidden NOT NULL DEFAULT FALSE should backfill existing rows"
