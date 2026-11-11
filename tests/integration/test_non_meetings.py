"""Integration tests: docket.services.non_meetings hides a clip that is not a meeting, and only that.

A clip is hidden when its title is the clerk's generic one, it has no
agenda link, minutes link, agenda item, or YouTube recording, it is not
locked, not a `yt-` row, and not exempt (`keep_visible_at`), the stored
calendar shows no council or committee event on its date, its date is on or
after the city's `calendar_complete_from` and at least four days past, the
calendar was read in the last 36 hours, and either it runs under 600
seconds or its transcript's status is `low_speech`. A clip that meets all
of it but has a public transcript is held back and listed, not hidden.

Every test seeds one test city and passes a fixed `today`, so nothing
depends on the day the suite runs. The service is imported inside each
test so the file collects before the module exists.

Pattern: tests/integration/test_ingest_meeting_types.py (the seeded test
municipality and prefix cleanup).
Plan `committee-clips-named-or-hidden`, M4.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from docket.config import DATABASE_URL
from docket.db import db, db_cursor

pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Integration tests require local DB; will not run against Railway prod",
)

TEST_SLUG = "test_non_meetings"
OTHER_SLUG = "test_non_meetings_other"
PREFIX = "nonm-"
GENERIC = "Regular City Council Meeting"
TODAY = date(2026, 11, 11)
COMPLETE_FROM = date(2026, 10, 5)
DAY = date(2026, 10, 15)  # a Thursday with nothing on the calendar
METADATA = '{"calendar_url": "https://example.test/council", "calendar_complete_from": "2026-10-05"}'


def _seed_city(cur, slug: str, metadata: str, *, active: bool = True) -> int:
    cur.execute(
        """
        INSERT INTO municipalities (slug, name, state, adapter_class, adapter_config, active, metadata)
        VALUES (%s, %s, 'AL', 'GranicusAdapter',
                '{"view_id": 1, "base_url": "https://example.com"}'::jsonb, %s, %s::jsonb)
        ON CONFLICT (slug) DO UPDATE SET active = EXCLUDED.active, metadata = EXCLUDED.metadata
        RETURNING id
        """,
        (slug, "Test " + slug, active, metadata),
    )
    return cur.fetchone()[0]


def _cleanup(cur, mid: int) -> None:
    cur.execute("DELETE FROM meetings WHERE municipality_id = %s", (mid,))
    cur.execute("DELETE FROM city_calendar_events WHERE municipality_id = %s", (mid,))


@pytest.fixture
def city():
    """The test city, its calendar read a moment ago: one event far from every test's day."""
    with db() as conn, conn.cursor() as cur:
        mid = _seed_city(cur, TEST_SLUG, METADATA)
        other = _seed_city(cur, OTHER_SLUG, "{}")
        _cleanup(cur, mid)
        _cleanup(cur, other)
    _event(mid, "fresh", "PUBLIC SAFETY COMMITTEE MEETING, September 1, 2026", datetime(2026, 9, 1, 19, tzinfo=timezone.utc))
    yield mid
    with db() as conn, conn.cursor() as cur:
        _cleanup(cur, mid)
        _cleanup(cur, other)
        cur.execute("DELETE FROM municipalities WHERE slug IN (%s, %s)", (TEST_SLUG, OTHER_SLUG))


def _event(mid: int, tag: str, title: str, starts_at: datetime, *, status: str | None = None) -> None:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO city_calendar_events (municipality_id, source_event_id, title, starts_at, source_url, event_status)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (mid, PREFIX + tag, title, starts_at, f"https://example.test/events/{tag}", status),
        )


def _clip(mid: int, tag: str, *, day: date = DAY, duration_s: int | None = 240, title: str = GENERIC,
          external_id: str | None = None, **columns) -> int:
    """One clip of the test city; `columns` are further `meetings` columns."""
    names = ["municipality_id", "external_id", "title", "meeting_date", "meeting_type", "duration_s", *columns]
    values = [mid, external_id or PREFIX + tag, title, day, "council", duration_s, *columns.values()]
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO meetings ({', '.join(names)}) VALUES ({', '.join(['%s'] * len(names))}) RETURNING id",
            values,
        )
        return cur.fetchone()[0]


def _transcript(meeting_id: int, status: str, *, uploaded: bool) -> None:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO transcripts (meeting_id, status, uploaded_at) VALUES (%s, %s, %s)",
            (meeting_id, status, datetime.now(timezone.utc) if uploaded else None),
        )


def _state(meeting_id: int) -> dict:
    with db_cursor() as cur:
        cur.execute(
            "SELECT is_hidden, hidden_at, hidden_by, hidden_reason, keep_visible_at FROM meetings WHERE id = %s",
            (meeting_id,),
        )
        return dict(cur.fetchone())


def _run(**kwargs) -> tuple[list[int], list[int]]:
    """Run the rule over every active city and return the test city's (hidden ids, held-back ids)."""
    from docket.services.non_meetings import hide_non_meetings

    return hide_non_meetings(today=TODAY, **kwargs).get(TEST_SLUG, ([], []))


def _hidden(meeting_id: int) -> bool:
    return _state(meeting_id)["is_hidden"]


# --- the clip the rule is for ------------------------------------------------


def test_a_short_generic_clip_on_an_empty_day_is_hidden_with_its_reason(city):
    clip = _clip(city, "short")

    hidden, held = _run()

    assert (hidden, held) == ([clip], [])
    state = _state(clip)
    assert state["is_hidden"] is True
    assert state["hidden_reason"] == "not_a_meeting"
    assert state["hidden_at"] is not None
    assert state["hidden_by"] is None, "no admin hid it"
    assert state["keep_visible_at"] is None


def test_a_second_run_hides_nothing_new(city):
    clip = _clip(city, "short")
    assert _run() == ([clip], [])
    first = _state(clip)

    assert _run() == ([], [])
    assert _state(clip) == first, "the row is not written again"


def test_a_dry_run_names_the_clip_and_writes_nothing(city):
    clip = _clip(city, "short")

    assert _run(dry_run=True) == ([clip], [])
    assert _state(clip)["is_hidden"] is False
    assert _state(clip)["hidden_reason"] is None


def test_find_returns_the_facts_the_script_prints(city):
    from docket.services.non_meetings import find

    clip = _clip(city, "short")
    held = _clip(city, "held", day=DAY + timedelta(days=1))
    _transcript(held, "compared", uploaded=True)

    municipality = {"id": city, "slug": TEST_SLUG, "name": "Test", "metadata": {
        "calendar_url": "https://example.test/council", "calendar_complete_from": "2026-10-05"}}
    to_hide, held_back = find(municipality, TODAY)

    assert [(r["id"], r["meeting_date"], r["title"], r["duration_s"], r["transcript_status"]) for r in to_hide] == [
        (clip, DAY, GENERIC, 240, None)
    ]
    assert [(r["id"], r["transcript_status"], r["city_slug"]) for r in held_back] == [(held, "compared", TEST_SLUG)]
    assert [r["city_name"] for r in to_hide + held_back] == ["Test", "Test"], "asserted after the failing-first commit `39ee32e`"


# --- what keeps a clip visible: the calendar ---------------------------------


def test_a_committee_event_on_the_day_keeps_the_clip(city):
    clip = _clip(city, "short")
    _event(city, "ev", "ARTS AND PARKS COMMITTEE MEETING, October 15, 2026", datetime(2026, 10, 15, 19, tzinfo=timezone.utc))

    assert _run() == ([], [])
    assert not _hidden(clip)


def test_a_council_event_on_the_day_keeps_the_clip(city):
    clip = _clip(city, "short")
    _event(city, "ev", "CITY COUNCIL MEETING, October 15, 2026", datetime(2026, 10, 15, 14, 30, tzinfo=timezone.utc))

    assert _run() == ([], [])
    assert not _hidden(clip)


def test_a_cancelled_committee_event_still_keeps_the_clip(city):
    """For naming a cancelled event counts for nothing; for hiding, any event on the day is a reason to leave the clip."""
    by_status = _clip(city, "status")
    _event(city, "ev1", "ARTS AND PARKS COMMITTEE MEETING, October 15, 2026",
           datetime(2026, 10, 15, 19, tzinfo=timezone.utc), status="cancelled")
    by_title = _clip(city, "title", day=date(2026, 10, 22))
    _event(city, "ev2", "CANCELLED: ARTS AND PARKS COMMITTEE MEETING, October 22, 2026",
           datetime(2026, 10, 22, 19, tzinfo=timezone.utc), status="active")

    assert _run() == ([], [])
    assert not _hidden(by_status) and not _hidden(by_title)


def test_an_event_that_is_neither_council_nor_committee_keeps_nothing(city):
    clip = _clip(city, "short")
    _event(city, "ev", "District 4 Holiday Hams Giveaway", datetime(2026, 10, 15, 19, tzinfo=timezone.utc))

    assert _run() == ([clip], [])


def test_the_events_day_is_read_in_chicago(city):
    """An event at 01:00 UTC on the 16th is the evening of the 15th in Birmingham."""
    on_the_15th = _clip(city, "d15", day=date(2026, 10, 15))
    on_the_16th = _clip(city, "d16", day=date(2026, 10, 16))
    _event(city, "ev", "ARTS AND PARKS COMMITTEE MEETING, October 15, 2026", datetime(2026, 10, 16, 1, tzinfo=timezone.utc))

    assert _run() == ([on_the_16th], [])
    assert not _hidden(on_the_15th)


def test_another_citys_event_keeps_nothing(city):
    clip = _clip(city, "short")
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = %s", (OTHER_SLUG,))
        other = cur.fetchone()["id"]
    _event(other, "ev", "ARTS AND PARKS COMMITTEE MEETING, October 15, 2026", datetime(2026, 10, 15, 19, tzinfo=timezone.utc))

    assert _run() == ([clip], [])


def test_another_citys_clip_is_not_this_citys_to_hide(city):
    """Added after the failing-first commit `39ee32e`: the rows read are this city's."""
    clip = _clip(city, "short")
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = %s", (OTHER_SLUG,))
        other = cur.fetchone()["id"]
    others_clip = _clip(other, "others")

    assert _run() == ([clip], [])
    assert not _hidden(others_clip)


# --- the brakes on the calendar itself ---------------------------------------


def test_nothing_is_hidden_while_the_calendar_was_last_read_two_days_ago(city, caplog):
    clip = _clip(city, "short")
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE city_calendar_events SET fetched_at = now() - interval '2 days' WHERE municipality_id = %s", (city,)
        )

    with caplog.at_level("WARNING", logger="docket.services.non_meetings"):
        assert _run() == ([], [])

    assert not _hidden(clip)
    assert any(TEST_SLUG in r.getMessage() and "36" in r.getMessage() for r in caplog.records), "the log says why"


def test_the_calendar_read_35_hours_ago_is_fresh_enough(city):
    clip = _clip(city, "short")
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE city_calendar_events SET fetched_at = now() - interval '35 hours' WHERE municipality_id = %s", (city,)
        )

    assert _run() == ([clip], [])


def test_one_fresh_event_is_enough_beside_old_ones(city):
    """The newest read is what is tested: past events the sitemap reader stored once are never fetched again."""
    clip = _clip(city, "short")
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE city_calendar_events SET fetched_at = now() - interval '30 days' WHERE municipality_id = %s", (city,)
        )
    _event(city, "new", "PUBLIC SAFETY COMMITTEE MEETING, November 30, 2026", datetime(2026, 11, 30, 19, tzinfo=timezone.utc))

    assert _run() == ([clip], [])


def test_nothing_is_hidden_when_the_calendar_holds_no_event_at_all(city):
    clip = _clip(city, "short")
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM city_calendar_events WHERE municipality_id = %s", (city,))

    assert _run() == ([], [])
    assert not _hidden(clip)


def test_another_citys_fresh_calendar_does_not_stand_for_this_one(city):
    """Added after the failing-first commit `39ee32e`: the freshness read is this city's."""
    clip = _clip(city, "short")
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE city_calendar_events SET fetched_at = now() - interval '2 days' WHERE municipality_id = %s", (city,)
        )
        cur.execute("SELECT id FROM municipalities WHERE slug = %s", (OTHER_SLUG,))
        other = cur.fetchone()[0]
    _event(other, "ev", "PUBLIC SAFETY COMMITTEE MEETING, November 30, 2026", datetime(2026, 11, 30, 19, tzinfo=timezone.utc))

    assert _run() == ([], [])
    assert not _hidden(clip)


def test_a_city_without_calendar_complete_from_or_calendar_url_is_left_alone(city):
    from docket.services.non_meetings import find

    clip = _clip(city, "short")
    full = {"calendar_url": "https://example.test/council", "calendar_complete_from": "2026-10-05"}
    for missing in full:
        metadata = {k: v for k, v in full.items() if k != missing}
        assert find({"id": city, "slug": TEST_SLUG, "metadata": metadata}, TODAY) == ([], []), missing
    assert [r["id"] for r in find({"id": city, "slug": TEST_SLUG, "metadata": full}, TODAY)[0]] == [clip]


def test_an_inactive_city_is_not_run(city):
    clip = _clip(city, "short")
    with db() as conn, conn.cursor() as cur:
        cur.execute("UPDATE municipalities SET active = FALSE WHERE id = %s", (city,))

    assert _run() == ([], [])
    assert not _hidden(clip)


# --- what keeps a clip visible: its date -------------------------------------


def test_a_clip_dated_before_calendar_complete_from_is_left(city):
    before = _clip(city, "before", day=COMPLETE_FROM - timedelta(days=1))
    on = _clip(city, "on", day=COMPLETE_FROM)

    assert _run() == ([on], [])
    assert not _hidden(before)


def test_a_clip_three_days_old_is_left_and_one_four_days_old_is_hidden(city):
    three = _clip(city, "three", day=TODAY - timedelta(days=3))
    four = _clip(city, "four", day=TODAY - timedelta(days=4))

    assert _run() == ([four], [])
    assert not _hidden(three)


# --- what keeps a clip visible: its own facts --------------------------------


@pytest.mark.parametrize("column,value", [
    ("agenda_url", "https://example.test/agenda.pdf"),
    ("minutes_url", "https://example.test/minutes.pdf"),
    ("keep_visible_at", datetime(2026, 11, 1, tzinfo=timezone.utc)),
    ("type_locked_at", datetime(2026, 11, 1, tzinfo=timezone.utc)),
])
def test_a_clip_with_this_column_set_is_left(city, column, value):
    clip = _clip(city, "kept", **{column: value})

    assert _run(dry_run=True) == ([], []), "the read itself leaves the row out; the write's own conditions are a second guard"
    assert _run() == ([], [])
    assert not _hidden(clip)


def test_a_clip_with_an_agenda_item_is_left(city):
    clip = _clip(city, "items")
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO agenda_items (meeting_id, title, item_number, processing_status) VALUES (%s, 'x', '1', 'pending')",
            (clip,),
        )

    assert _run() == ([], [])
    assert not _hidden(clip)


def test_a_clip_with_a_youtube_recording_is_left(city):
    """`meeting_videos.provider` admits only `youtube` (migration 040's CHECK), so no other provider's row can be seeded beside it."""
    clip = _clip(city, "yt")
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO meeting_videos (meeting_id, provider, video_id, url, title, clean_title, duration_s, is_primary)
               VALUES (%s, 'youtube', %s, 'https://example.test/v', 'x', 'x', 240, TRUE)""",
            (clip, f"NONM{clip}"),
        )

    assert _run() == ([], [])
    assert not _hidden(clip)


def test_a_yt_row_is_left(city):
    clip = _clip(city, "yt-row", external_id="yt-nonm-1")

    assert _run() == ([], [])
    assert not _hidden(clip)


def test_a_clip_whose_title_names_a_body_is_left(city):
    clip = _clip(city, "named", title="Public Safety Committee")

    assert _run() == ([], [])
    assert not _hidden(clip)


def test_a_clip_whose_title_says_cancelled_is_left(city):
    clip = _clip(city, "cancelled", title="Regular City Council Meeting - Cancelled")

    assert _run() == ([], [])
    assert not _hidden(clip)


def test_a_row_an_admin_already_hid_keeps_its_reason(city):
    clip = _clip(city, "admin", is_hidden=True, hidden_reason="admin")

    assert _run(dry_run=True) == ([], [])
    assert _run() == ([], [])
    assert _state(clip)["hidden_reason"] == "admin"


@pytest.mark.parametrize("change,expected_reason", [
    ("keep_visible_at = now()", None),
    ("is_hidden = TRUE, hidden_reason = 'admin'", "admin"),
])
def test_a_row_an_admin_changed_between_the_read_and_the_write_is_left_as_the_admin_put_it(
    city, monkeypatch, change, expected_reason
):
    """Added after the failing-first commit `39ee32e`: the UPDATE repeats the rule's two conditions on the row's own state."""
    from docket.services import non_meetings

    changed = _clip(city, "changed")
    untouched = _clip(city, "untouched", day=DAY + timedelta(days=1))
    real_find = non_meetings.find

    def find(municipality, today):
        found = real_find(municipality, today)
        if municipality["slug"] == TEST_SLUG:
            with db() as conn, conn.cursor() as cur:
                cur.execute(f"UPDATE meetings SET {change} WHERE id = %s", (changed,))
        return found

    monkeypatch.setattr(non_meetings, "find", find)

    assert _run() == ([untouched], []), "the ids returned are the rows written, not the rows read"
    assert _state(changed)["hidden_reason"] == expected_reason
    assert _state(changed)["hidden_at"] is None


# --- short, or without speech ------------------------------------------------


def test_a_clip_of_unknown_length_without_a_transcript_is_left(city):
    clip = _clip(city, "unknown", duration_s=None)

    assert _run() == ([], [])
    assert not _hidden(clip)


def test_a_clip_of_exactly_600_seconds_is_not_short(city):
    at = _clip(city, "at", duration_s=600)
    under = _clip(city, "under", duration_s=599, day=DAY + timedelta(days=1))

    assert _run() == ([under], [])
    assert not _hidden(at)


def test_a_long_clip_is_hidden_when_its_transcript_is_low_speech_and_not_otherwise(city):
    silent = _clip(city, "silent", duration_s=2400, day=date(2026, 10, 15))
    _transcript(silent, "low_speech", uploaded=True)
    untranscribed = _clip(city, "none", duration_s=2400, day=date(2026, 10, 16))
    spoken = _clip(city, "spoken", duration_s=2400, day=date(2026, 10, 22))
    _transcript(spoken, "compared", uploaded=True)

    assert _run() == ([silent], []), "a long clip with speech is neither hidden nor held back"
    assert not _hidden(untranscribed) and not _hidden(spoken)


def test_a_clip_of_unknown_length_is_hidden_when_its_transcript_is_low_speech(city):
    clip = _clip(city, "silent", duration_s=None)
    _transcript(clip, "low_speech", uploaded=False)

    assert _run() == ([clip], [])


def test_a_short_clip_with_a_public_transcript_is_held_back_and_listed(city):
    clip = _clip(city, "speech")
    _transcript(clip, "compared", uploaded=True)

    assert _run() == ([], [clip])
    assert not _hidden(clip)
    assert _state(clip)["hidden_reason"] is None


def test_a_short_clip_whose_transcript_was_never_uploaded_is_hidden(city):
    """A transcript that is not public (no upload) is no evidence of speech."""
    clip = _clip(city, "claimed")
    _transcript(clip, "claimed", uploaded=False)

    assert _run() == ([clip], [])


def test_a_short_clip_whose_uploaded_transcript_is_low_speech_is_hidden_not_held(city):
    clip = _clip(city, "quiet")
    _transcript(clip, "low_speech", uploaded=True)

    assert _run() == ([clip], [])


# --- one city failing --------------------------------------------------------


def test_a_city_that_fails_does_not_stop_the_others(city, monkeypatch):
    from docket.services import non_meetings

    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE municipalities SET active = TRUE, metadata = %s::jsonb WHERE slug = %s", (METADATA, OTHER_SLUG)
        )
    clip = _clip(city, "short")
    real_find = non_meetings.find

    def find(municipality, today):
        if municipality["slug"] == OTHER_SLUG:
            raise RuntimeError("boom")
        return real_find(municipality, today)

    monkeypatch.setattr(non_meetings, "find", find)

    result = non_meetings.hide_non_meetings(today=TODAY)

    assert result[TEST_SLUG] == ([clip], [])
    assert OTHER_SLUG not in result
