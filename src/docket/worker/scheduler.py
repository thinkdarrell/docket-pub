"""APScheduler entry point for the docket.pub cron worker.

Two modes:

  python -m docket.worker.scheduler                   # daemon mode (Railway worker)
  python -m docket.worker.scheduler --run-once <task> # foreground one-shot

The daemon registers all seven jobs with the timezone in $WORKER_TIMEZONE
(default America/Chicago) and calls scheduler.start(), which blocks.

The one-shot mode runs a single named task in the foreground using the same
_safe_run wrapper as scheduled runs, ensuring environmental parity for
manual triggers and verification.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from docket.worker.tasks import TASKS

log = logging.getLogger(__name__)


def build_scheduler(timezone: str = "America/Chicago") -> BlockingScheduler:
    """Build a scheduler with all seven jobs registered. Does not start it."""
    sched = BlockingScheduler(timezone=timezone)

    sched.add_job(
        TASKS["repair_empty_agendas"],
        CronTrigger(day_of_week=0, hour=5, minute=0, timezone=timezone),
        id="repair_empty_agendas",
        coalesce=True,
        max_instances=1,
    )
    sched.add_job(
        TASKS["ingest_all"],
        CronTrigger(hour=6, minute=0, timezone=timezone),
        id="ingest_all",
        coalesce=True,
        max_instances=1,
    )
    sched.add_job(
        TASKS["video_ocr"],
        CronTrigger(hour=6, minute=30, timezone=timezone),
        id="video_ocr",
        coalesce=True,
        max_instances=1,
    )
    sched.add_job(
        TASKS["ai_items"],
        CronTrigger(hour=7, minute=0, timezone=timezone),
        id="ai_items",
        coalesce=True,
        max_instances=1,
    )
    sched.add_job(
        TASKS["ai_meetings"],
        CronTrigger(hour=8, minute=0, timezone=timezone),
        id="ai_meetings",
        coalesce=True,
        max_instances=1,
    )
    sched.add_job(
        TASKS["vote_matching"],
        CronTrigger(hour=9, minute=0, timezone=timezone),
        id="vote_matching",
        coalesce=True,
        max_instances=1,
    )
    sched.add_job(
        TASKS["process_badges"],
        CronTrigger(hour=9, minute=30, timezone=timezone),
        id="process_badges",
        coalesce=True,
        max_instances=1,
    )
    sched.add_job(
        TASKS["calibration_report"],
        CronTrigger(hour=11, minute=0, timezone=timezone),
        id="calibration_report",
        coalesce=True,
        max_instances=1,
    )
    # Phase 3 backfill: poll + ingest Anthropic batch results every 30 min.
    # Anthropic Batches API has a 24h SLA but typically completes in 1-4h —
    # 30-min polling keeps latency low without pounding their endpoint.
    sched.add_job(
        TASKS["process_batches"],
        CronTrigger(minute="0,30", timezone=timezone),
        id="process_batches",
        coalesce=True,
        max_instances=1,
    )
    # Refresh mv_city_backfill_ratio daily before ingest_all so the
    # volume-timeline partial reads a fresh ratio. ~50ms; concurrent
    # refresh via the UNIQUE INDEX on city_id (migration 025).
    sched.add_job(
        TASKS["refresh_backfill_ratio_mv"],
        CronTrigger(hour=4, minute=30, timezone=timezone),
        id="refresh_backfill_ratio_mv",
        coalesce=True,
        max_instances=1,
    )
    # Monthly retention: drop Umami events older than 24 months.
    # 1st of the month at 04:00 America/Chicago — before the morning task
    # cluster, when DB pressure is lowest.
    sched.add_job(
        TASKS["prune_analytics"],
        CronTrigger(day=1, hour=4, minute=0, timezone=timezone),
        id="prune_analytics",
        coalesce=True,
        max_instances=1,
    )
    return sched


def run_once_task(name: str) -> None:
    """Foreground execution of a single named task. Exits non-zero on unknown name."""
    if name not in TASKS:
        sys.exit(f"unknown task: {name!r} (known: {sorted(TASKS)})")
    TASKS[name]()


def main() -> None:
    parser = argparse.ArgumentParser(description="docket.pub cron worker")
    parser.add_argument(
        "--run-once",
        metavar="TASK",
        help="Run a single task in the foreground and exit (e.g. --run-once ingest_all)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.run_once:
        run_once_task(args.run_once)
        return

    tz = os.environ.get("WORKER_TIMEZONE", "America/Chicago")
    sched = build_scheduler(timezone=tz)
    log.info(
        "docket.pub worker starting timezone=%s jobs=%d", tz, len(sched.get_jobs())
    )
    for job in sched.get_jobs():
        next_run = getattr(job, "next_run_time", None)
        log.info("  job=%s next_run=%s", job.id, next_run)
    sched.start()  # blocks


if __name__ == "__main__":
    main()
