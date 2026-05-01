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


import json
from psycopg2.extras import Json

from docket.ai.prompts import ITEM_PROMPT_VERSION, MEETING_PROMPT_VERSION
from docket.ai.results import ItemAIResult, MeetingAIResult


def write_item_result(conn, item_id: int, result: ItemAIResult, *, model: str) -> None:
    """Update an agenda_item row with AI output."""
    metadata = {
        "significance_rationale": result.significance_rationale,
        "consent_placement_rationale": result.consent_placement_rationale,
        "confidence": result.confidence,
        "is_substantive": result.is_substantive,
        "model": model,
    }
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE agenda_items
               SET summary                 = %s,
                   significance_score      = %s,
                   consent_placement_score = %s,
                   ai_metadata             = %s,
                   ai_prompt_version       = %s,
                   ai_generated_at         = NOW()
             WHERE id = %s
        """, (
            result.summary,
            result.significance_score,
            result.consent_placement_score,
            Json(metadata),
            ITEM_PROMPT_VERSION,
            item_id,
        ))


def mark_item_failed(conn, item_id: int, reason: str) -> None:
    """Permanently mark an item as completed_failed: summary stays NULL, version bumped."""
    metadata = {
        "confidence": "low",
        "is_substantive": None,
        "error": reason,
        "model": None,
    }
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE agenda_items
               SET ai_metadata       = %s,
                   ai_prompt_version = %s,
                   ai_generated_at   = NOW()
             WHERE id = %s
        """, (Json(metadata), ITEM_PROMPT_VERSION, item_id))


def write_meeting_result(conn, meeting_id: int, result: MeetingAIResult, *, model: str) -> None:
    metadata = {
        "phase": result.phase,
        "is_substantive": result.is_substantive,
        "substantive_item_count": result.substantive_item_count,
        "confidence": result.confidence,
        "model": model,
    }
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE meetings
               SET executive_summary = %s,
                   ai_metadata       = %s,
                   ai_prompt_version = %s,
                   ai_generated_at   = NOW()
             WHERE id = %s
        """, (result.executive_summary, Json(metadata), MEETING_PROMPT_VERSION, meeting_id))


def mark_meeting_empty(conn, meeting_id: int) -> None:
    """Skip Sonnet call: meeting has zero substantive items."""
    metadata = {
        "phase": "provisional",
        "is_substantive": False,
        "substantive_item_count": 0,
        "confidence": "high",
        "model": None,
    }
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE meetings
               SET ai_metadata       = %s,
                   ai_prompt_version = %s,
                   ai_generated_at   = NOW()
             WHERE id = %s
        """, (Json(metadata), MEETING_PROMPT_VERSION, meeting_id))
