"""Migration 040 — YouTube recordings: `meeting_videos`, `meetings.duration_s`, the `video` type source, Birmingham's channel.

`meeting_videos` holds every recording of a meeting that is not the row's
own `video_url`: one row per provider video (`UNIQUE (provider, video_id)`),
at most one primary per meeting and provider (partial unique index), and
`ON DELETE CASCADE` so a meeting's recordings go with it. `provider` is
`youtube` only for now. `clean_title` is the video title with its date and
part tokens removed (`docket.services.youtube_meetings.clean_title`); the
meeting-type ladder reads it.

`meetings.duration_s` is the recording's length in seconds, filled from the
Granicus publisher page's Duration cell and from YouTube; the YouTube sync
pairs a stream with a Granicus clip by it, because stored start times are
wrong (issue #88).

`meetings_type_source_check` gains `video`: the ladder rung that names a
row from its YouTube recording's clean title. The down returns any
`video` row to `title` before restoring the narrower CHECK; the next
ingest's resolver recomputes it.

Birmingham's metadata gains `youtube_channel` and `youtube_channel_id`;
the down removes both keys.

Number 039 is left to plans/active/meeting-types-name-the-body.md (M6).
Plan: plans/active/youtube-council-channel.md (M2).
"""

from __future__ import annotations


SQL_UP = r"""
CREATE TABLE IF NOT EXISTS meeting_videos (
    id          SERIAL PRIMARY KEY,
    meeting_id  INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    provider    TEXT NOT NULL CHECK (provider IN ('youtube')),
    video_id    TEXT NOT NULL,
    url         TEXT NOT NULL,
    title       TEXT NOT NULL,
    clean_title TEXT NOT NULL,
    duration_s  INTEGER NULL,
    started_at  TIMESTAMPTZ NULL,
    is_primary  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, video_id)
);

CREATE INDEX IF NOT EXISTS idx_meeting_videos_meeting
    ON meeting_videos (meeting_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_meeting_videos_primary
    ON meeting_videos (meeting_id, provider) WHERE is_primary;

ALTER TABLE meetings ADD COLUMN IF NOT EXISTS duration_s INTEGER NULL;

ALTER TABLE meetings DROP CONSTRAINT IF EXISTS meetings_type_source_check;
ALTER TABLE meetings ADD CONSTRAINT meetings_type_source_check
    CHECK (type_source IN ('title', 'calendar', 'schedule_rule', 'admin', 'video'));

UPDATE municipalities
   SET metadata = metadata || '{"youtube_channel": "citycouncilbham", "youtube_channel_id": "UCxKV8MgjDbqw9PMGTsF_NUw"}'::jsonb
 WHERE slug = 'birmingham';
"""

SQL_DOWN = r"""
UPDATE municipalities
   SET metadata = metadata - 'youtube_channel' - 'youtube_channel_id'
 WHERE slug = 'birmingham';

UPDATE meetings SET type_source = 'title' WHERE type_source = 'video';

ALTER TABLE meetings DROP CONSTRAINT IF EXISTS meetings_type_source_check;
ALTER TABLE meetings ADD CONSTRAINT meetings_type_source_check
    CHECK (type_source IN ('title', 'calendar', 'schedule_rule', 'admin'));

ALTER TABLE meetings DROP COLUMN IF EXISTS duration_s;

DROP INDEX IF EXISTS uq_meeting_videos_primary;
DROP INDEX IF EXISTS idx_meeting_videos_meeting;
DROP TABLE IF EXISTS meeting_videos;
"""
