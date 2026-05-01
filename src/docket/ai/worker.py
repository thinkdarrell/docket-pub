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


# ---------------------------------------------------------------------------
# Run loop (Task 14) + budget check (Task 15)
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field
from typing import Literal

from docket.ai.client import AIClient
from docket.ai.contexts import AgendaItemContext, MeetingContext
from docket.ai.exceptions import (
    AIFatalError,
    AIPermanentRowError,
    AIRateLimited,
    AITransientError,
)
from docket.ai.pricing import Usage, calculate_cost_usd, usage_add, usage_to_jsonb
from docket.config import (
    ANTHROPIC_API_KEY,
    AI_DAILY_BUDGET_USD,
    AI_ITEM_DEBOUNCE_MINUTES,
    AI_MAX_BATCH_SIZE,
)


class BudgetExceededError(Exception):
    """Today's accumulated cost exceeds AI_DAILY_BUDGET_USD."""


@dataclass
class RunSummary:
    stage: str
    rows_processed: int = 0
    rows_failed: int = 0
    cost_usd: float = 0.0
    usage: Usage = field(default_factory=lambda: Usage(0, 0, 0, 0))


def _make_client() -> AIClient:
    """Factory wrapped for monkeypatching in tests."""
    return AIClient(api_key=ANTHROPIC_API_KEY or "")


def _today_spend(conn) -> float:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COALESCE(SUM(cost_usd), 0) FROM ai_runs
             WHERE started_at >= date_trunc('day', NOW() AT TIME ZONE 'UTC')
        """)
        return float(cur.fetchone()[0])


def _open_run(conn, stage: str, model: str, notes: str | None) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO ai_runs (started_at, stage, model, notes)
            VALUES (NOW(), %s, %s, %s) RETURNING id
        """, (stage, model, notes))
        return cur.fetchone()[0]


def _close_run(conn, run_id: int, summary: RunSummary) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE ai_runs
               SET finished_at    = NOW(),
                   rows_processed = %s,
                   rows_failed    = %s,
                   usage          = %s,
                   cost_usd       = %s
             WHERE id = %s
        """, (summary.rows_processed, summary.rows_failed,
              Json(usage_to_jsonb(summary.usage)), summary.cost_usd, run_id))


def run_once(*, stage: Literal["items", "meetings"],
             limit: int = AI_MAX_BATCH_SIZE,
             notes: str | None = None,
             force_budget: bool = False) -> RunSummary:
    """Process up to `limit` rows for the given stage. Returns summary."""
    if limit > AI_MAX_BATCH_SIZE:
        limit = AI_MAX_BATCH_SIZE

    with db() as conn:
        spent = _today_spend(conn)
    if spent >= AI_DAILY_BUDGET_USD and not force_budget:
        raise BudgetExceededError(
            f"Today's AI spend ${spent:.2f} >= budget ${AI_DAILY_BUDGET_USD:.2f}; "
            f"pass force_budget=True to override"
        )

    client = _make_client()
    summary = RunSummary(stage=stage)
    model = client.item_model if stage == "items" else client.meeting_model

    with db() as conn:
        run_id = _open_run(conn, stage, model, notes)
        conn.commit()

        if stage == "items":
            _process_items(conn, client, limit, summary)
        else:
            _process_meetings(conn, client, limit, summary)

        _close_run(conn, run_id, summary)
        conn.commit()

    return summary


def _process_items(conn, client: AIClient, limit: int, summary: RunSummary) -> None:
    with conn.cursor() as cur:
        cur.execute(claim_items_sql(), (ITEM_PROMPT_VERSION, AI_ITEM_DEBOUNCE_MINUTES, limit))
        rows = cur.fetchall()

    columns = ["id", "meeting_id", "title", "description", "sponsor",
               "dollars_amount", "topic", "is_consent"]

    for row in rows:
        row_dict = dict(zip(columns, row))
        ctx = AgendaItemContext.from_row(row_dict)
        try:
            result, usage = client.summarize_item(ctx)
            write_item_result(conn, row_dict["id"], result, model=client.item_model)
            summary.usage = usage_add(summary.usage, usage)
            summary.cost_usd += calculate_cost_usd(client.item_model, usage)
            summary.rows_processed += 1
            conn.commit()
        except AIRateLimited:
            log.warning("Rate limited; ending batch")
            conn.rollback()
            break
        except AITransientError as e:
            log.warning("Transient error on item %s: %s", row_dict["id"], e)
            conn.rollback()
            continue
        except AIPermanentRowError as e:
            log.error("Permanent failure on item %s: %s", row_dict["id"], e)
            conn.rollback()
            mark_item_failed(conn, row_dict["id"], reason=str(e)[:200])
            summary.rows_failed += 1
            conn.commit()
        except AIFatalError:
            log.critical("Fatal error; exiting")
            conn.rollback()
            raise


def _process_meetings(conn, client: AIClient, limit: int, summary: RunSummary) -> None:
    with conn.cursor() as cur:
        cur.execute(claim_meetings_sql(),
                    (MEETING_PROMPT_VERSION, ITEM_PROMPT_VERSION, limit))
        rows = cur.fetchall()

    for row in rows:
        meeting_id, meeting_type, meeting_date, minutes_adopted_at, ai_metadata = row
        with conn.cursor() as cur:
            cur.execute("""
                SELECT summary
                  FROM agenda_items
                 WHERE meeting_id = %s
                   AND COALESCE(ai_metadata->>'is_substantive', '') = 'true'
                   AND summary IS NOT NULL
                 ORDER BY id
            """, (meeting_id,))
            item_summaries = [r[0] for r in cur.fetchall()]

        if not item_summaries:
            mark_meeting_empty(conn, meeting_id)
            conn.commit()
            summary.rows_processed += 1
            continue

        phase = "adopted" if minutes_adopted_at else "provisional"
        ctx = MeetingContext(
            meeting_id=meeting_id, meeting_type=meeting_type,
            meeting_date=meeting_date, phase=phase,
            item_summaries=item_summaries,
        )
        try:
            result, usage = client.summarize_meeting(ctx)
            write_meeting_result(conn, meeting_id, result, model=client.meeting_model)
            summary.usage = usage_add(summary.usage, usage)
            summary.cost_usd += calculate_cost_usd(client.meeting_model, usage)
            summary.rows_processed += 1
            conn.commit()
        except AIRateLimited:
            log.warning("Rate limited; ending batch")
            conn.rollback()
            break
        except AITransientError as e:
            log.warning("Transient error on meeting %s: %s", meeting_id, e)
            conn.rollback()
            continue
        except AIPermanentRowError as e:
            log.error("Permanent failure on meeting %s: %s", meeting_id, e)
            conn.rollback()
            summary.rows_failed += 1
        except AIFatalError:
            conn.rollback()
            raise
