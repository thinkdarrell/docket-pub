"""Migration 032 — meetings.start_time for per-meeting upcoming-transition timing.

Adds nullable TIME column. Adapters that already pull a time component
(Granicus hidden timestamp, CivicClerk eventDate) start persisting it on the
next ingest cycle. Meetings with NULL start_time fall back to noon CT in the
is_upcoming() helper.

Spec: docs/superpowers/plans/2026-05-19-upcoming-meeting-transition-buffer.md
"""
from __future__ import annotations


SQL_UP = r"""
ALTER TABLE meetings
    ADD COLUMN IF NOT EXISTS start_time TIME NULL;
"""

SQL_DOWN = r"""
ALTER TABLE meetings DROP COLUMN IF EXISTS start_time;
"""
