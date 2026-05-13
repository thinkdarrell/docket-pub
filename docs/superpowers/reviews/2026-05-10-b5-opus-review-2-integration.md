# B5 Opus Review #2 — Worker Integration + G4 Refactor + Flag Wiring

**Reviewer:** Opus (independent reviewer #2 — integration scope)
**Date:** 2026-05-10
**Branch:** `release/impact-first-v3`
**Range:** `3186610..c7442e1` (5 commits)
**Scope:** `worker.py` (v3 dispatch, `claim_items_v3_sql`, `_process_items_v3`, `_AttrAccess`, lazy `_make_client`), `config.py` (`IMPACT_FIRST_ENABLED`), `services/conflict_resolution.py` (G4 refactor), `tests/integration/test_worker_v3_dispatch.py`, `tests/integration/test_conflict_resolution.py`. **Out of scope:** `pipeline.py`, `test_pipeline_e2e.py`, `test_pipeline_live.py` (reviewer #1).

---

## Summary verdict

**Ship with one REQUIRED fix and three SUGGESTED follow-ups.**

REQUIRED count: **1** (a latent `AttributeError` masquerading as `AIFatalError` when v3 path encounters misconfigured pricing).

The integration is otherwise correct: the dispatch routes correctly under both flag states; `claim_items_v3_sql` is syntactically and semantically right for the v3 versioning columns; the G4 refactor preserves the regression contract via 5 surgical second-monkeypatch lines that all cover the right call site; the audit-payload synthesis maps cleanly to the existing G4 test assertions; the early-UPDATE TOCTOU guard in `edit_stage_1_facts` is preserved; the `_DEAD_CODE_REMOVED` stub was cleaned up before commit; `_AttrAccess` is correctly column-aligned with the v3 claim SQL.

Three observed behavioral changes are documented but not flagged as REQUIRED because the test suite's regression contract still holds:
1. Admin `re_prompt_stage_2` and `edit_stage_1_facts` now go through the pipeline's `already_retried=False` path, which can fire a second LLM call inside one admin click. Pre-B5 the admin paths called `reconcile_stages(..., already_retried=True)` (no retry).
2. Admin path audit payload no longer carries `served_model` or `is_substantive` (no G4 test asserts these, but a hypothetical operator query against `processing_status_audit.payload` will get less detail post-B5).
3. The module docstring of `conflict_resolution.py` is now stale — it describes deleted functions.

---

## Deviation-report verdict (your-scope subset)

| # | Deviation | Verdict |
|---|---|---|
| 3 | 5 G4 tests got a second `monkeypatch.setattr("docket.ai.pipeline.rewrite_item", ...)` | **OK — minimal and complete.** All 5 sites where the old path is patched also patch the new path. The fixture `mock_rewrite_item` cascades to 4 dependent tests, so functional coverage is ~8 LLM-touching tests. No silently-passing tests detected. |
| 4 | Audit payload preservation via post-pipeline read-back + synthesized `reconcile_action` | **OK — mapping is correct; no test relied on `served_model`/`is_substantive` payload keys.** Read-back is in a separate, post-Phase-C transaction; reads the committed state correctly. Synthesized mapping: `completed → "accept"`, `cross_stage_conflict → "mark_cross_stage_conflict"`. Matches G4 test assertions at lines 704 and 751. |
| 5 | `run_once` lazy `AIClient` + `AI_ITEM_MODEL` fallback | **MOSTLY OK — has one latent bug.** Fallback fires only on v3 path. `AI_ITEM_MODEL` exists in `config.py`. `_open_run` records the fallback model in `ai_runs.model`. **REQUIRED fix:** the PRICING-validation error message at `worker.py:330` still dereferences `client.item_model`/`client.meeting_model` even though `client` is None on the v3 path — would raise `AttributeError` masking `AIFatalError`. See REQUIRED-1 below. |
| 6 | `_re_prompt_stage_2_legacy_DEAD_CODE_REMOVED` stub | **OK — zero matches** for `_DEAD_CODE_REMOVED` or `_legacy` in `conflict_resolution.py`. The deleted function bodies are gone (verified via `git diff 3186610..HEAD`). Only the stale module-level docstring still references the deleted helpers — see SUGGESTED-2. |

---

## G4 regression status

All 45 G4 tests should still pass per the implementer's verification (the user-supplied test-run preamble cites 1305 passing). My static analysis surfaces no test that should silently pass:

- The 5 monkeypatch sites all cover both `docket.services.conflict_resolution.rewrite_item` (the old re-export, still importable for back-compat) AND `docket.ai.pipeline.rewrite_item` (the new actual call site).
- Tests that don't reach the LLM (pydantic validation, 404, login redirect, length-cap validation) don't need either patch.
- `test_re_prompt_returns_400_on_stored_facts_pydantic_drift` (line 1132) doesn't mock anything; validation fails BEFORE the pipeline import, so this is safe.
- `test_accept_s2_lost_race_surfaces_4xx_with_body` (line 1173) doesn't go through the LLM-touching paths at all (accept_stage_2 has no Stage 2 call). Safe.
- `test_edit_facts_pre_llm_race_does_not_overwrite_completed_facts` (line 1014) asserts `llm_called == []` — if the mock fired via either path the test would fail. Functions as a self-check.

**G4 verdict: regression contract intact.**

---

## REQUIRED

### REQUIRED-1: PRICING-validation error message dereferences `None` on v3 path

**Location:** `src/docket/ai/worker.py:326-331`

```python
from docket.ai.pricing import PRICING
if model not in PRICING:
    raise AIFatalError(
        f"Model {model!r} has no entry in docket.ai.pricing.PRICING; "
        f"add per-token rates before running. Configured models: "
        f"AI_ITEM_MODEL={client.item_model!r}, AI_MEETING_MODEL={client.meeting_model!r}"
    )
```

When `IMPACT_FIRST_ENABLED=True` and `stage="items"`, `client is None` (per the lazy-construction guard on line 310). If a v3 deployment sets `AI_ITEM_MODEL` to a value not in `PRICING` (typo, new model version not yet registered), this branch fires, but `client.item_model` raises `AttributeError: 'NoneType' object has no attribute 'item_model'` — burying the original misconfiguration behind a stack trace pointing at the error-message construction.

Likelihood: low (PRICING and AI_ITEM_MODEL are usually in sync) but the consequence is a misleading error during a config-drift incident — exactly when clarity matters most.

**Fix:** make the message tolerate `client is None`:

```python
if model not in PRICING:
    configured = (
        f"AI_ITEM_MODEL={client.item_model!r}, "
        f"AI_MEETING_MODEL={client.meeting_model!r}"
        if client is not None else
        f"AI_ITEM_MODEL (v3 fallback)={AI_ITEM_MODEL!r}"
    )
    raise AIFatalError(
        f"Model {model!r} has no entry in docket.ai.pricing.PRICING; "
        f"add per-token rates before running. Configured models: {configured}"
    )
```

Or simpler — drop the client-dereferencing tail entirely; the bare `model` value plus `AI_ITEM_MODEL` from `os.environ` is enough for the operator to diagnose.

This is the only REQUIRED fix in scope. It does not block the flag flip (production PRICING is presumably correct), but it's a sharp edge that will draw blood at exactly the wrong moment.

---

## SUGGESTED

### SUGGESTED-1: Admin paths now do silent auto-retry on reconcile

**Location:** `src/docket/services/conflict_resolution.py:re_prompt_stage_2`, `edit_stage_1_facts` → calls `pipeline._rerun_from_stage2`

**Observation:** Pre-B5, the local `_rerun_stage2` helper called `reconcile_stages(facts, rewrite, item_view, already_retried=True)` — **always** suppressing the auto-retry path. Post-B5, the admin paths call `pipeline._rerun_from_stage2` which uses `already_retried=False` (`pipeline.py:223`). If the post-admin-override Stage 2 rewrite returns `is_substantive` in a way that trips reconcile's `retry_stage2_with_override` branch, a second `rewrite_item` call fires inside the same admin click — **doubling LLM cost and latency for that single admin action**.

The retry's `extra_instruction` is `result.override_instruction` (from `reconcile_stages`), NOT the admin's `override`. So the admin's instruction is honored on the FIRST call but silently discarded on the retry.

**Impact:**
- Admin button click cost: ~$0.001 per call → ~$0.002 worst case (still trivial in absolute terms).
- Admin button click latency: ~2-3s → ~4-6s worst case (noticeable in the UI).
- Audit trail: `reconcile_action` reflects the SECOND reconcile's result, not the first. An admin reading the audit log may wonder why their override "worked" or "failed" without realizing a second internal rewrite happened.

**Recommendation (NICE-TO-HAVE):** add an `already_retried` (or `allow_auto_retry`) parameter to `pipeline._rerun_from_stage2` defaulting to `False`. The admin paths pass `already_retried=True` to preserve pre-B5 semantics. The worker path keeps the default. Or, more aggressively: don't add a parameter; treat the dual-LLM behavior on admin paths as an intentional convergence with the worker's behavior, and document it.

Either choice is defensible. The current state (silently changed semantics) is the worst of both — flag for explicit decision.

### SUGGESTED-2: Stale module docstring in `conflict_resolution.py`

**Location:** `src/docket/services/conflict_resolution.py:1-38`

The module docstring describes `_rerun_stage2`, `_get_enabled_policy_slugs`, and the "plan deviation" notes about `apply_score_floors`'s signature — all of which apply to deleted code. The docstring still says:

> Two of the four actions (`re_prompt_stage_2`, `edit_stage_1_facts`) re-run Stage 2 of the v3 pipeline. They use a private helper `_rerun_stage2` that calls `rewrite.rewrite_item` -> `floors.apply_score_floors` -> `reconcile.reconcile_stages`. This helper is a minimal Stage 2 re-run path; B5 (the cross-track convergence task) will later subsume it into a full per-item orchestrator.

Post-B5 (this commit set) that's wrong on two counts: the helper is deleted, and the subsumption has happened. Replace with a 4-line description pointing readers at `docket.ai.pipeline._rerun_from_stage2`.

Low priority, but a future maintainer grepping for `_rerun_stage2` will land here, find nothing, and waste a minute. Mechanical cleanup.

### SUGGESTED-3: Meeting-path `model = AI_ITEM_MODEL` mislabel in lazy-construction edge case

**Location:** `src/docket/ai/worker.py:319-320`

The lazy-construction guard correctly produces `client = None` only when `(stage == "items" AND IMPACT_FIRST_ENABLED)`. So in production the `else: model = AI_ITEM_MODEL` branch only executes for v3 item batches — and `AI_ITEM_MODEL` is correct there.

BUT under test (`test_run_once_dispatch_preserves_meeting_path`, `worker_v3_dispatch.py:71`), `_make_client` is monkeypatched to return None for `stage="meetings"`. The fallback then records `AI_ITEM_MODEL` in `ai_runs.model` for a meetings run. This is a test-only artifact (the production path always has a real client for meetings), but it does mean the dispatch tests can't be used to verify model accounting.

**Recommendation:** none required. Flag for the technical-report synthesizer.

### SUGGESTED-4: `claim_items_v3_sql` lacks deterministic ordering across parallel workers

**Location:** `src/docket/ai/worker.py:31-67`

`ORDER BY ai.id` is deterministic by row, but `SKIP LOCKED` means parallel workers race for the top-K. The first worker takes ids [1..10], the second takes [11..20], etc., subject to lock-skip semantics. Decision #8 of the plan documents that v3 is single-instance, so this is fine. But the plan also says (decision #10) cost telemetry is per-batch, and there's no mechanism to attribute work to a worker — so the cost-tracking gap compounds with parallel-worker uncertainty.

**Recommendation:** none. Document in the cron-worker runbook that v3 is single-instance until cost-attribution lands.

### SUGGESTED-5: `_process_items_v3` cost telemetry gap (decision #10)

**Location:** `src/docket/ai/worker.py:467-541`

Per decision #10 in the plan, `summary.cost_usd` stays at 0.0 for v3 batches. The `ai_runs` row is opened (line 334), but `_close_run` writes `cost_usd=0.0` and `usage` as an empty Usage. Operational follow-up flagged in plan §B5 fix-up notes.

**Recommendation:** confirm Grafana / Healthchecks dashboards for the `ai_items` cron are reviewed for zero-spend alerts BEFORE flipping `IMPACT_FIRST_ENABLED=true` on Railway (matches the plan's self-review item at line 2169).

### SUGGESTED-6: `municipality_id` vs `city_id` naming inconsistency

The DB column is `meetings.municipality_id`; the pipeline contract calls it `city_id`; the admin path's `_ItemView` maps `municipality_id → city_id`. The worker's `claim_items_v3_sql` aliases `m.municipality_id AS city_id`. The implementer flagged this. **Not a bug** — every call site maps consistently — but a one-pass rename pass would prevent future drift. Out of B5 scope.

---

## Detail-by-file findings

### `src/docket/config.py` (+10 lines)

Trivially correct. Flag definition follows the existing env-var pattern. Default `False` preserves pre-B5 behavior. Inline comment documents the cutover sequence (FINAL-3, decision #45, decision #93 SMART_BREVITY_UI).

No findings.

### `src/docket/ai/worker.py` (+~90 lines)

- **`claim_items_v3_sql` (lines 31-67):** correct.
  - Filter `processing_status = 'pending'::processing_status_enum` excludes `cross_stage_conflict` (admin-resolution territory) AND excludes the already-completed/skipped states. ✓
  - Version-mismatch predicate covers both `NULL` and `< version` paths for extraction AND rewrite versions. ✓
  - `FOR UPDATE OF ai SKIP LOCKED` locks only `agenda_items` (not the joined `meetings`/`municipalities` reads). Safe — concurrent meeting writes don't block item claims. ✓
  - `ORDER BY ai.id LIMIT %s` is deterministic at the row level. ✓
  - No debounce — documented in the docstring; reasonable given Wave 0 pre-classifies. ✓
  - Schema verified: `last_error_at`/`last_error_message` columns exist (migration 013:44-45); `failed_permanent` is in `processing_status_enum` (migration 013:31).
- **`_AttrAccess` (lines 456-464):** lightweight dict-to-attribute adapter; thread-safe and side-effect-free. Implementation via `self.__dict__.update(d)` correctly handles None values (the issue would be if it tried to call dict methods on None — it doesn't).
  - The class is defined AFTER `_process_items_v3` would conceptually reference it, but both are module-level so import order doesn't matter. Cosmetic only.
- **`_process_items_v3` (lines 467-541):**
  - Reads claim SQL, builds `row_dict` from the 10 returned columns. ✓
  - Sets `source_type='agenda'` and `raw_text=None` defaults because `agenda_items` table has no such columns. Verified by `grep "source_type" src/docket/migrations/` returning empty. Plan said the SELECT should include `source_type` — the implementer correctly recognized the schema mismatch and patched at the Python layer. **Plan drift, correctly handled.**
  - Per-row commit on success; rollback on transient/permanent/fatal. ✓
  - `AIPermanentRowError` writes `failed_permanent` + `last_error_at` + `last_error_message`. ✓
  - `AITransientError`: `continue` (try next row). ✓
  - `AIRateLimited`: `break` (end batch). ✓
  - `AIFatalError`: re-raise. ✓
  - **One concern:** if `pipeline.process_item` raises an exception NOT in this hierarchy (e.g., `pydantic.ValidationError` from a malformed Stage 1 fact set, or a raw `psycopg2.OperationalError` from a transient DB blip), the loop has no handler — the exception propagates out of `_process_items_v3`, leaving the in-progress row uncommitted but NOT marked failed. Then `_close_run` is skipped, leaving the `ai_runs` row at `finished_at=NULL`. This is a graceful-degradation gap. The v2 path has the same gap, so this is NOT a regression — flag for a future hardening pass.
- **`run_once` dispatch (lines 291-348):** logic is correct.
  - Lazy `_make_client` per `(stage == "meetings" or not IMPACT_FIRST_ENABLED)` — matches plan step 2.4(e). ✓
  - `if client is not None: model = client.item_model if stage == "items" else client.meeting_model` correctly chooses the right model for v2.
  - Else branch uses `AI_ITEM_MODEL` — correct for v3-items but technically wrong for "meetings with mocked-None client" (test-only artifact, see SUGGESTED-3).
  - Dispatch block correctly routes items to v3 when flag is True, v2 otherwise; meetings always to v2. ✓
  - **REQUIRED-1 lives here** (line 330: `client.item_model` deref on None).

### `src/docket/services/conflict_resolution.py` (~-120 lines net)

Files diff verified via `git diff 3186610..HEAD -- src/docket/services/conflict_resolution.py`.

- **Deletions confirmed:**
  - `_rerun_stage2` function: deleted (-95 lines).
  - `_get_enabled_policy_slugs` function: deleted (-11 lines).
  - `_RerunOutcome` dataclass: deleted (-8 lines).
  - Imports of `apply_score_floors`, `reconcile_stages`, `list_enabled_badges`: deleted.
  - Import of `typing.Any, Literal`: deleted (no longer used after `_RerunOutcome` removal).
- **Kept (correctly):**
  - `_ItemView` class — extended with `city_id` (mapped from `municipality_id`), `source_type='agenda'`, `raw_text=None` to match the pipeline's expanded contract. ✓
  - `rewrite_item` import — kept as a no-op re-export for backward-compat with G4 tests that patch `docket.services.conflict_resolution.rewrite_item`. The `noqa: F401` is correctly applied. ✓
  - `_load_conflict_item`, `_audit`, `accept_stage_1`, `accept_stage_2` — unchanged.
- **`re_prompt_stage_2` refactor:**
  - Sequence matches the plan (Step 3.2): validate → load → pydantic-validate facts → call pipeline with `expected_status='cross_stage_conflict'` → on `PipelineConcurrencyError` write lost-race audit + raise `ConflictAlreadyResolvedError` → on success write audit + return.
  - Catches `pydantic.ValidationError` specifically (line 378) — not bare `Exception`. Matches plan's engineer-review specificity ask. ✓
  - `ConflictAlreadyResolvedError` message includes `current_status` (line 428-430). ✓
  - **Audit payload synthesis** (lines 432-474): reads `score_overrides, headline, why_it_matters, significance_score, consent_placement_score` in a fresh transaction post-pipeline, then synthesizes `reconcile_action` from `pipeline_status`. The synthesized mapping (`completed → "accept"`, else → `"mark_cross_stage_conflict"`) matches the G4 test assertions at line 704 (`assert payload["reconcile_action"] == "accept"`) and line 751 (`assert payload["reconcile_action"] == "mark_cross_stage_conflict"`). ✓
  - Read-back happens in a SEPARATE transaction from the pipeline's Phase C commit. Since Phase C committed before this read, the read sees the post-pipeline state correctly. ✓
  - **Minor concern (not REQUIRED):** the audit row no longer carries `served_model` or `is_substantive`. Grep of `tests/integration/test_conflict_resolution.py` confirms no test asserts these keys. But an admin debugging post-resolution behavior loses visibility into "which model served this resolution" — flag for an operational follow-up (could be added by extending `pipeline._rerun_from_stage2` to return more than just `str`, but that's out of B5 scope).
- **`edit_stage_1_facts` refactor:**
  - Pydantic validation up-front with `PydanticValidationError` specificity (line 533). ✓
  - **Pre-LLM TOCTOU UPDATE preserved (lines 549-557):**
    ```python
    UPDATE agenda_items
       SET extracted_facts = %s::jsonb
     WHERE id = %s
       AND processing_status = 'cross_stage_conflict'::processing_status_enum
    ```
    `cur.rowcount == 0` check writes the `edit_stage1_facts_lost_race_pre_llm` audit row (line 569) and sets `race_lost_pre_llm = True`. Raise is deferred until after the `with db()` block (line 581-591) so the audit row commits. **This preserves G4 fix-up B-R1's pre-LLM race detection — saves the LLM spend on lost races AND prevents the silent overwrite of post-resolution `extracted_facts`.** ✓
  - **The early UPDATE is NOT inside the pipeline.** It's still inside `conflict_resolution.py:edit_stage_1_facts`. The pipeline's own extraction-write UPDATE (`pipeline.py:262-270`) is a SEPARATE write that happens INSIDE the pipeline's Phase C transaction. The two writes are layered:
    1. `edit_stage_1_facts` writes the admin's corrected facts FIRST (guarded by `processing_status = 'cross_stage_conflict'`), saving LLM spend on race-loss.
    2. The pipeline's Phase C re-writes `extracted_facts` (with the same facts object — `model_dump_json()`) INSIDE its atomic block, guarded by the same `expected_status` predicate.
    The double-write is intentional and not wasteful: the pipeline's write is part of its all-or-none commit; without it, an admin's late-race-loss would leave the pre-LLM UPDATE committed but the rewrite uncommitted, breaking the atomic invariant. **Architecturally correct.** ✓
  - Pipeline call uses `expected_status='cross_stage_conflict'` (line 605) — late TOCTOU guard. ✓
  - On `PipelineConcurrencyError`, writes `edit_stage1_facts_lost_race` audit (line 619) — distinct verb from `edit_stage1_facts_lost_race_pre_llm` so trail readers can distinguish. ✓
  - Post-success audit payload synthesis matches `re_prompt_stage_2`'s shape. ✓
- **`_ItemView` defaults `source_type='agenda'` and `raw_text=None`** (lines 326-327) — admin paths don't re-run Wave 0, so these attributes are never actually consumed by the pipeline (Wave 0 is skipped because the row is already at `cross_stage_conflict`, so `process_item`'s Wave 0 branch is unreachable for the admin path that goes directly to `_rerun_from_stage2`). Belt-and-suspenders defaulting; harmless. ✓
- **Module docstring (lines 1-38):** stale. See SUGGESTED-2.

### `tests/integration/test_worker_v3_dispatch.py` (NEW, 112 lines)

Four tests, matching plan task 2.1:
1. `test_run_once_dispatches_to_v3_when_flag_enabled` — sets `IMPACT_FIRST_ENABLED=True`, asserts `_process_items_v3` got called and `_process_items` did not. ✓
2. `test_run_once_dispatches_to_v2_when_flag_disabled` — sets flag to `False`, asserts the opposite. ✓
3. `test_run_once_dispatch_preserves_meeting_path` — sets flag to `True` but stage="meetings", asserts `_process_meetings` got called regardless. ✓
4. `test_run_once_v3_dispatch_does_not_construct_ai_client` — sets flag to `True`, asserts `_make_client` was NOT called (line 108-111). ✓

**Concerns:**
- All four tests monkeypatch `_today_spend → 0.0` to bypass the budget gate, and `_make_client → None`. The `_make_client` mock is unnecessary for test 1 and 4 (which explicitly assert it isn't called) but harmless.
- Test 4 documents the design choice ("If the implementer prefers to always construct the client (for consistency with v2), flip to assert `len(client_factory_calls)==1`"). The implementer kept the lazy-construct design. ✓
- No test exercises the **dispatch with a REAL pricing-validation failure path** — but that's REQUIRED-1's territory; adding a regression test there would be a good companion fix.
- Test parametrization: implemented as two separate tests rather than a parametrize fixture. The plan didn't specify; either is fine. Two-test form is more readable for this small case.

### `tests/integration/test_conflict_resolution.py` (+10 lines across 5 sites)

Already covered in "G4 regression status" and "Deviation #3" above.

Site-by-site:
- **Line 666** (fixture `mock_rewrite_item`): added `monkeypatch.setattr("docket.ai.pipeline.rewrite_item", mock)` alongside the existing `docket.services.conflict_resolution.rewrite_item` patch. Cascades to 4 tests: `test_re_prompt_resolves_conflict_when_rerun_is_substantive`, `test_re_prompt_validates_override_length`, `test_re_prompt_404_for_unknown_or_completed_item`, `test_edit_facts_persists_corrected_facts_and_reruns_stage2`. ✓
- **Line 732** (`test_re_prompt_stays_in_conflict_when_rerun_still_procedural`): mocks `_mock` returning procedural rewrite, patches both old + new. ✓
- **Line 838** (`test_re_prompt_returns_409_when_item_resolved_during_llm_call`): mocks `_mock_with_concurrent_resolve` that fires a racing UPDATE inside the mock. Patches both old + new — critical, because the racing UPDATE has to fire DURING the actual rewrite_item call window for the test's TOCTOU detection to be exercised. Patching only the old path would make this test silently pass via a never-fired mock. ✓
- **Line 992** (`test_edit_facts_returns_409_when_item_resolved_during_llm_call`): same shape as line 838, for the edit-facts path. ✓
- **Line 1108** (`test_edit_facts_pre_llm_race_does_not_overwrite_completed_facts`): pre-LLM race test. The mock SHOULDN'T fire (test asserts `llm_called == []`). Double-patch is redundant but harmless — if the mock did fire via either path, the assertion would catch it. ✓

**G4 tests NOT requiring monkeypatch:**
- All `accept_stage_1` / `accept_stage_2` tests — no LLM.
- Form-rendering tests (`test_re_prompt_form_renders_inline`, `test_edit_facts_form_renders_inline`) — GET endpoints; no LLM.
- `test_edit_facts_validates_pydantic_schema`, `test_edit_facts_validates_json_parseability`, `test_edit_facts_404_for_unknown_or_completed_item` — fail at validation or 404 before pipeline; no LLM.
- `test_re_prompt_validates_override_length` — uses fixture, gets coverage via fixture.
- `test_re_prompt_404_for_unknown_or_completed_item` — uses fixture, gets coverage via fixture.
- `test_re_prompt_returns_400_on_stored_facts_pydantic_drift` — pydantic fails BEFORE pipeline; no LLM.
- `test_accept_s2_lost_race_surfaces_4xx_with_body` — Accept-S2 doesn't go through Stage 2; no LLM.

**No silently-passing tests detected.**

---

## Cross-cutting concerns

### Worker v2 path unchanged

Verified: `_process_items` (v2, lines 351-386) is unchanged from pre-B5. The `claim_items_sql` (lines 18-28) is unchanged. The v2 worker's `write_item_result`, `mark_item_failed`, `mark_meeting_*` functions are unchanged. The flag flip is non-destructive. ✓

### Per-row commit semantics in `_process_items_v3` vs v2

v2 (line 359-386): `try: ... commit ... except: ... rollback/continue/break`. Shape:
- Success → commit
- Rate-limit → rollback + break
- Transient → rollback + continue
- Permanent → rollback + mark_item_failed + commit
- Fatal → rollback + raise

v3 (line 510-541): same shape with one difference — permanent failure runs an inline `UPDATE agenda_items SET processing_status='failed_permanent'...` instead of calling a helper. Equivalent semantics; v3 inlines because the v2 helper `mark_item_failed` uses the v2 columns (`ai_metadata`, `ai_prompt_version`) which are v2's failure-recording shape.

Both paths correctly rollback the failed-row's in-progress writes BEFORE writing the failure marker, so the failure marker is a fresh atomic write — won't get rolled back if the loop's next iteration's commit fails.

### Schema-column verification

Confirmed via `grep` on migrations:
- `processing_status_enum` includes `'pending'`, `'failed_permanent'`, `'cross_stage_conflict'`. ✓ (Migration 013:28-31.)
- `agenda_items.last_error_at` (TIMESTAMPTZ) and `last_error_message` (TEXT). ✓ (Migration 013:44-45.)
- `agenda_items.ai_extraction_version` and `ai_rewrite_version`. ✓ (Implied by Track 1 work; confirmed by pipeline.py's UPDATE statements.)
- `agenda_items.source_type` does NOT exist. ✓ (No matches in `src/docket/migrations/`.)
- `meetings.municipality_id` is the FK column. ✓ (Used in `claim_items_v3_sql`'s JOIN.)

### Spec drift on `claim_items_v3_sql` from plan

Plan line 1344-1346 includes `ai.source_type` in the SELECT. Implementer removed it because the column doesn't exist. Documented in worker.py:499-506 with a comment defaulting `source_type` and `raw_text` to safe values. **Correct.**

### Decision #13 — concurrency guard via `expected_status`

Verified end-to-end:
1. Admin paths pass `expected_status='cross_stage_conflict'` to `pipeline._rerun_from_stage2` (conflict_resolution.py:398, 605). ✓
2. Worker path passes nothing (default `None`) so the guard is a no-op (worker.py uses `pipeline.process_item` → `_rerun_from_stage2(item, facts)` with no extras). ✓
3. Pipeline UPDATE includes `AND (%s::text IS NULL OR processing_status = %s::processing_status_enum)` with `expected_status` bound twice (pipeline.py:288, 300-302). ✓
4. On `cur.rowcount == 0`, pipeline raises `PipelineConcurrencyError` which the `with db() as conn` context propagates as an exception, causing rollback of the entire Phase C (extraction UPDATE + rewrite UPDATE + badge INSERTs). Confirmed by reading pipeline.py:254-317. ✓
5. Admin paths catch `PipelineConcurrencyError` and translate to `ConflictAlreadyResolvedError` after writing a `*_lost_race` audit row in a fresh transaction (conflict_resolution.py:400-430, 607-636). ✓

**Layer separation per plan's decision #13:** pipeline owns concurrency-detection; services owns audit-translation. ✓

---

## Items the technical-report synthesizer should highlight

For the reviewer #1 + reviewer #2 + spec-drift synthesis pass:

1. **REQUIRED-1** is the only ship-blocker in this scope, and it's a 4-line message-text fix.
2. **Admin path now does silent auto-retry on reconcile (SUGGESTED-1).** This is the most notable behavioral change relative to G4. The technical report should ask: do we want the convergence (admin = worker semantics) or do we want admin paths to skip the auto-retry? The current state changed implicitly via the refactor.
3. **Audit payload sparseness (SUGGESTED-1 secondary):** The post-B5 audit no longer carries `served_model` / `is_substantive`. Operationally minor but a data-loss vs G4's pre-refactor payload.
4. **Cost telemetry gap (SUGGESTED-5):** `summary.cost_usd = 0.0` for v3 batches. Decision #10 documented; needs Grafana audit before FINAL-3.
5. **Single-instance v3 worker assumption:** preserved (decisions #7, #8 of plan). Multi-instance would need (a) cost attribution and (b) more granular row-claim coordination. Not in B5 scope.
6. **Plan drift on `source_type`:** plan's SQL included `ai.source_type`; reality has no such column. Correctly worked around. Should be back-propagated to the plan if anyone re-uses it.

---

## Architectural commentary

### Why the two-layer TOCTOU works

`edit_stage_1_facts` now has THREE protective barriers:

1. **`_load_conflict_item`'s `FOR UPDATE OF ai`** — serializes concurrent admin clicks on the same row. Two admins hitting Accept-S1 simultaneously will queue up; the second sees `processing_status != 'cross_stage_conflict'` and gets `None`, which the route maps to 404.
2. **Early `extracted_facts` UPDATE with `AND processing_status = 'cross_stage_conflict'`** — catches the race where admin A's FOR-UPDATE lock has already released (transaction committed) but the row was just flipped to `completed` by admin B. Without this, admin A's late commit would overwrite admin B's just-resolved facts. Fires BEFORE the LLM call so admin A's $0.001 of LLM spend is saved.
3. **Pipeline's `expected_status` Phase C UPDATE predicate** — catches the race where the row was in `cross_stage_conflict` at early-UPDATE time but got resolved by admin B WHILE admin A's LLM call was in flight. Rolls back the entire Phase C (extraction + rewrite + scores + badges) atomically.

Each barrier covers a distinct race window:
- Barrier 1: between `_load_conflict_item`'s read and the same-transaction's `_load`-then-write window. Closed by SQL serialization.
- Barrier 2: between Barrier 1's transaction commit and the LLM call. Closed by application-level rowcount check.
- Barrier 3: between Barrier 2's transaction commit and Phase C's UPDATE. Closed by the pipeline's predicate + exception-driven rollback.

Together they form a Swiss-cheese defense that is robust against multi-admin concurrency. The architectural pattern is worth documenting in `docs/runbooks/cross-stage-conflicts.md` if it doesn't already live there.

### Why the auto-retry change is subtle but real

`reconcile_stages` is the pure-CPU consistency checker. When `already_retried=False`, it has three outcomes:
- `accept` — Stage 1 facts and Stage 2 rewrite agree (e.g., both substantive or both procedural, scores roughly aligned).
- `mark_cross_stage_conflict` — irrecoverable disagreement.
- `retry_stage2_with_override` — Stage 2 hallucinated; reconcile generates a corrective instruction and the orchestrator runs Stage 2 once more.

When `already_retried=True`, only the first two outcomes are reachable. Pre-B5 admin paths used `True`, so an admin's override was the SOLE rewrite. Post-B5 admin paths use `False`, so a reconcile-generated instruction can override the admin's override on the retry.

This is most visible in `test_re_prompt_stays_in_conflict_when_rerun_still_procedural`: the mock returns `is_substantive=False` regardless of instruction. Reconcile will likely see "Stage 1 says counterparty + funding_source (substantive-coded) but Stage 2 says is_substantive=False" — a classic retry trigger. The retry calls the same mock (returning still-procedural), then reconcile with `already_retried=True` concludes `mark_cross_stage_conflict`. **Two LLM calls per admin click for what was one click pre-B5.**

The test still passes because final state is `cross_stage_conflict` with `reconcile_action='mark_cross_stage_conflict'` either way. But cost + latency doubled on the sad path.

### Why the audit payload simplification is fine

Pre-B5 G4 wrote rich payloads:
```python
payload={
    "override_instruction": override,
    "reconcile_action": outcome.reconcile_action,
    "conflicts": outcome.conflicts,
    "served_model": outcome.served_model,
    "is_substantive": outcome.rewrite.is_substantive,
    "final_headline": outcome.rewrite.headline,
    "final_why_it_matters": outcome.rewrite.why_it_matters,
    "final_significance": outcome.score_overrides_obj.final_significance,
    "final_consent": outcome.score_overrides_obj.final_consent,
}
```

Post-B5:
```python
payload={
    "override_instruction": override,
    "pipeline_status": pipeline_status,
    "reconcile_action": reconcile_action,  # synthesized
    "conflicts": post_overrides.get("conflicts", []),
    "final_headline": post_headline,
    "final_why_it_matters": post_why,
    "final_significance": post_sig,
    "final_consent": post_consent,
}
```

Lost keys:
- `served_model`: which model handled this resolution. The pipeline's internal calls don't propagate the served-model string to the admin layer. Loss = post-mortem queries like "did Haiku 4.5 misbehave on these admin overrides?" lose granularity.
- `is_substantive`: was the rewrite substantive after the override? Inferable from `final_headline IS NULL` (procedural rewrites null out headlines) but not directly stored.

Gained key:
- `pipeline_status`: redundant with `to_status` in the audit row (same value).

**Verdict:** the loss is real but not test-asserted. If post-mortem audit queries need `served_model`, the fix is either (a) thread the model string through the pipeline's return signature, or (b) capture it in `score_overrides` JSONB at pipeline write time. Either is a follow-up, not B5 scope.

---

## Deeper walkthrough: dispatch-test correctness under mocked `_make_client`

Each of the four dispatch tests sets `_make_client → lambda: None`. This is a useful test isolation choice — it prevents network/import-time cost — but it creates non-trivial interactions with the post-B5 `run_once` code path. Let me trace each test to confirm correctness:

### Test 1: `test_run_once_dispatches_to_v3_when_flag_enabled`

- `IMPACT_FIRST_ENABLED = True`, `stage = "items"`.
- Line 310: `client = _make_client() if (stage == "meetings" or not IMPACT_FIRST_ENABLED) else None`
  - `("meetings" == "meetings" or not True) = (False or False) = False`
  - So `client = None` (the else branch); `_make_client` is NOT called.
- Line 312: `if client is not None: ...` — False, skip.
- Line 319-320: `from docket.config import AI_ITEM_MODEL; model = AI_ITEM_MODEL`.
- Line 326: `if model not in PRICING:` — assumed False (test environment has `claude-haiku-4-5-20251001` in PRICING).
- Line 337: `if stage == "items":` True; `IMPACT_FIRST_ENABLED` True → `_process_items_v3(conn, limit, summary)`.
- `_process_items_v3` is monkeypatched to record into `v3_calls`. ✓
- Test assertion: `len(v3_calls) == 1` and `len(v2_calls) == 0`. ✓

### Test 2: `test_run_once_dispatches_to_v2_when_flag_disabled`

- `IMPACT_FIRST_ENABLED = False`, `stage = "items"`.
- Line 310: `(False or not False) = (False or True) = True` → `_make_client()` is called → returns `None` (mocked).
- Line 312: `if client is not None:` — False (since mock returned None), skip.
- Line 319-320: fall to `model = AI_ITEM_MODEL`.
- Line 337: `if stage == "items":` True; `IMPACT_FIRST_ENABLED` False → `_process_items(conn, client=None, limit, summary)`.
- `_process_items` is monkeypatched. ✓
- **Note:** in production, v2 with `client=None` would crash inside `_process_items` (line 363 calls `client.summarize_item(ctx)`). The test passes only because `_process_items` is mocked. **This is a test-isolation artifact, not a production bug.**

### Test 3: `test_run_once_dispatch_preserves_meeting_path`

- `IMPACT_FIRST_ENABLED = True`, `stage = "meetings"`.
- Line 310: `(True or False) = True` → `_make_client()` is called → returns `None` (mocked).
- Line 312: `if client is not None:` — False, skip.
- Line 319-320: `model = AI_ITEM_MODEL`. **Mislabel: ai_runs row records `AI_ITEM_MODEL` for a meetings run.** Test doesn't assert on the recorded model, so the test passes; production never hits this branch (real meetings client is non-None).
- Line 337: `if stage == "items":` False → `_process_meetings(conn, client=None, limit, summary)`.
- `_process_meetings` is monkeypatched. ✓
- Test assertion: `len(meetings_calls) == 1`. ✓

### Test 4: `test_run_once_v3_dispatch_does_not_construct_ai_client`

- `IMPACT_FIRST_ENABLED = True`, `stage = "items"`.
- Line 310: `(False or False) = False` → `client = None`, `_make_client` NOT called.
- Test assertion: `client_factory_calls == []`. ✓
- This is the design-choice-documenting test. If a future refactor moves `_make_client()` outside the lazy guard, this test catches it.

**All 4 tests pass for the right reasons.** The `_make_client → None` mock is overly permissive (it would allow a buggy v2 path to slip through if `_process_items` weren't also mocked), but in combination with the `_process_items` mock the tests correctly isolate dispatch logic from execution logic.

---

## AIFatalError validation — production-mode walkthrough

REQUIRED-1's surface is narrow. To confirm just how narrow, walk through every production-mode call to `run_once`:

### Scenario A: `IMPACT_FIRST_ENABLED=False`, `stage="items"` (v2 path, default state today)

- `client = _make_client()` → real `AIClient`.
- `model = client.item_model` (line 313).
- PRICING check at line 326: if `model not in PRICING`, fire `AIFatalError` with message referencing `client.item_model` and `client.meeting_model`. Both attributes exist on a real `AIClient`. **No crash.** ✓

### Scenario B: `IMPACT_FIRST_ENABLED=False`, `stage="meetings"` (v2 meetings)

- Same as A but `model = client.meeting_model`. Same outcome. ✓

### Scenario C: `IMPACT_FIRST_ENABLED=True`, `stage="items"` (v3 path post-FINAL-3)

- `client = None`.
- `model = AI_ITEM_MODEL`.
- If `AI_ITEM_MODEL` is NOT in PRICING (e.g., a fresh Anthropic release that hasn't been added to PRICING yet, or an env-var typo): fire `AIFatalError` with message `f"AI_ITEM_MODEL={client.item_model!r}, AI_MEETING_MODEL={client.meeting_model!r}"`.
- `client` is `None`. **Crash: `AttributeError: 'NoneType' object has no attribute 'item_model'`.**
- The original `AIFatalError` is never constructed; the operator sees `AttributeError` from inside the error message construction, masking the actual misconfiguration.

### Scenario D: `IMPACT_FIRST_ENABLED=True`, `stage="meetings"` (v3-flagged but meetings)

- Line 310's guard hits the LEFT side of the `or`: `("meetings" == "meetings") = True`, so `_make_client()` is called → real `AIClient`.
- Same as Scenario B. ✓

### Conclusion

Only Scenario C is at risk. The fix is trivial. The likelihood of triggering is low (PRICING is hand-maintained and changes when models change), but the failure mode (wrong exception type, message references undefined attributes) is exactly the kind that wastes 20 minutes during an incident.

Recommend either:

```python
# Option 1: bullet-proof, minimal
if model not in PRICING:
    raise AIFatalError(
        f"Model {model!r} has no entry in docket.ai.pricing.PRICING; "
        f"add per-token rates before running."
    )
```

```python
# Option 2: preserve diagnostic detail
if model not in PRICING:
    if client is not None:
        configured = (
            f"AI_ITEM_MODEL={client.item_model!r}, "
            f"AI_MEETING_MODEL={client.meeting_model!r}"
        )
    else:
        configured = f"AI_ITEM_MODEL (v3 fallback)={AI_ITEM_MODEL!r}"
    raise AIFatalError(
        f"Model {model!r} has no entry in docket.ai.pricing.PRICING. "
        f"Configured: {configured}"
    )
```

Either is acceptable; both close REQUIRED-1.

---

## Code-quality notes (NICE-TO-HAVE only)

### `_process_items_v3` style consistency with `_process_items`

The two functions have parallel structure (try/except/commit pattern, claim+loop shape) but slightly different exception-block shapes:

- v2's permanent-failure block calls `mark_item_failed(conn, ...)` (a helper) and then `conn.commit()`.
- v3's permanent-failure block opens a `with conn.cursor() as cur:` and runs the UPDATE inline.

For symmetry, a future cleanup could extract a v3 helper `mark_item_failed_v3(conn, item_id, error_message)` to mirror v2's structure. Cosmetic.

### `_AttrAccess` could be a `SimpleNamespace`

```python
class _AttrAccess:
    def __init__(self, d: dict):
        self.__dict__.update(d)
```

This is functionally identical to:

```python
from types import SimpleNamespace
_AttrAccess = lambda d: SimpleNamespace(**d)
```

The custom class adds a name + docstring, which is fine. Not worth changing.

### `pipeline._rerun_from_stage2` is being imported lazily

`conflict_resolution.py` imports `_rerun_from_stage2` and `PipelineConcurrencyError` inside the function bodies (lines 389-392, 597-600), not at module top. This avoids a circular import (services → ai → services) at module load. Comment explaining "why lazy" would help future maintainers — currently it looks like an oversight rather than a deliberate choice. NICE-TO-HAVE.

### Worker `_open_run` records model BEFORE the PRICING check could theoretically fail

Actually wait — re-reading line 326-335: the PRICING check is BEFORE `_open_run`. So a model-not-in-PRICING crash happens BEFORE any `ai_runs` row is opened. Good — no orphan run rows on misconfiguration. ✓

---

## Verification commands (for the synthesizer)

Recommended manual checks before flag-flip:

```bash
# Confirm REQUIRED-1 is fixed:
grep -n "client.item_model" src/docket/ai/worker.py
# Expected: only line 313 (under the `if client is not None:` guard).

# Confirm no dead code in conflict_resolution:
grep -nE "_DEAD_CODE|_legacy|_rerun_stage2|_get_enabled_policy_slugs|_RerunOutcome" \
    src/docket/services/conflict_resolution.py
# Expected: only docstring references at top of file (SUGGESTED-2).

# Confirm both monkeypatch sites in test_conflict_resolution.py:
grep -cE "monkeypatch.setattr.*pipeline.rewrite_item" \
    tests/integration/test_conflict_resolution.py
# Expected: 5

grep -cE "monkeypatch.setattr.*conflict_resolution.rewrite_item|conflict_mod.*rewrite_item" \
    tests/integration/test_conflict_resolution.py
# Expected: 5

# Confirm schema columns exist:
psql -c "SELECT column_name FROM information_schema.columns WHERE table_name='agenda_items' AND column_name IN ('processing_status','ai_extraction_version','ai_rewrite_version','last_error_at','last_error_message','extracted_facts','score_overrides','headline','why_it_matters')"
# Expected: all 9 rows.

# Confirm AI_ITEM_MODEL in PRICING (prevents REQUIRED-1's AttributeError path from firing):
venv/bin/python -c "from docket.config import AI_ITEM_MODEL; from docket.ai.pricing import PRICING; assert AI_ITEM_MODEL in PRICING, f'{AI_ITEM_MODEL!r} not in PRICING'"
```

---

## What did NOT need a deep review (and why)

- **pipeline.py** — reviewer #1's beat. I traced into it only to verify the `expected_status` predicate, the `PipelineConcurrencyError` raise site, and the Phase C UPDATE shape — all integration touchpoints with my scope.
- **test_pipeline_e2e.py / test_pipeline_live.py** — reviewer #1's beat. I checked only that the `_ItemView` shape used in those tests matches the worker's `_AttrAccess` and the admin's `_ItemView`.
- **Migration 013** — verified as supporting context (enum values, column existence) but not reviewed for correctness.
- **Track 1's extraction / Track 2's badge writing** — assumed correct; B5 is integration not implementation of those.

---

## Closing

The B5 integration is solid. The G4 regression suite is preserved with surgical, minimal monkeypatch additions that correctly target the new call site. The flag wiring matches the plan. The `claim_items_v3_sql` is schema-correct (the plan's `source_type` reference was wrong and the implementer caught it). The audit payload synthesis maps to the existing G4 assertions cleanly. The early-UPDATE TOCTOU guard in `edit_stage_1_facts` is preserved separately from the pipeline's atomic-extraction UPDATE — both are needed and both fire.

Ship REQUIRED-1, consider SUGGESTED-1's behavioral question explicitly, file SUGGESTED-2 and SUGGESTED-5 as follow-ups. The 17 new tests (13 e2e + 4 dispatch) plus the 45-test G4 regression contract land cleanly per the implementer's verification.

**Reviewer #2 signed off, pending REQUIRED-1 cleanup.**
