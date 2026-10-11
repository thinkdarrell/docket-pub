"""One cron task drives three stages: uploaded -> speakers_resolved -> events_extracted -> compared.

Claim pattern is the OCR one (CTE, FOR UPDATE SKIP LOCKED, newest meeting
first, attempts bumped at claim time, 24-hour backoff in the WHERE clause).
Every processed claim opens and closes an ``ai_runs`` row through the v2
worker helpers so ``AI_DAILY_BUDGET_USD`` sees the spend. Stage modules are
imported lazily so this module has no import-time dependency on them.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from docket.ai.exceptions import (AIFatalError, AIPermanentRowError, AIRateLimited, AITransientError,
                                  TranscriptHeld)
from docket.ai.pricing import PRICING, Usage, calculate_cost_usd, usage_add, usage_capture
from docket.config import (AI_DAILY_BUDGET_USD, AI_TRANSCRIPT_COMPARE_MODEL, AI_TRANSCRIPT_EVENTS_MODEL,
                           AI_TRANSCRIPT_SPEAKER_MODEL, TRANSCRIPT_MIN_WORDS, TRANSCRIPT_PER_TICK)
from docket.db import db, db_cursor

log = logging.getLogger(__name__)

STAGE_FOR_STATUS = {"uploaded": "speakers", "speakers_resolved": "events", "events_extracted": "compare"}
RUN_NAME = {"speakers": "transcript_speakers", "events": "transcript_events", "compare": "transcript_compare"}
MODEL_FOR_STAGE = {"speakers": AI_TRANSCRIPT_SPEAKER_MODEL, "events": AI_TRANSCRIPT_EVENTS_MODEL,
                   "compare": AI_TRANSCRIPT_COMPARE_MODEL}

CLAIM_SQL = """
WITH candidate AS (
    SELECT t.id
      FROM transcripts t
      JOIN meetings m        ON m.id  = t.meeting_id
      JOIN municipalities mu ON mu.id = m.municipality_id
     WHERE mu.slug = 'birmingham'
       AND m.external_id ~ '^[0-9]+$'
       AND m.is_hidden = FALSE
       AND t.status IN ('uploaded', 'speakers_resolved', 'events_extracted')
       AND (t.status <> 'events_extracted'
            OR t.compare_skipped_reason IS NULL
            OR t.compare_skipped_reason = 'minutes_changed'
            OR (t.compare_skipped_reason IN ('no_minutes', 'minutes_unavailable')
                AND m.minutes_url IS NOT NULL))
       AND t.stage_attempts < 3
       AND (t.last_attempted_at IS NULL OR t.last_attempted_at < now() - interval '24 hours')
     ORDER BY m.meeting_date DESC, t.id
     LIMIT 1
     FOR UPDATE OF t SKIP LOCKED
)
UPDATE transcripts t
   SET stage_attempts = t.stage_attempts + 1, last_attempted_at = now(), updated_at = now()
  FROM candidate
 WHERE t.id = candidate.id
RETURNING t.id, t.meeting_id, t.status, t.version, t.word_count, t.compare_skipped_reason
"""


@dataclass
class StageOutcome:
    next_status: str
    skipped_reason: str | None = None
    detail: str = ""


@dataclass
class PipelineSummary:
    processed: int = 0
    advanced: int = 0
    skipped: int = 0
    low_speech: int = 0
    held: int = 0
    failed: int = 0
    transient: int = 0
    stopped_reason: str | None = None


def fitness_reason(word_count: int | None, floor: int = TRANSCRIPT_MIN_WORDS) -> str | None:
    if word_count is None:
        return "word_count unknown"
    if word_count < floor:
        return f"word_count {word_count} below floor {floor}"
    return None


def claim_next() -> dict | None:
    with db_cursor() as cur:
        cur.execute(CLAIM_SQL)
        row = cur.fetchone()
        return dict(row) if row else None


def assign_index_points(transcript_id: int, meeting_id: int) -> int:
    """Initial agenda_item_id from Granicus index points (spec: 'index point drift').

    Each unassigned, non-silence segment gets the item whose index point is the
    latest one at or before the segment's start. Segments before the first index
    point (pre-meeting) stay NULL. Confident item_opened events re-assign later
    with assignment_method = 'event'; manual assignments are never touched.
    """
    with db_cursor() as cur:
        cur.execute(
            """UPDATE transcript_segments s
                  SET agenda_item_id = x.item_id, assignment_method = 'index_point'
                 FROM (SELECT s2.id AS seg_id,
                              (SELECT a.id FROM agenda_items a
                                WHERE a.meeting_id = %s AND a.video_timestamp_seconds IS NOT NULL
                                  AND a.video_timestamp_seconds <= s2.start_s
                                ORDER BY a.video_timestamp_seconds DESC, a.id LIMIT 1) AS item_id
                         FROM transcript_segments s2
                        WHERE s2.transcript_id = %s AND s2.assignment_method IS NULL AND s2.is_silence = FALSE) x
                WHERE s.id = x.seg_id AND x.item_id IS NOT NULL""",
            [meeting_id, transcript_id],
        )
        return cur.rowcount


def advance(transcript_id: int, outcome: StageOutcome) -> None:
    with db_cursor() as cur:
        cur.execute(
            """UPDATE transcripts
                  SET status = %s, stage_attempts = 0, last_error = NULL, needs_review_reason = NULL,
                      compare_skipped_reason = %s, updated_at = now()
                WHERE id = %s""",
            [outcome.next_status, outcome.skipped_reason, transcript_id],
        )
        if outcome.skipped_reason in ("no_minutes", "minutes_unavailable"):
            # Retry daily without burning the three-attempt cap (Review Focus 1).
            cur.execute("UPDATE transcripts SET stage_attempts = 0 WHERE id = %s", [transcript_id])


def mark_low_speech(transcript_id: int, detail: str) -> None:
    with db_cursor() as cur:
        cur.execute("""UPDATE transcripts SET status = 'low_speech', last_error = %s, stage_attempts = 0,
                              updated_at = now() WHERE id = %s""", [detail, transcript_id])


def mark_needs_review(transcript_id: int, reason: str, detail: str) -> None:
    with db_cursor() as cur:
        cur.execute("""UPDATE transcripts SET status = 'needs_review', needs_review_reason = %s,
                              last_error = %s, updated_at = now() WHERE id = %s""",
                    [reason, detail[:2000], transcript_id])


def mark_transient(transcript_id: int, detail: str) -> str:
    """Record the error; the third failed attempt becomes `failed`. Returns the status."""
    with db_cursor() as cur:
        cur.execute("""UPDATE transcripts
                          SET last_error = %s, updated_at = now(),
                              status = CASE WHEN stage_attempts >= 3 THEN 'failed' ELSE status END
                        WHERE id = %s RETURNING status""", [detail[:2000], transcript_id])
        return cur.fetchone()["status"]


def _stage_fn(stage: str) -> Callable[..., StageOutcome]:
    if stage == "speakers":
        from docket.ai.transcripts.speakers import run_speaker_stage
        return run_speaker_stage
    if stage == "events":
        from docket.ai.transcripts.events import run_events_stage
        return run_events_stage
    from docket.ai.transcripts.compare import run_compare_stage
    return run_compare_stage


def _cost(emissions: list[tuple[str, Usage]]) -> tuple[float, Usage]:
    total = Usage(0, 0, 0, 0)
    cost = 0.0
    for model, u in emissions:
        total = usage_add(total, u)
        cost += calculate_cost_usd(model, u)
    return cost, total


def process_claim(claim: dict, *, client, notes: str) -> str:
    from docket.ai.transcripts.alerts import post_alert
    from docket.ai.worker import RunSummary, _close_run, _open_run

    stage = STAGE_FOR_STATUS[claim["status"]]
    tid, mid = claim["id"], claim["meeting_id"]
    if stage == "speakers":
        reason = fitness_reason(claim.get("word_count"))
        if reason:
            mark_low_speech(tid, reason)
            log.info("transcript %s meeting %s -> low_speech (%s)", tid, mid, reason)
            return "low_speech"
        assign_index_points(tid, mid)

    run_name, model = RUN_NAME[stage], MODEL_FOR_STAGE[stage]
    with db() as conn:
        run_id = _open_run(conn, run_name, model, notes)
    summary = RunSummary(stage=run_name)
    emissions: list[tuple[str, Usage]] = []
    outcome = "transient"
    try:
        with usage_capture() as emissions:
            result = _stage_fn(stage)(claim, client=client)
        advance(tid, result)
        summary.rows_processed = 1
        outcome = "advanced" if result.skipped_reason is None else "skipped"
        log.info("transcript %s meeting %s: %s -> %s %s", tid, mid, claim["status"], result.next_status,
                 result.skipped_reason or "")
    except TranscriptHeld as e:
        mark_needs_review(tid, e.reason, str(e))
        summary.rows_failed = 1
        outcome = "held"
        post_alert("transcript_needs_review", f"Transcript for meeting {mid} held: {e.reason} ({e})",
                   meeting_id=mid, stage=stage, reason=e.reason)
    except AIPermanentRowError as e:
        mark_needs_review(tid, "permanent", str(e))
        summary.rows_failed = 1
        outcome = "held"
        post_alert("transcript_needs_review", f"Transcript for meeting {mid} held after {stage}: {e}",
                   meeting_id=mid, stage=stage, reason="permanent")
    except AIRateLimited as e:
        mark_transient(tid, f"rate limited: {e}")
        summary.rows_failed = 1
        outcome = "rate_limited"
    except AITransientError as e:
        status = mark_transient(tid, str(e))
        summary.rows_failed = 1
        outcome = "failed" if status == "failed" else "transient"
        if status == "failed":
            post_alert("transcript_failed", f"Transcript for meeting {mid} failed at {stage}: {e}",
                       meeting_id=mid, stage=stage)
    except AIFatalError:
        raise
    except Exception as e:  # a bug in a stage must not take the cron down
        log.exception("transcript %s stage %s crashed", tid, stage)
        status = mark_transient(tid, f"{type(e).__name__}: {e}")
        summary.rows_failed = 1
        outcome = "failed" if status == "failed" else "transient"
    finally:
        summary.cost_usd, summary.usage = _cost(emissions)
        with db() as conn:
            _close_run(conn, run_id, summary)
    return outcome


def _validate_models() -> None:
    for stage, model in MODEL_FOR_STAGE.items():
        if model not in PRICING:
            raise AIFatalError(f"{stage} model {model!r} has no PRICING entry; add it before running")


def run_transcript_pipeline(*, limit: int = TRANSCRIPT_PER_TICK, notes: str = "cron_transcripts",
                            force_budget: bool = False, client=None) -> PipelineSummary:
    from docket.ai.transcripts.alerts import alert_if_producer_stalled
    from docket.ai.transcripts.client import StructuredClient
    from docket.ai.worker import BudgetExceededError, _today_spend

    _validate_models()
    reset_for_versions()
    client = client or StructuredClient()
    s = PipelineSummary()
    for _ in range(limit):
        with db() as conn:
            spent = _today_spend(conn)
        if spent >= AI_DAILY_BUDGET_USD and not force_budget:
            if s.processed == 0:
                raise BudgetExceededError(
                    f"Today's AI spend ${spent:.2f} >= budget ${AI_DAILY_BUDGET_USD:.2f}; pass force_budget=True to override")
            s.stopped_reason = "budget"
            break
        claim = claim_next()
        if claim is None:
            break
        outcome = process_claim(claim, client=client, notes=notes)
        s.processed += 1
        setattr(s, outcome if outcome != "rate_limited" else "transient",
                getattr(s, outcome if outcome != "rate_limited" else "transient") + 1)
        if outcome == "rate_limited":
            s.stopped_reason = "rate_limited"
            break
    sweep_minutes_changes()
    alert_if_producer_stalled()
    log.info("transcript_pipeline %s", s)
    return s


def reset_for_versions() -> int:
    """Bumping a prompt version resets that stage and later ones only (spec: re-runs are per stage)."""
    from docket.ai.transcripts.prompts import COMPARE_PROMPT_VERSION, EVENTS_PROMPT_VERSION
    with db_cursor() as cur:
        cur.execute("""UPDATE transcripts t SET status = 'speakers_resolved', stage_attempts = 0, compare_skipped_reason = NULL
                        WHERE t.status IN ('events_extracted', 'compared')
                          AND EXISTS (SELECT 1 FROM meeting_events e WHERE e.meeting_id = t.meeting_id
                                         AND e.source = 'transcript' AND e.prompt_version < %s)""",
                    [EVENTS_PROMPT_VERSION])
        n = cur.rowcount
        cur.execute("""UPDATE transcripts t SET status = 'events_extracted', stage_attempts = 0
                        WHERE t.status = 'compared'
                          AND EXISTS (SELECT 1 FROM minutes_discrepancies d WHERE d.meeting_id = t.meeting_id
                                         AND d.prompt_version < %s)""", [COMPARE_PROMPT_VERSION])
        return n + cur.rowcount


def sweep_minutes_changes(limit: int = 10) -> int:
    """Placeholder until Task 12 fills it: returns 0."""
    return 0
