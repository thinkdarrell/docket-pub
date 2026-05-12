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
from contextlib import contextmanager
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


@contextmanager
def _maybe_cursor(conn):
    """Yield a cursor on `conn` if provided, else open a fresh ``db()``.

    Fix for #57: the v3 worker (``_process_items_v3``) holds row locks via
    ``SELECT ... FOR UPDATE SKIP LOCKED`` on its own connection across the
    call to ``process_item``. If the pipeline opens a new connection via
    ``db()`` and tries to UPDATE the same row in Phase C, the new connection
    blocks forever waiting for the worker's lock — PostgreSQL can't detect
    this because there's no cycle (the worker conn isn't waiting on anything,
    just holding the lock). Passing the worker's conn through avoids this.

    When ``conn`` is provided:
      - The block uses its cursor.
      - No commit/rollback/close — the caller owns the transaction.
      - Exceptions propagate; the caller decides whether to rollback.

    When ``conn`` is ``None`` (admin / one-off paths):
      - A fresh connection is opened via ``db()``, which commits on success,
        rolls back on exception, and always closes. Preserves the existing
        rollback semantics for the ``expected_status`` concurrency guard
        (decision #13).
    """
    if conn is not None:
        with conn.cursor() as cur:
            yield cur
    else:
        with db() as fresh, fresh.cursor() as cur:
            yield cur


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


def process_item(item, *, conn=None) -> str:
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
        conn: optional psycopg2 connection. The v3 worker
            (``_process_items_v3``) MUST pass its own connection here —
            without it, the pipeline opens fresh ``db()`` connections for
            Phase A / 2.5 / C writes and Phase C's UPDATE blocks forever
            on the row lock the worker holds (#57). Admin / one-off
            callers leave ``conn=None`` and the pipeline opens its own
            connections (with the existing commit/rollback semantics).

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
        with _maybe_cursor(conn) as cur:
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
        with _maybe_cursor(conn) as cur:
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
    return _rerun_from_stage2(item, facts, conn=conn)


def _rerun_from_stage2(
    item,
    facts: StructuredFacts,
    *,
    override_instruction: str | None = None,
    expected_status: str | None = None,
    already_retried: bool = False,
    conn=None,
) -> str:
    """Run Stage 2 → 2.5 → reconcile → atomic commit.

    Used by:
      - ``process_item`` after Stage 1 succeeds (no override, no guard,
        ``already_retried=False`` — full auto-retry behavior on reconcile).
      - G4's conflict-resolution admin actions ``re_prompt_stage_2``
        and ``edit_stage_1_facts`` (with admin override instruction
        AND ``expected_status='cross_stage_conflict'`` for the
        concurrency guard AND ``already_retried=True`` to suppress the
        auto-retry — admin re-runs are explicit one-shots).

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
        already_retried: A1 review-driven addition. When False (worker
            default), the first ``reconcile_stages`` call uses
            ``already_retried=False`` — if reconcile says
            ``retry_stage2_with_override``, this function auto-retries
            Stage 2 with reconcile's machine-generated override
            (decision #45). When True (admin paths), the first
            ``reconcile_stages`` call uses ``already_retried=True``
            — reconcile.py L66-67 short-circuits the retry branch to
            ``mark_cross_stage_conflict``, so no second LLM call ever
            fires. Preserves G4's pre-refactor one-shot semantics on
            admin clicks: an admin override that doesn't produce a
            substantive verdict surfaces as ``cross_stage_conflict``
            in one shot, not two.
        conn: optional psycopg2 connection (fix for #57). The worker
            passes its own connection so Phase C's UPDATE doesn't
            self-deadlock against the worker's ``FOR UPDATE`` row lock.
            Admin paths pass ``None`` and get the fresh-``db()``
            behavior with auto-commit/rollback that preserves the
            ``expected_status`` guard rollback semantics.

    Returns:
        Final ``processing_status`` value: 'completed' or 'cross_stage_conflict'.

    Raises:
        - ``PipelineConcurrencyError`` — when ``expected_status`` was
          supplied and the row's actual status no longer matches.
          Phase C's whole transaction (including the inline extraction
          UPDATE) rolls back; no writes commit.
        - Anthropic SDK exceptions (``AIRateLimited``, etc.) — bubble.
    """
    enabled_slugs = list(get_enabled_policy_slugs(item.city_id))

    # Phase B (part 2) — Stage 2 rewrite (LLM) ------------------------
    rewrite, _served_rewrite = rewrite_item(
        item, facts, enabled_slugs,
        extra_instruction=override_instruction,
    )

    # Reconcile pre-check for the auto-retry path (decision #45).
    # Admin paths pass already_retried=True and skip this entirely —
    # reconcile.py short-circuits to mark_cross_stage_conflict in that
    # case, so no second LLM call ever fires.
    if not already_retried:
        precheck = reconcile_stages(facts, rewrite, item, already_retried=False)
        if precheck.action == "retry_stage2_with_override":
            # Worker auto-retry: one extra LLM call with the
            # reconcile-generated override prompt.
            rewrite, _served_retry = rewrite_item(
                item, facts, enabled_slugs,
                extra_instruction=precheck.override_instruction,
            )

    # Finalize is shared with batch_ingest: floors → reconcile
    # (already_retried=True) → Phase C atomic commit.
    return finalize_from_rewrite(
        item, facts, rewrite,
        conn=conn,
        override_instruction=override_instruction,
        expected_status=expected_status,
    )


def finalize_from_rewrite(
    item,
    facts: StructuredFacts,
    rewrite: ItemRewrite,
    *,
    conn=None,
    override_instruction: str | None = None,
    expected_status: str | None = None,
) -> str:
    """Run Stage 2.5 floors → reconcile (one-shot) → atomic Phase C commit.

    Pure post-LLM logic — does NOT call Anthropic. Shared by:
      - ``_rerun_from_stage2`` (after its rewrite_item call, optionally
        after one auto-retry).
      - ``docket.ai.batch_ingest`` for results returned by Anthropic's
        Batches API, where the rewrite came back in a downloaded
        ``MessageBatchIndividualResponse`` rather than from a sync call.

    Reconcile is invoked with ``already_retried=True`` — by the time we
    reach this helper, the caller has decided whether a retry was
    warranted. This forces reconcile.py to surface any remaining
    Stage 1↔Stage 2 conflict as ``mark_cross_stage_conflict`` rather
    than asking for another LLM call.

    Concurrency guard semantics are unchanged: when ``expected_status``
    is set and the row's actual status no longer matches, raise
    ``PipelineConcurrencyError`` and let the surrounding ``_maybe_cursor``
    (or ``db()`` fallback) roll back Phase C.
    """
    # Phase B (part 3) — Stage 2.5 floors (CPU + brief DB) ------------
    with _maybe_cursor(conn) as cur:
        overrides = apply_score_floors(cur, item, facts, rewrite, item.city_id)

    # Phase B (part 4) — Final reconcile (no further retry) -----------
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

    with _maybe_cursor(conn) as cur:
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
            log.info(
                "pipeline.finalize_from_rewrite concurrency guard fired: "
                "item_id=%s expected_status=%s — rolling back Phase C",
                item.id, expected_status,
            )
            raise PipelineConcurrencyError(
                f"item {item.id} status no longer matches "
                f"expected_status={expected_status!r}; Phase C rolled back"
            )

        # On-write process badges (decision #57: SQL + on-write must agree).
        # Decision #92: include city_id in every INSERT.
        # Process badges are always deterministic — status='applied'.
        for slug, conf in compute_on_write_process_badges(
            item, facts, overrides, rewrite.confidence,
        ):
            cur.execute(
                """
                INSERT INTO agenda_item_badges
                  (agenda_item_id, city_id, badge_slug, kind, confidence,
                   source, matching_metadata, status)
                VALUES (%s, %s, %s, 'process', %s, 'deterministic', '{}'::jsonb, 'applied')
                ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING
                """,
                (item.id, item.city_id, slug, conf),
            )

        # Policy badges (deterministic + LLM-suggested per Section D).
        # Refactor #2: status='applied' when deterministic backing exists,
        # 'flagged' when only the LLM suggested the badge.
        for slug, conf, source, metadata, status in compute_policy_badges(
            item, facts, rewrite, item.city_id,
        ):
            cur.execute(
                """
                INSERT INTO agenda_item_badges
                  (agenda_item_id, city_id, badge_slug, kind, confidence,
                   source, matching_metadata, status)
                VALUES (%s, %s, %s, 'policy', %s, %s, %s::jsonb, %s)
                ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING
                """,
                (item.id, item.city_id, slug, conf, source, json.dumps(metadata), status),
            )

    log.info(
        "pipeline.finalize_from_rewrite done: item_id=%s status=%s override=%s",
        item.id, final_status, override_instruction is not None,
    )
    return final_status
