# 0068 — A YouTube recording is paired with a Granicus clip by duration, and a day the durations cannot settle creates a row rather than merging

## Decision

Where a date holds more than one Granicus candidate row or more than one YouTube group, `services/youtube_meetings.sync_city` pairs them by recording length: `pairs(a, b)` is true when `abs(a - b) <= max(300, 0.25 * max(a, b))`, nearest difference first, each row once, comparing a group's total over its parts with the clip's `meetings.duration_s` (which the Granicus adapter reads from the archive row's Duration cell). A group left unpaired creates its own `yt-` row, the unpaired clips are left alone, and the date is logged at WARNING and listed by the backfill; a date whose candidate clip has no stored duration creates nothing (`no_duration`).

## Rationale

`meetings.start_time` would be the natural key, but the stored Granicus values are wrong by construction (issue #88: archived clips carry 02:00), and the resolver already refuses to read them. Title similarity is no help either, since the Granicus clips this pass meets are titled "Regular City Council Meeting" whatever they record. Durations are printed by both sources and, on every overlapping 2026 day observed while the plan was written, paired the right clip with the right stream and nothing else did. The total over parts is compared because Granicus records one continuous clip where the council's stream broke into Pt. 1 and Pt. 2.

On an ambiguous day the choice is between a cosmetic duplicate and a wrong merge. A duplicate row is visible and recoverable in admin; a wrong merge attaches one committee's recording and name to another committee's clip and misattributes the record to a reader, which `docs/PRINCIPLES.md` forbids. The `no_duration` guard exists because the historical backfill runs over clips whose durations are filled only by the first ingest after the migration; without it a run before that ingest would create a `yt-` twin of every committee clip Granicus already holds.

## Date

2026-10-24, Claude, with the guard and the group total from the operator's external review, in `plans/active/youtube-council-channel.md` (built in its M2 and M4; the file moves to `plans/completed/` when the plan closes).

## Status

accepted
