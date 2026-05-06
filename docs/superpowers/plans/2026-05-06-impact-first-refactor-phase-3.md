# Impact-First Refactor — Phase 3 Implementation Plan (Backfill Execution)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the actual backfill — process every `pending` agenda item from Wave 0 through the new pipeline (Stages 0a/0b/1/2/2.5 + reconcile + badges). Three sequential LLM waves with a sync burst at the front for live calibration. Output: every substantive item in the database has v3 outputs (`headline`, `why_it_matters`, `extracted_facts`, badges); citizens see Smart Brevity Cards on every meeting from 2017 to present.

**Architecture:** Mostly operational, not code-heavy. The driver, Batches API wrapper, AdaptiveWorkerPool, and per-item pipeline orchestrator all shipped in Phase 2. Phase 3 = run them in sequence, monitor for drift, calibrate prompts if needed, and flip the citizen-facing UI flag. Includes one decision point after Wave 1 (bump `ITEM_PROMPT_VERSION` and re-run, or proceed to Wave 2).

**Tech Stack:** No new code. Anthropic Batches API + AdaptiveWorkerPool already in place. Daily monitoring via `/admin/calibration` dashboard.

**Spec:** `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md` — sections 7.1, 7.2, 7.4, 7.5, 7.6, 7.7, 8.3 (Phase 3).

**Estimated effort:** ~3 engineer-days of active work spread across **7-14 calendar days** (most of the elapsed time is Anthropic Batches API processing, not human work).

**Depends on:** Phase 2 plan complete and shipped to Railway with `IMPACT_FIRST_ENABLED=true` for the worker. `SMART_BREVITY_UI` should still be `false` (cit-facing flip happens mid-phase).

---

## File Structure

**No new code files.** Phase 3 is operations on top of Phase 2's machinery.

**Updates (operational artifacts only):**
- `docs/runbooks/backfill.md` — operator runbook (already created in Phase 2)
- Healthchecks dashboard — new heartbeats may need configuring (`HEALTHCHECK_BACKFILL_DRIVER_UUID`, `HEALTHCHECK_BATCH_POLLER_UUID`)
- Railway env vars — flip `SMART_BREVITY_UI=true` mid-phase

---

## Pre-Task: Sanity Check

- [ ] **Step 0.1: Verify Phase 2 shipped clean**

```bash
cd ~/docket-pub
git log --oneline | head -5
```

Expected: most recent commits include the Phase 2 FINAL tag.

- [ ] **Step 0.2: Verify worker is running v3 pipeline on new items**

```bash
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT COUNT(*) FILTER (WHERE ai_rewrite_version = 3) AS v3_count,
       COUNT(*) FILTER (WHERE ai_rewrite_version IS NULL) AS no_version,
       MAX(updated_at) AS most_recent_update
FROM agenda_items
WHERE updated_at > NOW() - INTERVAL '3 days';
"
```
Expected: nonzero `v3_count`. The live nightly worker has been processing new items via the v3 pipeline since Phase 2 ship.

- [ ] **Step 0.3: Verify SMART_BREVITY_UI is OFF**

```bash
railway variables --service docket-web | grep SMART_BREVITY
```
Expected: `SMART_BREVITY_UI=false` (or not set). Citizens should still see v2 UI at this point.

- [ ] **Step 0.4: Note the starting `pending` count from Wave 0**

```bash
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT COUNT(*) AS pending_after_wave_0
FROM agenda_items
WHERE processing_status = 'pending';
"
```

Record this number — it's the input to all subsequent cost projections. (Likely 40-50K items based on spec §7.1 estimates.)

- [ ] **Step 0.5: SDK calibration check (decision #94)**

Verify `anthropic.Anthropic` is being instantiated with `max_retries=0` so 429 errors bubble up to `AdaptiveWorkerPool` instead of being silently retried by the SDK.

```bash
railway run venv/bin/python -c "
from docket.ai.extraction import anthropic_client
print('extraction max_retries:', anthropic_client.max_retries)
from docket.ai.rewrite import anthropic_client as rw
print('rewrite max_retries:', rw.max_retries)
"
```
Expected: both report `0`. If either reports a nonzero value, **halt and fix Phase 2** before continuing — the AdaptiveWorkerPool will be blind to rate-limit signals during the backfill.

- [ ] **Step 0.6: Index verification (decision #92)**

Confirm the composite index on `agenda_item_badges` is live. Without it, category landing pages WILL slow under backfill load.

```bash
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'agenda_item_badges'
  AND indexname = 'idx_agenda_item_badges_city_slug_conf';
"
```
Expected: one row showing the index DDL with `(city_id, badge_slug, confidence)`. If missing, Phase 1 didn't ship correctly — investigate before proceeding.

- [ ] **Step 0.7: Cache verification (decision #91)**

Confirm the DB-backed `ai_response_cache` table exists and is being used. Without it, every Wave 0.5 / Wave 1+ call goes uncached — duplicate API spend during retries, slower backfill resume after restarts.

```bash
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT
  COUNT(*) AS total_cached,
  COUNT(*) FILTER (WHERE accessed_at > NOW() - INTERVAL '24 hours') AS used_today
FROM ai_response_cache;
"
```
Expected: `total_cached` is nonzero (the live `ai_items` task has been hitting it since Phase 2 deploy). If 0, the cache integration didn't land — investigate before stressing it with the backfill.

- [ ] **Step 0.8: Markdown-strip helper verification (decision #94b)**

Sanity-check that `_strip_markdown_fences` is wired up in both extraction and rewrite paths.

```bash
railway run venv/bin/python -c "
from docket.ai.extraction import _strip_markdown_fences
print(_strip_markdown_fences('\`\`\`json\n{\"x\": 1}\n\`\`\`') == '{\"x\": 1}')
"
```
Expected: `True`. If the helper is missing or the import fails, Wave 0.5 can hit avoidable JSONDecodeErrors when Haiku decides to wrap output in markdown.

---

## Task 1: Wave 0.5 — Live Calibration Burst

**Context:** Wave 0.5 (decision #88) is a synchronous-API burst on items where `meeting_date >= DATE_TRUNC('month', CURRENT_DATE)`. Trades higher per-item cost (~$0.005/item sync) for ~4-hour turnaround instead of 1-2 days for Batches API. Goal: have v3 outputs on the most recent month within hours so spot-checks happen on familiar content.

- [ ] **Step 1.1: Verify the wave's eligible item count and projected cost**

```bash
railway run venv/bin/python -m docket.ai.cli --wave 0.5 --dry-run
```

Expected output:
```
Wave 0.5 dry run:
  Eligible items: ~500-1500
  Projected cost: ~$3-8
  Method: synchronous (max_retries=0, AdaptiveWorkerPool)
  Backfill session ID: 01918f...
```

If the count is way outside the ~500-1500 range, investigate before proceeding.

- [ ] **Step 1.2: Run Wave 0.5**

```bash
railway run venv/bin/python -m docket.ai.cli --wave 0.5
```

This kicks off the synchronous burst. Should complete in ~1-4 hours. The CLI will tail progress logs. Watch for:
- Rate-limit storms (AdaptiveWorkerPool will scale workers down)
- Cross-stage conflicts (should be <1%)
- Failed-permanent items (should be <2%)

Walking away is fine — but check back periodically via the Railway logs.

- [ ] **Step 1.3: Verify Wave 0.5 completion**

```bash
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT processing_status, COUNT(*) AS n
FROM agenda_items ai
JOIN meetings m ON m.id = ai.meeting_id
WHERE m.meeting_date >= DATE_TRUNC('month', CURRENT_DATE)
GROUP BY processing_status
ORDER BY processing_status;
"
```

Expected:
- `completed`: ~95%+ of the wave
- `cross_stage_conflict`: <1%
- `failed_retry` or `failed_permanent`: <2%

If failure rate >5%, halt and investigate before Wave 1.

---

## Task 2: Spot-Check Wave 0.5 Outputs

**Goal:** Read 20-30 random Wave 0.5 outputs and verify the headlines / why_it_matters / badges are clean. Catch prompt regressions BEFORE committing the bigger Wave 1.

- [ ] **Step 2.1: Pull 20 random substantive items from Wave 0.5**

```bash
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT ai.id, ai.title, ai.headline, ai.why_it_matters,
       ai.significance_score, ai.consent_placement_score,
       ai.extracted_facts->>'action_type' AS action_type,
       ai.extracted_facts->>'counterparty' AS counterparty
FROM agenda_items ai
JOIN meetings m ON m.id = ai.meeting_id
WHERE m.meeting_date >= DATE_TRUNC('month', CURRENT_DATE)
  AND ai.processing_status = 'completed'
  AND ai.headline IS NOT NULL
ORDER BY RANDOM()
LIMIT 20;
"
```

Read each row. Check against the quality bar in spec §3.1:
- Headlines are resident-first, ≤60 chars, no banned legalese
- why_it_matters tells a citizen the practical consequence
- Action_type matches what the title actually does
- Significance score isn't obviously wrong (e.g., a $5M item shouldn't be sig=2)

- [ ] **Step 2.2: Browse the calibration dashboard**

Visit `https://docket.pub/admin/calibration` (admin login required). Check:
- "Under-scoring Impact" panel — any action_type with >20% sig boost rate?
- "Over-scoring Consent" panel — any with >20% consent reduction?
- "Top False Positives" — any badges admins are removing?
- Per-item divergence — any items with sig delta > 3?

If any panel surfaces persistent issues for a SPECIFIC action_type, that's a prompt-tuning signal (proceed to Task 3 conditional).

- [ ] **Step 2.3: Drain the cross-stage conflict queue (zero gate before Wave 1)**

Visit `/admin/review/conflicts`. **Resolve every standing item** via the appropriate action (Accept Stage 1, Accept Stage 2, Re-prompt, Edit Stage 1). Wave 0.5 is small enough that a few minutes of manual review is doable.

**Hard gate:** do NOT proceed to Wave 1 (Task 4) until the conflict queue is empty.

```bash
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT COUNT(*) AS open_conflicts
FROM agenda_items
WHERE processing_status = 'cross_stage_conflict';
"
```
Expected: `0`. Wave 1 ships ~6K more items; you don't want to mix unresolved Wave 0.5 conflicts in with fresh Wave 1 noise during diagnostic work.

---

## Task 3: Decision Point — Bump Prompt Version?

**This is the most important checkpoint in the whole backfill.** Wave 1 is going to process ~6K items. If the prompt has a systematic flaw, you want to catch it now (and re-run the small Wave 0.5 + the 6K Wave 1) rather than discover it after Waves 2 and 3 commit ~50K items to a flawed prompt.

- [ ] **Step 3.1: Decide based on Task 2 evidence**

Bump `ITEM_PROMPT_VERSION` (in `src/docket/ai/extraction.py` or `rewrite.py`) and redeploy if ANY of:
- Spot-checks revealed multiple items with city-first/legalese/jargon-laden headlines
- A specific action_type shows >25% sig boost rate (prompt is consistently underweighting that category)
- Cross-stage conflict rate exceeds 2% in Wave 0.5
- Banned-words list is consistently violated (rare but possible if Haiku ignored the prompt)

Otherwise, proceed to Task 4.

- [ ] **Step 3.2: If bumping — make the prompt fix in code**

Edit `src/docket/ai/rewrite.py` or `extraction.py`:
- Bump the version constant: `ITEM_REWRITE_PROMPT_VERSION = 4` (or whichever)
- Adjust the system prompt to address the specific issue (e.g., add an example, tighten a rule, add a banned phrase)
- Commit:

```bash
git checkout -b fix/item-prompt-v4
# ... edit rewrite.py ...
git commit -am "fix(ai): tighten item prompt v3→v4 for [specific issue]"
git push -u origin fix/item-prompt-v4
railway up --service worker --detach
```

- [ ] **Step 3.3: Re-run Wave 0.5 with the new prompt**

```bash
railway run venv/bin/python -m docket.ai.cli --wave 0.5 --reprocess
```

`--reprocess` flag tells the driver to re-process items where `ai_rewrite_version < CURRENT_VERSION`. Cost: ~$8 again. Spot-check (Task 2) again.

- [ ] **Step 3.4: Iterate until satisfactory**

Repeat Tasks 2 + 3 until Wave 0.5 outputs pass spot-check. Don't proceed to Wave 1 until you're confident.

---

## Task 4: Submit Wave 1 (2026 Items)

**Context:** Wave 1 = remaining 2026 `pending` items not already processed in Wave 0.5. ~6K items via Anthropic Batches API. Cost ~$13 (50% Batches discount). Calendar time: 1-2 days for the Batches API to process.

- [ ] **Step 4.1: Verify the Wave 1 working set**

```bash
railway run venv/bin/python -m docket.ai.cli --wave 1 --dry-run
```

Expected:
```
Wave 1 dry run:
  Eligible items: ~5500-6500 (2026 items still pending after Wave 0.5)
  Projected cost: ~$13 via Batches API (~$26 sync alternative)
  Method: Anthropic Batches API (24h SLA)
  Backfill session ID: 019190...
```

- [ ] **Step 4.2: Submit Wave 1**

```bash
railway run venv/bin/python -m docket.ai.cli --wave 1 --submit
```

This creates `ai_batches` rows and submits to Anthropic. Returns the session_id and batch IDs.

Record the session_id — needed for rollback if something goes wrong.

- [ ] **Step 4.3: Verify the batches were accepted by Anthropic**

```bash
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT id, anthropic_batch_id, stage, item_count, status, submitted_at
FROM ai_batches
WHERE wave = '1'
ORDER BY submitted_at DESC;
"
```

Expected: 2 rows (one for `stage1`, one for `stage2`), both `status='submitted'` or `'in_progress'`.

---

## Task 5: Wait for Wave 1 (1-2 calendar days)

The Batches API has a 24-hour SLA. Typical latency is 1-4 hours, occasionally up to 24h. The polling task `backfill_batch_driver` runs every 30 minutes and pulls results once each batch is `ended`.

- [ ] **Step 5.1: Daily ops checks (morning + evening)**

```bash
# Are batches still processing?
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT wave, stage, status, item_count,
       AGE(NOW(), submitted_at) AS elapsed
FROM ai_batches
WHERE status NOT IN ('ended', 'failed', 'expired')
ORDER BY submitted_at DESC;
"

# Are completion percentages climbing?
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT m.meeting_date::date AS date,
       COUNT(*) AS total,
       COUNT(*) FILTER (WHERE ai.processing_status = 'completed') AS done,
       ROUND(100.0 * COUNT(*) FILTER (WHERE ai.processing_status = 'completed') / NULLIF(COUNT(*), 0), 1) AS pct
FROM agenda_items ai
JOIN meetings m ON m.id = ai.meeting_id
WHERE m.meeting_date >= '2026-01-01'
GROUP BY date
ORDER BY date DESC
LIMIT 10;
"
```

- [ ] **Step 5.2: Watch for batch failures or stuck batches**

If any batch shows `status='failed'` or `'expired'`, OR if any batch is `'in_progress'` for >36 hours:

```bash
railway run venv/bin/python -m docket.ai.cli --batch-status <anthropic_batch_id>
```

Anthropic's API will explain. Common failures: rate limit / billing issue / malformed request. Fix root cause and resubmit (see runbook).

- [ ] **Step 5.3: Resolve any cross-stage conflicts that surface**

Visit `/admin/review/conflicts`. As Wave 1 lands, items will appear here. Resolve them (target: zero standing items at all times).

---

## Task 6: Wave 1 Complete — Final Verification

- [ ] **Step 6.1: Verify all Wave 1 items processed**

```bash
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT processing_status, COUNT(*) AS n
FROM agenda_items ai
JOIN meetings m ON m.id = ai.meeting_id
WHERE m.meeting_date >= '2026-01-01'
GROUP BY processing_status
ORDER BY processing_status;
"
```

Expected after Wave 1:
- `completed`: ~85-90%
- `procedural_skipped`: ~10-15% (from Wave 0)
- `data_quality_skipped`: ~1-3% (from Wave 0)
- `failed_retry` / `failed_permanent` / `cross_stage_conflict`: <2% combined

If `failed_*` exceeds 5% of the wave, **halt** before Wave 2 and investigate.

- [ ] **Step 6.2: Spot-check 20 more Wave 1 items**

Same query as Task 2.1, but scoped to Wave 1's items (any 2026 item with `ai_rewrite_version=3`). Read 20 random rows. Confirm the prompt is producing solid output across the broader 2026 dataset (Wave 0.5 was just the current month — Wave 1 spans all of 2026).

- [ ] **Step 6.3: Calibration dashboard check**

Visit `/admin/calibration`. Look at:
- "Under-scoring Impact" panel — should still be <20% per action_type
- "Baseline drift" — significance averages per action_type stable week-over-week
- "Top False Positives" — should be empty or near-empty

---

## Task 7: Flip SMART_BREVITY_UI=true

**Citizens see v3 cards on 2026 meetings.** Older meetings still render v2-fallback cards (chip says "summary updating"). Decision #22 progressive switchover.

- [ ] **Step 7.1: Verify worker is fully on v3 for new items + Wave 1 covers recent meetings**

```bash
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT
  COUNT(*) FILTER (WHERE ai_rewrite_version = 3 AND m.meeting_date >= '2026-01-01') AS v3_2026,
  COUNT(*) FILTER (WHERE m.meeting_date >= '2026-01-01') AS total_2026,
  COUNT(*) FILTER (WHERE ai_rewrite_version IS NOT NULL OR processing_status IN ('procedural_skipped', 'data_quality_skipped')) AS classified
FROM agenda_items ai
JOIN meetings m ON m.id = ai.meeting_id;
"
```

Expected: `v3_2026 / total_2026` is ≥85% (the rest are skipped/failed).

- [ ] **Step 7.2: Flip the flag**

```bash
railway variables --service docket-web --set SMART_BREVITY_UI=true
```

Railway will redeploy `docket-web` automatically with the new env var. Wait for the redeploy to land (~1-2 minutes).

- [ ] **Step 7.3: Smoke-test the live site**

Visit `https://docket.pub/al/birmingham/` and click into a recent meeting. Verify:
- Items render as Smart Brevity Cards (headline + why_it_matters + facts strip + badges)
- Older items render the v2-fallback variant with "summary updating" chip
- No broken layouts, no 500 errors
- Mobile viewport works (test in browser dev tools at 375px width — verify the carousel)

- [ ] **Step 7.4: Watch logs for 30 minutes**

```bash
railway logs --service docket-web --follow
```

Look for unexpected errors. If anything looks off, immediately set `SMART_BREVITY_UI=false` and redeploy to roll back to v2 UI. Investigate before re-flipping.

---

## Task 8: Submit Wave 2 (2021-2025 Items)

**Context:** ~28K items via Batches API. Cost ~$63. Calendar: 4-7 days.

- [ ] **Step 8.1: Dry-run + submit**

```bash
railway run venv/bin/python -m docket.ai.cli --wave 2 --dry-run
# Verify count and cost
railway run venv/bin/python -m docket.ai.cli --wave 2 --submit
```

- [ ] **Step 8.2: Daily monitoring (4-7 days)**

Same checks as Task 5.1 + 5.3, scoped to 2021-2025 dates. Plus: as 2025 → 2024 → 2023 etc. items land on Railway, the citizen-facing v3 UI will progressively cover more of the timeline. The "summary updating" chip retreats.

- [ ] **Step 8.3: Monitor citizen-facing UI for any v3-rendering regressions**

As more items get v3 outputs, more cards switch from v2-fallback to full Smart Brevity. If any rendering regression surfaces (e.g., a specific item's `extracted_facts` JSONB has a shape that breaks the template), it'll show up now. Fix forward via a small template patch + commit.

- [ ] **Step 8.4: Wave 2 complete — verify**

Same query shape as Task 6.1, scoped to `meeting_date BETWEEN '2021-01-01' AND '2025-12-31'`. Same 5% failure-rate halt rule.

---

## Task 9: Submit Wave 3 (2017-2020 Items)

**Context:** ~16K items via Batches API. Cost ~$36. Calendar: 2-4 days.

- [ ] **Step 9.1: Dry-run + submit**

```bash
railway run venv/bin/python -m docket.ai.cli --wave 3 --dry-run
railway run venv/bin/python -m docket.ai.cli --wave 3 --submit
```

- [ ] **Step 9.2: Daily monitoring (2-4 days)**

Same drill. **Watch for higher `data_quality_skipped` rates** — older PDFs from 2017-2020 are more likely to have OCR issues. The Big Fish Override (decision #86) catches the most important ones; the rest go to the OCR queue.

- [ ] **Step 9.3: Wave 3 complete — verify**

```bash
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT processing_status, COUNT(*) AS n
FROM agenda_items
GROUP BY processing_status
ORDER BY processing_status;
"
```

Expected (across the entire archive):
- `completed`: ~85-90% of the original 75K
- `procedural_skipped`: ~10-15%
- `data_quality_skipped`: ~3-5%
- `failed_*` / `cross_stage_conflict`: <1% combined

---

## Task 10: Final Verification + Tag

- [ ] **Step 10.1: Verify the v3 ai_rewrite_version is uniform**

```bash
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT ai_rewrite_version, COUNT(*) AS n
FROM agenda_items
WHERE processing_status = 'completed'
GROUP BY ai_rewrite_version
ORDER BY ai_rewrite_version NULLS LAST;
"
```

Expected: virtually all `completed` items at `ai_rewrite_version = 3` (or whatever the current version landed at after any Task 3 prompt bumps). A small number of legacy items at `ai_rewrite_version IS NULL` is acceptable IF they're the procedural_skipped/data_quality_skipped paths.

- [ ] **Step 10.2: Verify search consistency**

Visit `https://docket.pub` and search for known terms (e.g., "Flock", "settlement", "blight"). Verify results return cleanly across the entire timeline (2017-2026). The unified `search_vector` (decision #83) should make this transparent regardless of v2 vs v3 state.

- [ ] **Step 10.3: Verify category landing pages have meaningful data**

Visit each BHM policy badge:
- `/al/birmingham/blight_accountability`
- `/al/birmingham/housing_stability`
- `/al/birmingham/property_recovery`
- `/al/birmingham/public_safety_tech_privacy`

Each should show 5-50+ items spanning multiple years. The volume timeline should show recognizable activity patterns (e.g., spikes during budget season, bands per mayor).

- [ ] **Step 10.4: Refresh materialized view one more time**

```bash
railway run venv/bin/python -c "
from docket.db import db_cursor
with db_cursor() as cur:
    cur.execute('REFRESH MATERIALIZED VIEW CONCURRENTLY mv_badge_volume_monthly')
print('done')
"
```

(The `process_badges` cron task already does this nightly, but a manual refresh post-Wave 3 ensures the SVG timelines reflect the full backfill.)

- [ ] **Step 10.5: Resolve any remaining cross-stage conflicts**

Visit `/admin/review/conflicts`. After Wave 3, the queue should be small (typically <50 items across 75K). Work through them.

- [ ] **Step 10.6: Tag the Phase 3 release**

```bash
git tag refactor-impact-first-phase-3-shipped
git push origin refactor-impact-first-phase-3-shipped
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Wave 0.5 (decision #88) — Task 1
- [x] Wave 1, 2, 3 (decision #12) — Tasks 4, 8, 9
- [x] Per-wave failure-rate threshold (decision #79 / spec §7.5) — Tasks 6.1, 8.4, 9.3
- [x] Calibration checkpoints (decisions #27, #49) — Tasks 2.2, 6.3
- [x] Prompt-version bump path (spec §7.8) — Task 3
- [x] Progressive switchover to v3 UI (decision #22) — Task 7
- [x] Cross-stage conflict resolution (decision #93) — Tasks 2.3, 5.3, 10.5
- [x] Materialized view refresh — Task 10.4

**Placeholder scan:**
- [x] No "TBD" / "TODO" — all tasks reference concrete commands and queries
- [x] All file paths and Railway service names exact
- [x] All SQL queries copy-pastable

**Type consistency:**
- [x] `--wave 0.5` / `--wave 1` / `--wave 2` / `--wave 3` flags used consistently (matches the CLI from Phase 2 Task H3)
- [x] `processing_status` enum values match spec
- [x] Date ranges (2021-01-01, 2026-01-01) consistent across queries

**Scope check:**
- [x] Phase 3 is execution-only — no new code (the only "code change" is a prompt-version bump if Task 3 fires)
- [x] Phase 3 ends with all completed items at v3 outputs and citizens seeing v3 UI everywhere

---

## What ships at the end of Phase 3

- Every substantive item in the 8.5-year archive has v3 outputs (`headline`, `why_it_matters`, `extracted_facts`)
- Every item has a `processing_status` that's either `completed`, `procedural_skipped`, `data_quality_skipped`, or `failed_permanent`
- Process badges populated for all completed items (7 deterministic rules + nightly recompute keeps them current)
- Policy badges populated for Birmingham (4 active templates) on items that match
- Citizens see Smart Brevity Cards on every meeting, regardless of year
- Search returns relevant results across the timeline
- Category landing pages render meaningful volume timelines
- Total spend: ~$120-150 (within the $144 Batches-API budget projection)

## What does NOT ship in Phase 3

- Migration 014 (legacy `summary` column drop) — Phase 4
- v2-fallback variant template removal — Phase 4
- Permanent retirement of dead code paths — Phase 4

---

## Rollback by failure mode (Phase-3-specific)

| Failure | Detected via | Action |
|---|---|---|
| Wave produces bad outputs (prompt regression) | Calibration alerts spike, spot-checks fail | Bump `ITEM_PROMPT_VERSION`. `UPDATE … WHERE backfill_session_id=:uuid` to clear the bad outputs. Re-run the wave with the new version. |
| Citizens hit broken UI after `SMART_BREVITY_UI=true` | Sentry / user reports | Set `SMART_BREVITY_UI=false`; redeploy. v2 UI returns immediately. Investigate without time pressure. |
| Anthropic Batches API rate-limited at scale | `ai_batches.status='failed'` | Adaptive concurrency self-corrects; if persistent, halt the driver via `railway run venv/bin/python -m docket.ai.cli --backfill-pause`. Resume next day. |
| Cross-stage-conflict rate climbs >2% | Calibration query | Bump prompt version (see Task 3); re-run the affected wave. |
| Cost overrun mid-wave | Daily budget gate (`AI_DAILY_BUDGET_USD`) breach | Soft cap auto-pauses new submissions. Increase the cap with `--force-budget` if urgent, otherwise resume next day. |
