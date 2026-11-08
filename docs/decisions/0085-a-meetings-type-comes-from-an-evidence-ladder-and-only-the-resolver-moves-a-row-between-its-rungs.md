# 0085 — A meeting's type comes from an evidence ladder, and only the resolver moves a row between its rungs

## Decision

`services/meeting_types.resolve` classifies a meeting from the strongest evidence that applies, in this order, and records the rung in `type_source`: the admin lock (`0086`); a specific title, one that says special, called, work session, budget, or names a committee or board, which is final; a YouTube recording's cleaned title that names a body (`0067`, `type_source = 'video'`); the city's own calendar event on the meeting's day (`calendar`), whose tie among several events is broken by documents and never by `start_time`, and which never matches a row with a minutes link to a committee event; the schedule rule (`schedule_rule`); and otherwise the title's generic reading (`title`). The schedule rule fires only when the title classifies as a regular council meeting, the city's metadata names the council's regular weekday (`council_schedule.weekday`) and the row's weekday differs, the row has no minutes link, and the title is not cancelled; it yields `committee`, `regular`, no body name. The matched calendar event is stored on the row (`calendar_event_id`), not recomputed.

The ingest writers set the classification from the title on INSERT, and on UPDATE only while the row's `type_source` is `title` and it is unlocked; `resolve_and_store`, run after every ingest over the rows the feed listed, is the only code that moves a row between rungs. Reclassifying a city's existing rows is one `UPDATE ... FROM (VALUES ...)` per city computed in Python and scoped to unlocked rows, an instance of `0026`, run by the operator against production with a dry run first that lists every pre-2026 row the schedule rule would touch.

## Rationale

The title is the city's own document and is right whenever it is specific; it is wrong in exactly one case, Birmingham's clerk naming nearly every clip "Regular City Council Meeting", committee recordings included, so that a reader of the week of 2026-10-19 saw six meetings under one name. The calendar is a second city source that names the body, but only for upcoming weeks, since the city's page lists upcoming events alone; the schedule rule is an inference (a council-department recording on a day the council does not sit, with no minutes) and ranks last among the evidence, above only the generic title. The `video` rung sits between the specific title and the calendar because the stream's title is the council's own name for that recording, written on the day (`0067`).

The schedule rule as first drafted also required zero agenda items, on the assumption that a committee clip never carries parsed items; the review found that Birmingham's Committee of the Whole previews the next council agenda (meeting 2613 held 51 items), so the condition was dropped. A real council meeting moved to another weekday (2024-12-23, a Monday before Christmas Eve) is still protected: it gains a minutes link once minutes are posted, and before that the calendar rung, which outranks the rule, names it from the city's "CITY COUNCIL MEETING" event. The dry run lists the pre-2026 rows the rule would touch so the operator reads them before the write; on production that list held six real council meetings (adjourned sessions, a full agenda), which the operator locked as `council` rather than adding a date floor to the rule.

The calendar tie is broken by documents, not by time, because `meetings.start_time` is wrong by construction: the Granicus adapter reads a Pacific wall-clock timestamp as if it were UTC-correct, so an archived clip stores 02:00 and an upcoming row a time two hours late (GitHub issue #88). A nearest-time rule would have matched the Tuesday council clip to the 11:30 committee as often as not. A row with minutes or items is the council meeting; a row with neither is the committee. Fixing the adapter is its own change under #88.

The writers are gated because the first draft had `_upsert_meetings` writing `type_source = 'title'` on every daily run and `resolve_and_store` restoring the calendar or rule result seconds later, so a page loaded between the two stages, or a run that failed between them, showed the clip name again. With the writer gated on `type_source = 'title'`, a resolved row is never touched by the upsert, and `resolve_and_store` recomputes the whole ladder from the current title each run, so a row that should fall back (minutes arrived, title gained "Cancelled") still does. The alternative of letting each source write its own answer (the YouTube pass writing the body name it read, the calendar task writing matches) would have had the passes flip a row daily.

## Date

2026-10-21, Claude as the author of plan `meeting-types-name-the-body` after the design review; the `video` rung added 2026-10-24 by `0067`; built in M4 and graduated by the M6 session on 2026-11-08.

## Status

accepted
