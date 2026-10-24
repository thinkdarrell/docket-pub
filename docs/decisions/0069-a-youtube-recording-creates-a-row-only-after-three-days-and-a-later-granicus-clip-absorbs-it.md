# 0069 — A YouTube recording creates a row only after three days, and a Granicus clip that arrives later absorbs it

## Decision

`sync_city` creates a `yt-<video id>` row for an unmatched recording only when the video was published at least `CREATE_AFTER_DAYS` (3) days before the run, and defers it otherwise. Each run then absorbs: a `yt-` row of the last 30 days with no agenda items, on a date that now has an unmatched Granicus candidate created after the `yt-` row (`meetings.created_at`) and pairing with it by duration (or being the day's one such candidate where the day has one of each), has its `meeting_videos` rows moved to the Granicus row and is deleted, or hidden when a `transcripts` row references it, logged at WARNING with both ids.

## Rationale

The promise is one row per meeting in either arrival order. Creating at once would race the clerk: Granicus clips post within a day or two of a meeting, so a same-day create would make a `yt-` row that the Granicus clip then duplicates the next morning. Waiting three days lets the Granicus row exist first so the recording attaches instead. Waiting alone does not cover a clip that arrives later still, which is what absorption is for; without it the duplicate would stand until someone hid it by hand.

Absorption deletes rather than merges because every foreign key that points at `meetings(id)` is `ON DELETE CASCADE` and a `yt-` row young enough to absorb has no items, votes, or minutes; it hides instead when a transcript exists, so a machine transcript is never deleted by a scheduled task. The 30-day window and the no-items condition keep it away from the 2023 Boutwell `yt-` rows and from anything a reader has come to rely on.

## Date

2026-10-24, Claude, in `plans/active/youtube-council-channel.md` (built in its M4; the file moves to `plans/completed/` when the plan closes).

## Status

accepted
