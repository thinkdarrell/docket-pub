"""Integration tests: the ingest writers classify from the title and respect a resolved or locked row.

`_upsert_meetings` writes `meeting_type`, `session_kind`, `body_name`, and
`type_source = 'title'` from `classify_title(title)` on INSERT, and on UPDATE
only while the row's `type_source` is `title` and it is not locked
(`type_locked_at IS NULL`). A row the resolver placed on the calendar or
schedule rung, or an admin locked, keeps its classification while `title`,
dates, and links still update. The event-* upgrade path is gated the same way.

Pattern: tests/integration/test_ingest_reconciliation.py.
Plan: plans/active/meeting-types-name-the-body.md (M2).
"""

from datetime import date

import pytest

from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.models.protocol import RawMeeting
from docket.services.ingest import _upsert_meetings


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Integration tests require local DB; will not run against Railway prod",
)


TEST_SLUG = "test_meeting_types"
PREFIX = "mtype-"


@pytest.fixture
def muni_id():
    """Seed a test municipality; delete this file's rows (by external_id prefix) before and after."""
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO municipalities (slug, name, state, adapter_class, adapter_config, active)
            VALUES (%s, 'Test Meeting Types', 'AL', 'GranicusAdapter',
                    '{"view_id": 1, "base_url": "https://example.com"}'::jsonb, TRUE)
            ON CONFLICT (slug) DO UPDATE SET active = TRUE
            RETURNING id
            """,
            (TEST_SLUG,),
        )
        mid = cur.fetchone()[0]
        cur.execute(
            "DELETE FROM meetings WHERE municipality_id = %s AND (external_id LIKE %s OR external_id LIKE 'event-%%')",
            (mid, PREFIX + "%"),
        )
    yield mid
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM meetings WHERE municipality_id = %s AND (external_id LIKE %s OR external_id LIKE 'event-%%')",
            (mid, PREFIX + "%"),
        )


def _meeting(external_id: str, title: str, meeting_date: date = date(2026, 5, 19)) -> RawMeeting:
    """A RawMeeting whose `meeting_type` is deliberately stale: ingest classifies from the title."""
    return RawMeeting(
        external_id=external_id,
        municipality_slug=TEST_SLUG,
        title=title,
        meeting_date=meeting_date,
        meeting_type="council",
        agenda_url=f"https://example.com/agenda/{external_id}",
        minutes_url=None,
        video_url=None,
        source_url=f"https://example.com/m/{external_id}",
    )


def _classification(muni_id: int, external_id: str) -> tuple:
    with db_cursor() as cur:
        cur.execute(
            "SELECT title, meeting_type, session_kind, body_name, type_source "
            "FROM meetings WHERE municipality_id = %s AND external_id = %s",
            (muni_id, external_id),
        )
        r = cur.fetchone()
        return (r["title"], r["meeting_type"], r["session_kind"], r["body_name"], r["type_source"])


def _set(muni_id: int, external_id: str, sql: str) -> None:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE meetings SET {sql} WHERE municipality_id = %s AND external_id = %s",
            (muni_id, external_id),
        )


class TestTitleRung:
    def test_insert_classifies_from_the_title(self, muni_id):
        inserted, updated = _upsert_meetings(muni_id, [_meeting("mtype-1", "Special Called Finance Committee")])
        assert (inserted, updated) == (1, 0)
        assert _classification(muni_id, "mtype-1") == (
            "Special Called Finance Committee", "committee", "special", "Finance Committee", "title",
        )

    def test_update_reclassifies_while_the_source_is_the_title(self, muni_id):
        _upsert_meetings(muni_id, [_meeting("mtype-1", "Special Called Finance Committee")])
        inserted, updated = _upsert_meetings(muni_id, [_meeting("mtype-1", "Finance Committee")])
        assert (inserted, updated) == (0, 1)
        assert _classification(muni_id, "mtype-1") == (
            "Finance Committee", "committee", "regular", "Finance Committee", "title",
        )


class TestResolvedRowIsTheResolvers:
    def test_calendar_rung_survives_the_upsert(self, muni_id):
        _upsert_meetings(muni_id, [_meeting("mtype-1", "Finance Committee")])
        _set(muni_id, "mtype-1",
             "meeting_type = 'committee', session_kind = 'regular', "
             "body_name = 'Public Safety Committee', type_source = 'calendar'")
        inserted, updated = _upsert_meetings(muni_id, [_meeting("mtype-1", "Regular City Council Meeting")])
        assert (inserted, updated) == (0, 1)
        assert _classification(muni_id, "mtype-1") == (
            "Regular City Council Meeting", "committee", "regular", "Public Safety Committee", "calendar",
        )

    def test_schedule_rule_rung_survives_the_upsert(self, muni_id):
        _upsert_meetings(muni_id, [_meeting("mtype-2", "Regular City Council Meeting")])
        _set(muni_id, "mtype-2",
             "meeting_type = 'committee', session_kind = 'regular', body_name = NULL, type_source = 'schedule_rule'")
        _upsert_meetings(muni_id, [_meeting("mtype-2", "Regular City Council Meeting - Part II")])
        assert _classification(muni_id, "mtype-2") == (
            "Regular City Council Meeting - Part II", "committee", "regular", None, "schedule_rule",
        )


class TestLockedRowIsTheAdmins:
    def test_lock_survives_the_upsert_while_the_title_updates(self, muni_id):
        _upsert_meetings(muni_id, [_meeting("mtype-1", "Regular City Council Meeting")])
        _set(muni_id, "mtype-1",
             "meeting_type = 'board', session_kind = 'regular', body_name = 'Library Board', "
             "type_source = 'admin', type_locked_at = now()")
        inserted, updated = _upsert_meetings(muni_id, [_meeting("mtype-1", "Special Called Finance Committee")])
        assert (inserted, updated) == (0, 1)
        assert _classification(muni_id, "mtype-1") == (
            "Special Called Finance Committee", "board", "regular", "Library Board", "admin",
        )
        with db_cursor() as cur:
            cur.execute(
                "SELECT type_locked_at, agenda_url FROM meetings WHERE municipality_id = %s AND external_id = 'mtype-1'",
                (muni_id,),
            )
            r = cur.fetchone()
        assert r["type_locked_at"] is not None
        assert r["agenda_url"] == "https://example.com/agenda/mtype-1", "the links still update"


class TestEventUpgradePath:
    """`_try_upgrade_event_row` (an event-* row becoming a clip row) is gated the same way."""

    def test_upgrade_keeps_a_resolved_classification(self, muni_id):
        _upsert_meetings(muni_id, [_meeting("event-9001", "Regular City Council Meeting")])
        _set(muni_id, "event-9001",
             "meeting_type = 'committee', session_kind = 'regular', "
             "body_name = 'Committee of the Whole / Administration & Governmental Affairs', type_source = 'calendar'")
        inserted, updated = _upsert_meetings(muni_id, [_meeting("mtype-9001", "Regular City Council Meeting")])
        assert (inserted, updated) == (0, 1)
        assert _classification(muni_id, "mtype-9001") == (
            "Regular City Council Meeting", "committee", "regular",
            "Committee of the Whole / Administration & Governmental Affairs", "calendar",
        )

    def test_upgrade_reclassifies_a_title_sourced_row(self, muni_id):
        _upsert_meetings(muni_id, [_meeting("event-9002", "Special Called Council Meeting")])
        inserted, updated = _upsert_meetings(muni_id, [_meeting("mtype-9002", "Special Called Council Meeting")])
        assert (inserted, updated) == (0, 1)
        assert _classification(muni_id, "mtype-9002") == (
            "Special Called Council Meeting", "council", "special", None, "title",
        )
