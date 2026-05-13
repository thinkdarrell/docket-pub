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


def claim_items_v3_sql() -> str:
    """Claim items for v3 pipeline processing.

    v3 filters on processing_status + the extraction/rewrite version
    columns — NOT on the v2 ai_prompt_version column. SELECT FOR UPDATE
    SKIP LOCKED ensures multiple workers don't double-process.

    Decision #45 + plan §B5: items in 'pending' state are eligible. Items
    in 'cross_stage_conflict' are NOT picked up — they wait for admin
    resolution via the G4 review UI.

    NOTE: this helper does NOT enforce a debounce equivalent to v2's
    AI_ITEM_DEBOUNCE_MINUTES. The v3 pipeline's expectation is that
    Phase 1's Wave 0 pre-classifier sets processing_status='pending'
    only for items that survived data-quality + procedural gates — i.e.,
    a debounce isn't needed because the eligibility filter is precise.
    If a debounce is wanted later, add it.

    Ordering: ``m.meeting_date DESC, ai.id ASC``. Newest meetings are
    claimed first so freshly ingested items always render with the v3
    smart-brevity card within one cron tick — the historical backfill
    (36K+ pending items going back to 2025-11) consumes leftover budget
    after recent items are drained. The original ASC ordering buried
    recent items at the tail of the queue, where they were effectively
    never reached at the ~200 items/day cron pace (2026-05-13 incident).
    """
    return """
        SELECT ai.id, ai.meeting_id, ai.title, ai.description,
               ai.sponsor, ai.dollars_amount, ai.topic, ai.is_consent,
               m.municipality_id AS city_id,
               muni.name         AS city_name
          FROM agenda_items ai
          JOIN meetings m ON m.id = ai.meeting_id
          JOIN municipalities muni ON muni.id = m.municipality_id
         WHERE ai.processing_status = 'pending'::processing_status_enum
           AND (
                ai.ai_extraction_version IS NULL
             OR ai.ai_extraction_version < %s
             OR ai.ai_rewrite_version IS NULL
             OR ai.ai_rewrite_version < %s
           )
         ORDER BY m.meeting_date DESC NULLS LAST, ai.id ASC
         LIMIT %s
         FOR UPDATE OF ai SKIP LOCKED
    """


def claim_meetings_sql() -> str:
    """Returns the SELECT SQL. Args: (current_meeting_version, current_item_version, limit).

    A meeting is claimable if EITHER:
      (a) provisional pass:  ai_prompt_version < current AND minutes_adopted_at IS NULL
                             AND all items at current item version
                             (version check alone gates re-runs; phase guard removed so
                              prompt-version bumps re-cascade through already-provisional rows)
      (b) adopted pass:      minutes_adopted_at IS NOT NULL AND ai_metadata.phase != 'adopted'
    """
    return """
        SELECT m.id, m.meeting_type, m.meeting_date, m.minutes_adopted_at, m.ai_metadata
        FROM meetings m
        WHERE (
            -- (a) provisional pass
            ((m.ai_prompt_version IS NULL OR m.ai_prompt_version < %s)
             AND m.minutes_adopted_at IS NULL
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


def mark_meeting_failed(conn, meeting_id: int, reason: str) -> None:
    """Permanently mark a meeting as completed_failed: executive_summary stays NULL,
    ai_prompt_version bumped so the row is not re-claimed indefinitely."""
    metadata = {
        "phase": None,
        "is_substantive": None,
        "confidence": "low",
        "error": reason,
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
               SET executive_summary = NULL,
                   ai_metadata       = %s,
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
    AI_ITEM_MODEL,
    AI_MAX_BATCH_SIZE,
    AI_MEETING_MODEL,
    IMPACT_FIRST_ENABLED,
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

    # v2 needs an AIClient for both items + meetings; v3 (items
    # only) does not. Construct lazily so the v3 path doesn't
    # pay the import / API-key check.
    client = _make_client() if (stage == "meetings" or not IMPACT_FIRST_ENABLED) else None
    summary = RunSummary(stage=stage)
    if client is not None:
        model = client.item_model if stage == "items" else client.meeting_model
    else:
        # v3 path: model is unused for budget-validation purposes here
        # (extract/rewrite have their own module-level clients with
        # model IDs baked in). Use the configured item model for the
        # ai_runs row. AI_ITEM_MODEL is now a top-level import (R2).
        model = AI_ITEM_MODEL

    # Validate model is in PRICING before any API call so cost tracking
    # cannot fail mid-batch with an unhandled KeyError. Misconfigured model
    # is a fatal config error, not a transient one.
    from docket.ai.pricing import PRICING
    if model not in PRICING:
        # R2: reference the config constants instead of client.* attributes
        # — the v3 lazy-construction path leaves client=None, so dereferencing
        # client.item_model would raise AttributeError and mask this AIFatalError.
        raise AIFatalError(
            f"Model {model!r} has no entry in docket.ai.pricing.PRICING; "
            f"add per-token rates before running. Configured models: "
            f"AI_ITEM_MODEL={AI_ITEM_MODEL!r}, AI_MEETING_MODEL={AI_MEETING_MODEL!r}"
        )

    with db() as conn:
        run_id = _open_run(conn, stage, model, notes)
        conn.commit()

        if stage == "items":
            if IMPACT_FIRST_ENABLED:
                _process_items_v3(conn, limit, summary)
            else:
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
                SELECT summary, significance_score, topic, title
                  FROM agenda_items
                 WHERE meeting_id = %s
                   AND COALESCE(ai_metadata->>'is_substantive', '') = 'true'
                   AND summary IS NOT NULL
                 ORDER BY significance_score DESC NULLS LAST, id
            """, (meeting_id,))
            item_rows = [
                {"summary": r[0], "significance_score": r[1], "topic": r[2], "title": r[3]}
                for r in cur.fetchall()
            ]

        if not item_rows:
            mark_meeting_empty(conn, meeting_id)
            conn.commit()
            summary.rows_processed += 1
            continue

        phase = "adopted" if minutes_adopted_at else "provisional"
        ctx = MeetingContext.from_meeting_items(
            meeting_id=meeting_id,
            meeting_type=meeting_type,
            meeting_date=meeting_date,
            phase=phase,
            rows=item_rows,
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
            mark_meeting_failed(conn, meeting_id, reason=str(e)[:200])
            summary.rows_failed += 1
            conn.commit()
        except AIFatalError:
            conn.rollback()
            raise


# ---------------------------------------------------------------------------
# v3 worker path — pipeline.process_item dispatch (B5)
# ---------------------------------------------------------------------------


class _AttrAccess:
    """Lightweight dict → attribute access for pipeline.process_item.

    pipeline.process_item duck-types the item; this class adapts the
    claim_items_v3_sql row dict to that shape. Equivalent to the
    SimpleNamespace pattern but minimally scoped.
    """
    def __init__(self, d: dict):
        self.__dict__.update(d)


def _process_items_v3(conn, limit: int, summary: RunSummary) -> None:
    """v3 per-item loop: calls pipeline.process_item per claimed row.

    Differs from v2 (_process_items):
      - No AIClient argument (extract/rewrite have module-level clients).
      - No usage tracking — v3 pipeline doesn't thread the Usage struct
        through extraction.py/rewrite.py yet (B5 v1 gap; flag as
        follow-up). summary.cost_usd stays at 0.0; summary.rows_processed
        counts items, summary.rows_failed counts permanent failures.
      - Per-row commit after pipeline.process_item returns. Lock from
        claim_items_v3_sql is held across the LLM calls (same shape
        as v2). Single-instance worker assumption preserved.

    Spec: section 7.5, decisions #45, #57.
    """
    from docket.ai import pipeline
    from docket.ai.extraction import EXTRACTION_PROMPT_VERSION
    from docket.ai.rewrite import ITEM_REWRITE_PROMPT_VERSION

    with conn.cursor() as cur:
        cur.execute(
            claim_items_v3_sql(),
            (EXTRACTION_PROMPT_VERSION, ITEM_REWRITE_PROMPT_VERSION, limit),
        )
        rows = cur.fetchall()

    columns = ["id", "meeting_id", "title", "description",
               "sponsor", "dollars_amount", "topic", "is_consent",
               "city_id", "city_name"]

    for row in rows:
        row_dict = dict(zip(columns, row))
        # agenda_items has no source_type column; default to 'agenda'
        # so wave0's evaluate_data_quality + Stage 2 prompt construction
        # can read the attribute. Mirrors run_wave_0's hard-coded 'pdf'
        # default — both choices are conservative for the LLM-eligible
        # subset (Wave 0 already classified these as `pending`).
        row_dict.setdefault("source_type", "agenda")
        # raw_text is also referenced by wave0 — same shape as source_type.
        row_dict.setdefault("raw_text", None)
        # Duck-typed item — pipeline.process_item accepts any object
        # with the attributes documented in its docstring.
        item = _AttrAccess(row_dict)
        try:
            # Pass conn so Phase C's UPDATE uses the SAME connection that
            # holds the FOR UPDATE row lock from claim_items_v3_sql.
            # Without this, the pipeline opens a fresh db() connection
            # that blocks forever on the row lock (#57 — no PG deadlock
            # detection because there's no cycle in the wait graph).
            pipeline.process_item(item, conn=conn)
            summary.rows_processed += 1
            conn.commit()
        except AIRateLimited:
            log.warning("Rate limited; ending v3 batch")
            conn.rollback()
            break
        except AITransientError as e:
            log.warning("v3 transient error on item %s: %s", row_dict["id"], e)
            conn.rollback()
            continue
        except AIPermanentRowError as e:
            log.error("v3 permanent failure on item %s: %s", row_dict["id"], e)
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agenda_items
                       SET processing_status = 'failed_permanent'::processing_status_enum,
                           last_error_at     = NOW(),
                           last_error_message = %s
                     WHERE id = %s
                    """,
                    (str(e)[:500], row_dict["id"]),
                )
            summary.rows_failed += 1
            conn.commit()
        except AIFatalError:
            log.critical("v3 fatal error; exiting")
            conn.rollback()
            raise
