"""Unit tests for docket.services.meeting_types.resolve: the evidence ladder, no database.

The ladder is admin lock, then calendar match, then schedule rule, then
title. `resolve` is pure: it takes the municipality row, the meeting row,
the city's calendar events, and the meeting's item count as dicts and ints,
and returns a `Resolution` (classification, type_source, matched calendar
event id) or `None` for a locked row. `start_time` is never read: Granicus
stores it wrong (issue #88), so every case here passes 02:00 or 11:00 and
expects the same answer.

The symbols under test are imported inside each test, so the file collects
and reads as failing before the module exists.

Dates: 2026-10-19 is a Monday, 2026-10-20 a Tuesday, 2026-10-21 a Wednesday.
Plan: plans/active/meeting-types-name-the-body.md (M4).
"""

from datetime import date, datetime, time, timezone

import pytest

MONDAY = date(2026, 10, 19)
TUESDAY = date(2026, 10, 20)
WEDNESDAY = date(2026, 10, 21)

BIRMINGHAM = {
    "id": 1,
    "slug": "birmingham",
    "metadata": {
        "council_schedule": {"weekday": 1},
        "calendar_url": "https://www.birminghamal.gov/government/city-council",
        "briefing": True,
    },
}
HOMEWOOD = {"id": 2, "slug": "homewood", "metadata": {}}

GENERIC = "Regular City Council Meeting"


def _utc(y, mo, d, h, mi) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


# The four events the city page listed on 2026-10-21, as the parser stores them.
COUNCIL_TUE = {"id": 4848, "title": "BIRMINGHAM CITY COUNCIL MEETING, October 20, 2026", "starts_at": _utc(2026, 10, 20, 14, 30)}
ECON_TUE = {"id": 4858, "title": "ECONOMIC & WORKFORCE DEVELOPMENT/TOURISM COMMITTEE MEETING, October 20, 2026", "starts_at": _utc(2026, 10, 20, 16, 30)}
COW_WED = {"id": 4854, "title": "COMMITTEE OF THE WHOLE/ADMINISTRATION & GOVERNMENTAL AFFAIRS COMMITTEE MEETING, October 21, 2026", "starts_at": _utc(2026, 10, 21, 20, 30)}
TRANSPO_MON = {"id": 4864, "title": "TRANSPORTATION AND INFRASTRUCTURE COMMITTEE MEETING, October 26, 2026", "starts_at": _utc(2026, 10, 26, 19, 0)}


def _meeting(title=GENERIC, meeting_date=TUESDAY, *, minutes_url=None, start_time=time(2, 0),
             type_locked_at=None, id=10) -> dict:
    return {
        "id": id,
        "title": title,
        "meeting_date": meeting_date,
        "minutes_url": minutes_url,
        "start_time": start_time,
        "type_locked_at": type_locked_at,
    }


def _triple(res) -> tuple:
    c = res.classification
    return (c.meeting_type, c.session_kind, c.body_name, res.type_source, res.calendar_event_id)


class TestLock:
    def test_locked_row_returns_none(self):
        from docket.services.meeting_types import resolve

        m = _meeting(type_locked_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
        assert resolve(BIRMINGHAM, m, calendar_events=[COUNCIL_TUE], item_count=5) is None


class TestTitleRung:
    @pytest.mark.parametrize("day", [MONDAY, TUESDAY, WEDNESDAY])
    def test_homewood_committee_title_resolves_from_the_title_whatever_the_weekday(self, day):
        from docket.services.meeting_types import resolve

        res = resolve(HOMEWOOD, _meeting("Finance Committee", day), calendar_events=[], item_count=0)
        assert _triple(res) == ("committee", "regular", "Finance Committee", "title", None)

    def test_specific_title_is_not_overridden_by_the_calendar_or_the_rule(self):
        from docket.services.meeting_types import resolve

        m = _meeting("Special Called Council Meeting", MONDAY)
        res = resolve(BIRMINGHAM, m, calendar_events=[TRANSPO_MON | {"starts_at": _utc(2026, 10, 19, 19, 0)}], item_count=0)
        assert _triple(res) == ("council", "special", None, "title", None)

    def test_tuesday_generic_title_with_nothing_else_is_the_council(self):
        from docket.services.meeting_types import resolve

        res = resolve(BIRMINGHAM, _meeting(GENERIC, TUESDAY), calendar_events=[], item_count=0)
        assert _triple(res) == ("council", "regular", None, "title", None)


class TestCalendarRung:
    @pytest.mark.parametrize("start_time", [time(2, 0), time(11, 0)])
    def test_one_committee_event_names_the_body(self, start_time):
        from docket.services.meeting_types import resolve

        m = _meeting(GENERIC, WEDNESDAY, start_time=start_time)
        res = resolve(BIRMINGHAM, m, calendar_events=[COUNCIL_TUE, ECON_TUE, COW_WED, TRANSPO_MON], item_count=51)
        assert _triple(res) == (
            "committee", "regular", "Committee of the Whole / Administration & Governmental Affairs", "calendar", 4854,
        )

    def test_canonical_name_matches_and_over_ampersand(self):
        from docket.services.meeting_types import resolve

        m = _meeting(GENERIC, date(2026, 10, 26))
        res = resolve(BIRMINGHAM, m, calendar_events=[TRANSPO_MON], item_count=0)
        assert _triple(res) == ("committee", "regular", "Transportation & Infrastructure", "calendar", 4864)

    def test_unlisted_committee_falls_back_to_the_cleaned_event_title(self):
        from docket.services.meeting_types import resolve

        ev = {"id": 5000, "title": "PUBLIC WORKS  COMMITTEE MEETING, October 21, 2026", "starts_at": _utc(2026, 10, 21, 20, 0)}
        res = resolve(BIRMINGHAM, _meeting(GENERIC, WEDNESDAY), calendar_events=[ev], item_count=0)
        assert _triple(res) == ("committee", "regular", "Public Works Committee", "calendar", 5000)

    def test_one_council_event_names_the_council_before_its_minutes_arrive(self):
        from docket.services.meeting_types import resolve

        ev = {"id": 5001, "title": "BIRMINGHAM CITY COUNCIL MEETING, October 19, 2026", "starts_at": _utc(2026, 10, 19, 14, 30)}
        res = resolve(BIRMINGHAM, _meeting(GENERIC, MONDAY), calendar_events=[ev], item_count=0)
        assert _triple(res) == ("council", "regular", None, "calendar", 5001)

    def test_special_council_event_is_a_special_sitting(self):
        from docket.services.meeting_types import resolve

        ev = {"id": 5002, "title": "SPECIAL CALLED CITY COUNCIL MEETING, October 19, 2026", "starts_at": _utc(2026, 10, 19, 14, 30)}
        res = resolve(BIRMINGHAM, _meeting(GENERIC, MONDAY), calendar_events=[ev], item_count=0)
        assert _triple(res) == ("council", "special", None, "calendar", 5002)

    @pytest.mark.parametrize("start_time", [time(2, 0), time(11, 0)])
    def test_tuesday_two_events_row_with_minutes_takes_the_council(self, start_time):
        from docket.services.meeting_types import resolve

        m = _meeting(GENERIC, TUESDAY, minutes_url="https://example.com/minutes.pdf", start_time=start_time)
        res = resolve(BIRMINGHAM, m, calendar_events=[COUNCIL_TUE, ECON_TUE], item_count=0)
        assert _triple(res) == ("council", "regular", None, "calendar", 4848)

    def test_tuesday_two_events_row_with_items_takes_the_council(self):
        from docket.services.meeting_types import resolve

        res = resolve(BIRMINGHAM, _meeting(GENERIC, TUESDAY), calendar_events=[COUNCIL_TUE, ECON_TUE], item_count=87)
        assert _triple(res) == ("council", "regular", None, "calendar", 4848)

    @pytest.mark.parametrize("start_time", [time(2, 0), time(11, 0)])
    def test_tuesday_two_events_row_without_documents_takes_the_committee(self, start_time):
        from docket.services.meeting_types import resolve

        m = _meeting(GENERIC, TUESDAY, start_time=start_time)
        res = resolve(BIRMINGHAM, m, calendar_events=[COUNCIL_TUE, ECON_TUE], item_count=0)
        assert _triple(res) == (
            "committee", "regular", "Economic and Workforce Development / Tourism", "calendar", 4858,
        )

    def test_tuesday_two_committee_events_and_no_documents_falls_past_the_calendar(self):
        from docket.services.meeting_types import resolve

        other = {"id": 4859, "title": "PUBLIC SAFETY COMMITTEE MEETING, October 20, 2026", "starts_at": _utc(2026, 10, 20, 18, 0)}
        res = resolve(BIRMINGHAM, _meeting(GENERIC, TUESDAY), calendar_events=[ECON_TUE, other], item_count=0)
        assert _triple(res) == ("council", "regular", None, "title", None)

    def test_two_council_events_and_documents_yields_nothing_from_the_calendar(self):
        from docket.services.meeting_types import resolve

        twin = {"id": 4849, "title": "BIRMINGHAM CITY COUNCIL MEETING, October 20, 2026 (Part II)", "starts_at": _utc(2026, 10, 20, 18, 0)}
        m = _meeting(GENERIC, TUESDAY, minutes_url="x")
        res = resolve(BIRMINGHAM, m, calendar_events=[COUNCIL_TUE, twin], item_count=0)
        assert _triple(res) == ("council", "regular", None, "title", None)

    def test_an_event_naming_neither_body_is_dropped(self):
        from docket.services.meeting_types import resolve

        ev = {"id": 5003, "title": "PRESS CONFERENCE, October 19, 2026", "starts_at": _utc(2026, 10, 19, 15, 0)}
        res = resolve(BIRMINGHAM, _meeting(GENERIC, MONDAY), calendar_events=[ev], item_count=0)
        assert _triple(res) == ("committee", "regular", None, "schedule_rule", None), "the rule still applies"

    def test_events_on_other_days_do_not_match(self):
        from docket.services.meeting_types import resolve

        res = resolve(BIRMINGHAM, _meeting(GENERIC, MONDAY), calendar_events=[COUNCIL_TUE, ECON_TUE, COW_WED], item_count=0)
        assert _triple(res) == ("committee", "regular", None, "schedule_rule", None)

    def test_event_day_is_read_in_chicago_time(self):
        from docket.services.meeting_types import resolve

        # 2026-10-22T03:00Z is still 2026-10-21 22:00 in Chicago.
        ev = {"id": 5004, "title": "PUBLIC SAFETY COMMITTEE MEETING, October 21, 2026", "starts_at": _utc(2026, 10, 22, 3, 0)}
        res = resolve(BIRMINGHAM, _meeting(GENERIC, WEDNESDAY), calendar_events=[ev], item_count=0)
        assert _triple(res) == ("committee", "regular", "Public Safety", "calendar", 5004)

    def test_a_row_with_minutes_never_takes_a_committee_event(self):
        from docket.services.meeting_types import resolve

        m = _meeting(GENERIC, WEDNESDAY, minutes_url="https://example.com/minutes.pdf")
        res = resolve(BIRMINGHAM, m, calendar_events=[COW_WED], item_count=51)
        assert _triple(res) == ("council", "regular", None, "title", None)

    def test_city_without_calendar_url_skips_the_calendar(self):
        from docket.services.meeting_types import resolve

        no_calendar = {"id": 3, "slug": "x", "metadata": {"council_schedule": {"weekday": 1}}}
        res = resolve(no_calendar, _meeting(GENERIC, WEDNESDAY), calendar_events=[COW_WED], item_count=0)
        assert _triple(res) == ("committee", "regular", None, "schedule_rule", None)


class TestScheduleRule:
    @pytest.mark.parametrize("item_count", [0, 50])
    @pytest.mark.parametrize("start_time", [time(2, 0), time(11, 0)])
    def test_monday_without_minutes_is_a_committee_whatever_its_items(self, item_count, start_time):
        from docket.services.meeting_types import resolve

        m = _meeting(GENERIC, MONDAY, start_time=start_time)
        res = resolve(BIRMINGHAM, m, calendar_events=[], item_count=item_count)
        assert _triple(res) == ("committee", "regular", None, "schedule_rule", None)

    def test_monday_with_minutes_is_the_council(self):
        from docket.services.meeting_types import resolve

        m = _meeting(GENERIC, MONDAY, minutes_url="https://example.com/minutes.pdf")
        res = resolve(BIRMINGHAM, m, calendar_events=[], item_count=0)
        assert _triple(res) == ("council", "regular", None, "title", None)

    def test_tuesday_is_the_council(self):
        from docket.services.meeting_types import resolve

        res = resolve(BIRMINGHAM, _meeting(GENERIC, TUESDAY), calendar_events=[], item_count=0)
        assert _triple(res) == ("council", "regular", None, "title", None)

    def test_cancelled_monday_is_the_council(self):
        from docket.services.meeting_types import resolve

        m = _meeting("Regular City Council Meeting - Cancelled (Next Regular Meeting 10/27/2026)", MONDAY)
        res = resolve(BIRMINGHAM, m, calendar_events=[], item_count=0)
        assert _triple(res) == ("council", "regular", None, "title", None)

    def test_metadata_as_a_json_string_is_read(self):
        from docket.services.meeting_types import resolve

        muni = {"id": 1, "slug": "birmingham", "metadata": '{"council_schedule": {"weekday": 1}}'}
        res = resolve(muni, _meeting(GENERIC, MONDAY), calendar_events=[], item_count=0)
        assert _triple(res) == ("committee", "regular", None, "schedule_rule", None)

    def test_meeting_date_as_a_string_is_read(self):
        from docket.services.meeting_types import resolve

        res = resolve(BIRMINGHAM, _meeting(GENERIC, "2026-10-19"), calendar_events=[], item_count=0)
        assert _triple(res) == ("committee", "regular", None, "schedule_rule", None)


class TestVocabulary:
    def test_type_sources_and_committees(self):
        from docket.services.meeting_types import BIRMINGHAM_COMMITTEES, TYPE_SOURCES

        assert TYPE_SOURCES == ("title", "calendar", "schedule_rule", "admin")
        assert len(BIRMINGHAM_COMMITTEES) == 8
        assert "Committee of the Whole / Administration & Governmental Affairs" in BIRMINGHAM_COMMITTEES


class TestSummaryClearing:
    def test_ids_leaving_council_are_selected(self):
        from docket.services.meeting_types import summary_clear_ids

        rows = [
            {"id": 1, "meeting_type": "council", "new_meeting_type": "committee"},
            {"id": 2, "meeting_type": "council", "new_meeting_type": "council"},
            {"id": 3, "meeting_type": "committee", "new_meeting_type": "council"},
            {"id": 4, "meeting_type": "council", "new_meeting_type": "other"},
            {"id": 5, "meeting_type": "special", "new_meeting_type": "council"},
            {"id": 6, "meeting_type": "committee", "new_meeting_type": "board"},
        ]
        assert summary_clear_ids(rows) == [1, 4]
