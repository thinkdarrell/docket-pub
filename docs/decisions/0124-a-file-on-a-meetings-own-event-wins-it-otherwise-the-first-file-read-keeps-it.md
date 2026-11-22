# 0124 — A file on a meeting's own event wins the meeting; otherwise the first file read keeps it

## Decision

When two Minutes files name one meeting's date, the file attached to that meeting's own event (`event_external_id` equal to the meeting's `external_id`) is the meeting's minutes and the other is recorded `superseded`; when neither or both sit on it, the file read first keeps the meeting. Before any `minutes_files` row becomes `paired` for a meeting, every other `paired` row naming that meeting is set `superseded` in the same transaction, every time.

## Rationale

26 of the dates Mobile's files name are named by two files each, and in each pair one file sits on the event of that date. A rule was needed that gives the same answer whatever order the files are read in, and "the newest file" or "the higher file id" says nothing about which the city means. The own-event rule also covers the ordinary correction: when the city replaces a meeting's minutes with a new file on the same event, the new file takes the meeting and its votes are replaced. In all 26 pairs both files hold the same votes, so which wins changes the link and not what a reader is told.

The unconditional supersede statement is a no-op while the pairing rule is right. It is kept because `minutes_files` allows one `paired` row per meeting by a partial unique index, and a pairing the rule got wrong would otherwise be refused by the index and fail the file for ever instead of repairing the table.

A `superseded` row keeps the id of the meeting it lost, so the table says which meeting each spare file names; only `paired` rows are read as holding a meeting.

## Date

2026-11-21, the authoring session of plan `mobile-votes-from-minutes` (Claude); the unconditional supersede added the same day from an outside review; built by that plan's M3 and graduated by its M6 session on 2026-11-22 (UTC).

## Status

accepted
