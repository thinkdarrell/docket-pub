"""Integration tests: docket.services.city_calendar fills city_calendar_events idempotently.

`refresh_city_calendar(municipality_id, metadata)` runs the readers the
city's metadata names (the council page, the events search, the sitemap's
event pages; each patched here to read the committed fixtures) and upserts
every event on `(municipality_id, source_event_id)`, so a second run changes
no row count and a changed title overwrites. A reader that fails does not
stop the others. `refresh_all()` selects every active city whose metadata
carries `calendar_url` and isolates a failure per city.

Pattern: tests/integration/test_ingest_meeting_types.py (the seeded test
municipality and prefix cleanup).
Plan: plans/completed/meeting-types-name-the-body.md (M3); the search and
sitemap readers are plan `committee-clips-named-or-hidden`, M1.
"""

import json
import re
from datetime import datetime, timezone

from pathlib import Path
from unittest.mock import patch

import pytest

from docket.config import DATABASE_URL
from docket.db import db, db_cursor


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Integration tests require local DB; will not run against Railway prod",
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "city_calendar"
FIXTURE = FIXTURES / "birmingham_council_page.html"
TEST_SLUG = "test_city_calendar"
TEST_URL = "https://example.test/government/city-council"
PAGE_ONLY = {"calendar_url": TEST_URL}

BASE_URL = "https://www.birminghamal.gov"
SEARCH_URL = BASE_URL + "/api/search/events"
SITEMAP_URL = BASE_URL + "/sitemap.xml"
# The keys the calendar-sources migration gives Birmingham, without calendar_url:
# these tests exercise the two new readers and leave the council page out.
SEARCH_AND_SITEMAP = {
    "calendar_search_url": SEARCH_URL,
    "calendar_department_id": "55",
    "calendar_department": "City Council",
    "calendar_sitemap_url": SITEMAP_URL,
}
COUNCIL_EVENT_URL = BASE_URL + "/events/2026-11-09transportation-infrastructure-committee-meeting-november-9-2026"
PLANNING_EVENT_URLS = {
    BASE_URL + "/events/2026-10-08framework-plan-implementation-committee-public-information-meeting",
    BASE_URL + "/events/2026-10-14framework-plan-implementation-committee-public-information-meeting",
}
# The one event both the search fixture and the sitemap fixture list.
SHARED_EVENT_URL = BASE_URL + "/events/2026-11-23budget-finance-committee-meeting-november-23-2026"
SEARCH_IDS = ["4943", "4964", "4965", "4967", "4969"]


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
            """SELECT source_event_id, title, starts_at, ends_at, source_url, categories, fetched_at, event_status
                 FROM city_calendar_events WHERE municipality_id = %s ORDER BY starts_at, source_event_id""",
            (muni_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def test_refresh_writes_every_event_once(muni_id):
    from docket.services.city_calendar import refresh_city_calendar

    with patch("docket.services.city_calendar.fetch_birminghamal_events", return_value=_fixture_events()) as mock_fetch:
        n = refresh_city_calendar(muni_id, PAGE_ONLY)

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
        assert refresh_city_calendar(muni_id, PAGE_ONLY) == 4
    first = _rows(muni_id)

    changed = [replace(events[0], title="BIRMINGHAM CITY COUNCIL MEETING (RESCHEDULED), October 20, 2026")] + events[1:]
    with patch("docket.services.city_calendar.fetch_birminghamal_events", return_value=changed):
        assert refresh_city_calendar(muni_id, PAGE_ONLY) == 4
    second = _rows(muni_id)

    assert len(first) == len(second) == 4
    assert second[0]["title"] == "BIRMINGHAM CITY COUNCIL MEETING (RESCHEDULED), October 20, 2026"
    assert [r["title"] for r in second[1:]] == [r["title"] for r in first[1:]]
    assert all(s["fetched_at"] >= f["fetched_at"] for s, f in zip(second, first))


def test_refresh_with_no_events_writes_nothing(muni_id):
    from docket.services.city_calendar import refresh_city_calendar

    with patch("docket.services.city_calendar.fetch_birminghamal_events", return_value=[]):
        assert refresh_city_calendar(muni_id, PAGE_ONLY) == 0
    assert _rows(muni_id) == []


def test_refresh_all_selects_cities_with_a_calendar_url_and_isolates_a_failure(muni_id, caplog):
    from docket.services import city_calendar

    calls: list[tuple[int, dict]] = []

    def fake_refresh(municipality_id: int, metadata: dict) -> int:
        calls.append((municipality_id, metadata))
        if municipality_id == muni_id:
            raise RuntimeError("city site down")
        return 4

    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM municipalities WHERE active = TRUE AND metadata ? 'calendar_url'")
        expected = cur.fetchone()["n"]

    with patch("docket.services.city_calendar.refresh_city_calendar", side_effect=fake_refresh), \
         caplog.at_level("INFO"):
        refreshed = city_calendar.refresh_all()

    assert (muni_id, {"calendar_url": TEST_URL}) in calls
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


# --- the search and the sitemap (plan committee-clips-named-or-hidden, M1) ---


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _search_events(*args, **kwargs):
    from docket.adapters.city_calendar import parse_search_page

    return parse_search_page(json.loads(_text("birmingham_events_search.json")), BASE_URL)[0]


def _sitemap_urls(*args) -> list[str]:
    from docket.adapters.city_calendar import parse_sitemap

    return parse_sitemap(_text("birmingham_sitemap.xml"))


_MONTHS = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"]


class EventPages:
    """Stands in for ``fetch_event_page``: every answer goes through ``parse_event_page``.

    The two pages saved from the city are served as saved. Every other URL
    of the sitemap fixture gets a page in the saved council page's shape,
    with an id of 9000 upward, the title and start read from the URL's own
    date, status ``active``, and the department "City Council" (or the
    Planning department's for the other Framework Plan page), so the
    department test is what keeps a page out.
    """

    def __init__(self, fail: set[str] | None = None):
        self.calls: list[str] = []
        self.fail = fail or set()
        self._ids: dict[str, str] = {}

    def __call__(self, url: str, department: str):
        from docket.adapters.city_calendar import parse_event_page

        self.calls.append(url)
        if url in self.fail:
            raise RuntimeError("event page down")
        if url == COUNCIL_EVENT_URL:
            return parse_event_page(_text("birmingham_event_council.html"), BASE_URL, department)
        if url.endswith("/2026-10-14framework-plan-implementation-committee-public-information-meeting"):
            return parse_event_page(_text("birmingham_event_planning.html"), BASE_URL, department)
        return parse_event_page(self._page(url), BASE_URL, department)

    def _page(self, url: str) -> str:
        path = url[len(BASE_URL):].rstrip("/")
        y, mo, d = (int(x) for x in re.match(r"/events/(\d{4})-(\d{2})-(\d{2})", path).groups())
        name = self._ids.setdefault(path, str(9000 + len(self._ids)))
        node = {
            "id": "4943" if url.rstrip("/") == SHARED_EVENT_URL else name,
            "title": f"{path[18:].replace('-', ' ').upper()}, {_MONTHS[mo]} {d}, {y}",
            "path": path,
            "department": {"name": "Planning, Engineering & Permits" if "framework-plan" in path else "City Council"},
            "startDate": {"time": f"{y:04d}-{mo:02d}-{d:02d}T20:00:00+00:00"},
            "endDate": {"time": f"{y:04d}-{mo:02d}-{d:02d}T21:30:00+00:00"},
            "eventStatus": "active",
            "eventCategories": None,
        }
        return '<html><body><script id="__NEXT_DATA__" type="application/json">%s</script></body></html>' % json.dumps(
            {"props": {"pageProps": {"nodeResource": node}}}
        )


def _run(muni_id: int, pages: EventPages, *, metadata: dict = SEARCH_AND_SITEMAP, search=_search_events,
         sitemap=_sitemap_urls) -> int:
    from docket.services.city_calendar import refresh_city_calendar

    with patch("docket.services.city_calendar.fetch_search_events", side_effect=search) as mock_search, \
         patch("docket.services.city_calendar.fetch_sitemap_event_urls", side_effect=sitemap) as mock_sitemap, \
         patch("docket.services.city_calendar.fetch_event_page", side_effect=pages), \
         patch("docket.services.city_calendar.fetch_birminghamal_events", return_value=[]) as mock_page:
        n = refresh_city_calendar(muni_id, metadata)
    if "calendar_url" not in metadata:
        mock_page.assert_not_called()
    if "calendar_search_url" in metadata:
        mock_search.assert_called_once_with(SEARCH_URL, "55", department="City Council")
    else:
        mock_search.assert_not_called()
    if "calendar_sitemap_url" in metadata:
        mock_sitemap.assert_called_once_with(SITEMAP_URL)
    else:
        mock_sitemap.assert_not_called()
    return n


def test_first_refresh_stores_the_search_and_the_sitemaps_council_events(muni_id):
    pages = EventPages()
    n = _run(muni_id, pages)

    rows = _rows(muni_id)
    by_id = {r["source_event_id"]: r for r in rows}
    # 5 from the search; the sitemap lists 33 pages, one of them the search's own
    # 4943 (not fetched) and two the Planning department's (fetched, not stored).
    assert n == 35
    assert len(rows) == 35
    assert set(SEARCH_IDS) <= set(by_id)
    assert by_id["4941"]["title"] == "TRANSPORTATION AND INFRASTRUCTURE COMMITTEE MEETING, November 9, 2026"
    assert by_id["4941"]["source_url"] == COUNCIL_EVENT_URL
    assert "4896" not in by_id, "the Planning department's committee is not the council's"
    assert not any("FRAMEWORK" in r["title"].upper() for r in rows)

    assert len(pages.calls) == 32
    assert SHARED_EVENT_URL not in pages.calls, "the search stored it; its page is not fetched"
    assert PLANNING_EVENT_URLS <= set(pages.calls)
    # newest first
    days = [u.rsplit("/", 1)[1][:10] for u in pages.calls]
    assert days == sorted(days, reverse=True)


def test_event_status_is_stored_from_the_event_pages(muni_id):
    _run(muni_id, EventPages())

    by_id = {r["source_event_id"]: r for r in _rows(muni_id)}
    from_pages = [r for sid, r in by_id.items() if sid not in SEARCH_IDS]
    assert len(from_pages) == 30
    assert {r["event_status"] for r in from_pages} == {"active"}
    # the search's results carry no status (the fixture has no eventStatus key)
    assert {by_id[sid]["event_status"] for sid in SEARCH_IDS} == {None}


def test_second_refresh_stores_nothing_new_and_fetches_no_stored_page(muni_id):
    _run(muni_id, EventPages())
    first = _rows(muni_id)

    pages = EventPages()
    n = _run(muni_id, pages)

    assert [r["source_event_id"] for r in _rows(muni_id)] == [r["source_event_id"] for r in first]
    assert n == 5, "the search's five are upserted again; the sitemap reader adds none"
    # only the two pages the department test rejected, which are never stored, are read again
    assert set(pages.calls) == PLANNING_EVENT_URLS and len(pages.calls) == 2


def test_a_page_the_search_stored_is_not_fetched_under_a_trailing_slash(muni_id):
    def with_slash(*args) -> list[str]:
        return [u + "/" if u == SHARED_EVENT_URL else u for u in _sitemap_urls()]

    pages = EventPages()
    _run(muni_id, pages, sitemap=with_slash)

    assert SHARED_EVENT_URL + "/" not in pages.calls and SHARED_EVENT_URL not in pages.calls
    assert len(pages.calls) == 32
    by_id = {r["source_event_id"]: r for r in _rows(muni_id)}
    assert by_id["4943"]["source_url"] == SHARED_EVENT_URL, "stored as the search spelled it"

    # and the sitemap's own events, stored without the slash, are skipped under it too
    again = EventPages()
    _run(muni_id, again, sitemap=lambda *a: [u + "/" for u in _sitemap_urls()])
    assert set(again.calls) == {u + "/" for u in PLANNING_EVENT_URLS}


def test_search_failure_does_not_stop_the_sitemap(muni_id, caplog):
    def down(*args, **kwargs):
        raise RuntimeError("search down")

    pages = EventPages()
    with caplog.at_level("ERROR"):
        n = _run(muni_id, pages, search=down)

    rows = _rows(muni_id)
    assert n == 31 and len(rows) == 31, "with nothing from the search, 4943 comes from its own page"
    assert {r["source_event_id"] for r in rows}.isdisjoint({"4964", "4965", "4967", "4969"})
    assert any(r["source_event_id"] == "4941" for r in rows)
    assert any("search" in r.getMessage() and r.exc_info for r in caplog.records)


def test_sitemap_failure_does_not_stop_the_search(muni_id, caplog):
    def down(*args):
        raise RuntimeError("sitemap down")

    with caplog.at_level("ERROR"):
        n = _run(muni_id, EventPages(), sitemap=down)

    assert n == 5
    assert sorted(r["source_event_id"] for r in _rows(muni_id)) == SEARCH_IDS
    assert any("sitemap" in r.getMessage() and r.exc_info for r in caplog.records)


def test_council_page_failure_does_not_stop_the_other_two(muni_id, caplog):
    from docket.services.city_calendar import refresh_city_calendar

    metadata = dict(SEARCH_AND_SITEMAP, calendar_url=TEST_URL)
    with patch("docket.services.city_calendar.fetch_birminghamal_events", side_effect=RuntimeError("page down")), \
         patch("docket.services.city_calendar.fetch_search_events", side_effect=_search_events), \
         patch("docket.services.city_calendar.fetch_sitemap_event_urls", side_effect=_sitemap_urls), \
         patch("docket.services.city_calendar.fetch_event_page", side_effect=EventPages()), \
         caplog.at_level("ERROR"):
        n = refresh_city_calendar(muni_id, metadata)

    assert n == 35 and len(_rows(muni_id)) == 35
    assert any("council page" in r.getMessage() and r.exc_info for r in caplog.records)


def test_every_reader_failing_raises(muni_id):
    from docket.services.city_calendar import refresh_city_calendar

    def down(*args, **kwargs):
        raise RuntimeError("city site down")

    metadata = dict(SEARCH_AND_SITEMAP, calendar_url=TEST_URL)
    with patch("docket.services.city_calendar.fetch_birminghamal_events", side_effect=down), \
         patch("docket.services.city_calendar.fetch_search_events", side_effect=down), \
         patch("docket.services.city_calendar.fetch_sitemap_event_urls", side_effect=down), \
         pytest.raises(RuntimeError):
        refresh_city_calendar(muni_id, metadata)
    assert _rows(muni_id) == []


def test_one_event_page_failing_keeps_the_rest(muni_id, caplog):
    pages = EventPages(fail={COUNCIL_EVENT_URL})
    with caplog.at_level("WARNING"):
        n = _run(muni_id, pages)

    rows = _rows(muni_id)
    assert n == 34 and len(rows) == 34
    assert not any(r["source_event_id"] == "4941" for r in rows)
    assert len(pages.calls) == 32, "the pages after the failed one are still read"
    assert any(COUNCIL_EVENT_URL in r.getMessage() for r in caplog.records)

    # the next run reads the page that failed (and the two Planning pages) and stores it
    retry = EventPages()
    _run(muni_id, retry)
    assert set(retry.calls) == PLANNING_EVENT_URLS | {COUNCIL_EVENT_URL}
    assert any(r["source_event_id"] == "4941" for r in _rows(muni_id))


def test_three_event_pages_failing_ends_the_sitemap_read_and_keeps_what_was_read(muni_id):
    urls = _sitemap_urls()
    todo = [u for u in urls if u != SHARED_EVENT_URL]
    pages = EventPages(fail={todo[1], todo[3], todo[4]})
    n = _run(muni_id, pages)

    assert pages.calls == todo[:5], "the read stops at the third failure"
    assert n == 5 + 2 and len(_rows(muni_id)) == 7


def _sitemap_read_at(muni_id: int):
    with db_cursor() as cur:
        cur.execute(
            "SELECT (metadata->>'calendar_sitemap_read_at')::timestamptz AS at, metadata FROM municipalities WHERE id = %s",
            (muni_id,),
        )
        row = cur.fetchone()
    assert row["metadata"]["calendar_url"] == TEST_URL, "the marker is added to the metadata, which keeps its other keys"
    return row["at"]


# --- the marker of a complete sitemap read (D120) ---------------------------
# `non_meetings` hides a clip on a day with no stored event only while this
# marker is recent, so it is written only when every unstored page was read.


def test_a_complete_sitemap_read_is_marked(muni_id):
    assert _sitemap_read_at(muni_id) is None
    _run(muni_id, EventPages())
    at = _sitemap_read_at(muni_id)
    assert at is not None and abs((datetime.now(timezone.utc) - at).total_seconds()) < 60


def test_one_failed_event_page_leaves_the_read_unmarked(muni_id):
    todo = [u for u in _sitemap_urls() if u != SHARED_EVENT_URL]
    _run(muni_id, EventPages(fail={todo[-1]}))
    assert _sitemap_read_at(muni_id) is None, "the oldest page failed: its day is not known to be empty"

    _run(muni_id, EventPages())
    assert _sitemap_read_at(muni_id) is not None, "the next morning reads it and the read is complete"


def test_a_read_that_stops_at_three_failures_is_unmarked(muni_id):
    todo = [u for u in _sitemap_urls() if u != SHARED_EVENT_URL]
    _run(muni_id, EventPages(fail={todo[1], todo[3], todo[4]}))
    assert _sitemap_read_at(muni_id) is None


def test_a_failed_sitemap_leaves_the_read_unmarked_though_the_search_stored_events(muni_id):
    def down(*args):
        raise RuntimeError("sitemap down")

    assert _run(muni_id, EventPages(), sitemap=down) == 5
    assert _sitemap_read_at(muni_id) is None


def test_a_later_incomplete_read_does_not_renew_the_marker(muni_id):
    _run(muni_id, EventPages())
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE municipalities
                  SET metadata = jsonb_set(metadata, '{calendar_sitemap_read_at}', to_jsonb(now() - interval '1 day'))
                WHERE id = %s""",
            (muni_id,),
        )
    before = _sitemap_read_at(muni_id)

    _run(muni_id, EventPages(fail=set(PLANNING_EVENT_URLS)))
    assert _sitemap_read_at(muni_id) == before, "it ages, and the hiding rule stops at 36 hours"


def test_no_more_than_sixty_event_pages_in_one_run(muni_id):
    many = [f"{BASE_URL}/events/2026-{1 + i // 28:02d}-{1 + i % 28:02d}x-committee-meeting-{i}" for i in range(70)]
    pages = EventPages()
    n = _run(muni_id, pages, metadata={k: v for k, v in SEARCH_AND_SITEMAP.items() if "search" not in k},
             sitemap=lambda *a: many)

    assert len(pages.calls) == 60
    assert pages.calls == many[:60], "in the order the parser gave"
    assert n == 60
    assert _sitemap_read_at(muni_id) is None, "ten pages are still unread"

    # the next run takes up the ten left over
    rest = EventPages()
    _run(muni_id, rest, metadata={k: v for k, v in SEARCH_AND_SITEMAP.items() if "search" not in k},
         sitemap=lambda *a: many)
    assert rest.calls == many[60:]
    assert _sitemap_read_at(muni_id) is not None


def test_a_reader_that_reports_no_status_does_not_erase_a_stored_one(muni_id):
    """The council page and the event pages report ``eventStatus``; the search does not.

    An event first stored from its page as ``active`` (or, one day, cancelled) and
    then listed again by the search keeps the status it had.
    """
    from dataclasses import replace

    from docket.services.city_calendar import refresh_city_calendar

    shared = next(e for e in _search_events() if e.source_event_id == "4943")
    assert shared.status is None
    with patch("docket.services.city_calendar.fetch_birminghamal_events",
               return_value=[replace(shared, status="cancelled")]):
        refresh_city_calendar(muni_id, PAGE_ONLY)
    assert _rows(muni_id)[0]["event_status"] == "cancelled"

    with patch("docket.services.city_calendar.fetch_birminghamal_events", return_value=[shared]):
        refresh_city_calendar(muni_id, PAGE_ONLY)
    assert _rows(muni_id)[0]["event_status"] == "cancelled"

    with patch("docket.services.city_calendar.fetch_birminghamal_events",
               return_value=[replace(shared, status="active")]):
        refresh_city_calendar(muni_id, PAGE_ONLY)
    assert _rows(muni_id)[0]["event_status"] == "active"


def test_refresh_all_hands_the_citys_metadata_to_the_refresh(muni_id):
    from docket.services import city_calendar

    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE municipalities SET metadata = metadata || %s::jsonb WHERE id = %s",
            (json.dumps(SEARCH_AND_SITEMAP), muni_id),
        )
    try:
        with patch("docket.services.city_calendar.refresh_city_calendar", return_value=0) as mock_refresh:
            city_calendar.refresh_all()
    finally:
        # leave the test city as its fixture seeds it: the keys must not outlive this test
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE municipalities SET metadata = %s::jsonb WHERE id = %s",
                (json.dumps({"calendar_url": TEST_URL}), muni_id),
            )
    mine = [c.args[1] for c in mock_refresh.call_args_list if c.args[0] == muni_id]
    assert mine == [dict(SEARCH_AND_SITEMAP, calendar_url=TEST_URL)]
