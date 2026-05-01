"""Batch worker: claims rows, calls AIClient, writes back.

This file currently only exposes the two claim-query SQL builders.
Subsequent tasks (T12-T15) extend it with write-back, run loop, and
budget controls.
"""

from __future__ import annotations

import logging

from docket.db import db


log = logging.getLogger(__name__)


def claim_items_sql() -> str:
    """Returns the SELECT SQL. Args: (current_item_version, debounce_minutes, limit)."""
    return """
        SELECT id, meeting_id, title, description, sponsor, dollars_amount, topic, is_consent
        FROM agenda_items
        WHERE (ai_prompt_version IS NULL OR ai_prompt_version < %s)
          AND created_at < NOW() - (%s || ' minutes')::interval
        ORDER BY id
        FOR UPDATE SKIP LOCKED
        LIMIT %s
    """


def claim_meetings_sql() -> str:
    """Returns the SELECT SQL. Args: (current_meeting_version, current_item_version, limit).

    A meeting is claimable if EITHER:
      (a) provisional pass:  ai_prompt_version != current AND minutes_adopted_at IS NULL
                             AND all items at current item version
                             AND ai_metadata.phase != 'provisional'
      (b) adopted pass:      minutes_adopted_at IS NOT NULL AND ai_metadata.phase != 'adopted'
    """
    return """
        SELECT m.id, m.meeting_type, m.meeting_date, m.minutes_adopted_at, m.ai_metadata
        FROM meetings m
        WHERE (
            -- (a) provisional pass
            ((m.ai_prompt_version IS NULL OR m.ai_prompt_version < %s)
             AND m.minutes_adopted_at IS NULL
             AND COALESCE(m.ai_metadata->>'phase', '') != 'provisional'
             AND NOT EXISTS (
               SELECT 1 FROM agenda_items ai
               WHERE ai.meeting_id = m.id
                 AND (ai.ai_prompt_version IS NULL OR ai.ai_prompt_version < %s)
             ))
            OR
            -- (b) adopted pass
            (m.minutes_adopted_at IS NOT NULL
             AND COALESCE(m.ai_metadata->>'phase', '') != 'adopted')
          )
        ORDER BY m.id
        FOR UPDATE OF m SKIP LOCKED
        LIMIT %s
    """
