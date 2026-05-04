# Cron Worker Runbook

The Railway `worker` service runs `python -m docket.worker.scheduler` and fires
five scheduled tasks (see the design spec at
`docs/superpowers/specs/2026-05-04-cron-worker-design.md`).

## Healthchecks.io setup (do this BEFORE merging to main)

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

```bash
railway up --detach
```

Confirm a `worker` service appears in the Railway dashboard alongside `web`.

## Verify each task end-to-end via --run-once

After deploy, run each task once in the foreground via Railway's shell:

```bash
railway run --service worker venv/bin/python -m docket.worker.scheduler --run-once repair_empty_agendas
railway run --service worker venv/bin/python -m docket.worker.scheduler --run-once ingest_all
railway run --service worker venv/bin/python -m docket.worker.scheduler --run-once ai_items
railway run --service worker venv/bin/python -m docket.worker.scheduler --run-once ai_meetings
railway run --service worker venv/bin/python -m docket.worker.scheduler --run-once vote_matching
```

Each should emit a Healthchecks ping (visible on the dashboard within seconds)
and complete successfully.

## Manual one-off triggers

The same `--run-once` invocation works for ad-hoc runs in production. Prefer it
over calling the underlying CLIs directly — `--run-once` runs through the same
logging and Healthchecks pipeline as scheduled runs, so manual triggers don't
silently bypass observability.

## When a Healthchecks alert fires

1. Check Railway logs for the worker service for the relevant time window.
2. The `health.ping(task, "fail", body=traceback)` line sends the traceback
   to Healthchecks, so the alert email/notification will include it.
3. Reproduce locally:
   ```bash
   DATABASE_URL=$DATABASE_PUBLIC_URL venv/bin/python -m docket.worker.scheduler --run-once <task>
   ```
4. Once fixed, re-trigger the task with `--run-once` from Railway to clear the
   "down" state on the corresponding Healthcheck.

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
