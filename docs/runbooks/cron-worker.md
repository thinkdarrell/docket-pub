# Cron Worker Runbook

The Railway `worker` service runs `python -m docket.worker.scheduler` and fires
**eleven scheduled tasks** (see the design spec at
`docs/superpowers/specs/2026-05-04-cron-worker-design.md`; subsequent additions
documented in `~/docket-pub/CLAUDE.md`).

**Status:** Live in production since 2026-05-04. Task count grew from the original 5 through 2026-05 as Phase 2/3 features shipped (`process_badges`, `calibration_report`, `process_batches`, `refresh_backfill_ratio_mv`, `prune_analytics`, `video_ocr`).

## Task inventory

| Task | Cron (America/Chicago) | Healthchecks env var | Notes |
|---|---|---|---|
| `repair_empty_agendas` | Mon 05:00 | `HEALTHCHECK_REPAIR_UUID` | Clears stuck `agenda_items_scraped` flags |
| `refresh_backfill_ratio_mv` | Daily 04:30 | `HEALTHCHECK_REFRESH_BACKFILL_RATIO_UUID` | Refreshes `mv_city_backfill_ratio` (concurrent) |
| `prune_analytics` | Day 1, 04:00 (monthly) | `HEALTHCHECK_PRUNE_ANALYTICS_UUID` *(silent-by-design)* | Drops Umami events older than 24 months |
| `ingest_all` | Daily 06:00 | `HEALTHCHECK_INGEST_UUID` | Loops all municipalities; per-city failure isolation |
| `video_ocr` | Daily 06:30 | `HEALTHCHECK_VIDEO_OCR_UUID` | Claim pattern; 3-attempt cap; 60-day window |
| `ai_items` | Daily 07:00 | `HEALTHCHECK_AI_ITEMS_UUID` | v3 pipeline; gated by `AI_DAILY_BUDGET_USD` |
| `ai_meetings` | Daily 08:00 | `HEALTHCHECK_AI_MEETINGS_UUID` | Sonnet 4.6; two-phase (provisional → adopted) |
| `vote_matching` | Daily 09:00 | `HEALTHCHECK_VOTE_MATCH_UUID` | N:M matcher + strict re-parse |
| `process_badges` | Daily 09:30 | `HEALTHCHECK_PROCESS_BADGES_UUID` | Conservative policy badge writer |
| `calibration_report` | Daily 11:00 | `HEALTHCHECK_CALIBRATION_UUID` *(silent-by-design)* | Daily diagnostic, no production impact |
| `process_batches` | Every :00 and :30 | `HEALTHCHECK_PROCESS_BATCHES_UUID` | Anthropic Batches API polling (Phase 3 backfill) |

**Silent-by-design** = the task is in `health.py`'s `TASK_UUID_ENV` map (so `ping()` doesn't `KeyError`), but no UUID env var is set on the `worker` service. The ping call short-circuits at the env lookup. Used for tasks whose failure mode is local and self-recovering (`prune_analytics` — slightly longer data retention; `calibration_report` — daily diagnostic with no citizen impact). Adding a UUID later is a no-code change: create the check at healthchecks.io, set the env var, redeploy.

## Healthchecks.io setup

Each check should be created at https://healthchecks.io. Copy the UUID from the ping URL (`https://hc-ping.com/<UUID>`) and set it on the `worker` service:

```bash
railway variables --service worker --set HEALTHCHECK_INGEST_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_AI_ITEMS_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_AI_MEETINGS_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_VOTE_MATCH_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_REPAIR_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_PROCESS_BADGES_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_PROCESS_BATCHES_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_REFRESH_BACKFILL_RATIO_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_VIDEO_OCR_UUID=<uuid>
# silent-by-design (do not set unless you want active alerting):
# railway variables --service worker --set HEALTHCHECK_CALIBRATION_UUID=<uuid>
# railway variables --service worker --set HEALTHCHECK_PRUNE_ANALYTICS_UUID=<uuid>
```

Suggested schedule + grace per check:

| Check name                       | Schedule           | Grace |
|----------------------------------|--------------------|-------|
| docket-ingest                    | Daily 06:00        | 2h    |
| docket-video-ocr                 | Daily 06:30        | 2h    |
| docket-ai-items                  | Daily 07:00        | 2h    |
| docket-ai-meetings               | Daily 08:00        | 2h    |
| docket-vote-matching             | Daily 09:00        | 2h    |
| docket-process-badges            | Daily 09:30        | 2h    |
| docket-process-batches           | Every 30m          | 1h    |
| docket-refresh-backfill-ratio    | Daily 04:30        | 2h    |
| docket-repair                    | Mon 05:00          | 24h   |

(Optional) Configure notification channels in Healthchecks.io (email, Slack, etc.) after creating the checks.

## Deploy

The `worker` service is a separate Railway service from `docket-web`, both deploying from the same Docker image. **Adding a `worker:` line to `Procfile` does NOT auto-create a Railway service** — you must create it once in the dashboard, then push code via CLI.

**One-time service creation** (already done for production):
1. Railway dashboard → **+ Create** → **Empty Service**, name it `worker`.
2. **Settings → Deploy → Custom Start Command:** `python -m docket.worker.scheduler` (this overrides the Procfile's `web:` line for this service).
3. **Variables tab:** copy from `docket-web` via Raw Editor. `DATABASE_URL` should be `${{Postgres.DATABASE_URL}}` (reference, not literal). Add the `HEALTHCHECK_*_UUID` vars from the table above.
4. Click **Deploy** in the dashboard to commit staged changes.

**Per-deploy:**
```bash
railway up --service worker --detach
```

(The matching `railway up --detach` for `docket-web` is unchanged.)

## Verify each task end-to-end via --run-once

The canonical way to manually trigger a task is `railway ssh --service worker`, which drops you into a shell **inside the running container** where `postgres.railway.internal` resolves and all env vars are set:

```bash
railway ssh --service worker
# now inside the container
python -m docket.worker.scheduler --run-once repair_empty_agendas
python -m docket.worker.scheduler --run-once refresh_backfill_ratio_mv
python -m docket.worker.scheduler --run-once ingest_all
python -m docket.worker.scheduler --run-once video_ocr
python -m docket.worker.scheduler --run-once ai_items
python -m docket.worker.scheduler --run-once ai_meetings
python -m docket.worker.scheduler --run-once vote_matching
python -m docket.worker.scheduler --run-once process_badges
python -m docket.worker.scheduler --run-once calibration_report
python -m docket.worker.scheduler --run-once process_batches
python -m docket.worker.scheduler --run-once prune_analytics
exit
```

Each should emit a Healthchecks ping (visible on the dashboard within seconds — silent-by-design tasks skip the ping) and complete successfully. Order: do `repair` and `vote_matching` first — they're zero-cost (DB only). `ingest_all` hits Granicus and other adapters. `ai_items` and `ai_meetings` spend a few cents each on Anthropic. `video_ocr` runs ffmpeg + tesseract — note the worker RSS climbs to ~1.7 GB during an active scan (see "OCR worker resource ceiling" in CLAUDE.md key decisions).

**Don't use `railway run --service worker python ...`** — that runs locally on your laptop, not in the container, and `postgres.railway.internal` won't resolve. If you must drive a one-shot from your laptop (e.g., the worker container is down), substitute `DATABASE_URL=$DATABASE_PUBLIC_URL` and run from `~/docket-pub`:

```bash
DATABASE_URL=$(railway variables --service worker --kv | grep ^DATABASE_PUBLIC_URL= | cut -d= -f2-) \
  HEALTHCHECK_REPAIR_UUID=<uuid> \
  venv/bin/python -m docket.worker.scheduler --run-once repair_empty_agendas
```

## Manual one-off triggers

The `--run-once` invocation through `railway ssh` is the right pattern for ad-hoc runs in production. Prefer it over calling the underlying CLIs directly — `--run-once` runs through the same logging and Healthchecks pipeline as scheduled runs, so manual triggers don't silently bypass observability.

## When a Healthchecks alert fires

1. Check Railway logs for the worker service for the relevant time window.
2. The `health.ping(task, "fail", body=traceback)` line sends the traceback to Healthchecks, so the alert email/notification will include it.
3. Reproduce — either from a laptop with the public DB URL, or inside the container via `railway ssh --service worker`:
   ```bash
   # laptop
   DATABASE_URL=$(railway variables --service worker --kv | grep ^DATABASE_PUBLIC_URL= | cut -d= -f2-) \
     venv/bin/python -m docket.worker.scheduler --run-once <task>

   # in-container (preferred)
   railway ssh --service worker
   python -m docket.worker.scheduler --run-once <task>
   ```
4. Once fixed, re-trigger the task with `--run-once` via `railway ssh` to clear the "down" state on the corresponding Healthcheck.

**Note**: A green `docket-ingest` ping does not guarantee every city succeeded — `ingest_all` aggregates all cities under a single check. If a specific municipality's data looks stale despite green pings, check Railway logs for per-city `ingest failed for <slug>` exceptions; per-city failures are caught and logged but do not fail the overall task.

## 18-month AI backfill (one-shot, separate from the worker)

The worker handles steady-state. To populate AI summaries/scoring for historical items, use `python -m docket.ai.cli` from a laptop (see CLAUDE.md "AI pipeline operator commands" for the current invocation). The cron-driven `process_batches` task polls and ingests Anthropic Batches API results every 30 minutes, so submitting a batch via the CLI and waiting is the recommended path — the worker handles the ingest side automatically.
