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
3. **calendar** — the city's own calendar page (``city_calendar_events``,
   filled daily by the worker task ``city_calendar``) lists an event on the
   meeting's day. The match reads documents and never ``start_time``, whose
   stored values are wrong (issue #88): with one event on the day, that
   one; with several, a row with documents (a minutes link or at least one
   agenda item) takes the day's council event when exactly one exists, a
   row without documents takes the day's committee event when exactly one
   exists, and otherwise the rung yields nothing. A row with a minutes link
   never takes a committee event, since committees have no minutes and a
   council meeting moved to a committee's day is told apart by them.
4. **schedule_rule** — the city's metadata names the council's regular
   weekday (``council_schedule.weekday``, Monday 0), the row falls on
   another weekday, has no minutes link, and is not cancelled: it is a
   council-department recording that is not the regular meeting, labelled
   "Council committee meeting" with no body name. Agenda items are not a
   condition (the Committee of the Whole carries the next council agenda).
5. Otherwise the title's classification stands, with source ``title``.

:func:`resolve` is pure; :func:`resolve_and_store` loads the rows and writes
the ones that changed in one statement; :func:`reclassify_city` is the
operator's one-time pass over a whole city (``scripts/reclassify_meetings.py``).

Plan: plans/active/meeting-types-name-the-body.md (M4).
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

TYPE_SOURCES: tuple[str, ...] = ("title", "calendar", "schedule_rule", "admin")

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

_CHICAGO = ZoneInfo("America/Chicago")
_GENERIC = Classification("council", "regular", None)
_DATE_SUFFIX = re.compile(r",\s*[A-Za-z]+\s+\d{1,2},?\s+\d{4}\s*$")
_SMALL_WORDS = {"of", "the", "and"}


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


def _choose_event(events: list[tuple[dict, Classification]], *, has_documents: bool, has_minutes: bool):
    """Pick the day's event for a row, by documents alone (never by start_time)."""
    if not events:
        return None
    if len(events) == 1:
        chosen = events[0]
    else:
        wanted = "council" if has_documents else "committee"
        of_kind = [e for e in events if e[1].meeting_type == wanted]
        if len(of_kind) != 1:
            return None
        chosen = of_kind[0]
    if has_minutes and chosen[1].meeting_type == "committee":
        return None
    return chosen


def resolve(
    municipality: dict,
    meeting: dict,
    *,
    calendar_events: list[dict],
    item_count: int,
) -> Resolution | None:
    """Run the ladder for one row; ``None`` when the row is locked.

    ``municipality`` needs ``metadata``; ``meeting`` needs ``title``,
    ``meeting_date``, ``minutes_url``, and ``type_locked_at``;
    ``calendar_events`` are the city's rows (``id``, ``title``,
    ``starts_at``), any day; ``item_count`` is the row's agenda items.
    ``start_time`` is never read.
    """
    if meeting.get("type_locked_at") is not None:
        return None
    title = meeting.get("title") or ""
    base = classify_title(title)
    if base != _GENERIC:
        return Resolution(base, "title", None)

    if meeting.get("meeting_date") is None:
        # The calendar and the schedule rule both need a date; a dated-less
        # row can only be what its title says.
        return Resolution(base, "title", None)
    meta = _metadata(municipality)
    meeting_date = _as_date(meeting["meeting_date"])
    has_minutes = bool(meeting.get("minutes_url"))
    has_documents = has_minutes or item_count > 0

    if meta.get("calendar_url"):
        todays: list[tuple[dict, Classification]] = []
        for ev in calendar_events:
            if _event_date(ev) != meeting_date:
                continue
            cls = classify_event(ev.get("title") or "")
            if cls is not None:
                todays.append((ev, cls))
        chosen = _choose_event(todays, has_documents=has_documents, has_minutes=has_minutes)
        if chosen is not None:
            return Resolution(chosen[1], "calendar", chosen[0]["id"])

    schedule = meta.get("council_schedule")
    weekday = schedule.get("weekday") if isinstance(schedule, dict) else None
    if (
        weekday is not None
        and meeting_date.weekday() != int(weekday)
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
           m.meeting_type, m.session_kind, m.body_name, m.type_source, m.calendar_event_id,
           m.executive_summary IS NOT NULL AS has_summary,
           (SELECT count(*) FROM agenda_items a WHERE a.meeting_id = m.id) AS item_count
      FROM meetings m
     WHERE m.municipality_id = %s AND {where}
     ORDER BY m.meeting_date, m.id
"""

_CALENDAR_SQL = "SELECT id, title, starts_at FROM city_calendar_events WHERE municipality_id = %s"

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
    """Resolve every row; return the rows whose five columns would change, each
    with ``resolution`` attached."""
    changed = []
    for m in meetings:
        res = resolve(municipality, m, calendar_events=events, item_count=int(m["item_count"] or 0))
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
    """Resolve the given rows of one city and write the ones that changed; returns how many.

    Runs after every ingest over the rows the feed listed that day, so a
    row that gains minutes, items, or a cancelled title moves back down the
    ladder on its own. The write is one ``UPDATE ... FROM (VALUES ...)``
    scoped to unlocked rows (decision 0026).
    """
    if not meeting_ids:
        return 0
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_MUNICIPALITY_SQL.format(where="id = %s"), (municipality_id,))
        municipality = cur.fetchone()
        if municipality is None:
            return 0
        meetings, events = _load(cur, municipality_id, "m.id = ANY(%s)", (list(meeting_ids),))
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
    """Lift the admin lock and put the row back on the ladder by resolving it once.

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
            meetings, events = _load(cur, municipality_id, "m.id = %s", (meeting_id,))
            _write(cur, _changes(dict(municipality), meetings, events))
        conn.commit()
