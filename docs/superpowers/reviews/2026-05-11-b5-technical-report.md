# B5 Per-Item Pipeline Orchestrator — Comprehensive Technical Report

**Phase:** 2 §B5 — atomic per-item orchestrator wiring Tracks 1+2+3
**Branch:** `release/impact-first-v3` @ `c7442e1` (5 B5 commits since `3186610`)
**Protocol run:** 16th. **Technical-report variant** (G1, G4 precedent — high architectural depth). This document replaces the standard Sonnet + auditor + 4-bullet packet with one synthesis you author the remediation plan from.

**Inputs:**
1. B5 implementation plan (post-engineer-consultant refinements baked in): `docs/superpowers/plans/2026-05-10-b5-pipeline-orchestrator.md`
2. Implementer report: 5 commits, 18 new tests passing (14 e2e + 4 dispatch), G4 regression suite intact at 45/45, full suite 1305 passed. Live smoke test skipped (no API key in env). 5 deviations from plan + 1 housekeeping cleanup.
3. Backend Opus review (322 lines): `docs/superpowers/reviews/2026-05-10-b5-opus-review-1-backend.md`
4. Integration Opus review (596 lines): `docs/superpowers/reviews/2026-05-10-b5-opus-review-2-integration.md`

---

## I. Executive summary

**Verdict:** mergeable after a focused fix-up. The architecture is sound. The TOCTOU concurrency guard from decision #13 (engineer-consultant addition) is correctly implemented and tested. The G4 regression contract holds — all 45 conflict-resolution tests pass post-refactor without modification. The cross-track contract (Stage 1 → 2 → 2.5 → reconcile → atomic Phase C with badges) is wired end-to-end and verified by 13 integration tests.

**Two findings are merge-blocking:**

1. **One test coverage gap** (backend R1) — `test_rerun_from_stage2_guard_raises_when_status_mismatch` asserts the rewrite columns rolled back but doesn't assert the inline-extraction columns (`extracted_facts`, `ai_extraction_version`) rolled back. The **code is correct** (both UPDATEs share one `with db()` transaction, the exception propagates to the rollback handler). The test is incomplete. One-line fix: add two assertions.

2. **One error-message bug** (integration R1) — `worker.py:330` PRICING-validation `AIFatalError` message dereferences `client.item_model` and `client.meeting_model`, but `client is None` on the v3 path. A misconfigured `AI_ITEM_MODEL` would raise `AttributeError` instead of the intended `AIFatalError`, masking the actual error during an incident. Four-line message-text fix.

**One architectural decision** worth your explicit attention before the fix-up commits — both reviewers caught it independently from different scopes (cross-model convergence):

**Admin paths now do silent auto-retry on reconcile.** Pre-B5, G4's `_rerun_stage2` hardcoded `reconcile_stages(..., already_retried=True)` — explicit admin re-runs were one-shot, no auto-retry. Post-B5, the admin paths delegate to `pipeline._rerun_from_stage2`, which uses `already_retried=False` on the first reconcile call. If the post-admin-override Stage 2 returns a state that trips reconcile's retry condition, **a second `rewrite_item` call fires inside the same admin click**, doubling LLM cost and latency on the sad path.

This is the **most consequential semantic change** in B5. The current behavior is consistent with the worker's happy path (both use `already_retried=False`), which is arguably the right "convergence" outcome. But it changes what happens when an admin clicks "Re-prompt Stage 2" with their carefully-crafted override and reconcile says "I generated my own override, retry with mine." Three plausible takes:

- **(a) Accept the new behavior.** Admin = worker semantics. Document the cost implication.
- **(b) Add a parameter** to `pipeline._rerun_from_stage2` (e.g., `already_retried: bool = False`). Admin paths pass `True` to preserve pre-B5 semantics. Worker keeps default.
- **(c) Hardcode admin paths to skip retry** by passing `already_retried=True` explicitly from `services/conflict_resolution.py`. No new parameter; the admin-vs-worker policy lives in the call site.

Backend SUG-1 and Integration SUGGESTED-1 both surfaced this. Backend recommended (b) or (c); Integration recommended (b) — adding a parameter. **You decide.**

**Tests:** 18 new B5 tests pass (14 e2e + 4 dispatch — beat the plan's 17 projection by one). G4 regression: 45/45. Full suite: 1305 passed + 4 xfailed (was 1287 pre-B5 + 17-test guard delta + 1 extra = 1305 ✓). Live smoke test: skipped (no API key). **No real regressions.**

**Deviations:** all 5 implementer deviations verified as correct by the relevant reviewer. The two that mattered architecturally — `source_type` column doesn't exist (plan bug); `persist_extraction` replaced with inline UPDATE (necessary for decision #13 to work) — both confirmed sound.

**Estimated remediation diff:** ~30 lines code + ~10 lines test if you take the recommended path. Single fix-up commit.

---

## II. Findings by severity

### REQUIRED (2, both in scope for the fix-up)

**R1 (Backend): test coverage gap on `extracted_facts` / `ai_extraction_version` rollback**

`tests/integration/test_pipeline_e2e.py` — `test_rerun_from_stage2_guard_raises_when_status_mismatch`.

The test verifies that on `PipelineConcurrencyError` raise:
- `final["headline"] is None` ✓
- `final["processing_status"] == "pending"` ✓
- `_read_badges(iid) == []` ✓

But doesn't verify that the inline extraction UPDATE rolled back:
- `final["extracted_facts"] is None` — missing
- `final["ai_extraction_version"] is None` — missing

The code is correct: pipeline.py's Phase C runs both UPDATEs inside one `with db() as conn:` block, so the `PipelineConcurrencyError` raised after the second UPDATE's `cur.rowcount == 0` check propagates through the context manager's `__exit__` which rolls back the entire transaction (including the first UPDATE). The reviewer traced this through `docket.db.db()`'s exception-rollback contract and confirmed.

But a future refactor that splits Phase C into two transactions (e.g., to allow Stage 1's persistence to survive Stage 2 failure — see plan decision #4 alternative) would silently break decision #13's atomicity unless this test catches it. The test should pin the contract.

**Fix:**
```python
# After the existing assertions:
assert final["extracted_facts"] is None, (
    "inline extraction UPDATE must also roll back on guard-fire"
)
assert final["ai_extraction_version"] is None, (
    "ai_extraction_version write must also roll back on guard-fire"
)
```

Two lines of test.

**R2 (Integration): `AIFatalError` message dereferences `None` on v3 path**

`src/docket/ai/worker.py:330` (approx; in the PRICING-validation block). The error-handling code looks something like:

```python
if not is_valid_pricing(...):
    raise AIFatalError(
        f"Missing PRICING for {client.item_model} or {client.meeting_model}"
    )
```

On the v3 path (`IMPACT_FIRST_ENABLED=True` + `stage="items"`), Step 2.4e's lazy construction sets `client = None`. The PRICING-validation block still runs (the check happens regardless of v2/v3 path), so the f-string evaluates `None.item_model` and raises `AttributeError` BEFORE the intended `AIFatalError` is constructed.

Operator impact: an operator misconfigures `AI_ITEM_MODEL` (e.g., bumps to a not-yet-priced Haiku 4.6), the worker fires, and Sentry/Healthchecks see `AttributeError: 'NoneType' object has no attribute 'item_model'` instead of `AIFatalError: Missing PRICING for claude-haiku-4-6-...`. Misleading at exactly the moment the operator is debugging an incident.

**Fix:** thread the configured model names through, not the client's attributes:

```python
from docket.config import AI_ITEM_MODEL, AI_MEETING_MODEL  # may already be imported

if not is_valid_pricing(...):
    raise AIFatalError(
        f"Missing PRICING for {AI_ITEM_MODEL} or {AI_MEETING_MODEL}"
    )
```

Four lines (or fewer; just an import + a message change).

### Architectural decision — author's explicit call

**A1: `already_retried` behavior on admin paths**

Both reviewers independently flagged this. Backend SUG-1 frames it as "admin paths now do silent auto-retry on reconcile." Integration's analysis is more concrete:

> "Pre-B5 the admin paths called `reconcile_stages(..., already_retried=True)` — always suppressing the auto-retry. Post-B5 the admin paths call `pipeline._rerun_from_stage2` which uses `already_retried=False`. If the post-admin-override Stage 2 rewrite returns `is_substantive` in a way that trips reconcile's `retry_stage2_with_override` branch, a second `rewrite_item` call fires inside the same admin click — doubling LLM cost and latency for that single admin action."

The most visible test case for this behavior change is `test_re_prompt_stays_in_conflict_when_rerun_still_procedural` (which already passes): the mock returns `is_substantive=False` regardless of the admin's instruction. Reconcile sees substantive Stage 1 facts vs procedural Stage 2 → fires retry → mock returns procedural again → second reconcile with `already_retried=True` marks `cross_stage_conflict`. **Two LLM calls per admin click for what was one click pre-B5.**

The product question: when an admin invokes "Re-prompt Stage 2" with their override, should the reconcile auto-retry path fire?

**Arguments for accepting the new behavior (A1-a):**
- Consistent with the worker's happy path — both worker and admin go through identical pipeline logic
- The retry uses reconcile's machine-generated override, which is specifically designed to push Stage 2 toward "yes this is substantive given the Stage 1 facts" — exactly what the admin wanted in the first place
- Doubling cost only happens on the sad path (admin's override didn't produce a substantive verdict either) — those are the cases where one more shot might genuinely help
- Simpler API surface

**Arguments for preserving pre-B5 semantics (A1-b/c):**
- Admin's override is presumably more informed than reconcile's machine-generated one. Reconcile re-running with its own override may undermine the admin's intent.
- Cost predictability: admin clicks → exactly one LLM call. Easier to reason about.
- The pre-B5 behavior was explicit (G4 hardcoded `already_retried=True`). The post-B5 change is implicit (a side-effect of the refactor). If we accept it, accept it explicitly.

**Recommendation (the most honest framing):** the change happened by accident in the refactor; the decision should be made deliberately. Implementing path (b) — add the parameter — costs ~5 lines and lets both admin paths pass `already_retried=True` explicitly. This makes the policy choice visible at the call site rather than hidden in `_rerun_from_stage2`'s body.

**Your decision determines whether the fix-up touches `pipeline.py` (adds parameter) and `conflict_resolution.py` (passes `True` at both call sites).**

### SUGGESTED (10 across both reviews — author's call which to bundle)

**SUG-2 (Backend, frontend-of-test): test docstring stale.** `test_process_item_e2e_extracted_facts_persisted_via_persist_extraction` — name + docstring reference `persist_extraction`, but the implementation uses an inline UPDATE post-deviation #2. Either rename or update the docstring. Two-line doc fix.

**SUG-3 (Backend): idempotency test missing return-value pin.** The idempotency test asserts `badges_first == badges_second` but doesn't pin the second `process_item` call's return value. A future "skip if already completed" short-circuit would silently change the contract without the test catching it. Add `assert pipeline.process_item(item2) == "completed"` and `assert final["headline"] == _substantive_rewrite().headline`.

**SUG-4 (Backend): live smoke test brittle vs LLM stability.** Asserts `"sole_source" in slugs`. Defensive alternative: `assert "sole_source" in slugs or "emergency_action" in slugs`. Acceptable as-is if the test is treated as a deliberate canary; flag-of-choice.

**SUG-5 (Backend): plan file still references `persist_extraction`.** Plan §659, §696, §1543 reference `persist_extraction(cur, ...)` in pseudocode and prose. After deviation #2, the plan and implementation diverge. Either add a "Deviation #2 appendix" at the top of the plan pointing at the implementer report, or update the pseudocode inline. Doc-only.

**SUGGESTED-2 (Integration): stale module docstring in `conflict_resolution.py`.** Module-level docstring still references the deleted `_rerun_stage2` helper. Doc fix.

**SUGGESTED-3 (Integration): meeting-path `model = AI_ITEM_MODEL` mislabel.** In the lazy-construction edge case (`stage="meetings"` + `client=None` mock), the run-log records `AI_ITEM_MODEL` even though it's a meetings batch. Test-only artifact; real production constructs the client for meetings unconditionally.

**SUGGESTED-4 (Integration): `claim_items_v3_sql` lacks deterministic ordering across parallel workers.** ORDER BY `ai.id` is deterministic at the SQL level but doesn't guarantee disjoint sets across parallel workers without coordination. The `FOR UPDATE SKIP LOCKED` clause handles disjointness; the ORDER BY is for predictability. Worth a comment noting this isn't a fairness/round-robin contract.

**SUGGESTED-5 (Integration): cost telemetry gap (decision #10).** `summary.cost_usd = 0.0` for v3-only batches. Documented; needs Grafana audit before FINAL-3 flips the flag. **Operational, not code.**

**SUGGESTED-6 (Integration): `municipality_id` vs `city_id` naming inconsistency.** `_load_conflict_item` returns `municipality_id`; pipeline expects `item.city_id`. The `_ItemView` adapter translates. Defer cleanup.

**Audit payload sparseness (Integration's secondary):** post-B5 audit no longer carries `served_model` / `is_substantive`. No test asserts these keys (so the regression contract holds), but an operator debugging a resolution outcome loses visibility into "which model served this." Operational follow-up.

### NICE-TO-HAVE (~8 across both reviews — defer)

Backend N1 (logging granularity gaps), N2 (`raw_text` default in `_load_item`), N3 (`persist_extraction` split as Phase 4 cleanup), N4 (city_id naming — overlaps integration SUGGESTED-6). Integration's NICE-TO-HAVE block adds polish items around `_AttrAccess` adapter shape + dispatch test parametrization. All defer.

---

## III. Architectural concerns (cross-cutting themes)

Three patterns the per-finding view doesn't reveal.

### Theme 1: Behavioral convergence at the cost of operational predictability

The B5 refactor's most consequential side-effect is the admin path now sharing semantics with the worker path on reconcile-retry behavior (A1 above). Both reviewers caught it independently. It's not a bug — it's a deliberate architectural property of the refactor, just one the plan didn't explicitly choose. The question is whether the convergence is desirable.

The argument for is consistency: one code path, one set of semantics, easier maintenance. The argument against is that admin actions historically have different cost/latency expectations than worker batches. Cost predictability matters for trust in the admin UI.

**This is fundamentally a product call**, not a technical one. Document the decision explicitly in the fix-up.

### Theme 2: Plan-vs-implementation drift is concentrated in two spots

The plan diverged from reality in two specific places:
1. **`source_type` column** — assumed to exist, doesn't. Plan bug.
2. **`persist_extraction` side-effect** — plan didn't know the helper flips `processing_status`. Plan/code drift relative to Track 1's design.

Both were caught and adapted by the implementer cleanly. The plan should be patched post-hoc (SUG-5) so the file accurately describes what shipped. Pattern: when a plan's pseudocode imports a helper, the planner should grep the helper's actual signature AND side-effects, not just transcribe from earlier plans. Forward-applicable lesson for any future plan touching `persist_*` / `mark_*` / `flush_*` named helpers — those names often carry hidden state mutations.

### Theme 3: Cost telemetry is a known v1 gap that needs operational follow-up

Decision #10 in the plan explicitly accepted that v3 batches won't have per-item cost detail (`summary.cost_usd = 0.0`). This was an intentional scope choice for B5 v1. But:

- **Grafana / Healthchecks** dashboards may alert on zero-spend anomalies for `ai_items` runs
- **Operators** will see "$0.00 cost" in `ai_runs` post-flag-flip
- **Budget gate** (`AI_DAILY_BUDGET_USD`) is monitored against these costs

Before FINAL-3 flips `IMPACT_FIRST_ENABLED=true` in production: audit alerting rules + dashboards, temporarily mute zero-spend alerts on `ai_items`, OR backfill the usage threading (~4-file refactor: extraction.py, rewrite.py, pipeline.py, worker.py). Out of B5's scope but blocking FINAL-3.

---

## IV. Recommended remediation strategy

Strawman for the fix-up commit. **Not prescriptive — you author the actual plan.**

**Required (in scope):**
- **R1**: add two assertions to `test_rerun_from_stage2_guard_raises_when_status_mismatch`. Two lines of test code.
- **R2**: replace `client.item_model` / `client.meeting_model` in the worker.py PRICING-validation `AIFatalError` message with `AI_ITEM_MODEL` / `AI_MEETING_MODEL`. ~4 lines (including import if needed).

**A1 architectural decision (choose one):**
- **(a) Accept new behavior + document.** No code change. Add a `## Behavior changes from G4` section to the conflict_resolution.py module docstring noting the auto-retry.
- **(b) Add `already_retried` parameter to `pipeline._rerun_from_stage2`** (default False). Admin paths in conflict_resolution.py pass `already_retried=True` at both call sites. ~5 lines pipeline.py + ~2 lines conflict_resolution.py. **Recommended** because it makes the policy choice visible.
- **(c) Hardcode admin paths to pass `already_retried=True`** by ... wait, that requires the parameter to exist, which is option (b). So (c) collapses into (b).

**Recommended bundle (Theme 2 — doc fixes):**
- SUG-2 (test docstring stale), SUG-5 (plan still references persist_extraction), SUGGESTED-2 (module docstring stale). Three doc fixes, ~10 lines total.

**Recommended bundle (Theme 3 — operational pre-FINAL-3):**
- File task #52 (or equivalent): audit Grafana zero-spend alerts before FINAL-3 flip.
- Optional: ship `usage` threading as a separate non-B5 commit. Not in B5's fix-up scope.

**Optional polish (defer if budget tight):**
- SUG-3: idempotency test return-value pin (+1 line test)
- SUG-4: live test defensive assertion (+2 lines test)
- SUGGESTED-3: meeting-path `model` mislabel — test-only, can defer
- SUGGESTED-4: claim_items_v3_sql ordering comment — defer
- SUGGESTED-6: municipality_id vs city_id naming — defer

**Deferred (out of scope for B5 fix-up):**
- All NICE-TO-HAVE
- Cost telemetry threading (separate commit/task)
- `persist_extraction` split (Phase 4 cleanup)

**Estimated fix-up diff:** ~15-25 lines of code + test, depending on A1 choice. Single commit.

**Suggested commit message** (assuming A1 = b):

```
fix(pipeline): B5 review fix-up — test coverage + error-message + already_retried

Per the comprehensive technical report (2026-05-11-b5-technical-report.md):

- R1 (backend test coverage): test_rerun_from_stage2_guard_raises_when_
  status_mismatch now asserts extracted_facts AND ai_extraction_version
  rolled back. Pins decision #13's full Phase-C atomicity contract.

- R2 (worker error message): worker.py PRICING-validation AIFatalError
  message references AI_ITEM_MODEL / AI_MEETING_MODEL from config
  instead of client.item_model / client.meeting_model. Fixes
  AttributeError-masking-AIFatalError on the v3 lazy-client path.

- A1 (architectural — already_retried semantics): pipeline._rerun_from_
  stage2 now accepts already_retried: bool = False. services.conflict_
  resolution's admin paths (re_prompt_stage_2, edit_stage_1_facts) pass
  already_retried=True to preserve G4's pre-refactor one-shot semantics
  on admin clicks. Worker path keeps the default (False) for auto-retry.
  Makes the worker-vs-admin policy choice visible at the call site.

Doc fixes: stale module docstring in conflict_resolution.py; stale test
docstring referencing persist_extraction in test_pipeline_e2e.py; plan
file deviation-#2 appendix.

Deferred (per technical report §IV): cost telemetry threading,
persist_extraction split, municipality_id vs city_id naming
inconsistency, idempotency test return-value pin, live test
defensive assertion, claim_items_v3_sql ordering comment.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## V. Cross-model convergence

One strong convergence pair:

**Both reviewers caught the `already_retried` behavior change from different scopes.** Backend SUG-1 framed it as "admin paths now do silent auto-retry"; Integration's narrative analysis (SUGGESTED-1) traced the specific code path and showed the doubling-cost-on-sad-path implication. Same finding, two independent perspectives. Strong signal of a real semantic concern, not noise.

The convergence reinforces: this is not just one reviewer's preference but a structural concern about the refactor's effect on admin operational predictability. Strong case for surfacing it as an explicit decision (A1).

No other convergences. The two REQUIRED findings live in different files and different aspects (test coverage gap vs error message bug). The SUGGESTED items don't overlap between reviewers.

---

## VI. Verified-correct (audit trail)

Both reviewers explicitly verified these items:

- **Decision #13 concurrency guard correctness:** the `expected_status` predicate fires on both call sites (worker via `None`, admin via `'cross_stage_conflict'`). The `with db()` exception-rollback chain holds because both UPDATEs share one transaction context.
- **Decision #92 city_id:** both process and policy badge INSERTs include `city_id`.
- **Decision #45 reconcile semantics:** first reconcile call is `already_retried=False`, retry-after-override is `already_retried=True`. Confirmed in `pipeline.py`.
- **G4 regression contract:** all 45 existing G4 tests pass without modification. The 5 monkeypatch additions cover both old and new call sites; no test silently passes via never-fired mock.
- **`source_type` column doesn't exist** — confirmed via grep of migrations 001-016. Implementer's `"agenda"` default is correct.
- **`persist_extraction` flips status as side-effect** — confirmed by reading `src/docket/ai/extraction.py:206`. Inline UPDATE workaround is necessary and correctly preserves behavioral parity (same Pydantic model_dump + version column write).
- **Lazy AIClient construction** — correct for v3 path; `AI_ITEM_MODEL` fallback fires only when client is None. (Except the worker.py:330 message-text bug — R2.)
- **Pipeline atomic Phase C** — extraction inline UPDATE + main UPDATE + badge INSERTs all share one `with db()` block. Exception-rollback chain confirmed.
- **`_AttrAccess` adapter shape** — matches `claim_items_v3_sql`'s SELECT column order; handles None columns gracefully.

---

## VII. Open questions for the user (non-binary judgment calls)

These are decisions the technical report can't make for you. Your remediation plan should answer each.

**Q1. A1 architectural decision: which path on `already_retried`?**
- (a) Accept the new auto-retry. Document. Zero code change.
- (b) Add `already_retried` parameter. Admin paths pass `True`. ~7 lines total.
- (c) [collapses into (b)]

**Q2. Doc-fix bundle scope.** Three stale docs (SUG-2, SUG-5, SUGGESTED-2). Take all three or just the most important? Recommend all three — total ~10 lines.

**Q3. Idempotency + live test polish (SUG-3 + SUG-4).** Cheap inclusions (~3 lines total) that tighten existing tests. Take them or defer to a follow-up?

**Q4. Cost telemetry follow-up timing.** File now as task #52, ship before FINAL-3? Or bundle into B5 fix-up (significant scope creep, ~4 files)?

**Q5. Plan file deviation appendix (SUG-5).** Update the plan file itself to note the post-implementation deviations (`source_type`, `persist_extraction`), or leave the plan as a historical artifact pointing at the implementer report? Recommend updating — future readers will appreciate not having to cross-reference reports.

---

## VIII. Implementer deviation review (final disposition)

Recap of the implementer's 5 deviations + 1 housekeeping:

1. **`source_type` column doesn't exist** — Reviewer-verified correct. Plan bug. **Accept as-shipped.** (Plan update recommended per SUG-5.)
2. **Inline UPDATE for extraction instead of `persist_extraction`** — Reviewer-verified correct and necessary for decision #13 to work. **Accept as-shipped.** Behavioral parity confirmed (same JSONB + version column). Open question on whether to split persist_extraction into two functions is a Phase 4 follow-up, not a B5 issue.
3. **5 G4 tests + second monkeypatch on `docket.ai.pipeline.rewrite_item`** — Reviewer-verified correct. All 5 sites properly cover both old and new call paths. **Accept as-shipped.**
4. **Audit payload preservation via post-pipeline read-back + synthesized `reconcile_action`** — Reviewer-verified correct. Mapping (`completed → "accept"`, else → `"mark_cross_stage_conflict"`) matches G4 test assertions. No test asserts on dropped keys (`served_model`, `is_substantive`). **Accept as-shipped.** Audit-payload visibility loss is a SUGGESTED follow-up but not a regression.
5. **`run_once` lazy AIClient + `AI_ITEM_MODEL` fallback** — Reviewer-verified mostly correct. **Accept as-shipped** EXCEPT for the worker.py:330 PRICING-validation message bug (R2).
6. **`_DEAD_CODE_REMOVED` stub** — Reviewer-verified zero matches. Cleanup complete. **Accept as-shipped.**

---

## IX. Summary table

| Class | Count | In scope for fix-up |
|---|---|---|
| REQUIRED | 2 | Both (~6 lines) |
| Architectural decision | 1 (A1) | User authors (~7 lines if path b) |
| SUGGESTED — Theme 2 (doc fixes) | 3 (SUG-2 + SUG-5 + SUGGESTED-2) | Recommended (~10 lines) |
| SUGGESTED — other | 7 | Defer / author's call |
| NICE-TO-HAVE | ~8 | Defer |
| Operational follow-up (Theme 3) | 1 (Grafana audit) | File as task #52; do before FINAL-3 |

**Estimated fix-up diff:** 15-25 lines code + test, single commit.

After the fix-up: push `release/impact-first-v3` to origin and open the PR to `main`. The integration branch becomes the canonical "v3-pipeline-shipped" merge candidate. FINAL-1 (deploy with flag off) → FINAL-3 (flip flag) per the existing plan.

---

*End of report. Author your remediation plan as a free-form response (not constrained to bullet decisions); the implementer applies it as a single fix-up commit. Memory + push + PR follow.*
