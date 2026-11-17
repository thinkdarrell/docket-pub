"""Rows for the coming-up tests: meetings, calendar events, and stored hearings under Birmingham.

Every meeting's title begins ``COMINGUP_TEST_`` and every calendar event's
``source_event_id`` begins the same; ``delete_seeded`` removes them and the
hearings their items were linked to, and a test file calls it before and
after each test. A hearing is seeded the way production makes one: an item
whose title is a fixture title, then ``hearings.refresh_hearings``. The
service's names are imported inside each function, so a test file that
imports this module collects whatever exists.

Shared by ``tests/services/test_coming_up.py`` and
``tests/web/test_coming_up_page.py`` (plan `birmingham-coming-up`, M6 and M7).
"""

from __future__ import annotations

import itertools
import json
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from docket.db import db_cursor

FIXTURE = Path(__file__).parent.parent / "fixtures" / "hearings" / "birmingham_titles.json"
TITLES = {row["id"]: row["title"] for row in json.loads(FIXTURE.read_text())}
PREFIX = "COMINGUP_TEST_"
CHICAGO = ZoneInfo("America/Chicago")

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

_serial = itertools.count(1)


def city_row(slug: str = "birmingham") -> dict:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM municipalities WHERE slug = %s", (slug,))
        return dict(cur.fetchone())


def delete_seeded() -> None:
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


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=CHICAGO)


def upcoming_row(
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
                city_row(city)["id"],
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


def event(
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
            (city_row()["id"], f"{PREFIX}{n}", title, starts, ends, event_url(n), status),
        )
        return cur.fetchone()["id"]


def event_url(n: int) -> str:
    return f"https://www.birminghamal.gov/events/comingup-test-{n}"


def source_url(event_id: int) -> str:
    with db_cursor() as cur:
        cur.execute("SELECT source_url FROM city_calendar_events WHERE id = %s", (event_id,))
        return cur.fetchone()["source_url"]


def held_meeting(day: date = OCT_13, *, agenda_url: str | None = AGENDA) -> int:
    """A recorded meeting, whose agenda holds the items that set hearings. Not an `event-` row."""
    n = next(_serial)
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type, agenda_url)
               VALUES (%s, %s, %s, %s, 'council', %s) RETURNING id""",
            (city_row()["id"], f"comingup-test-{n}", PREFIX + "Regular meeting", day, agenda_url),
        )
        return cur.fetchone()["id"]


def item(meeting_id: int, title: str) -> int:
    n = next(_serial)
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO agenda_items (meeting_id, external_id, title, processing_status)
               VALUES (%s, %s, %s, 'completed') RETURNING id""",
            (meeting_id, f"comingup-test-item-{n}", title),
        )
        return cur.fetchone()["id"]


def store_hearings() -> None:
    from docket.services import hearings

    hearings.refresh_hearings(city_row()["id"], SINCE)


def hearing_of(item_id: int) -> int:
    with db_cursor() as cur:
        cur.execute("SELECT hearing_id FROM public_hearing_items WHERE agenda_item_id = %s", (item_id,))
        return cur.fetchone()["hearing_id"]


def hearing(title: str, day: date = OCT_13, *, agenda_url: str | None = AGENDA) -> tuple[int, int]:
    """One item setting one hearing, stored. Returns the hearing's id and the item's."""
    item_id = item(held_meeting(day, agenda_url=agenda_url), title)
    store_hearings()
    return hearing_of(item_id), item_id


def entries(today: date = TODAY, slug: str = "birmingham"):
    from docket.services import coming_up

    return coming_up.list_entries(city_row(slug), today=today)


def association(name: str, **changes):
    """An association of the checked-in schedule, with fields replaced."""
    from dataclasses import replace

    from docket.services import neighborhood_schedule

    schedule = neighborhood_schedule.get_schedule("birmingham")
    found = next(a for a in schedule.associations if a.name == name)
    return replace(found, **changes)


def use_schedule(monkeypatch, *associations):
    """Make the service see a schedule of just these associations (the source block is the real one)."""
    from dataclasses import replace

    from docket.services import neighborhood_schedule

    real = neighborhood_schedule.get_schedule("birmingham")
    made = replace(real, associations=tuple(associations))
    monkeypatch.setattr(neighborhood_schedule, "get_schedule", lambda slug: made if slug == "birmingham" else None)
    return made
