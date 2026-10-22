"""Tests for docket.adapters.city_calendar: the Birmingham council page's embedded events.

The fixture tests/fixtures/city_calendar/birmingham_council_page.html is the
city council page fetched on 2026-10-21 (HTTP 200, 73,920 bytes), trimmed to
its ``<script id="__NEXT_DATA__">`` element inside a minimal html wrapper. It
holds the four events the plan quotes in Context, so the assertions name
them verbatim.

The symbols under test are imported inside each test, so the file collects
and reads as failing, not as a collection error, before the module exists.

Plan: plans/active/meeting-types-name-the-body.md (M3).
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

FIXTURE = Path(__file__).parent.parent / "fixtures" / "city_calendar" / "birmingham_council_page.html"
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
