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
Plan: plans/completed/meeting-types-name-the-body.md (M4).
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

    def test_a_row_with_items_on_the_council_day_does_not_take_a_lone_committee_event(self):
        """2026-11-03: the calendar table held the day's committee work session but not
        its council meeting, and the 63-item council clip was named after the committee."""
        from docket.services.meeting_types import resolve

        ws = {"id": 5005, "title": "ECONOMIC DEVELOPMENT & TOURISM COMMITTEE WORK SESSION, November 3, 2026", "starts_at": _utc(2026, 11, 3, 17, 30)}
        res = resolve(BIRMINGHAM, _meeting(GENERIC, date(2026, 11, 3)), calendar_events=[ws], item_count=63)
        assert _triple(res) == ("council", "regular", None, "title", None)

    def test_a_row_without_documents_on_the_council_day_still_takes_a_lone_committee_event(self):
        from docket.services.meeting_types import resolve

        ws = {"id": 5005, "title": "ECONOMIC DEVELOPMENT & TOURISM COMMITTEE WORK SESSION, November 3, 2026", "starts_at": _utc(2026, 11, 3, 17, 30)}
        res = resolve(BIRMINGHAM, _meeting(GENERIC, date(2026, 11, 3)), calendar_events=[ws], item_count=0)
        assert _triple(res) == ("committee", "regular", "Economic Development & Tourism Committee Work Session", "calendar", 5005)

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

        assert TYPE_SOURCES == ("title", "video", "calendar", "schedule_rule", "admin")
        assert len(BIRMINGHAM_COMMITTEES) == 8
        assert "Committee of the Whole / Administration & Governmental Affairs" in BIRMINGHAM_COMMITTEES


class TestVideoRung:
    """The rung between the specific title and the calendar: a YouTube
    recording attached to the row (``meeting_videos``) whose cleaned title
    names a body. Plan: plans/completed/youtube-council-channel.md (M3)."""

    def test_generic_row_takes_the_body_from_its_youtube_recording(self):
        from docket.services.meeting_types import resolve

        res = resolve(BIRMINGHAM, _meeting(GENERIC, TUESDAY), calendar_events=[], item_count=0,
                      video_titles=["Budget and Finance Committee Meeting"])
        assert _triple(res) == ("committee", "regular", "Budget and Finance Committee", "video", None)

    def test_video_outranks_the_calendar(self):
        from docket.services.meeting_types import resolve

        res = resolve(BIRMINGHAM, _meeting(GENERIC, TUESDAY), calendar_events=[COUNCIL_TUE, ECON_TUE],
                      item_count=0, video_titles=["Budget and Finance Committee Meeting"])
        assert _triple(res) == ("committee", "regular", "Budget and Finance Committee", "video", None)

    def test_video_outranks_the_schedule_rule(self):
        from docket.services.meeting_types import resolve

        res = resolve(BIRMINGHAM, _meeting(GENERIC, MONDAY), calendar_events=[], item_count=0,
                      video_titles=["Committee of the Whole Meeting"])
        assert _triple(res) == ("committee", "regular", "Committee of the Whole", "video", None)

    def test_generic_video_title_falls_through_to_the_title_rung(self):
        from docket.services.meeting_types import resolve

        res = resolve(BIRMINGHAM, _meeting(GENERIC, TUESDAY), calendar_events=[], item_count=0,
                      video_titles=["Birmingham City Council Meeting"])
        assert _triple(res) == ("council", "regular", None, "title", None)

    def test_generic_video_title_falls_through_to_the_calendar(self):
        from docket.services.meeting_types import resolve

        res = resolve(BIRMINGHAM, _meeting(GENERIC, TUESDAY), calendar_events=[COUNCIL_TUE, ECON_TUE],
                      item_count=0, video_titles=["Birmingham City Council Meeting"])
        assert _triple(res)[3] == "calendar"

    def test_first_specific_entry_decides(self):
        from docket.services.meeting_types import resolve

        res = resolve(BIRMINGHAM, _meeting(GENERIC, TUESDAY), calendar_events=[], item_count=0,
                      video_titles=["Birmingham City Council Meeting", "Public Safety Committee Meeting",
                                    "Budget and Finance Committee Meeting"])
        assert _triple(res) == ("committee", "regular", "Public Safety Committee", "video", None)

    def test_specific_title_keeps_the_title_rung(self):
        from docket.services.meeting_types import resolve

        res = resolve(BIRMINGHAM, _meeting("Budget Hearing", TUESDAY), calendar_events=[], item_count=0,
                      video_titles=["Budget and Finance Committee Meeting"])
        assert _triple(res) == ("council", "budget_hearing", None, "title", None)

    def test_locked_row_returns_none(self):
        from docket.services.meeting_types import resolve

        m = _meeting(type_locked_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
        assert resolve(BIRMINGHAM, m, calendar_events=[], item_count=0,
                       video_titles=["Budget and Finance Committee Meeting"]) is None

    @pytest.mark.parametrize("titles", [None, []])
    def test_no_video_titles_behaves_as_before(self, titles):
        from docket.services.meeting_types import resolve

        res = resolve(BIRMINGHAM, _meeting(GENERIC, MONDAY), calendar_events=[], item_count=0, video_titles=titles)
        assert _triple(res) == ("committee", "regular", None, "schedule_rule", None)

    def test_changes_passes_the_rows_video_titles(self):
        from docket.services.meeting_types import _changes

        row = _meeting(GENERIC, TUESDAY)
        row.update(item_count=0, meeting_type="council", session_kind="regular", body_name=None,
                   type_source="title", calendar_event_id=None,
                   video_titles=["Budget and Finance Committee Meeting"])
        changed = _changes(BIRMINGHAM, [row], [])
        assert [m["id"] for m in changed] == [10]
        assert changed[0]["resolution"].type_source == "video"


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


# --- the whole day (plan `committee-clips-named-or-hidden`, M2) -------------------
#
# 2026-11-09 is a Monday with two committee events, X and Y. R is the row
# under test: the clerk's generic title, no minutes, no items. A sibling is
# another non-hidden row of the same day, given to `resolve` as the facts it
# reads of the row itself.

NOV9 = date(2026, 11, 9)
X = {"id": 4942, "title": "BUDGET AND FINANCE COMMITTEE MEETING, November 9, 2026",
     "starts_at": _utc(2026, 11, 9, 21, 30), "event_status": "active"}
Y = {"id": 4941, "title": "TRANSPORTATION AND INFRASTRUCTURE COMMITTEE  MEETING, November 9, 2026",
     "starts_at": _utc(2026, 11, 9, 20, 0), "event_status": "active"}
RULE = ("committee", "regular", None, "schedule_rule", None)
NAMED_Y = ("committee", "regular", "Transportation & Infrastructure", "calendar", 4941)
NAMED_X = ("committee", "regular", "Budget and Finance", "calendar", 4942)


def _sibling(title=GENERIC, *, duration_s=None, item_count=0, minutes_url=None, video_titles=None,
             type_locked_at=None, meeting_type="council", body_name=None) -> dict:
    return {
        "title": title, "minutes_url": minutes_url, "type_locked_at": type_locked_at,
        "meeting_type": meeting_type, "body_name": body_name, "item_count": item_count,
        "video_titles": video_titles, "duration_s": duration_s,
    }


S = _sibling("Budget and Finance Committee Meeting", duration_s=5760)


def _day(events, *, duration_s=None, siblings=(), item_count=0, meeting_date=NOV9, minutes_url=None) -> tuple:
    from docket.services.meeting_types import resolve

    res = resolve(BIRMINGHAM, _meeting(GENERIC, meeting_date, minutes_url=minutes_url), calendar_events=list(events),
                  item_count=item_count, duration_s=duration_s, siblings=list(siblings))
    return _triple(res)


class TestSameCommittee:
    def test_a_raw_event_title_against_a_recordings_name(self):
        from docket.services.meeting_types import same_committee

        assert same_committee(X["title"], "Budget and Finance Committee") is True
        assert same_committee("Budget and Finance Committee", X["title"]) is True

    def test_a_short_name_that_opens_the_long_one(self):
        from docket.services.meeting_types import same_committee

        event = "COMMITTEE OF THE WHOLE/ADMINISTRATION AND GOVERNMENTAL AFFAIRS COMMITTEE MEETING, October 21, 2026"
        assert same_committee("Committee of the Whole", event) is True

    def test_two_committees_are_not_one(self):
        from docket.services.meeting_types import same_committee

        assert same_committee("Public Safety Committee", "Planning & Zoning") is False

    def test_a_prefix_under_eight_letters_is_not_enough(self):
        from docket.services.meeting_types import same_committee

        assert same_committee("Public Committee", "Public Works Committee") is False
        assert same_committee("Planning Committee", "Planning & Zoning") is True, "PLANNING is eight letters"

    def test_the_date_and_the_canonical_name_are_read_before_the_trailing_words(self):
        """Added after the failing-first commit: removing `committee_name_for`
        from either side, the trailing-word strip from the second, or "work
        session" from the words failed no test, because the prefix rule
        answered for every name of eight letters or more."""
        from docket.services.meeting_types import same_committee

        special = "SPECIAL CALLED ARTS AND PARKS COMMITTEE MEETING, November 2, 2026"
        assert same_committee(special, "Arts and Parks Committee") is True
        assert same_committee("Arts and Parks Committee", special) is True
        dated = "ARTS COMMITTEE MEETING, November 2, 2026"
        assert same_committee(dated, "Arts Committee") is True
        assert same_committee("Arts Committee", dated) is True
        assert same_committee("Arts Committee Work Session", "Arts Committee") is True
        assert same_committee("Arts Committee", "Arts Committee Work Session") is True

    def test_trailing_words_are_dropped_and_a_name_of_nothing_else_matches_nothing(self):
        from docket.services.meeting_types import same_committee

        assert same_committee("Public Works Committee Work Session", "Public Works Committee Meeting") is True
        assert same_committee("Committee Meeting", "Committee") is False
        assert same_committee("", "") is False


class TestWholeDay:
    def test_case_1_the_committee_the_named_recording_leaves_over(self):
        assert _day([X, Y], duration_s=2220, siblings=[S]) == NAMED_Y

    def test_case_2_a_short_recording_is_not_named_by_elimination(self):
        assert _day([X, Y], duration_s=240, siblings=[S]) == RULE

    def test_a_recording_of_unknown_length_is_not_named_by_elimination(self):
        assert _day([X, Y], duration_s=None, siblings=[S]) == RULE

    def test_six_hundred_seconds_is_long(self):
        assert _day([X, Y], duration_s=600, siblings=[S]) == NAMED_Y
        assert _day([X, Y], duration_s=599, siblings=[S]) == RULE

    def test_case_3_a_long_competitor_stops_elimination_and_a_short_one_does_not(self):
        assert _day([X, Y], duration_s=2220, siblings=[S, _sibling(duration_s=3000)]) == RULE
        assert _day([X, Y], duration_s=2220, siblings=[S, _sibling(duration_s=180)]) == NAMED_Y

    def test_a_competitor_of_unknown_length_stops_elimination(self):
        assert _day([X, Y], duration_s=2220, siblings=[S, _sibling(duration_s=None)]) == RULE

    def test_case_4_two_events_and_no_namer(self):
        assert _day([X, Y], duration_s=2220) == RULE

    def test_two_namers_leave_nothing_over(self):
        t = _sibling("Transportation and Infrastructure Committee Meeting", duration_s=3000)
        assert _day([X, Y], duration_s=2220, siblings=[S, t]) == RULE

    def test_case_5_a_namer_whose_name_opens_the_events(self):
        cow = {"id": 4854, "title": "COMMITTEE OF THE WHOLE/ADMINISTRATION AND GOVERNMENTAL AFFAIRS COMMITTEE MEETING, October 21, 2026",
               "starts_at": _utc(2026, 10, 21, 20, 30)}
        ps = {"id": 4860, "title": "PUBLIC SAFETY COMMITTEE MEETING, October 21, 2026", "starts_at": _utc(2026, 10, 21, 18, 0)}
        namer = _sibling("Committee of the Whole Meeting", duration_s=4000)
        assert _day([cow, ps], duration_s=2220, siblings=[namer], meeting_date=WEDNESDAY) == (
            "committee", "regular", "Public Safety", "calendar", 4860,
        )

    def test_case_6_a_row_with_agenda_items_and_no_council_event_is_eligible(self):
        assert _day([X, Y], duration_s=2220, siblings=[S], item_count=3) == NAMED_Y

    def test_case_7_a_short_clip_does_not_share_the_name_with_a_full_length_recording(self):
        long_sibling = _sibling(duration_s=2700)
        assert _day([X], duration_s=120, siblings=[long_sibling]) == RULE
        # The sibling, resolved in its own call with R as its sibling, takes the name.
        assert _day([X], duration_s=2700, siblings=[_sibling(duration_s=120)]) == NAMED_X
        # Alone, the short clip is named, as before.
        assert _day([X], duration_s=120) == NAMED_X

    def test_a_short_clip_beside_a_short_or_unmeasured_one_is_still_named(self):
        assert _day([X], duration_s=120, siblings=[_sibling(duration_s=300)]) == NAMED_X
        assert _day([X], duration_s=120, siblings=[_sibling(duration_s=None)]) == NAMED_X

    def test_an_unmeasured_clip_beside_a_full_length_one_is_still_named(self):
        assert _day([X], duration_s=None, siblings=[_sibling(duration_s=2700)]) == NAMED_X

    def test_case_8_a_cancelled_event_names_nothing_and_claims_nothing(self):
        assert _day([X | {"event_status": "cancelled"}, Y], duration_s=2220) == NAMED_Y
        assert _day([X | {"event_status": "cancelled"}], duration_s=2220) == RULE

    def test_an_event_whose_title_says_cancelled_is_dropped(self):
        gone = X | {"title": "BUDGET AND FINANCE COMMITTEE MEETING, November 9, 2026 - CANCELLED"}
        assert _day([gone, Y], duration_s=2220) == NAMED_Y

    def test_an_event_with_no_status_is_a_held_event(self):
        assert _day([X | {"event_status": None}, Y], duration_s=2220) == RULE
        no_key = {k: v for k, v in X.items() if k != "event_status"}
        assert _day([no_key, Y], duration_s=2220) == RULE

    def test_case_9_the_council_row_of_a_tuesday_is_not_a_competitor(self):
        ps = {"id": 4859, "title": "PUBLIC SAFETY COMMITTEE MEETING, October 20, 2026", "starts_at": _utc(2026, 10, 20, 18, 0)}
        council_row = _sibling(duration_s=9000, item_count=87)
        namer = _sibling("Public Safety Committee Meeting", duration_s=3000)
        assert _day([COUNCIL_TUE, ECON_TUE, ps], duration_s=2220, siblings=[council_row, namer],
                    meeting_date=TUESDAY) == (
            "committee", "regular", "Economic and Workforce Development / Tourism", "calendar", 4858,
        )
        # The council row itself, resolved with the other two as siblings, takes the council event.
        assert _day([COUNCIL_TUE, ECON_TUE, ps], duration_s=9000, item_count=87,
                    siblings=[_sibling(duration_s=2220), namer], meeting_date=TUESDAY) == (
            "council", "regular", None, "calendar", 4848,
        )

    def test_a_sibling_with_minutes_is_not_a_competitor(self):
        with_minutes = _sibling(duration_s=9000, minutes_url="https://example.com/minutes.pdf")
        assert _day([X, Y], duration_s=2220, siblings=[S, with_minutes]) == NAMED_Y

    def test_a_sibling_with_items_on_a_day_without_a_council_event_is_a_competitor(self):
        assert _day([X, Y], duration_s=2220, siblings=[S, _sibling(duration_s=3000, item_count=4)]) == RULE

    def test_a_named_or_locked_sibling_is_not_a_competitor(self):
        locked_council = _sibling(duration_s=3000, type_locked_at=datetime(2026, 11, 1, tzinfo=timezone.utc))
        special = _sibling("Special Called Council Meeting", duration_s=3000)
        assert _day([X, Y], duration_s=2220, siblings=[S, locked_council, special]) == NAMED_Y

    def test_a_recording_names_a_sibling(self):
        by_video = _sibling(duration_s=5760, video_titles=["Birmingham City Council Meeting",
                                                           "Budget and Finance Committee Meeting"])
        assert _day([X, Y], duration_s=2220, siblings=[by_video]) == NAMED_Y

    def test_a_locked_committee_row_is_a_namer_by_its_stored_name(self):
        locked = _sibling(duration_s=5760, type_locked_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
                          meeting_type="committee", body_name="Budget and Finance")
        assert _day([X, Y], duration_s=2220, siblings=[locked]) == NAMED_Y
        unnamed = locked | {"body_name": None}
        assert _day([X, Y], duration_s=2220, siblings=[unnamed]) == RULE

    def test_a_row_with_minutes_takes_the_one_council_event_whatever_the_committees(self):
        council = {"id": 5100, "title": "BIRMINGHAM CITY COUNCIL MEETING, November 9, 2026", "starts_at": _utc(2026, 11, 9, 15, 30)}
        assert _day([council, X, Y], duration_s=9000, minutes_url="x") == ("council", "regular", None, "calendar", 5100)
        assert _day([X], duration_s=9000, minutes_url="x") == ("council", "regular", None, "title", None)

    def test_a_row_with_items_takes_the_council_event_on_any_weekday(self):
        """Added after the failing-first commit: nothing told a row with items
        beside a council event on a day that is not the council's from a row
        without documents."""
        council = {"id": 5100, "title": "BIRMINGHAM CITY COUNCIL MEETING, November 9, 2026", "starts_at": _utc(2026, 11, 9, 15, 30)}
        assert _day([council, X], duration_s=9000, item_count=5) == ("council", "regular", None, "calendar", 5100)
        # As a sibling, such a row is not a competitor either.
        assert _day([council, X, Y], duration_s=2220,
                    siblings=[S, _sibling(duration_s=9000, item_count=5)]) == NAMED_Y

    def test_only_a_committee_row_is_a_namer(self):
        """Added after the failing-first commit: a locked planning row whose
        stored name reads like a committee's set the event aside."""
        pz = {"id": 4950, "title": "PLANNING AND ZONING COMMITTEE MEETING, November 9, 2026", "starts_at": _utc(2026, 11, 9, 22, 0)}
        locked = _sibling(duration_s=5000, type_locked_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
                          meeting_type="planning", body_name="Planning & Zoning")
        assert _day([pz, Y], duration_s=2220, siblings=[locked]) == RULE
        assert _day([pz, Y], duration_s=2220, siblings=[locked | {"meeting_type": "committee"}]) == NAMED_Y

    def test_a_row_with_items_and_two_council_events_gets_nothing(self):
        twin = {"id": 4849, "title": "BIRMINGHAM CITY COUNCIL MEETING, October 20, 2026 (Part II)", "starts_at": _utc(2026, 10, 20, 18, 0)}
        assert _day([COUNCIL_TUE, twin, ECON_TUE], item_count=5, meeting_date=TUESDAY) == (
            "council", "regular", None, "title", None,
        )

    def test_a_row_without_documents_takes_the_council_event_only_when_it_is_the_days_only_event(self):
        council = {"id": 5100, "title": "BIRMINGHAM CITY COUNCIL MEETING, November 9, 2026", "starts_at": _utc(2026, 11, 9, 15, 30)}
        twin = council | {"id": 5101}
        assert _day([council]) == ("council", "regular", None, "calendar", 5100)
        assert _day([council, twin]) == RULE

    def test_changes_gives_each_row_its_length_and_the_days_other_rows(self):
        from docket.services.meeting_types import _changes

        def row(id, title, duration_s, **extra):
            r = _meeting(title, NOV9, id=id)
            r.update(item_count=0, meeting_type="council", session_kind="regular", body_name=None,
                     type_source="title", calendar_event_id=None, video_titles=None,
                     duration_s=duration_s, is_hidden=False)
            r.update(extra)
            return r

        named = row(1, GENERIC, 5760, video_titles=["Budget and Finance Committee Meeting"])
        generic = row(2, GENERIC, 2220)
        other_day = row(3, GENERIC, 3000, meeting_date=date(2026, 11, 16))
        hidden = row(4, GENERIC, 3000, is_hidden=True)
        changed = _changes(BIRMINGHAM, [named, generic, other_day, hidden], [X, Y])
        got = {m["id"]: _triple(m["resolution"]) for m in changed}
        assert got[2] == NAMED_Y, "the hidden row and the other day's row are not its competitors"
        assert got[1] == ("committee", "regular", "Budget and Finance Committee", "video", None)
