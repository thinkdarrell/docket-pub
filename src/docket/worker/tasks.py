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
import traceback
from typing import Callable

from docket.ai.worker import BudgetExceededError, run_once
from docket.analysis.vote_matcher import match_all_unmatched
from docket.db import db_cursor
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


# --- registry — used by scheduler.py and the --run-once flag -----------------

TASKS: dict[str, Callable[[], None]] = {
    "ingest_all":           task_ingest_all,
    "ai_items":             task_ai_items,
    "ai_meetings":          task_ai_meetings,
    "vote_matching":        task_vote_matching,
    "repair_empty_agendas": task_repair_empty_agendas,
}
