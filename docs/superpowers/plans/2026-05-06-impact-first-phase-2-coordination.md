# Phase 2 Multi-Agent Coordination

> **For Claude Code multi-agent execution.** This doc supplements `2026-05-06-impact-first-refactor-phase-2.md` with track decomposition, branch strategy, integration cadence, and per-track briefings that double as system-prompt extensions for parallel Claude Code sessions.

**Purpose:** Phase 2 covers ~23 engineer-days across 8 sections (A-H). Worked sequentially, calendar time is ~6 weeks. Worked in 3 parallel tracks, calendar time drops to ~10-12 days. This doc enables the parallel pattern.

---

## Execution patterns by phase

| Phase | Pattern | Why |
|---|---|---|
| **Phase 1** (~3 days) | Single agent, sequential dispatch via `superpowers:subagent-driven-development` | Tasks build on each other; parallelization yields no time savings |
| **Phase 2** (~23 days serial / ~10-12 days parallel) | **Multi-agent, 3 tracks** | Largest phase; section dependencies allow real parallelization |
| **Phase 3** (~3 days active over 7-14 calendar days) | Single human operator + CLI | Wave execution and calibration require one set of eyes; multi-agent causes chaos |
| **Phase 4** (~0.5 days) | Single agent, sequential | Tiny scope; one engineer, half a day |

This doc focuses on Phase 2's three-track pattern.

---

## Track decomposition

### Track 1 — Backend Pipeline (~10-12 days)

**Owner: one Claude Code session** in worktree `pf2-track-1-pipeline/`.

**Goal:** Land the AI pipeline modules (Stages 0/1/2/2.5 + reconcile), excluding the integration orchestrator. Stop short of `pipeline.py` (Task B5) because it imports from Track 2's outputs.

**Owned files (creates):**
- `src/docket/ai/extraction_schema.py`
- `src/docket/ai/extraction.py`
- `src/docket/ai/cache.py`
- `src/docket/ai/rewrite_schema.py`
- `src/docket/ai/rewrite.py`
- `src/docket/ai/floors.py`
- `src/docket/ai/reconcile.py`
- `src/docket/ai/concurrency.py`
- `src/docket/ai/batches.py`
- `src/docket/ai/backfill_driver.py`
- `tests/unit/test_extraction*.py`, `test_rewrite*.py`, `test_floors.py`, `test_reconcile.py`, `test_concurrency.py`, `test_batches.py`, `test_ai_cache.py`

**Owned modifications:**
- `src/docket/ai/cli.py` — add `--wave 0.5/1/2/3` flags
- `requirements.txt` — verify `anthropic`, `pydantic` (probably no change needed)

**Tasks (in order):**
A1 → A2 → A3 → A4 → B1 → B2 → B3 → B4 → H1 → H2 → H3

**Out of scope for Track 1:**
- B5 (`pipeline.py` orchestrator) — handled at convergence
- Cron task wiring (`worker/tasks.py` modifications) — Track 2
- Frontend, admin, calibration UI — Track 3

**Track 1 estimated effort:** ~10-12 engineer-days. The longest critical path.

---

### Track 2 — Badges + Worker Tasks (~5 days)

**Owner: one Claude Code session** in worktree `pf2-track-2-badges/`.

**Goal:** Process and policy badge logic + cron task wiring + audit log + calibration service.

**Owned files (creates):**
- `src/docket/ai/badges_process.py`
- `src/docket/ai/badges_policy.py`
- `src/docket/services/badges.py`
- `src/docket/services/calibration.py`
- `tests/unit/test_badges_process.py`, `test_badges_policy.py`
- `tests/integration/test_badges_audit.py`

**Owned modifications:**
- `src/docket/worker/tasks.py` — add `process_badges_task` and `calibration_report_task` functions (Track 1 will modify the existing `ai_items_task` body separately at convergence — see contention notes below)
- `src/docket/worker/scheduler.py` — register the two new cron schedules
- `docs/runbooks/cron-worker.md` — document new env vars (`HEALTHCHECK_PROCESS_BADGES_UUID`, `HEALTHCHECK_CALIBRATION_REPORT_UUID`)

**Tasks (in order):**
C1 → C2 → D1 → D2 → H4

**Out of scope for Track 2:**
- Stage 1/2 pipeline modules — Track 1
- Frontend, admin views — Track 3
- Pipeline orchestrator integration — convergence

**Track 2 estimated effort:** ~5 engineer-days. Shortest track. Engineer can pick up frontend work (Track 3 spillover) after finishing.

---

### Track 3 — Frontend + Admin (~9-11 days)

**Owner: one Claude Code session** in worktree `pf2-track-3-frontend/`.

**Goal:** All citizen-facing UI (Smart Brevity Card variants, category landing pages, mobile carousel, accessibility), all admin views (calibration, OCR queue, errors, audit log, conflict resolution), search service updates.

**Owned files (creates):**
- All `src/docket/web/templates/partials/card_*.html` (6 variants)
- `src/docket/web/templates/partials/smart_brevity_card.html` (dispatcher)
- `src/docket/web/templates/partials/badge_chip.html`, `engagement_strip.html`, `source_anchor_button.html`, `dollar_tier.html`, `volume_timeline.html`
- `src/docket/web/templates/category_landing.html`, `data_debt.html`
- `src/docket/web/templates/admin/calibration.html`, `data_debt.html`, `errors.html`, `badges_audit.html`, `review_conflicts.html`, `_conflict_resolved.html`
- `src/docket/web/templates/rss/data_debt.xml.j2`, `upcoming_hearings.xml.j2`
- `src/docket/web/static/css/smart_brevity.css`
- `src/docket/services/conflict_resolution.py`
- `tests/unit/test_card_variants.py`, `test_engagement_strip.py`, `test_volume_timeline.py`, `test_badge_chip_ordering.py`, `test_source_anchor.py`, `test_dollar_tier.py`
- `tests/integration/test_conflict_resolution.py`, `test_list_items_by_badge.py`

**Owned modifications:**
- `src/docket/web/public.py` — add category landing route, public data-debt page, RSS feeds
- `src/docket/web/admin.py` — add 5 admin routes
- `src/docket/web/templates/base.html` — include CSS, badge legend
- `src/docket/web/templates/city.html` — Browse by Priority section
- `src/docket/web/templates/meeting_detail.html` — wire variant dispatcher
- `src/docket/web/filters.py` — `order_badges`, `dollar_tier`, `format_dollars` helpers
- `src/docket/services/query.py` — `list_items_by_badge` with significance gating

**Tasks (in order):**
E1 → E2 → E3 → E4 → E5 → E6 → F1 → F2 → F3 → F4 → F5 → G1 → G2 → G3 → G4

**Out of scope for Track 3:**
- AI pipeline modules — Track 1
- Cron tasks — Track 2 (Track 3 reads from `services/calibration.py` and `services/badges.py` but does not own them)
- Pipeline orchestrator — convergence

**Track 3 estimated effort:** ~9-11 engineer-days. Slightly shorter than Track 1.

---

## Branch strategy

**Use git worktrees for isolation.** Each track gets its own worktree pointing at a feature branch off `feat/impact-first-phase-2`.

```bash
cd ~/docket-pub
git checkout main
git pull origin main
git checkout -b feat/impact-first-phase-2
git push -u origin feat/impact-first-phase-2

# Worktree per track (all share the parent branch)
git worktree add ../docket-pub-pf2-track-1 -b feat/impact-first-phase-2-track-1 feat/impact-first-phase-2
git worktree add ../docket-pub-pf2-track-2 -b feat/impact-first-phase-2-track-2 feat/impact-first-phase-2
git worktree add ../docket-pub-pf2-track-3 -b feat/impact-first-phase-2-track-3 feat/impact-first-phase-2
```

Each worktree is its own filesystem path with its own branch. Three Claude Code sessions can run concurrently against `~/docket-pub-pf2-track-{1,2,3}/` without trampling each other.

**Daily integration:**

```bash
# Each track engineer/agent does this once a day:
cd ~/docket-pub-pf2-track-N
git fetch origin
git rebase origin/feat/impact-first-phase-2     # pull in other tracks' commits
# fix any merge conflicts (rare if file ownership is respected)
git push --force-with-lease origin feat/impact-first-phase-2-track-N

# Then: open PR or push directly to the integration branch
git push origin HEAD:feat/impact-first-phase-2
```

Or simpler: each track pushes directly to `feat/impact-first-phase-2` daily, with frequent pulls.

**Final merge to main:** only after all three tracks complete + B5 convergence + FINAL tasks + smoke test against the integration branch.

---

## Contention points (where tracks touch the same files)

These are the few places where the file-ownership matrix above isn't clean. Mitigations follow.

### Contention 1: `src/docket/worker/tasks.py`

**Tracks involved:** Track 1 (modifies `ai_items_task` to call `process_item()` from new pipeline.py), Track 2 (adds `process_badges_task` and `calibration_report_task` functions).

**Mitigation:** different functions in the same file. Both tracks add to the file via append-only edits — Track 2 appends new task functions; Track 1 modifies the body of the existing `ai_items_task` function. Conflict resolution at daily merge: trivial (different anchor regions).

**Convergence note:** Track 1's `ai_items_task` modification depends on `pipeline.py` existing (B5 convergence), so this specific edit happens at the FINAL phase, not during Track 1's normal work.

### Contention 2: `src/docket/services/query.py`

**Tracks involved:** Track 3 (adds `list_items_by_badge`).

**Mitigation:** only Track 3 modifies. Other tracks may import from it but don't add new functions. No contention in practice.

### Contention 3: `requirements.txt`

**Tracks involved:** Track 1 verifies `anthropic`, `pydantic`. Track 3 may add `flask-caching` for RSS cache (decision #90).

**Mitigation:** Either track edits independently. Final merge resolves trivially (both adds are line additions).

### Contention 4: `src/docket/migrations/runner.py`

**Tracks involved:** None during Phase 2. Phase 4 modifies for Migration 014.

**Mitigation:** N/A — file isn't touched in Phase 2.

### Contention 5: `pipeline.py` (Task B5)

**Tracks involved:** Track 1 owns the file; Track 1's B5 imports from Track 2's `badges_process.py`, `badges_policy.py`, `services/badges.py`.

**Mitigation:** Track 1 stops at B4. After Tracks 2 + 3 land their integration-branch commits, a single agent (could be any track, recommended Track 1) picks up B5 with full visibility into all three tracks' outputs.

This is the **convergence task** — see "Convergence" section below.

---

## Daily cadence

Suggested rhythm for parallel execution:

**Morning (15 min):**
1. Pull `feat/impact-first-phase-2` into your worktree (`git pull origin feat/impact-first-phase-2 --rebase`)
2. Run `pytest tests/` to verify your branch + the latest integration changes still play nicely
3. Skim the previous day's commits from other tracks: `git log feat/impact-first-phase-2 --since="1 day ago" --oneline --not feat/impact-first-phase-2-track-N`

**Throughout the day:**
- Work your assigned tasks in TDD pattern (the Phase 2 plan is bite-sized)
- Commit frequently (per task, per the Phase 2 plan's "commit" steps)
- Push to your track branch frequently

**End of day (15 min):**
1. Run integration tests on your branch (`pytest tests/`)
2. Push to `feat/impact-first-phase-2` (your shared branch)
3. Note in a shared status doc (or chat) what tasks landed today and any new blockers

**Weekly sync (~30 min):**
- Track owners + project lead review the integration branch's CI status
- Identify any cross-track blockers (e.g., "I need Track 2's `compute_policy_badges` signature finalized before I can mock it in tests")
- Adjust task ordering if needed

---

## Convergence: B5 + FINAL tasks

After all three tracks complete their independent work:

### Step 1: B5 Pipeline Orchestrator

A single agent (any track that has bandwidth) picks up Phase 2 Task B5 from `2026-05-06-impact-first-refactor-phase-2.md`. By this point:
- Track 1's outputs (extraction, rewrite, floors, reconcile) are landed
- Track 2's outputs (process badges on-write helper, policy badges matcher, services/badges.py) are landed
- All three tracks' tests are green on the integration branch

`pipeline.py` is implemented to import from all three tracks' modules. Its end-to-end integration test (`tests/integration/test_pipeline_e2e.py`) is the highest-confidence indicator that the merge succeeded.

### Step 2: FINAL-1 — Wire `IMPACT_FIRST_ENABLED` flag

Modify `src/docket/worker/tasks.py:ai_items_task` to dispatch through `pipeline.process_item` when the flag is set. This is the touchpoint between Track 1's pipeline.py and Track 2's `worker/tasks.py` — a small edit, but it's the integration moment.

### Step 3: FINAL-2 — Deploy with flags off

Push the integration branch to Railway. Both flags `IMPACT_FIRST_ENABLED=false` and `SMART_BREVITY_UI=false`. v2 keeps running. Verify no regressions.

### Step 4: FINAL-3 — Flip `IMPACT_FIRST_ENABLED=true` for worker

The first real test of the multi-track integration: live `ai_items` task processes new items via the v3 pipeline. Watch logs for 24 hours.

### Step 5: FINAL-4 — Tag and merge to main

```bash
git checkout main
git merge feat/impact-first-phase-2 --no-ff
git tag refactor-impact-first-phase-2-shipped
git push origin main refactor-impact-first-phase-2-shipped
```

Phase 2 done. Phase 3 (backfill execution) starts.

---

## Per-track agent briefings

Each section below is a self-contained briefing for one Claude Code session. Copy into the new session's first prompt to give that agent everything it needs.

### Briefing for Track 1 — Backend Pipeline

```
You are working on Track 1 of Phase 2 of the docket.pub Impact-First Refactor.

CONTEXT
- Working directory: ~/docket-pub-pf2-track-1
- Branch: feat/impact-first-phase-2-track-1 (forked from feat/impact-first-phase-2)
- Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md
- Plan: docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-2.md
- Coordination: docs/superpowers/plans/2026-05-06-impact-first-phase-2-coordination.md

YOUR TASKS (work in order):
A1 — Pydantic schemas (StructuredFacts, LocationDetail, NextSteps)
A2 — DB-backed AI response cache (decision #91)
A3 — Stage 1 extraction worker with SDK hardening (decision #94)
A4 — Persist extraction outputs
B1 — ItemRewrite Pydantic schema with density check (decision #87)
B2 — Stage 2 v3 worker (item prompt v3, banned words, suggested badges)
B3 — Stage 2.5 score floors (SIGNIFICANCE_FLOORS, CONSENT_PLACEMENT_CEILINGS, SUBJECT_MATTER_FLOORS)
B4 — Reconcile module with auto-retry
H1 — AdaptiveWorkerPool
H2 — Anthropic Batches API wrapper
H3 — Backfill driver (CLI integration for waves 0.5/1/2/3)

DO NOT DO:
- Task B5 (pipeline orchestrator) — that's a convergence task after all 3 tracks ship
- Any worker/tasks.py modifications — Track 2 owns those
- Any frontend, admin, or template work — Track 3 owns those

RULES:
- Use superpowers:subagent-driven-development to dispatch one subagent per task
- Each task follows the TDD pattern in the Phase 2 plan: write failing test → run to confirm fail → implement → run to confirm pass → commit
- Commit per task as the plan specifies
- Push to feat/impact-first-phase-2-track-1 after each task; rebase against feat/impact-first-phase-2 daily
- Daily merge to feat/impact-first-phase-2 at end of work session
- If you encounter a contention point (file owned by another track), STOP and flag it — don't edit other tracks' files

START: invoke superpowers:subagent-driven-development against the Phase 2 plan, scoped to Tasks A1 through H3.
```

### Briefing for Track 2 — Badges + Worker Tasks

```
You are working on Track 2 of Phase 2 of the docket.pub Impact-First Refactor.

CONTEXT
- Working directory: ~/docket-pub-pf2-track-2
- Branch: feat/impact-first-phase-2-track-2 (forked from feat/impact-first-phase-2)
- Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md
- Plan: docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-2.md
- Coordination: docs/superpowers/plans/2026-05-06-impact-first-phase-2-coordination.md

YOUR TASKS (work in order):
C1 — Process badge SQL queries (7 badges; include city_id per decision #92)
C2 — Process_badges nightly cron task with advisory lock + manual badge preservation
D1 — Policy badge matcher (deterministic_policy_match + compute_policy_badges) with regex flag (decision #60)
D2 — Audit log integration (record_badge_action writing to agenda_item_badges_audit)
H4 — calibration_report cron task (4 calibration queries + cache_cleanup call)

DO NOT DO:
- Task B5 (pipeline orchestrator) — that's a convergence task after all 3 tracks ship
- Any AI pipeline modules (extraction, rewrite, floors, reconcile) — Track 1 owns those
- Any frontend, admin, or template work — Track 3 owns those
- Any cli.py modifications for --wave flags — Track 1's H3 owns that

RULES:
- Use superpowers:subagent-driven-development to dispatch one subagent per task
- Each task follows TDD: write failing test → confirm fail → implement → confirm pass → commit
- All process-badge SQL INSERTs MUST include city_id resolved via JOIN to meetings (decision #92)
- worker/tasks.py: only ADD new task functions (process_badges_task, calibration_report_task). Do NOT modify the existing ai_items_task — Track 1 will handle that at convergence.
- Daily rebase + merge to feat/impact-first-phase-2

START: invoke superpowers:subagent-driven-development against the Phase 2 plan, scoped to Tasks C1, C2, D1, D2, H4.
```

### Briefing for Track 3 — Frontend + Admin

```
You are working on Track 3 of Phase 2 of the docket.pub Impact-First Refactor.

CONTEXT
- Working directory: ~/docket-pub-pf2-track-3
- Branch: feat/impact-first-phase-2-track-3 (forked from feat/impact-first-phase-2)
- Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md
- Plan: docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-2.md
- Coordination: docs/superpowers/plans/2026-05-06-impact-first-phase-2-coordination.md

YOUR TASKS (work in order):
E1 — Smart Brevity Card variant dispatcher + 6 variant partials
E2 — Badge chip rendering with Verification Spark (decision #67) + mobile carousel CSS (decision #66)
E3 — Engagement strip with mailto: fallback (decision #77)
E4 — Source-anchor adaptive button (bbox/page/doc/OCR-needed)
E5 — Dollar-tier WCAG 2.1 markup (decision #75)
E6 — SMART_BREVITY_UI feature flag wiring
F1 — list_items_by_badge service with render-time significance gating (decision #61)
F2 — Category landing page route + template
F3 — SVG volume timeline with mayoral overlay + consent baseline split (decision #68)
F4 — Cross-filter HTMX dropdown + Browse by Priority + badge legend
F5 — Public data-debt page + RSS feeds with 60-min cache (decision #90)
G1 — Calibration dashboard
G2 — Admin OCR queue + errors queue (priority-sorted, decision #79)
G3 — Audit log viewer + manual badge HTMX endpoints
G4 — Cross-Stage Conflict Resolution UI (decision #93) — 4 HTMX-powered actions

DO NOT DO:
- Any AI pipeline modules — Track 1 owns those
- Any worker/tasks.py modifications — Track 2 owns those (you may import from services/calibration.py once Track 2 lands it)
- Pipeline orchestrator (B5) — convergence task

RULES:
- Use superpowers:subagent-driven-development to dispatch one subagent per task
- Each task follows TDD where applicable; for templates, snapshot tests acceptable
- list_items_by_badge MUST implement render-time significance gating (NOT matcher-time) — see decision #61 revised
- All policy badge filtering happens at READ time, not WRITE time
- Daily rebase + merge to feat/impact-first-phase-2

NOTABLE DEPENDENCIES:
- Task G1 (calibration dashboard) depends on Track 2's services/calibration.py existing. If you reach G1 before Track 2 lands the file, mock it temporarily and revisit at convergence.
- Task G3 (manual badge endpoints) depends on Track 2's services/badges.py. Same — mock if blocked.

START: invoke superpowers:subagent-driven-development against the Phase 2 plan, scoped to Tasks E1 through G4.
```

---

## Claude Code multi-agent quick start

If you have three terminals available, run one Claude Code session per worktree. Each session reads its track briefing as context and works the assigned tasks.

**Terminal 1 (Track 1 — Backend Pipeline):**

```bash
cd ~/docket-pub-pf2-track-1
claude code
```

Then in the Claude Code prompt:
```
Read /Users/darrellnance/docket-pub/docs/superpowers/plans/2026-05-06-impact-first-phase-2-coordination.md
and execute Track 1's briefing using superpowers:subagent-driven-development.
```

**Terminal 2 (Track 2 — Badges + Worker Tasks):**

```bash
cd ~/docket-pub-pf2-track-2
claude code
```

```
Read /Users/darrellnance/docket-pub/docs/superpowers/plans/2026-05-06-impact-first-phase-2-coordination.md
and execute Track 2's briefing using superpowers:subagent-driven-development.
```

**Terminal 3 (Track 3 — Frontend):**

```bash
cd ~/docket-pub-pf2-track-3
claude code
```

```
Read /Users/darrellnance/docket-pub/docs/superpowers/plans/2026-05-06-impact-first-phase-2-coordination.md
and execute Track 3's briefing using superpowers:subagent-driven-development.
```

Each session works independently. Daily, you (the human coordinator) merge each track's branch into `feat/impact-first-phase-2` and notify each session to rebase.

---

## Solo agent execution (alternative)

If you don't have parallelization budget, run one Claude Code session against the main `feat/impact-first-phase-2` branch and work tasks sequentially per the Phase 2 plan. Calendar time: ~22-23 days. Same end state.

```bash
cd ~/docket-pub
git checkout feat/impact-first-phase-2
claude code
```

```
Use superpowers:subagent-driven-development against
docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-2.md
working tasks A1 through G4 then FINAL-1 through FINAL-4 in order.
```

---

## Phase 1 quick start (single agent)

```bash
cd ~/docket-pub
git checkout main
claude code
```

```
Use superpowers:subagent-driven-development against
docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-1.md
working tasks 1 through 15 in order.
```

Calendar: ~3 days.

---

## Phase 3 — operator-driven (NOT agent-driven)

Phase 3 is wave execution. The plan is a runbook of CLI commands and verification queries. **Do not use Claude Code or subagent-driven for Phase 3.** A human operator runs the commands and watches the output.

The reason: Phase 3's checkpoints are visual + judgment-based (spot-checking 20 random outputs, deciding whether to bump prompt version). An agent could be fooled into proceeding when a human would catch a subtle quality issue. Calendar: ~7-14 days, mostly waiting for Anthropic Batches API.

---

## Phase 4 quick start (single agent)

```bash
cd ~/docket-pub
git checkout main
claude code
```

```
Use superpowers:subagent-driven-development against
docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-4.md
working tasks 1 through 5 in order.
```

Calendar: ~half day.

---

## Risk mitigation

### "What if a track gets ahead of dependencies?"

Tracks shouldn't strictly block each other within Phase 2 since they own disjoint files. But if Track 3 reaches G1 (calibration dashboard) before Track 2 lands `services/calibration.py`, Track 3 has options:

1. **Mock it temporarily** — write `services/calibration.py` as a stub returning empty data, complete the template + route, and revisit at integration when Track 2's real implementation lands
2. **Skip ahead** — work G2/G3/G4 first; come back to G1 once Track 2 is closer

Same applies for Track 3's G3 (manual badge endpoints) needing Track 2's `services/badges.py`.

### "What if a track ships a breaking change?"

Daily integration catches this. If Track 2 changes a function signature that Track 3 depends on, the daily rebase + test run on Track 3's branch will fail. Coordination message goes out, fix is small, no data loss.

### "What if FINAL convergence reveals a bigger integration issue than expected?"

Worst case: B5 doesn't compose the three tracks cleanly because their interfaces drifted. Fix: a 1-2 day "integration sprint" where one engineer reconciles the interfaces. This is unlikely if daily merges run; they'd surface the drift earlier.

### "What if one track is much slower than the others?"

Spillover plan: when Track 2 finishes (likely first, ~5 days), the engineer joins Track 3 to help with the remaining UI work. Track 1 generally can't be helped by spillover labor since it's the longest critical path of dependent work.

---

## Success criteria for Phase 2 coordination

- All three tracks land their assigned tasks with passing tests on the integration branch
- B5 convergence integrates cleanly (one PR, ≤ 1 day of work)
- FINAL-1 through FINAL-4 deploy successfully to Railway
- `IMPACT_FIRST_ENABLED=true` for the worker; live `ai_items` task processes new items via v3 pipeline
- `SMART_BREVITY_UI=false` (citizens still see v2 — the flip is Phase 3)
- All ~250 tests (per the Phase 2 plan's test strategy) pass
- Tag `refactor-impact-first-phase-2-shipped` exists

When all of the above are true, Phase 2 is done and Phase 3 starts.
