"""Migration 046 — `meeting_video_alignments` holds one row per confirmed stretch of a recording.

A YouTube recording can match its Granicus clip at more than one offset (a
stream that dropped and resumed, two pieces stitched together). Since method
version 3 the transcriber stores each confirmed stretch as its own row, with
its own offset and its own span of the Granicus clock. This migration keeps
the table of migration 042 and reshapes it for that: it adds
`stretch INTEGER NOT NULL DEFAULT 1` (counted from 1 in order of where the
coverage starts), re-keys the table as `PRIMARY KEY (meeting_video_id,
stretch)`, and adds `CHECK (stretch >= 1)`. Migration 042's constraint that a
`passed` row has an offset and a non-empty span is not touched. There is no
sequence and no surrogate id, and no CHECK ties `stretch = 1` to a row that
is not `passed`: a `rejected` or `failed` recording is one row with
`stretch = 1` by the writer's rule, and the operator's off switch sets every
passed row, later stretches included, to `rejected` and back.

It then runs one targeted statement (decision 0026): it deletes the rows
`rejected` at method version 2, so those recordings are candidates for the
next measuring pass, where the stretch rule may confirm what the
whole-recording verdict threw out. On the production read of 2026-11-12 that
was 60 rows, every stored row then being at version 2. A row the owner
switched off (`rejected` with the reason `operator`, a passed row whose
links were sent back to Granicus) is kept, so a switch that is on when the
migration runs stays on and can be restored. Rows `passed` at
version 2 are kept and stay trusted (`ALIGN_TRUSTED_VERSION` in
`transcriber/transcriber/align.py`, `MIN_METHOD_VERSION` in
`src/docket/services/video_links.py`); `failed` rows are kept and retried by
their own rule. The statement is harmless to repeat.

The down keeps each recording's first stretch: it deletes the rows with
`stretch > 1`, drops the column, and restores the single-column key. It does
not restore the rejections the up deleted; the next measuring run makes them
again.

The `transcriber` role needs DELETE on this table to replace a recording's
stretch rows on a re-measure. No migration grants anything to that role: the
grant is in `scripts/sql/create_transcriber_role.sql`, and on a database
whose role predates this migration the owner runs
`GRANT DELETE ON meeting_video_alignments TO transcriber;` by hand.

Plan `youtube-links-cover-matching-stretches`, M2.
"""

from __future__ import annotations


SQL_UP = r"""
ALTER TABLE meeting_video_alignments
    ADD COLUMN IF NOT EXISTS stretch INTEGER NOT NULL DEFAULT 1;
ALTER TABLE meeting_video_alignments
    DROP CONSTRAINT IF EXISTS meeting_video_alignments_pkey;
ALTER TABLE meeting_video_alignments
    ADD CONSTRAINT meeting_video_alignments_pkey PRIMARY KEY (meeting_video_id, stretch);
ALTER TABLE meeting_video_alignments
    DROP CONSTRAINT IF EXISTS meeting_video_alignments_stretch_positive;
ALTER TABLE meeting_video_alignments
    ADD CONSTRAINT meeting_video_alignments_stretch_positive CHECK (stretch >= 1);
DELETE FROM meeting_video_alignments
 WHERE status = 'rejected' AND method_version = 2 AND reason IS DISTINCT FROM 'operator';
"""

SQL_DOWN = r"""
DELETE FROM meeting_video_alignments WHERE stretch > 1;
ALTER TABLE meeting_video_alignments
    DROP CONSTRAINT IF EXISTS meeting_video_alignments_stretch_positive;
ALTER TABLE meeting_video_alignments
    DROP CONSTRAINT IF EXISTS meeting_video_alignments_pkey;
ALTER TABLE meeting_video_alignments
    DROP COLUMN IF EXISTS stretch;
ALTER TABLE meeting_video_alignments
    ADD CONSTRAINT meeting_video_alignments_pkey PRIMARY KEY (meeting_video_id);
"""
