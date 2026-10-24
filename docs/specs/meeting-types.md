# Meeting types

What a meeting's type, sitting, and body name mean, how a row gets them, and what a reader sees. Present tense; the plan that built this is `plans/completed/meeting-types-name-the-body.md` once it closes, and `plans/active/` until then.

## The vocabularies

A meeting carries five classification columns on `meetings`: `meeting_type` (the body), `session_kind` (the sitting), `body_name` (the committee or board the row belongs to, when known), `type_source` (which rung of the ladder below named it), and the admin lock pair `type_locked_at` / `type_locked_by`. A sixth, `calendar_event_id`, points at the city-calendar event that named the body when the calendar did.

`meeting_type` is one of `council`, `committee`, `planning`, `board`, `other`. `session_kind` is one of `regular`, `special`, `work_session`, `budget_hearing`. `type_source` is one of `title`, `video`, `calendar`, `schedule_rule`, `admin`. The two vocabularies are the tuples `MEETING_TYPES` and `SESSION_KINDS` in `src/docket/adapters/_helpers.py`, and every other file imports them from there. Migration 038 holds the CHECK constraints on `session_kind` and `type_source` (migration 040 widens the latter with `video`); the CHECK on `meeting_type` lands with migration 039 after every city's rows conform.

A clip name such as "Special Called Finance Committee" classifies as `committee`, `special`, "Finance Committee"; "Regular City Council Meeting" is the generic `council`, `regular`, no body; "Budget Hearing" is `council`, `budget_hearing`. `classify_title` in `_helpers.py` owns these readings.

## The ladder

`services/meeting_types.resolve` classifies one row from the evidence, strongest rung first; the first rung that applies wins and is recorded in `type_source`.

1. **Admin lock.** A row with `type_locked_at` set is returned unchanged; nothing below this rung touches it.
2. **Specific title.** A specific title (one that says special, called, work session, budget, or names a committee or board) is final: the video, the calendar, and the rule never override it.
3. **Video.** For a generic title, a YouTube recording attached to the row (`meeting_videos`) whose cleaned title names a body is final; the council's own name for its stream outranks the calendar and the rule. The row's YouTube clean titles are read primary first, and the first whose `classify_title` is not the generic council reading decides, with `type_source = 'video'` and no calendar event.
4. **Calendar.** For a generic title, the city's calendar events on the meeting's date (America/Chicago) are read (`classify_event`: "CITY COUNCIL MEETING" is a council sitting, special when the title says so; "COMMITTEE" is a committee named by `committee_name_for`, the canonical committee list or the cleaned event title). With one usable event that day it is the match; with several, a row that has documents (a minutes link or agenda items) takes the day's council event and a row without takes the committee event, and when exactly one such event does not exist there is no match. A row with minutes is never matched to a committee event. The match writes `calendar_event_id` to the event and, for a committee event, `body_name` from it; a council event names no body.
5. **Schedule rule.** The city's metadata names the council's regular weekday (`council_schedule.weekday`, Monday 0; Birmingham's is Tuesday). A generic-titled row on another weekday, with no minutes link and not cancelled, is a `committee`, `regular` recording with no body name.
6. Otherwise the title's own generic reading stands (`council`, `regular`, source `title`). A row with no `meeting_date` stops at the title rung either way, since the calendar and the rule both need a date.

`resolve_and_store(municipality_id, meeting_ids)` runs after every ingest over the rows the feed listed that day and writes the rows whose five columns changed in one `UPDATE ... FROM (VALUES ...)` scoped to unlocked rows, so a row that gains minutes, items, or a cancelled title moves back down the ladder on its own. The ingest writers themselves set the four columns from the title on INSERT, and on UPDATE only while `type_source` is `title` and the row is unlocked, so a row the video, the calendar, the rule, or an admin placed keeps its classification while its title, dates, and links still update.

## The label

A reader never sees the clip name as the meeting's name. The Jinja global `meeting_label(meeting)` (registered in `docket.web.create_app`) calls `label_for` in `_helpers.py`: a `council` row reads "City Council meeting", "Special called council meeting", "Council work session", or "Budget hearing" by its sitting; a `committee`, `planning`, or `board` row reads its `body_name`, or "Council committee meeting", "Planning commission meeting", "Board meeting" when none is known, with " (special called)" or " (work session)" appended for those sittings; an `other` row reads its own title. A cancelled title (`query.is_cancelled_title`) appends " (cancelled)", except on an `other` row, which reads its title unchanged. A row without the columns, or with a type outside the vocabulary, prints its title.

The label is the card's heading on the meetings list, the home page's strips, and the city page's "Recent meetings"; it is the meeting page's `h1` and `<title>`. The meeting page's eyebrow carries a chip for `meeting_type` and, when the sitting is not `regular`, a chip reading "special called", "work session", or "budget hearing".

## Provenance

When the label differs from the title, the meeting page prints below the hero: `The city's archive lists this recording as “<title>”.` A row named by the schedule rule continues: "It is not on the council's regular meeting day and the city calendar did not name the body." A row named by the calendar continues: "The city's calendar names it." with a link to the event's `source_url` (`meeting_types.calendar_event_for`). A row whose label is its title prints nothing.

## The filter row

The meetings page at `/al/<slug>/meetings/` carries a `nav.type-filter` above the grid: "All" with the city's visible meeting count, then Council, Committees, Planning, Boards, Other, each linking to `?type=<meeting_type>` with its count from `query.meeting_type_counts` (one `GROUP BY meeting_type` over the city's non-hidden rows). A type with no rows is text, not a link. The filtered page lists only rows of that type.

## The admin override

On a meeting page, an admin sees a form with a `meeting_type` select, a `session_kind` select, and a `body_name` field. Saving posts to `POST /admin/meetings/<id>/type`, which rejects a value outside the vocabularies with 400 and otherwise calls `meeting_types.set_override`: the four columns are written with `type_source = 'admin'`, `type_locked_at = now()`, `type_locked_by` the admin's id, and `calendar_event_id` cleared. A locked row shows "Set by hand on <date>" and an Unlock button posting to `POST /admin/meetings/<id>/type/unlock`, which calls `meeting_types.clear_override`: the lock is cleared and the row is resolved once through the ladder, in one transaction. Neither route clears the row's AI meeting summary; the worker's adoption pass regenerates it as it does after `resolve_and_store`. Both routes redirect to the login page when no admin is signed in, as the other admin POSTs do. The lock survives ingest and the daily resolution until it is lifted.

## The city calendar

The worker task `city_calendar` runs daily at 05:30 America/Chicago (`src/docket/worker/scheduler.py`) and, for every active city whose metadata carries `calendar_url`, fetches the page and upserts its upcoming events into `city_calendar_events` (`municipality_id`, `source_event_id`, `title`, `starts_at`, `ends_at`, `source_url`, `categories`, `fetched_at`; unique on city and source event). Birmingham's URL is the council page at `https://www.birminghamal.gov/government/city-council`, whose embedded Next.js JSON lists the upcoming events; `parse_birminghamal_page` reads it. The calendar lists upcoming events only, so past rows are named by the schedule rule unless the event was fetched before the meeting.

## Reclassifying a city

`scripts/reclassify_meetings.py --city <slug>` resolves every non-hidden row of one city through the ladder, prints the transition table (old type and sitting to new type, sitting, and source, with counts) and, one per line, the rows the schedule rule would classify that predate 2026-01-01, then writes the changed rows in one statement scoped to unlocked rows and clears the AI meeting summary of each row whose body left `council` so the worker regenerates it. The operator runs it one city at a time, `--dry-run` first, against production with `DATABASE_URL` set to `DATABASE_PUBLIC_URL`, reads the pre-2026 list, and locks by hand any row that is a real council meeting before the write (`docs/specs/operations.md` has the Railway pattern). A second dry run after the write prints every count on the diagonal. Birmingham was reclassified on 2026-10-22; the other cities follow.
