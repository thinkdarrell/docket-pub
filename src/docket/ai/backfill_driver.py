"""Backfill wave driver — coordinates a session of bulk Stage 1 / Stage 2 work.

A "wave" is a chunk of historical data (e.g., 2026-only, then 2021-2025, then
2017-2020) processed via Anthropic's Batches API. Each invocation gets a fresh
`backfill_session_id` UUID; the same UUID is written to every agenda_items row
the wave touches, enabling single-statement rollback if the wave's prompt
turns out to be buggy.

This module is the operational plumbing — iterating pending items, submitting
batches via `docket.ai.batches`, recording the session. Per-item result
processing (parsing Anthropic responses, calling the AI pipeline, persisting
to agenda_items) is the orchestrator's job in `docket.ai.pipeline` (B5).

Spec: section 7.3, 7.5, decisions #82, #95.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Iterator, Literal

from docket.ai.batches import submit_batch
from docket.db import db

log = logging.getLogger(__name__)


# Wave definitions — names map to date ranges per spec §7.1.
# These are conventional labels used across the project; if the user
# wants different boundaries, override via run_wave(wave_name='custom', date_range=(start, end)).
WAVE_DATE_RANGES: dict[str, tuple[date, date]] = {
    '0.5': (date(2026, 1, 1), date(2026, 12, 31)),
    '1':   (date(2026, 1, 1), date(2026, 12, 31)),
    '2':   (date(2021, 1, 1), date(2025, 12, 31)),
    '3':   (date(2017, 1, 1), date(2020, 12, 31)),
}


@dataclass
class WaveResult:
    """Returned by run_wave — small audit summary for the CLI to print."""
    session_id: uuid.UUID
    wave_name: str
    stage: str
    batch_count: int
    item_count: int
    anthropic_batch_ids: list[str] = field(default_factory=list)


def iterate_pending_items(
    date_range: tuple[date, date],
    stage: str,
    batch_size: int = 10_000,
) -> Iterator[list]:
    """Yield item batches that need processing for the given stage in the date range.

    For stage='stage1': items with processing_status='pending' (Wave 0 cleared
    `data_quality_skipped` and `procedural_skipped`; only LLM-eligible items
    remain in 'pending').

    For stage='stage2': items with processing_status='extracted' (Stage 1 done).

    Items are yielded in chunks of `batch_size`. Each yielded batch is a list
    of duck-typed item objects with the attributes that batches.build_*_request
    needs (.id, .title, .description, .sponsor, .dollars_amount, .topic, .is_consent).
    """
    from types import SimpleNamespace

    start_date, end_date = date_range
    target_status = 'pending' if stage == 'stage1' else 'extracted'

    sql = """
        SELECT ai.id, ai.title, ai.description, ai.sponsor, ai.dollars_amount,
               ai.topic, ai.is_consent
          FROM agenda_items ai
          JOIN meetings m ON m.id = ai.meeting_id
         WHERE ai.processing_status = %s
           AND ai.backfill_session_id IS NULL
           AND m.meeting_date >= %s
           AND m.meeting_date <= %s
         ORDER BY ai.id
    """
    with db() as conn, conn.cursor() as cur:
        cur.execute(sql, [target_status, start_date, end_date])
        rows = cur.fetchall()

    all_items = [
        SimpleNamespace(
            id=r[0], title=r[1], description=r[2], sponsor=r[3],
            dollars_amount=r[4], topic=r[5], is_consent=r[6],
        )
        for r in rows
    ]

    for i in range(0, len(all_items), batch_size):
        chunk = all_items[i:i + batch_size]
        if chunk:
            yield chunk


def claim_session(item_ids: list[int], session_id: uuid.UUID) -> int:
    """Mark items as belonging to this wave session.

    Idempotent: re-running with the same session_id is safe. Returns rowcount.
    Items already claimed by any session (including this one) are skipped.
    """
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agenda_items
               SET backfill_session_id = %s
             WHERE id = ANY(%s)
               AND backfill_session_id IS NULL
            """,
            [str(session_id), item_ids],
        )
        return cur.rowcount


def run_wave(
    wave_name: str,
    stage: Literal['stage1', 'stage2'],
    *,
    date_range: tuple[date, date] | None = None,
    batch_size: int = 10_000,
) -> WaveResult:
    """Submit pending items for a wave via the Batches API.

    Returns a WaveResult with the session_id (for rollback), submitted batch
    count, and item count.

    NOTE: This function only SUBMITS the batches. Polling, parsing, and
    persisting per-item results is the orchestrator's job (B5 / docket.ai.pipeline).
    Run `python -m docket.ai.cli --poll-batch <batch_id>` (B5) to ingest results.
    """
    if date_range is None:
        if wave_name not in WAVE_DATE_RANGES:
            raise ValueError(
                f"unknown wave_name {wave_name!r} and no explicit date_range given. "
                f"known waves: {sorted(WAVE_DATE_RANGES)}"
            )
        date_range = WAVE_DATE_RANGES[wave_name]

    session_id = uuid.uuid4()
    log.info(
        "starting wave %s stage=%s with session_id=%s, dates=%s..%s",
        wave_name, stage, session_id, date_range[0], date_range[1],
    )

    submitted_batch_ids: list[str] = []
    total_items = 0

    for chunk in iterate_pending_items(date_range, stage, batch_size=batch_size):
        if not chunk:
            continue
        item_ids = [it.id for it in chunk]
        n_claimed = claim_session(item_ids, session_id)
        log.info("wave %s claimed %d items for session %s", wave_name, n_claimed, session_id)

        try:
            anthropic_batch_id = submit_batch(chunk, stage=stage, wave=wave_name)
            submitted_batch_ids.append(anthropic_batch_id)
            total_items += len(chunk)
            log.info(
                "wave %s submitted batch %s (%d items)",
                wave_name, anthropic_batch_id, len(chunk),
            )
        except Exception:
            # On submission failure, release the session_id so the next run
            # can retry (decision #82 — atomic rollback per session)
            log.exception(
                "wave %s batch submission failed; rolling back session claim", wave_name
            )
            with db() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE agenda_items SET backfill_session_id = NULL "
                    "WHERE backfill_session_id = %s",
                    [str(session_id)],
                )
            raise

    return WaveResult(
        session_id=session_id,
        wave_name=wave_name,
        stage=stage,
        batch_count=len(submitted_batch_ids),
        item_count=total_items,
        anthropic_batch_ids=submitted_batch_ids,
    )
