"""Migration 048 — `granicus_clip_sound` says where a meeting's Granicus clip is silent.

Some Granicus clips have no sound, for all of their length or for part of it,
while the council's YouTube recording of the same meeting is audible. The
transcriber's measuring pass already fetches a clip's audio to compare a
YouTube recording against it; from the same samples it measures which
stretches of the clip are silent (`transcriber/transcriber/sound.py` owns the
rule and its constants). This table holds the result, so the site can say "no
sound" on a link to the Granicus player.

One row per meeting, keyed on `meeting_id` and deleted with its meeting.
Silence is a property of the clip, not of one YouTube recording, so it is not
a column or a reason on `meeting_video_alignments`. `granicus_clip_id` is the
meeting's `external_id` when the clip was measured: a reader uses a row only
while it equals the meeting's current `external_id`. `method_version` is the
writer's `SOUND_METHOD_VERSION`. `duration_s` is the clip's length and
`silent_s` the total of its silent spans, never more than the duration.
`silent_spans` is a JSON array of two-number arrays, `[start_s, end_s]`, in
order, in seconds on the Granicus clock; a clip with no silent span holds
`[]`. The writer replaces a meeting's row in place.

The down drops the table. Its rows return as clips are measured again.

The `transcriber` role needs SELECT, INSERT, and UPDATE on this table, and
not DELETE. No migration grants anything to that role: the grant is in
`scripts/sql/create_transcriber_role.sql`, and on a database whose role
predates this migration the owner runs
`GRANT SELECT, INSERT, UPDATE ON granicus_clip_sound TO transcriber;` by hand.

Plan `silent-granicus-says-so`, M2.
"""

from __future__ import annotations


SQL_UP = r"""
CREATE TABLE IF NOT EXISTS granicus_clip_sound (
    meeting_id       INTEGER PRIMARY KEY REFERENCES meetings(id) ON DELETE CASCADE,
    granicus_clip_id TEXT NOT NULL,
    method_version   INTEGER NOT NULL,
    duration_s       DOUBLE PRECISION NOT NULL CHECK (duration_s > 0),
    silent_s         DOUBLE PRECISION NOT NULL CHECK (silent_s >= 0 AND silent_s <= duration_s),
    silent_spans     JSONB NOT NULL DEFAULT '[]'::jsonb,
    measured_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

SQL_DOWN = r"""
DROP TABLE IF EXISTS granicus_clip_sound;
"""
