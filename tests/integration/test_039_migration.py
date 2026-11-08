"""Verify migration 039: the CHECK on `meetings.meeting_type`, the guard that folds a stray value into `other`, and the down that drops the constraint.

Pattern: tests/integration/test_038_migration.py. Plan `meeting-types-name-the-body`, M6.
The migration module and the runner's list are read inside the test functions so
the file collects before the migration exists and the before state reads as every
test failing rather than one collection error.
"""
import importlib
import re
from datetime import date

import psycopg2.errors
import pytest
from docket.adapters._helpers import MEETING_TYPES
from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Migration test must not run against Railway prod.",
)

PREFIX = "m039-"
MODULE = "docket.migrations.039_meeting_type_checks"


def _delete_test_meetings() -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE external_id LIKE %s", (PREFIX + "%",))


def _insert(tag: str, meeting_type: str) -> int:
    """One Birmingham meeting with the given body; returns its id."""
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
        muni = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type) "
            "VALUES (%s, %s, 'Regular City Council Meeting', %s, %s) RETURNING id",
            (muni, PREFIX + tag, date(2026, 11, 10), meeting_type),
        )
        return cur.fetchone()["id"]


def _meeting_type(meeting_id: int) -> str:
    with db_cursor() as cur:
        cur.execute("SELECT meeting_type FROM meetings WHERE id = %s", (meeting_id,))
        return cur.fetchone()["meeting_type"]


def _constraint_exists() -> bool:
    with db_cursor() as cur:
        cur.execute(
            "SELECT 1 FROM pg_constraint "
            "WHERE conname = 'meetings_meeting_type_check' AND conrelid = 'meetings'::regclass"
        )
        return cur.fetchone() is not None


@pytest.fixture
def applied_039():
    with db() as conn:
        runner.apply_migrations(conn)
    yield
    _delete_test_meetings()


@pytest.fixture
def fresh_039():
    """Every migration applied, then 039 rolled back; the teardown deletes the test rows and re-applies."""
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 39)
    yield
    _delete_test_meetings()
    with db() as conn:
        runner.apply_migrations(conn)


def test_039_is_registered_directly_after_038():
    assert MODULE in runner.MIGRATIONS
    assert runner.MIGRATIONS.index(MODULE) == runner.MIGRATIONS.index("docket.migrations.038_meeting_types") + 1


def test_039_literals_equal_the_vocabulary():
    """The migration is frozen text; its two literal lists must equal MEETING_TYPES so they cannot drift."""
    mod = importlib.import_module(MODULE)
    lists = re.findall(r"meeting_type\s+(?:NOT\s+)?IN\s*\(([^)]*)\)", mod.SQL_UP)
    assert len(lists) == 2, "one list in the guard UPDATE and one in the CHECK"
    for literal in lists:
        assert tuple(re.findall(r"'([a-z_]+)'", literal)) == MEETING_TYPES
    assert "meetings_meeting_type_check" in mod.SQL_UP
    assert "DROP CONSTRAINT IF EXISTS meetings_meeting_type_check" in mod.SQL_DOWN


def test_039_up_refuses_an_old_vocabulary_value(applied_039):
    assert _constraint_exists()
    for value in MEETING_TYPES:
        _insert(f"ok-{value}", value)
    for value in ("special", "work_session", "C"):
        with pytest.raises(psycopg2.errors.CheckViolation):
            with db_cursor() as cur:
                cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
                muni = cur.fetchone()["id"]
                cur.execute(
                    "INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type) "
                    "VALUES (%s, %s, 'Special Called Meeting', %s, %s)",
                    (muni, PREFIX + f"bad-{value}", date(2026, 11, 10), value),
                )
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM meetings WHERE external_id LIKE %s", (PREFIX + "bad-%",))
        assert cur.fetchone()["n"] == 0


def test_039_guard_folds_a_stray_value_into_other_then_the_check_holds(fresh_039):
    assert not _constraint_exists()
    stray = _insert("stray-c", "C")
    old = _insert("stray-special", "special")
    kept = _insert("kept", "committee")

    with db() as conn:
        runner.apply_migrations(conn)

    assert _constraint_exists()
    assert _meeting_type(stray) == "other"
    assert _meeting_type(old) == "other"
    assert _meeting_type(kept) == "committee"


def test_039_down_drops_the_constraint_and_the_insert_succeeds(fresh_039):
    with db() as conn:
        runner.apply_migrations(conn)
    assert _constraint_exists()

    with db() as conn:
        runner.rollback_migration(conn, 39)
    assert not _constraint_exists()
    meeting_id = _insert("after-down", "special")
    assert _meeting_type(meeting_id) == "special"
