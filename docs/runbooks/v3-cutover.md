# v3 Pipeline Cutover Runbook (FINAL-1 through FINAL-3)

> **Status: HISTORICAL — flag flipped in production on 2026-05-12.**
> Both `IMPACT_FIRST_ENABLED=true` (worker) and `SMART_BREVITY_UI=true`
> (docket-web) are the live state. This runbook is preserved as the
> audit record of the pre-flip checklist and as the rollback procedure
> if v3 ever needs to be disabled. The pre-flip checklist and FINAL-1/
> FINAL-2 sections below are no longer actionable — see the Rollback
> Procedure for the operationally-relevant portion. Several outstanding
> follow-ups referenced here (#54 usage threading, #57 self-deadlock)
> have since shipped; see `~/docket-pub/CLAUDE.md` for current state.

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

**The problem:** v3 batches have `summary.cost_usd = 0.0` AND `usage = NULL` in `ai_runs` rows (decision #10 of the B5 plan — `extraction.py` and `rewrite.py` swallow `response.usage` rather than threading it through the call chain). After the flag flip, every `ai_items` v3 batch will record $0.00 cost even though Anthropic was actually called. Railway-side `AI_DAILY_BUDGET_USD` enforcement reads `cost_usd` sum, so the gate effectively never fires for v3 batches. **The Anthropic dashboard becomes the only spend enforcement.** Task #54 (post-Phase-2 cleanup) restores Railway-side enforcement by threading `usage` through the v3 pipeline.

**Project monitoring stack (no Grafana / Prometheus / Datadog configured):**
1. **Healthchecks.io** — primary cron alerting (5 UUIDs in `HEALTHCHECK_*_UUID` env vars on the `worker` service)
2. **Railway built-in** — `railway logs --service <name>` + dashboard CPU/memory/restart count
3. **Anthropic console** — `console.anthropic.com` for actual API spend

**Action items to complete before FINAL-3:**

### Healthchecks.io audit
- [ ] **Log into hc.io** with the docket.pub account
- [ ] **Locate the 5 cron-task checks** corresponding to `HEALTHCHECK_*_UUID` env vars on the worker service: `repair_empty_agendas`, `ingest_all`, `ai_items`, `ai_meetings`, `vote_matching`
- [ ] **Verify all 5 are currently green** (last ping success, no alerts firing)
- [ ] **Confirm the success-ping body** isn't asserting cost > 0 — the project's success ping is a POST with empty body per `src/docket/worker/health.py` (the body arg defaults to `None` and `_safe_run` never passes one on success), so any cost-based alerting at this layer is impossible. Quick visual confirmation only.
- [ ] **Confirm `BudgetExceededError`-swallow path still pings success** in the AI tasks (expected per project memory — the worker treats budget-exceeded as a graceful no-op).

### Anthropic-side spend cap (CRITICAL BACKSTOP)
- [ ] **Log into console.anthropic.com** with the docket.pub Anthropic account
- [ ] **Set a daily or monthly spend cap** on the production API key — current v3 cost expectation is ~$0.0024/item × ~37K items at peak Phase 3 backfill = ~$90 total, so a $50/day cap with $200 monthly ceiling is conservative
- [ ] **Configure email alerts** on the spend cap at 50% / 80% / 100% thresholds
- [ ] **Verify the production API key** matches what's in Railway's `ANTHROPIC_API_KEY` env var (so the cap actually applies to the right key)

Decision #10's gap means this is the only enforcement layer that will catch a v3 runaway until task #54 lands.

### Known gap (recorded for FINAL-3 awareness)

`ai_runs` rows for v3-only batches will have `cost_usd = 0.0` and `usage = NULL`. **Don't be alarmed** — money is being spent, it's just not being recorded in this column. Look at the Anthropic console for actual spend during the first 24h post-flip.

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
- **#56** — `calibration_report` SQL bug. After #55 unmasked it (KeyError was hiding it before), `QUERY_A_DIVERGENCE` in `src/docket/ai/calibration.py:124` fails with `psycopg2.errors.UndefinedColumn: column ai.updated_at does not exist` (HINT: "Perhaps you meant `m.updated_at`"). Task has been crashing every 11:00 CDT — daily diagnostic only, no production impact. Fix: trace the alias in the query, switch to the right column, add a test that exercises the query against a real cursor (the existing `test_run_calibration_queries_*` tests use a mock cursor so they didn't catch this). Discovered 2026-05-11.
- **#57 (BLOCKED FINAL-3, FIXED)** — v3 `ai_items` hung deterministically after 2 successful Anthropic API calls. Observed 2026-05-11 during the first FINAL-3 attempt: flag flipped at 19:11 UTC, worker restarted clean, `--run-once ai_items` made 2 successful POST calls to `api.anthropic.com/v1/messages` at 19:13:09 and 19:13:11, then blocked indefinitely. Process state at +15 min: alive, S (sleeping), RSS 218 MB (cap is 954 MB so no OOM), single thread, 0.94 CPU-sec total. Blocked in syscall=`7` (`poll()`) with timeout=`-1` (infinite) on 1 fd. 4 sockets open (2 DB, 2 Anthropic). `ai_runs.id=13` row created at 19:13:08 with `finished_at=NULL`, `rows_processed=0`. Zero `agenda_items` had v3 outputs and zero `agenda_item_badges` inserted. No Anthropic SDK retry log emitted. SIGKILL'd by container restart on rollback. Rolled back to `IMPACT_FIRST_ENABLED=false` at 2026-05-11 19:35 UTC; no data corruption because v3 wrote nothing.

  **Root cause:** self-deadlock between two connections in the worker process. `worker._process_items_v3` opens **conn A**, claims rows via `claim_items_v3_sql()` → `SELECT … FOR UPDATE OF ai SKIP LOCKED` (row locks held on conn A), then calls `pipeline.process_item(item)`. The pipeline opened a **separate** connection via `db()` for Phase C's `UPDATE agenda_items` — that second connection blocked forever on conn A's row lock. PostgreSQL couldn't detect this because there's no cycle in the wait graph (conn A wasn't waiting on anything, just holding the lock). Hypotheses (a) and (c) ruled out — Anthropic SDK uses its 10-min default timeout (not `None`); pipeline is fully synchronous (no async). Hypothesis (b) was correct in principle but the conflicting connection was the worker's own outer conn, not the daemon's idle conn. Tests didn't catch it because `tests/integration/test_pipeline_e2e.py` calls `pipeline.process_item` directly without ever holding a `FOR UPDATE` lock from a separate connection. v2 doesn't have this bug because `_process_items` threads the worker's `conn` into `write_item_result(conn, …)` — same connection throughout.

  **Fix:** thread the worker's `conn` through `process_item` / `_rerun_from_stage2` so Phase A / 2.5 / C writes all use the same connection that holds the `FOR UPDATE` lock. Admin paths in `services/conflict_resolution.py` continue to pass no conn and get the fresh-`db()` fallback (preserving the `expected_status` concurrency-guard rollback semantics). Regression test `test_process_item_uses_caller_conn_to_avoid_self_deadlock` pins the contract by patching `pipeline.db` to a forbidder that raises if the pipeline opens a new connection while a conn was provided. Suite: 1309 passed + 4 xfailed.
