"""Migration 042 — `meeting_video_alignments`: where a YouTube recording sits on its Granicus clip's clock.

One row per attached recording (`meeting_videos.id` is the primary key, and
`ON DELETE CASCADE` takes the row with the recording or its meeting). The
transcriber measures a recording against the meeting's Granicus clip by
comparing the sound of the two and stores the answer here; it keeps none of
the audio.

`offset_s` is Granicus seconds minus YouTube seconds for the same instant:
a moment at Granicus second g is at YouTube second g minus the offset.
`granicus_start_s` and `granicus_end_s` are the stretch of the Granicus
clock the recording has been confirmed to cover. `granicus_clip_id` is the
clip the offset was measured against; a row whose clip id differs from the
meeting's current `external_id` counts as no measurement, because a
recording can move to another meeting row and an upcoming event's id
changes when it becomes a clip. `method_version` is the matcher's version
(`transcriber.align.ALIGN_METHOD_VERSION`), compared with a floor so a
changed method re-measures old rows.

`status` is `passed` (the match met the pass mark; the CHECK requires an
offset and a non-empty span), `rejected` (audio fetched, match below the
mark; `reason` is the verdict's reason), or `failed` (the audio could not
be fetched or read; `reason` is the error text). `score`, `runner_up`,
`windows`, and `windows_confirmed` are the figures the verdict was reached
on, kept so an operator can read why.

The `transcriber` role's grants on this table and on `meeting_videos` are
in `scripts/sql/create_transcriber_role.sql`, not here.

Number 039 is left to plans/active/meeting-types-name-the-body.md (M6) and
041 to pull request #140 (plan/search-finds-what-was-said).
Plan: plans/completed/video-links-land-on-the-moment.md (M2).
"""

from __future__ import annotations


SQL_UP = r"""
CREATE TABLE IF NOT EXISTS meeting_video_alignments (
    meeting_video_id  INTEGER PRIMARY KEY REFERENCES meeting_videos(id) ON DELETE CASCADE,
    granicus_clip_id  TEXT NOT NULL,
    method_version    INTEGER NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('passed', 'rejected', 'failed')),
    reason            TEXT NULL,
    offset_s          DOUBLE PRECISION NULL,
    granicus_start_s  DOUBLE PRECISION NULL,
    granicus_end_s    DOUBLE PRECISION NULL,
    score             DOUBLE PRECISION NULL,
    runner_up         DOUBLE PRECISION NULL,
    windows           INTEGER NULL,
    windows_confirmed INTEGER NULL,
    measured_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT meeting_video_alignments_passed_has_span CHECK (
        status <> 'passed'
        OR (offset_s IS NOT NULL AND granicus_start_s IS NOT NULL
            AND granicus_end_s IS NOT NULL AND granicus_end_s > granicus_start_s))
);
"""

SQL_DOWN = r"""
DROP TABLE IF EXISTS meeting_video_alignments;
"""
