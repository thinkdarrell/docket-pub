"""Resolve which body met and what kind of sitting it was, from every source we hold.

A meeting's classification is three facts on ``meetings``: ``meeting_type``
(the body: ``council``, ``committee``, ``planning``, ``board``, ``other``),
``session_kind`` (the sitting: ``regular``, ``special``, ``work_session``,
``budget_hearing``), and ``body_name`` (the body's name when a source
supplied it). ``type_source`` says which evidence decided them.

The evidence ladder, top rung first:

1. **admin** — an admin locked the row (``type_locked_at``); nothing here
   touches it, and :func:`resolve` returns ``None``.
2. **title** — the city's own name for the clip, classified by
   ``docket.adapters._helpers.classify_title``. A specific title (one that
   says special, called, work session, budget, or names a committee or
   board) is final. Only the generic case, ``council`` and ``regular``
   ("Regular City Council Meeting", which Birmingham's clerk puts on every
   clip), goes on to the next rungs.
3. **video** — for a generic title, a YouTube recording attached to the row
   (``meeting_videos``) whose cleaned title names a body is final; the
   council's own name for its stream outranks the calendar and the rule.
   The row's YouTube clean titles are read primary first, and the first one
   whose ``classify_title`` is not the generic council reading decides.
4. **calendar** — the city's own calendar (``city_calendar_events``,
   filled daily by the worker task ``city_calendar``) lists an event on the
   meeting's day. A cancelled event (a stored status other than ``active``,
   or a title that says cancelled) is dropped first. The match reads
   documents, lengths, and the day's other rows, and never ``start_time``,
   whose stored values are wrong (issue #88). A row with a minutes link
   takes the day's council event when exactly one exists and never a
   committee's, since committees keep no minutes. A row with agenda items
   takes the one council event too; with no council event it gets nothing
   on the council's regular weekday (the council's own event can be
   missing while a committee's is stored, 2026-11-03) and on any other day
   is read as a row without documents, since committee clips carry the
   next council agenda. A row without documents takes the council event
   when that is the day's only event. With one committee event it takes
   that, unless it runs under ``ELIMINATION_MIN_S`` and another unnamed
   recording of the day runs longer: a stream test does not share a name
   with the meeting. With several committee events it is named by
   elimination: the events that the day's named rows account for
   (:func:`same_committee`) are set aside, and the row takes the one left
   only when exactly one is left, the row is long, and no other unnamed
   recording of the day is long or of unknown length. Who competes and who
   names is decided from each row's own facts, never from what this rung
   stored for a sibling, so one call per row gives the same answer in any
   order.
5. **schedule_rule** — the city's metadata names the council's regular
   weekday (``council_schedule.weekday``, Monday 0), the row falls on
   another weekday, has no minutes link, and is not cancelled: it is a
   council-department recording that is not the regular meeting, labelled
   "Council committee meeting" with no body name. Agenda items are not a
   condition (the Committee of the Whole carries the next council agenda).
6. Otherwise the title's classification stands, with source ``title``.

:func:`resolve` is pure; :func:`resolve_and_store` loads the rows and writes
the ones that changed in one statement; :func:`reclassify_city` is the
operator's one-time pass over a whole city (``scripts/reclassify_meetings.py``).

Plan: plans/completed/meeting-types-name-the-body.md (M4); the video rung,
plans/completed/youtube-council-channel.md (M3); the whole-day calendar rung,
plan `committee-clips-named-or-hidden` (M2).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import psycopg2.extras

from docket.adapters._helpers import MEETING_TYPES, SESSION_KINDS, Classification, classify_title
from docket.db import db
from docket.services.query import is_cancelled_title

log = logging.getLogger(__name__)

TYPE_SOURCES: tuple[str, ...] = ("title", "video", "calendar", "schedule_rule", "admin")

# The council's eight standing committees for 2025 to 2027, as the city
# council page's menu names them. A calendar event is matched to one by
# letters alone (see _letters), longest name first.
BIRMINGHAM_COMMITTEES: tuple[str, ...] = (
    "Arts and Parks",
    "Budget and Finance",
    "Committee of the Whole / Administration & Governmental Affairs",
    "Community Development",
    "Economic and Workforce Development / Tourism",
    "Planning & Zoning",
    "Public Safety",
    "Transportation & Infrastructure",
)

# A recording of at least this many seconds is long: it can be named by
# elimination, and beside it a shorter one is not named after the day's one
# committee event. Real committee meetings of 6 and 11 minutes exist, so the
# floor decides only between recordings of one day, never whether a row is a
# meeting.
ELIMINATION_MIN_S = 600
# The shorter of two committee names must have this many letters before it
# matches the longer as a prefix ("Committee of the Whole" against the
# calendar's "Committee of the Whole / Administration & Governmental Affairs").
_PREFIX_MIN_LETTERS = 8

_CHICAGO = ZoneInfo("America/Chicago")
_GENERIC = Classification("council", "regular", None)
_DATE_SUFFIX = re.compile(r",\s*[A-Za-z]+\s+\d{1,2},?\s+\d{4}\s*$")
_SMALL_WORDS = {"of", "the", "and"}
_TRAILING_BODY_WORDS = re.compile(r"(?:\s*\b(?:committee|meeting|work\s+session)\b\s*)+$", re.IGNORECASE)


@dataclass(frozen=True)
class Resolution:
    """What the ladder decided for one row: the classification, which rung, and the matched calendar event."""

    classification: Classification
    type_source: str
    calendar_event_id: int | None


@dataclass(frozen=True)
class ReclassifyReport:
    """What one pass of :func:`reclassify_city` saw and did.

    ``transitions`` maps ``(old type, old kind, new type, new kind, source)``
    to a row count over every non-hidden row of the city (a locked row
    appears unchanged under source ``admin``); ``rule_rows_before_2026``
    lists the rows the schedule rule classifies that predate 2026-01-01
    (``id``, ``meeting_date``, ``weekday``, ``title``, ``item_count``) so the
    operator reads them before the write; ``written`` and
    ``summaries_cleared`` are 0 on a dry run.
    """

    transitions: dict[tuple[str, str, str, str, str], int]
    rule_rows_before_2026: list[dict]
    written: int
    summaries_cleared: int


# --- the pure ladder ---------------------------------------------------------


def _metadata(municipality: dict) -> dict:
    meta = municipality.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            return {}
    return meta if isinstance(meta, dict) else {}


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _letters(text: str) -> str:
    """Only the letters, uppercased, with ``&`` read as ``and`` so the city's
    two spellings of a committee ("Transportation & Infrastructure" in the
    menu, "TRANSPORTATION AND INFRASTRUCTURE" on the event) compare equal."""
    return re.sub(r"[^A-Z]", "", text.replace("&", " and ").upper())


_COMMITTEES_BY_LENGTH = sorted(BIRMINGHAM_COMMITTEES, key=len, reverse=True)
_COMMITTEE_LETTERS = tuple((_letters(name), name) for name in _COMMITTEES_BY_LENGTH)


def _clean_event_title(title: str) -> str:
    """The fallback body name for a committee the canonical list does not
    hold: the title without its date, without the word MEETING, title-cased
    ("Public Works Committee")."""
    name = _DATE_SUFFIX.sub("", title)
    name = re.sub(r"\bMEETING\b", " ", name, flags=re.IGNORECASE)
    name = name.replace("/", " / ").replace("&", " & ")
    words = name.split()
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        if w in ("/", "&"):
            out.append(w)
        elif i > 0 and lw in _SMALL_WORDS:
            out.append(lw)
        else:
            out.append(lw.capitalize())
    return " ".join(out)


def committee_name_for(event_title: str) -> str:
    """The canonical committee name an event title names, or the cleaned title."""
    letters = _letters(event_title)
    for canonical_letters, name in _COMMITTEE_LETTERS:
        if canonical_letters and canonical_letters in letters:
            return name
    return _clean_event_title(event_title)


def classify_event(event_title: str) -> Classification | None:
    """What a calendar event's title says: a council sitting, a committee, or nothing usable."""
    upper = event_title.upper()
    if "CITY COUNCIL MEETING" in upper:
        return Classification("council", "special" if "SPECIAL" in upper else "regular", None)
    if "COMMITTEE" in upper:
        return Classification("committee", "regular", committee_name_for(event_title))
    return None


def _event_date(ev: dict) -> date:
    starts_at = ev["starts_at"]
    if isinstance(starts_at, str):
        starts_at = datetime.fromisoformat(starts_at)
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=ZoneInfo("UTC"))
    return starts_at.astimezone(_CHICAGO).date()


def same_committee(a: str, b: str) -> bool:
    """Do two names, a recording's or a calendar event's, name one committee?

    Each goes through :func:`committee_name_for` first, which removes an
    event title's trailing date and the word MEETING or returns the
    canonical name; only then is a trailing run of "committee", "meeting",
    and "work session" removed (an event title ends with its date, so the
    other order would remove nothing), and the rest reduced to letters.
    Equal letters are the same committee, and so is a shorter name of at
    least eight letters that opens the longer one. A name with nothing
    left matches nothing.
    """
    ka = _letters(_TRAILING_BODY_WORDS.sub("", committee_name_for(a or "")))
    kb = _letters(_TRAILING_BODY_WORDS.sub("", committee_name_for(b or "")))
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    shorter, longer = sorted((ka, kb), key=len)
    return len(shorter) >= _PREFIX_MIN_LETTERS and longer.startswith(shorter)


def _is_live(ev: dict) -> bool:
    """A calendar event that was held, as far as the city says: its stored
    status is NULL (the source reported none) or ``active``, and its title
    does not say cancelled. Only ``active`` has been observed, so the test is
    written against what is not ``active``."""
    status = ev.get("event_status")
    return (status is None or status == "active") and not is_cancelled_title(ev.get("title"))


def _before_calendar(row: dict) -> tuple[Classification, str] | None:
    """What the rungs above the calendar decide for a row, with the rung, or
    ``None`` when the row reaches the calendar: the stored classification of
    a locked row, a specific title's, or the first naming recording's."""
    if row.get("type_locked_at") is not None:
        stored = Classification(
            row.get("meeting_type") or _GENERIC.meeting_type,
            row.get("session_kind") or _GENERIC.session_kind,
            row.get("body_name"),
        )
        return stored, "admin"
    base = classify_title(row.get("title") or "")
    if base != _GENERIC:
        return base, "title"
    for video_title in row.get("video_titles") or ():
        named = classify_title(video_title or "")
        if named != _GENERIC:
            return named, "video"
    return None


def _is_long(row: dict) -> bool:
    return row.get("duration_s") is not None and row["duration_s"] >= ELIMINATION_MIN_S


def _is_short(row: dict) -> bool:
    return row.get("duration_s") is not None and row["duration_s"] < ELIMINATION_MIN_S


def _without_documents(row: dict, *, council_events: int, on_council_day: bool) -> bool:
    """Is this a row the day's committee events are for? One with no
    minutes link and no agenda items, or one with items and no minutes on a
    day that has no council event and is not the council's weekday (a
    committee clip carries the next council agenda)."""
    if row.get("minutes_url"):
        return False
    if int(row.get("item_count") or 0) > 0:
        return council_events == 0 and not on_council_day
    return True


def _choose_event(
    events: list[tuple[dict, Classification]], row: dict, siblings: list[dict], *, on_council_day: bool
):
    """Pick the day's event for a row that reached the calendar rung, from
    the row's documents and length and the day's other rows (never from
    ``start_time``). ``events`` are the day's live, usable events; ``row``
    and each sibling carry ``title``, ``minutes_url``, ``type_locked_at``,
    ``meeting_type``, ``body_name``, ``item_count``, ``video_titles``, and
    ``duration_s``. The module docstring states the rule.
    """
    council = [e for e in events if e[1].meeting_type == "council"]
    committee = [e for e in events if e[1].meeting_type == "committee"]
    one_council = council[0] if len(council) == 1 else None

    if not _without_documents(row, council_events=len(council), on_council_day=on_council_day):
        # Minutes, or items beside a council event, or items on the council's
        # weekday with no council event stored (2026-11-03): the one council
        # event or nothing, never a committee's.
        return one_council
    if not committee:
        return one_council

    competitors = [
        s for s in siblings
        if _before_calendar(s) is None
        and _without_documents(s, council_events=len(council), on_council_day=on_council_day)
    ]
    if len(committee) == 1:
        if _is_short(row) and any(_is_long(c) for c in competitors):
            return None
        return committee[0]

    namers = []
    for s in siblings:
        above = _before_calendar(s)
        if above is not None and above[0].meeting_type == "committee" and above[0].body_name:
            namers.append(above[0].body_name)
    left = [e for e in committee if not any(same_committee(n, e[1].body_name) for n in namers)]
    if len(left) != 1 or not _is_long(row):
        return None
    if any(not _is_short(c) for c in competitors):
        return None
    return left[0]


def resolve(
    municipality: dict,
    meeting: dict,
    *,
    calendar_events: list[dict],
    item_count: int,
    video_titles: list[str] | None = None,
    duration_s: int | None = None,
    siblings: list[dict] | None = None,
) -> Resolution | None:
    """Run the ladder for one row; ``None`` when the row is locked.

    ``municipality`` needs ``metadata``; ``meeting`` needs ``title``,
    ``meeting_date``, ``minutes_url``, and ``type_locked_at``;
    ``calendar_events`` are the city's rows (``id``, ``title``,
    ``starts_at``, and ``event_status`` when stored), any day;
    ``item_count`` is the row's agenda items; ``video_titles`` are the clean
    titles of the row's YouTube recordings, primary first (``None`` or empty
    when it has none); ``duration_s`` is the row's stored length;
    ``siblings`` are the city's other non-hidden rows of the same
    ``meeting_date``, each a dict of the facts read of the row itself
    (``title``, ``minutes_url``, ``type_locked_at``, ``meeting_type``,
    ``body_name``, ``item_count``, ``video_titles``, ``duration_s``).
    ``start_time`` is never read, and nothing the calendar rung stored for
    a sibling (its ``type_source``, its ``calendar_event_id``) is either.
    """
    if meeting.get("type_locked_at") is not None:
        return None
    title = meeting.get("title") or ""
    base = classify_title(title)
    row = {**meeting, "item_count": item_count, "video_titles": video_titles, "duration_s": duration_s}
    above = _before_calendar(row)
    if above is not None:
        return Resolution(above[0], above[1], None)

    if meeting.get("meeting_date") is None:
        # The calendar and the schedule rule both need a date; a dated-less
        # row can only be what its title says.
        return Resolution(base, "title", None)
    meta = _metadata(municipality)
    meeting_date = _as_date(meeting["meeting_date"])
    has_minutes = bool(meeting.get("minutes_url"))
    schedule = meta.get("council_schedule")
    weekday = schedule.get("weekday") if isinstance(schedule, dict) else None
    on_council_day = weekday is not None and meeting_date.weekday() == int(weekday)

    if meta.get("calendar_url"):
        todays: list[tuple[dict, Classification]] = []
        for ev in calendar_events:
            if _event_date(ev) != meeting_date or not _is_live(ev):
                continue
            cls = classify_event(ev.get("title") or "")
            if cls is not None:
                todays.append((ev, cls))
        chosen = _choose_event(todays, row, list(siblings or ()), on_council_day=on_council_day)
        if chosen is not None:
            return Resolution(chosen[1], "calendar", chosen[0]["id"])

    if (
        weekday is not None
        and not on_council_day
        and not has_minutes
        and not is_cancelled_title(title)
    ):
        return Resolution(Classification("committee", "regular", None), "schedule_rule", None)

    return Resolution(base, "title", None)


def summary_clear_ids(rows: list[dict]) -> list[int]:
    """The ids whose body leaves ``council`` (``meeting_type`` to ``new_meeting_type``):
    their AI meeting summary was written as a council meeting's and is cleared
    so the worker regenerates it."""
    return [
        r["id"] for r in rows
        if r.get("meeting_type") == "council" and r.get("new_meeting_type") != "council"
    ]


# --- loading and writing -----------------------------------------------------

_MUNICIPALITY_SQL = "SELECT id, slug, metadata FROM municipalities WHERE {where}"

_MEETING_ROWS_SQL = """
    SELECT m.id, m.title, m.meeting_date, m.minutes_url, m.type_locked_at,
           m.duration_s, m.is_hidden,
           m.meeting_type, m.session_kind, m.body_name, m.type_source, m.calendar_event_id,
           m.executive_summary IS NOT NULL AS has_summary,
           (SELECT count(*) FROM agenda_items a WHERE a.meeting_id = m.id) AS item_count,
           (SELECT array_agg(v.clean_title ORDER BY v.is_primary DESC, v.id)
              FROM meeting_videos v
             WHERE v.meeting_id = m.id AND v.provider = 'youtube') AS video_titles
      FROM meetings m
     WHERE m.municipality_id = %s AND {where}
     ORDER BY m.meeting_date, m.id
"""

_CALENDAR_SQL = "SELECT id, title, starts_at, event_status FROM city_calendar_events WHERE municipality_id = %s"

# The rows one resolution of some ids must load: the ids themselves (hidden
# or dateless ones too, as before) and every non-hidden row of the city on
# any of their dates, since a row's answer depends on its day.
_WHOLE_DAYS_WHERE = """(m.id = ANY(%s) OR (m.is_hidden = FALSE AND m.meeting_date IN (
        SELECT d.meeting_date FROM meetings d
         WHERE d.municipality_id = m.municipality_id AND d.id = ANY(%s))))"""

_WRITE_SQL = """
    UPDATE meetings AS m
       SET meeting_type = v.t, session_kind = v.k, body_name = v.b, type_source = v.s,
           calendar_event_id = v.c
      FROM (VALUES {values}) AS v(id, t, k, b, s, c)
     WHERE m.id = v.id AND m.type_locked_at IS NULL
"""

_CLEAR_SUMMARIES_SQL = """
    UPDATE meetings
       SET executive_summary = NULL, executive_summary_voice = NULL,
           ai_prompt_version = NULL, ai_generated_at = NULL
     WHERE id = ANY(%s) AND executive_summary IS NOT NULL
"""


def _load(cur, municipality_id: int, where: str, params: tuple) -> tuple[list[dict], list[dict]]:
    cur.execute(_MEETING_ROWS_SQL.format(where=where), (municipality_id, *params))
    meetings = [dict(r) for r in cur.fetchall()]
    cur.execute(_CALENDAR_SQL, (municipality_id,))
    events = [dict(r) for r in cur.fetchall()]
    return meetings, events


def _changes(municipality: dict, meetings: list[dict], events: list[dict]) -> list[dict]:
    """Resolve every row once, each with the non-hidden rows of its date as
    siblings; return the rows whose five columns would change, each with
    ``resolution`` attached. ``meetings`` must hold every non-hidden row of
    each date it holds a row of, or a row's competitors go unseen."""
    by_date: dict[date, list[dict]] = {}
    for m in meetings:
        if m.get("meeting_date") is not None and not m.get("is_hidden"):
            by_date.setdefault(_as_date(m["meeting_date"]), []).append(m)
    changed = []
    for m in meetings:
        day = by_date.get(_as_date(m["meeting_date"]), []) if m.get("meeting_date") is not None else []
        res = resolve(municipality, m, calendar_events=events, item_count=int(m["item_count"] or 0),
                      video_titles=m.get("video_titles"), duration_s=m.get("duration_s"),
                      siblings=[s for s in day if s is not m])
        m["resolution"] = res
        if res is None:
            continue
        c = res.classification
        new = (c.meeting_type, c.session_kind, c.body_name, res.type_source, res.calendar_event_id)
        old = (m["meeting_type"], m["session_kind"], m["body_name"], m["type_source"], m["calendar_event_id"])
        if new != old:
            changed.append(m)
    return changed


def _write(cur, changed: list[dict]) -> int:
    """One statement over every changed row; returns the rows written."""
    if not changed:
        return 0
    values = ", ".join(["(%s::int, %s::text, %s::text, %s::text, %s::text, %s::int)"] * len(changed))
    params: list = []
    for m in changed:
        res = m["resolution"]
        c = res.classification
        params.extend([m["id"], c.meeting_type, c.session_kind, c.body_name, res.type_source, res.calendar_event_id])
    cur.execute(_WRITE_SQL.format(values=values), params)
    return cur.rowcount


def resolve_and_store(municipality_id: int, meeting_ids: list[int]) -> int:
    """Resolve the given rows of one city, and every other non-hidden row of
    their dates, and write the ones that changed; returns how many.

    Runs after every ingest over the rows the feed listed that day, so a
    row that gains minutes, items, or a cancelled title moves back down the
    ladder on its own, and after the YouTube pass over the rows it touched.
    The set is widened to whole days because one row's new recording can
    name the row beside it; each row is resolved once. The write is one
    ``UPDATE ... FROM (VALUES ...)`` scoped to unlocked rows (decision 0026).
    """
    if not meeting_ids:
        return 0
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_MUNICIPALITY_SQL.format(where="id = %s"), (municipality_id,))
        municipality = cur.fetchone()
        if municipality is None:
            return 0
        ids = list(meeting_ids)
        meetings, events = _load(cur, municipality_id, _WHOLE_DAYS_WHERE, (ids, ids))
        changed = _changes(dict(municipality), meetings, events)
        return _write(cur, changed)


def reclassify_city(slug: str, *, dry_run: bool) -> ReclassifyReport:
    """Resolve every non-hidden row of one city; write them in one statement unless ``dry_run``.

    After the write, the AI meeting summaries of the rows whose body left
    ``council`` are cleared in a second statement so the worker regenerates
    them (``meetings_pending_v3_where`` re-queues a row whose
    ``ai_prompt_version`` is NULL and whose minutes are not adopted).
    """
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_MUNICIPALITY_SQL.format(where="slug = %s"), (slug,))
        municipality = cur.fetchone()
        if municipality is None:
            raise ValueError(f"unknown city slug: {slug}")
        meetings, events = _load(cur, municipality["id"], "m.is_hidden = FALSE", ())
        changed = _changes(dict(municipality), meetings, events)

        transitions: dict[tuple[str, str, str, str, str], int] = {}
        rule_rows: list[dict] = []
        for m in meetings:
            res = m["resolution"]
            if res is None:
                key = (m["meeting_type"], m["session_kind"], m["meeting_type"], m["session_kind"], "admin")
            else:
                c = res.classification
                key = (m["meeting_type"], m["session_kind"], c.meeting_type, c.session_kind, res.type_source)
                if res.type_source == "schedule_rule" and _as_date(m["meeting_date"]) < date(2026, 1, 1):
                    rule_rows.append({
                        "id": m["id"],
                        "meeting_date": _as_date(m["meeting_date"]),
                        "weekday": _as_date(m["meeting_date"]).strftime("%a"),
                        "title": m["title"],
                        "item_count": int(m["item_count"] or 0),
                    })
            transitions[key] = transitions.get(key, 0) + 1

        leaving = summary_clear_ids([
            {"id": m["id"], "meeting_type": m["meeting_type"],
             "new_meeting_type": m["resolution"].classification.meeting_type}
            for m in changed
        ])
        if dry_run:
            return ReclassifyReport(transitions, rule_rows, 0, 0)

        written = _write(cur, changed)
        cleared = 0
        if leaving:
            cur.execute(_CLEAR_SUMMARIES_SQL, (leaving,))
            cleared = cur.rowcount
        log.info("reclassify %s: %d rows written, %d summaries cleared", slug, written, cleared)
        return ReclassifyReport(transitions, rule_rows, written, cleared)


# --- the admin override and the calendar event behind a row (M5) ---------------

_CALENDAR_EVENT_FOR_SQL = """
    SELECT e.id, e.title, e.starts_at, e.ends_at, e.source_url, e.categories
      FROM meetings m
      JOIN city_calendar_events e ON e.id = m.calendar_event_id
     WHERE m.id = %s
"""

_SET_OVERRIDE_SQL = """
    UPDATE meetings
       SET meeting_type = %s, session_kind = %s, body_name = %s, type_source = 'admin',
           type_locked_at = now(), type_locked_by = %s, calendar_event_id = NULL
     WHERE id = %s
"""

_CLEAR_OVERRIDE_SQL = """
    UPDATE meetings
       SET type_locked_at = NULL, type_locked_by = NULL
     WHERE id = %s
 RETURNING municipality_id
"""


def calendar_event_for(meeting_id: int) -> dict | None:
    """The ``city_calendar_events`` row a meeting's ``calendar_event_id`` points at, or ``None``."""
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_CALENDAR_EVENT_FOR_SQL, (meeting_id,))
        row = cur.fetchone()
        return dict(row) if row else None


_ELIMINATION_ROW_SQL = """
    SELECT m.municipality_id, m.meeting_type, m.type_source, e.title, e.starts_at
      FROM meetings m
      JOIN city_calendar_events e ON e.id = m.calendar_event_id
     WHERE m.id = %s
"""


def named_by_elimination(meeting_id: int) -> bool:
    """Was this row's committee name reached by elimination, not read off a lone event?

    True only when the row is a ``committee`` named by the ``calendar``
    rung, its matched event is a committee's, and the city's stored,
    non-cancelled committee events on that event's Chicago date number more
    than one. A council row on a day with two committee events is not: the
    test is of the row's own type. The meeting page says so in its
    provenance sentence (``docs/PRINCIPLES.md``, "Source or silence").
    """
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_ELIMINATION_ROW_SQL, (meeting_id,))
        row = cur.fetchone()
        if row is None or row["meeting_type"] != "committee" or row["type_source"] != "calendar":
            return False
        matched = classify_event(row["title"] or "")
        if matched is None or matched.meeting_type != "committee":
            return False
        day = _event_date(dict(row))
        cur.execute(_CALENDAR_SQL, (row["municipality_id"],))
        committees = 0
        for ev in cur.fetchall():
            if _event_date(ev) != day or not _is_live(ev):
                continue
            cls = classify_event(ev.get("title") or "")
            if cls is not None and cls.meeting_type == "committee":
                committees += 1
        return committees > 1


def set_override(
    meeting_id: int,
    meeting_type: str,
    session_kind: str,
    body_name: str | None,
    admin_user_id: int | None,
) -> None:
    """Write the admin's classification and lock the row (the ladder's first rung).

    The lock is ``type_locked_at``; ingest's gated SET clauses and the
    resolver's ``WHERE type_locked_at IS NULL`` both leave a locked row alone
    until ``clear_override`` lifts it.
    """
    if meeting_type not in MEETING_TYPES:
        raise ValueError(f"unknown meeting_type: {meeting_type!r}")
    if session_kind not in SESSION_KINDS:
        raise ValueError(f"unknown session_kind: {session_kind!r}")
    with db() as conn, conn.cursor() as cur:
        cur.execute(_SET_OVERRIDE_SQL, (meeting_type, session_kind, body_name or None, admin_user_id, meeting_id))
        conn.commit()


def clear_override(meeting_id: int) -> None:
    """Lift the admin lock and put the row back on the ladder by resolving it, and the
    other rows of its date (a locked committee row names nothing once unlocked), once.

    One transaction: the lock is lifted and the row re-resolved under the same
    cursor, so a failure leaves the lock in place rather than a half-unlocked row.
    """
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_CLEAR_OVERRIDE_SQL, (meeting_id,))
        row = cur.fetchone()
        if row is None:
            return
        municipality_id = int(row["municipality_id"])
        cur.execute(_MUNICIPALITY_SQL.format(where="id = %s"), (municipality_id,))
        municipality = cur.fetchone()
        if municipality is not None:
            meetings, events = _load(cur, municipality_id, _WHOLE_DAYS_WHERE, ([meeting_id], [meeting_id]))
            _write(cur, _changes(dict(municipality), meetings, events))
        conn.commit()
