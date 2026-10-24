"""Integration tests: the ingest writers classify from the title and respect a resolved or locked row.

`_upsert_meetings` writes `meeting_type`, `session_kind`, `body_name`, and
`type_source = 'title'` from `classify_title(title)` on INSERT, and on UPDATE
only while the row's `type_source` is `title` and it is not locked
(`type_locked_at IS NULL`). A row the resolver placed on the calendar or
schedule rung, or an admin locked, keeps its classification while `title`,
dates, and links still update. The event-* upgrade path is gated the same way.

M4 adds the end-to-end cases: the seeded city carries Birmingham's
`council_schedule` and `calendar_url` metadata, and `resolve_and_store` /
`reclassify_city` (imported inside the tests so the file collects before
the module exists) move rows between rungs from the calendar table and the
schedule rule, recomputing the whole ladder each run.

Pattern: tests/integration/test_ingest_reconciliation.py.
Plan: plans/active/meeting-types-name-the-body.md (M2, M4).
"""

from datetime import date, datetime, timezone

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
            INSERT INTO municipalities (slug, name, state, adapter_class, adapter_config, active, metadata)
            VALUES (%s, 'Test Meeting Types', 'AL', 'GranicusAdapter',
                    '{"view_id": 1, "base_url": "https://example.com"}'::jsonb, TRUE,
                    '{"council_schedule": {"weekday": 1}, "calendar_url": "https://example.com/council"}'::jsonb)
            ON CONFLICT (slug) DO UPDATE SET active = TRUE, metadata = EXCLUDED.metadata
            RETURNING id
            """,
            (TEST_SLUG,),
        )
        mid = cur.fetchone()[0]
        _cleanup(cur, mid)
    yield mid
    with db() as conn, conn.cursor() as cur:
        _cleanup(cur, mid)


def _cleanup(cur, mid: int) -> None:
    cur.execute(
        "DELETE FROM meetings WHERE municipality_id = %s AND (external_id LIKE %s OR external_id LIKE 'event-%%')",
        (mid, PREFIX + "%"),
    )
    cur.execute("DELETE FROM city_calendar_events WHERE municipality_id = %s", (mid,))


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


class TestDuration:
    """`duration_s` is written on INSERT and kept by an UPDATE that brings none (plans/active/youtube-council-channel.md, M2)."""

    @staticmethod
    def _duration(muni_id: int, external_id: str):
        with db_cursor() as cur:
            cur.execute(
                "SELECT duration_s FROM meetings WHERE municipality_id = %s AND external_id = %s",
                (muni_id, external_id),
            )
            return cur.fetchone()["duration_s"]

    def test_insert_writes_and_a_null_update_keeps_the_duration(self, muni_id):
        from dataclasses import replace

        with_duration = replace(_meeting("mtype-dur", "Regular City Council Meeting"), duration_s=1500)
        assert _upsert_meetings(muni_id, [with_duration]) == (1, 0)
        assert self._duration(muni_id, "mtype-dur") == 1500
        assert _upsert_meetings(muni_id, [_meeting("mtype-dur", "Regular City Council Meeting")]) == (0, 1)
        assert self._duration(muni_id, "mtype-dur") == 1500
        assert _upsert_meetings(muni_id, [replace(with_duration, duration_s=1560)]) == (0, 1)
        assert self._duration(muni_id, "mtype-dur") == 1560

    def test_event_upgrade_writes_the_duration(self, muni_id):
        from dataclasses import replace

        _upsert_meetings(muni_id, [_meeting("event-9003", "Regular City Council Meeting")])
        clip = replace(_meeting("mtype-9003", "Regular City Council Meeting"), duration_s=360)
        assert _upsert_meetings(muni_id, [clip]) == (0, 1)
        assert self._duration(muni_id, "mtype-9003") == 360


# --- M4: resolution after ingest -------------------------------------------

GENERIC = "Regular City Council Meeting"
MONDAY = date(2026, 10, 19)
TUESDAY = date(2026, 10, 20)
WEDNESDAY = date(2026, 10, 21)
COW_TITLE = "COMMITTEE OF THE WHOLE/ADMINISTRATION & GOVERNMENTAL AFFAIRS COMMITTEE MEETING, October 21, 2026"
COW_NAME = "Committee of the Whole / Administration & Governmental Affairs"


def _calendar_event(muni_id: int, source_event_id: str, title: str, starts_at: datetime) -> int:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO city_calendar_events
                   (municipality_id, source_event_id, title, starts_at, source_url)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (muni_id, source_event_id, title, starts_at, f"https://example.com/events/{source_event_id}"),
        )
        return cur.fetchone()[0]


def _row(muni_id: int, external_id: str) -> dict:
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, meeting_type, session_kind, body_name, type_source, calendar_event_id, executive_summary "
            "FROM meetings WHERE municipality_id = %s AND external_id = %s",
            (muni_id, external_id),
        )
        return dict(cur.fetchone())


def _five(r: dict) -> tuple:
    return (r["meeting_type"], r["session_kind"], r["body_name"], r["type_source"], r["calendar_event_id"])


class TestResolveAndStore:
    def test_calendar_match_then_gated_upsert_then_minutes_flip_back(self, muni_id):
        from docket.services.meeting_types import resolve_and_store

        event_id = _calendar_event(muni_id, "4854", COW_TITLE, datetime(2026, 10, 21, 20, 30, tzinfo=timezone.utc))
        raw = _meeting("mtype-cow", GENERIC, WEDNESDAY)
        _upsert_meetings(muni_id, [raw])
        row = _row(muni_id, "mtype-cow")
        assert _five(row) == ("council", "regular", None, "title", None)

        assert resolve_and_store(muni_id, [row["id"]]) == 1
        assert _five(_row(muni_id, "mtype-cow")) == ("committee", "regular", COW_NAME, "calendar", event_id)

        # The gated writer leaves a resolved row alone.
        _upsert_meetings(muni_id, [raw])
        assert _five(_row(muni_id, "mtype-cow")) == ("committee", "regular", COW_NAME, "calendar", event_id)

        # A second resolution changes nothing.
        assert resolve_and_store(muni_id, [row["id"]]) == 0

        # Minutes arrive: the resolver recomputes the whole ladder.
        _set(muni_id, "mtype-cow", "minutes_url = 'x'")
        assert resolve_and_store(muni_id, [row["id"]]) == 1
        assert _five(_row(muni_id, "mtype-cow")) == ("council", "regular", None, "title", None)

    def test_schedule_rule_and_locked_row(self, muni_id):
        from docket.services.meeting_types import resolve_and_store

        _upsert_meetings(muni_id, [
            _meeting("mtype-mon", GENERIC, MONDAY),
            _meeting("mtype-tue", GENERIC, TUESDAY),
            _meeting("mtype-locked", GENERIC, MONDAY),
        ])
        _set(muni_id, "mtype-locked",
             "meeting_type = 'board', session_kind = 'regular', body_name = 'Library Board', "
             "type_source = 'admin', type_locked_at = now()")
        ids = [_row(muni_id, e)["id"] for e in ("mtype-mon", "mtype-tue", "mtype-locked")]
        assert resolve_and_store(muni_id, ids) == 1
        assert _five(_row(muni_id, "mtype-mon")) == ("committee", "regular", None, "schedule_rule", None)
        assert _five(_row(muni_id, "mtype-tue")) == ("council", "regular", None, "title", None)
        assert _five(_row(muni_id, "mtype-locked")) == ("board", "regular", "Library Board", "admin", None)

    def test_youtube_recording_names_the_row_primary_first(self, muni_id):
        """`_MEETING_ROWS_SQL` carries the row's YouTube clean titles, primary
        first. Plan: plans/active/youtube-council-channel.md (M3)."""
        from docket.services.meeting_types import resolve_and_store

        _upsert_meetings(muni_id, [_meeting("mtype-yt", GENERIC, TUESDAY)])
        mid = _row(muni_id, "mtype-yt")["id"]
        with db() as conn, conn.cursor() as cur:
            for vid, clean, primary in (("mtypeA", "Public Safety Committee Meeting", False),
                                        ("mtypeB", "Budget and Finance Committee Meeting", True)):
                cur.execute(
                    "INSERT INTO meeting_videos (meeting_id, provider, video_id, url, title, clean_title, is_primary) "
                    "VALUES (%s, 'youtube', %s, %s, %s, %s, %s)",
                    (mid, vid, f"https://www.youtube.com/watch?v={vid}", clean + " 10.20.26", clean, primary),
                )
        assert resolve_and_store(muni_id, [mid]) == 1
        assert _five(_row(muni_id, "mtype-yt")) == (
            "committee", "regular", "Budget and Finance Committee", "video", None,
        )
        assert resolve_and_store(muni_id, [mid]) == 0

    def test_empty_id_list_writes_nothing(self, muni_id):
        from docket.services.meeting_types import resolve_and_store

        assert resolve_and_store(muni_id, []) == 0


class TestReclassifyCity:
    def test_dry_run_then_write_then_diagonal(self, muni_id):
        from docket.services.meeting_types import reclassify_city

        event_id = _calendar_event(muni_id, "4854", COW_TITLE, datetime(2026, 10, 21, 20, 30, tzinfo=timezone.utc))
        _upsert_meetings(muni_id, [
            _meeting("mtype-r-mon", GENERIC, MONDAY),
            _meeting("mtype-r-old", GENERIC, date(2025, 12, 22)),      # a Monday before 2026
            _meeting("mtype-r-tue", GENERIC, TUESDAY),
            _meeting("mtype-r-wed", GENERIC, WEDNESDAY),
            _meeting("mtype-r-test", "Granicus Test", TUESDAY),
        ])
        _set(muni_id, "mtype-r-mon",
             "executive_summary = 'written as a council meeting', ai_prompt_version = 3, ai_generated_at = now()")
        _set(muni_id, "mtype-r-tue", "executive_summary = 'the council met', ai_prompt_version = 3")

        dry = reclassify_city(TEST_SLUG, dry_run=True)
        assert dry.written == 0 and dry.summaries_cleared == 0
        assert dry.transitions == {
            ("council", "regular", "committee", "regular", "schedule_rule"): 2,
            ("council", "regular", "committee", "regular", "calendar"): 1,
            ("council", "regular", "council", "regular", "title"): 1,
            ("other", "regular", "other", "regular", "title"): 1,
        }
        assert [(r["id"], r["meeting_date"], r["title"], r["item_count"]) for r in dry.rule_rows_before_2026] == [
            (_row(muni_id, "mtype-r-old")["id"], date(2025, 12, 22), GENERIC, 0),
        ]
        assert _five(_row(muni_id, "mtype-r-mon")) == ("council", "regular", None, "title", None), "a dry run writes nothing"
        assert _row(muni_id, "mtype-r-mon")["executive_summary"] == "written as a council meeting"

        wet = reclassify_city(TEST_SLUG, dry_run=False)
        assert wet.written == 3
        assert wet.summaries_cleared == 1
        assert _five(_row(muni_id, "mtype-r-mon")) == ("committee", "regular", None, "schedule_rule", None)
        assert _five(_row(muni_id, "mtype-r-wed")) == ("committee", "regular", COW_NAME, "calendar", event_id)
        assert _row(muni_id, "mtype-r-mon")["executive_summary"] is None
        assert _row(muni_id, "mtype-r-tue")["executive_summary"] == "the council met", "a row that stays council keeps its summary"
        with db_cursor() as cur:
            cur.execute(
                "SELECT executive_summary_voice, ai_prompt_version, ai_generated_at FROM meetings "
                "WHERE municipality_id = %s AND external_id = 'mtype-r-mon'",
                (muni_id,),
            )
            assert tuple(cur.fetchone().values()) == (None, None, None)

        again = reclassify_city(TEST_SLUG, dry_run=True)
        assert again.written == 0
        assert all(old_t == new_t and old_k == new_k for (old_t, old_k, new_t, new_k, _s) in again.transitions)
        assert sum(again.transitions.values()) == 5
