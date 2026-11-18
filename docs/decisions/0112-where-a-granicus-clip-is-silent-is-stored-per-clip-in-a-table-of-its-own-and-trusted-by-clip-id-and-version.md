# 0112 — Where a Granicus clip is silent is stored per clip, in a table of its own, and a row is trusted by its clip id and its method version

## Decision

Where a meeting's Granicus clip has no sound is stored in `granicus_clip_sound` (migration 048), one row per meeting keyed on `meeting_id`, holding the clip's length, its silent seconds, and its silent spans on the Granicus clock. It is not a `reason` on a row of `meeting_video_alignments` and not a column of `meetings`. The `transcriber` database role may select, insert, and update the table and never delete from it; `scripts/sql/create_transcriber_role.sql` holds the grant, the database owner runs it by hand where the role already exists, and no migration grants anything to the role. The site uses a row only when its `method_version` is at least `MIN_SOUND_VERSION` in `src/docket/services/video_links.py` and its `granicus_clip_id` equals the meeting's current `external_id`.

## Rationale

Every Granicus clip that was tested behind a recording the matcher had rejected turned out to be silent, for all of its length or for part of it (issue #174; 42 recordings were `rejected` on 2026-11-17, 38 of them with reason `score`). The obvious record of that was a new reason, `silent`, on the rejected measurement row. It lost on three counts. Silence is a property of the clip and not of one YouTube recording: a meeting with two recordings would carry the fact twice, and a meeting whose recording is later moved to another row would lose it. A partly silent clip needs spans, and a rejected row carries none; clip 2034 is silent for 2,719 of its 6,019 seconds in five spans while one of its recordings passes on the audible part. And decision `0106` makes the transcriber's candidate query the one reader of `reason`, which a site that read it would break, with the three hand statements of `docs/runbooks/transcripts.md` that write the table to re-prove.

Columns on `meetings` were the other shape. They would have needed UPDATE on a table ingest owns, the reach decision `0030` exists to refuse. This record extends `0030` and `0076` by one table: the role gains write access to exactly one more table it alone writes, without DELETE, because the writer replaces a meeting's row in place (`ON CONFLICT (meeting_id)`) and a row goes with its meeting by cascade. The grant stays in the role file for the reason `0076` gives; until the owner runs it the measuring pass logs one `measure: skipped (...)` warning and the run transcribes as before.

The two tests a row must pass are the two a measurement already passes (`MIN_METHOD_VERSION` and the clip id in `video_links.for_meetings`). The clip id keeps a row measured before an event id became a clip id, or against a clip the meeting no longer has, from labelling the new clip. The version is a floor, so a later method's rows are used as they are, and it gives the owner a switch without a deploy: setting every row's `method_version` to 0 takes the note and the label off the site, and setting it back restores them.

The clips already rejected are measured for sound because the owner deletes their rejected rows, not because `ALIGN_METHOD_VERSION` rises or the candidate query changes: the matcher's arithmetic did not change, and the candidate query's predicate is read by the runbook's hand statements.

## Date

2026-11-17, the authoring session of plan `silent-granicus-says-so` (Claude), on the findings of issue #174; built by that plan's M2 to M4 and graduated by its M6 session on 2026-11-18.

## Status

accepted
