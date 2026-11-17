"""docket.services.coming_up: the entries of the next 60 days, in three kinds.

Every row is seeded under Birmingham: meetings whose titles begin
``COMINGUP_TEST_`` and calendar events whose ``source_event_id`` begins the
same. The meetings, the events, and the hearings the seeded items were
linked to are deleted before and after every test. ``today`` is always
passed in, so no test depends on the day it runs; the checked-in schedule
gives no neighborhood meeting after 2026-12-31. The service's names are
imported inside each test, so the file collects before the service exists.
Runs in the services tier (DATABASE_URL names docket_test_*).

Plan `birmingham-coming-up`, M6.
"""

from __future__ import annotations

import itertools
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from docket.db import db_cursor

FIXTURE = Path(__file__).parent.parent / "fixtures" / "hearings" / "birmingham_titles.json"
TITLES = {row["id"]: row["title"] for row in json.loads(FIXTURE.read_text())}
PREFIX = "COMINGUP_TEST_"
CHICAGO = ZoneInfo("America/Chicago")
UTC = ZoneInfo("UTC")

TODAY = date(2026, 11, 16)
NOV_17 = date(2026, 11, 17)
NOV_23 = date(2026, 11, 23)
NOV_24 = date(2026, 11, 24)
OCT_13 = date(2026, 10, 13)
OCT_26 = date(2026, 10, 26)
SINCE = date(2025, 1, 1)

COUNCIL_EVENT = "BIRMINGHAM CITY COUNCIL MEETING, November 17, 2026"
COMMITTEE_EVENT = "BUDGET AND FINANCE COMMITTEE MEETING, November 23, 2026"
GIVEAWAY_EVENT = "DISTRICT 4 200 HAMS GIVEAWAY AT LEGION FIELD"
AGENDA = "https://bhamal.granicus.com/AgendaViewer.php?view_id=2&event_id=990001"
PDF = (
    "https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/s3fs-public/2026-02/"
    "2026_NA_Meeting_Schedule_rev._2-3-2026.pdf"
)
BADGES = {"meeting", "zoning", "weed-lots", "vacation", "budget", "hearing", "neighborhood"}

_serial = itertools.count(1)


# --- seeding ----------------------------------------------------------------


def _city_row(slug: str = "birmingham") -> dict:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM municipalities WHERE slug = %s", (slug,))
        return dict(cur.fetchone())


def _delete_seeded() -> None:
    with db_cursor() as cur:
        cur.execute(
            """DELETE FROM public_hearings WHERE id IN (
                   SELECT phi.hearing_id FROM public_hearing_items phi
                     JOIN agenda_items ai ON ai.id = phi.agenda_item_id
                     JOIN meetings mt ON mt.id = ai.meeting_id
                    WHERE mt.title LIKE %s)""",
            (PREFIX + "%",),
        )
        cur.execute("DELETE FROM meetings WHERE title LIKE %s", (PREFIX + "%",))
        cur.execute("DELETE FROM city_calendar_events WHERE source_event_id LIKE %s", (PREFIX + "%",))


@pytest.fixture(autouse=True)
def _clean():
    _delete_seeded()
    yield
    _delete_seeded()


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=CHICAGO)


def _upcoming_row(
    day: date = NOV_17,
    *,
    title: str = "Regular City Council Meeting",
    start: time | None = time(11, 0),
    hidden: bool = False,
    meeting_type: str | None = "council",
    session_kind: str = "regular",
    body_name: str | None = None,
    event_id: int | None = None,
    agenda_url: str | None = AGENDA,
    city: str = "birmingham",
) -> int:
    """A meeting the video site lists and has not recorded: an `event-` row."""
    n = next(_serial)
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, external_id, title, meeting_date, start_time, is_hidden,
                                     meeting_type, session_kind, body_name, calendar_event_id, agenda_url)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (
                _city_row(city)["id"],
                f"event-99{n:04d}",
                PREFIX + title,
                day,
                start,
                hidden,
                meeting_type,
                session_kind,
                body_name,
                event_id,
                agenda_url,
            ),
        )
        return cur.fetchone()["id"]


def _event(
    starts: datetime,
    title: str = COUNCIL_EVENT,
    *,
    status: str | None = None,
    ends: datetime | None = None,
) -> int:
    n = next(_serial)
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO city_calendar_events (municipality_id, source_event_id, title, starts_at, ends_at,
                                                 source_url, event_status)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (_city_row()["id"], f"{PREFIX}{n}", title, starts, ends, _event_url(n), status),
        )
        return cur.fetchone()["id"]


def _event_url(n: int) -> str:
    return f"https://www.birminghamal.gov/events/comingup-test-{n}"


def _source_url(event_id: int) -> str:
    with db_cursor() as cur:
        cur.execute("SELECT source_url FROM city_calendar_events WHERE id = %s", (event_id,))
        return cur.fetchone()["source_url"]


def _held_meeting(day: date = OCT_13, *, agenda_url: str | None = AGENDA) -> int:
    """A recorded meeting, whose agenda holds the items that set hearings. Not an `event-` row."""
    n = next(_serial)
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type, agenda_url)
               VALUES (%s, %s, %s, %s, 'council', %s) RETURNING id""",
            (_city_row()["id"], f"comingup-test-{n}", PREFIX + "Regular meeting", day, agenda_url),
        )
        return cur.fetchone()["id"]


def _item(meeting_id: int, title: str) -> int:
    n = next(_serial)
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO agenda_items (meeting_id, external_id, title, processing_status)
               VALUES (%s, %s, %s, 'completed') RETURNING id""",
            (meeting_id, f"comingup-test-item-{n}", title),
        )
        return cur.fetchone()["id"]


def _store_hearings() -> None:
    from docket.services import hearings

    hearings.refresh_hearings(_city_row()["id"], SINCE)


def _hearing_of(item_id: int) -> int:
    with db_cursor() as cur:
        cur.execute("SELECT hearing_id FROM public_hearing_items WHERE agenda_item_id = %s", (item_id,))
        return cur.fetchone()["hearing_id"]


def _hearing(title: str, day: date = OCT_13, *, agenda_url: str | None = AGENDA) -> tuple[int, int]:
    """One item setting one hearing, stored. Returns the hearing's id and the item's."""
    item = _item(_held_meeting(day, agenda_url=agenda_url), title)
    _store_hearings()
    return _hearing_of(item), item


def _entries(today: date = TODAY, slug: str = "birmingham"):
    from docket.services import coming_up

    return coming_up.list_entries(_city_row(slug), today=today)


def _by_uid(entries) -> dict:
    return {e.uid: e for e in entries}


def _association(name: str, **changes):
    """An association of the checked-in schedule, with fields replaced."""
    from dataclasses import replace

    from docket.services import neighborhood_schedule

    schedule = neighborhood_schedule.get_schedule("birmingham")
    found = next(a for a in schedule.associations if a.name == name)
    return replace(found, **changes)


def _use_schedule(monkeypatch, *associations):
    """Make the service see a schedule of just these associations (the source block is the real one)."""
    from dataclasses import replace

    from docket.services import neighborhood_schedule

    real = neighborhood_schedule.get_schedule("birmingham")
    made = replace(real, associations=tuple(associations))
    monkeypatch.setattr(neighborhood_schedule, "get_schedule", lambda slug: made if slug == "birmingham" else None)
    return made


# --- the gate and the slug --------------------------------------------------


def test_birmingham_is_a_coming_up_city_and_mobile_is_not():
    from docket.services import coming_up

    assert coming_up.is_coming_up_city(_city_row("birmingham")) is True
    assert coming_up.is_coming_up_city(_city_row("mobile")) is False


@pytest.mark.parametrize(
    "municipality, expected",
    [
        (None, False),
        ({}, False),
        ({"metadata": None}, False),
        ({"metadata": {"coming_up": True}}, True),
        ({"metadata": '{"coming_up": true}'}, True),
        ({"metadata": {"coming_up": "true"}}, False),
        ({"metadata": {"coming_up": 1}}, False),
        ({"metadata": {"briefing": True}}, False),
        ({"metadata": "not json"}, False),
        ({"metadata": '["coming_up"]'}, False),
    ],
)
def test_is_coming_up_city_needs_the_boolean_true(municipality, expected):
    from docket.services import coming_up

    assert coming_up.is_coming_up_city(municipality) is expected


def test_association_slug():
    from docket.services import coming_up

    assert coming_up.association_slug("Acipco-Finley") == "acipco-finley"
    assert coming_up.association_slug("Forest Park/South Avondale") == "forest-park-south-avondale"
    assert coming_up.association_slug(" East  Lake (North) ") == "east-lake-north"
    assert coming_up.association_slug("5 Points West") == "5-points-west"


def test_the_window_is_sixty_days_and_the_kinds_are_three():
    from docket.services import coming_up

    assert coming_up.WINDOW_DAYS == 60
    assert coming_up.KINDS == ("meeting", "hearing", "neighborhood")


# --- meetings: the two sources, merged --------------------------------------


def test_the_production_case_one_merged_meeting_a_committee_alone_and_no_giveaway():
    """Production on 2026-11-16: meeting 3207 with event 120, event 79, and the giveaways."""
    from docket.adapters._helpers import label_for

    council_event = _event(_at(NOV_17, 9, 30), COUNCIL_EVENT, ends=_at(NOV_17, 12, 0))
    row = _upcoming_row(NOV_17, start=time(11, 0), event_id=council_event)
    committee_event = _event(_at(NOV_23, 15, 30), COMMITTEE_EVENT, status="active")
    giveaway = _event(_at(date(2026, 11, 21), 10, 0), GIVEAWAY_EVENT, status="active")

    found = _by_uid(_entries())

    merged = found[f"calendar-{council_event}@docket.pub"]
    assert f"meeting-{row}@docket.pub" not in found
    assert merged.kind == "meeting"
    assert merged.title == label_for("council", "regular", None, "x", cancelled=False) == "City Council meeting"
    assert merged.on == NOV_17
    # The calendar's time, not the row's 11:00 (issue #88).
    assert merged.starts_at == _at(NOV_17, 9, 30)
    assert merged.starts_at.utcoffset() == timedelta(hours=-6)
    assert merged.ends_at == _at(NOV_17, 12, 0)
    assert merged.ends_at.utcoffset() == timedelta(hours=-6)
    assert merged.links == (
        ("City calendar", _source_url(council_event)),
        ("Agenda", AGENDA),
        ("Meeting on docket.pub", f"/al/birmingham/meetings/{row}/"),
    )
    assert merged.source_url == _source_url(council_event)
    assert merged.cancelled is False
    assert merged.cancelled_by == ()
    assert merged.detail == ()
    assert merged.place is None
    assert merged.attend == ()
    assert merged.association is None
    assert (merged.badge, merged.badge_label) == ("meeting", "Meeting")

    committee = found[f"calendar-{committee_event}@docket.pub"]
    assert committee.title == label_for("committee", "regular", "Budget and Finance", "x", cancelled=False)
    assert committee.title == "Budget and Finance"
    assert committee.on == NOV_23
    assert committee.starts_at == _at(NOV_23, 15, 30)
    assert committee.ends_at is None
    assert committee.links == (("City calendar", _source_url(committee_event)),)
    assert committee.source_url == _source_url(committee_event)
    assert committee.cancelled is False

    assert f"calendar-{giveaway}@docket.pub" not in found


def test_a_council_row_and_a_council_event_of_one_day_merge_without_the_stored_link():
    event = _event(_at(NOV_17, 9, 30))
    row = _upcoming_row(NOV_17, event_id=None)

    found = _by_uid(_entries())

    assert f"meeting-{row}@docket.pub" not in found
    merged = found[f"calendar-{event}@docket.pub"]
    assert merged.links[2] == ("Meeting on docket.pub", f"/al/birmingham/meetings/{row}/")


def test_two_council_events_and_one_council_row_of_one_day_are_three_entries():
    first = _event(_at(NOV_17, 9, 30))
    second = _event(_at(NOV_17, 14, 0), "SPECIAL CALLED CITY COUNCIL MEETING, November 17, 2026")
    row = _upcoming_row(NOV_17)

    found = _by_uid(_entries())

    assert {f"calendar-{first}@docket.pub", f"calendar-{second}@docket.pub", f"meeting-{row}@docket.pub"} <= set(found)
    assert len(found[f"calendar-{first}@docket.pub"].links) == 1
    assert found[f"calendar-{second}@docket.pub"].title == "Special called council meeting"


def test_one_council_event_and_two_council_rows_of_one_day_are_three_entries():
    event = _event(_at(NOV_17, 9, 30))
    a, b = _upcoming_row(NOV_17), _upcoming_row(NOV_17)

    found = _by_uid(_entries())

    assert {f"calendar-{event}@docket.pub", f"meeting-{a}@docket.pub", f"meeting-{b}@docket.pub"} <= set(found)


def test_a_council_row_and_a_council_event_of_different_days_stay_apart():
    event = _event(_at(NOV_24, 9, 30))
    row = _upcoming_row(NOV_17)

    found = _by_uid(_entries())

    assert {f"calendar-{event}@docket.pub", f"meeting-{row}@docket.pub"} <= set(found)


def test_a_committee_row_and_a_committee_event_of_one_day_are_not_merged_by_the_day():
    """The second rule is for council sittings alone: two committees can sit on one day."""
    event = _event(_at(NOV_23, 15, 30), COMMITTEE_EVENT)
    row = _upcoming_row(NOV_23, meeting_type="committee", body_name="Budget and Finance")

    found = _by_uid(_entries())

    assert {f"calendar-{event}@docket.pub", f"meeting-{row}@docket.pub"} <= set(found)


def test_a_council_row_is_not_merged_with_a_committee_event_of_its_day():
    event = _event(_at(NOV_17, 15, 30), COMMITTEE_EVENT)
    row = _upcoming_row(NOV_17)

    found = _by_uid(_entries())

    assert {f"calendar-{event}@docket.pub", f"meeting-{row}@docket.pub"} <= set(found)


def test_the_stored_link_pairs_first_and_the_day_rule_takes_what_is_left():
    """Two council events and two council rows on one day; one row names its event."""
    named = _event(_at(NOV_17, 9, 30))
    other = _event(_at(NOV_17, 14, 0), "SPECIAL CALLED CITY COUNCIL MEETING, November 17, 2026")
    row_other = _upcoming_row(NOV_17, title="Special Called Meeting")
    row_named = _upcoming_row(NOV_17, event_id=named)

    found = _by_uid(_entries())

    assert f"meeting-{row_named}@docket.pub" not in found
    assert f"meeting-{row_other}@docket.pub" not in found
    assert found[f"calendar-{named}@docket.pub"].links[2][1] == f"/al/birmingham/meetings/{row_named}/"
    assert found[f"calendar-{other}@docket.pub"].links[2][1] == f"/al/birmingham/meetings/{row_other}/"


def test_a_stored_link_pairs_a_committee_row_with_its_event_whatever_the_day_rule_says():
    event = _event(_at(NOV_23, 15, 30), COMMITTEE_EVENT)
    row = _upcoming_row(NOV_23, meeting_type="committee", body_name="Budget and Finance", event_id=event, start=None)

    found = _by_uid(_entries())

    assert f"meeting-{row}@docket.pub" not in found
    assert found[f"calendar-{event}@docket.pub"].starts_at == _at(NOV_23, 15, 30)
    assert found[f"calendar-{event}@docket.pub"].title == "Budget and Finance"


def test_two_rows_naming_one_event_the_first_is_merged_and_the_second_stands_alone():
    event = _event(_at(NOV_24, 9, 30), "PUBLIC SAFETY COMMITTEE MEETING, November 24, 2026")
    first = _upcoming_row(NOV_24, meeting_type="committee", event_id=event)
    second = _upcoming_row(NOV_24, meeting_type="committee", event_id=event)

    found = _by_uid(_entries())

    assert found[f"calendar-{event}@docket.pub"].links[-1][1] == f"/al/birmingham/meetings/{first}/"
    assert f"meeting-{second}@docket.pub" in found
    assert f"meeting-{first}@docket.pub" not in found


def test_a_row_naming_a_giveaway_stands_alone_and_the_giveaway_is_dropped():
    giveaway = _event(_at(NOV_17, 10, 0), GIVEAWAY_EVENT)
    row = _upcoming_row(NOV_17, event_id=giveaway)

    found = _by_uid(_entries())

    assert f"calendar-{giveaway}@docket.pub" not in found
    alone = found[f"meeting-{row}@docket.pub"]
    assert alone.links == (("Agenda", AGENDA), ("Meeting on docket.pub", f"/al/birmingham/meetings/{row}/"))


def test_a_recorded_meeting_is_no_entry():
    """Only `event-` rows are meetings still to come; a recorded row is not listed."""
    held = _held_meeting(NOV_17)

    assert f"meeting-{held}@docket.pub" not in _by_uid(_entries())


def test_a_row_alone_prints_its_stored_time_and_its_own_links():
    row = _upcoming_row(NOV_24, start=time(11, 0))

    alone = _by_uid(_entries())[f"meeting-{row}@docket.pub"]

    assert alone.on == NOV_24
    assert alone.starts_at == _at(NOV_24, 11, 0)
    assert alone.starts_at.utcoffset() == timedelta(hours=-6)
    assert alone.ends_at is None
    assert alone.title == "City Council meeting"
    assert alone.links == (("Agenda", AGENDA), ("Meeting on docket.pub", f"/al/birmingham/meetings/{row}/"))
    assert alone.source_url == AGENDA


def test_a_row_with_no_start_time_and_no_event_has_no_time():
    row = _upcoming_row(NOV_24, start=None)

    assert _by_uid(_entries())[f"meeting-{row}@docket.pub"].starts_at is None


def test_a_row_with_no_agenda_has_the_meeting_page_alone_and_no_source():
    row = _upcoming_row(NOV_24, agenda_url=None)

    alone = _by_uid(_entries())[f"meeting-{row}@docket.pub"]

    assert alone.links == (("Meeting on docket.pub", f"/al/birmingham/meetings/{row}/"),)
    assert alone.source_url is None


def test_a_merged_row_with_no_agenda_has_two_links():
    event = _event(_at(NOV_17, 9, 30))
    row = _upcoming_row(NOV_17, event_id=event, agenda_url=None)

    merged = _by_uid(_entries())[f"calendar-{event}@docket.pub"]

    assert [label for label, _ in merged.links] == ["City calendar", "Meeting on docket.pub"]
    assert merged.source_url == _source_url(event)
    assert row


def test_a_rows_title_is_its_label_by_type_kind_and_body():
    special = _upcoming_row(NOV_24, session_kind="special")
    committee = _upcoming_row(NOV_24, meeting_type="committee", body_name="Public Safety", session_kind="work_session")
    other = _upcoming_row(NOV_24, title="Tree lighting", meeting_type="other")
    untyped = _upcoming_row(NOV_24, title="Something the video site listed", meeting_type=None)

    found = _by_uid(_entries())

    assert found[f"meeting-{special}@docket.pub"].title == "Special called council meeting"
    assert found[f"meeting-{committee}@docket.pub"].title == "Public Safety (work session)"
    assert found[f"meeting-{other}@docket.pub"].title == PREFIX + "Tree lighting"
    assert found[f"meeting-{untyped}@docket.pub"].title == PREFIX + "Something the video site listed"


def test_a_merged_meeting_is_titled_by_its_row_not_its_event():
    event = _event(_at(NOV_17, 9, 30))
    _upcoming_row(NOV_17, event_id=event, session_kind="work_session")

    assert _by_uid(_entries())[f"calendar-{event}@docket.pub"].title == "Council work session"


def test_an_event_is_placed_on_its_chicago_day_not_its_utc_day():
    """8:00 p.m. in Chicago on November 17 is 02:00 UTC on November 18."""
    late = datetime(2026, 11, 18, 2, 0, tzinfo=UTC)
    event = _event(late, "PUBLIC SAFETY COMMITTEE MEETING, November 17, 2026", ends=datetime(2026, 11, 18, 3, 0, tzinfo=UTC))

    entry = _by_uid(_entries())[f"calendar-{event}@docket.pub"]

    assert entry.on == NOV_17
    assert entry.starts_at == late
    assert (entry.starts_at.hour, entry.starts_at.utcoffset()) == (20, timedelta(hours=-6))
    assert (entry.ends_at.hour, entry.ends_at.utcoffset()) == (21, timedelta(hours=-6))
    # On the window's last evening it is inside by Chicago's day, though past it by UTC's.
    assert f"calendar-{event}@docket.pub" in _by_uid(_entries(NOV_17 - timedelta(days=60)))
    assert f"calendar-{event}@docket.pub" not in _by_uid(_entries(NOV_17 - timedelta(days=61)))
    # And on November 18 it is past, though by UTC's day it would be today.
    assert f"calendar-{event}@docket.pub" not in _by_uid(_entries(date(2026, 11, 18)))


def test_an_event_of_another_city_is_not_listed():
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO city_calendar_events (municipality_id, source_event_id, title, starts_at, source_url)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (_city_row("mobile")["id"], PREFIX + "mobile", COUNCIL_EVENT, _at(NOV_17, 9, 30), "https://example.org/e"),
        )
        event = cur.fetchone()["id"]
    row = _upcoming_row(NOV_17, city="mobile")

    found = _by_uid(_entries())

    assert f"calendar-{event}@docket.pub" not in found
    assert f"meeting-{row}@docket.pub" not in found


# --- meetings: cancelled, and shown -----------------------------------------


def test_a_pair_whose_event_is_cancelled_names_the_calendar_and_says_the_video_site_still_lists_it():
    event = _event(_at(NOV_17, 9, 30), status="cancelled")
    row = _upcoming_row(NOV_17, event_id=event)

    entries = [e for e in _entries() if e.uid in (f"calendar-{event}@docket.pub", f"meeting-{row}@docket.pub")]

    assert len(entries) == 1
    entry = entries[0]
    assert entry.cancelled is True
    assert entry.cancelled_by == ("the city calendar",)
    assert entry.detail == ("Cancelled, according to the city calendar.", "The council's video site still lists it.")
    # Nothing else about it changes.
    assert entry.title == "City Council meeting"
    assert entry.starts_at == _at(NOV_17, 9, 30)
    assert len(entry.links) == 3


def test_a_pair_whose_row_says_cancelled_names_the_video_site_and_says_the_calendar_still_lists_it():
    event = _event(_at(NOV_17, 9, 30), status="active")
    row = _upcoming_row(NOV_17, title="Regular City Council Meeting - CANCELLED", event_id=event)

    entries = [e for e in _entries() if e.uid in (f"calendar-{event}@docket.pub", f"meeting-{row}@docket.pub")]

    assert len(entries) == 1
    entry = entries[0]
    assert entry.cancelled is True
    assert entry.cancelled_by == ("the council's video site",)
    assert entry.detail == ("Cancelled, according to the council's video site.", "The city calendar still lists it.")
    assert entry.title == "City Council meeting"


def test_a_pair_both_of_whose_sources_say_cancelled_names_both_and_adds_no_second_sentence():
    event = _event(_at(NOV_17, 9, 30), status="cancelled")
    _upcoming_row(NOV_17, title="Regular City Council Meeting - CANCELLED", event_id=event)

    entry = _by_uid(_entries())[f"calendar-{event}@docket.pub"]

    assert entry.cancelled is True
    assert entry.cancelled_by == ("the council's video site", "the city calendar")
    assert entry.detail == ("Cancelled, according to the council's video site and the city calendar.",)


def test_an_event_alone_marked_postponed_is_quoted_not_called_cancelled():
    event = _event(_at(NOV_23, 15, 30), COMMITTEE_EVENT, status="postponed")

    entry = _by_uid(_entries())[f"calendar-{event}@docket.pub"]

    assert entry.cancelled is True
    assert entry.cancelled_by == ("the city calendar",)
    assert entry.detail == ('The city calendar marks this "postponed".',)


def test_the_calendars_status_is_quoted_as_stored():
    event = _event(_at(NOV_23, 15, 30), COMMITTEE_EVENT, status="Rescheduled")

    assert _by_uid(_entries())[f"calendar-{event}@docket.pub"].detail == ('The city calendar marks this "Rescheduled".',)


@pytest.mark.parametrize("status", ["cancelled", "canceled", "Cancelled", "CANCELED"])
def test_an_event_alone_whose_status_is_the_word_cancelled_in_either_spelling(status):
    event = _event(_at(NOV_23, 15, 30), COMMITTEE_EVENT, status=status)

    entry = _by_uid(_entries())[f"calendar-{event}@docket.pub"]

    assert entry.cancelled is True
    assert entry.detail == ("Cancelled, according to the city calendar.",)


def test_an_event_alone_whose_title_says_cancelled_though_its_status_is_active():
    event = _event(_at(NOV_23, 15, 30), "CANCELLED: " + COMMITTEE_EVENT, status="active")

    entry = _by_uid(_entries())[f"calendar-{event}@docket.pub"]

    assert entry.cancelled is True
    assert entry.cancelled_by == ("the city calendar",)
    assert entry.detail == ("Cancelled, according to the city calendar.",)


def test_an_event_whose_title_says_cancelled_and_whose_status_is_another_word_is_called_cancelled():
    event = _event(_at(NOV_23, 15, 30), "CANCELLED: " + COMMITTEE_EVENT, status="postponed")

    assert _by_uid(_entries())[f"calendar-{event}@docket.pub"].detail == ("Cancelled, according to the city calendar.",)


def test_a_postponed_event_paired_with_a_live_row_is_quoted_and_the_video_site_still_lists_it():
    event = _event(_at(NOV_17, 9, 30), status="postponed")
    _upcoming_row(NOV_17, event_id=event)

    entry = _by_uid(_entries())[f"calendar-{event}@docket.pub"]

    assert entry.cancelled_by == ("the city calendar",)
    assert entry.detail == ('The city calendar marks this "postponed".', "The council's video site still lists it.")


def test_a_postponed_event_paired_with_a_row_that_says_cancelled_is_called_cancelled_by_both():
    """The exception is for when neither title says cancelled; here the row's does."""
    event = _event(_at(NOV_17, 9, 30), status="postponed")
    _upcoming_row(NOV_17, title="Regular City Council Meeting (Canceled)", event_id=event)

    entry = _by_uid(_entries())[f"calendar-{event}@docket.pub"]

    assert entry.cancelled_by == ("the council's video site", "the city calendar")
    assert entry.detail == ("Cancelled, according to the council's video site and the city calendar.",)


def test_a_row_alone_that_says_cancelled_is_kept_and_marked_with_one_sentence():
    row = _upcoming_row(NOV_24, title="Regular City Council Meeting - CANCELLED")

    entry = _by_uid(_entries())[f"meeting-{row}@docket.pub"]

    assert entry.cancelled is True
    assert entry.cancelled_by == ("the council's video site",)
    assert entry.detail == ("Cancelled, according to the council's video site.",)
    assert entry.title == "City Council meeting"


def test_a_hidden_row_is_absent_and_its_calendar_event_stands_alone():
    event = _event(_at(NOV_17, 9, 30))
    row = _upcoming_row(NOV_17, event_id=event, hidden=True)

    found = _by_uid(_entries())

    assert f"meeting-{row}@docket.pub" not in found
    assert found[f"calendar-{event}@docket.pub"].links == (("City calendar", _source_url(event)),)


def test_a_hidden_row_that_says_cancelled_is_still_absent():
    row = _upcoming_row(NOV_24, title="Regular City Council Meeting - CANCELLED", hidden=True)

    assert f"meeting-{row}@docket.pub" not in _by_uid(_entries())


# --- the window -------------------------------------------------------------


def test_a_row_sixty_days_ahead_is_listed_and_one_sixty_one_days_ahead_is_not():
    last = _upcoming_row(TODAY + timedelta(days=60))
    past_it = _upcoming_row(TODAY + timedelta(days=61))
    today = _upcoming_row(TODAY)
    yesterday = _upcoming_row(TODAY - timedelta(days=1))

    found = _by_uid(_entries())

    assert f"meeting-{last}@docket.pub" in found
    assert f"meeting-{past_it}@docket.pub" not in found
    assert f"meeting-{today}@docket.pub" in found
    assert f"meeting-{yesterday}@docket.pub" not in found


def test_an_event_is_listed_from_today_through_sixty_days_ahead():
    def committee(day: date) -> int:
        return _event(_at(day, 15, 30), f"PUBLIC SAFETY COMMITTEE MEETING, {day:%B} {day.day}, {day.year}")

    last, past_it = committee(TODAY + timedelta(days=60)), committee(TODAY + timedelta(days=61))
    today, yesterday = committee(TODAY), committee(TODAY - timedelta(days=1))

    found = _by_uid(_entries())

    assert f"calendar-{last}@docket.pub" in found
    assert f"calendar-{past_it}@docket.pub" not in found
    assert f"calendar-{today}@docket.pub" in found
    assert f"calendar-{yesterday}@docket.pub" not in found


def test_a_hearing_dated_today_is_listed_and_one_dated_yesterday_is_not():
    hearing, _ = _hearing(TITLES[63046])  # November 24, 2026

    assert f"hearing-{hearing}@docket.pub" in _by_uid(_entries(NOV_24))
    assert f"hearing-{hearing}@docket.pub" not in _by_uid(_entries(date(2026, 11, 25)))
    assert f"hearing-{hearing}@docket.pub" in _by_uid(_entries(NOV_24 - timedelta(days=60)))
    assert f"hearing-{hearing}@docket.pub" not in _by_uid(_entries(NOV_24 - timedelta(days=61)))


def test_neighborhood_meetings_are_listed_from_today_through_sixty_days_ahead():
    """Acipco-Finley meets on the first Wednesday: November 4 and December 2, 2026."""
    def acipco(today: date) -> list[date]:
        return [e.on for e in _entries(today) if e.association == "acipco-finley"]

    assert acipco(TODAY) == [date(2026, 12, 2)]
    assert acipco(date(2026, 11, 4)) == [date(2026, 11, 4), date(2026, 12, 2)]
    assert acipco(date(2026, 11, 5)) == [date(2026, 12, 2)]
    assert acipco(date(2026, 10, 3)) == [date(2026, 10, 7), date(2026, 11, 4), date(2026, 12, 2)]
    assert acipco(date(2026, 10, 2)) == [date(2026, 10, 7), date(2026, 11, 4)]


def test_in_2027_there_is_no_neighborhood_entry():
    assert [e for e in _entries(date(2027, 1, 5)) if e.kind == "neighborhood"] == []


def test_the_default_day_is_the_modules_today(monkeypatch):
    from docket.services import coming_up

    row = _upcoming_row(NOV_24)
    monkeypatch.setattr(coming_up, "_today", lambda: NOV_24)
    assert f"meeting-{row}@docket.pub" in _by_uid(coming_up.list_entries(_city_row()))
    monkeypatch.setattr(coming_up, "_today", lambda: date(2026, 11, 25))
    assert f"meeting-{row}@docket.pub" not in _by_uid(coming_up.list_entries(_city_row()))


def test_today_is_chicagos_day(monkeypatch):
    """03:00 UTC on November 17 is still November 16 in Chicago."""
    from docket.services import coming_up

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 17, 3, 0, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(coming_up, "datetime", Clock)
    assert coming_up._today() == TODAY


# --- hearings ---------------------------------------------------------------


def test_a_zoning_hearing_entry():
    hearing, item = _hearing(TITLES[63046])

    entry = _by_uid(_entries())[f"hearing-{hearing}@docket.pub"]

    assert entry.kind == "hearing"
    assert entry.on == NOV_24
    assert entry.starts_at is None and entry.ends_at is None
    assert entry.title == "Zoning hearing"
    assert (entry.badge, entry.badge_label) == ("zoning", "Zoning")
    assert entry.links == (
        ("City agenda", AGENDA),
        ("On the agenda of October 13, 2026", f"/al/birmingham/items/{item}/"),
    )
    assert entry.source_url == AGENDA
    assert entry.place is None
    assert entry.attend == ()
    assert entry.association is None
    assert entry.cancelled is False and entry.cancelled_by == ()


def test_a_hearings_subject_is_cut_at_a_word_with_an_ellipsis():
    hearing, _ = _hearing(TITLES[63046])

    (line,) = _by_uid(_entries())[f"hearing-{hearing}@docket.pub"].detail

    assert line.startswith("to consider the adoption of an Ordinance “TO AMEND THE ZONING DISTRICT MAP")
    assert line.endswith("…")
    body = line[:-1]
    assert len(body) <= 240
    assert body == body.rstrip()
    # Cut between words: the stored subject goes on with a space and the next word.
    with db_cursor() as cur:
        cur.execute("SELECT subject FROM public_hearings WHERE id = %s", (hearing,))
        subject = cur.fetchone()["subject"]
    assert subject.startswith(body + " ")
    # And no earlier than it had to be: the next word would not have fitted.
    assert len(body + " " + subject[len(body) + 1 :].split(" ")[0]) > 240


def test_clip_keeps_a_short_text_and_cuts_a_long_one_at_a_word():
    from docket.services import coming_up

    assert coming_up._clip("a b c", 240) == "a b c"
    assert coming_up._clip("x" * 240, 240) == "x" * 240
    assert coming_up._clip("x" * 241, 240) == "x" * 240 + "…"
    # A word that ends exactly at the limit is kept whole.
    assert coming_up._clip("aaaa bbbbb cc", 10) == "aaaa bbbbb…"
    assert coming_up._clip("aaaa bbbbbb cc", 10) == "aaaa…"
    assert coming_up._clip("aaaa  bbbbbbb", 10) == "aaaa…"


def test_a_short_subject_is_printed_whole():
    hearing, _ = _hearing(
        "A Resolution setting a public hearing November 24, 2026, to consider a moratorium on new billboards."
    )

    entry = _by_uid(_entries())[f"hearing-{hearing}@docket.pub"]

    assert entry.detail == ("to consider a moratorium on new billboards.",)
    assert entry.title == "Public hearing"
    assert (entry.badge, entry.badge_label) == ("hearing", "Hearing")


def test_a_weed_lot_hearing_says_how_many_properties_and_not_its_subject():
    hearing, _ = _hearing(TITLES[62882])

    entry = _by_uid(_entries())[f"hearing-{hearing}@docket.pub"]

    assert entry.title == "Weed lots hearing"
    assert entry.detail == ("212 properties",)
    assert (entry.badge, entry.badge_label) == ("weed-lots", "Weed lots")


def test_a_weed_lot_hearing_with_no_count_has_no_detail():
    hearing, _ = _hearing(
        "A Resolution finding that certain properties have noxious or dangerous weeds growing thereon and "
        "further providing for a public hearing November 24, 2026, to hear and consider all objections."
    )

    entry = _by_uid(_entries())[f"hearing-{hearing}@docket.pub"]

    assert entry.title == "Weed lots hearing"
    assert entry.detail == ()


def test_a_vacation_hearing_and_a_budget_hearing_are_titled_and_labelled_by_kind():
    vacation, _ = _hearing(TITLES[62182])
    budget, _ = _hearing(
        "A Resolution setting a public hearing November 24, 2026, to consider the Mayor's proposed budget."
    )

    found = _by_uid(_entries())

    assert found[f"hearing-{vacation}@docket.pub"].title == "Street or right-of-way hearing"
    assert found[f"hearing-{vacation}@docket.pub"].badge == "vacation"
    assert found[f"hearing-{vacation}@docket.pub"].badge_label == "Street or right-of-way"
    assert found[f"hearing-{budget}@docket.pub"].title == "Budget hearing"
    assert (found[f"hearing-{budget}@docket.pub"].badge, found[f"hearing-{budget}@docket.pub"].badge_label) == (
        "budget",
        "Budget",
    )


def test_a_hearing_set_on_two_agendas_links_both_and_the_newer_agenda_first():
    older_agenda = "https://bhamal.granicus.com/AgendaViewer.php?view_id=2&clip_id=1"
    newer_agenda = "https://bhamal.granicus.com/AgendaViewer.php?view_id=2&clip_id=2"
    first = _item(_held_meeting(OCT_13, agenda_url=older_agenda), TITLES[62830])
    second = _item(_held_meeting(OCT_26, agenda_url=newer_agenda), TITLES[62830])
    _store_hearings()
    hearing = _hearing_of(first)
    assert _hearing_of(second) == hearing

    entry = _by_uid(_entries())[f"hearing-{hearing}@docket.pub"]

    assert entry.links == (
        ("City agenda", newer_agenda),
        ("On the agenda of October 13, 2026", f"/al/birmingham/items/{first}/"),
        ("On the agenda of October 26, 2026", f"/al/birmingham/items/{second}/"),
    )
    assert entry.source_url == newer_agenda


def test_the_city_agenda_is_the_newest_that_has_one():
    older_agenda = "https://bhamal.granicus.com/AgendaViewer.php?view_id=2&clip_id=1"
    first = _item(_held_meeting(OCT_13, agenda_url=older_agenda), TITLES[62830])
    second = _item(_held_meeting(OCT_26, agenda_url=None), TITLES[62830])
    _store_hearings()

    entry = _by_uid(_entries())[f"hearing-{_hearing_of(first)}@docket.pub"]

    assert entry.links[0] == ("City agenda", older_agenda)
    assert len(entry.links) == 3
    assert second


def test_a_hearing_whose_meetings_have_no_agenda_address_has_item_links_alone_and_no_source():
    hearing, item = _hearing(TITLES[63046], agenda_url=None)

    entry = _by_uid(_entries())[f"hearing-{hearing}@docket.pub"]

    assert entry.links == (("On the agenda of October 13, 2026", f"/al/birmingham/items/{item}/"),)
    assert entry.source_url is None


# --- neighborhood meetings --------------------------------------------------


def test_a_neighborhood_entry_carries_the_schedule_and_what_it_gives():
    """Acipco-Finley: first Wednesday at 5:30 p.m., in person, a place and no call-in."""
    (entry,) = [e for e in _entries() if e.association == "acipco-finley"]

    assert entry.kind == "neighborhood"
    assert entry.uid == "na-acipco-finley-20261202@docket.pub"
    assert entry.on == date(2026, 12, 2)
    assert entry.starts_at == _at(date(2026, 12, 2), 17, 30)
    assert entry.starts_at.utcoffset() == timedelta(hours=-6)
    assert entry.ends_at is None
    assert entry.title == "Acipco-Finley Neighborhood Association"
    assert entry.detail == ("In-Person",)
    assert entry.links == (("City schedule (PDF)", PDF),)
    assert entry.source_url == PDF
    assert entry.place == "Acipco Finley Community Room, 453 38th Ave W, Birmingham, AL 35207"
    assert entry.attend == (("Where", "Acipco Finley Community Room, 453 38th Ave W, Birmingham, AL 35207"),)
    assert (entry.badge, entry.badge_label) == ("neighborhood", "Neighborhood")
    assert entry.cancelled is False and entry.cancelled_by == ()


def test_a_neighborhood_meeting_in_summer_is_on_daylight_time(monkeypatch):
    _use_schedule(monkeypatch, _association("Acipco-Finley"))

    (entry,) = _entries(date(2026, 7, 1))[:1]

    assert entry.on == date(2026, 7, 1)
    assert (entry.starts_at.hour, entry.starts_at.minute) == (17, 30)
    assert entry.starts_at.utcoffset() == timedelta(hours=-5)


def test_gate_city_says_call_in_details_are_not_in_the_schedule():
    (entry,) = [e for e in _entries() if e.association == "gate-city"]

    assert entry.on == date(2026, 12, 14)
    assert entry.detail == ("Teleconfernce / In-Person", "Call-in details are not in the schedule")
    assert [label for label, _ in entry.attend] == ["Where"]


def test_the_first_association_with_call_in_details_has_them_under_attend_and_not_in_detail():
    from docket.services import coming_up, neighborhood_schedule

    schedule = neighborhood_schedule.get_schedule("birmingham")
    association = next((a for a in schedule.associations if a.remote is not None and a.ordinal is not None), None)
    assert association is not None, "no dated association of the schedule has call-in details"

    entries = [e for e in _entries() if e.association == coming_up.association_slug(association.name)]

    assert entries
    for entry in entries:
        assert ("Call-in", association.remote) in entry.attend
        assert association.remote not in entry.detail
        assert "Call-in details are not in the schedule" not in entry.detail


def test_attend_holds_where_then_call_in_when_the_schedule_gives_both(monkeypatch):
    _use_schedule(monkeypatch, _association("Acipco-Finley", place="The hall", remote="Dial: 555 0100", modes=("in_person", "phone")))

    (entry,) = _entries()

    assert entry.attend == (("Where", "The hall"), ("Call-in", "Dial: 555 0100"))
    assert entry.place == "The hall"
    assert entry.detail == ("In-Person",)


def test_an_association_with_call_in_details_alone_has_no_place(monkeypatch):
    _use_schedule(monkeypatch, _association("Acipco-Finley", place=None, remote="Dial: 555 0100", modes=("phone",)))

    (entry,) = _entries()

    assert entry.attend == (("Call-in", "Dial: 555 0100"),)
    assert entry.place is None


def test_an_association_with_neither_place_nor_call_in_has_an_empty_attend(monkeypatch):
    _use_schedule(monkeypatch, _association("Acipco-Finley", place=None, remote=None))

    (entry,) = _entries()

    assert entry.attend == ()
    assert entry.detail == ("In-Person",)


@pytest.mark.parametrize("modes", [("phone",), ("video",), ("in_person", "video")])
def test_a_call_or_video_meeting_with_no_details_says_so(monkeypatch, modes):
    _use_schedule(monkeypatch, _association("Acipco-Finley", remote=None, modes=modes))

    (entry,) = _entries()

    assert entry.detail == ("In-Person", "Call-in details are not in the schedule")


def test_an_association_with_no_time_says_so_and_has_no_start(monkeypatch):
    _use_schedule(monkeypatch, _association("Acipco-Finley", time=None, remote=None, modes=("phone",)))

    (entry,) = _entries()

    assert entry.starts_at is None
    assert entry.detail == ("In-Person", "Call-in details are not in the schedule", "The schedule gives no time")


def test_a_city_with_no_schedule_has_no_neighborhood_entry(monkeypatch):
    from docket.services import neighborhood_schedule

    monkeypatch.setattr(neighborhood_schedule, "get_schedule", lambda slug: None)

    assert [e for e in _entries() if e.kind == "neighborhood"] == []


def test_the_schedule_asked_for_is_the_citys(monkeypatch):
    from docket.services import coming_up, neighborhood_schedule

    asked = []

    def get_schedule(slug):
        asked.append(slug)
        return None

    monkeypatch.setattr(neighborhood_schedule, "get_schedule", get_schedule)
    coming_up.list_entries(_city_row("mobile"), today=TODAY)
    coming_up.undated_associations("mobile")
    coming_up.schedule_source("mobile")
    coming_up.association_feeds("mobile")

    assert asked == ["mobile"] * 4


# --- the list: order, labels, filters ---------------------------------------


def test_entries_are_ordered_by_day_then_timed_by_start_then_kind_then_title(monkeypatch):
    _use_schedule(
        monkeypatch,
        _association("Brown Springs", time="09:30"),  # third Thursday: November 19
        _association("Acipco-Finley", ordinal="third", weekday="thursday", time=None),
    )
    hearing, _ = _hearing(
        "A Resolution setting a public hearing November 19, 2026, to consider a moratorium on new billboards."
    )
    nov_19 = date(2026, 11, 19)
    afternoon = _event(_at(nov_19, 15, 30), "PUBLIC SAFETY COMMITTEE MEETING, November 19, 2026")
    morning = _event(_at(nov_19, 9, 30), "BUDGET AND FINANCE COMMITTEE MEETING, November 19, 2026")
    untimed_b = _upcoming_row(nov_19, title="B", meeting_type="other", start=None)
    untimed_a = _upcoming_row(nov_19, title="A", meeting_type="other", start=None)
    day_before = _upcoming_row(date(2026, 11, 18), start=time(18, 0))

    ours = {
        f"meeting-{day_before}@docket.pub",
        f"calendar-{morning}@docket.pub",
        "na-brown-springs-20261119@docket.pub",
        f"calendar-{afternoon}@docket.pub",
        f"meeting-{untimed_a}@docket.pub",
        f"meeting-{untimed_b}@docket.pub",
        f"hearing-{hearing}@docket.pub",
        "na-acipco-finley-20261119@docket.pub",
    }
    order = [e.uid for e in _entries() if e.uid in ours]

    assert order == [
        f"meeting-{day_before}@docket.pub",  # the day before, though later in its day
        f"calendar-{morning}@docket.pub",  # 9:30, a meeting before a neighborhood meeting of the same minute
        "na-brown-springs-20261119@docket.pub",
        f"calendar-{afternoon}@docket.pub",
        f"meeting-{untimed_a}@docket.pub",  # untimed: meetings by title,
        f"meeting-{untimed_b}@docket.pub",
        f"hearing-{hearing}@docket.pub",  # then the hearing,
        "na-acipco-finley-20261119@docket.pub",  # then the neighborhood meeting
    ]


def test_every_entry_carries_one_of_the_seven_labels():
    _event(_at(NOV_17, 9, 30))
    _hearing(TITLES[63046])
    _hearing(TITLES[62882])

    entries = _entries()

    assert {e.kind for e in entries} == {"meeting", "hearing", "neighborhood"}
    assert {e.badge for e in entries} <= BADGES
    assert all(e.badge_label for e in entries)
    assert {e.attend for e in entries if e.kind != "neighborhood"} == {()}
    assert {e.association for e in entries if e.kind != "neighborhood"} == {None}
    assert all(e.association for e in entries if e.kind == "neighborhood")
    assert not any(e.cancelled for e in entries if e.kind != "meeting")


def test_filter_entries_by_kind_by_association_by_both_and_by_neither():
    from docket.services import coming_up

    _event(_at(NOV_17, 9, 30))
    _hearing(TITLES[63046])
    _hearing(TITLES[62882])
    entries = _entries()

    only_hearings = coming_up.filter_entries(entries, kind="hearing")
    assert only_hearings and {e.kind for e in only_hearings} == {"hearing"}
    assert only_hearings == [e for e in entries if e.kind == "hearing"]

    acipco = coming_up.filter_entries(entries, association="acipco-finley")
    assert [e.uid for e in acipco] == ["na-acipco-finley-20261202@docket.pub"]

    assert coming_up.filter_entries(entries, kind="meeting", association="acipco-finley") == []
    assert coming_up.filter_entries(entries, kind="neighborhood", association="acipco-finley") == acipco
    assert coming_up.filter_entries(entries) == entries
    assert coming_up.filter_entries(entries) is not entries


def test_association_feeds_names_every_dated_association_once():
    from docket.services import coming_up, neighborhood_schedule

    feeds = coming_up.association_feeds("birmingham")
    schedule = neighborhood_schedule.get_schedule("birmingham")

    assert len(feeds) == 97
    assert len(feeds) == len([a for a in schedule.associations if a.ordinal is not None])
    assert len({slug for _, slug in feeds}) == 97
    assert ("Acipco-Finley", "acipco-finley") in feeds
    assert ("Forest Park/South Avondale", "forest-park-south-avondale") in feeds
    names = [name for name, _ in feeds]
    assert names == sorted(names)
    assert "Bridlewood" not in names and "Glen Iris" not in names
    assert coming_up.association_feeds("mobile") == []


def test_association_feeds_are_in_name_order_whatever_the_files_order(monkeypatch):
    from docket.services import coming_up

    _use_schedule(monkeypatch, _association("Huffman"), _association("Glen Iris"), _association("Acipco-Finley"))

    assert coming_up.association_feeds("birmingham") == [("Acipco-Finley", "acipco-finley"), ("Huffman", "huffman")]


def test_every_association_slug_is_the_one_its_entries_carry():
    from docket.services import coming_up

    slugs = {slug for _, slug in coming_up.association_feeds("birmingham")}

    assert {e.association for e in _entries() if e.kind == "neighborhood"} <= slugs


def test_undated_associations_and_the_schedules_source():
    from docket.services import coming_up

    assert coming_up.undated_associations("birmingham") == [
        ("Bridlewood", "The schedule says: No Meetings"),
        ("Glen Iris", "The schedule says: First Monday of this month @ 6:30 pm"),
    ]
    assert coming_up.undated_associations("mobile") == []
    assert coming_up.schedule_source("birmingham") == {
        "title": "City of Birmingham Community Resource Services Division Neighborhood Association Meeting Schedule",
        "url": PDF,
        "revised": date(2026, 2, 3),
        "year": 2026,
    }
    assert coming_up.schedule_source("mobile") is None


def test_the_service_reads_no_server_clock_and_imports_nothing_from_the_web():
    from docket.services import coming_up

    source = Path(coming_up.__file__).read_text()

    assert "NOW()" not in source.upper().replace(" ", "")
    assert "CURRENT_DATE" not in source.upper()
    assert "CURRENT_TIMESTAMP" not in source.upper()
    assert "docket.web" not in source
    assert "docket.worker" not in source
