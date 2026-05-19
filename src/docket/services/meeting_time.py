"""Single source of truth for the upcoming-vs-prior transition rule.

A meeting is "upcoming" until ``meeting_date + COALESCE(start_time, 12:00)
+ 3 hours`` has passed in America/Chicago wall time.

NULL ``start_time`` falls back to noon CT, so the effective cutoff for
meetings whose time we haven't captured yet is 3:00pm CT on the meeting day.
Granicus + CivicClerk adapters do capture times; Generic CMS / Homewood
does not and will use the fallback.

The transition rule is mirrored in two places:
- :func:`is_upcoming` — Python, used at request time by the Jinja
  ``is_upcoming(meeting)`` global.
- :data:`UPCOMING_PREDICATE_SQL` — SQL fragment that will be interpolated
  into :mod:`docket.services.query` to filter ``list_upcoming_meetings`` /
  ``list_recent_meetings`` so the database does the same arithmetic.
  (Wiring lands alongside this helper in the same PR.)

Keep both definitions in sync. The integration test in
``tests/integration/test_upcoming_transition.py`` exercises them
against the same set of cases.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

_CHICAGO = ZoneInfo("America/Chicago")
_FALLBACK_START = time(12, 0)
_BUFFER = timedelta(hours=3)


def is_upcoming(
    meeting_date: date | None,
    start_time: time | None,
    now: datetime | None = None,
) -> bool:
    """Return True iff the meeting has not yet hit its transition moment.

    The transition moment is ``meeting_date + start_time + 3h`` in CT.
    ``start_time`` of None is treated as noon CT (so transition = 3pm CT).

    A naive ``now`` is assumed to be CT wall time, not UTC. Prefer passing
    a tz-aware datetime.
    """
    if meeting_date is None:
        return False
    if now is None:
        now = datetime.now(_CHICAGO)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=_CHICAGO)

    start = start_time or _FALLBACK_START
    transition_naive = datetime.combine(meeting_date, start)
    transition = transition_naive.replace(tzinfo=_CHICAGO) + _BUFFER
    return now < transition


# SQL mirror. Predicate evaluates TRUE for upcoming rows.
#
# Both ``meeting_date`` (DATE) and ``start_time`` (TIME) are CT-anchored
# local types. Combine with COALESCE(start_time, '12:00'::time), add 3h,
# compare to NOW() converted to a CT naive timestamp via AT TIME ZONE.
UPCOMING_PREDICATE_SQL = """
    (meeting_date::timestamp
     + COALESCE(start_time, TIME '12:00')
     + INTERVAL '3 hours')
    > (NOW() AT TIME ZONE 'America/Chicago')
"""
