"""Integration tests: docket.services.city_calendar fills city_calendar_events idempotently.

`refresh_city_calendar(municipality_id, url)` fetches the page (patched here
to the committed fixture's events) and upserts every event on
`(municipality_id, source_event_id)`, so a second run changes no row count and
a changed title overwrites. `refresh_all()` selects every active city whose
metadata carries `calendar_url` and isolates a failure per city.

Pattern: tests/integration/test_ingest_meeting_types.py (the seeded test
municipality and prefix cleanup).
Plan: plans/active/meeting-types-name-the-body.md (M3).
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from docket.config import DATABASE_URL
from docket.db import db, db_cursor


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Integration tests require local DB; will not run against Railway prod",
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "city_calendar" / "birmingham_council_page.html"
TEST_SLUG = "test_city_calendar"
TEST_URL = "https://example.test/government/city-council"


@pytest.fixture
def muni_id():
    """Seed a test municipality whose metadata carries calendar_url; delete its calendar rows before and after."""
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO municipalities (slug, name, state, adapter_class, adapter_config, active, metadata)
            VALUES (%s, 'Test City Calendar', 'AL', 'GranicusAdapter',
                    '{"view_id": 1, "base_url": "https://example.com"}'::jsonb, TRUE,
                    %s::jsonb)
            ON CONFLICT (slug) DO UPDATE SET active = TRUE, metadata = EXCLUDED.metadata
            RETURNING id
            """,
            (TEST_SLUG, '{"calendar_url": "%s"}' % TEST_URL),
        )
        mid = cur.fetchone()[0]
        cur.execute("DELETE FROM city_calendar_events WHERE municipality_id = %s", (mid,))
    yield mid
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM city_calendar_events WHERE municipality_id = %s", (mid,))


def _fixture_events():
    from docket.adapters.city_calendar import parse_birminghamal_page

    return parse_birminghamal_page(FIXTURE.read_text(encoding="utf-8"), "https://www.birminghamal.gov")


def _rows(muni_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            """SELECT source_event_id, title, starts_at, ends_at, source_url, categories, fetched_at
                 FROM city_calendar_events WHERE municipality_id = %s ORDER BY starts_at, source_event_id""",
            (muni_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def test_refresh_writes_every_event_once(muni_id):
    from docket.services.city_calendar import refresh_city_calendar

    with patch("docket.services.city_calendar.fetch_birminghamal_events", return_value=_fixture_events()) as mock_fetch:
        n = refresh_city_calendar(muni_id, TEST_URL)

    mock_fetch.assert_called_once_with(TEST_URL)
    assert n == 4
    rows = _rows(muni_id)
    assert [r["source_event_id"] for r in rows] == ["4848", "4858", "4854", "4864"]
    assert rows[2]["title"] == "COMMITTEE OF THE WHOLE/ADMINISTRATION & GOVERNMENTAL AFFAIRS COMMITTEE MEETING, October 21, 2026"
    assert rows[2]["starts_at"].isoformat() == "2026-10-21T20:30:00+00:00"
    assert rows[2]["ends_at"].isoformat() == "2026-10-21T22:00:00+00:00"
    assert rows[2]["source_url"].endswith("/events/2026-10-21committee-wholeadministration-governmental-affairs-committee-meeting-october-21-2026")
    assert rows[2]["categories"] == [
        "Committee of the Whole / Administration & Governmental Affairs",
        "Community Development Committee",
    ]
    assert all(r["fetched_at"] is not None for r in rows)


def test_second_refresh_changes_no_row_count_and_overwrites_a_changed_title(muni_id):
    from dataclasses import replace

    from docket.services.city_calendar import refresh_city_calendar

    events = _fixture_events()
    with patch("docket.services.city_calendar.fetch_birminghamal_events", return_value=events):
        assert refresh_city_calendar(muni_id, TEST_URL) == 4
    first = _rows(muni_id)

    changed = [replace(events[0], title="BIRMINGHAM CITY COUNCIL MEETING (RESCHEDULED), October 20, 2026")] + events[1:]
    with patch("docket.services.city_calendar.fetch_birminghamal_events", return_value=changed):
        assert refresh_city_calendar(muni_id, TEST_URL) == 4
    second = _rows(muni_id)

    assert len(first) == len(second) == 4
    assert second[0]["title"] == "BIRMINGHAM CITY COUNCIL MEETING (RESCHEDULED), October 20, 2026"
    assert [r["title"] for r in second[1:]] == [r["title"] for r in first[1:]]
    assert all(s["fetched_at"] >= f["fetched_at"] for s, f in zip(second, first))


def test_refresh_with_no_events_writes_nothing(muni_id):
    from docket.services.city_calendar import refresh_city_calendar

    with patch("docket.services.city_calendar.fetch_birminghamal_events", return_value=[]):
        assert refresh_city_calendar(muni_id, TEST_URL) == 0
    assert _rows(muni_id) == []


def test_refresh_all_selects_cities_with_a_calendar_url_and_isolates_a_failure(muni_id, caplog):
    from docket.services import city_calendar

    calls: list[tuple[int, str]] = []

    def fake_refresh(municipality_id: int, url: str) -> int:
        calls.append((municipality_id, url))
        if municipality_id == muni_id:
            raise RuntimeError("city site down")
        return 4

    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM municipalities WHERE active = TRUE AND metadata ? 'calendar_url'")
        expected = cur.fetchone()["n"]

    with patch("docket.services.city_calendar.refresh_city_calendar", side_effect=fake_refresh), \
         caplog.at_level("INFO"):
        refreshed = city_calendar.refresh_all()

    assert (muni_id, TEST_URL) in calls
    assert len(calls) == expected
    assert refreshed == expected - 1
    assert any(f"city_calendar: {TEST_SLUG} failed" in r.message for r in caplog.records)
    assert any("events upserted" in r.getMessage() for r in caplog.records if r.levelname == "INFO") or expected == 1


def test_refresh_all_skips_a_city_without_a_calendar_url(muni_id):
    from docket.services import city_calendar

    with db() as conn, conn.cursor() as cur:
        cur.execute("UPDATE municipalities SET metadata = metadata - 'calendar_url' WHERE id = %s", (muni_id,))
    try:
        with patch("docket.services.city_calendar.refresh_city_calendar", return_value=0) as mock_refresh:
            city_calendar.refresh_all()
        assert all(c.args[0] != muni_id for c in mock_refresh.call_args_list)
    finally:
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE municipalities SET metadata = metadata || %s::jsonb WHERE id = %s",
                ('{"calendar_url": "%s"}' % TEST_URL, muni_id),
            )
