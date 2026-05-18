"""Migration 031 — voice column for forward-voice (upcoming) AI text.

Adds:
  - agenda_items.ai_rewrite_voice text NULL — values 'completed' | 'upcoming'
  - meetings.executive_summary_voice text NULL — same values

Backfill: every row with non-NULL ai_rewrite_version / executive_summary today
is in completed voice (no upcoming prompt has ever run). Mark them explicitly
so the re-cascade query can rely on the column.

Spec: docs/superpowers/specs/2026-05-18-upcoming-meeting-forward-voice-design.md
"""
from __future__ import annotations


SQL_UP = r"""
ALTER TABLE agenda_items
    ADD COLUMN IF NOT EXISTS ai_rewrite_voice text;

ALTER TABLE meetings
    ADD COLUMN IF NOT EXISTS executive_summary_voice text;

UPDATE agenda_items
   SET ai_rewrite_voice = 'completed'
 WHERE ai_rewrite_version IS NOT NULL
   AND ai_rewrite_voice IS NULL;

UPDATE meetings
   SET executive_summary_voice = 'completed'
 WHERE executive_summary IS NOT NULL
   AND executive_summary_voice IS NULL;
"""

SQL_DOWN = r"""
ALTER TABLE meetings DROP COLUMN IF EXISTS executive_summary_voice;
ALTER TABLE agenda_items DROP COLUMN IF EXISTS ai_rewrite_voice;
"""
