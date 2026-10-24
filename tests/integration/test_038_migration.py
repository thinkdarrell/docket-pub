"""Verify migration 038: the classification columns, the lock, city_calendar_events, and Birmingham's schedule metadata; down removes all of them.

Pattern: tests/integration/test_037_migration.py. Plan: plans/active/meeting-types-name-the-body.md (M2).
"""
from datetime import date, datetime, timezone

import psycopg2.errors
import pytest
from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Migration test must not run against Railway prod.",
)

NEW_COLUMNS = (
    "session_kind", "body_name", "type_source",
    "type_locked_at", "type_locked_by", "calendar_event_id",
)


@pytest.fixture
def fresh_038():
    with db() as conn:
        runner.apply_migrations(conn)
        # 040 re-creates the type_source CHECK that 038's down drops with
        # the column; roll it back first so re-applying restores both.
        runner.rollback_migration(conn, 40)
        runner.rollback_migration(conn, 38)
    yield
    with db() as conn:
        runner.apply_migrations(conn)


def _meeting_columns() -> set[str]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'meetings' AND column_name = ANY(%s)",
            (list(NEW_COLUMNS),),
        )
        return {r["column_name"] for r in cur.fetchall()}


def _table_exists() -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT to_regclass('public.city_calendar_events') AS t")
        return cur.fetchone()["t"] is not None


def _birmingham_meta() -> dict:
    with db_cursor() as cur:
        cur.execute("SELECT metadata FROM municipalities WHERE slug = 'birmingham'")
        return cur.fetchone()["metadata"]


def test_038_up_adds_columns_table_and_metadata(fresh_038):
    assert _meeting_columns() == set()
    assert not _table_exists()
    meta = _birmingham_meta()
    assert "council_schedule" not in meta and "calendar_url" not in meta
    with db() as conn:
        runner.apply_migrations(conn)
    assert _meeting_columns() == set(NEW_COLUMNS)
    assert _table_exists()
    meta = _birmingham_meta()
    assert meta["council_schedule"] == {"weekday": 1}
    assert meta["calendar_url"] == "https://www.birminghamal.gov/government/city-council"
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM municipalities WHERE metadata ? 'calendar_url'")
        assert cur.fetchone()["n"] == 1, "only Birmingham carries a calendar"


def test_038_existing_rows_take_the_defaults(fresh_038):
    with db() as conn:
        runner.apply_migrations(conn)
    with db_cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM meetings "
            "WHERE session_kind <> 'regular' OR type_source <> 'title' "
            "OR body_name IS NOT NULL OR type_locked_at IS NOT NULL OR calendar_event_id IS NOT NULL"
        )
        assert cur.fetchone()["n"] == 0


def test_038_down_removes_all(fresh_038):
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 38)
    assert _meeting_columns() == set()
    assert not _table_exists()
    meta = _birmingham_meta()
    assert "council_schedule" not in meta and "calendar_url" not in meta
    assert "council_type" in meta, "the other metadata keys survive the down"
    assert meta.get("briefing") is True, "037's key survives the down"


class TestCalendarEventForeignKey:
    """meetings.calendar_event_id references city_calendar_events(id) ON DELETE SET NULL."""

    @pytest.fixture
    def birmingham_id(self):
        with db() as conn:
            runner.apply_migrations(conn)
        with db_cursor() as cur:
            cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
            mid = cur.fetchone()["id"]
        yield mid
        with db_cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE municipality_id = %s AND external_id LIKE 'm038-%%'", (mid,))
            cur.execute("DELETE FROM city_calendar_events WHERE municipality_id = %s AND source_event_id LIKE 'm038-%%'", (mid,))

    def test_unknown_calendar_event_is_refused(self, birmingham_id):
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            with db_cursor() as cur:
                cur.execute(
                    "INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type, calendar_event_id) "
                    "VALUES (%s, 'm038-fk', 'Regular City Council Meeting', %s, 'council', 2147483000)",
                    (birmingham_id, date(2026, 10, 21)),
                )

    def test_deleting_the_event_nulls_the_reference(self, birmingham_id):
        with db_cursor() as cur:
            cur.execute(
                "INSERT INTO city_calendar_events (municipality_id, source_event_id, title, starts_at, source_url) "
                "VALUES (%s, 'm038-4854', 'COMMITTEE OF THE WHOLE MEETING', %s, 'https://example.com/e') RETURNING id",
                (birmingham_id, datetime(2026, 10, 21, 20, 30, tzinfo=timezone.utc)),
            )
            event_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type, calendar_event_id) "
                "VALUES (%s, 'm038-ref', 'Regular City Council Meeting', %s, 'council', %s) RETURNING id",
                (birmingham_id, date(2026, 10, 21), event_id),
            )
            meeting_id = cur.fetchone()["id"]
            cur.execute("DELETE FROM city_calendar_events WHERE id = %s", (event_id,))
            cur.execute("SELECT calendar_event_id FROM meetings WHERE id = %s", (meeting_id,))
            assert cur.fetchone()["calendar_event_id"] is None
