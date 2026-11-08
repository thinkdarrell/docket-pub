# 0076 — The transcriber role also reads meeting_videos and may insert and update, never delete, meeting_video_alignments; measurements live in that table of their own, and the production grant is an operator step

## Decision

Where an attached YouTube recording sits on its Granicus clip's clock is stored in `meeting_video_alignments` (migration 042), one row per recording keyed on `meeting_video_id`, not in columns on `meeting_videos`. The `transcriber` database role gains SELECT on `meeting_videos` and SELECT, INSERT, and UPDATE on the new table, and nothing else; it is granted no DELETE, so a re-measure overwrites the row. `scripts/sql/create_transcriber_role.sql` stays the one place the role's grants are written, and on a database where the role already exists the database owner runs its two new `GRANT` statements by hand; no migration grants anything to the role.

## Rationale

Decision `0030` bounds what a credential kept on a machine outside Railway can do by letting the role write only its own tables. The obvious alternative, three or four columns on `meeting_videos`, would have needed UPDATE on a table the worker's YouTube sync owns and rewrites (it moves recordings between meeting rows), which is the reach `0030` exists to refuse. A separate table lets the role gain write access to exactly one new table and read access to one more. One row per recording is the shape of the fact, so the recording's id is the key and no sequence needs a grant.

A conditional `GRANT` inside migration 042 was the other way to deliver the grants. It would have made the migration a second owner of the role's grants beside the role file, and the migration runs as the application role on every deploy whether or not the `transcriber` role exists on that database. Until the owner runs the two statements the measuring pass logs one warning and the run transcribes as before, so the cost of the manual step is a delay and not a failure.

## Date

2026-11-05, the plan author (Claude) from the operator's goal and its scope brief, in `plans/completed/video-links-land-on-the-moment.md` (built in its M2; the file is under `plans/active/` until the plan closes); graduated from the plan's Decision Log by its M8 session on 2026-11-06.

## Status

accepted
