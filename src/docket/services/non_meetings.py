"""Hide the clips that are not meetings: a short or speechless recording on a day the city's calendar shows nothing.

The clerk's streaming equipment leaves recordings of a minute or a few in
Birmingham's Granicus archive on days when no body met, under the same
generic title as every real clip. The daily worker task ``non_meetings``
(06:55 America/Chicago, after ``youtube_ingest``) hides such a clip and
records why (``meetings.hidden_reason = 'not_a_meeting'``, migration 044).
Every reader of ``is_hidden`` then treats it exactly as a row an admin hid.

A clip is hidden when all of this holds:

- the city's metadata carries ``calendar_url`` and ``calendar_complete_from``
  (Birmingham only), the city has a stored event, and its
  ``calendar_sitemap_read_at`` is within ``CALENDAR_FRESH_HOURS``. That
  stamp is written by ``docket.services.city_calendar`` only after the
  sitemap reader, the one source of past days, read every unstored event
  page without a failure. Without it an empty day means a page was not
  read, not that nothing was scheduled, and nothing is hidden: a stream
  test left on the site costs less than a meeting taken off it;
- the row is visible, not locked by an admin (``type_locked_at``), not
  exempt (``keep_visible_at``, set for good by an admin's unhide), and not
  a ``yt-`` row;
- it has no agenda link, no minutes link, no agenda item, and no YouTube
  recording attached;
- its date is on or after ``calendar_complete_from`` and at least
  ``HIDE_AFTER_DAYS`` days before today (the YouTube pass creates a row for
  an unmatched recording at three days, so by four it has attached a
  recording to the clip or decided it has none);
- its title is the clerk's generic one and does not say cancelled;
- the stored calendar has no event on that date, in Chicago, that
  ``classify_event`` reads as a council sitting or a committee, whatever
  the event's status: a cancelled event still keeps the clip, which is the
  safe direction;
- it runs under ``SHORT_CLIP_S`` seconds, or its transcript's status is
  ``low_speech``. Length alone hides nothing: real committee meetings of
  six and eleven minutes exist, and it is the empty calendar day that marks
  a test.

A clip that meets all of it but has a public transcript (uploaded, and not
``low_speech``) is held back: it is not hidden, and ``/admin/meetings/hidden``
lists it for the operator.

The undo is the admin's Unhide on that page, which also exempts the row.
Plan `committee-clips-named-or-hidden`, M4.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from docket import config
from docket.adapters._helpers import classify_title
from docket.db import db, db_cursor
from docket.services.meeting_types import _GENERIC, _as_date, _event_date, _metadata, classify_event
from docket.services.query import is_cancelled_title

log = logging.getLogger(__name__)

# A clip under ten minutes is short. The same number as the resolver's
# ELIMINATION_MIN_S, and a separate rule: that one says which recording may
# take a committee's name, this one which may be hidden.
SHORT_CLIP_S = 600
# A clip is hidden no sooner than this many days after its date.
HIDE_AFTER_DAYS = 4
# The sitemap's last complete read must be this recent for the rule to run.
CALENDAR_FRESH_HOURS = 36

_CITIES_SQL = """
    SELECT id, slug, name, metadata
      FROM municipalities
     WHERE active = TRUE AND metadata ? 'calendar_complete_from'
     ORDER BY slug
"""

# The past days are known only after a complete sitemap read, so neither
# the council page's nor the search's morning read counts here.
_FRESH_SQL = """
    SELECT COALESCE((m.metadata->>'calendar_sitemap_read_at')::timestamptz >= now() - make_interval(hours => %s), FALSE)
           AND EXISTS (SELECT 1 FROM city_calendar_events e WHERE e.municipality_id = m.id) AS fresh
      FROM municipalities m
     WHERE m.id = %s
"""

_EVENTS_SQL = "SELECT title, starts_at FROM city_calendar_events WHERE municipality_id = %s"

_ROWS_SQL = """
    SELECT m.id, m.title, m.meeting_date, m.duration_s,
           t.status AS transcript_status, t.uploaded_at AS transcript_uploaded_at
      FROM meetings m
      LEFT JOIN transcripts t ON t.meeting_id = m.id
     WHERE m.municipality_id = %s
       AND m.is_hidden = FALSE
       AND m.keep_visible_at IS NULL
       AND m.type_locked_at IS NULL
       AND m.external_id NOT LIKE 'yt-%%'
       AND m.agenda_url IS NULL
       AND m.minutes_url IS NULL
       AND NOT EXISTS (SELECT 1 FROM agenda_items a WHERE a.meeting_id = m.id)
       AND NOT EXISTS (SELECT 1 FROM meeting_videos v WHERE v.meeting_id = m.id AND v.provider = 'youtube')
       AND m.meeting_date BETWEEN %s AND %s
     ORDER BY m.meeting_date, m.id
"""

# One statement for the city's list (decision 0026). The two conditions
# after the ids are the rule's own, repeated so that a row an admin hid or
# exempted between the read and the write is left as the admin put it.
_HIDE_SQL = """
    UPDATE meetings
       SET is_hidden = TRUE, hidden_at = now(), hidden_reason = 'not_a_meeting'
     WHERE id = ANY(%s) AND is_hidden = FALSE AND keep_visible_at IS NULL
 RETURNING id
"""


def find(municipality: dict, today: date) -> tuple[list[dict], list[dict]]:
    """The city's clips the rule hides, and the ones it holds back for their transcript.

    ``municipality`` carries ``id``, ``slug``, ``metadata``, and optionally
    ``name``. Each returned row has ``id``, ``title``, ``meeting_date``,
    ``duration_s``, ``transcript_status``, ``transcript_uploaded_at``,
    ``city_slug``, and ``city_name``. Reads only; two empty lists for a city
    without the two metadata keys, and, with a warning, for one whose
    sitemap was not read to the end lately or whose calendar is empty.
    """
    meta = _metadata(municipality)
    complete_from = meta.get("calendar_complete_from")
    if not complete_from or not meta.get("calendar_url"):
        return [], []
    slug = municipality.get("slug")

    with db_cursor() as cur:
        cur.execute(_FRESH_SQL, (CALENDAR_FRESH_HOURS, municipality["id"]))
        fresh = cur.fetchone()
        if fresh is None or not fresh["fresh"]:
            log.warning(
                "non_meetings %s: the sitemap's event pages were not all read in the last %d hours,"
                " or no event is stored; nothing is hidden",
                slug, CALENDAR_FRESH_HOURS,
            )
            return [], []
        cur.execute(_EVENTS_SQL, (municipality["id"],))
        event_days = {_event_date(ev) for ev in cur.fetchall() if classify_event(ev["title"]) is not None}
        cur.execute(
            _ROWS_SQL,
            (municipality["id"], _as_date(complete_from), today - timedelta(days=HIDE_AFTER_DAYS)),
        )
        rows = [dict(r) for r in cur.fetchall()]

    to_hide: list[dict] = []
    held_back: list[dict] = []
    for row in rows:
        if classify_title(row["title"]) != _GENERIC or is_cancelled_title(row["title"]):
            continue
        if _as_date(row["meeting_date"]) in event_days:
            continue
        low_speech = row["transcript_status"] == "low_speech"
        short = row["duration_s"] is not None and row["duration_s"] < SHORT_CLIP_S
        if not (short or low_speech):
            continue
        row["city_slug"] = slug
        row["city_name"] = municipality.get("name")
        if row["transcript_uploaded_at"] is not None and not low_speech:
            held_back.append(row)
        else:
            to_hide.append(row)
    return to_hide, held_back


def _today() -> date:
    return datetime.now(ZoneInfo(config.WORKER_TIMEZONE)).date()


def find_all(today: date | None = None) -> dict[str, tuple[list[dict], list[dict]]]:
    """:func:`find` for every active city whose metadata carries ``calendar_complete_from``, by slug.

    A city whose read fails is logged and left out; it does not block the others.
    """
    today = today or _today()
    with db_cursor() as cur:
        cur.execute(_CITIES_SQL)
        cities = [dict(c) for c in cur.fetchall()]
    found: dict[str, tuple[list[dict], list[dict]]] = {}
    for city in cities:
        try:
            found[city["slug"]] = find(city, today)
        except Exception:
            log.exception("non_meetings: %s failed", city["slug"])
    return found


def held_back(today: date | None = None) -> list[dict]:
    """Every city's held-back clips, for the admin's hidden-meetings page."""
    return [row for _, held in find_all(today).values() for row in held]


def hide_non_meetings(*, dry_run: bool = False, today: date | None = None) -> dict[str, tuple[list[int], list[int]]]:
    """Hide each city's clips that are not meetings; returns, by slug, the ids hidden and the ids held back.

    One ``UPDATE`` per city. With ``dry_run`` nothing is written and the
    first list is the ids that would be hidden. ``today`` defaults to the
    worker's date and exists for the tests.
    """
    result: dict[str, tuple[list[int], list[int]]] = {}
    for slug, (to_hide, held) in find_all(today).items():
        ids = [r["id"] for r in to_hide]
        if ids and not dry_run:
            with db() as conn, conn.cursor() as cur:
                cur.execute(_HIDE_SQL, (ids,))
                ids = sorted(r[0] for r in cur.fetchall())
        result[slug] = (ids, [r["id"] for r in held])
    return result
