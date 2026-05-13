# B5 Backend / Orchestration Review — Opus reviewer #1

**Scope:** `src/docket/ai/pipeline.py`, `tests/integration/test_pipeline_e2e.py` (backend-relevant subset), `tests/live/test_pipeline_live.py`.
**Branch:** `release/impact-first-v3` @ `c7442e1`. Diff range: `3186610..HEAD`.
**Out of scope:** worker.py, conflict_resolution.py, config.py, worker dispatch tests, G4 regression tests (covered by reviewer #2).

---

## Summary

The pipeline orchestrator is well-structured and decision #13 is correctly wired. The two-UPDATE Phase C is in **the same `with db()` block** (same transaction), so the rollback semantics on guard-fire are sound; the inline extraction UPDATE rolls back together with the guarded UPDATE on `PipelineConcurrencyError`, preserving decision #13's all-or-none guarantee even though the inline UPDATE itself has no guard predicate.

All 5 implementer deviations check out against the codebase. Deviations #1 (no `source_type` column) and #2 (avoid `persist_extraction`'s status side-effect) are not just acceptable — they are **necessary for correctness**. Without deviation #2, the admin-path concurrency guard would fire spuriously on every Phase C call because `persist_extraction` flips `processing_status` to `'extracted'` BEFORE the guarded UPDATE checks `processing_status = 'cross_stage_conflict'`.

Findings are weighted to SUGGESTED. The single REQUIRED is a test-coverage gap (not a code defect): the rollback test only asserts the rewrite columns are unchanged, not the inline-UPDATE columns (`extracted_facts`, `ai_extraction_version`). The code is correct; the test does not prove it is correct. Closing this gap is one line of assertions.

### Verdict counts
- REQUIRED: 1
- SUGGESTED: 5
- NICE-TO-HAVE: 4

### Deviation verdicts
1. `source_type` column does not exist — **CORRECT** (plan bug; column doesn't exist in 001 or 013).
2. Inline extraction UPDATE instead of `persist_extraction` — **CORRECT and necessary** (without it, decision #13's guard fires spuriously).
3. G4 test mock paths (reviewer-2 owns primarily) — pipeline-side tests are consistent.
4. Audit payload preservation — reviewer-2's beat.
5. `run_once` lazy AIClient — reviewer-2's beat.

---

## REQUIRED

### REQ-1: `test_rerun_from_stage2_guard_raises_when_status_mismatch` does not assert that the inline extraction UPDATE rolled back

**File:** `tests/integration/test_pipeline_e2e.py:604-632`

The test currently checks:
```python
final = _load_item(iid)
assert final["headline"] is None
assert final["processing_status"] == "pending"
assert _read_badges(iid) == []
```

But the most subtle correctness claim of deviation #2 + decision #13 is that **the inline `UPDATE agenda_items SET extracted_facts = ..., ai_extraction_version = ...` rolls back together with the guarded UPDATE**. The test does not assert this. If a future refactor accidentally split the Phase C transaction (e.g., moved the inline UPDATE into its own `with db()` block, or auto-committed), this test would still pass while the rollback contract silently broke.

**Code correctness is fine** — both UPDATEs share `with db() as conn, conn.cursor() as cur:` (pipeline.py:254), psycopg2 starts an implicit transaction on the first `execute`, the raise propagates out of the `with` block, and `db()` calls `conn.rollback()` (db.py:30-32). The inline UPDATE is rolled back. But the test does not prove it.

**Fix:** add two assertions at the end of the test (and ideally the same on `test_rerun_from_stage2_guard_allows_match` to verify the happy path writes both):

```python
# Inline extraction UPDATE rolled back: extracted_facts / ai_extraction_version
# are still NULL because the WHOLE Phase C transaction was atomic.
with db_cursor() as cur:
    cur.execute(
        "SELECT extracted_facts, ai_extraction_version FROM agenda_items WHERE id = %s",
        (iid,),
    )
    pre_facts = dict(cur.fetchone())
assert pre_facts["extracted_facts"] is None
assert pre_facts["ai_extraction_version"] is None
```

This single addition turns deviation #2's correctness claim from "argued in a code comment" into "verified by a regression test." Given that decision #13 is the most-emphasized invariant of B5 and the implementer explicitly noted it as the reason for deviation #2, this gap should be closed before merge.

---

## SUGGESTED

### SUG-1: Stage 2.5 floors block uses `with db() as conn` purely for the cursor — wasteful but not incorrect

**File:** `src/docket/ai/pipeline.py:219-220`, `:231-234`

```python
with db() as conn, conn.cursor() as cur:
    overrides = apply_score_floors(cur, item, facts, rewrite, item.city_id)
```

`apply_score_floors` (`floors.py:219`) only uses the cursor for the `_resolve_threshold` SELECT against `city_score_floor_overrides`. The `with db()` block opens a new connection per call. The retry path opens ANOTHER one (`pipeline.py:231-234`). That's 2 connection-acquire-and-release cycles in the LLM-call path on the retry branch, plus a third connection for Phase C.

Not incorrect — `db()` properly opens and closes. But for a hot pipeline running 60K backfill items, this is 3 connection acquisitions per item where 1 would do. **Defer to a later optimization pass** (post-Phase 3 if needed); the explicit goal is "no held DB connection across LLM calls," which is correctly preserved here.

Note that **closing the cursor before Stage 2 retry** is the right choice — that's deliberate per the pipeline.py module docstring's Phase B description. Don't conflate "wasteful" with "wrong."

### SUG-2: Test docstring on `test_process_item_e2e_extracted_facts_persisted_via_persist_extraction` is now stale

**File:** `tests/integration/test_pipeline_e2e.py:719-722`

```python
def test_process_item_e2e_extracted_facts_persisted_via_persist_extraction(
    bag, monkeypatch,
):
    """The Stage 1 facts JSONB is persisted into agenda_items.extracted_facts
    by extraction.persist_extraction. End-to-end verification: ..."""
```

Per deviation #2, `persist_extraction` is **not** called anymore. The function and test name both reference it. The test still works because it's checking the end-state column values, but the docstring and function name lie about the implementation. Either:

- Rename to `test_process_item_e2e_persists_extracted_facts_inline` and update the docstring; or
- Leave the test name as-is (less churn) and just fix the docstring to: "...persisted into `agenda_items.extracted_facts` by the pipeline's inline UPDATE (replaces the original `persist_extraction` call to avoid the `processing_status='extracted'` side-effect — see deviation #2 / pipeline.py:254-270 comment)."

This is a doc-only fix but matters for future readers.

### SUG-3: Idempotency test doesn't catch a possible regression in the Wave 0 short-circuit

**File:** `tests/integration/test_pipeline_e2e.py:803-841`

The test calls `process_item` twice on the same row. Both calls have `evaluate_data_quality` mocked to return `('ok', 'normal')`. After the first call, `processing_status` is `'completed'`. The second call still runs through Stage 1 + 2 mocks and Phase C. The assertion `badges_first == badges_second` passes due to `ON CONFLICT DO NOTHING`.

**But** the test doesn't pin down what `process_item` returns on the second call. If a future refactor adds a "skip if already completed" short-circuit (a reasonable optimization), the second call's return value would change from `'completed'` to something like `'skip_already_completed'`. The test wouldn't notice because it doesn't assert the return value of the second call.

**Suggestion:** add `assert pipeline.process_item(item2) == "completed"` and pin the second-call return alongside the badge equality. This makes the test explicit about the idempotency contract: "calling twice gives the same status and the same badges."

Same comment for `final["headline"]` — assert it's still the expected text after the second call, not just that badges match.

### SUG-4: Live test asserts `"sole_source" in slugs` but this depends on Anthropic's extraction stability

**File:** `tests/live/test_pipeline_live.py:127-134`

The deterministic `sole_source` process badge fires off `facts.procurement_method ∈ ('sole_source', 'no_bid')`, which is a Stage 1 (Haiku 4.5) classification. The seeded item's description explicitly says "sole-source contract" — a clear signal — so Haiku should reliably classify it. But the assertion is brittle if Anthropic's model drifts or if a future prompt update changes the enum mapping.

The other deterministic policy badges (sole_source emergency detection, etc.) don't fire here because they're $1.2M with "emergency" not in the title.

**Suggestion (defensive):** make the assertion more inclusive:

```python
# Sole-source $1.2M HVAC contract should fire at least one process badge.
# 'sole_source' is the strongest signal; allow 'emergency_action' as a
# secondary if Haiku ever interprets the description differently.
assert slugs, f"expected at least one badge; got none. (final={final})"
assert "sole_source" in slugs or "emergency_action" in slugs, (
    f"expected sole_source or emergency_action; got {slugs}"
)
```

Keeps the test cheap (~$0.003) and stable across minor LLM variance. Or accept the brittleness as a deliberate canary signal — flag-of-choice for the implementer.

### SUG-5: Plan §659 referenced `persist_extraction` — fold deviation #2 back into the plan

**File:** `docs/superpowers/plans/2026-05-10-b5-pipeline-orchestrator.md:659`, `:696`, `:1543`

The plan still references `persist_extraction(cur, item.id, facts, version=EXTRACTION_PROMPT_VERSION)` in the pseudocode (line 659) and in the comment about "Phase C's whole transaction (including persist_extraction)" (line 696). Plan §1543's narrative also says "...including persist_extraction's write..."

Since the implementer chose to inline the write **to make decision #13 work correctly**, the plan should be updated as a post-hoc correction note (a one-paragraph "Deviation #2" appendix at the top of the plan, pointing at the implementer report) so that anyone reading the plan first doesn't think the implementation drifted by accident. Keep the inline-UPDATE shape's rationale captured for future readers.

This is a doc-only nit but the implementation diverges from the plan in a deliberate, important way; readers shouldn't have to read the implementer's report to figure that out.

---

## NICE-TO-HAVE

### NTH-1: Logging granularity is asymmetric

**File:** `src/docket/ai/pipeline.py`

The pipeline logs:
- Wave 0a reject (line 134-137) ✓
- Wave 0b match (line 151-154) ✓
- Phase C guard fire (line 309-313) ✓
- Final completion of `_rerun_from_stage2` (line 350-353) ✓

But it does NOT log:
- Stage 1 success / cache hit (extraction.py has its own `log.debug`)
- Reconcile-retry-fired event (when `result.action == "retry_stage2_with_override"`)
- "Lost-race short-circuit avoided" — when `expected_status` is set and the guard succeeds (a debug-level positive confirmation would help in production debugging when admins are racing)

Suggestion: add `log.info("pipeline.retry_stage2_fired: item_id=%s", item.id)` before the auto-retry rewrite call (around line 226). When backfill hits high reconcile-conflict rates, this log is the only way to count retry frequency without scanning `score_overrides` JSONB after the fact.

Not blocking; observability improvement.

### NTH-2: `_ItemView` requires `raw_text` attribute but tests don't always set it

**File:** `tests/integration/test_pipeline_e2e.py:202-227`

`_load_item` populates the `source_type` attribute but NOT `raw_text`. Wave 0's `evaluate_data_quality` reads `item.raw_text` (`wave0.py:64`). If `evaluate_data_quality` were ever NOT monkeypatched in a test, it would raise `AttributeError`. All current tests do monkeypatch it, so this is latent.

The live test correctly sets `row["raw_text"] = None` (`test_pipeline_live.py:101`). The worker-side `_ItemView` (out of scope, reviewer-2) also handles it.

**Suggestion:** add `row["raw_text"] = None` in `_load_item` (test_pipeline_e2e.py:227) as a defensive default, parallel to the existing `row["source_type"] = "agenda"` line. Future tests that call the real `evaluate_data_quality` without re-thinking item shape won't trip.

### NTH-3: Open question — should `persist_extraction` be split into "persist+flip" and "persist-only"?

The implementer raised this as a follow-up question. My take:

- Today's call sites of `persist_extraction`:
  - `worker.py` Stage 1 worker (v3) — wants the flip-to-extracted side-effect.
  - `pipeline.py` (would have) — must NOT flip because Phase C overwrites the status atomically.

- Refactor options:
  - **Option A:** split into `persist_extraction_only(cur, item_id, facts, version)` and `persist_extraction_and_mark_extracted(cur, item_id, facts, version)`. Two functions, intentions explicit.
  - **Option B:** add a flag — `persist_extraction(cur, item_id, facts, version, *, set_status=True)`. One function with a discriminator.
  - **Option C (current state):** keep `persist_extraction` flipping status; inline 4 lines of SQL in `pipeline.py` where the side-effect would be wrong. Code-comment explains why.

Option C (current) is fine for B5. Once Phase 3 backfill is shipping at scale, Option A is the cleanest. Option B is a foot-gun if someone forgets the kwarg. **Defer Option A as a Phase 4 cleanup task.**

### NTH-4: `city_id` vs `municipality_id` naming inconsistency

**Files:** `pipeline.py` reads `item.city_id`; `_load_item` query in test does `m.municipality_id AS city_id`; `_ItemView` in `conflict_resolution.py:321` maps `municipality_id → city_id`.

This is a known papercut — DB column is `municipalities.id`, FK is `meetings.municipality_id`, pipeline contract uses `city_id`. The `AS city_id` aliasing is the integration point.

Not B5's problem to fix. **Defer to a holistic naming pass** — probably either rename the DB column or fully embrace `municipality_id` in the pipeline. Both are bigger than B5.

---

## Decisions to escalate

None. All findings are in-scope and can be addressed by the implementer.

---

## Verified correct

Each item below was independently checked against the codebase and matches the plan/spec contract.

### Decision #13 — expected_status concurrency guard
- `_rerun_from_stage2` accepts `expected_status: str | None = None`. ✓ (`pipeline.py:172`)
- Worker path passes None. ✓ (called from `process_item` line 163 without expected_status, and from worker.py — reviewer #2's scope).
- Admin paths pass `'cross_stage_conflict'`. ✓ (`conflict_resolution.py:398, :605`).
- Phase C UPDATE has the conditional predicate `(%s::text IS NULL OR processing_status = %s::processing_status_enum)`. ✓ (`pipeline.py:288`).
- When `expected_status is not None and cur.rowcount == 0`, raises `PipelineConcurrencyError`. ✓ (`pipeline.py:305-317`).
- Raise propagates out of `with db()` block; `db()` rolls back. ✓ (`db.py:30-32`).
- `PipelineConcurrencyError` is a distinct exception class with comprehensive docstring. ✓ (`pipeline.py:74-88`).

### Phase C atomicity
- Both UPDATEs (inline extraction + guarded rewrite) share the same `with db() as conn, conn.cursor() as cur:` block. ✓ (`pipeline.py:254`).
- Same connection, same transaction. ✓ (psycopg2 implicit transaction on first `execute`).
- Exception propagation triggers `conn.rollback()`. ✓ (verified via `db.py` source).
- Badge INSERTs also live in the same block. ✓ (`pipeline.py:319-348`).

### Deviation #1: `source_type` column does not exist
- Migration 001 `agenda_items` table definition (`migrations/001_initial.py:79-95`) does not include `source_type`. ✓
- Migration 013 ALTER (`migrations/013_impact_first_refactor.py:35-59`) does not add `source_type`. ✓
- Grep across all migrations confirms no `source_type` ADD COLUMN. ✓
- `wave0.py:175-177` explicitly comments "agenda_items has no raw_text or source_type column; PDF source is the dominant input shape, so we hard-code 'pdf'".
- `worker.py:499-505` (reviewer-2 scope, but verified): same defaulting pattern.
- **Verdict: plan §305, §238, §247 had bugs; implementer correctly drops the column reference and defaults to "agenda" at the duck-typed level.**

### Deviation #2: `persist_extraction` flips `processing_status` → 'extracted'
- `extraction.py:206-220` confirms `persist_extraction` writes `processing_status = 'extracted'::processing_status_enum`. ✓
- If the plan's call had been preserved, in the admin-path case:
  1. `persist_extraction` writes `processing_status = 'extracted'`.
  2. Guarded UPDATE checks `processing_status = 'cross_stage_conflict'` — fails.
  3. `cur.rowcount = 0`.
  4. `PipelineConcurrencyError` raised — but spuriously, because no actual race happened.
- The implementer's inline UPDATE writes ONLY `extracted_facts` and `ai_extraction_version` — preserving the status for the guarded check. ✓ (`pipeline.py:262-270`).
- Behavioral parity: `facts.model_dump_json()` matches the exact call in `persist_extraction` (`extraction.py:219` vs `pipeline.py:269`). Same Pydantic v2 method, same `::jsonb` cast. ✓
- `EXTRACTION_PROMPT_VERSION` written: same constant (imported on pipeline.py:57). ✓
- **Verdict: deviation #2 is correct AND necessary. Without it, decision #13 leaks via the persist_extraction side-effect.**

### Wave 0 short-circuit (Phase A)
- `evaluate_data_quality != 'ok'` writes status `'data_quality_skipped'` in its own brief transaction, returns early. ✓ (`pipeline.py:122-138`).
- `is_procedural(item.title)` writes `'procedural_skipped'`. ✓ (`pipeline.py:140-155`).
- Both short-circuit BEFORE any LLM call — tested by `test_process_item_short_circuits_on_bad_data_quality` and `test_process_item_short_circuits_on_procedural_title`. ✓

### Reconcile auto-retry (decision #45)
- First reconcile call: `already_retried=False`. ✓ (`pipeline.py:223`).
- Retry-fired path: `reconcile_stages(..., already_retried=True)` on the SECOND call. ✓ (`pipeline.py:235`).
- Test `test_process_item_reconcile_retry_resolves_on_second_attempt` asserts both branches: first procedural → retry → substantive → completed, with `rewrite_call_count[0] == 2`. ✓
- Test `test_process_item_reconcile_escalates_after_second_failure` asserts the escalate path: both attempts procedural → `'cross_stage_conflict'` with conflicts populated in `score_overrides`. ✓

### Atomic write completeness — Phase C
- `extracted_facts` + `ai_extraction_version` (inline). ✓
- `headline`, `why_it_matters`, `significance_score`, `consent_placement_score`, `ai_confidence`, `ai_rewrite_version`, `score_overrides`, `processing_status` (guarded UPDATE). ✓
- On-write process badges (4 fast: hidden_on_consent, sole_source, legal_settlement, emergency_action). ✓ (calls `compute_on_write_process_badges`).
- Policy badges (deterministic + LLM-suggested). ✓ (calls `compute_policy_badges`).
- All in one transaction. ✓

### `compute_on_write_process_badges` signature alignment
- Plan + implementer pass `(item, facts, scores, ai_confidence)`. ✓
- `badges_process.py:214-219` declares exactly this signature. ✓
- Returns `list[tuple[str, float]]` — iterated as `for slug, conf in ...` in pipeline.py:321-323. ✓

### `compute_policy_badges` return shape
- Returns `list[tuple[str, float, str, dict]]` per `badges_policy.py:115`. ✓
- Iterated as `for slug, conf, source, metadata in ...` in pipeline.py:336-338. ✓ (4-tuple unpacking matches).

### Decision #92 — city_id on every INSERT
- Process badge INSERT (pipeline.py:326-333) includes `item.city_id`. ✓
- Policy badge INSERT (pipeline.py:339-348) includes `item.city_id`. ✓
- Test `test_process_item_happy_path_completes_and_writes_badges` asserts `badge[4] == bag.city_id` for every badge. ✓ (lines 394-396).
- Test `test_process_item_e2e_sole_source_fires_process_badge` asserts the same per-badge. ✓ (lines 712-716).

### `get_enabled_policy_slugs` consumed as list
- `get_enabled_policy_slugs(city_id) -> tuple[str, ...]` per `services/badges.py:29`. ✓
- `pipeline.py:208` wraps with `list(...)` to match `rewrite_item`'s `list[str]` signature. ✓

### Pydantic v2 `model_dump_json` vs `json.dumps`
- `StructuredFacts` extends `BaseModel` (Pydantic v2). ✓ (`extraction_schema.py:54`).
- Pipeline uses `facts.model_dump_json()` then casts via `%s::jsonb`. ✓ (`pipeline.py:269`).
- This is the SAME pattern used inside `persist_extraction` (`extraction.py:219`) — behavioral parity confirmed.

### Test mocking surface
- All tests monkeypatch `docket.ai.pipeline.<name>` not `docket.ai.extraction.<name>` or `docket.ai.rewrite.<name>`. ✓
- Specifically: `pipeline.evaluate_data_quality`, `pipeline.is_procedural`, `pipeline.extract_facts_for_item`, `pipeline.rewrite_item`.
- This is the correct interception point because `pipeline.py:56-69` does `from docket.ai.extraction import extract_facts_for_item` (etc.) — the names are bound at import time at the pipeline module level. Mocks at the source modules wouldn't take effect.

### `db()` context manager rollback behavior
- `db()` calls `conn.rollback()` on any exception inside the `with` block. ✓ (`db.py:30-32`).
- Both Phase A short-circuit UPDATEs and Phase C are wrapped in `with db() as conn`.
- Test `test_rerun_from_stage2_guard_raises_when_status_mismatch` exercises the rollback path; status returns to pending, no headline, no badges (modulo the REQ-1 gap on `extracted_facts` assertion).

---

## Files reviewed

- `/Users/darrellnance/docket-pub-integration/src/docket/ai/pipeline.py` (355 lines)
- `/Users/darrellnance/docket-pub-integration/src/docket/ai/extraction.py` (verified persist_extraction side-effect, lines 206-220)
- `/Users/darrellnance/docket-pub-integration/src/docket/ai/rewrite.py` (verified rewrite_item signature)
- `/Users/darrellnance/docket-pub-integration/src/docket/ai/wave0.py` (verified evaluate_data_quality / is_procedural)
- `/Users/darrellnance/docket-pub-integration/src/docket/ai/floors.py` (verified apply_score_floors 5-arg signature)
- `/Users/darrellnance/docket-pub-integration/src/docket/ai/reconcile.py` (verified reconcile_stages and ReconciliationResult)
- `/Users/darrellnance/docket-pub-integration/src/docket/ai/badges_process.py` (verified compute_on_write_process_badges signature and return)
- `/Users/darrellnance/docket-pub-integration/src/docket/ai/badges_policy.py` (verified compute_policy_badges return shape)
- `/Users/darrellnance/docket-pub-integration/src/docket/services/badges.py` (verified get_enabled_policy_slugs returns tuple)
- `/Users/darrellnance/docket-pub-integration/src/docket/db.py` (verified rollback semantics)
- `/Users/darrellnance/docket-pub-integration/src/docket/migrations/001_initial.py:79-95` (verified no source_type column in agenda_items)
- `/Users/darrellnance/docket-pub-integration/src/docket/migrations/013_impact_first_refactor.py:34-59, 129-140` (verified no source_type added; UNIQUE (agenda_item_id, badge_slug))
- `/Users/darrellnance/docket-pub-integration/tests/integration/test_pipeline_e2e.py` (842 lines)
- `/Users/darrellnance/docket-pub-integration/tests/live/test_pipeline_live.py` (135 lines)
- `/Users/darrellnance/docket-pub-integration/docs/superpowers/plans/2026-05-10-b5-pipeline-orchestrator.md` (selected sections per decision #13, persist_extraction references, source_type references)
- `/Users/darrellnance/docket-pub-integration/src/docket/services/conflict_resolution.py:300-420` (verified G4 call sites — but the file itself is reviewer-2 scope; I only confirmed the contract surface my scope exposes)
