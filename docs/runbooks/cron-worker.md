# Cron Worker Runbook

The Railway `worker` service runs `python -m docket.worker.scheduler` and fires
five scheduled tasks (see the design spec at
`docs/superpowers/specs/2026-05-04-cron-worker-design.md`).

**Status:** Live in production as of 2026-05-04. Five Healthchecks.io UUIDs are wired into the `worker` service env vars; first verification run (`repair_empty_agendas`) completed cleanly with a green ping.

## Healthchecks.io setup (initial provisioning, retained for reference)

1. Sign up at https://healthchecks.io (free tier covers this entirely).
2. Create five checks. For each, copy the UUID from the ping URL
   (`https://hc-ping.com/<UUID>`).

   | Check name           | Schedule    | Grace |
   |----------------------|-------------|-------|
   | docket-ingest        | Daily 06:00 | 2h    |
   | docket-ai-items      | Daily 07:00 | 2h    |
   | docket-ai-meetings   | Daily 08:00 | 2h    |
   | docket-vote-matching | Daily 09:00 | 2h    |
   | docket-repair        | Mon 05:00   | 24h   |

3. Set Railway env vars (use `railway variables --set` with the actual UUIDs):

   ```bash
   railway variables --service worker --set HEALTHCHECK_INGEST_UUID=<uuid>
   railway variables --service worker --set HEALTHCHECK_AI_ITEMS_UUID=<uuid>
   railway variables --service worker --set HEALTHCHECK_AI_MEETINGS_UUID=<uuid>
   railway variables --service worker --set HEALTHCHECK_VOTE_MATCH_UUID=<uuid>
   railway variables --service worker --set HEALTHCHECK_REPAIR_UUID=<uuid>
   ```

4. (Optional) Configure notification channels in Healthchecks.io
   (email, Slack, etc.).

## Deploy

The `worker` service is a separate Railway service from `docket-web`, both deploying from the same Docker image. **Adding a `worker:` line to `Procfile` does NOT auto-create a Railway service** — you must create it once in the dashboard, then push code via CLI.

**One-time service creation** (already done for production):
1. Railway dashboard → **+ Create** → **Empty Service**, name it `worker`.
2. **Settings → Deploy → Custom Start Command:** `python -m docket.worker.scheduler` (this overrides the Procfile's `web:` line for this service).
3. **Variables tab:** copy from `docket-web` via Raw Editor. `DATABASE_URL` should be `${{Postgres.DATABASE_URL}}` (reference, not literal). Add the five `HEALTHCHECK_*_UUID` vars.
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
python -m docket.worker.scheduler --run-once vote_matching
python -m docket.worker.scheduler --run-once ingest_all
python -m docket.worker.scheduler --run-once ai_items
python -m docket.worker.scheduler --run-once ai_meetings
exit
```

Each should emit a Healthchecks ping (visible on the dashboard within seconds) and complete successfully. Order: do `repair` and `vote_matching` first — they're zero-cost (DB only). `ingest_all` hits Granicus and other adapters. `ai_items` and `ai_meetings` spend a few cents each on Anthropic.

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
2. The `health.ping(task, "fail", body=traceback)` line sends the traceback
   to Healthchecks, so the alert email/notification will include it.
3. Reproduce — either from a laptop with the public DB URL, or inside the container via `railway ssh --service worker`:
   ```bash
   # laptop
   DATABASE_URL=$(railway variables --service worker --kv | grep ^DATABASE_PUBLIC_URL= | cut -d= -f2-) \
     venv/bin/python -m docket.worker.scheduler --run-once <task>

   # in-container (preferred)
   railway ssh --service worker
   python -m docket.worker.scheduler --run-once <task>
   ```
4. Once fixed, re-trigger the task with `--run-once` via `railway ssh` to clear the
   "down" state on the corresponding Healthcheck.

**Note**: A green `docket-ingest` ping does not guarantee every city succeeded — `ingest_all` aggregates all five cities under a single check. If a specific municipality's data looks stale despite green pings, check Railway logs for per-city `ingest failed for <slug>` exceptions; per-city failures are caught and logged but do not fail the overall task.

## 18-month AI backfill (one-shot, separate from the worker)

The worker handles steady-state. To populate AI summaries/scoring for the
existing ~4,500 unprocessed items in the 18-month window, run from a laptop:

```bash
DATABASE_URL=$DATABASE_PUBLIC_URL ANTHROPIC_API_KEY=... \
  venv/bin/python -m docket.ai.cli --items --force-budget
DATABASE_URL=$DATABASE_PUBLIC_URL ANTHROPIC_API_KEY=... \
  venv/bin/python -m docket.ai.cli --meetings --force-budget
```

Estimated cost ~$12. Watch for tracebacks in real-time; if a corrupted PDF
trips the parser, you'll see it immediately rather than buried in Railway logs.
