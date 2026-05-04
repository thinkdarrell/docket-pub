# Cron Worker Design

**Date:** 2026-05-04
**Status:** Approved (brainstorm)
**Scope:** A scheduled Railway worker process that runs the existing ingest, AI, and vote-matching pipelines on a daily cadence, plus a weekly cleanup pass. Closes T27 (the final remaining piece of the AI summaries + scoring milestone).

## Problem

docket.pub has been operating in a manual-trigger mode: every ingest, AI run, and vote-matching pass is kicked off by hand from a laptop. This works while a human is actively developing, but it does not scale to "data stays current without intervention," which the platform now needs.

Concretely, two gaps need to close:

1. **No recurring schedule.** New Birmingham meetings post weekly, minutes appear days later, and adoptions land at the next meeting. Without automation, every one of those events depends on remembering to run a CLI.
2. **Ingest sometimes flags a meeting as scraped without producing items.** Current Railway data shows ~10 meetings in the last 18 months with `processing_status.agenda_items_scraped = TRUE` but zero rows in `agenda_items`. These accumulate silently; nothing in the steady-state pipeline notices or recovers them.

A separate concern, **the 18-month AI backfill** (4,551 unprocessed items in the rolling 18-month window), is explicitly *out of scope* for the worker. It runs once as a manual `--force-budget` push from a laptop with full terminal observability, then the worker handles steady state thereafter.

## Goals

- Automate ingest, AI, and vote-matching on a daily schedule.
- Detect and recover meetings whose ingest produced no agenda items.
- Operate multi-city by default — the loop reads from the `municipalities` table; adding Mobile or Vestavia is a DB row, not a deploy.
- Surface failures within hours, not days, via Healthchecks.io heartbeats.
- Stay simple — no new business logic. The worker is a scheduler; existing services do the work.

## Non-Goals

- The 18-month AI backfill (manual one-shot, separate playbook).
- Real-time / event-driven ingest. Daily cadence is sufficient for civic data.
- A web UI for monitoring jobs. Healthchecks.io provides this off the shelf.
- Concurrency / parallel workers. One worker process running sequential jobs is sufficient and matches the AI worker's `SELECT FOR UPDATE SKIP LOCKED` design.

## Architecture

### Process model

A second Railway service named `worker`, declared in `Procfile`:

```
web: python -m docket.migrations.runner && gunicorn "docket.web:create_app()" --bind 0.0.0.0:${PORT:-5000} --timeout 120
worker: python -m docket.worker.scheduler
```

Both services share the same Docker image, env vars, and database. Deployed together on every `railway up --detach`. The `worker` process runs APScheduler's `BlockingScheduler` configured with `timezone='America/Chicago'`, so cron expressions read as Birmingham wall-clock time regardless of DST.

### Module layout

```
src/docket/worker/
  __init__.py          # package marker
  scheduler.py         # entry point — builds BlockingScheduler, registers jobs, calls .start(); supports --run-once <task>
  tasks.py             # the 5 task functions; each wraps work in try/except and pings Healthchecks
  health.py            # ping(task_name, status, body=None) helper; no-ops if UUID env var missing
```

The worker has **no business logic of its own**. `tasks.py` calls into existing entry points:

- `docket.services.ingest.ingest_municipality(slug)`
- `docket.ai.cli.run_items(limit=200)` and `run_meetings(limit=50)` (refactored from current `main()` to be importable)
- `docket.analysis.vote_matcher.match_all_unmatched()`
- A new helper `docket.services.maintenance.repair_empty_agendas()` for the cleanup pass

### Scheduled jobs

| # | Task | Schedule (CT) | Implementation |
|---|------|---------------|----------------|
| 0 | `repair_empty_agendas` | Mon 05:00 | New: clear `agenda_items_scraped` for non-cancelled meetings with empty agenda within last 18 months |
| 1 | `ingest_all` | Daily 06:00 | Loop `SELECT slug FROM municipalities`, call `ingest_municipality(slug)` per row. Adoption sweep already runs as Stage 5 inside ingest. |
| 2 | `ai_items` | Daily 07:00 | `run_items(limit=200)` — bounded by `AI_DAILY_BUDGET_USD` |
| 3 | `ai_meetings` | Daily 08:00 | `run_meetings(limit=50)` — picks up whatever the adoption sweep flipped |
| 4 | `vote_matching` | Daily 09:00 | `match_all_unmatched()` — idempotent, respects `is_manual=TRUE` shield at app and DB level |

Sequential ordering is intentional: ingest creates new items → Haiku scores them → Sonnet rolls up adopted meetings → matcher links any new votes to the now-existing items. Each step's output feeds the next, and stagger of one hour gives ample headroom even on the small Railway instance.

### `repair_empty_agendas` details

```python
def repair_empty_agendas() -> int:
    """Find meetings flagged scraped but with no items, clear the flag.

    Skips cancelled meetings (title matches /cancell?ed/i) — those legitimately
    have no items and re-scraping them is wasted work.
    """
    with db() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE processing_status ps
               SET agenda_items_scraped = FALSE
              FROM meetings m
             WHERE ps.meeting_id = m.id
               AND m.agenda_url IS NOT NULL
               AND m.meeting_date >= CURRENT_DATE - INTERVAL '18 months'
               AND ps.agenda_items_scraped = TRUE
               AND m.title !~* 'cancell?ed'
               AND NOT EXISTS (
                   SELECT 1 FROM agenda_items ai WHERE ai.meeting_id = m.id
               )
            RETURNING m.id
        """)
        cleared = cur.rowcount
    logger.info("repair_empty_agendas cleared=%d", cleared)
    return cleared
```

Lives in `src/docket/services/maintenance.py`. The next 06:00 `ingest_all` re-fetches whatever was cleared.

### Health monitoring

Each task wraps its work in try/except and pings Healthchecks.io:

```python
from docket.worker.health import ping

def _safe_run(task_name: str, fn):
    ping(task_name, "start")
    try:
        fn()
        ping(task_name, "success")
    except Exception:
        ping(task_name, "fail", body=traceback.format_exc())
        logger.exception("task=%s failed", task_name)
        # do NOT re-raise — APScheduler would log a noisy traceback and the
        # next run will fire on schedule regardless. Healthchecks is the alert path.
```

`health.py`:

```python
HEALTHCHECK_BASE = "https://hc-ping.com"
TASK_UUID_ENV = {
    "ingest_all":             "HEALTHCHECK_INGEST_UUID",
    "ai_items":               "HEALTHCHECK_AI_ITEMS_UUID",
    "ai_meetings":            "HEALTHCHECK_AI_MEETINGS_UUID",
    "vote_matching":          "HEALTHCHECK_VOTE_MATCH_UUID",
    "repair_empty_agendas":   "HEALTHCHECK_REPAIR_UUID",
}

def ping(task: str, status: str, body: str | None = None) -> None:
    uuid = os.environ.get(TASK_UUID_ENV[task])
    if not uuid:
        return  # silent in dev/local
    url = f"{HEALTHCHECK_BASE}/{uuid}"
    if status == "start":
        url += "/start"
    elif status == "fail":
        url += "/fail"
    try:
        requests.post(url, data=(body or "").encode("utf-8"), timeout=10)
    except Exception as e:
        # Network blip to Healthchecks.io shouldn't crash the worker, but it
        # should be visible in Railway logs so an operator doesn't mistake
        # "no ping arrived" for "the job didn't run."
        logger.warning("healthcheck ping failed task=%s status=%s err=%s", task, status, e)
```

A Healthchecks.io grace-period configuration per task (e.g., 1h grace on daily jobs, 6h on weekly) catches both "the cron didn't fire" and "the task started but never completed."

### `--run-once` flag

`scheduler.py` accepts an optional `--run-once <task>` argument. With it, the named task runs once in the foreground and the process exits — same logging, same error handling, same Healthchecks pings as a scheduled run. Without it, the process registers all jobs with `BlockingScheduler` and calls `.start()`.

```bash
# Manual one-shot from Railway console or laptop
railway run --service worker venv/bin/python -m docket.worker.scheduler --run-once ingest_all
```

This is the canonical way to trigger a single job for verification or recovery, ensuring environmental parity with scheduled runs.

## Data Model

No schema changes. The worker reads from `municipalities`, `meetings`, `processing_status`, `agenda_items`, `votes`, `vote_agenda_items`, `ai_runs` and writes through existing services that already handle these tables.

## Configuration

New env vars, all optional:

| Var | Purpose | Default |
|-----|---------|---------|
| `HEALTHCHECK_INGEST_UUID` | Healthchecks.io UUID for `ingest_all` | unset → no ping |
| `HEALTHCHECK_AI_ITEMS_UUID` | UUID for `ai_items` | unset → no ping |
| `HEALTHCHECK_AI_MEETINGS_UUID` | UUID for `ai_meetings` | unset → no ping |
| `HEALTHCHECK_VOTE_MATCH_UUID` | UUID for `vote_matching` | unset → no ping |
| `HEALTHCHECK_REPAIR_UUID` | UUID for `repair_empty_agendas` | unset → no ping |
| `WORKER_TIMEZONE` | APScheduler timezone | `America/Chicago` |

Existing `DATABASE_URL`, `ANTHROPIC_API_KEY`, `AI_DAILY_BUDGET_USD` are reused as-is.

## Dependencies

Add to `requirements.txt`:

```
apscheduler>=3.10
```

`requests` and `pytz` are already transitively present.

## Testing

Unit tests in `tests/unit/test_worker_*.py`:

- `test_health_ping_no_uuid_is_noop` — `ping()` returns silently when env var unset
- `test_health_ping_builds_correct_url` — start/success/fail map to correct URL suffixes
- `test_safe_run_pings_success_on_clean_run` — wrapper pings success on no-op task
- `test_safe_run_pings_fail_with_traceback_on_exception` — wrapper catches, pings, does not re-raise
- `test_repair_empty_agendas_skips_cancelled_meetings` — title regex correctly ignores "Cancelled" rows
- `test_repair_empty_agendas_skips_meetings_with_items` — only clears truly empty ones
- `test_repair_empty_agendas_only_within_18mo_window` — older empty meetings left alone

Integration smoke (manual, not CI): after deploy, `railway run --service worker venv/bin/python -m docket.worker.scheduler --run-once repair_empty_agendas` and verify the count returned matches a hand-counted query against the DB.

## Rollout

1. Land code on `feat/worker-cron` branch with full unit test coverage.
2. Run the **manual 18-month AI backfill** from laptop (out-of-scope for this design but a precondition):
   ```
   DATABASE_URL=$DATABASE_PUBLIC_URL ANTHROPIC_API_KEY=... \
     venv/bin/python -m docket.ai.cli --items --force-budget
   venv/bin/python -m docket.ai.cli --meetings --force-budget
   ```
3. Provision Healthchecks.io project and create 5 checks; copy UUIDs.
4. Set Railway env vars: `railway variables --set HEALTHCHECK_INGEST_UUID=...` (×5).
5. Merge PR → `railway up --detach` → confirm `worker` service appears in Railway dashboard.
6. Verify each task end-to-end via `--run-once` before letting the schedule take over:
   - `--run-once repair_empty_agendas`
   - `--run-once ingest_all` (small scope)
   - `--run-once ai_items`
   - `--run-once ai_meetings`
   - `--run-once vote_matching`
7. Watch Healthchecks dashboard for 48 hours to confirm cadence and grace periods are tuned correctly.

## Edge Cases (Birmingham-specific)

These were surfaced during brainstorming and are already handled by existing code; the worker does not need to add logic for them, but operators should be aware:

- **Cancelled meetings** — `repair_empty_agendas` filters them via title regex; otherwise they'd retry every Monday forever.
- **10.7% vote-level match rate** — known data ceiling for now (a separate fix is in flight to improve this). The matcher handles it correctly; don't relax thresholds in pursuit of a higher number.
- **Curly apostrophe in member names** — handled in `minutes_parser.py`; new members with punctuated names should be tested against the existing regex.
- **Council member roster gaps** — votes outside known term ranges resolve to NULL `council_member_id`. Backfill scripts handle this; the cron does not need to.
- **Strict re-parse zero-target safeguard** — `strict_reparse_meeting` aborts rather than mass-deactivating consent links if the enumerated list resolves to zero items. Don't "fix" it if it ever fires.
- **Manual shield (`is_manual=TRUE`)** — protected at both app and DB level in `_upsert_link`. Daily re-runs of the matcher cannot clobber manual edits.

## Risks & Mitigations

- **Cron silently broken (cosmic-ray scenario)** → Healthchecks.io grace-period alerts catch missing pings within an hour.
- **Anthropic rate limit during `ai_items`** → existing CLI already handles this; worst case the run aborts and tomorrow's run picks up where it left off. Daily budget cap acts as a second safety net.
- **Adapter breaks because city changed website** → `ingest_all` exception caught, `ingest` Healthcheck pings `/fail` with traceback, operator notified.
- **DB pressure** from concurrent jobs → not a concern: jobs are sequential, staggered by an hour.
- **Worker process crashes** → Railway auto-restarts. APScheduler's `coalesce=True` (default) means missed runs don't pile up; only the most recent is replayed on startup.
- **Cost overrun** → `AI_DAILY_BUDGET_USD` ($10 default) is a hard daily cap. Steady-state spend is ~$0.13/day; the cap mostly matters during prompt-version re-cascades.

## Open Questions

None — all surfaced questions resolved during brainstorming.

## References

- `src/docket/services/ingest.py:42` — `ingest_municipality(slug, since)`
- `src/docket/ai/cli.py:131` — current AI CLI entry point (will be refactored to expose `run_items` / `run_meetings` as importable functions)
- `src/docket/analysis/vote_matcher.py:730` — `match_all_unmatched()`
- `src/docket/analysis/vote_matcher.py:91` — `_upsert_link()` with manual-shield enforcement
- `Procfile` — current single-line web declaration
- CLAUDE.md — T27 ("Cron jobs not yet configured") flagged as the final remaining piece of the AI summaries + scoring milestone
