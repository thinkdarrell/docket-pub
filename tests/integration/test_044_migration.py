"""Verify migration 044: `meetings.hidden_reason` with its CHECK and `meetings.keep_visible_at`; down removes both and leaves `is_hidden` alone.

Pattern: tests/integration/test_043_migration.py. Plan `committee-clips-named-or-hidden`, M4.
The migration module and the runner's list are read inside the test functions so
the file collects before the migration exists.
"""
import importlib

import psycopg2.errors
import pytest
from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Migration test must not run against Railway prod.",
)

PREFIX = "m044-"
MODULE = "docket.migrations.044_hidden_reason"


def _delete_test_meetings() -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE external_id LIKE %s", (PREFIX + "%",))


@pytest.fixture
def fresh_044():
    """Every migration applied, then 044 rolled back; the teardown re-applies it."""
    _delete_test_meetings()
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 44)
    yield
    _delete_test_meetings()
    with db() as conn:
        runner.apply_migrations(conn)


def _insert(tag: str, *, is_hidden: bool) -> int:
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
        muni = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type, is_hidden) "
            "VALUES (%s, %s, 'Regular City Council Meeting', '2026-11-05', 'council', %s) RETURNING id",
            (muni, PREFIX + tag, is_hidden),
        )
        return cur.fetchone()["id"]


def _columns() -> dict[str, tuple[str, str]]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT column_name, is_nullable, data_type FROM information_schema.columns "
            "WHERE table_name = 'meetings' AND column_name IN ('hidden_reason', 'keep_visible_at', 'is_hidden')"
        )
        return {r["column_name"]: (r["is_nullable"], r["data_type"]) for r in cur.fetchall()}


def test_044_is_registered_in_order():
    versions = [int(m.rsplit(".", 1)[-1].split("_")[0]) for m in runner.MIGRATIONS]
    assert 44 in versions
    assert versions == sorted(versions)
    assert importlib.import_module(MODULE).SQL_DOWN.strip()


def test_044_up_adds_the_two_columns_and_sets_no_value(fresh_044):
    assert set(_columns()) == {"is_hidden"}
    hidden_before = _insert("before", is_hidden=True)

    with db() as conn:
        runner.apply_migrations(conn)

    assert _columns() == {
        "is_hidden": ("NO", "boolean"),
        "hidden_reason": ("YES", "text"),
        "keep_visible_at": ("YES", "timestamp with time zone"),
    }
    with db_cursor() as cur:
        cur.execute("SELECT is_hidden, hidden_reason, keep_visible_at FROM meetings WHERE id = %s", (hidden_before,))
        row = cur.fetchone()
    assert (row["is_hidden"], row["hidden_reason"], row["keep_visible_at"]) == (True, None, None), (
        "a row hidden before the column has no reason"
    )


def test_044_the_check_admits_the_three_reasons_and_nothing_else(fresh_044):
    with db() as conn:
        runner.apply_migrations(conn)
    mid = _insert("check", is_hidden=True)
    for reason in ("admin", "absorbed", "not_a_meeting", None):
        with db_cursor() as cur:
            cur.execute("UPDATE meetings SET hidden_reason = %s WHERE id = %s", (reason, mid))
    with pytest.raises(psycopg2.errors.CheckViolation):
        with db_cursor() as cur:
            cur.execute("UPDATE meetings SET hidden_reason = 'test' WHERE id = %s", (mid,))


def test_044_up_twice_is_the_same_schema(fresh_044):
    module = importlib.import_module(MODULE)
    with db() as conn:
        runner.apply_migrations(conn)
    with db_cursor() as cur:
        cur.execute(module.SQL_UP)
        cur.execute(
            "SELECT count(*) AS n FROM pg_constraint "
            "WHERE conrelid = 'meetings'::regclass AND pg_get_constraintdef(oid) LIKE '%hidden_reason%'"
        )
        assert cur.fetchone()["n"] == 1


def test_044_down_removes_the_columns_and_leaves_hidden_rows_hidden(fresh_044):
    with db() as conn:
        runner.apply_migrations(conn)
    mid = _insert("down", is_hidden=True)
    with db_cursor() as cur:
        cur.execute("UPDATE meetings SET hidden_reason = 'not_a_meeting' WHERE id = %s", (mid,))

    with db() as conn:
        runner.rollback_migration(conn, 44)

    assert set(_columns()) == {"is_hidden"}
    with db_cursor() as cur:
        cur.execute("SELECT is_hidden FROM meetings WHERE id = %s", (mid,))
        assert cur.fetchone()["is_hidden"] is True
