"""Healthchecks.io ping helper for the cron worker.

One UUID per task lives in env vars; the helper is a no-op when the
corresponding UUID is missing, so dev/local runs don't need any setup.
"""

from __future__ import annotations

import logging
import os
from typing import Literal

import requests

log = logging.getLogger(__name__)

HEALTHCHECK_BASE = "https://hc-ping.com"

# Task name → env var name. Unknown task names are a programmer error.
TASK_UUID_ENV: dict[str, str] = {
    "ingest_all":               "HEALTHCHECK_INGEST_UUID",
    "ai_items":                 "HEALTHCHECK_AI_ITEMS_UUID",
    "ai_meetings":              "HEALTHCHECK_AI_MEETINGS_UUID",
    "vote_matching":            "HEALTHCHECK_VOTE_MATCH_UUID",
    "repair_empty_agendas":     "HEALTHCHECK_REPAIR_UUID",
    "process_badges":           "HEALTHCHECK_PROCESS_BADGES_UUID",
    "calibration_report":       "HEALTHCHECK_CALIBRATION_UUID",
    "process_batches":          "HEALTHCHECK_PROCESS_BATCHES_UUID",
    # No Healthchecks UUID configured for the MV refresh — failure
    # mode is local (one-day stale ratio) and self-recovers. The map
    # entry is here so ping() in _safe_run() doesn't KeyError; ping()
    # short-circuits when the env var is unset.
    "refresh_backfill_ratio_mv": "HEALTHCHECK_REFRESH_BACKFILL_RATIO_UUID",
    # No Healthchecks UUID configured yet for analytics pruning — failure
    # mode is cosmetic (slightly longer data retention) and self-recovers.
    # The map entry is here so ping() in _safe_run() doesn't KeyError;
    # ping() short-circuits when the env var is unset.
    "prune_analytics":           "HEALTHCHECK_PRUNE_ANALYTICS_UUID",
}

PingStatus = Literal["start", "success", "fail"]


def ping(task: str, status: PingStatus, body: str | None = None) -> None:
    """Ping Healthchecks.io for a task lifecycle event.

    No-ops when the task's UUID env var is unset (e.g., local dev).
    Network errors are logged at WARNING and swallowed — the worker must
    never crash because the monitoring endpoint is unreachable.
    """
    env_var = TASK_UUID_ENV[task]  # KeyError on unknown task — intentional
    uuid = os.environ.get(env_var)
    if not uuid:
        return

    url = f"{HEALTHCHECK_BASE}/{uuid}"
    if status == "start":
        url += "/start"
    elif status == "fail":
        url += "/fail"

    try:
        requests.post(url, data=(body or "").encode("utf-8"), timeout=10)
    except Exception as e:
        # A network blip to Healthchecks.io shouldn't crash the worker, but it
        # should be visible in Railway logs so an operator doesn't mistake
        # "no ping arrived" for "the job didn't run."
        log.warning("healthcheck ping failed task=%s status=%s err=%s", task, status, e)
