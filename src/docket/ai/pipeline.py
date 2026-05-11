"""Per-item pipeline orchestrator — Tracks 1+2+3 convergence (Task B5).

Wraps the full v3 pipeline for a single agenda item:

  Wave 0 (data_quality + procedural pre-pass, no LLM)
   → Stage 1 (extraction.extract_facts_for_item — Haiku 4.5 tool-use)
   → Stage 2 (rewrite.rewrite_item — Haiku 4.5 tool-use)
   → Stage 2.5 (floors.apply_score_floors — deterministic post-pass)
   → reconcile (reconcile.reconcile_stages with auto-retry once)
   → atomic commit (extraction + rewrite + scores + on-write badges + policy badges)

Two exported entry points:

- ``process_item(item) -> str`` — full pipeline, used by the v3 worker
  (``_process_items_v3``) when ``IMPACT_FIRST_ENABLED=true``.
- ``_rerun_from_stage2(item, facts, *, override_instruction=None) -> str``
  — partial pipeline starting at Stage 2, used by:
    1. ``process_item`` itself (after Stage 1 returns); and
    2. G4's ``services/conflict_resolution`` admin actions
       (``re_prompt_stage_2``, ``edit_stage_1_facts``) when admins request a
       Stage 2 re-run with override.

The split exists because G4 ships the conflict-resolution UI before B5
exists, and G4's resolution actions operate on items that already have
Stage 1 facts persisted. ``_rerun_from_stage2`` lets the admin paths
skip Stage 1 (which would otherwise overwrite their carefully-edited
facts).

Transaction shape:
- Phase A (DB write, short): Wave 0 short-circuit only — sets
  processing_status to data_quality_skipped / procedural_skipped.
- Phase B (no held DB connection): LLM calls (Stage 1, Stage 2,
  optional Stage 2 retry) + CPU (floors, reconcile). A single brief
  cursor opens during Stage 2.5 floors for the per-city threshold
  override lookup; the cursor closes before Stage 2 or any retry runs.
- Phase C (atomic DB write): single transaction commits extraction +
  rewrite + scores + on-write process badges + policy badges + final
  processing_status.

If any step in Phase B raises (AIRateLimited, AITransientError,
network), no row state changes — Stage 1's cost is wasted on retry.
This is the all-or-none design from plan §B5 decision (alternative:
persist Stage 1 immediately is a documented trade-off; not chosen for
v1).

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md
sections 1, 3, 7.5; decisions #45, #57, #92.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from docket.ai.extraction import (
    EXTRACTION_PROMPT_VERSION,
    extract_facts_for_item,
)
from docket.ai.extraction_schema import StructuredFacts
from docket.ai.floors import apply_score_floors
from docket.ai.reconcile import reconcile_stages
from docket.ai.rewrite import ITEM_REWRITE_PROMPT_VERSION, rewrite_item
from docket.ai.rewrite_schema import ItemRewrite
from docket.ai.wave0 import evaluate_data_quality, is_procedural
from docket.ai.badges_process import compute_on_write_process_badges
from docket.ai.badges_policy import compute_policy_badges
from docket.db import db
from docket.services.badges import get_enabled_policy_slugs

log = logging.getLogger(__name__)


class PipelineConcurrencyError(RuntimeError):
    """Raised by ``_rerun_from_stage2`` when the optional ``expected_status``
    guard fires: the row's ``processing_status`` changed between the caller's
    read and the pipeline's Phase C UPDATE, and the pipeline declined to
    overwrite. The Phase C transaction rolls back via this exception's exit
    from the ``with db()`` block — no partial writes.

    Worker path passes ``expected_status=None`` (it holds the per-row
    FOR UPDATE SKIP LOCKED lock for the duration of the transaction, so the
    race window doesn't exist). Admin paths in
    ``services/conflict_resolution.py`` pass
    ``expected_status='cross_stage_conflict'`` and catch this exception,
    write a ``*_lost_race`` audit row, and re-raise as
    ``ConflictAlreadyResolvedError`` for the route layer. Decision #13.
    """


def process_item(item) -> str:
    """Run the full per-item v3 pipeline against an agenda item.

    Args:
        item: duck-typed object exposing:
            - id (int)
            - city_id (int) — from joined meetings.municipality_id
            - city_name (str) — from joined municipalities.name
            - title, description, sponsor, dollars_amount (per Stage 2 prompt)
            - topic, is_consent, source_type (per Stage 2 prompt)
            See ``_ItemView`` in tests/integration/test_pipeline_e2e.py
            for the test-side adapter; the v3 worker constructs an
            equivalent shape from claim_items_v3_sql rows.

    Returns:
        Final ``processing_status`` value (one of):
          - 'data_quality_skipped'  (Wave 0a rejected)
          - 'procedural_skipped'    (Wave 0b matched)
          - 'completed'             (Stage 1+2 + reconcile success)
          - 'cross_stage_conflict'  (reconcile escalated after retry)

    Raises:
        - ``AIRateLimited``, ``AITransientError`` — bubble from
          extract_facts_for_item / rewrite_item; worker handles per-item
          recovery (skip + log) per its existing patterns.
        - ``AIFatalError`` — bubble; worker stops the batch.
        - ``AIPermanentRowError`` — bubble; worker marks the row as
          failed_permanent.
    """
    # Phase A — Wave 0 short-circuit ----------------------------------
    quality, priority = evaluate_data_quality(item)
    if quality != "ok":
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agenda_items
                   SET data_quality       = %s::data_quality_enum,
                       data_debt_priority = %s::data_debt_priority_enum,
                       processing_status  = 'data_quality_skipped'::processing_status_enum
                 WHERE id = %s
                """,
                (quality, priority, item.id),
            )
        log.info(
            "pipeline.process_item Wave 0a reject: item_id=%s quality=%s",
            item.id, quality,
        )
        return "data_quality_skipped"

    if is_procedural(item.title):
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agenda_items
                   SET data_quality      = 'ok'::data_quality_enum,
                       processing_status = 'procedural_skipped'::processing_status_enum
                 WHERE id = %s
                """,
                (item.id,),
            )
        log.info(
            "pipeline.process_item Wave 0b match: item_id=%s",
            item.id,
        )
        return "procedural_skipped"

    # Phase B (part 1) — Stage 1 extraction (LLM) ---------------------
    facts, _served_extract = extract_facts_for_item(item)

    # Delegate to _rerun_from_stage2 for the rest of the pipeline.
    # Keeps the Stage 2+ code path identical between the worker's
    # full-pipeline call and the G4 conflict-resolution admin paths.
    return _rerun_from_stage2(item, facts)


def _rerun_from_stage2(
    item,
    facts: StructuredFacts,
    *,
    override_instruction: str | None = None,
    expected_status: str | None = None,
) -> str:
    """Run Stage 2 → 2.5 → reconcile → atomic commit.

    Used by:
      - ``process_item`` after Stage 1 succeeds (no override, no guard).
      - G4's conflict-resolution admin actions ``re_prompt_stage_2``
        and ``edit_stage_1_facts`` (with admin override instruction
        AND expected_status='cross_stage_conflict' for the concurrency
        guard).

    Args:
        item: as ``process_item``.
        facts: Stage 1 ``StructuredFacts`` — either freshly extracted
            or admin-edited.
        override_instruction: optional admin override appended to the
            Stage 2 user message. None for the worker's happy path;
            the instruction text for admin re-prompts.
        expected_status: optional concurrency guard (decision #13).
            When None (worker path), Phase C UPDATE runs unconditionally
            — safe because the worker holds the per-row SKIP LOCKED
            lock. When a string (admin paths), Phase C UPDATE adds
            ``AND processing_status = %s`` as a guard; if cur.rowcount
            is 0, the function raises ``PipelineConcurrencyError``
            and Phase C's transaction rolls back via the ``with db()``
            exception path — no partial writes.

    Returns:
        Final ``processing_status`` value: 'completed' or 'cross_stage_conflict'.

    Raises:
        - ``PipelineConcurrencyError`` — when ``expected_status`` was
          supplied and the row's actual status no longer matches.
          Phase C's whole transaction (including persist_extraction)
          rolls back; no writes commit.
        - Anthropic SDK exceptions (``AIRateLimited``, etc.) — bubble.
    """
    enabled_slugs = list(get_enabled_policy_slugs(item.city_id))

    # Phase B (part 2) — Stage 2 rewrite (LLM) ------------------------
    rewrite, _served_rewrite = rewrite_item(
        item, facts, enabled_slugs,
        extra_instruction=override_instruction,
    )

    # Phase B (part 3) — Stage 2.5 floors (CPU + brief DB) ------------
    # apply_score_floors needs a cursor for per-city threshold overrides
    # (city_score_floor_overrides table). Brief, non-LLM-spanning DB use.
    with db() as conn, conn.cursor() as cur:
        overrides = apply_score_floors(cur, item, facts, rewrite, item.city_id)

    # Phase B (part 4) — Reconcile (CPU, possibly one LLM retry) ------
    result = reconcile_stages(facts, rewrite, item, already_retried=False)
    if result.action == "retry_stage2_with_override":
        # Auto-retry once with the reconcile-generated override.
        # (Decision #45 — the worker auto-retry path.)
        rewrite, _served_retry = rewrite_item(
            item, facts, enabled_slugs,
            extra_instruction=result.override_instruction,
        )
        with db() as conn, conn.cursor() as cur:
            overrides = apply_score_floors(
                cur, item, facts, rewrite, item.city_id,
            )
        result = reconcile_stages(facts, rewrite, item, already_retried=True)

    final_status = (
        "cross_stage_conflict"
        if result.action == "mark_cross_stage_conflict"
        else "completed"
    )

    # Phase C — Atomic commit -----------------------------------------
    overrides_jsonb = json.dumps({
        "conflicts": result.conflicts,
        "original_ai_significance": overrides.original_ai_significance,
        "final_significance": overrides.final_significance,
        "original_ai_consent": overrides.original_ai_consent,
        "final_consent": overrides.final_consent,
        "triggers": overrides.triggers,
        "admin_override_used": override_instruction is not None,
    })

    with db() as conn, conn.cursor() as cur:
        # Inline extraction write — mirrors persist_extraction but omits
        # its `processing_status = 'extracted'` side-effect. Setting the
        # status to 'extracted' here would (a) be immediately overwritten
        # by the Phase C UPDATE below, AND (b) break the expected_status
        # guard (decision #13) by changing the status mid-Phase-C, so the
        # guard would fire spuriously on internal writes. The Phase C
        # UPDATE below is the single source of truth for processing_status.
        cur.execute(
            """
            UPDATE agenda_items
               SET extracted_facts = %s::jsonb,
                   ai_extraction_version = %s
             WHERE id = %s
            """,
            [facts.model_dump_json(), EXTRACTION_PROMPT_VERSION, item.id],
        )

        # Phase C UPDATE with optional concurrency guard (decision #13).
        # The `(%s::text IS NULL OR processing_status = %s)` predicate
        # is a no-op when expected_status is None (worker path) and a
        # hard guard when expected_status is supplied (admin paths).
        cur.execute(
            """
            UPDATE agenda_items
               SET headline                = %s,
                   why_it_matters          = %s,
                   significance_score      = %s,
                   consent_placement_score = %s,
                   ai_confidence           = %s,
                   ai_rewrite_version      = %s,
                   score_overrides         = %s::jsonb,
                   processing_status       = %s::processing_status_enum
             WHERE id = %s
               AND (%s::text IS NULL OR processing_status = %s::processing_status_enum)
            """,
            (
                rewrite.headline,
                rewrite.why_it_matters,
                overrides.final_significance,
                overrides.final_consent,
                rewrite.confidence,
                ITEM_REWRITE_PROMPT_VERSION,
                overrides_jsonb,
                final_status,
                item.id,
                expected_status,
                expected_status,
            ),
        )

        if expected_status is not None and cur.rowcount == 0:
            # Concurrency guard fired. Roll back the whole Phase C
            # (including persist_extraction's write) by raising — the
            # `with db()` context manager catches and rolls back.
            log.info(
                "pipeline._rerun_from_stage2 concurrency guard fired: "
                "item_id=%s expected_status=%s — rolling back Phase C",
                item.id, expected_status,
            )
            raise PipelineConcurrencyError(
                f"item {item.id} status no longer matches "
                f"expected_status={expected_status!r}; Phase C rolled back"
            )

        # On-write process badges (decision #57: SQL + on-write must agree).
        # Decision #92: include city_id in every INSERT.
        for slug, conf in compute_on_write_process_badges(
            item, facts, overrides, rewrite.confidence,
        ):
            cur.execute(
                """
                INSERT INTO agenda_item_badges
                  (agenda_item_id, city_id, badge_slug, kind, confidence,
                   source, matching_metadata)
                VALUES (%s, %s, %s, 'process', %s, 'deterministic', '{}'::jsonb)
                ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING
                """,
                (item.id, item.city_id, slug, conf),
            )

        # Policy badges (deterministic + LLM-suggested per Section D).
        for slug, conf, source, metadata in compute_policy_badges(
            item, facts, rewrite, item.city_id,
        ):
            cur.execute(
                """
                INSERT INTO agenda_item_badges
                  (agenda_item_id, city_id, badge_slug, kind, confidence,
                   source, matching_metadata)
                VALUES (%s, %s, %s, 'policy', %s, %s, %s::jsonb)
                ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING
                """,
                (item.id, item.city_id, slug, conf, source, json.dumps(metadata)),
            )

    log.info(
        "pipeline._rerun_from_stage2 done: item_id=%s status=%s override=%s",
        item.id, final_status, override_instruction is not None,
    )
    return final_status
