"""Unit tests for the CivicClerk adapter: item flattening, the event listing
(paging, the date filter, the delay, retries) and what a listed meeting carries
(its posted time and its links to the city's own files)."""

import copy
import json
from datetime import date, time
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from docket.adapters.civicclerk import CivicClerkAdapter

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
        assert result[0].title == "1 Roll Call"
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
        assert result[0].title == "1 Roll Call"
        assert result[2].title == "3 Minutes"

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
        assert result[0].title == "A Item A"
        assert result[1].title == "B Item B"

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
        assert result[0].title == "1 Rezoning"

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
        assert result[0].title == "1.1.1 Leaf"

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
        assert result[0].title == "1 Bold Item"
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
        assert result[0].title == "1 Item & Thing"

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
        assert result[0].title == "1 Alt Name"

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
        assert result[0].title == "1 Child"

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
