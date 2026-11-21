"""Unit tests for the CivicClerk adapter: item flattening, the event listing
(paging, the date filter, the delay, retries), what a listed meeting carries
(its posted time and its links to the city's own files), and what a fetched
agenda gives (the right agenda, "not ready", and each item as the city titled it)."""

import copy
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
import requests

from docket.adapters.civicclerk import CivicClerkAdapter
from docket.models.protocol import RawMeeting

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "civicclerk"


class TestFlattenItems:
    """Tests for CivicClerkAdapter._flatten_items().

    CivicClerk returns hierarchical agenda items with nested childItems.
    The flattener should:
    - Skip section headers (isSection=True or no item number + has children)
    - Recursively include leaf items
    - Strip HTML from names and descriptions
    - Assign sequential indexes
    """

    def setup_method(self):
        self.adapter = CivicClerkAdapter("test", {"tenant": "test", "category_id": 1})

    def _flatten(self, item_list):
        result = []
        self.adapter._flatten_items(item_list, result, "meeting-1", index=0)
        return result

    # --- Basic flattening ---------------------------------------------------

    def test_single_item(self):
        items = [{"id": 1, "agendaObjectItemName": "Roll Call", "agendaObjectItemNumber": "1"}]
        result = self._flatten(items)
        assert len(result) == 1
        assert result[0].title == "Roll Call"
        assert result[0].external_id == "1"
        assert result[0].item_number == "1"

    def test_multiple_items(self):
        items = [
            {"id": 1, "agendaObjectItemName": "Roll Call", "agendaObjectItemNumber": "1"},
            {"id": 2, "agendaObjectItemName": "Pledge", "agendaObjectItemNumber": "2"},
            {"id": 3, "agendaObjectItemName": "Minutes", "agendaObjectItemNumber": "3"},
        ]
        result = self._flatten(items)
        assert len(result) == 3
        assert result[0].title == "Roll Call"
        assert result[2].title == "Minutes"

    # --- Section headers skipped --------------------------------------------

    def test_section_header_skipped(self):
        items = [
            {
                "isSection": True,
                "agendaObjectItemName": "Consent Agenda",
                "childItems": [
                    {"id": 10, "agendaObjectItemName": "Item A", "agendaObjectItemNumber": "A"},
                    {"id": 11, "agendaObjectItemName": "Item B", "agendaObjectItemNumber": "B"},
                ],
            },
        ]
        result = self._flatten(items)
        assert len(result) == 2
        assert result[0].title == "Item A"
        assert result[1].title == "Item B"

    def test_implicit_section_skipped(self):
        """Items with no item number but with children are treated as sections."""
        items = [
            {
                "agendaObjectItemName": "New Business",
                "childItems": [
                    {"id": 20, "agendaObjectItemName": "Rezoning", "agendaObjectItemNumber": "1"},
                ],
            },
        ]
        result = self._flatten(items)
        assert len(result) == 1
        assert result[0].title == "Rezoning"

    # --- Nested children ----------------------------------------------------

    def test_deeply_nested(self):
        items = [
            {
                "isSection": True,
                "agendaObjectItemName": "Section",
                "childItems": [
                    {
                        "isSection": True,
                        "agendaObjectItemName": "Sub-section",
                        "childItems": [
                            {"id": 30, "agendaObjectItemName": "Leaf", "agendaObjectItemNumber": "1.1.1"},
                        ],
                    },
                ],
            },
        ]
        result = self._flatten(items)
        assert len(result) == 1
        assert result[0].title == "Leaf"

    # --- HTML stripping -----------------------------------------------------

    def test_html_stripped(self):
        items = [
            {
                "id": 40,
                "agendaObjectItemName": "<b>Bold Item</b>",
                "agendaObjectItemNumber": "1",
                "description": "<p>Some &amp; description</p>",
            },
        ]
        result = self._flatten(items)
        assert result[0].title == "Bold Item"
        assert result[0].description == "Some & description"

    def test_html_entities(self):
        items = [
            {
                "id": 41,
                "agendaObjectItemName": "Item &amp; Thing",
                "agendaObjectItemNumber": "1",
            },
        ]
        result = self._flatten(items)
        assert result[0].title == "Item & Thing"

    # --- Description truncation ---------------------------------------------

    def test_long_description_truncated(self):
        items = [
            {
                "id": 50,
                "agendaObjectItemName": "Item",
                "agendaObjectItemNumber": "1",
                "description": "x" * 500,
            },
        ]
        result = self._flatten(items)
        assert len(result[0].description) == 300

    # --- Alternative field names --------------------------------------------

    def test_name_field(self):
        """CivicClerk sometimes uses 'name' instead of 'agendaObjectItemName'."""
        items = [{"id": 60, "name": "Alt Name", "itemNumber": "1"}]
        result = self._flatten(items)
        assert result[0].title == "Alt Name"

    def test_children_field(self):
        """Some responses use 'children' instead of 'childItems'."""
        items = [
            {
                "isSection": True,
                "agendaObjectItemName": "Header",
                "children": [
                    {"id": 70, "agendaObjectItemName": "Child", "agendaObjectItemNumber": "1"},
                ],
            },
        ]
        result = self._flatten(items)
        assert len(result) == 1
        assert result[0].title == "Child"

    # --- Empty / edge cases -------------------------------------------------

    def test_empty_list(self):
        assert self._flatten([]) == []

    def test_item_without_id_gets_generated_external_id(self):
        items = [{"agendaObjectItemName": "No ID Item", "agendaObjectItemNumber": "1"}]
        result = self._flatten(items)
        assert result[0].external_id == "meeting-1-0"

    def test_meeting_external_id_propagated(self):
        items = [{"id": 80, "agendaObjectItemName": "Item", "agendaObjectItemNumber": "1"}]
        result = self._flatten(items)
        assert result[0].meeting_external_id == "meeting-1"


# --- _event_to_meeting start_time extraction -----------------------------------


class TestEventToMeetingStartTime:
    """Tests for start_time extraction from CivicClerk eventDate strings."""

    def setup_method(self):
        self.adapter = CivicClerkAdapter("al-mobile", {"tenant": "mobileal", "category_id": None})

    def test_event_to_meeting_extracts_start_time(self):
        from datetime import time

        event = {
            "eventId": 42,
            "eventName": "Council Regular",
            "eventDate": "2026-05-20T17:30:00",
            "hasAgenda": True,
            "hasMinutes": False,
        }
        raw = self.adapter._event_to_meeting(event)
        assert raw is not None
        assert raw.start_time == time(17, 30)

    def test_event_to_meeting_handles_missing_time(self):
        event = {
            "eventId": 42,
            "eventName": "Council Regular",
            "eventDate": "2026-05-20",
            "hasAgenda": True,
            "hasMinutes": False,
        }
        raw = self.adapter._event_to_meeting(event)
        assert raw is not None
        assert raw.start_time is None

    def test_event_to_meeting_falls_back_to_today_when_event_date_missing(self):
        event = {
            "eventId": 42,
            "eventName": "Council Regular",
            "hasAgenda": False,
            "hasMinutes": False,
        }
        raw = self.adapter._event_to_meeting(event)
        assert raw is not None
        assert raw.start_time is None
        # meeting_date defaults to date.today() — don't assert the specific value,
        # just that it's a real date.
        from datetime import date as _date
        assert isinstance(raw.meeting_date, _date)


# --- The listing (plan mobile-agendas-flow-again, M1) ---------------------------
#
# The two pages under tests/fixtures/civicclerk/ are rows Mobile's CivicClerk
# server returned on 2026-11-20, cut down to the keys the adapter reads. No test
# reaches the city's site: each patches the get of the adapter's own session.

FILE_BASE = "https://mobileal.api.civicclerk.com/v1/Meetings/GetMeetingFileStream"


def _page(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _response(payload=None, *, status: int = 200, body: bytes | None = None) -> requests.Response:
    """A real requests.Response holding a JSON payload, or the raw body given."""
    resp = requests.Response()
    resp.status_code = status
    resp._content = body if body is not None else json.dumps(payload).encode()
    resp.url = "https://mobileal.api.civicclerk.com/v1/Events"
    return resp


def _mobile(config: dict | None = None) -> CivicClerkAdapter:
    return CivicClerkAdapter("mobile", config or {"tenant": "mobileal", "category_id": 26})


def _url(call) -> str:
    return call.args[0] if call.args else call.kwargs["url"]


def _params(call):
    if len(call.args) > 1:
        return call.args[1]
    return call.kwargs.get("params")


def _list(adapter: CivicClerkAdapter, *pages: dict, since: date | None = None):
    """Run list_meetings over the given pages; returns (meetings, get mock, sleep mock)."""
    with patch.object(adapter._session, "get") as get, patch(
        "docket.adapters.civicclerk.time.sleep"
    ) as sleep:
        get.side_effect = [_response(p) for p in pages]
        meetings = adapter.list_meetings(since=since)
    return meetings, get, sleep


def _event(event_id: int) -> dict:
    """One fixture row, copied so a test may change it."""
    for name in ("events_page_1.json", "events_page_2.json"):
        for row in _page(name)["value"]:
            if row["id"] == event_id:
                return copy.deepcopy(row)
    raise KeyError(event_id)


def _one(row: dict):
    """The meeting list_meetings makes of one event row."""
    meetings, _, _ = _list(_mobile(), {"@odata.count": 1, "value": [row]})
    assert len(meetings) == 1
    return meetings[0]


class TestListMeetings:
    def test_list_meetings_follows_next_links_to_the_last_page(self):
        adapter = _mobile()
        page_1 = _page("events_page_1.json")
        meetings, get, sleep = _list(adapter, page_1, _page("events_page_2.json"))

        assert [m.external_id for m in meetings] == ["501", "500", "573", "297"]
        assert get.call_count == 2
        second = get.call_args_list[1]
        assert _url(second) == page_1["@odata.nextLink"]
        assert not _params(second)
        # One polite pause between the two pages.
        assert [c.args[0] for c in sleep.call_args_list] == [1.0]
        # Each event's agenda id is remembered for fetch_agenda_items.
        assert adapter._agenda_ids == {"501": 473, "500": 472, "573": 0, "297": 270}

        # A server that never stops giving a next link is an error, not a loop.
        adapter = _mobile()
        endless = dict(page_1)
        with patch.object(adapter._session, "get") as get, patch(
            "docket.adapters.civicclerk.time.sleep"
        ):
            get.side_effect = lambda *a, **k: _response(endless)
            with pytest.raises(ValueError):
                adapter.list_meetings()
        assert get.call_count == 200

    def test_list_meetings_sends_no_top_or_skip(self):
        _, get, _ = _list(_mobile(), _page("events_page_1.json"), _page("events_page_2.json"))
        first = get.call_args_list[0]
        assert _url(first) == "https://mobileal.api.civicclerk.com/v1/Events"
        params = _params(first)
        assert "$top" not in params
        assert "$skip" not in params
        assert params["$orderby"] == "eventDate desc"
        assert params["$count"] == "true"
        for call in get.call_args_list:
            assert "$top" not in _url(call)
            assert "$skip=" not in _url(call)

    def test_list_meetings_asks_for_events_on_or_after_since(self):
        last_page = _page("events_page_2.json")

        _, get, _ = _list(_mobile(), last_page, since=date(2021, 11, 1))
        assert (
            _params(get.call_args_list[0])["$filter"]
            == "eventCategoryId eq 26 and eventDate ge 2021-11-01T00:00:00Z"
        )

        no_category = _mobile({"tenant": "mobileal"})
        _, get, _ = _list(no_category, last_page, since=date(2021, 11, 1))
        assert _params(get.call_args_list[0])["$filter"] == "eventDate ge 2021-11-01T00:00:00Z"

        _, get, _ = _list(_mobile(), last_page)
        assert _params(get.call_args_list[0])["$filter"] == "eventCategoryId eq 26"

        _, get, _ = _list(_mobile({"tenant": "mobileal"}), last_page)
        assert "$filter" not in _params(get.call_args_list[0])

        # The check on this side stays: a row the server sends from before the
        # date asked is still left out (event 297 is dated 2023-04-25).
        meetings, _, _ = _list(_mobile(), last_page, since=date(2024, 1, 1))
        assert [m.external_id for m in meetings] == ["573"]

    def test_list_meetings_refuses_a_next_link_on_another_host(self):
        tail = "Events?$orderby=eventDate%20desc&$skiptoken=id-500"
        refused = [
            f"https://evil.example.com/v1/{tail}",
            f"https://mobileal.api.civicclerk.com.evil.example.com/v1/{tail}",
            f"https://mobileal.api.civicclerk.com@evil.example.com/v1/{tail}",
            f"http://mobileal.api.civicclerk.com/v1/{tail}",
            f"https://mobileal.api.civicclerk.com/v2/{tail}",
            f"https://mobileal.api.civicclerk.com/v1{tail}",
        ]
        for link in refused:
            page = _page("events_page_1.json")
            page["@odata.nextLink"] = link
            adapter = _mobile()
            with patch.object(adapter._session, "get") as get, patch(
                "docket.adapters.civicclerk.time.sleep"
            ):
                get.side_effect = [_response(page), _response(_page("events_page_2.json"))]
                with pytest.raises(ValueError):
                    adapter.list_meetings()
            assert get.call_count == 1, link

        # The host's case is ignored.
        page = _page("events_page_1.json")
        page["@odata.nextLink"] = f"https://MobileAL.api.CivicClerk.com/v1/{tail}"
        meetings, get, _ = _list(_mobile(), page, _page("events_page_2.json"))
        assert len(meetings) == 4
        assert _url(get.call_args_list[1]) == page["@odata.nextLink"]

    def test_delay_is_never_below_one_second(self):
        assert _mobile({"tenant": "mobileal", "delay": 0.5}).delay == 1.0
        assert _mobile({"tenant": "mobileal"}).delay == 1.0
        assert _mobile({"tenant": "mobileal", "delay": 2.5}).delay == 2.5


class TestGet:
    def test_get_retries_a_timeout_then_succeeds(self):
        adapter = _mobile()
        with patch.object(adapter._session, "get") as get, patch(
            "docket.adapters.civicclerk.time.sleep"
        ) as sleep:
            get.side_effect = [requests.Timeout("read timed out"), _response({"value": [1]})]
            data = adapter._get("Events", {"$count": "true"})
        assert data == {"value": [1]}
        assert get.call_count == 2
        assert [c.args[0] for c in sleep.call_args_list] == [1.0]
        for call in get.call_args_list:
            assert _url(call) == "https://mobileal.api.civicclerk.com/v1/Events"
            assert _params(call) == {"$count": "true"}
            assert call.kwargs["timeout"] == (10, 30)

    def test_get_raises_after_three_failures(self):
        adapter = _mobile({"tenant": "mobileal", "delay": 1.5})
        with patch.object(adapter._session, "get") as get, patch(
            "docket.adapters.civicclerk.time.sleep"
        ) as sleep:
            get.side_effect = requests.ConnectionError("handshake timed out")
            with pytest.raises(requests.RequestException) as raised:
                adapter._get("Meetings/473")
        assert get.call_count == 3
        assert "https://mobileal.api.civicclerk.com/v1/Meetings/473" in str(raised.value)
        # The delay after the first failure, twice the delay after the second.
        assert [c.args[0] for c in sleep.call_args_list] == [1.5, 3.0]

        # A status the server rejects with is a failure too.
        adapter = _mobile()
        with patch.object(adapter._session, "get") as get, patch(
            "docket.adapters.civicclerk.time.sleep"
        ):
            get.side_effect = lambda *a, **k: _response({"error": "x"}, status=503)
            with pytest.raises(requests.RequestException):
                adapter._get("Meetings/473")
        assert get.call_count == 3

    def test_a_pause_of_the_delay_separates_every_two_requests(self):
        """A one-page listing, a fetch that fails three times, then two fetches
        that succeed: whatever came before a request, a wait of at least the
        delay comes between it and the one before (GOALS.md Constraints)."""
        adapter = _mobile()
        trace: list[tuple[str, object]] = []
        failure = requests.ConnectionError("handshake timed out")
        last_page = copy.deepcopy(_page("events_page_2.json"))
        last_page.pop("@odata.nextLink", None)
        answers = [last_page, failure, failure, failure, _agenda(), _agenda()]

        def get(url, **kwargs):
            trace.append(("GET", url))
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return _response(answer)

        with patch.object(adapter._session, "get", side_effect=get), patch(
            "docket.adapters.civicclerk.time.sleep",
            side_effect=lambda seconds: trace.append(("sleep", seconds)),
        ):
            adapter.list_meetings()
            first, second, third = _meeting("901"), _meeting("902"), _meeting("903")
            for m in (first, second, third):
                adapter._agenda_ids[m.external_id] = 473
            with pytest.raises(requests.RequestException):
                adapter.fetch_agenda_items(first)
            adapter.fetch_agenda_items(second)
            adapter.fetch_agenda_items(third)

        kinds = [kind for kind, _ in trace]
        assert kinds.count("GET") == 6
        assert kinds[0] == "GET"  # nothing to wait for before the first request
        for i in range(1, len(trace)):
            if trace[i][0] == "GET":
                before = trace[i - 1]
                assert before[0] == "sleep" and before[1] >= adapter.delay, trace

    def test_get_treats_an_empty_body_as_a_failure(self):
        adapter = _mobile()
        with patch.object(adapter._session, "get") as get, patch(
            "docket.adapters.civicclerk.time.sleep"
        ):
            get.side_effect = [_response(body=b""), _response({"id": 473})]
            assert adapter._get("Meetings/473") == {"id": 473}
        assert get.call_count == 2

        # A body that is not JSON is the same failure.
        adapter = _mobile()
        with patch.object(adapter._session, "get") as get, patch(
            "docket.adapters.civicclerk.time.sleep"
        ):
            get.side_effect = lambda *a, **k: _response(body=b"<html>Bad Gateway</html>")
            with pytest.raises(requests.RequestException) as raised:
                adapter._get("Meetings/473")
        assert get.call_count == 3
        assert "https://mobileal.api.civicclerk.com/v1/Meetings/473" in str(raised.value)


class TestListedMeeting:
    def test_start_time_is_the_posted_wall_clock_time(self):
        meeting = _one(_event(501))
        assert meeting.meeting_date == date(2026, 11, 17)
        assert meeting.start_time == time(10, 30)

        # A numeric offset, never observed, is still converted to Central.
        row = _event(501)
        row["eventDate"] = "2026-05-20T22:30:00+00:00"
        meeting = _one(row)
        assert meeting.meeting_date == date(2026, 5, 20)
        assert meeting.start_time == time(17, 30)

    def test_agenda_link_is_the_agenda_file(self):
        meeting = _one(_event(501))
        assert meeting.agenda_url == f"{FILE_BASE}(fileId=3859,plainText=false)"
        assert meeting.minutes_url is None

    def test_agenda_link_falls_back_to_the_event_page_without_an_agenda_file(self):
        meeting = _one(_event(500))
        assert meeting.agenda_url == "https://mobileal.portal.civicclerk.com/event/500/agenda"

        # The event's id is read from `id` before `eventId`.
        row = _event(500)
        row["eventId"] = 9
        meeting = _one(row)
        assert meeting.external_id == "500"
        assert meeting.agenda_url == "https://mobileal.portal.civicclerk.com/event/500/agenda"

    def test_the_latest_file_of_a_type_is_the_one_linked(self):
        # Built here; not a row the city sent. No event read had two files of a type.
        amended = {
            "fileId": 3870,
            "type": "Agenda",
            "name": "11/17/26 Agenda amended",
            "publishOn": "2026-11-17T09:00:00Z",
        }
        row = _event(501)
        row["publishedFiles"].insert(0, dict(amended))
        assert _one(row).agenda_url == f"{FILE_BASE}(fileId=3870,plainText=false)"

        # The publish time decides, not the place in the list nor the file id.
        row = _event(501)
        older_higher_id = {
            "fileId": 3900,
            "type": "Agenda",
            "name": "11/17/26 Agenda draft",
            "publishOn": "2026-11-15T09:00:00Z",
        }
        row["publishedFiles"] = [older_higher_id, dict(amended)] + row["publishedFiles"]
        assert _one(row).agenda_url == f"{FILE_BASE}(fileId=3870,plainText=false)"

        # Published at the same moment: the higher file id.
        row = _event(501)
        same_moment = dict(amended, publishOn="2026-11-16T08:48:58.697Z")
        row["publishedFiles"].append(same_moment)
        assert _one(row).agenda_url == f"{FILE_BASE}(fileId=3870,plainText=false)"

    def test_minutes_link_is_the_minutes_file_of_an_event_created_before_its_date(self):
        meeting = _one(_event(500))
        assert meeting.minutes_url == f"{FILE_BASE}(fileId=3861,plainText=false)"

    def test_an_event_created_on_the_evening_of_its_own_day_keeps_its_minutes_link(self):
        # Built here: 01:30 UTC on 2026-11-11 is 19:30 Central on 2026-11-10.
        row = _event(500)
        row["eventDate"] = "2026-11-10T10:00:00Z"
        row["createdOn"] = "2026-11-11T01:30:00.5Z"
        assert _one(row).minutes_url == f"{FILE_BASE}(fileId=3861,plainText=false)"

    def test_no_minutes_link_for_an_event_created_after_its_date(self):
        meeting = _one(_event(297))
        assert meeting.minutes_url is None
        assert meeting.agenda_url == f"{FILE_BASE}(fileId=548,plainText=false)"

        # Without a creation date nothing says the event was not imported.
        row = _event(500)
        del row["createdOn"]
        assert _one(row).minutes_url is None

    def test_a_scheduled_event_has_no_links(self):
        meeting = _one(_event(573))
        assert meeting.agenda_url is None
        assert meeting.minutes_url is None


# --- The items (plan mobile-agendas-flow-again, M2) ------------------------------
#
# meeting_473.json is the agenda of 2026-11-17 as Mobile's server returned it on
# 2026-11-20, cut down to nine nodes: five headings and four items, each item
# under the heading the city has it under. AgendaNotReady and split_item_name
# are imported inside the tests, so this file still collects without them.

CHICAGO_TODAY = datetime.now(ZoneInfo("America/Chicago")).date()
YESTERDAY = CHICAGO_TODAY - timedelta(days=1)
TOMORROW = CHICAGO_TODAY + timedelta(days=1)

ARENA_NAME = (
    "01-1211 Authorize Agreement with the Mobile County Commission for the design and "
    "construction of the Regions Arena; $7,500,000.00 (sponsored by Mayor Cheriogotis) "
    "(submitted by Robert Shreve, City Attorney)."
)
ARENA_TITLE = (
    "01-1211 Authorize Agreement with the Mobile County Commission for the design and "
    "construction of the Regions Arena; $7,500,000.00."
)
NUISANCE_TITLE = (
    "40-1225 Declare the structure at 701 N. Joachim Street a public nuisance and "
    "order it demolished."
)
HEARING_TITLE = (
    "Public hearing to fix costs for demolition of the structure at 1423 Cedar Park "
    "Drive; $4,000.00 (District 3)."
)
CHAPLAIN_TITLE = "Father Dan Good, Public Safety Chaplain"


def _agenda() -> dict:
    return _page("meeting_473.json")


def _meeting(external_id: str = "501", meeting_date: date = date(2026, 11, 17)) -> RawMeeting:
    return RawMeeting(
        external_id=external_id,
        municipality_slug="mobile",
        title="City Council Meeting",
        meeting_date=meeting_date,
        meeting_type="council",
        agenda_url=None,
        minutes_url=None,
        video_url=None,
        source_url=f"https://mobileal.portal.civicclerk.com/event/{external_id}",
    )


def _listed() -> CivicClerkAdapter:
    """An adapter that has listed the two fixture pages."""
    adapter = _mobile()
    _list(adapter, _page("events_page_1.json"), _page("events_page_2.json"))
    return adapter


def _fetch(adapter: CivicClerkAdapter, meeting: RawMeeting, *answers):
    """Run fetch_agenda_items over the given answers (payloads or exceptions).

    Returns (items or the exception raised, get mock, sleep mock)."""
    with patch.object(adapter._session, "get") as get, patch(
        "docket.adapters.civicclerk.time.sleep"
    ) as sleep:
        get.side_effect = [a if isinstance(a, Exception) else _response(a) for a in answers]
        try:
            outcome = adapter.fetch_agenda_items(meeting)
        except Exception as e:  # noqa: BLE001 - the caller asserts on its type
            outcome = e
    return outcome, get, sleep


def _items_of_473():
    items, _, _ = _fetch(_listed(), _meeting(), _agenda())
    assert isinstance(items, list), items
    return {item.external_id: item for item in items}


def _flat(nodes: list[dict]):
    result = []
    _mobile()._flatten_items(nodes, result, "501", index=0)
    return result


class TestFetchAgendaItems:
    def test_items_come_from_the_events_agenda_id(self):
        items, get, sleep = _fetch(_listed(), _meeting("501"), _agenda())

        assert [item.external_id for item in items] == ["13498", "13505", "13520", "13512"]
        assert {item.meeting_external_id for item in items} == {"501"}
        urls = [_url(c) for c in get.call_args_list]
        assert urls == ["https://mobileal.api.civicclerk.com/v1/Meetings/473"]
        assert not any(u.endswith("/Meetings/501") for u in urls)
        # The polite pause comes before the request: the listing was the one before it.
        assert [c.args[0] for c in sleep.call_args_list] == [1.0]
        # A CivicClerk item has no video timestamp, and the adapter says so.
        assert CivicClerkAdapter.items_carry_video_timestamps is False

    def test_agenda_id_is_looked_up_for_a_meeting_not_listed(self):
        adapter = _mobile()
        lookup = {"@odata.count": 1, "value": [_event(501)]}
        items, get, sleep = _fetch(adapter, _meeting("501"), lookup, _agenda())

        assert len(items) == 4
        first, second = get.call_args_list
        assert _url(first) == "https://mobileal.api.civicclerk.com/v1/Events"
        assert _params(first) == {"$filter": "id eq 501"}
        assert _url(second) == "https://mobileal.api.civicclerk.com/v1/Meetings/473"
        # The lookup is this instance's first request; one pause before the agenda.
        assert [c.args[0] for c in sleep.call_args_list] == [1.0]
        assert adapter._agenda_ids == {"501": 473}

        # The server knows no such event: an error, and the agenda is not asked for.
        outcome, get, _ = _fetch(_mobile(), _meeting("501"), {"@odata.count": 0, "value": []})
        assert isinstance(outcome, ValueError)
        assert get.call_count == 1

        # A row for another event is not this event.
        outcome, get, _ = _fetch(_mobile(), _meeting("501"), {"value": [_event(500)]})
        assert isinstance(outcome, ValueError)
        assert get.call_count == 1

        # An id that is not a whole number is let through as ValueError, with no request.
        outcome, get, _ = _fetch(_mobile(), _meeting("event-2026-11-17"))
        assert isinstance(outcome, ValueError)
        assert get.call_count == 0

    def test_no_agenda_id_raises_agenda_not_ready_without_a_request(self):
        from docket.models.protocol import AgendaNotReady

        outcome, get, _ = _fetch(_listed(), _meeting("573", date(2027, 8, 31)))
        assert isinstance(outcome, AgendaNotReady)
        assert get.call_count == 0

        # Not listed by this adapter: the lookup is the only request.
        outcome, get, _ = _fetch(
            _mobile(), _meeting("573", date(2027, 8, 31)), {"value": [_event(573)]}
        )
        assert isinstance(outcome, AgendaNotReady)
        assert [_url(c) for c in get.call_args_list] == [
            "https://mobileal.api.civicclerk.com/v1/Events"
        ]

    def test_an_unpublished_agenda_raises_agenda_not_ready(self):
        from docket.models.protocol import AgendaNotReady

        unpublished = _agenda()
        unpublished["agendaIsPublish"] = False
        outcome, get, _ = _fetch(_listed(), _meeting("501", YESTERDAY), unpublished)
        # Raised although the answer holds items and the meeting's date is past.
        assert isinstance(outcome, AgendaNotReady)
        assert get.call_count == 1

        # An answer without the key is treated as published.
        keyless = _agenda()
        del keyless["agendaIsPublish"]
        items, _, _ = _fetch(_listed(), _meeting("501", YESTERDAY), keyless)
        assert len(items) == 4

    def test_an_empty_agenda_of_a_coming_meeting_raises_agenda_not_ready(self):
        from docket.models.protocol import AgendaNotReady

        empty = {"id": 473, "agendaIsPublish": True, "items": []}
        outcome, get, _ = _fetch(_listed(), _meeting("501", TOMORROW), empty)
        assert isinstance(outcome, AgendaNotReady)
        assert get.call_count == 1

        # Headings with nothing under them are no item either.
        headings = {"id": 473, "agendaIsPublish": True, "items": _agenda()["items"][:1]}
        outcome, _, _ = _fetch(_listed(), _meeting("501", TOMORROW), headings)
        assert isinstance(outcome, AgendaNotReady)

        # A meeting held today is still coming.
        outcome, _, _ = _fetch(_listed(), _meeting("501", CHICAGO_TODAY), empty)
        assert isinstance(outcome, AgendaNotReady)

        # "Today" is the city's date, not the worker's: at 01:00 UTC on the 18th
        # it is still 19:00 on the 17th in Mobile.
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                instant = datetime(2026, 11, 18, 1, 0, tzinfo=timezone.utc)
                return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

        with patch("docket.adapters.civicclerk.datetime", Clock):
            outcome, _, _ = _fetch(_listed(), _meeting("501", date(2026, 11, 17)), empty)
            assert isinstance(outcome, AgendaNotReady)
            outcome, _, _ = _fetch(_listed(), _meeting("501", date(2026, 11, 16)), empty)
            assert outcome == []

    def test_an_empty_agenda_of_a_past_meeting_returns_no_items(self):
        empty = {"id": 473, "agendaIsPublish": True, "items": []}
        outcome, get, _ = _fetch(_listed(), _meeting("501", YESTERDAY), empty)
        assert outcome == []
        assert get.call_count == 1

        # Headings alone are no items either (every imported Mobile agenda).
        headings = {"id": 270, "agendaIsPublish": True, "items": _agenda()["items"][:1]}
        outcome, _, _ = _fetch(_listed(), _meeting("297", date(2023, 4, 25)), headings)
        assert outcome == []

    def test_a_failed_request_raises(self):
        failure = requests.ConnectionError("handshake timed out")
        outcome, get, _ = _fetch(_listed(), _meeting("501"), failure, failure, failure)
        assert isinstance(outcome, requests.RequestException)
        assert "https://mobileal.api.civicclerk.com/v1/Meetings/473" in str(outcome)
        assert get.call_count == 3

        # So does a failed lookup of the agenda id.
        outcome, get, _ = _fetch(_mobile(), _meeting("501"), failure, failure, failure)
        assert isinstance(outcome, requests.RequestException)
        assert get.call_count == 3


class TestItemsOfAnAgenda:
    def test_section_headings_are_not_items(self):
        nodes = _agenda()["items"]
        assert len(nodes) + sum(len(n["childItems"]) for n in nodes) == 9
        items = _flat(nodes)
        assert [item.external_id for item in items] == ["13498", "13505", "13520", "13512"]
        assert not {"7754", "7752", "7772", "7763", "7764"} & {i.external_id for i in items}

    def test_an_item_under_a_consent_heading_is_a_consent_item(self):
        items = _items_of_473()
        assert items["13512"].is_consent is True
        assert items["13498"].is_consent is False
        assert items["13505"].is_consent is False
        assert items["13520"].is_consent is False

        def node(item_id, name, children=None, section=0, number="2026-1"):
            return {
                "id": item_id,
                "isSection": section,
                "agendaObjectItemName": name,
                "agendaObjectItemNumber": "" if section else number,
                "childItems": children or [],
            }

        tree = [
            node(1, "Consent Resolutions Held Over", section=1, children=[
                node(10, "Pay a claim"),
                # A heading under a consent heading keeps its items on the consent agenda.
                node(2, "ROADS", section=1, children=[node(11, "Resurface a street")]),
            ]),
            # The next heading starts again.
            node(3, "ORDINANCES HELD OVER", section=1, children=[
                node(12, "Amend the zoning code"),
                # As before this plan, an item whose own name says so.
                node(13, "Approve the consent agenda"),
                # Only a heading puts what is under it on the consent agenda: an
                # item with a file number is no heading, whatever its name says.
                node(14, "Consent to an assignment", children=[node(15, "Exhibit A")]),
            ]),
        ]
        flags = {item.external_id: item.is_consent for item in _flat(tree)}
        assert flags == {
            "10": True, "11": True, "12": False, "13": True, "14": True, "15": False,
        }

    def test_title_is_the_citys_item_name_and_keeps_its_code(self):
        items = _items_of_473()
        assert items["13520"].title == ARENA_TITLE
        assert items["13512"].title == NUISANCE_TITLE
        assert items["13505"].title == HEARING_TITLE
        assert items["13498"].title == CHAPLAIN_TITLE
        # The file number stays the item number and is no longer put before the title.
        assert items["13520"].item_number == "2026-2408"
        assert items["13512"].item_number == "2026-2400"
        assert re.match(r"^(\d{2}-\d{3,4})\b", items["13520"].title).group(1) == "01-1211"

        # An item with a file number and no name is not an item.
        assert _flat([{"id": 5, "agendaObjectItemNumber": "2026-9", "agendaObjectItemName": " "}]) == []

    def test_sponsor_and_submitter_are_split_from_the_name(self):
        from docket.adapters.civicclerk import split_item_name

        items = _items_of_473()
        arena = items["13520"]
        assert arena.sponsor == "Mayor Cheriogotis"
        assert arena.sponsor != "Robert Shreve, City Attorney"
        assert arena.description == "Submitted by Robert Shreve, City Attorney."
        assert items["13512"].sponsor == "Councilmember Ingram"
        assert items["13512"].description is None
        assert items["13505"].sponsor is None
        assert items["13498"].sponsor is None
        assert items["13498"].description is None

        assert split_item_name(ARENA_NAME) == (
            ARENA_TITLE,
            "Mayor Cheriogotis",
            "Robert Shreve, City Attorney",
        )
        assert split_item_name(HEARING_TITLE) == (HEARING_TITLE, None, None)
        assert split_item_name(CHAPLAIN_TITLE) == (CHAPLAIN_TITLE, None, None)
        # Two names of Vestavia Hills': an entity, and a tag with a non-breaking space.
        assert split_item_name("City Manager&rsquo;s Report") == (
            "City Manager’s Report",
            None,
            None,
        )
        assert split_item_name(
            "Public Hearing - Ordinance Number 3363 \xa0- Rezoning - "
            '<a href="file://cityhall-smb/x.d">4616 Old Looney Mill Road</a>'
        ) == (
            "Public Hearing - Ordinance Number 3363 - Rezoning - 4616 Old Looney Mill Road",
            None,
            None,
        )
        # Case and spacing inside the parentheses do not matter; a submitter alone.
        assert split_item_name("Pay a claim ( Submitted By  Jane Roe, Clerk ) ; $5.00") == (
            "Pay a claim; $5.00",
            None,
            "Jane Roe, Clerk",
        )
        # Spaces inside the parentheses are not part of the name, and a run of
        # whitespace in it (a non-breaking space among them) is one space.
        assert split_item_name("Pay ( Sponsored By  Council\xa0 Member Small ) the claim") == (
            "Pay the claim",
            "Council Member Small",
            None,
        )
        # The first of two is the one kept; both are taken out of the title.
        assert split_item_name("X (sponsored by A) (sponsored by B) : y , z") == (
            "X: y, z",
            "A",
            None,
        )

    def test_the_code_survives_enrichment(self):
        from docket.services.enrichment import enrich_agenda_item

        item = _items_of_473()["13512"]
        enriched = enrich_agenda_item(item.title, item.description, True)
        assert enriched["clean_title"] == item.title
        assert re.match(r"^(\d{2}-\d{3,4})\b", enriched["clean_title"]).group(1) == "40-1225"
        # Enrichment finds no attribution left in the title, so ingest keeps the adapter's.
        assert enriched["sponsor"] is None
        assert (enriched["sponsor"] or item.sponsor) == "Councilmember Ingram"

    def test_description_is_read_from_the_citys_description_field(self):
        def described(**keys):
            node = {"id": 9, "agendaObjectItemNumber": "26-997", "agendaObjectItemName": "Item"}
            node.update(keys)
            (item,) = _flat([node])
            return item

        item = described(agendaObjectItemDescription="<p>Renews the lease &amp; sets the rent.</p>")
        assert item.description == "Renews the lease & sets the rent."

        # The city's key first; the older key only when the city's is empty.
        item = described(agendaObjectItemDescription="The city's.", description="The older.")
        assert item.description == "The city's."
        item = described(agendaObjectItemDescription="", description="The older.")
        assert item.description == "The older."
        assert described(agendaObjectItemDescription=None).description is None

        # The submitter follows the description, one space between.
        item = described(
            agendaObjectItemName="Item (submitted by Jane Roe, Clerk)",
            agendaObjectItemDescription="Renews the lease.",
        )
        assert item.title == "Item"
        assert item.description == "Renews the lease. Submitted by Jane Roe, Clerk."

        # The 300-character cut is applied last, over the joined text.
        item = described(
            agendaObjectItemName="Item (submitted by Jane Roe, Clerk)",
            agendaObjectItemDescription="x" * 290,
        )
        assert item.description == ("x" * 290 + " Submitted by Jane Roe, Clerk.")[:300]
        assert len(item.description) == 300
