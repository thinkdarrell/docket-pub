"""Anthropic Batches API wrapper.

Provides submit_batch() and poll_batch() for submitting and polling Anthropic
Message Batches. Records batches in ai_batches / ai_batch_items tables.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md §7.3
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Literal

import anthropic

from docket.ai.extraction import (
    SYSTEM_PROMPT as EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_PROMPT_VERSION,  # noqa: F401 — imported for future B5 wiring
    build_user_message as build_extraction_user_message,
)
from docket.ai.extraction_schema import StructuredFacts
from docket.ai.rewrite import (
    SYSTEM_PROMPT as REWRITE_SYSTEM_PROMPT,
    ITEM_REWRITE_PROMPT_VERSION,  # noqa: F401 — imported for future B5 wiring
    build_user_message as build_rewrite_user_message,
)
from docket.db import db

log = logging.getLogger(__name__)


@dataclass
class BatchStatus:
    id: str
    status: str  # 'submitted' | 'in_progress' | 'ended' | 'failed' | 'expired'
    request_counts: Any  # opaque structure from Anthropic SDK


# ---------------------------------------------------------------------------
# Request builders
# ---------------------------------------------------------------------------

def build_stage1_request(item, *, model: str = "claude-haiku-4-5-20251001") -> dict:
    """Build the Anthropic messages.create params dict for Stage 1 extraction."""
    return {
        'model': model,
        'max_tokens': 1024,
        'system': [
            {"type": "text", "text": EXTRACTION_SYSTEM_PROMPT,
             "cache_control": {"type": "ephemeral"}},
        ],
        'messages': [{'role': 'user', 'content': build_extraction_user_message(item)}],
    }


def build_stage2_request(
    item,
    facts: StructuredFacts,
    enabled_policy_badges: list[str] | None = None,
    *,
    model: str = "claude-haiku-4-5-20251001",
) -> dict:
    """Build the Anthropic messages.create params dict for Stage 2 rewrite."""
    return {
        'model': model,
        'max_tokens': 1024,
        'system': [
            {"type": "text", "text": REWRITE_SYSTEM_PROMPT,
             "cache_control": {"type": "ephemeral"}},
        ],
        'messages': [{
            'role': 'user',
            'content': build_rewrite_user_message(item, facts, enabled_policy_badges or []),
        }],
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_stage1_facts(item) -> StructuredFacts | None:
    """Read previously-persisted Stage 1 facts for item.id. Returns None
    if no Stage 1 output yet."""
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT extracted_facts FROM agenda_items WHERE id = %s",
            [item.id],
        )
        row = cur.fetchone()
    if row is None or row[0] is None:
        return None
    return StructuredFacts.model_validate(row[0])


def record_batch(
    anthropic_batch_id: str,
    stage: str,
    wave: str,
    item_ids: list[int],
) -> int:
    """Insert one ai_batches row + N ai_batch_items rows. Returns internal ai_batches.id."""
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ai_batches (anthropic_batch_id, stage, wave, item_count, status)
            VALUES (%s, %s, %s, %s, 'submitted')
            RETURNING id
            """,
            [anthropic_batch_id, stage, wave, len(item_ids)],
        )
        batch_id = cur.fetchone()[0]
        for item_id in item_ids:
            cur.execute(
                """
                INSERT INTO ai_batch_items (batch_id, agenda_item_id, custom_id)
                VALUES (%s, %s, %s)
                """,
                [batch_id, item_id, f'item-{item_id}-{stage}'],
            )
    return batch_id


def persist_batch_result(result, anthropic_batch_id: str) -> None:
    """Update the ai_batch_items.result_status row corresponding to this result.

    result.custom_id is in the form 'item-<id>-<stage>'.
    result.result.type is 'succeeded' / 'errored' / 'expired'.

    NOTE: This persists only the status — the actual response content
    (parsed StructuredFacts or ItemRewrite) is the orchestrator's job
    to consume separately. H2 is the wrapper, not the orchestrator (B5/H3).
    """
    custom_id = result.custom_id
    # Parse 'item-<id>-<stage>' to extract agenda_item_id
    parts = custom_id.split('-')
    agenda_item_id = int(parts[1])

    result_status = result.result.type  # 'succeeded' | 'errored' | 'expired'

    with db() as conn, conn.cursor() as cur:
        # Look up the internal batch_id
        cur.execute(
            "SELECT id FROM ai_batches WHERE anthropic_batch_id = %s",
            [anthropic_batch_id],
        )
        row = cur.fetchone()
        if row is None:
            log.warning(
                "persist_batch_result: no ai_batches row for anthropic id %s",
                anthropic_batch_id,
            )
            return
        batch_id = row[0]

        cur.execute(
            """
            UPDATE ai_batch_items
            SET result_status = %s
            WHERE batch_id = %s AND agenda_item_id = %s
            """,
            [result_status, batch_id, agenda_item_id],
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def submit_batch(
    items: list,
    stage: Literal['stage1', 'stage2'],
    wave: str,
) -> str:
    """Submit a batch to Anthropic. Returns batch ID for polling.

    For stage2, each item must have previously-persisted Stage 1 facts
    (agenda_items.extracted_facts). Items whose facts are missing are
    skipped with a warning.
    """
    client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

    submitted_items = []
    requests = []
    for item in items:
        if stage == 'stage1':
            req = build_stage1_request(item)
        else:
            facts = get_stage1_facts(item)
            if facts is None:
                log.warning(
                    "submit_batch: item %s has no Stage 1 facts; skipping",
                    getattr(item, 'id', '?'),
                )
                continue
            req = build_stage2_request(item, facts)
        requests.append({
            'custom_id': f'item-{item.id}-{stage}',
            'params': req,
        })
        submitted_items.append(item)

    if not requests:
        raise ValueError("submit_batch: no items to submit (all skipped or empty input)")

    batch = client.messages.batches.create(requests=requests)
    record_batch(batch.id, stage, wave, [i.id for i in submitted_items])
    return batch.id


def poll_batch(batch_id: str) -> BatchStatus:
    """Poll the batch. Returns status; pulls and persists results when 'ended'."""
    client = anthropic.Anthropic()
    batch = client.messages.batches.retrieve(batch_id)

    if batch.processing_status == 'ended':
        for result in client.messages.batches.results(batch_id):
            persist_batch_result(result, batch_id)
        # Mark parent batch as ended
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai_batches
                SET status = 'ended', completed_at = NOW()
                WHERE anthropic_batch_id = %s
                """,
                [batch_id],
            )
    elif batch.processing_status in ('failed', 'expired'):
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE ai_batches SET status = %s WHERE anthropic_batch_id = %s",
                [batch.processing_status, batch_id],
            )

    return BatchStatus(
        id=batch.id,
        status=batch.processing_status,
        request_counts=batch.request_counts,
    )
