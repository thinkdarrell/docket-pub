"""Tests for docket.adapters.city_calendar: the Birmingham council page's embedded events.

The fixture tests/fixtures/city_calendar/birmingham_council_page.html is the
city council page fetched on 2026-10-21 (HTTP 200, 73,920 bytes), trimmed to
its ``<script id="__NEXT_DATA__">`` element inside a minimal html wrapper. It
holds the four events the plan quotes in Context, so the assertions name
them verbatim.

The symbols under test are imported inside each test, so the file collects
and reads as failing, not as a collection error, before the module exists.

Plan: plans/completed/meeting-types-name-the-body.md (M3).

Plan `committee-clips-named-or-hidden`, M1, added the three other fixtures in
that directory, each saved from the live site on 2026-11-11: the events
search's answer for department 55 (five results, ``pageInfo`` total 5 and
pageSize 10), the sitemap trimmed to its 119 ``/events/`` entries plus the
home page and one news page, and two event pages (the council's
Transportation and Infrastructure Committee of 2026-11-09, and the Planning
department's Framework Plan Implementation Committee of 2026-10-14).
"""

import json

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures" / "city_calendar"
FIXTURE = FIXTURES / "birmingham_council_page.html"
SEARCH_URL = "https://www.birminghamal.gov/api/search/events"
SITEMAP_URL = "https://www.birminghamal.gov/sitemap.xml"
COUNCIL_EVENT_URL = (
    "https://www.birminghamal.gov/events/2026-11-09transportation-infrastructure-committee-meeting-november-9-2026"
)
PLANNING_EVENT_URL = (
    "https://www.birminghamal.gov/events/2026-10-14framework-plan-implementation-committee-public-information-meeting"
)


@pytest.fixture(autouse=True)
def no_real_pause(monkeypatch):
    """The fetchers pause between requests; no unit test waits for one. Yields the recorded pauses."""
    pauses: list[float] = []
    try:
        from docket.adapters import city_calendar
    except ImportError:
        yield pauses
        return
    if hasattr(city_calendar, "time"):
        monkeypatch.setattr(city_calendar.time, "sleep", pauses.append)
    if hasattr(city_calendar, "_last_request_at"):
        monkeypatch.setattr(city_calendar, "_last_request_at", None)
    yield pauses
BASE_URL = "https://www.birminghamal.gov"
PAGE_URL = "https://www.birminghamal.gov/government/city-council"


def _fixture_html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _utc(y, mo, d, h, mi) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


class TestParseBirminghamalPage:
    def test_fixture_yields_the_four_events_in_page_order(self):
        from docket.adapters.city_calendar import CalendarEvent, parse_birminghamal_page

        events = parse_birminghamal_page(_fixture_html(), BASE_URL)
        assert len(events) == 4
        assert all(isinstance(e, CalendarEvent) for e in events)
        assert [e.source_event_id for e in events] == ["4848", "4858", "4854", "4864"]

    def test_titles_verbatim_with_whitespace_collapsed(self):
        from docket.adapters.city_calendar import parse_birminghamal_page

        titles = [e.title for e in parse_birminghamal_page(_fixture_html(), BASE_URL)]
        assert titles == [
            "BIRMINGHAM CITY COUNCIL MEETING, October 20, 2026",
            "ECONOMIC & WORKFORCE DEVELOPMENT/TOURISM COMMITTEE MEETING, October 20, 2026",
            "COMMITTEE OF THE WHOLE/ADMINISTRATION & GOVERNMENTAL AFFAIRS COMMITTEE MEETING, October 21, 2026",
            # the source has a double space before MEETING; the parser collapses it
            "TRANSPORTATION AND INFRASTRUCTURE COMMITTEE MEETING, October 26, 2026",
        ]

    def test_start_instants_are_tz_aware_utc(self):
        from docket.adapters.city_calendar import parse_birminghamal_page

        starts = [e.starts_at for e in parse_birminghamal_page(_fixture_html(), BASE_URL)]
        assert starts == [
            _utc(2026, 10, 20, 14, 30),
            _utc(2026, 10, 20, 16, 30),
            _utc(2026, 10, 21, 20, 30),
            _utc(2026, 10, 26, 19, 0),
        ]
        assert all(s.tzinfo is not None and s.utcoffset().total_seconds() == 0 for s in starts)

    def test_end_instants(self):
        from docket.adapters.city_calendar import parse_birminghamal_page

        ends = [e.ends_at for e in parse_birminghamal_page(_fixture_html(), BASE_URL)]
        assert ends == [
            _utc(2026, 10, 20, 16, 30),
            _utc(2026, 10, 20, 18, 0),
            _utc(2026, 10, 21, 22, 0),
            _utc(2026, 10, 26, 20, 30),
        ]

    def test_source_urls_join_base_and_path(self):
        from docket.adapters.city_calendar import parse_birminghamal_page

        urls = [e.source_url for e in parse_birminghamal_page(_fixture_html(), BASE_URL)]
        assert urls == [
            BASE_URL + "/events/2026-10-20birmingham-city-council-meeting-october-20-2026",
            BASE_URL + "/events/2026-10-20economic-workforce-developmenttourism-committee-meeting-october-20-2026",
            BASE_URL + "/events/2026-10-21committee-wholeadministration-governmental-affairs-committee-meeting-october-21-2026",
            BASE_URL + "/events/2026-10-26transportation-infrastructure-committee-meeting-october-26-2026",
        ]

    def test_base_url_trailing_slash_does_not_double(self):
        from docket.adapters.city_calendar import parse_birminghamal_page

        events = parse_birminghamal_page(_fixture_html(), BASE_URL + "/")
        assert events[0].source_url.startswith(BASE_URL + "/events/")
        assert "//events" not in events[0].source_url

    def test_categories_are_kept_as_the_page_said(self):
        from docket.adapters.city_calendar import parse_birminghamal_page

        cats = [e.categories for e in parse_birminghamal_page(_fixture_html(), BASE_URL)]
        assert cats == [
            ("City Council Meetings",),
            ("Economic and Workforce Development / Tourism Committee",),
            ("Committee of the Whole / Administration & Governmental Affairs", "Community Development Committee"),
            ("Public Safety Committee",),
        ]

    def test_events_are_frozen(self):
        import dataclasses

        from docket.adapters.city_calendar import parse_birminghamal_page

        ev = parse_birminghamal_page(_fixture_html(), BASE_URL)[0]
        try:
            ev.title = "x"
        except dataclasses.FrozenInstanceError:
            return
        raise AssertionError("CalendarEvent is not frozen")


class TestParseDegradesToEmpty:
    def test_page_without_the_script_returns_empty_and_warns(self, caplog):
        from docket.adapters.city_calendar import parse_birminghamal_page

        with caplog.at_level("WARNING"):
            assert parse_birminghamal_page("<html><body><p>No results were found</p></body></html>", BASE_URL) == []
        assert any("__NEXT_DATA__" in r.message for r in caplog.records)

    def test_script_that_is_not_json_returns_empty(self, caplog):
        from docket.adapters.city_calendar import parse_birminghamal_page

        html = '<html><body><script id="__NEXT_DATA__" type="application/json">{not json</script></body></html>'
        with caplog.at_level("WARNING"):
            assert parse_birminghamal_page(html, BASE_URL) == []
        assert caplog.records

    def test_json_without_the_events_path_returns_empty(self, caplog):
        from docket.adapters.city_calendar import parse_birminghamal_page

        html = '<html><body><script id="__NEXT_DATA__" type="application/json">{"props": {"pageProps": {}}}</script></body></html>'
        with caplog.at_level("WARNING"):
            assert parse_birminghamal_page(html, BASE_URL) == []
        assert caplog.records

    def test_empty_html_returns_empty(self):
        from docket.adapters.city_calendar import parse_birminghamal_page

        assert parse_birminghamal_page("", BASE_URL) == []

    def test_html_entities_in_a_title_are_unescaped(self):
        """A guard: the page's JSON has carried a plain ``&`` on every read so far, but a
        stored ``&amp;`` would defeat the canonical committee-name match in meeting_types
        (``committee_name_for`` compares letters, and "AMP" breaks "Arts and Parks")."""
        import json

        from docket.adapters.city_calendar import parse_birminghamal_page

        payload = {"props": {"pageProps": {"nodeResource": {"events": {"results": [
            {"id": "27", "title": "ARTS &amp; PARKS COMMITTEE MEETING, November 16, 2026", "path": "/events/a",
             "startDate": {"time": "2026-11-06T21:30:00+00:00"}},
            {"id": "28", "title": "ARTS & PARKS COMMITTEE MEETING, November 23, 2026", "path": "/events/b",
             "startDate": {"time": "2026-11-23T21:30:00+00:00"}},
        ]}}}}}
        html = f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script></body></html>'
        events = parse_birminghamal_page(html, BASE_URL)
        assert [e.title for e in events] == [
            "ARTS & PARKS COMMITTEE MEETING, November 16, 2026",
            "ARTS & PARKS COMMITTEE MEETING, November 23, 2026",
        ]

    def test_result_without_a_start_is_skipped_and_the_rest_kept(self, caplog):
        import json

        from docket.adapters.city_calendar import parse_birminghamal_page

        payload = {"props": {"pageProps": {"nodeResource": {"events": {"results": [
            {"id": "1", "title": "A  B", "path": "/events/a", "startDate": {"time": "2026-10-20T14:30:00+00:00"}},
            {"id": "2", "title": "No start", "path": "/events/b", "startDate": None},
            {"id": "3", "title": "No end", "path": "/events/c",
             "startDate": {"time": "2026-10-21T20:30:00+00:00"}, "endDate": {"time": None}},
        ]}}}}}
        html = f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script></body></html>'
        with caplog.at_level("WARNING"):
            events = parse_birminghamal_page(html, BASE_URL)
        assert [e.source_event_id for e in events] == ["1", "3"]
        assert events[0].title == "A B"
        assert events[0].ends_at is None
        assert events[0].categories == ()
        assert events[1].ends_at is None
        assert any("skipping" in r.message for r in caplog.records)


class TestFetchBirminghamalEvents:
    def test_one_get_with_browser_user_agent_and_timeout(self):
        from docket.adapters import city_calendar

        resp = MagicMock()
        resp.text = _fixture_html()
        resp.raise_for_status = MagicMock()
        with patch("docket.adapters.city_calendar.requests.get", return_value=resp) as mock_get:
            events = city_calendar.fetch_birminghamal_events(PAGE_URL)

        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert args == (PAGE_URL,)
        assert kwargs["timeout"] == 60
        assert kwargs["headers"]["User-Agent"].startswith("Mozilla/5.0")
        resp.raise_for_status.assert_called_once()
        assert len(events) == 4
        # the base url is derived from the page url, so paths resolve on the city's host
        assert events[0].source_url.startswith(BASE_URL + "/events/")

    def test_http_error_propagates(self):
        import requests

        from docket.adapters import city_calendar

        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError("503")
        with patch("docket.adapters.city_calendar.requests.get", return_value=resp):
            try:
                city_calendar.fetch_birminghamal_events(PAGE_URL)
            except requests.HTTPError:
                return
        raise AssertionError("HTTPError did not propagate")


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _search_payload() -> dict:
    return json.loads(_text("birmingham_events_search.json"))


class TestEventStatus:
    def test_council_page_results_carry_their_status(self):
        from docket.adapters.city_calendar import parse_birminghamal_page

        assert [e.status for e in parse_birminghamal_page(_fixture_html(), BASE_URL)] == ["active"] * 4

    def test_a_result_without_a_status_has_none(self):
        from docket.adapters.city_calendar import parse_search_page

        events, _, _ = parse_search_page(_search_payload(), BASE_URL)
        assert [e.status for e in events] == [None] * 5


class TestParseSearchPage:
    def test_fixture_yields_five_events_and_the_page_info(self):
        from docket.adapters.city_calendar import CalendarEvent, parse_search_page

        events, total, page_size = parse_search_page(_search_payload(), BASE_URL)
        assert (total, page_size) == (5, 10)
        assert all(isinstance(e, CalendarEvent) for e in events)
        assert [e.source_event_id for e in events] == ["4967", "4969", "4965", "4943", "4964"]

    def test_the_committee_event_reads_like_a_council_page_result(self):
        from docket.adapters.city_calendar import parse_search_page

        ev = parse_search_page(_search_payload(), BASE_URL)[0][3]
        assert ev.title == "BUDGET AND FINANCE COMMITTEE MEETING, November 23, 2026"
        assert ev.starts_at == _utc(2026, 11, 23, 21, 30)
        assert ev.ends_at == _utc(2026, 11, 23, 23, 0)
        assert ev.source_url == BASE_URL + "/events/2026-11-23budget-finance-committee-meeting-november-23-2026"
        assert ev.categories == ()

    def test_a_result_of_another_department_is_dropped_when_a_department_is_named(self):
        from docket.adapters.city_calendar import parse_search_page

        payload = _search_payload()
        payload["graphqlEventsSearchWww"]["results"][0]["department"] = {"name": "Planning, Engineering & Permits"}
        events, total, _ = parse_search_page(payload, BASE_URL, department="City Council")
        assert [e.source_event_id for e in events] == ["4969", "4965", "4943", "4964"]
        assert total == 5
        # without a department every result is kept, whatever it says
        assert len(parse_search_page(payload, BASE_URL)[0]) == 5

    def test_malformed_payloads_are_empty_with_a_warning(self, caplog):
        from docket.adapters.city_calendar import parse_search_page

        with caplog.at_level("WARNING"):
            assert parse_search_page({}, BASE_URL) == ([], 0, 0)
            assert parse_search_page({"graphqlEventsSearchWww": {"results": "x"}}, BASE_URL) == ([], 0, 0)
            assert parse_search_page([], BASE_URL) == ([], 0, 0)
        assert len(caplog.records) == 3

    def test_missing_page_info_reads_as_zero(self):
        from docket.adapters.city_calendar import parse_search_page

        payload = {"graphqlEventsSearchWww": {"results": _search_payload()["graphqlEventsSearchWww"]["results"]}}
        events, total, page_size = parse_search_page(payload, BASE_URL)
        assert len(events) == 5 and (total, page_size) == (0, 0)


class TestParseSitemap:
    def test_fixture_yields_the_33_council_shaped_event_urls(self):
        from docket.adapters.city_calendar import parse_sitemap

        urls = parse_sitemap(_text("birmingham_sitemap.xml"))
        assert len(urls) == 33
        assert all("/events/" in u for u in urls)
        assert COUNCIL_EVENT_URL in urls and PLANNING_EVENT_URL in urls

    def test_fixture_is_read_newest_first(self):
        from docket.adapters.city_calendar import parse_sitemap

        urls = parse_sitemap(_text("birmingham_sitemap.xml"))
        assert urls[0] == BASE_URL + "/events/2026-11-23budget-finance-committee-meeting-november-23-2026"
        assert urls[-1] == BASE_URL + "/events/2025-09-08budget-finance-committee-meeting-09082025"
        days = [u.rsplit("/", 1)[1][:10] for u in urls]
        assert days == sorted(days, reverse=True)

    def test_a_page_outside_events_is_not_listed_whatever_its_name(self):
        from docket.adapters.city_calendar import parse_sitemap

        # the fixture's one news page has "committee" in its path
        assert "federal-advocacy-committee" in _text("birmingham_sitemap.xml")
        assert not any("/news/" in u for u in parse_sitemap(_text("birmingham_sitemap.xml")))

    def test_an_event_that_names_no_council_body_is_not_listed(self):
        from docket.adapters.city_calendar import parse_sitemap

        assert "/events/2026-10-08octobers-thursday-luncheon" in _text("birmingham_sitemap.xml")
        assert not any("luncheon" in u for u in parse_sitemap(_text("birmingham_sitemap.xml")))

    def test_three_urls_dated_out_of_order_come_back_newest_first_and_undated_last(self):
        from docket.adapters.city_calendar import parse_sitemap

        def loc(path: str) -> str:
            return f"<url><loc>https://city.test{path}</loc></url>"

        xml = "<urlset>" + "".join([
            loc("/events/budget-committee-undated"),
            loc("/events/2026-10-05community-development-committee-meeting"),
            loc("/events/2026-11-10Birmingham-City-Council-Meeting-november-10"),
            loc("/events/2026-10-20economic-development-WORK-SESSION"),
        ]) + "</urlset>"
        assert parse_sitemap(xml) == [
            "https://city.test/events/2026-11-10Birmingham-City-Council-Meeting-november-10",
            "https://city.test/events/2026-10-20economic-development-WORK-SESSION",
            "https://city.test/events/2026-10-05community-development-committee-meeting",
            "https://city.test/events/budget-committee-undated",
        ]

    def test_each_of_the_three_words_admits_a_url_and_nothing_else_does(self):
        from docket.adapters.city_calendar import parse_sitemap

        def one(path: str) -> list[str]:
            return parse_sitemap(f"<urlset><url><loc>https://city.test{path}</loc></url></urlset>")

        assert one("/events/2026-01-01a-committee-x")
        assert one("/events/2026-01-01a-council-meeting-x")
        assert one("/events/2026-01-01a-work-session-x")
        assert one("/events/2026-01-01council-giveaway") == []
        assert one("/government/committee-list") == []

    def test_text_that_is_not_a_sitemap_is_empty(self):
        from docket.adapters.city_calendar import parse_sitemap

        assert parse_sitemap("") == []
        assert parse_sitemap("<html><body>503</body></html>") == []


class TestParseEventPage:
    def test_the_council_page_is_event_4941(self):
        from docket.adapters.city_calendar import parse_event_page

        ev = parse_event_page(_text("birmingham_event_council.html"), BASE_URL, "City Council")
        assert ev is not None
        assert ev.source_event_id == "4941"
        # the source has a double space before MEETING; the parser collapses it
        assert ev.title == "TRANSPORTATION AND INFRASTRUCTURE COMMITTEE MEETING, November 9, 2026"
        assert ev.starts_at == _utc(2026, 11, 9, 20, 0)
        assert ev.ends_at == _utc(2026, 11, 9, 21, 30)
        assert ev.source_url == COUNCIL_EVENT_URL
        assert ev.status == "active"
        assert ev.categories == ()

    def test_the_planning_departments_page_is_none(self):
        from docket.adapters.city_calendar import parse_event_page

        assert parse_event_page(_text("birmingham_event_planning.html"), BASE_URL, "City Council") is None
        # the same page is an event for its own department: the test above is the department's doing
        own = parse_event_page(_text("birmingham_event_planning.html"), BASE_URL, "Planning, Engineering & Permits")
        assert own is not None and own.source_event_id == "4896"

    def test_a_page_without_a_department_is_none(self):
        from docket.adapters.city_calendar import parse_event_page

        node = {"id": "9", "title": "X COMMITTEE MEETING", "path": "/events/x",
                "startDate": {"time": "2026-10-20T14:30:00+00:00"}}
        html = '<script id="__NEXT_DATA__" type="application/json">%s</script>' % json.dumps(
            {"props": {"pageProps": {"nodeResource": node}}}
        )
        assert parse_event_page(html, BASE_URL, "City Council") is None

    def test_malformed_pages_are_none_with_a_warning(self, caplog):
        from docket.adapters.city_calendar import parse_event_page

        with caplog.at_level("WARNING"):
            assert parse_event_page("<html></html>", BASE_URL, "City Council") is None
            assert parse_event_page(
                '<script id="__NEXT_DATA__">{"props": {"pageProps": {}}}</script>', BASE_URL, "City Council"
            ) is None
        assert len(caplog.records) == 2


class TestNormaliseEventUrl:
    def test_spellings_of_one_address_reduce_alike(self):
        from docket.adapters.city_calendar import normalise_event_url

        want = "https://www.birminghamal.gov/events/2026-11-09Budget"
        assert normalise_event_url("https://www.birminghamal.gov/events/2026-11-09Budget") == want
        assert normalise_event_url("https://www.birminghamal.gov/events/2026-11-09Budget/") == want
        assert normalise_event_url("HTTPS://WWW.BirminghamAL.gov/events/2026-11-09Budget") == want
        assert normalise_event_url("https://www.birminghamal.gov/events/2026-11-09Budget?utm=1#top") == want

    def test_different_pages_stay_different(self):
        from docket.adapters.city_calendar import normalise_event_url

        assert normalise_event_url("https://a.test/events/x") != normalise_event_url("https://a.test/events/y")


def _response(*, text: str = "", payload: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


def _search_page(ids: list[str], total: int, page_size: int) -> dict:
    template = _search_payload()["graphqlEventsSearchWww"]["results"][3]
    return {"graphqlEventsSearchWww": {
        "pageInfo": {"offset": 0, "page": 0, "pageSize": page_size, "total": total},
        "results": [dict(template, id=i, path=f"/events/e{i}") for i in ids],
    }}


class TestFetchSearchEvents:
    def test_one_page_when_the_total_fits(self, no_real_pause):
        from docket.adapters import city_calendar

        with patch("docket.adapters.city_calendar.requests.get",
                   return_value=_response(payload=_search_payload())) as mock_get:
            events = city_calendar.fetch_search_events(SEARCH_URL, "55")

        assert len(events) == 5
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert args == (SEARCH_URL,)
        assert kwargs["params"] == {"page": 0, "search": "", "fromDate": "", "toDate": "",
                                    "department": "55", "category": "", "district": ""}
        assert kwargs["timeout"] == 60
        assert kwargs["headers"]["User-Agent"].startswith("Mozilla/5.0")
        assert events[0].source_url.startswith(BASE_URL + "/events/")

    def test_pages_are_read_until_the_total_is_covered_with_a_pause_between(self, no_real_pause):
        from docket.adapters import city_calendar

        pages = [
            _response(payload=_search_page(["1", "2"], total=5, page_size=2)),
            _response(payload=_search_page(["3", "4"], total=5, page_size=2)),
            _response(payload=_search_page(["5"], total=5, page_size=2)),
        ]
        with patch("docket.adapters.city_calendar.requests.get", side_effect=pages) as mock_get:
            events = city_calendar.fetch_search_events(SEARCH_URL, "55")

        assert [e.source_event_id for e in events] == ["1", "2", "3", "4", "5"]
        assert [c.kwargs["params"]["page"] for c in mock_get.call_args_list] == [0, 1, 2]
        assert len(no_real_pause) == 2 and all(0 < p <= 1 for p in no_real_pause)

    def test_no_more_than_ten_pages(self, no_real_pause):
        from docket.adapters import city_calendar

        def page(*args, **kwargs):
            n = kwargs["params"]["page"]
            return _response(payload=_search_page([str(n)], total=1000, page_size=1))

        with patch("docket.adapters.city_calendar.requests.get", side_effect=page) as mock_get:
            events = city_calendar.fetch_search_events(SEARCH_URL, "55")

        assert mock_get.call_count == 10
        assert len(events) == 10

    def test_an_empty_page_ends_the_read(self, no_real_pause):
        from docket.adapters import city_calendar

        pages = [
            _response(payload=_search_page(["1"], total=9, page_size=1)),
            _response(payload=_search_page([], total=9, page_size=1)),
        ]
        with patch("docket.adapters.city_calendar.requests.get", side_effect=pages) as mock_get:
            events = city_calendar.fetch_search_events(SEARCH_URL, "55")

        assert mock_get.call_count == 2 and len(events) == 1

    def test_a_named_department_drops_another_departments_result(self, no_real_pause):
        from docket.adapters import city_calendar

        payload = _search_payload()
        payload["graphqlEventsSearchWww"]["results"][0]["department"] = {"name": "Mayor's Office"}
        with patch("docket.adapters.city_calendar.requests.get", return_value=_response(payload=payload)):
            events = city_calendar.fetch_search_events(SEARCH_URL, "55", department="City Council")
        assert len(events) == 4

    def test_http_error_propagates(self, no_real_pause):
        import requests

        from docket.adapters import city_calendar

        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError("503")
        with patch("docket.adapters.city_calendar.requests.get", return_value=resp):
            with pytest.raises(requests.HTTPError):
                city_calendar.fetch_search_events(SEARCH_URL, "55")


class TestFetchSitemapAndEventPage:
    def test_sitemap_is_one_get_parsed(self, no_real_pause):
        from docket.adapters import city_calendar

        with patch("docket.adapters.city_calendar.requests.get",
                   return_value=_response(text=_text("birmingham_sitemap.xml"))) as mock_get:
            urls = city_calendar.fetch_sitemap_event_urls(SITEMAP_URL)

        mock_get.assert_called_once()
        assert mock_get.call_args.args == (SITEMAP_URL,)
        assert mock_get.call_args.kwargs["timeout"] == 60
        assert mock_get.call_args.kwargs["headers"]["User-Agent"].startswith("Mozilla/5.0")
        assert len(urls) == 33

    def test_event_page_is_one_get_parsed_against_its_own_host(self, no_real_pause):
        from docket.adapters import city_calendar

        with patch("docket.adapters.city_calendar.requests.get",
                   return_value=_response(text=_text("birmingham_event_council.html"))) as mock_get:
            ev = city_calendar.fetch_event_page(COUNCIL_EVENT_URL, "City Council")

        mock_get.assert_called_once()
        assert mock_get.call_args.args == (COUNCIL_EVENT_URL,)
        assert mock_get.call_args.kwargs["timeout"] == 60
        assert ev is not None and ev.source_event_id == "4941" and ev.source_url == COUNCIL_EVENT_URL

    def test_event_page_of_another_department_is_none(self, no_real_pause):
        from docket.adapters import city_calendar

        with patch("docket.adapters.city_calendar.requests.get",
                   return_value=_response(text=_text("birmingham_event_planning.html"))):
            assert city_calendar.fetch_event_page(PLANNING_EVENT_URL, "City Council") is None

    def test_a_second_request_waits_out_the_rest_of_one_second(self, no_real_pause):
        from docket.adapters import city_calendar

        with patch("docket.adapters.city_calendar.requests.get",
                   return_value=_response(text=_text("birmingham_event_council.html"))):
            city_calendar.fetch_event_page(COUNCIL_EVENT_URL, "City Council")
            assert no_real_pause == []
            city_calendar.fetch_event_page(COUNCIL_EVENT_URL, "City Council")
            city_calendar.fetch_sitemap_event_urls(SITEMAP_URL)
        assert len(no_real_pause) == 2 and all(0 < p <= 1 for p in no_real_pause)

    def test_http_error_propagates(self, no_real_pause):
        import requests

        from docket.adapters import city_calendar

        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError("404")
        with patch("docket.adapters.city_calendar.requests.get", return_value=resp):
            with pytest.raises(requests.HTTPError):
                city_calendar.fetch_event_page(COUNCIL_EVENT_URL, "City Council")
            with pytest.raises(requests.HTTPError):
                city_calendar.fetch_sitemap_event_urls(SITEMAP_URL)
