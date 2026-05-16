"""Task functions for the cron worker.

Each public task entry point is wrapped via _safe_run, which handles
Healthchecks pings and exception swallowing. The internal _do_* helpers
contain the actual work and are unit-tested directly.

Tasks intentionally call existing services and keep no business logic
of their own. The worker is a scheduler; ingest, AI, and matching
modules do the work.
"""

from __future__ import annotations

import logging
import os
import traceback
from typing import Callable

import psycopg2 as psycopg

from docket.ai.worker import BudgetExceededError, run_once
from docket.analysis.vote_matcher import match_all_unmatched
from docket.db import db, db_cursor
from docket.services.ingest import ingest_municipality
from docket.services.maintenance import repair_empty_agendas
from docket.worker import health

log = logging.getLogger(__name__)


def _safe_run(task_name: str, fn: Callable[[], None]) -> None:
    """Run a task with Healthchecks pings, catching exceptions.

    Does not re-raise. APScheduler's built-in error logging is noisy and
    duplicative — we own error reporting through Healthchecks instead.
    """
    health.ping(task_name, "start")
    try:
        fn()
        health.ping(task_name, "success")
    except Exception:
        tb = traceback.format_exc()
        log.exception("task=%s failed", task_name)
        health.ping(task_name, "fail", body=tb)


# --- internal task implementations -------------------------------------------

def _do_ingest_all() -> None:
    """Loop over every active municipality and run the ingest pipeline.

    A failure for one city is logged but does not block the others.
    """
    with db_cursor() as cur:
        cur.execute("SELECT slug FROM municipalities WHERE active = TRUE ORDER BY slug")
        rows = cur.fetchall()

    for row in rows:
        slug = row["slug"]
        try:
            ingest_municipality(slug)
        except Exception:
            log.exception("ingest failed for %s", slug)


def _do_ai_items() -> None:
    try:
        run_once(stage="items", limit=200, notes="cron_items")
    except BudgetExceededError as e:
        # Hitting the daily cap is expected behavior, not a failure.
        log.info("ai_items skipped: %s", e)


def _do_ai_meetings() -> None:
    try:
        run_once(stage="meetings", limit=50, notes="cron_meetings")
    except BudgetExceededError as e:
        log.info("ai_meetings skipped: %s", e)


def _do_vote_matching() -> None:
    result = match_all_unmatched()
    log.info(
        "vote_matching meetings=%d ts=%d sub=%d consent=%d",
        result.get("meetings", 0),
        result.get("timestamp_matched", 0),
        result.get("substantive_matched", 0),
        result.get("consent_matched", 0),
    )


def _do_repair_empty_agendas() -> None:
    repair_empty_agendas()


def _do_process_badges() -> None:
    """Recompute deterministic process badges for items modified in last 36h.

    Runs after the AI pipeline (which sets processing_status='completed').
    Uses pg_try_advisory_lock so a manual --run-once can't collide with the
    nightly schedule. Manual badges (source='manual') are preserved
    (decision #57). Spec §4.5.
    """
    from docket.ai.badges_process import PROCESS_BADGE_QUERIES

    LOCK_KEY = "docket.process_badges"
    with db_cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", [LOCK_KEY])
        got_lock = cur.fetchone()[0]
        if not got_lock:
            log.warning("process_badges already running, skipping")
            return

        try:
            cur.execute("""
                CREATE TEMP TABLE recent_items ON COMMIT DROP AS
                SELECT id FROM agenda_items
                 WHERE updated_at > NOW() - INTERVAL '36 hours'
                   AND processing_status = 'completed';
            """)

            cur.execute("""
                DELETE FROM agenda_item_badges
                 WHERE kind = 'process'
                   AND source != 'manual'
                   AND agenda_item_id IN (SELECT id FROM recent_items);
            """)

            for query in PROCESS_BADGE_QUERIES:
                cur.execute(query)
        finally:
            cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", [LOCK_KEY])


# --- public, _safe_run-wrapped entry points ----------------------------------

def task_ingest_all() -> None:
    _safe_run("ingest_all", _do_ingest_all)


def task_ai_items() -> None:
    _safe_run("ai_items", _do_ai_items)


def task_ai_meetings() -> None:
    _safe_run("ai_meetings", _do_ai_meetings)


def task_vote_matching() -> None:
    _safe_run("vote_matching", _do_vote_matching)


def task_repair_empty_agendas() -> None:
    _safe_run("repair_empty_agendas", _do_repair_empty_agendas)


def task_process_badges() -> None:
    _safe_run("process_badges", _do_process_badges)


def _do_calibration_report() -> None:
    """Daily calibration: 4 queries summarizing AI scoring drift + cache cleanup.

    Logs a single structured line with counters; admins can re-query
    individual sections from the cache_cleanup-aware admin dashboard later.
    Spec §3.5 + decision #91.
    """
    from docket.ai.cache import cache_cleanup
    from docket.ai.calibration import run_calibration_queries

    with db_cursor() as cur:
        counts = run_calibration_queries(cur)

    n_cache_deleted = cache_cleanup(max_age_days=90)

    log.info(
        "calibration_report: divergence=%d underscoring=%d overscoring=%d "
        "drift_alerts=%d cache_cleanup=%d",
        counts['divergence_count'],
        counts['underscoring_categories'],
        counts['overscoring_categories'],
        counts['drift_alerts'],
        n_cache_deleted,
    )


def task_calibration_report() -> None:
    _safe_run("calibration_report", _do_calibration_report)


def _do_process_batches() -> None:
    """Poll all in-flight Anthropic batches and ingest any newly-ended ones.

    Phase 3 backfill submits items to the Batches API
    (``docket.ai.cli --wave N --stage S``); Anthropic processes them
    async with a 24h SLA. This task drains the queue: it polls every
    `submitted`/`in_progress` row in `ai_batches`, marks `ended`
    ones, then downloads + ingests results into `agenda_items` via
    ``docket.ai.batch_ingest.poll_and_ingest``. Idempotent and safe
    to run as often as desired.
    """
    from docket.ai.batch_ingest import poll_and_ingest
    summary = poll_and_ingest()
    log.info(
        "process_batches polled=%d ingested=%d items_succeeded=%d items_errored=%d",
        summary.batches_polled, summary.batches_ingested,
        summary.items_succeeded, summary.items_errored,
    )


def task_process_batches() -> None:
    _safe_run("process_batches", _do_process_batches)


def _do_refresh_backfill_ratio_mv() -> None:
    """Refresh ``mv_city_backfill_ratio`` (migration 025).

    The MV caches the v3-completed fraction per city — read by the
    category-landing volume-timeline partial (PR D) to pick the
    backfill-banner copy variant. ~50ms on prod; the UNIQUE INDEX on
    ``city_id`` lets us use CONCURRENTLY so readers don't block.

    Failure mode is local (stale ratio for one day) and self-recovers
    the next run; no Healthchecks ping.
    """
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_city_backfill_ratio"
            )
        conn.commit()


def task_refresh_backfill_ratio_mv() -> None:
    _safe_run("refresh_backfill_ratio_mv", _do_refresh_backfill_ratio_mv)


def _do_prune_analytics() -> dict[str, int]:
    """Delete Umami events older than 24 months.

    Connects to the umami database via $ANALYTICS_DATABASE_URL (a separate
    DSN from the editorial $DATABASE_URL — different role, different db).
    Idempotent; returns the deleted row count.
    """
    dsn = os.environ["ANALYTICS_DATABASE_URL"]
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM website_event "
            "WHERE created_at < NOW() - INTERVAL '24 months'"
        )
        deleted = cur.rowcount
        conn.commit()
    log.info("prune_analytics deleted=%d", deleted)
    return {"deleted": deleted}


def task_prune_analytics() -> None:
    _safe_run("prune_analytics", _do_prune_analytics)


# --- registry — used by scheduler.py and the --run-once flag -----------------

TASKS: dict[str, Callable[[], None]] = {
    "repair_empty_agendas":      task_repair_empty_agendas,
    "ingest_all":                task_ingest_all,
    "ai_items":                  task_ai_items,
    "ai_meetings":               task_ai_meetings,
    "vote_matching":             task_vote_matching,
    "process_badges":            task_process_badges,
    "calibration_report":        task_calibration_report,
    "process_batches":           task_process_batches,
    "refresh_backfill_ratio_mv": task_refresh_backfill_ratio_mv,
    "prune_analytics":           task_prune_analytics,
}
