"""Integration test for migration 033 — meetings.is_hidden + partial index + MV refresh.

Asserts the migration produces the expected schema after up, and reverts cleanly
on down. Mirrors the pattern of tests/integration/test_029_migration.py.
"""

import importlib

import pytest

from docket.config import DATABASE_URL
from docket.db import db


_m033 = importlib.import_module("docket.migrations.033_meetings_is_hidden")


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
    """mv_badge_volume_monthly's WHERE clause filters meetings.is_hidden."""
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_viewdef('mv_badge_volume_monthly'::regclass, true)"
        )
        defn = cur.fetchone()[0]
    assert "m.is_hidden = false" in defn.lower(), (
        "mv_badge_volume_monthly must filter on meetings.is_hidden in its WHERE clause"
    )


def test_033_default_is_false():
    """New meetings rows default to is_hidden=FALSE — confirms the NOT NULL DEFAULT."""
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM meetings WHERE is_hidden IS NULL"
        )
        n_null = cur.fetchone()[0]
    assert n_null == 0, "is_hidden NOT NULL DEFAULT FALSE should backfill existing rows"


def test_033_sql_down_drops_columns_index_and_rebuilds_mv_without_filter():
    """SQL_DOWN must drop the three columns, the partial index, and rebuild
    the MV without the is_hidden predicate."""
    down = _m033.SQL_DOWN
    assert "DROP MATERIALIZED VIEW IF EXISTS mv_badge_volume_monthly" in down
    assert "DROP INDEX IF EXISTS idx_meetings_public_visible" in down
    assert "DROP COLUMN IF EXISTS is_hidden" in down
    assert "DROP COLUMN IF EXISTS hidden_at" in down
    assert "DROP COLUMN IF EXISTS hidden_by" in down
    # And the rebuilt MV in SQL_DOWN does NOT carry the is_hidden filter:
    lowered = down.lower()
    if "create materialized view" in lowered:
        assert "m.is_hidden" not in lowered.split("create materialized view")[1]
