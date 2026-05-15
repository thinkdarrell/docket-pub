"""Ingest Anthropic Batches API results into agenda_items.

Phase 3 backfill submits items to Anthropic's Batches API (50% discount,
24h SLA). ``docket.ai.backfill_driver.run_wave`` does the submission.
``docket.ai.batches.poll_batch`` polls Anthropic for status and marks
``ai_batches.status='ended'`` when done. This module is the missing
piece: when a batch has ``status='ended' AND ingested_at IS NULL``,
download the per-item results and persist them into ``agenda_items``.

Stage 1 ingest: parse tool_use → ``StructuredFacts`` → write
``extracted_facts``, ``ai_extraction_version``, set
``processing_status='extracted'``. Stage 2 ingest: load Stage 1 facts
+ city context, parse tool_use → ``ItemRewrite``, then delegate to
``pipeline.finalize_from_rewrite`` for Stage 2.5 floors + reconcile +
atomic commit (same writes as the sync worker path).

Per-item validation failures (out-of-enum values, overlong headlines,
procedural-consistency violations) follow the same coerce-then-retry
pattern as the sync path; if coercion can't recover, the item is
marked ``failed_permanent`` and the batch continues. Anthropic-side
``errored``/``expired`` per-item results also surface as
``failed_permanent``.

After a successful pass over a batch, ``ai_batches.ingested_at`` is
set to ``NOW()`` so the orchestrator's queue predicate
(``status='ended' AND ingested_at IS NULL``) skips it on the next
poll. Re-running ingestion against an already-ingested batch is a
no-op short-circuit at the top of ``ingest_batch``.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md
sections 7.3, 7.5.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from types import SimpleNamespace

import anthropic
from pydantic import ValidationError

from docket.ai.batches import poll_batch
from docket.ai.exceptions import AIPermanentRowError
from docket.ai.extraction import (
    EXTRACTION_PROMPT_VERSION,
    STAGE1_TOOL,
    _coerce_unknown_enums,
    _normalize_string_nulls,
    _truncate_overlong_strings,
)
from docket.ai.pricing import Usage, calculate_cost_usd, usage_add
from docket.ai.extraction_schema import StructuredFacts
from docket.ai.pipeline import finalize_from_rewrite
from docket.ai.rewrite import STAGE2_TOOL
from docket.ai.rewrite_schema import ItemRewrite
from docket.db import db

log = logging.getLogger(__name__)


@dataclass
class IngestSummary:
    """Roll-up returned by ``poll_and_ingest`` for operator visibility."""
    batches_polled: int = 0
    batches_ingested: int = 0
    items_succeeded: int = 0
    items_errored: int = 0
    items_skipped: int = 0
    batch_ids_ingested: list[str] = field(default_factory=list)


def _extract_tool_input_from_message(message, tool_name: str) -> dict:
    """Pull the named tool_use block's input from a batch-result Message.

    Mirrors ``extraction._extract_tool_input`` but operates on an
    ``anthropic.types.Message`` (returned via ``batches.results(...)``)
    instead of a sync ``messages.create`` response. The shape is
    identical — ``message.content`` is a list of content blocks.
    """
    for block in message.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        block_name = getattr(block, "name", None)
        if not isinstance(block_name, str) or block_name == tool_name:
            return dict(block.input)
    raise AIPermanentRowError(
        f"no tool_use block named {tool_name} in batch-result message"
    )


def _mark_failed_permanent(item_id: int, error_message: str) -> None:
    """Set processing_status='failed_permanent' with a truncated error blurb."""
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agenda_items
               SET processing_status  = 'failed_permanent'::processing_status_enum,
                   last_error_at      = NOW(),
                   last_error_message = %s
             WHERE id = %s
            """,
            [error_message[:500], item_id],
        )


def _validate_stage1_payload(payload: dict, item_id: int) -> StructuredFacts:
    """Coerce-and-retry wrap for Stage 1 schema validation.

    Mirrors the sync path's coercion chain in ``extraction.py``:
    first normalize string-null tokens ('null'/'None'/etc.) for the
    object-typed fields (notably ``next_steps``), then coerce out-of-
    enum values. Without the string-null normalization, Haiku's
    occasional ``next_steps='null'`` crashes Pydantic with
    ``input_type=str`` — observed at 29/9281 items in Wave 2 (2026-05-14).
    """
    prefix = f"stage1 batch item={item_id} "
    try:
        return StructuredFacts.model_validate(payload)
    except ValidationError:
        payload = _normalize_string_nulls(payload, log_prefix=prefix)
        payload = _coerce_unknown_enums(
            payload, STAGE1_TOOL["input_schema"], log_prefix=prefix,
        )
        try:
            return StructuredFacts.model_validate(payload)
        except ValidationError as e:
            raise AIPermanentRowError(
                f"stage1 batch validation failed after coercion for item {item_id}: {e}"
            ) from e


def _validate_stage2_payload(
    payload: dict,
    item_id: int,
    *,
    retry_ctx: tuple | None = None,
) -> ItemRewrite:
    """Coerce + truncate + (optional) assertion-error retry for Stage 2.

    Args:
        payload: Haiku's tool_use input from the Stage 2 batch result.
        item_id: for error messages.
        retry_ctx: optional ``(item, facts, enabled_policy_slugs)`` tuple.
            When provided and the remaining errors after mechanical fixes
            are all assertion-class (procedural_consistency violations,
            issue #26), re-prompts Haiku once with the bad payload + error
            as feedback. Without retry_ctx the function preserves its
            pre-retry behavior: any post-coercion failure raises
            ``AIPermanentRowError`` so callers without the necessary
            context (item/facts/slugs) still get the same surface.
    """
    try:
        return ItemRewrite.model_validate(payload)
    except ValidationError as e:
        prefix = f"stage2 batch item={item_id} "
        # Mirror the Stage 1 coercion order: normalize string-nulls first so
        # any nested 'null'/'None' strings don't bleed past schema coercion.
        # Stage 2 doesn't currently have nested object fields, but symmetry
        # with the sync path keeps the two ingest surfaces from drifting.
        payload = _normalize_string_nulls(payload, log_prefix=prefix)
        payload = _coerce_unknown_enums(payload, STAGE2_TOOL["input_schema"], log_prefix=prefix)
        payload = _truncate_overlong_strings(payload, e, log_prefix=prefix)
        try:
            return ItemRewrite.model_validate(payload)
        except ValidationError as e2:
            from docket.ai.rewrite import (
                _is_assertion_only_error,
                _retry_with_assertion_feedback,
            )
            if retry_ctx is not None and _is_assertion_only_error(e2):
                item, facts, enabled_slugs = retry_ctx
                log.warning("%sassertion-error retry: %s", prefix, e2)
                payload = _retry_with_assertion_feedback(
                    item, facts, enabled_slugs, payload, e2,
                    model="claude-haiku-4-5-20251001",
                )
                try:
                    return ItemRewrite.model_validate(payload)
                except ValidationError as e3:
                    raise AIPermanentRowError(
                        f"stage2 batch validation failed after assertion-error "
                        f"retry for item {item_id}: {e3}"
                    ) from e3
            raise AIPermanentRowError(
                f"stage2 batch validation failed after coercion+truncation for item {item_id}: {e2}"
            ) from e2


def _ingest_stage1_message(item_id: int, message) -> None:
    """Parse a Stage 1 batch result and write extracted_facts."""
    payload = _extract_tool_input_from_message(message, STAGE1_TOOL["name"])
    facts = _validate_stage1_payload(payload, item_id)

    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agenda_items
               SET extracted_facts       = %s::jsonb,
                   ai_extraction_version = %s,
                   processing_status     = 'extracted'::processing_status_enum
             WHERE id = %s
            """,
            [facts.model_dump_json(), EXTRACTION_PROMPT_VERSION, item_id],
        )


def _load_item_view(item_id: int):
    """Build the duck-typed item + reconstruct Stage 1 facts for Stage 2 ingest.

    Returns (item, facts) tuple, or (None, None) if the row is gone or
    has no extracted_facts yet (defensive — submission ordering should
    prevent the latter).
    """
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT ai.id, ai.title, ai.description, ai.sponsor, ai.dollars_amount,
                   ai.topic, ai.is_consent, ai.extracted_facts,
                   m.municipality_id AS city_id,
                   muni.name         AS city_name
              FROM agenda_items ai
              JOIN meetings m       ON m.id = ai.meeting_id
              JOIN municipalities muni ON muni.id = m.municipality_id
             WHERE ai.id = %s
            """,
            [item_id],
        )
        row = cur.fetchone()
    if row is None or row[7] is None:
        return None, None

    facts = StructuredFacts.model_validate(row[7])
    item = SimpleNamespace(
        id=row[0],
        title=row[1],
        description=row[2],
        sponsor=row[3],
        dollars_amount=row[4],
        topic=row[5],
        is_consent=row[6],
        city_id=row[8],
        city_name=row[9],
        source_type="agenda",
        raw_text=None,
    )
    return item, facts


def _ingest_stage2_message(item_id: int, message) -> None:
    """Parse a Stage 2 batch result and run the rest of the pipeline."""
    from docket.services.badges import get_enabled_policy_slugs

    item, facts = _load_item_view(item_id)
    if item is None or facts is None:
        raise AIPermanentRowError(
            f"stage2 batch ingest: item {item_id} has no Stage 1 facts "
            f"(or row missing); cannot finalize"
        )

    payload = _extract_tool_input_from_message(message, STAGE2_TOOL["name"])
    enabled_slugs = list(get_enabled_policy_slugs(item.city_id))
    rewrite = _validate_stage2_payload(
        payload, item_id,
        retry_ctx=(item, facts, enabled_slugs),
    )

    # Shared with the sync worker path. No new LLM calls.
    finalize_from_rewrite(item, facts, rewrite)


def ingest_batch(anthropic_batch_id: str) -> dict:
    """Download + persist one Anthropic batch's results.

    Idempotent: if ``ai_batches.ingested_at`` is already set, returns
    immediately with ``{'already_ingested': True}``. Otherwise iterates
    every per-item result, dispatches to Stage 1 / Stage 2 ingest
    helpers, records succeeded / errored / skipped counts, and marks
    ``ingested_at = NOW()`` at the end.

    Per-item exceptions are caught and surfaced as ``failed_permanent``
    on the agenda item; the batch itself continues. A bug-class
    exception (e.g. KeyError, AttributeError) bubbles up — those
    indicate code bugs we want to fix, not data to skip.
    """
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, stage, ingested_at FROM ai_batches WHERE anthropic_batch_id = %s",
            [anthropic_batch_id],
        )
        row = cur.fetchone()
    if row is None:
        log.warning(
            "ingest_batch: no ai_batches row for %s; skipping",
            anthropic_batch_id,
        )
        return {"skipped_no_row": True}

    batch_pk, stage, ingested_at = row
    if ingested_at is not None:
        log.info(
            "ingest_batch: batch %s already ingested at %s; skipping",
            anthropic_batch_id, ingested_at,
        )
        return {"already_ingested": True}

    succeeded = 0
    errored = 0
    skipped = 0
    # Per-model usage accumulator. Anthropic Batches API only bills successful
    # results, so we only add to this on the `succeeded` path below. After the
    # loop we compute the total cost via the project's pricing table and write
    # it to ai_batches.cost_usd alongside ingested_at.
    total_usage_by_model: dict[str, Usage] = {}

    client = anthropic.Anthropic()
    for result in client.messages.batches.results(anthropic_batch_id):
        custom_id = getattr(result, "custom_id", "") or ""
        parts = custom_id.split("-")
        if len(parts) < 2:
            log.warning("ingest_batch: malformed custom_id %r; skipping", custom_id)
            skipped += 1
            continue
        try:
            item_id = int(parts[1])
        except ValueError:
            log.warning("ingest_batch: non-numeric item id in custom_id %r; skipping", custom_id)
            skipped += 1
            continue

        result_type = getattr(result.result, "type", "?")
        if result_type != "succeeded":
            # Anthropic returned errored / expired / canceled for this item.
            # Issue #34 follow-up: capture the SDK's specific error if
            # present so the operator can diagnose without round-tripping
            # to Anthropic's console. ``result.result.error`` is an object
            # with ``type`` + ``message`` attributes when type=='errored';
            # absent for ``expired`` / ``canceled``.
            err_obj = getattr(result.result, "error", None)
            err_detail = ""
            if err_obj is not None:
                err_type = getattr(err_obj, "type", None)
                err_message = getattr(err_obj, "message", None)
                if err_type or err_message:
                    err_detail = f": {err_type or ''}: {err_message or ''}".rstrip(": ")
            reason = f"batch result type={result_type}{err_detail}"
            log.warning(
                "ingest_batch: item=%s batch=%s %s — marking failed_permanent",
                item_id, anthropic_batch_id, reason,
            )
            _mark_failed_permanent(item_id, reason)
            errored += 1
            continue

        message = result.result.message
        try:
            if stage == "stage1":
                _ingest_stage1_message(item_id, message)
            elif stage == "stage2":
                _ingest_stage2_message(item_id, message)
            else:
                log.warning("ingest_batch: unknown stage=%r on batch %s; skipping",
                            stage, anthropic_batch_id)
                skipped += 1
                continue
            succeeded += 1
            # Accumulate usage for cost telemetry. Anthropic's SDK exposes
            # cache_* fields as None when the request didn't hit cache; coerce
            # to 0 so usage_add stays well-typed.
            mu = getattr(message, "usage", None)
            if mu is not None:
                u = Usage(
                    input_tokens=mu.input_tokens or 0,
                    cache_creation_input_tokens=(getattr(mu, "cache_creation_input_tokens", 0) or 0),
                    cache_read_input_tokens=(getattr(mu, "cache_read_input_tokens", 0) or 0),
                    output_tokens=mu.output_tokens or 0,
                )
                model = getattr(message, "model", "") or ""
                if model in total_usage_by_model:
                    total_usage_by_model[model] = usage_add(total_usage_by_model[model], u)
                else:
                    total_usage_by_model[model] = u
        except AIPermanentRowError as e:
            log.warning("ingest_batch: item=%s permanent failure: %s", item_id, e)
            _mark_failed_permanent(item_id, str(e))
            errored += 1

    # Compute the total batch cost from per-model usage. An unknown model name
    # raises KeyError from calculate_cost_usd — that's intentional (we want to
    # learn about pricing-table gaps loudly, not silently log $0). If you hit
    # this, add the new model to docket/ai/pricing.py:PRICING.
    total_cost_usd = 0.0
    for model, agg in total_usage_by_model.items():
        total_cost_usd += calculate_cost_usd(model, agg)

    # Mark the batch as ingested so subsequent poll_and_ingest passes
    # don't reprocess it. Idempotent via the predicate at the top.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE ai_batches SET ingested_at = NOW(), cost_usd = %s WHERE id = %s",
            [total_cost_usd, batch_pk],
        )

    log.info(
        "ingest_batch: %s stage=%s succeeded=%d errored=%d skipped=%d cost_usd=$%.4f",
        anthropic_batch_id, stage, succeeded, errored, skipped, total_cost_usd,
    )
    return {
        "anthropic_batch_id": anthropic_batch_id,
        "stage": stage,
        "succeeded": succeeded,
        "errored": errored,
        "skipped": skipped,
    }


def poll_and_ingest() -> IngestSummary:
    """One pass over all in-flight batches: poll status, then ingest the ready ones.

    Called by both the ``--process-batches`` CLI and the
    ``process_batches`` cron task. Safe to invoke as often as desired
    — every step is idempotent. Per-batch errors are logged and skipped
    so one bad batch doesn't block the rest of the queue.
    """
    summary = IngestSummary()

    # Step 1: poll each submitted/in_progress batch. poll_batch() updates
    # ai_batches.status to 'ended'/'failed'/'expired' as appropriate.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT anthropic_batch_id
              FROM ai_batches
             WHERE status IN ('submitted', 'in_progress')
             ORDER BY submitted_at
            """,
        )
        in_flight = [r[0] for r in cur.fetchall()]

    for batch_id in in_flight:
        try:
            poll_batch(batch_id)
            summary.batches_polled += 1
        except Exception:
            log.exception("poll_batch failed for %s; continuing", batch_id)

    # Step 2: ingest any batches that are 'ended' but not yet ingested.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT anthropic_batch_id
              FROM ai_batches
             WHERE status = 'ended' AND ingested_at IS NULL
             ORDER BY completed_at NULLS FIRST, submitted_at
            """,
        )
        ready = [r[0] for r in cur.fetchall()]

    for batch_id in ready:
        try:
            result = ingest_batch(batch_id)
            if result.get("already_ingested") or result.get("skipped_no_row"):
                continue
            summary.batches_ingested += 1
            summary.batch_ids_ingested.append(batch_id)
            summary.items_succeeded += result.get("succeeded", 0)
            summary.items_errored += result.get("errored", 0)
            summary.items_skipped += result.get("skipped", 0)
        except Exception:
            log.exception("ingest_batch failed for %s; continuing", batch_id)

    log.info(
        "poll_and_ingest: polled=%d ingested=%d items succeeded=%d errored=%d skipped=%d",
        summary.batches_polled, summary.batches_ingested,
        summary.items_succeeded, summary.items_errored, summary.items_skipped,
    )
    return summary
