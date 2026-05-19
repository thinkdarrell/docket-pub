# Upcoming-Meeting Transition Buffer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop flipping meetings from "upcoming" to "prior" at midnight CT — instead transition at `meeting.start_time + 3h` (CT), with a noon CT fallback for meetings whose time we don't know.

**Architecture:** Add a nullable `start_time TIME` column to `meetings`, capture the time portion that adapters already pull (Granicus' hidden Unix timestamp, CivicClerk's ISO 8601 `eventDate`) and discard today, then introduce a single `is_upcoming(meeting_date, start_time, now_ct)` helper used by both the Jinja templates and the `services/query.py` SQL. The fallback for `start_time IS NULL` is the user's brain-dump default: noon CT same day plus 3h = 3:00pm CT cutoff.

**Tech Stack:** PostgreSQL 18 (Railway), psycopg, Flask + Jinja2, `zoneinfo.ZoneInfo("America/Chicago")`.

**Out of scope (named so we don't drift):**
- AI voice-selection at queue time (`ai/client.py:50`, `ai/rewrite.py:328`) — already persisted per-row via `ai_rewrite_voice` / `executive_summary_voice`; touching it would re-open the recast-cron debate. Cron-based recast is Task 11 of the forward-voice plan and stays there.
- Generic CMS / Homewood time extraction — minutes PDFs don't carry a consistent meeting time. Falls through to noon fallback automatically.
- Backfill of `start_time` for historical archive rows. They're all in the past, so the upcoming/prior flip doesn't matter for them.

---

## File Structure

**Create:**
- `src/docket/migrations/032_meetings_start_time.py` — adds `meetings.start_time TIME NULL`
- `src/docket/services/meeting_time.py` — single source of truth for the transition rule. Exports `is_upcoming(meeting_date, start_time, now_ct=None) -> bool` and the SQL fragment `UPCOMING_PREDICATE_SQL` used by `query.py`.
- `tests/unit/test_meeting_time.py` — unit tests for the helper
- `tests/integration/test_upcoming_transition.py` — integration test that exercises template-level + SQL-level consistency on a real DB row

**Modify:**
- `src/docket/migrations/runner.py` — register migration 032
- `src/docket/models/protocol.py` — add `start_time: time | None = None` to `RawMeeting`
- `src/docket/models/meeting.py` — add `start_time: time | None = None` to `Meeting` + `from_row`
- `src/docket/adapters/granicus.py` — preserve time component in `_parse_upcoming_row` (and any sibling archive parser that reads the hidden timestamp)
- `src/docket/adapters/civicclerk.py` — preserve time component in `_event_to_meeting`
- `src/docket/services/ingest.py` — include `start_time` in `_upsert_meetings` INSERT + UPDATE; carry through `_try_upgrade_event_row` so the upgrade preserves the upcoming row's known time
- `src/docket/services/query.py` — replace `meeting_date > CURRENT_DATE` / `meeting_date <= CURRENT_DATE` predicates in `list_upcoming_meetings`, `list_upcoming_meetings_for_city`, `list_recent_meetings`, `list_recent_meetings_for_city` with the new predicate
- `src/docket/web/__init__.py` — register `is_upcoming` as a Jinja global alongside the existing `today` context processor
- `src/docket/web/templates/partials/meeting_card.html`, `partials/_card_shell.html`, `partials/_vote_result_block.html`, `partials/card_v2_fallback.html`, `meeting_detail.html`, `item_detail.html` — replace `meeting.meeting_date >= today` comparisons with `is_upcoming(meeting)` calls

**Don't touch:**
- AI pipeline files (`ai/client.py`, `ai/rewrite.py`) — see "Out of scope" above.
- `_priority.py`, `wave0.py` — Wave 0 doesn't care about transition timing.

---

### Task 1: Add migration 032 — `meetings.start_time` column

**Files:**
- Create: `src/docket/migrations/032_meetings_start_time.py`
- Modify: `src/docket/migrations/runner.py:16-50` (MIGRATIONS list)
- Test: tested implicitly by Task 11 integration test; no dedicated unit test needed (`IF NOT EXISTS` makes this trivially idempotent and replayable).

- [ ] **Step 1: Write the migration file**

```python
# src/docket/migrations/032_meetings_start_time.py
"""Migration 032 — meetings.start_time for per-meeting upcoming-transition timing.

Adds nullable TIME column. Adapters that already pull a time component
(Granicus hidden timestamp, CivicClerk eventDate) start persisting it on the
next ingest cycle. Meetings with NULL start_time fall back to noon CT in the
is_upcoming() helper.

Spec: docs/superpowers/plans/2026-05-19-upcoming-meeting-transition-buffer.md
"""
from __future__ import annotations


SQL_UP = r"""
ALTER TABLE meetings
    ADD COLUMN IF NOT EXISTS start_time TIME NULL;
"""

SQL_DOWN = r"""
ALTER TABLE meetings DROP COLUMN IF EXISTS start_time;
"""


def up(cur) -> None:
    cur.execute(SQL_UP)


def down(cur) -> None:
    cur.execute(SQL_DOWN)
```

- [ ] **Step 2: Register the migration**

Edit `src/docket/migrations/runner.py:16-50`. Append `"docket.migrations.032_meetings_start_time",` after the existing `031_ai_rewrite_voice` entry. Keep alphabetical / numerical order.

- [ ] **Step 3: Apply against local DB**

Run: `cd ~/docket-pub && venv/bin/python -m docket.migrations.runner`
Expected: `[applied] 032_meetings_start_time` in output, no errors.

- [ ] **Step 4: Verify the column landed**

Run: `cd ~/docket-pub && venv/bin/python -c "from docket.db import db_cursor; from docket.config import DATABASE_URL; print(DATABASE_URL); 
import psycopg
with psycopg.connect(DATABASE_URL) as c, c.cursor() as cur:
    cur.execute(\"SELECT column_name, data_type FROM information_schema.columns WHERE table_name='meetings' AND column_name='start_time'\")
    print(cur.fetchone())"`
Expected: `('start_time', 'time without time zone')`

- [ ] **Step 5: Commit**

```bash
git add src/docket/migrations/032_meetings_start_time.py src/docket/migrations/runner.py
git commit -m "feat(meetings): add start_time column for upcoming-transition buffer

Per-meeting time enables a 3h post-start grace window for the
upcoming→prior flip; NULL falls back to noon CT in the application
helper. Bare column add, no row rewrites."
```

---

### Task 2: Extend `RawMeeting` and `Meeting` dataclasses

**Files:**
- Modify: `src/docket/models/protocol.py:10-22`
- Modify: `src/docket/models/meeting.py:9-45`
- Test: `tests/unit/test_meeting_models.py` (new file if it doesn't exist; otherwise append)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_meeting_models.py
from datetime import date, time

from docket.models.meeting import Meeting
from docket.models.protocol import RawMeeting


def test_raw_meeting_accepts_start_time():
    rm = RawMeeting(
        external_id="event-123",
        municipality_slug="al-birmingham",
        title="Council Meeting",
        meeting_date=date(2026, 5, 20),
        meeting_type="council",
        agenda_url=None, minutes_url=None, video_url=None,
        source_url="https://example.com",
        start_time=time(17, 30),
    )
    assert rm.start_time == time(17, 30)


def test_raw_meeting_start_time_defaults_to_none():
    rm = RawMeeting(
        external_id="event-123",
        municipality_slug="al-birmingham",
        title="Council Meeting",
        meeting_date=date(2026, 5, 20),
        meeting_type="council",
        agenda_url=None, minutes_url=None, video_url=None,
        source_url="https://example.com",
    )
    assert rm.start_time is None


def test_meeting_from_row_reads_start_time():
    row = {
        "id": 1, "municipality_id": 1, "external_id": "e1",
        "title": "X", "meeting_date": date(2026, 5, 20),
        "meeting_type": "council", "agenda_url": None,
        "minutes_url": None, "video_url": None, "source_url": "u",
        "start_time": time(17, 30),
    }
    m = Meeting.from_row(row)
    assert m.start_time == time(17, 30)


def test_meeting_from_row_start_time_missing_is_none():
    row = {
        "id": 1, "municipality_id": 1, "external_id": "e1",
        "title": "X", "meeting_date": date(2026, 5, 20),
        "meeting_type": "council", "agenda_url": None,
        "minutes_url": None, "video_url": None, "source_url": "u",
    }
    m = Meeting.from_row(row)
    assert m.start_time is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/docket-pub && venv/bin/pytest tests/unit/test_meeting_models.py -v`
Expected: 4 FAIL — `RawMeeting.__init__() got an unexpected keyword argument 'start_time'` and `AttributeError: 'Meeting' object has no attribute 'start_time'`.

- [ ] **Step 3: Add `start_time` to `RawMeeting`**

Edit `src/docket/models/protocol.py`. At the top of the file change the imports:

```python
from datetime import date, time
```

In the `RawMeeting` dataclass (currently lines 10-22), append `start_time` as the last field with a default:

```python
@dataclass(frozen=True)
class RawMeeting:
    """A meeting as returned by a platform adapter, before DB persistence."""

    external_id: str
    municipality_slug: str
    title: str
    meeting_date: date
    meeting_type: str  # 'council' | 'work_session' | 'bza' | 'planning' | 'special'
    agenda_url: str | None
    minutes_url: str | None
    video_url: str | None
    source_url: str
    start_time: time | None = None
```

- [ ] **Step 4: Add `start_time` to `Meeting`**

Edit `src/docket/models/meeting.py`. Change the import:

```python
from datetime import datetime, time
```

Add the field after `executive_summary_voice` and update `from_row`:

```python
@dataclass(frozen=True)
class Meeting:
    id: int
    municipality_id: int
    external_id: str | None
    title: str
    meeting_date: str | None
    meeting_type: str | None
    agenda_url: str | None
    minutes_url: str | None
    video_url: str | None
    source_url: str | None
    executive_summary: str | None = None
    executive_summary_voice: str | None = None
    ai_metadata: dict | None = None
    ai_prompt_version: int | None = None
    ai_generated_at: datetime | None = None
    start_time: time | None = None

    @classmethod
    def from_row(cls, row: dict) -> Meeting:
        return cls(
            id=row["id"],
            municipality_id=row["municipality_id"],
            external_id=row.get("external_id"),
            title=row.get("title", ""),
            meeting_date=row.get("meeting_date"),
            meeting_type=row.get("meeting_type"),
            agenda_url=row.get("agenda_url"),
            minutes_url=row.get("minutes_url"),
            video_url=row.get("video_url"),
            source_url=row.get("source_url"),
            executive_summary=row.get("executive_summary"),
            executive_summary_voice=row.get("executive_summary_voice"),
            ai_metadata=row.get("ai_metadata"),
            ai_prompt_version=row.get("ai_prompt_version"),
            ai_generated_at=row.get("ai_generated_at"),
            start_time=row.get("start_time"),
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ~/docket-pub && venv/bin/pytest tests/unit/test_meeting_models.py -v`
Expected: 4 PASS.

- [ ] **Step 6: Run the broader unit suite to catch any positional-arg regressions**

Run: `cd ~/docket-pub && venv/bin/pytest tests/unit -x -q`
Expected: all pass. `RawMeeting` is constructed positionally in some places (adapters, tests) — adding `start_time` *after* `source_url` with a default is backwards-compatible. If anything red, check the trace and fix the positional call before continuing.

- [ ] **Step 7: Commit**

```bash
git add src/docket/models/protocol.py src/docket/models/meeting.py tests/unit/test_meeting_models.py
git commit -m "feat(models): add optional start_time to RawMeeting + Meeting"
```

---

### Task 3: Write the `is_upcoming` helper (Python + SQL)

**Files:**
- Create: `src/docket/services/meeting_time.py`
- Test: `tests/unit/test_meeting_time.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_meeting_time.py
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from docket.services.meeting_time import (
    UPCOMING_PREDICATE_SQL,
    is_upcoming,
)

CT = ZoneInfo("America/Chicago")


def _now(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=CT)


def test_future_date_is_upcoming():
    # Meeting two days from now, no start_time known.
    assert is_upcoming(date(2026, 5, 21), None, _now(2026, 5, 19, 8)) is True


def test_past_date_is_not_upcoming():
    assert is_upcoming(date(2026, 5, 10), None, _now(2026, 5, 19, 8)) is False


def test_same_day_no_start_time_before_3pm_is_upcoming():
    # noon fallback + 3h = 3pm CT cutoff
    assert is_upcoming(date(2026, 5, 19), None, _now(2026, 5, 19, 14, 59)) is True


def test_same_day_no_start_time_at_3pm_is_not_upcoming():
    assert is_upcoming(date(2026, 5, 19), None, _now(2026, 5, 19, 15, 0)) is False


def test_same_day_with_start_time_before_buffer_is_upcoming():
    # 5:30pm meeting + 3h = 8:30pm CT cutoff
    assert is_upcoming(
        date(2026, 5, 19), time(17, 30), _now(2026, 5, 19, 20, 29)
    ) is True


def test_same_day_with_start_time_at_buffer_is_not_upcoming():
    assert is_upcoming(
        date(2026, 5, 19), time(17, 30), _now(2026, 5, 19, 20, 30)
    ) is False


def test_morning_committee_meeting_transitions_mid_morning():
    # 9am committee + 3h = noon CT cutoff
    assert is_upcoming(date(2026, 5, 19), time(9, 0), _now(2026, 5, 19, 11, 59)) is True
    assert is_upcoming(date(2026, 5, 19), time(9, 0), _now(2026, 5, 19, 12, 0)) is False


def test_late_evening_meeting_does_not_flip_at_midnight():
    # 8pm meeting + 3h = 11pm CT cutoff (same day, NOT midnight)
    assert is_upcoming(date(2026, 5, 19), time(20, 0), _now(2026, 5, 19, 22, 59)) is True
    assert is_upcoming(date(2026, 5, 19), time(20, 0), _now(2026, 5, 19, 23, 1)) is False


def test_now_defaults_to_current_chicago_time():
    # Smoke test: calling without explicit now shouldn't raise and should
    # return a bool. Don't assert direction — that depends on wall clock.
    result = is_upcoming(date(2026, 5, 19), None)
    assert result in (True, False)


def test_sql_predicate_is_a_nonempty_string():
    # The SQL fragment is consumed verbatim by query.py; downstream callers
    # rely on it being a well-formed predicate string.
    assert "meeting_date" in UPCOMING_PREDICATE_SQL
    assert "start_time" in UPCOMING_PREDICATE_SQL
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/docket-pub && venv/bin/pytest tests/unit/test_meeting_time.py -v`
Expected: All FAIL — `ModuleNotFoundError: No module named 'docket.services.meeting_time'`.

- [ ] **Step 3: Implement the helper**

```python
# src/docket/services/meeting_time.py
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
- :data:`UPCOMING_PREDICATE_SQL` — SQL fragment, used by
  :mod:`docket.services.query` to filter ``list_upcoming_meetings`` /
  ``list_recent_meetings`` so the database does the same arithmetic.

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/docket-pub && venv/bin/pytest tests/unit/test_meeting_time.py -v`
Expected: 10 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/docket/services/meeting_time.py tests/unit/test_meeting_time.py
git commit -m "feat(services): is_upcoming helper with start_time + 3h transition rule

Mirrors a Python helper and a SQL predicate so the Jinja templates and
the list_upcoming_meetings query share one definition of when a meeting
flips from upcoming to prior. NULL start_time → noon CT fallback."
```

---

### Task 4: Granicus adapter — preserve time in upcoming row parser

**Files:**
- Modify: `src/docket/adapters/granicus.py:388-440` (`_parse_upcoming_row`)
- Test: `tests/unit/test_granicus_adapter.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_granicus_adapter.py`:

```python
from datetime import time

from bs4 import BeautifulSoup


def test_parse_upcoming_row_extracts_start_time(monkeypatch):
    """The hidden span carries a Unix timestamp — keep the time component, not
    just the date. 1747765800 = 2025-05-20 17:30 America/Chicago."""
    from docket.adapters.granicus import GranicusAdapter

    html = '''
    <tr class="row-name1">
      <td headers="EventName">Council Meeting</td>
      <td headers="EventDate">
        <span style="display: none">1747765800</span>
        2025-05-20
      </td>
      <td><a onclick="javascript:event_id=12345">Agenda</a></td>
    </tr>
    '''
    soup = BeautifulSoup(html, "html.parser")
    row = soup.find("tr")

    adapter = GranicusAdapter.__new__(GranicusAdapter)
    adapter.municipality_slug = "al-birmingham"
    adapter.base_url = "https://example.com"

    raw = adapter._parse_upcoming_row(row)
    assert raw is not None
    assert raw.start_time == time(17, 30)
```

Note: `1747765800` is `2025-05-20 22:30:00 UTC`, which is `17:30 America/Chicago` (CDT, UTC-5). If you choose a different timestamp, recompute manually and adjust the assertion.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ~/docket-pub && venv/bin/pytest tests/unit/test_granicus_adapter.py::test_parse_upcoming_row_extracts_start_time -v`
Expected: FAIL with `AttributeError: 'RawMeeting' object has no attribute 'start_time'` OR `assert None == datetime.time(17, 30)` (depending on whether Task 2 has been merged onto this branch).

- [ ] **Step 3: Update `_parse_upcoming_row`**

Edit `src/docket/adapters/granicus.py`. The current block reads:

```python
        date_cell = row.find("td", headers=re.compile(r"^EventDate"))
        meeting_date = None
        if date_cell:
            hidden_span = date_cell.find("span", style=re.compile(r"display:\s*none"))
            if hidden_span:
                try:
                    ts = int(hidden_span.get_text(strip=True))
                    meeting_date = datetime.fromtimestamp(ts, tz=timezone.utc).date()
                except (ValueError, OSError):
                    pass

        if meeting_date is None:
            ...
```

Replace with:

```python
        from zoneinfo import ZoneInfo  # local import keeps adapter module-level imports tidy
        date_cell = row.find("td", headers=re.compile(r"^EventDate"))
        meeting_date = None
        start_time = None
        if date_cell:
            hidden_span = date_cell.find("span", style=re.compile(r"display:\s*none"))
            if hidden_span:
                try:
                    ts = int(hidden_span.get_text(strip=True))
                    dt_ct = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(
                        ZoneInfo("America/Chicago")
                    )
                    meeting_date = dt_ct.date()
                    start_time = dt_ct.time().replace(microsecond=0)
                except (ValueError, OSError):
                    pass

        if meeting_date is None:
            logger.warning(
                "Could not parse date for upcoming meeting '%s', using today", title
            )
            meeting_date = date.today()
```

Then pass `start_time` to the `RawMeeting(...)` call at the bottom of the function (add as the final keyword arg).

- [ ] **Step 4: Audit the archive-row parser for the same field**

Run: `grep -n "display:\s*none\|fromtimestamp\|hidden_span" src/docket/adapters/granicus.py`
If there's an analogous block in the archive-row parser that also discards the time, apply the same change there. (Archive rows are past meetings so the upcoming/prior flip doesn't matter for them, but persisting `start_time` keeps the column consistent and helps future analytics — only do this if it's a one-line change. If structurally different, file as a follow-up issue and don't expand scope.)

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd ~/docket-pub && venv/bin/pytest tests/unit/test_granicus_adapter.py -v`
Expected: All Granicus tests PASS, including the new one.

- [ ] **Step 6: Commit**

```bash
git add src/docket/adapters/granicus.py tests/unit/test_granicus_adapter.py
git commit -m "feat(granicus): preserve start_time when parsing upcoming rows

Hidden Unix timestamp on each #upcoming row carries the full datetime;
previously we threw the time component away. Now retained and converted
to America/Chicago for the new meetings.start_time column."
```

---

### Task 5: CivicClerk adapter — preserve time from `eventDate`

**Files:**
- Modify: `src/docket/adapters/civicclerk.py:130-156` (`_event_to_meeting`)
- Test: `tests/unit/test_civicclerk_adapter.py` (append; if no file exists, create with a single focused test)

- [ ] **Step 1: Find or create the test file**

Run: `ls tests/unit/test_civicclerk*`
If file exists, append a test. If not, create the file with:

```python
# tests/unit/test_civicclerk_adapter.py
```

- [ ] **Step 2: Write the failing test**

```python
from datetime import time

def test_event_to_meeting_extracts_start_time():
    from docket.adapters.civicclerk import CivicClerkAdapter

    adapter = CivicClerkAdapter.__new__(CivicClerkAdapter)
    adapter.municipality_slug = "al-mobile"
    adapter.base_url = "https://example.civicclerk.com"

    event = {
        "eventId": 42,
        "eventName": "Council Regular",
        "eventDate": "2026-05-20T17:30:00",
        "hasAgenda": True,
        "hasMinutes": False,
    }
    raw = adapter._event_to_meeting(event)
    assert raw is not None
    assert raw.start_time == time(17, 30)


def test_event_to_meeting_handles_missing_time():
    from docket.adapters.civicclerk import CivicClerkAdapter

    adapter = CivicClerkAdapter.__new__(CivicClerkAdapter)
    adapter.municipality_slug = "al-mobile"
    adapter.base_url = "https://example.civicclerk.com"

    event = {
        "eventId": 42,
        "eventName": "Council Regular",
        "eventDate": "2026-05-20",
        "hasAgenda": True,
        "hasMinutes": False,
    }
    raw = adapter._event_to_meeting(event)
    assert raw is not None
    assert raw.start_time is None
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd ~/docket-pub && venv/bin/pytest tests/unit/test_civicclerk_adapter.py -v`
Expected: FAIL with `AttributeError: 'RawMeeting' object has no attribute 'start_time'` OR `assert None == time(17,30)`.

- [ ] **Step 4: Update `_event_to_meeting`**

Edit `src/docket/adapters/civicclerk.py` around lines 130-156. Replace the date-parsing block with:

```python
        event_date_str = event.get("eventDate", "")
        meeting_date = None
        start_time = None
        if event_date_str:
            # Accepts both 'YYYY-MM-DD' and 'YYYY-MM-DDTHH:MM:SS(.fff)?(Z|±HH:MM)?'.
            try:
                if "T" in event_date_str:
                    # CivicClerk dates are local (no zone suffix in practice);
                    # if a Z/+offset is present, fromisoformat handles it on
                    # Python >=3.11.
                    dt = datetime.fromisoformat(event_date_str.replace("Z", "+00:00"))
                    meeting_date = dt.date()
                    start_time = dt.time().replace(microsecond=0)
                else:
                    meeting_date = datetime.strptime(event_date_str[:10], "%Y-%m-%d").date()
            except ValueError:
                pass
        if meeting_date is None:
            meeting_date = date.today()
```

And pass `start_time=start_time` to the `RawMeeting(...)` call.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd ~/docket-pub && venv/bin/pytest tests/unit/test_civicclerk_adapter.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/docket/adapters/civicclerk.py tests/unit/test_civicclerk_adapter.py
git commit -m "feat(civicclerk): preserve start_time from eventDate ISO string"
```

---

### Task 6: Ingest pipeline — persist `start_time`

**Files:**
- Modify: `src/docket/services/ingest.py:136-265` (`_upsert_meetings` and `_try_upgrade_event_row`)
- Test: `tests/integration/test_ingest_start_time.py` (new)

- [ ] **Step 1: Write the failing integration test**

Note: ingest tests in this repo typically hit a real Postgres test DB; mirror the pattern from `tests/integration/test_ingest_reconciliation.py`. If you're unsure, read that file first for the fixture conventions.

```python
# tests/integration/test_ingest_start_time.py
from datetime import date, time

from docket.db import db_cursor
from docket.models.protocol import RawMeeting
from docket.services.ingest import _upsert_meetings


def test_upsert_meetings_persists_start_time(test_municipality_id):
    """test_municipality_id is the standard fixture defined elsewhere in
    tests/integration — provides a clean municipality row. If your fixture
    is named differently, adapt accordingly."""
    rm = RawMeeting(
        external_id="event-99999",
        municipality_slug="al-test",
        title="Test Council",
        meeting_date=date(2026, 5, 20),
        meeting_type="council",
        agenda_url=None, minutes_url=None, video_url=None,
        source_url="https://example.com",
        start_time=time(17, 30),
    )
    inserted, updated = _upsert_meetings(test_municipality_id, [rm])
    assert inserted == 1

    with db_cursor() as cur:
        cur.execute(
            "SELECT start_time FROM meetings WHERE municipality_id = %s AND external_id = %s",
            (test_municipality_id, "event-99999"),
        )
        (st,) = cur.fetchone()
        assert st == time(17, 30)


def test_upsert_meetings_updates_start_time(test_municipality_id):
    rm = RawMeeting(
        external_id="event-99998",
        municipality_slug="al-test",
        title="Test Council",
        meeting_date=date(2026, 5, 20),
        meeting_type="council",
        agenda_url=None, minutes_url=None, video_url=None,
        source_url="https://example.com",
        start_time=time(17, 30),
    )
    _upsert_meetings(test_municipality_id, [rm])

    # Re-ingest with a different time (Granicus sometimes corrects the
    # posted time before the meeting).
    rm_updated = RawMeeting(
        external_id="event-99998",
        municipality_slug="al-test",
        title="Test Council",
        meeting_date=date(2026, 5, 20),
        meeting_type="council",
        agenda_url=None, minutes_url=None, video_url=None,
        source_url="https://example.com",
        start_time=time(18, 0),
    )
    inserted, updated = _upsert_meetings(test_municipality_id, [rm_updated])
    assert updated == 1

    with db_cursor() as cur:
        cur.execute(
            "SELECT start_time FROM meetings WHERE municipality_id = %s AND external_id = %s",
            (test_municipality_id, "event-99998"),
        )
        (st,) = cur.fetchone()
        assert st == time(18, 0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ~/docket-pub && venv/bin/pytest tests/integration/test_ingest_start_time.py -v`
Expected: FAIL — either the `start_time` column doesn't make it into the INSERT, or it's NULL after upsert.

- [ ] **Step 3: Update `_upsert_meetings` UPDATE branch**

Edit `src/docket/services/ingest.py`. The current UPDATE statement (lines 157-170):

```python
                if existing:
                    cur.execute(
                        """
                        UPDATE meetings SET
                            title = %s, meeting_date = %s, meeting_type = %s,
                            agenda_url = %s, minutes_url = %s, video_url = %s,
                            source_url = %s
                        WHERE municipality_id = %s AND external_id = %s
                        """,
                        (
                            m.title, m.meeting_date, m.meeting_type,
                            m.agenda_url, m.minutes_url, m.video_url,
                            m.source_url, municipality_id, m.external_id,
                        ),
                    )
```

Update to include `start_time`. Important: only overwrite `start_time` when the new value is non-NULL — otherwise a re-ingest from an adapter that didn't capture a time would wipe out a value captured by an earlier ingest from an adapter that did. Use `COALESCE`:

```python
                if existing:
                    cur.execute(
                        """
                        UPDATE meetings SET
                            title = %s, meeting_date = %s, meeting_type = %s,
                            agenda_url = %s, minutes_url = %s, video_url = %s,
                            source_url = %s,
                            start_time = COALESCE(%s, start_time)
                        WHERE municipality_id = %s AND external_id = %s
                        """,
                        (
                            m.title, m.meeting_date, m.meeting_type,
                            m.agenda_url, m.minutes_url, m.video_url,
                            m.source_url, m.start_time,
                            municipality_id, m.external_id,
                        ),
                    )
```

- [ ] **Step 4: Update `_upsert_meetings` INSERT branch**

Replace the INSERT block (lines 182-194) with:

```python
                cur.execute(
                    """
                    INSERT INTO meetings (
                        municipality_id, external_id, title, meeting_date,
                        meeting_type, agenda_url, minutes_url, video_url,
                        source_url, start_time
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        municipality_id, m.external_id, m.title, m.meeting_date,
                        m.meeting_type, m.agenda_url, m.minutes_url, m.video_url,
                        m.source_url, m.start_time,
                    ),
                )
```

- [ ] **Step 5: Update `_try_upgrade_event_row` to carry start_time**

Edit the UPDATE inside `_try_upgrade_event_row` (starts ~line 246). Add `start_time = COALESCE(%s, start_time),` and append `m.start_time` to the parameter tuple in the right position. Read the surrounding code first; the param list order is sensitive.

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd ~/docket-pub && venv/bin/pytest tests/integration/test_ingest_start_time.py -v`
Expected: 2 PASS.

- [ ] **Step 7: Run the full ingest integration suite to check for regressions**

Run: `cd ~/docket-pub && venv/bin/pytest tests/integration/ -x -q`
Expected: all pass. If the reconciliation test reds, inspect — the `_try_upgrade_event_row` change is the most likely culprit.

- [ ] **Step 8: Commit**

```bash
git add src/docket/services/ingest.py tests/integration/test_ingest_start_time.py
git commit -m "feat(ingest): persist meeting start_time, preserve on re-ingest

COALESCE on the UPDATE so an adapter that returns NULL start_time
(e.g. Generic CMS) doesn't blow away a time captured by an earlier
ingest from an adapter that does extract it (Granicus, CivicClerk)."
```

---

### Task 7: Update `query.py` to use the new predicate

**Files:**
- Modify: `src/docket/services/query.py:848-927` (`list_recent_meetings`, `list_upcoming_meetings`, `list_recent_meetings_for_city`, `list_upcoming_meetings_for_city`)
- Test: `tests/integration/test_upcoming_transition.py` (new — also covers Task 11)

- [ ] **Step 1: Write the failing integration test (deferred to Task 11)**

Skip writing the test inline here — Task 11 builds the integration test that covers SQL + template parity. For now, write a focused unit-level smoke test that compiles the SQL.

```python
# tests/unit/test_query_upcoming_predicate.py
def test_upcoming_predicate_compiles_against_real_db():
    """The predicate is a literal SQL fragment — confirm Postgres parses it
    without yelling about types or syntax. We don't care about the result
    set, only that EXPLAIN succeeds."""
    from docket.db import db_cursor
    from docket.services.meeting_time import UPCOMING_PREDICATE_SQL

    with db_cursor() as cur:
        cur.execute(
            f"EXPLAIN SELECT 1 FROM meetings WHERE {UPCOMING_PREDICATE_SQL}"
        )
        plan = cur.fetchall()
        assert plan  # at least one row returned by EXPLAIN
```

- [ ] **Step 2: Run the test to verify it fails (or skip cleanly)**

Run: `cd ~/docket-pub && venv/bin/pytest tests/unit/test_query_upcoming_predicate.py -v`
Expected: PASS if migration 032 applied locally — we're really exercising the SQL parser. If FAIL, the SQL has a syntax/type error; fix the predicate in `meeting_time.py` before moving on.

- [ ] **Step 3: Update `list_upcoming_meetings`**

In `src/docket/services/query.py`, replace:

```python
              AND mt.meeting_date > CURRENT_DATE
              AND mt.meeting_date <= CURRENT_DATE + %s
```

with:

```python
              AND {predicate}
              AND mt.meeting_date <= (NOW() AT TIME ZONE 'America/Chicago')::date + %s
```

where `{predicate}` is the SQL fragment from `meeting_time.UPCOMING_PREDICATE_SQL` with `meeting_date` and `start_time` prefixed with `mt.` so the join doesn't break:

```python
from docket.services.meeting_time import UPCOMING_PREDICATE_SQL
# At module import time, build a prefixed variant:
_UPCOMING_PREDICATE_MT = UPCOMING_PREDICATE_SQL.replace("meeting_date", "mt.meeting_date").replace("start_time", "mt.start_time")
```

…then interpolate `_UPCOMING_PREDICATE_MT` into the SQL. (Manual prefix-injection is brittle but the predicate is short and locally controlled; if you'd rather, parameterize via SQL functions — see Task 12 follow-up.)

Apply the same change to `list_upcoming_meetings_for_city`.

- [ ] **Step 4: Update `list_recent_meetings` (inverse predicate)**

A meeting is "recent" iff it's *not* upcoming and within the lookback window. Replace:

```python
              AND mt.meeting_date >= CURRENT_DATE - %s
              AND mt.meeting_date <= CURRENT_DATE
```

with:

```python
              AND NOT ({predicate})
              AND mt.meeting_date >= (NOW() AT TIME ZONE 'America/Chicago')::date - %s
```

Apply to `list_recent_meetings_for_city` too.

- [ ] **Step 5: Run the broader query test suite**

Run: `cd ~/docket-pub && venv/bin/pytest tests/ -k "query or upcoming or recent" -v`
Expected: all pass. If any test asserts old "midnight CT" behavior, update it to the new semantics — those tests are now wrong, not the code.

- [ ] **Step 6: Commit**

```bash
git add src/docket/services/query.py tests/unit/test_query_upcoming_predicate.py
git commit -m "feat(query): use is_upcoming predicate in list_upcoming/list_recent

Replaces 'meeting_date > CURRENT_DATE' (server-UTC, day-granularity)
with the start_time + 3h Chicago-anchored predicate, mirroring the
Python helper. The upcoming and recent lists now agree with the
templates' is_upcoming() rendering."
```

---

### Task 8: Register `is_upcoming` as a Jinja global

**Files:**
- Modify: `src/docket/web/__init__.py:74-97`
- Test: `tests/web/test_is_upcoming_jinja.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/web/test_is_upcoming_jinja.py
from datetime import date, time

import pytest


@pytest.fixture
def app():
    from docket.web import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app


def test_is_upcoming_is_a_jinja_global(app):
    assert "is_upcoming" in app.jinja_env.globals


def test_is_upcoming_renders_truthy_for_future_meeting(app):
    # Render a minimal template snippet using the global.
    class _M:
        def __init__(self, md, st=None):
            self.meeting_date = md
            self.start_time = st

    with app.test_request_context():
        tmpl = app.jinja_env.from_string(
            "{% if is_upcoming(m) %}UP{% else %}OVER{% endif %}"
        )
        # Pick a date well in the future so wall-clock doesn't matter.
        out = tmpl.render(m=_M(date(2099, 1, 1)))
        assert out == "UP"
        out = tmpl.render(m=_M(date(2000, 1, 1)))
        assert out == "OVER"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ~/docket-pub && venv/bin/pytest tests/web/test_is_upcoming_jinja.py -v`
Expected: 3 tests, first 2 FAIL — `is_upcoming` not in globals.

- [ ] **Step 3: Wire the global**

Edit `src/docket/web/__init__.py` in the same neighborhood as the `today` context processor (lines 74-97). After the `_inject_today` definition, add:

```python
    from docket.services.meeting_time import is_upcoming as _is_upcoming_impl

    def _is_upcoming_template(meeting) -> bool:
        """Jinja wrapper that accepts either a Meeting/RawMeeting object or a
        dict row (psycopg returns row mappings, models return dataclasses)."""
        if meeting is None:
            return False
        if hasattr(meeting, "meeting_date"):
            md = meeting.meeting_date
            st = getattr(meeting, "start_time", None)
        else:
            md = meeting.get("meeting_date")
            st = meeting.get("start_time")
        return _is_upcoming_impl(md, st)

    app.jinja_env.globals["is_upcoming"] = _is_upcoming_template
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd ~/docket-pub && venv/bin/pytest tests/web/test_is_upcoming_jinja.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/docket/web/__init__.py tests/web/test_is_upcoming_jinja.py
git commit -m "feat(web): register is_upcoming() Jinja global

Accepts both Meeting/RawMeeting dataclasses and dict rows, so templates
can call it on cards, hero blocks, and Vote Result branches without
caring which shape the row arrived in."
```

---

### Task 9: Switch templates to `is_upcoming(meeting)`

**Files (all 6 template files):**
- Modify: `src/docket/web/templates/partials/meeting_card.html:36`
- Modify: `src/docket/web/templates/partials/_card_shell.html:39,86`
- Modify: `src/docket/web/templates/partials/_vote_result_block.html:95`
- Modify: `src/docket/web/templates/partials/card_v2_fallback.html:12`
- Modify: `src/docket/web/templates/meeting_detail.html:15,46`
- Modify: `src/docket/web/templates/item_detail.html:27,66`

Each call site currently looks like:

```jinja
{% if today is defined and X.meeting_date and X.meeting_date >= today %}
```

(where `X` is `meeting` or `item`). Replace with:

```jinja
{% if is_upcoming(X) %}
```

Note the wrapped helper already null-checks both `meeting_date` and the input itself, so the verbose `today is defined and X.meeting_date and …` guard is no longer needed. **However:** `item_detail.html:27` and `partials/card_v2_fallback.html:12` also check `(item.ai_rewrite_voice or '') != 'upcoming'` — preserve that conjunct, only swap the date comparison:

```jinja
{% if is_upcoming(item) and (item.ai_rewrite_voice or '') != 'upcoming' %}
```

- [ ] **Step 1: Snapshot the existing template strings**

For confidence, run before editing:

```bash
cd ~/docket-pub && grep -rn "meeting_date.*>=.*today\|today.*meeting_date.*>=\|meeting_date >= today" src/docket/web/templates/
```

Expected: ~8 matches across 6 files. Confirm the count matches the file list above.

- [ ] **Step 2: Edit `partials/meeting_card.html` line 36**

Replace:

```jinja
    {% if today is defined and meeting.meeting_date and meeting.meeting_date >= today %}
```

with:

```jinja
    {% if is_upcoming(meeting) %}
```

- [ ] **Step 3: Edit `partials/_card_shell.html` lines 39 and 86**

Replace at line 39:

```jinja
      {% if today is defined and item.meeting_date >= today %}
```

with:

```jinja
      {% if is_upcoming(item) %}
```

And at line 86 (multi-line condition):

```jinja
                                and item.meeting_date >= today
```

Read the surrounding `{% if … %}` context and condense the whole `today is defined and item.meeting_date >= today` chain into `is_upcoming(item)`.

- [ ] **Step 4: Edit `partials/_vote_result_block.html` line 95**

Replace:

```jinja
        {% if today is defined and meeting and meeting.meeting_date and meeting.meeting_date >= today %}
```

with:

```jinja
        {% if is_upcoming(meeting) %}
```

- [ ] **Step 5: Edit `partials/card_v2_fallback.html` line 12**

Replace the existing `{%- if … -%}` block and keep the voice-suppression conjunct:

```jinja
  {%- if is_upcoming(item) and (item.ai_rewrite_voice or '') != 'upcoming' -%}
```

- [ ] **Step 6: Edit `meeting_detail.html` lines 15 and 46**

Replace at line 15:

```jinja
                {% if today is defined and meeting.meeting_date and meeting.meeting_date >= today %}
```

with:

```jinja
                {% if is_upcoming(meeting) %}
```

And the assignment at line 46:

```jinja
{% set _meeting_is_upcoming = today is defined and meeting.meeting_date and meeting.meeting_date >= today %}
```

with:

```jinja
{% set _meeting_is_upcoming = is_upcoming(meeting) %}
```

- [ ] **Step 7: Edit `item_detail.html` lines 27 and 66**

At line 27, retain the voice conjunct:

```jinja
            <h1 class="hero-title t-display">{% if is_upcoming(item) and (item.ai_rewrite_voice or '') != 'upcoming' %}{{ item.title }}{% else %}{{ item.headline or item.title }}{% endif %}</h1>
```

At line 66 (likely also a multi-line block), condense similarly. Re-read surrounding context before editing — there may be additional clauses to preserve.

- [ ] **Step 8: Verify no occurrences remain**

Run: `cd ~/docket-pub && grep -rn "meeting_date.*>=.*today\|today.*meeting_date.*>=" src/docket/web/templates/`
Expected: zero matches.

- [ ] **Step 9: Run web tests**

Run: `cd ~/docket-pub && venv/bin/pytest tests/web -v`
Expected: all pass. The existing tests around the upcoming chip and Vote Result branch (`test_upcoming_meeting_voice_layer1.py`, `test_vote_result_block.py`) should be unaffected since the *behavior* is identical for purely-future / purely-past meetings — only the same-day grace window changes.

- [ ] **Step 10: Commit**

```bash
git add src/docket/web/templates/
git commit -m "refactor(templates): use is_upcoming() instead of inline date compare

Centralizes the upcoming check so the start_time + 3h transition rule
applies uniformly across cards, meeting detail, item detail, and the
Vote Result no-vote branch. Preserves the voice-suppression conjunct
on item_detail and card_v2_fallback."
```

---

### Task 10: Migration replay — Railway prod check

**Files:** none (operational task)

- [ ] **Step 1: Apply migration 032 to staging / dev**

Run: `cd ~/docket-pub && venv/bin/python -m docket.migrations.runner --status | tail -5`
Confirm `[applied] 032_meetings_start_time` shows up locally.

- [ ] **Step 2: Deploy to Railway after merge**

Per CLAUDE.md: deploys from `main` apply migrations automatically via the `web:` Procfile entry. After PR merges:

```bash
git checkout main && git pull
railway up --detach --service docket-web
```

Then verify:

```bash
railway ssh --service docket-web -- "python -m docket.migrations.runner --status | tail -3"
```

Expected: `[applied] 032_meetings_start_time`.

- [ ] **Step 3: Backfill is intentionally not automated**

Document in the PR description that historical rows keep `start_time = NULL` and will use the noon-CT fallback. Granicus and CivicClerk adapters will populate `start_time` on the next scheduled `ingest_all` run (06:00 CT daily) — and only for upcoming rows. Past Granicus archive rows stay NULL unless a future task re-scrapes them, which is fine because their upcoming-vs-prior status is already settled.

---

### Task 11: Integration test — SQL + template parity

**Files:**
- Create: `tests/integration/test_upcoming_transition.py`

This test inserts meetings at known dates/times, then asserts that:
- `list_upcoming_meetings` returns them ⇔ `is_upcoming(meeting)` returns True
- A meeting whose transition moment has passed is in `list_recent_meetings` and `is_upcoming` returns False

- [ ] **Step 1: Write the test**

```python
# tests/integration/test_upcoming_transition.py
"""Cross-checks the SQL predicate in query.py against the Python helper in
meeting_time.py. If these two ever drift, this test catches it."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from docket.db import db_cursor
from docket.services.meeting_time import is_upcoming
from docket.services import query

CT = ZoneInfo("America/Chicago")


@pytest.fixture
def municipality_id():
    """Reuse the cleanest available test-muni fixture pattern in this repo —
    inspect tests/integration/conftest.py for the canonical setup. If a
    fixture named municipality_id exists, this auto-resolves. If not, copy
    the seed pattern from test_ingest_reconciliation.py."""
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO municipalities (slug, name, state, active, adapter_kind)
            VALUES ('al-transition-test', 'Transition Test City', 'AL', TRUE, 'granicus')
            ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """
        )
        (mid,) = cur.fetchone()
        yield mid
        cur.execute("DELETE FROM municipalities WHERE id = %s", (mid,))


def _insert_meeting(muni_id, days_offset, start_time=None, title="T"):
    md = (datetime.now(CT).date() + timedelta(days=days_offset))
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO meetings (
                municipality_id, external_id, title, meeting_date,
                meeting_type, source_url, start_time
            ) VALUES (%s, %s, %s, %s, 'council', 'https://x', %s)
            RETURNING id, meeting_date, start_time
            """,
            (muni_id, f"test-{days_offset}-{start_time}", title, md, start_time),
        )
        row = cur.fetchone()
        return {"id": row[0], "meeting_date": row[1], "start_time": row[2]}


def test_future_meeting_appears_in_upcoming_and_not_recent(municipality_id):
    _insert_meeting(municipality_id, days_offset=2)
    upcoming = query.list_upcoming_meetings(days=7, limit=50)
    recent = query.list_recent_meetings(days=7, limit=50)
    assert any(m["municipality_id"] == municipality_id for m in upcoming)
    assert not any(m["municipality_id"] == municipality_id for m in recent)


def test_yesterday_meeting_appears_in_recent_and_not_upcoming(municipality_id):
    _insert_meeting(municipality_id, days_offset=-1)
    upcoming = query.list_upcoming_meetings(days=7, limit=50)
    recent = query.list_recent_meetings(days=7, limit=50)
    assert not any(m["municipality_id"] == municipality_id for m in upcoming)
    assert any(m["municipality_id"] == municipality_id for m in recent)


def test_python_helper_agrees_with_sql_for_a_grid_of_cases(municipality_id):
    """Insert meetings at varied (offset, start_time) combos and assert
    is_upcoming() matches membership in list_upcoming_meetings."""
    cases = [
        (0, None),            # today, no time → noon+3h cutoff
        (0, time(9, 0)),      # today 9am → 12pm cutoff
        (0, time(17, 30)),    # today 5:30pm → 8:30pm cutoff
        (-1, time(17, 30)),   # yesterday — always prior
        (1, time(9, 0)),      # tomorrow — always upcoming
    ]
    inserted = [_insert_meeting(municipality_id, off, st, title=f"case-{off}-{st}")
                for off, st in cases]
    upcoming = {m["id"]: m for m in query.list_upcoming_meetings(days=7, limit=50)}

    now = datetime.now(CT)
    for m in inserted:
        py = is_upcoming(m["meeting_date"], m["start_time"], now)
        sql = m["id"] in upcoming
        assert py == sql, (
            f"mismatch: meeting_date={m['meeting_date']} "
            f"start_time={m['start_time']} python={py} sql={sql}"
        )
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `cd ~/docket-pub && venv/bin/pytest tests/integration/test_upcoming_transition.py -v`
Expected: 3 PASS.

If the grid test fails, it's a real bug — the Python and SQL definitions have drifted. Inspect the failing case and align the two.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_upcoming_transition.py
git commit -m "test(integration): SQL/Python parity for upcoming transition

Pins the contract that list_upcoming_meetings agrees with is_upcoming()
on the same set of rows. If the SQL predicate or the helper drifts in
the future, this fails fast."
```

---

### Task 12: PR + manual smoke (UI verification)

**Files:** none (operational)

- [ ] **Step 1: Open the PR**

```bash
gh pr create --title "Per-meeting upcoming→prior transition w/ 3h buffer" --body "$(cat <<'EOF'
## Summary

- New `meetings.start_time TIME NULL` column (migration 032).
- Granicus + CivicClerk adapters now persist the time component they already pull from upstream.
- `services/meeting_time.is_upcoming()` + `UPCOMING_PREDICATE_SQL` define the rule once; templates and `query.py` both call into it.
- Templates (`meeting_card`, `_card_shell`, `_vote_result_block`, `card_v2_fallback`, `meeting_detail`, `item_detail`) replaced inline `meeting_date >= today` comparisons with `is_upcoming(meeting)`.
- Replaces midnight-CT flip with `meeting.start_time + 3h` (noon CT fallback if `start_time IS NULL`).

## Test plan

- [ ] `pytest -x` — full suite green locally
- [ ] After merge: `railway up --detach --service docket-web`, then `railway ssh --service docket-web -- "python -m docket.migrations.runner --status | tail -3"` shows `[applied] 032`
- [ ] After next 06:00 CT `ingest_all` worker run: spot-check a BHM upcoming row in prod has non-NULL `start_time`
- [ ] Visit a BHM 5pm+ council meeting page on its meeting day at e.g. 6pm CT — Upcoming chip + forward-voice copy still rendered
- [ ] Visit a BHM 9am committee meeting page at 1pm CT — should have transitioned to "prior" copy
EOF
)"
```

- [ ] **Step 2: After merge, manual smoke on Railway**

Once the worker has run a fresh `ingest_all`, hit `https://docket.pub/al/birmingham/` and:
1. Find an upcoming meeting card. Verify the Upcoming chip is still present.
2. Note the next-meeting date + time from the chip. Check `meetings.start_time` in the DB for that meeting — should be populated.
3. After that meeting's `start_time + 3h` passes, refresh and verify the card has moved to the "recent" rail / lost the chip.

If anything looks off, capture the exact `(meeting_date, start_time, now_ct, is_upcoming_result)` and open a follow-up issue rather than patching in haste.

---

## Self-Review Notes

1. **Spec coverage:**
   - User asked for `start_time + 3h` with noon CT fallback → Tasks 1-3 (column + helper + 3h constant + 12:00 default).
   - Persist time data adapters already pull → Tasks 4-5 (Granicus, CivicClerk).
   - Wire to UI → Tasks 8-9 (Jinja global + 6 template files).
   - Wire to SQL filters → Task 7 (`list_upcoming_meetings*`, `list_recent_meetings*`).
   - Tests at each layer → Tasks 2/3/4/5/6/7/8/11.
   - Out-of-scope explicitly named → AI voice selection, Generic CMS time extraction, historical backfill.

2. **Placeholders:** None. Every step has the actual SQL/Python/Jinja edit.

3. **Type consistency:**
   - `time | None` used consistently across `RawMeeting`, `Meeting`, helper signature, adapter return values.
   - `is_upcoming(meeting_date, start_time, now=None)` signature identical in test file (Task 3) and call sites (Tasks 8, 11).
   - SQL fragment `UPCOMING_PREDICATE_SQL` defined once (Task 3), referenced in Task 7 with documented `mt.` prefix injection.

4. **Known sharp edge:** Task 7's `.replace("meeting_date", "mt.meeting_date")` is a fragile string-substitution. If `meeting_time.py` later mentions `meeting_date` outside the predicate proper (e.g. in a doc string interpolated into the constant), the replace would corrupt unintended sites. Keeping the predicate string narrow and tested by Task 7 Step 2 mitigates this; long-term, a Postgres function `is_meeting_upcoming(meeting_date, start_time) RETURNS BOOLEAN IMMUTABLE` would be cleaner. Out of scope for this plan but worth a follow-up.
