"""What is coming up in a city: meetings, scheduled hearings, neighborhood meetings.

`list_entries` returns one list, in date order, of everything a flagged city
has ahead of it in the window (today through `WINDOW_DAYS` days ahead, both
in America/Chicago), in three kinds:

- `meeting`: the council meetings the video site lists as upcoming (the
  `event-` rows of `meetings`) and the council and committee meetings on the
  city's calendar (`city_calendar_events`), a meeting both sources list
  appearing once. A meeting either source calls cancelled is kept, marked,
  with the source that says so named: both things the city published are
  shown and nothing here rules between them.
- `hearing`: the stored hearings of `docket.services.hearings`.
- `neighborhood`: the dated meetings `docket.services.neighborhood_schedule`
  computes from the city's published schedule.

An entry carries the city document it came from where a stored row gives
its address; `source_url` is None where none does, and the page says so
under that entry. A value the source does
not give (a time, a place, call-in details) is absent, never filled in
(`docs/PRINCIPLES.md`, "Source or silence").

The page and the calendar feed are both built from one call of
`list_entries`, so they cannot differ. Every bound is computed from one
`today` and passed as a parameter; no statement here reads the server's
clock.

Plan `birmingham-coming-up`, M6, whose Decision Log says why each rule is
what it is.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from docket.adapters._helpers import MEETING_TYPES, label_for
from docket.db import db_cursor
from docket.enrichment.hearings import KIND_LABELS, KIND_TITLES
from docket.services import hearings, meeting_types, neighborhood_schedule
from docket.services.query import is_cancelled_title

WINDOW_DAYS = 60

# The kinds of entry, in the order they are listed within one day, and the
# vocabulary a feed's `?kind=` is checked against.
KINDS = ("meeting", "hearing", "neighborhood")

_CHICAGO = ZoneInfo("America/Chicago")

# How each of the two meeting sources is named to a reader.
_VIDEO_SITE = "the council's video site"
_CALENDAR = "the city calendar"

# A stored calendar status that is the word for cancelled. Any other status
# that is not `active` is quoted to the reader as the city wrote it.
_CANCELLED_WORDS = ("cancelled", "canceled")

_SUBJECT_MAX = 240


@dataclass(frozen=True)
class Entry:
    """One thing on the page: a meeting, a hearing, or one dated neighborhood meeting.

    `links` are `(label, url)` pairs; a city document's url is its full
    address and a docket.pub page's is a site path beginning `/`.
    `source_url` is the first city document among them, or None.
    `starts_at` and `ends_at` are in America/Chicago, or None where the
    source gives no time.
    """

    kind: str
    uid: str
    on: date
    starts_at: datetime | None
    ends_at: datetime | None
    title: str
    detail: tuple[str, ...]
    links: tuple[tuple[str, str], ...]
    source_url: str | None
    place: str | None
    badge: str
    badge_label: str
    cancelled: bool
    cancelled_by: tuple[str, ...]
    attend: tuple[tuple[str, str], ...]
    association: str | None


def _today() -> date:
    return datetime.now(_CHICAGO).date()


def is_coming_up_city(municipality: dict | None) -> bool:
    """True when the municipality row's metadata carries ``"coming_up": true``."""
    if not municipality:
        return False
    meta = municipality.get("metadata")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            return False
    return isinstance(meta, dict) and meta.get("coming_up") is True


def association_slug(name: str) -> str:
    """The name in lower case, each run of anything but a to z and 0 to 9 one hyphen, none at either end."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _long_date(day: date) -> str:
    return f"{day:%B} {day.day}, {day.year}"


def _clip(text: str, limit: int) -> str:
    """`text`, or its first `limit` characters cut back to the end of a word, with an ellipsis."""
    if len(text) <= limit:
        return text
    head = text[: limit + 1]
    if " " in head:
        head = head.rsplit(" ", 1)[0]
    else:
        head = text[:limit]
    return head.rstrip() + "…"


# --- meetings ---------------------------------------------------------------


def _granicus_rows(municipality_id: int, start: date, end: date) -> list[dict]:
    """The city's visible meetings the video site lists and has not recorded, dated in the window."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT id, title, meeting_date, start_time, agenda_url,
                      meeting_type, session_kind, body_name, calendar_event_id
                 FROM meetings
                WHERE municipality_id = %s
                  AND external_id LIKE 'event-%%'
                  AND is_hidden = FALSE
                  AND meeting_date >= %s
                  AND meeting_date <= %s
                ORDER BY id""",
            (municipality_id, start, end),
        )
        return [dict(r) for r in cur.fetchall()]


def _calendar_events(municipality_id: int, start: date, end: date) -> list[dict]:
    """The city's calendar events that are meetings and start, by Chicago's clock, on a day in the window.

    Each carries `classification` (what `classify_event` read from its
    title; an event it reads nothing from is not a meeting and is left
    out) and `on`, its Chicago date.
    """
    with db_cursor() as cur:
        cur.execute(
            """SELECT id, title, starts_at, ends_at, source_url, event_status
                 FROM city_calendar_events
                WHERE municipality_id = %s
                  AND (starts_at AT TIME ZONE 'America/Chicago')::date >= %s
                  AND (starts_at AT TIME ZONE 'America/Chicago')::date <= %s
                ORDER BY id""",
            (municipality_id, start, end),
        )
        rows = [dict(r) for r in cur.fetchall()]
    events = []
    for event in rows:
        classification = meeting_types.classify_event(event["title"])
        if classification is None:
            continue
        event["classification"] = classification
        event["starts_at"] = event["starts_at"].astimezone(_CHICAGO)
        if event["ends_at"] is not None:
            event["ends_at"] = event["ends_at"].astimezone(_CHICAGO)
        event["on"] = event["starts_at"].date()
        events.append(event)
    return events


def _pair(rows: list[dict], events: list[dict]) -> list[tuple[dict | None, dict | None]]:
    """Which video-site row and which calendar event are one meeting. Pure.

    First a row and the event its `calendar_event_id` names. Then, among
    what is left, a council row and a council event of one day, when each
    is the only such one that day. Everything else stands alone.
    """
    by_id = {event["id"]: event for event in events}
    paired_rows: set[int] = set()
    paired_events: set[int] = set()
    out: list[tuple[dict | None, dict | None]] = []

    for row in rows:
        event = by_id.get(row["calendar_event_id"])
        if event is not None and event["id"] not in paired_events:
            out.append((row, event))
            paired_rows.add(row["id"])
            paired_events.add(event["id"])

    days: dict[date, tuple[list[dict], list[dict]]] = {}
    for row in rows:
        if row["id"] not in paired_rows and row["meeting_type"] == "council":
            days.setdefault(row["meeting_date"], ([], []))[0].append(row)
    for event in events:
        if event["id"] not in paired_events and event["classification"].meeting_type == "council":
            days.setdefault(event["on"], ([], []))[1].append(event)
    for day_rows, day_events in days.values():
        if len(day_rows) == 1 and len(day_events) == 1:
            out.append((day_rows[0], day_events[0]))
            paired_rows.add(day_rows[0]["id"])
            paired_events.add(day_events[0]["id"])

    out.extend((row, None) for row in rows if row["id"] not in paired_rows)
    out.extend((None, event) for event in events if event["id"] not in paired_events)
    return out


def _cancellation(row: dict | None, event: dict | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Who says the meeting is off, and the sentences that tell the reader. Both empty when nobody does."""
    row_says = row is not None and is_cancelled_title(row["title"])
    event_says = event is not None and not meeting_types._is_live(event)
    if not (row_says or event_says):
        return (), ()
    said_by = tuple(name for says, name in ((row_says, _VIDEO_SITE), (event_says, _CALENDAR)) if says)

    a_title_says = row_says or (event is not None and is_cancelled_title(event["title"]))
    status = event["event_status"] if event is not None else None
    if event_says and not a_title_says and status.lower() not in _CANCELLED_WORDS:
        # The calendar's own word, which may not mean cancelled; quoted, not translated.
        sentences = [f'The city calendar marks this "{status}".']
    else:
        sentences = [f"Cancelled, according to {' and '.join(said_by)}."]
    if row is not None and event is not None and len(said_by) == 1:
        sentences.append("The city calendar still lists it." if row_says else "The council's video site still lists it.")
    return said_by, tuple(sentences)


def _meeting_title(row: dict | None, event: dict | None) -> str:
    """The label a reader sees: the row's, as the `meeting_label` template global builds it, or the event's."""
    if row is not None:
        if row["meeting_type"] not in MEETING_TYPES:
            return row["title"]
        return label_for(row["meeting_type"], row["session_kind"], row["body_name"], row["title"], cancelled=False)
    found = event["classification"]
    return label_for(found.meeting_type, found.session_kind, found.body_name, event["title"], cancelled=False)


def _meeting_entry(slug: str, row: dict | None, event: dict | None) -> Entry:
    if event is not None:
        on, starts_at, ends_at = event["on"], event["starts_at"], event["ends_at"]
    else:
        on, ends_at = row["meeting_date"], None
        starts_at = (
            datetime.combine(on, row["start_time"], tzinfo=_CHICAGO) if row["start_time"] is not None else None
        )

    links: list[tuple[str, str]] = []
    source_url = None
    if event is not None:
        links.append(("City calendar", event["source_url"]))
        source_url = event["source_url"]
    if row is not None:
        if row["agenda_url"]:
            links.append(("Agenda", row["agenda_url"]))
            source_url = source_url or row["agenda_url"]
        links.append(("Meeting on docket.pub", f"/al/{slug}/meetings/{row['id']}/"))

    said_by, sentences = _cancellation(row, event)
    return Entry(
        kind="meeting",
        uid=f"calendar-{event['id']}@docket.pub" if event is not None else f"meeting-{row['id']}@docket.pub",
        on=on,
        starts_at=starts_at,
        ends_at=ends_at,
        title=_meeting_title(row, event),
        detail=sentences,
        links=tuple(links),
        source_url=source_url,
        place=None,
        badge="meeting",
        badge_label="Meeting",
        cancelled=bool(said_by),
        cancelled_by=said_by,
        attend=(),
        association=None,
    )


# --- hearings ---------------------------------------------------------------


def _hearing_entry(slug: str, hearing: dict) -> Entry:
    kind = hearing["kind"]
    title = KIND_TITLES[kind]
    if kind == "other":
        badge, badge_label = "hearing", "Hearing"
    else:
        badge, badge_label = kind.replace("_", "-"), KIND_LABELS[kind]

    if kind == "weed_lots":
        # The list of lots is the subject; the count says it, and no count is invented.
        count = hearing["property_count"]
        # "listed in a resolution", not "found by the council": nothing here
        # checks that the resolution was adopted.
        detail = (
            (
                f"{count} {'property' if count == 1 else 'properties'} listed in a resolution"
                " as having noxious or dangerous weeds",
            )
            if count is not None
            else ()
        )
    else:
        detail = (_clip(hearing["subject"], _SUBJECT_MAX),)

    links: list[tuple[str, str]] = []
    source_url = None
    for item in reversed(hearing["items"]):  # oldest meeting first, so the newest is last
        if item["agenda_url"]:
            source_url = item["agenda_url"]
            links.append(("City agenda", source_url))
            break
    for item in hearing["items"]:
        links.append((f"On the agenda of {_long_date(item['meeting_date'])}", f"/al/{slug}/items/{item['item_id']}/"))

    return Entry(
        kind="hearing",
        uid=f"hearing-{hearing['id']}@docket.pub",
        on=hearing["hearing_date"],
        starts_at=None,
        ends_at=None,
        title=title,
        detail=detail,
        links=tuple(links),
        source_url=source_url,
        place=None,
        badge=badge,
        badge_label=badge_label,
        cancelled=False,
        cancelled_by=(),
        attend=(),
        association=None,
    )


# --- neighborhood meetings --------------------------------------------------


def _neighborhood_entry(schedule: neighborhood_schedule.Schedule, occurrence: neighborhood_schedule.Occurrence) -> Entry:
    association, on = occurrence.association, occurrence.on
    slug = association_slug(association.name)

    detail = [association.type_text]
    if association.remote is None and ("phone" in association.modes or "video" in association.modes):
        detail.append("Call-in details are not in the schedule")
    starts_at = None
    if association.time is None:
        detail.append("The schedule gives no time")
    else:
        starts_at = datetime.combine(on, time.fromisoformat(association.time), tzinfo=_CHICAGO)

    attend: list[tuple[str, str]] = []
    if association.place is not None:
        attend.append(("Where", association.place))
    if association.remote is not None:
        attend.append(("Call-in", association.remote))

    return Entry(
        kind="neighborhood",
        uid=f"na-{slug}-{on:%Y%m%d}@docket.pub",
        on=on,
        starts_at=starts_at,
        ends_at=None,
        title=f"{association.name} Neighborhood Association",
        detail=tuple(detail),
        links=(("City schedule (PDF)", schedule.url),),
        source_url=schedule.url,
        place=association.place,
        badge="neighborhood",
        badge_label="Neighborhood",
        cancelled=False,
        cancelled_by=(),
        attend=tuple(attend),
        association=slug,
    )


# --- the list ---------------------------------------------------------------


def _order(entry: Entry) -> tuple:
    timed = entry.starts_at is not None
    return (entry.on, not timed, entry.starts_at if timed else None, KINDS.index(entry.kind), entry.title)


def list_entries(municipality: dict, *, today: date | None = None) -> list[Entry]:
    """Every entry of the city from `today` through `WINDOW_DAYS` days ahead.

    Ordered by date, then timed entries by start before untimed ones, then
    kind (meeting, hearing, neighborhood), then title. `today` defaults to
    the current date in America/Chicago.
    """
    start = today if today is not None else _today()
    end = start + timedelta(days=WINDOW_DAYS)
    city_id, slug = municipality["id"], municipality["slug"]

    entries = [
        _meeting_entry(slug, row, event)
        for row, event in _pair(_granicus_rows(city_id, start, end), _calendar_events(city_id, start, end))
    ]
    entries.extend(_hearing_entry(slug, hearing) for hearing in hearings.list_upcoming(city_id, start, end))
    schedule = neighborhood_schedule.get_schedule(slug)
    if schedule is not None:
        entries.extend(
            _neighborhood_entry(schedule, occurrence)
            for occurrence in neighborhood_schedule.occurrences(schedule, start, end)
        )

    # Untimed entries all compare equal on the third term, so None is never ordered against a time.
    entries.sort(key=_order)
    return entries


def filter_entries(entries: list[Entry], *, kind: str | None = None, association: str | None = None) -> list[Entry]:
    """The entries of `kind`, of `association`, of both, or all of them; the order is kept. Pure."""
    return [
        entry
        for entry in entries
        if (kind is None or entry.kind == kind) and (association is None or entry.association == association)
    ]


def undated_associations(slug: str) -> list[tuple[str, str]]:
    """The name and the reason of each association the city's schedule gives no dates."""
    schedule = neighborhood_schedule.get_schedule(slug)
    if schedule is None:
        return []
    return [(a.name, a.undated_reason) for a in neighborhood_schedule.undated(schedule)]


def schedule_source(slug: str) -> dict | None:
    """The schedule's `title`, `url`, `revised` date and `year`, or None for a city with no schedule."""
    schedule = neighborhood_schedule.get_schedule(slug)
    if schedule is None:
        return None
    return {"title": schedule.title, "url": schedule.url, "revised": schedule.revised, "year": schedule.year}


def association_feeds(slug: str) -> list[tuple[str, str]]:
    """The name and slug of every association of the city's schedule that is given dates, in name order."""
    schedule = neighborhood_schedule.get_schedule(slug)
    if schedule is None:
        return []
    return sorted((a.name, association_slug(a.name)) for a in schedule.associations if a.ordinal is not None)
