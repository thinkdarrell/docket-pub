# v3 Pipeline Cutover Runbook (FINAL-1 through FINAL-3)

The Impact-First Refactor Phase 2 ships the v3 AI pipeline (Stage 1 extraction → Stage 2 Smart Brevity rewrite → Stage 2.5 floors → reconcile → atomic commit with badges) behind the `IMPACT_FIRST_ENABLED` env-var flag. The flag defaults to **false** — deploying the code does NOT change production behavior. Flipping the flag at **FINAL-3** is the cutover.

This runbook covers the pre-flag-flip audit (FINAL-1 → FINAL-2 confidence window → FINAL-3 flag flip) and what to do if production goes sideways post-flip.

For the parallel citizen-rendering flip (`SMART_BREVITY_UI=true`) see `smart-brevity-ui-flip.md`.

---

## Current state

- **Phase 2 merged to main** as of PR #8 (commit `244699a`).
- **`docket-web` + `worker` services deployed** to Railway on the new code. v2 cron tasks continue to run (`IMPACT_FIRST_ENABLED=false` is the default).
- **Migrations 1–13, 15, 16 applied on Railway prod.** Migration 016 verified live (`agenda_item_badges_audit.agenda_item_id` is `ON DELETE SET NULL`).
- **Live smoke test passed** against the production Anthropic key (`tests/live/test_pipeline_live.py`).

## FINAL-1 verification (post-deploy, done)

| Check | Status | How to re-verify |
|---|---|---|
| `docket-web` service running v3 code | ✓ | `railway logs --service docket-web \| head -3` — expect `gunicorn ... Listening at: http://0.0.0.0:8080` |
| `worker` service running v3 code | ✓ | `railway logs --service worker \| head -5` — expect APScheduler jobs registered |
| Migrations on prod | ✓ | `railway ssh --service docket-web "cd /app && python -m docket.migrations.runner --status"` |
| v2 cron still firing | (let one cycle pass) | Healthchecks.io UUIDs in `HEALTHCHECK_*_UUID` env vars on the worker service — log into hc.io to view ping history |

## FINAL-2 confidence window

Recommend **24–48 hours minimum** before flipping the flag. During the window:

1. **Watch the next `ai_items` cron cycle.** Fires at 07:00 America/Chicago daily. With the flag false, the v2 worker path executes — `_process_items` claims items where `ai_prompt_version IS NULL OR < ITEM_PROMPT_VERSION`, calls v2 Haiku item-summaries, writes results.
2. **Watch the next `ai_meetings` cycle** (08:00 CDT). Should also be v2 unchanged — `IMPACT_FIRST_ENABLED` doesn't gate the meetings stage.
3. **Watch Healthchecks.io ping history** for all 5 cron tasks. Any unexpected failure pings → investigate before proceeding.
4. **Spot-check citizen-facing rendering** at https://docket.pub (apex domain). With `SMART_BREVITY_UI=false` (default) the v2 cards keep rendering — no visual change should be observable.

Manual trigger to force an immediate v2 run (if you don't want to wait for cron):
```bash
railway ssh --service worker "cd /app && python -m docket.worker.scheduler --run-once ai_items"
```

## Task #52 — Monitoring audit (BLOCKS FINAL-3)

**The problem:** v3 batches have `summary.cost_usd = 0.0` in `ai_runs` rows (decision #10 of the B5 plan — `usage` is not threaded through extraction.py / rewrite.py). After the flag flip, every `ai_items` v3 batch will record $0.00 cost even though Anthropic was actually called.

**Action items to complete before FINAL-3:**

### Healthchecks.io
- [ ] **Log into hc.io** with the docket.pub account
- [ ] **Locate the 5 cron-task checks** corresponding to `HEALTHCHECK_*_UUID` env vars on the worker service: `repair_empty_agendas`, `ingest_all`, `ai_items`, `ai_meetings`, `vote_matching`
- [ ] **Verify the success-ping body** isn't asserting cost > 0 (the project's success ping is a no-body GET per `src/docket/worker/health.py`, so this should be fine — confirm)
- [ ] **Verify no alerting rules** depend on the ping body containing cost data
- [ ] **Check fail-ping behavior** — the worker pings fail with the exception traceback per `_safe_run` in `worker/tasks.py`. `BudgetExceededError` is swallowed in AI tasks and pings success (expected). Confirm.

### Grafana (if configured)
- [ ] **Log into the Grafana instance** (if any — the project memory doesn't reference Grafana directly, but the FINAL-3 monitoring may have it)
- [ ] **Audit dashboards for `ai_runs.cost_usd` queries** that alert on zero-spend or below-threshold:
  - SQL pattern: `SELECT cost_usd FROM ai_runs WHERE stage='items' ORDER BY id DESC LIMIT N`
  - Any alert with predicate `cost_usd = 0` or `cost_usd < $X` for items stage will fire constantly post-flip
- [ ] **Temporarily mute** any such alerts, OR add a query exception for `cost_usd = 0` on v3 batches
- [ ] **Document the v3 spend** by querying `ai_runs.usage` JSONB directly (still populated; just not the `cost_usd` column):
  ```sql
  SELECT
    started_at,
    (usage->>'input_tokens')::int AS input_tokens,
    (usage->>'output_tokens')::int AS output_tokens,
    (usage->>'cache_read_input_tokens')::int AS cache_read,
    (usage->>'cache_creation_input_tokens')::int AS cache_create
  FROM ai_runs
  WHERE stage='items' AND started_at > NOW() - INTERVAL '24 hours'
  ORDER BY id DESC;
  ```
  Wait — see "Known gap" below: v3 does NOT populate `usage` either today. The above query returns NULLs for v3 batches.

### Known gap (informational)

Decision #10 of the B5 plan accepted "no `usage` tracking in v3 v1." `extraction.py` and `rewrite.py` swallow the anthropic `response.usage` field rather than returning it through the call chain. The pipeline doesn't thread it; the worker doesn't accumulate it. So `ai_runs` rows for v3-only batches will have:
- `cost_usd = 0.0`
- `usage = NULL` (no JSONB)

**This is intentional v1 scope.** The follow-up to backfill usage threading is task #54 (post-Phase-2 cleanup). Until then, v3 batches are invisible to cost-based monitoring — operators rely on:
1. **Anthropic dashboard** for actual spend (login: console.anthropic.com)
2. **`AI_DAILY_BUDGET_USD` enforcement** — the worker reads `ai_runs.cost_usd` sum to gate new batches. With v3 reporting $0, the gate effectively never fires for v3 batches. **Consider lowering the gate or setting an Anthropic-side spend limit** as a backstop before FINAL-3.

### Anthropic-side spend limit (recommended)

Before flipping the flag:
- [ ] Log into console.anthropic.com
- [ ] Set a daily or monthly spend cap on the production API key as a hard backstop
- [ ] Set up email/SMS alerting on the spend cap at 50% / 80% / 100%

Decision-#10's gap means Railway's `AI_DAILY_BUDGET_USD` won't catch a v3 runaway. The Anthropic dashboard is the only enforcement that will.

## FINAL-3 flag flip procedure

Once tasks #52 (this runbook) and #53 (live smoke test, already done) are complete AND the confidence window has passed:

1. **Flip the flag on the worker service:**
   ```bash
   cd ~/docket-pub
   railway variables --service worker --set IMPACT_FIRST_ENABLED=true
   ```
   This restarts the worker with the new env var. The next `ai_items` cron cycle will route through `_process_items_v3` instead of `_process_items`.

2. **(Optional) Flip the flag on `docket-web`** — only matters if a Flask route imports the worker's dispatch logic. Most paths don't; the flag is worker-relevant. Leave docket-web as `IMPACT_FIRST_ENABLED=false` initially.

3. **Force an immediate v3 run** to verify in real time (skips waiting for 07:00 cron):
   ```bash
   railway ssh --service worker "cd /app && python -m docket.worker.scheduler --run-once ai_items"
   ```
   Watch for:
   - Items in `processing_status='pending'` move to `'completed'` or `'cross_stage_conflict'`
   - `extracted_facts` JSONB populated
   - `headline` + `why_it_matters` populated
   - `agenda_item_badges` rows insert with `kind='process'` or `'policy'`
   - No tracebacks in Railway logs

4. **First-hour validation:**
   ```sql
   -- On the prod DB, count v3-processed items in the last hour:
   SELECT processing_status::text, COUNT(*)
   FROM agenda_items
   WHERE ai_rewrite_version IS NOT NULL
     AND updated_at > NOW() - INTERVAL '1 hour'  -- if updated_at exists
   GROUP BY processing_status;
   ```
   Note: the column referenced as `updated_at` doesn't exist in this schema (B-S4 deferred item). Use a different freshness proxy — perhaps look at recent badge inserts:
   ```sql
   SELECT COUNT(*) FROM agenda_item_badges WHERE detected_at > NOW() - INTERVAL '1 hour';
   ```

5. **Expect a small fraction in `cross_stage_conflict`** — reconcile escalates items where Stage 1 found substance but Stage 2 said procedural after retry. Per Section 7.5 of the spec, anything >5% should halt the next wave. Spot-check a few via the new `/admin/review/conflicts` queue.

## Rollback procedure

If v3 runs poorly post-flip:

1. **Immediate kill-switch:**
   ```bash
   cd ~/docket-pub
   railway variables --service worker --set IMPACT_FIRST_ENABLED=false
   ```
   Worker restarts; next cron cycle routes through v2 again. Items already processed by v3 stay at their `completed` / `cross_stage_conflict` state (no rollback to `pending`). v2 won't re-process them because v2's claim query filters on `ai_prompt_version` not `ai_extraction_version`.

2. **Investigate via Railway logs** + `ai_runs` table:
   ```sql
   SELECT id, started_at, finished_at, rows_processed, rows_failed, notes
   FROM ai_runs ORDER BY id DESC LIMIT 10;
   ```

3. **If specific items are broken, reset them to pending:**
   ```sql
   UPDATE agenda_items
   SET processing_status = 'pending',
       ai_extraction_version = NULL,
       ai_rewrite_version = NULL,
       extracted_facts = NULL,
       headline = NULL,
       why_it_matters = NULL,
       significance_score = NULL,
       consent_placement_score = NULL,
       score_overrides = NULL
   WHERE id IN (...);
   -- Also clean up the badge rows on those items:
   DELETE FROM agenda_item_badges WHERE agenda_item_id IN (...);
   ```
   The next v2 cycle will then re-process them via the v2 pipeline (which writes the old `summary` column instead of headline / why_it_matters / extracted_facts).

## Phase 3 backfill (post-FINAL-3)

Once FINAL-3 is stable, Phase 3 kicks off the backfill of ~37K LLM-eligible items via the Anthropic Batches API (50% discount). Estimated cost ~$100, calendar time 7–14 days at the budget cap. Plan: `docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-3.md`.

The `docket.ai.cli` already supports the relevant ops:
- `--status` queue depth + cost
- `--items --limit N` process N items
- `--force-budget` override daily cap

Run inside the container (Railway public proxy makes per-row latency prohibitive):
```bash
railway ssh --service docket-web "cd /app && python -m docket.ai.cli --status"
```

## Followup tasks still open

- **#52** (this runbook is the audit framework — operator executes manually)
- **#53** (done: live smoke test passed 2026-05-11)
- **#54** — backfill `usage` threading through `extraction.py` → `rewrite.py` → `pipeline.py` → `worker.py` so v3 batches report cost. Defers monitoring observability. ~4-file refactor.
- **#48** — fix G1 flaky date-sensitive test
- **#50** — stray `login_required` reference at `admin.py:445`
- **#51** — optional CSS-token drift CI script
