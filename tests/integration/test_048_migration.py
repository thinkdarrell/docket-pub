"""Verify migration 048: `granicus_clip_sound`, one row per meeting saying where its Granicus clip is silent; down drops the table.

Pattern: tests/integration/test_046_migration.py. Plan `silent-granicus-says-so`, M2.
The runner's list is read inside the test functions so the file collects before the migration exists.
"""
import importlib
from datetime import date

import psycopg2.errors
import pytest
from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Migration test must not run against Railway prod.",
)

PREFIX = "m048-"
MODULE = "docket.migrations.048_granicus_clip_sound"


def _delete_test_meetings() -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE external_id LIKE %s", (PREFIX + "%",))


@pytest.fixture
def fresh_048():
    """Every migration applied, then 048 rolled back; the teardown re-applies it."""
    _delete_test_meetings()
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 48)
    yield
    _delete_test_meetings()
    with db() as conn:
        runner.apply_migrations(conn)


@pytest.fixture
def applied_048():
    _delete_test_meetings()
    with db() as conn:
        runner.apply_migrations(conn)
    yield
    _delete_test_meetings()
    with db() as conn:
        runner.apply_migrations(conn)


def _meeting(tag: str) -> int:
    """One Birmingham meeting; its id."""
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
        muni = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type) "
            "VALUES (%s, %s, 'Regular City Council Meeting', %s, 'council') RETURNING id",
            (muni, PREFIX + tag, date(2026, 11, 10)),
        )
        return cur.fetchone()["id"]


def _sound(meeting_id: int, *, duration_s=600.0, silent_s=120.0, spans: str | None = "[[0, 120]]") -> None:
    """One stored row; `silent_spans` is named only when given, so the column's default can be read."""
    columns = ["meeting_id", "granicus_clip_id", "method_version", "duration_s", "silent_s"]
    values = [meeting_id, "2034", 1, duration_s, silent_s]
    if spans is not None:
        columns.append("silent_spans")
        values.append(spans)
    with db_cursor() as cur:
        cur.execute(
            f"INSERT INTO granicus_clip_sound ({', '.join(columns)}) "
            f"VALUES ({', '.join(['%s'] * len(values))})",
            values,
        )


def _rows(meeting_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT granicus_clip_id, method_version, duration_s, silent_s, silent_spans, "
            "       measured_at > now() - interval '1 minute' AS fresh "
            "FROM granicus_clip_sound WHERE meeting_id = %s", (meeting_id,))
        return [dict(r) for r in cur.fetchall()]


def _table_exists() -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT to_regclass('granicus_clip_sound') AS t")
        return cur.fetchone()["t"] is not None


def test_048_up_creates_the_table_and_a_row_reads_back(fresh_048):
    versions = [int(m.rsplit(".", 1)[-1].split("_")[0]) for m in runner.MIGRATIONS]
    assert MODULE in runner.MIGRATIONS and versions == sorted(versions)
    assert not _table_exists()

    with db() as conn:
        runner.apply_migrations(conn)

    a = _meeting("A")
    _sound(a)
    assert _rows(a) == [dict(granicus_clip_id="2034", method_version=1, duration_s=600.0, silent_s=120.0,
                             silent_spans=[[0, 120]], fresh=True)]
    # A meeting has one row: the writer replaces it in place.
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _sound(a, silent_s=60.0, spans="[[0, 60]]")
    # A clip with no silent span is stored without naming the column.
    b = _meeting("B")
    _sound(b, silent_s=0.0, spans=None)
    assert _rows(b)[0]["silent_spans"] == []
    # The up is harmless to repeat on a database that already holds the table.
    with db_cursor() as cur:
        cur.execute(importlib.import_module(MODULE).SQL_UP)
    assert len(_rows(a)) == 1


def test_048_silent_longer_than_the_clip_is_refused(applied_048):
    a = _meeting("A")
    with pytest.raises(psycopg2.errors.CheckViolation):
        _sound(a, duration_s=600.0, silent_s=600.5)
    with pytest.raises(psycopg2.errors.CheckViolation):
        _sound(a, silent_s=-1.0)
    with pytest.raises(psycopg2.errors.CheckViolation):
        _sound(a, duration_s=0.0, silent_s=0.0)
    assert _rows(a) == []
    _sound(a, duration_s=600.0, silent_s=600.0, spans="[[0, 600]]")   # silent throughout is allowed
    assert len(_rows(a)) == 1


def test_048_the_meeting_takes_its_sound_row_along(applied_048):
    a = _meeting("A")
    _sound(a)
    assert len(_rows(a)) == 1

    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE id = %s", (a,))
    assert _rows(a) == []


def test_048_down_drops_the_table_and_the_up_applies_again(applied_048):
    a = _meeting("A")
    _sound(a)

    with db() as conn:
        runner.rollback_migration(conn, 48)

    assert not _table_exists()
    with db() as conn:
        assert 48 not in runner.applied_versions(conn)
    # The down is harmless to repeat on a database that no longer holds the table.
    with db_cursor() as cur:
        cur.execute(importlib.import_module(MODULE).SQL_DOWN)

    with db() as conn:
        runner.apply_migrations(conn)

    assert _table_exists()
    assert _rows(a) == [], "the down dropped the rows with the table"
    _sound(a)
    assert len(_rows(a)) == 1
