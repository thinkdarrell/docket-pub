"""Migration 038 — meeting types name the body: classification columns, the admin lock, city_calendar_events, Birmingham's schedule metadata.

`meetings.meeting_type` keeps naming the body (`council`, `committee`,
`planning`, `board`, `other`; its CHECK waits for 039, after production is
reclassified). This migration adds the sitting and its provenance:
`session_kind` (`regular`, `special`, `work_session`, `budget_hearing`),
`body_name` (the body's name when a source supplied it), `type_source`
(which evidence decided the row: `title`, `calendar`, `schedule_rule`,
`admin`), and the admin lock pair `type_locked_at` / `type_locked_by`,
mirroring 033's `hidden_at` / `hidden_by`. Every existing row conforms
through the defaults, so both CHECKs are safe to add here.

`city_calendar_events` holds the upcoming events a city's own calendar
page lists (one row per city per source event id), filled daily by the
worker task `city_calendar`; `meetings.calendar_event_id` records the
event the resolver matched, so the provenance link is a join and never a
recomputation. Birmingham's metadata gains `council_schedule` (the
council's regular weekday, Monday 0 as Python's `date.weekday()` counts;
Tuesday is 1) and `calendar_url`; the down removes both keys.

The two vocabularies' one owner is `MEETING_TYPES` / `SESSION_KINDS` in
src/docket/adapters/_helpers.py; the literals here are frozen text.
Plan: plans/active/meeting-types-name-the-body.md (M2).
"""

from __future__ import annotations


SQL_UP = r"""
ALTER TABLE meetings
    ADD COLUMN IF NOT EXISTS session_kind   TEXT NOT NULL DEFAULT 'regular',
    ADD COLUMN IF NOT EXISTS body_name      TEXT NULL,
    ADD COLUMN IF NOT EXISTS type_source    TEXT NOT NULL DEFAULT 'title',
    ADD COLUMN IF NOT EXISTS type_locked_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS type_locked_by INTEGER NULL REFERENCES admin_users(id) ON DELETE SET NULL;

ALTER TABLE meetings DROP CONSTRAINT IF EXISTS meetings_type_source_check;
ALTER TABLE meetings ADD CONSTRAINT meetings_type_source_check
    CHECK (type_source IN ('title', 'calendar', 'schedule_rule', 'admin'));

ALTER TABLE meetings DROP CONSTRAINT IF EXISTS meetings_session_kind_check;
ALTER TABLE meetings ADD CONSTRAINT meetings_session_kind_check
    CHECK (session_kind IN ('regular', 'special', 'work_session', 'budget_hearing'));

CREATE TABLE IF NOT EXISTS city_calendar_events (
    id              SERIAL PRIMARY KEY,
    municipality_id INTEGER NOT NULL REFERENCES municipalities(id) ON DELETE CASCADE,
    source_event_id TEXT NOT NULL,
    title           TEXT NOT NULL,
    starts_at       TIMESTAMPTZ NOT NULL,
    ends_at         TIMESTAMPTZ NULL,
    source_url      TEXT NOT NULL,
    categories      JSONB NOT NULL DEFAULT '[]'::jsonb,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (municipality_id, source_event_id)
);

CREATE INDEX IF NOT EXISTS idx_city_calendar_events_city_start
    ON city_calendar_events (municipality_id, starts_at);

ALTER TABLE meetings
    ADD COLUMN IF NOT EXISTS calendar_event_id INTEGER NULL REFERENCES city_calendar_events(id) ON DELETE SET NULL;

UPDATE municipalities
   SET metadata = metadata || '{"council_schedule": {"weekday": 1}, "calendar_url": "https://www.birminghamal.gov/government/city-council"}'::jsonb
 WHERE slug = 'birmingham';
"""

SQL_DOWN = r"""
UPDATE municipalities
   SET metadata = metadata - 'council_schedule' - 'calendar_url'
 WHERE slug = 'birmingham';

ALTER TABLE meetings DROP COLUMN IF EXISTS calendar_event_id;

DROP INDEX IF EXISTS idx_city_calendar_events_city_start;
DROP TABLE IF EXISTS city_calendar_events;

ALTER TABLE meetings DROP CONSTRAINT IF EXISTS meetings_session_kind_check;
ALTER TABLE meetings DROP CONSTRAINT IF EXISTS meetings_type_source_check;

ALTER TABLE meetings
    DROP COLUMN IF EXISTS type_locked_by,
    DROP COLUMN IF EXISTS type_locked_at,
    DROP COLUMN IF EXISTS type_source,
    DROP COLUMN IF EXISTS body_name,
    DROP COLUMN IF EXISTS session_kind;
"""
