# G4 Cross-Stage Conflict Resolution — Comprehensive Technical Report

**Phase:** 2 Track 3 §G4 — admin UI for items in `processing_status='cross_stage_conflict'`
**Branch:** `feat/impact-first-phase-2-track-3` @ `8dcd406` (7 G4 commits)
**Protocol run:** 15th. Technical-report variant (G1 precedent) — replaces Sonnet second-look + final auditor + 4-bullet packet with this synthesis. **You author a remediation plan directly from this document; the implementer applies it as a single fix-up commit.**

**Inputs:**
1. G4 implementation plan: `docs/superpowers/plans/2026-05-10-g4-cross-stage-conflict-resolution.md` (with two Gemini-driven mid-flight refinements: D6 HTMX 4xx UX + D12-13 TOCTOU guards)
2. Implementer's report: 7 commits, 42 G4 tests, 1164 full-suite passing (after the manual FK fix described below). Four reasonable deviations from the plan (`get_enabled_policy_slugs` shim, `apply_score_floors` signature drift, `updated_at` column missing, TOCTOU audit-row commit ordering).
3. Backend Opus review (626 lines): `docs/superpowers/reviews/2026-05-10-g4-opus-review-1-backend.md`
4. Frontend Opus review (467 lines): `docs/superpowers/reviews/2026-05-10-g4-opus-review-2-frontend-ux-auth.md`
5. Pre-existing local-DB anomaly surfaced during reviews — see §VII below; not a G4 issue but G4-adjacent.

---

## I. Executive summary

**Verdict:** mergeable after a focused fix-up commit. The architecture is sound — the LLM call runs strictly outside any held DB transaction, `_rerun_stage2` is correctly minimal (B5-cleanable), `already_retried=True` is correct in both call sites, all four LATE persistence UPDATEs in the LLM-touching paths carry the TOCTOU predicate, and the audit-then-commit-then-raise ordering correctly handles psycopg2's rollback-on-exception semantics. HTMX 4xx UX (decision #6) is verbatim across the three form templates; the `.form-error` span lives inside the form so the on-error swap doesn't lose it.

**Three findings are merge-blocking:**

1. **One missed UPDATE** — `edit_stage_1_facts` has a fifth UPDATE statement (the early `extracted_facts` write before the LLM call) that the plan implicitly covered under decision #12 but the code doesn't guard. Under READ COMMITTED, a concurrent admin who resolves between `_load_conflict_item` and that early UPDATE will see the **completed row's `extracted_facts` silently overwritten**. The implementer's inline comment frames this as a "tradeoff" with the wrong consequence model. Three-line fix; bonus: catching the race before the LLM call saves the API spend.

2. **One missed try/except** — `re_prompt_stage_2`'s defensive `StructuredFacts.model_validate` against stored JSONB raises `pydantic.ValidationError` on drift, which escapes past the route's `ConflictValidationError` handler → bubbles to a 500 instead of the documented 400. `edit_stage_1_facts` got this right; `re_prompt_stage_2` was missed. Five-line fix.

3. **One missed token rename** — `var(--mono, …)` doesn't exist; the actual editorial design system token is `--font-mono` (used at six pre-G4 call sites). Two file locations: `tweaks.css:317` and `_conflict_form_edit_facts.html:17`. Cosmetic but visible — admin-machine browsers without JetBrains Mono installed render the JSON in `ui-monospace` while every other monospace element on the page renders in IBM Plex Mono. Same drift class as G3's `--surface-2/--border/--muted` finding.

**The architectural concerns** (covered in §III) are larger than these three findings. The race-condition cluster (R1 + Backend-S1 + Frontend-S1) reveals that decision #12's prose understated the problem — `accept_stage_*` paths are also race-prone under READ COMMITTED, contrary to the plan's claim. The asymmetry cluster (R2 + Backend-S5 + Backend-N5) reveals copy-evolved-but-not-backported patterns between `re_prompt_stage_2` and `edit_stage_1_facts`. Both clusters are worth a holistic remediation rather than per-finding patches.

**Tests:** 42 G4 tests pass (vs plan's projected 41). The test suite covers happy path + still-conflicting reconcile path + TOCTOU race-loss for both LLM-touching actions, with a clever `monkeypatch` that flips status to `completed` from inside the `rewrite_item` mock. Two regression tests are recommended for the fix-up: one for R1 (silent `extracted_facts` overwrite), one for the missed-Pydantic-wrap branch.

**Migrations:** none required for G4 itself. All schema is from migration 013. Pre-existing FK drift on `agenda_item_badges_audit` (G3's migration 016 was recorded as applied but not actually applied at the constraint level) was discovered during G4 review and manually fixed; root cause investigation is a separate follow-up.

---

## II. Findings by severity

### REQUIRED (3, all in scope for the fix-up)

**B-R1 (Backend): `edit_stage_1_facts` early `extracted_facts` UPDATE missing TOCTOU predicate → silent data corruption on lost race**

`src/docket/services/conflict_resolution.py:580-591`. The function does work in two transactions split by the LLM call:
- Tx 1: load item (filter on status='conflict') → UPDATE `extracted_facts` (no status filter)
- LLM call (no DB held)
- Tx 2: late UPDATE with status filter, rowcount check, race-loss audit, raise

A concurrent `accept_stage_2` (or `accept_stage_1`) that commits between `_load_conflict_item` and the early UPDATE **will** see its just-set `extracted_facts=NULL` (or just-preserved facts) clobbered by Admin A's losing-race edit. The late UPDATE then correctly fires the 0-rowcount path and returns 409 to Admin A — but Admin B's now-`completed` row is corrupted in the database.

The implementer's inline comment at L610-618 documents the consequence as "silently affected 0 rows" — that's what a TOCTOU-guarded UPDATE would do. The actual UPDATE only filters on `WHERE id = %s`, so it affects 1 row regardless of status. The mental model and the SQL diverged.

Fix: add `AND processing_status = 'cross_stage_conflict'::processing_status_enum` to the early UPDATE; check `cur.rowcount == 0` before the LLM call; on 0, write the lost-race audit and raise — saving the LLM spend on a known-lost race in addition to closing the corruption window.

**B-R2 (Backend): `re_prompt_stage_2` Pydantic call not wrapped → 500 on stored-JSONB drift**

`src/docket/services/conflict_resolution.py:413`. The bare `StructuredFacts.model_validate(item["extracted_facts"])` raises `pydantic.ValidationError`, which escapes past the route's `except conflict_svc.ConflictValidationError` clause. The implementer's docstring at L407 says "If the JSONB drifted, this surfaces it cleanly" — code disagrees with prose.

`edit_stage_1_facts` at L573-577 wraps the same call in try/except and raises `ConflictValidationError` (route returns 400). Apply the same pattern to `re_prompt_stage_2`.

**F-R1 (Frontend): CSS token drift — `var(--mono)` doesn't exist; real token is `--font-mono`**

`src/docket/web/static/tweaks.css:317` and `src/docket/web/templates/admin/_conflict_form_edit_facts.html:17`. The editorial design system declares `--font-mono` (`styles.css:42`) and uses it at six pre-G4 sites. G4 invented `var(--mono, ui-monospace, …)`.

The fallback chain still produces a monospace face (the browser falls through `ui-monospace, "JetBrains Mono", monospace`), so the visual outcome is "monospace, but skipping IBM Plex Mono entirely." On admin machines without JetBrains Mono installed, the JSON cells and the textarea render in `ui-monospace` (system mono) while every other monospace element on the same page renders in IBM Plex Mono — a visible inconsistency.

This is the same class of drift as G3's `--surface-2/--border/--muted` finding from the G3 review packet. The G4 plan's review-checklist line ("verify G4's CSS uses the established `--paper-2/--rule/--ink-3/--mono` tokens") even propagated the wrong assumption — both the implementer and the packet author wrote `--mono` when the actual token is `--font-mono`. Project-wide pattern recurrence; see §V.

Fix: `s/var(--mono,/var(--font-mono,/g` across the two locations.

### SUGGESTED (9 — author's call which to bundle into the fix-up)

**B-S1 (Backend): `accept_stage_*` paths are also race-prone under READ COMMITTED — plan's decision #12 prose is wrong**

`src/docket/services/conflict_resolution.py:194-228, 259-291`, plus `_load_conflict_item:125-157`. Plain `SELECT` does not lock the row. Two concurrent admins doing `accept_stage_1` with different manual headlines: both pass `_load_conflict_item`, both UPDATE successfully, later writer silently wins. No audit-trail signal that there were competing edits. The window is microseconds (no LLM between SELECT and UPDATE), so the race is rare in practice — but the plan's claim ("clean LookupError → 404 for the loser") isn't what the code delivers.

Cheap fix: add `FOR UPDATE` to `_load_conflict_item`'s SELECT, OR add the same TOCTOU predicate to all four `accept_stage_*` UPDATEs and check rowcount. `FOR UPDATE` is one line. The dual-`accept_stage_2` case is idempotent so it's harmless; the dual-`accept_stage_1` case is the real (rare) hazard.

**B-S2 (Backend): still-conflicting branch writes `score_overrides` JSONB but not the underlying `significance_score`/`consent_placement_score` columns**

`src/docket/services/conflict_resolution.py:462-473, 642-651`. When `_rerun_stage2` returns `mark_cross_stage_conflict`, the JSONB is refreshed with new `final_significance`/`final_consent` but the table columns are not. JSONB and column become inconsistent. Citizen-facing rendering is shielded (the row stays at `cross_stage_conflict`, which dispatches to the verification-pending card variant), but admin-side and replay-from-audit consumers see drift. Cheap to fix; also write the columns in the still-conflicting branch.

**B-S3 (Backend): `reason` validation is inconsistent between `accept_stage_2` (raises) and `edit_stage_1_facts` (silently truncates)**

`accept_stage_2:251-257` raises `ConflictValidationError` if `len(reason) > REASON_MAX`; `edit_stage_1_facts:570-571` silently truncates with `[:REASON_MAX]`. Pick one. Recommend raising consistently — silent truncation hides admin intent and makes the behavior surprising on the rare overflow case.

**B-S4 (Backend): `ai_generated_at` listing-sort substitution has a semantic mismatch for `accept_stage_1` resolutions** (this is the substantive form of implementer-deviation #3)

`src/docket/services/query.py:2054`. `agenda_items` has no `updated_at` column; the implementer substituted `ai_generated_at`. `accept_stage_1` doesn't run AI, so the column doesn't update. The row falls out of the listing on resolution (status flips to `completed`), so the secondary sort impact is mostly moot — but if a row entered `cross_stage_conflict` via Wave 0 without ever running v3 Stage 2, `ai_generated_at` is NULL and the row sinks under `NULLS LAST`. Unlikely in production (cross_stage_conflict is reached via reconcile, which means Stage 2 ran), but worth noting.

Cleanup options if you decide to fix: (a) add `agenda_items.updated_at` populated by trigger, OR (b) sort by latest `processing_status_audit.occurred_at`. Both over-engineered for v1; flag for B5 or a future migration.

**B-S5 (Backend): success-branch audit payloads on LLM-touching paths don't carry the actual values written**

`conflict_resolution.py:511-518, 688-694`. Payloads carry `override_instruction` / `new_facts_json` (admin input) + `reconcile_action` + `conflicts` + `served_model` + `is_substantive`, but NOT the `headline`, `why_it_matters`, `final_significance`, `final_consent` actually written to the row. Replay-from-audit needs to re-run the LLM to reconstruct post-action state. Asymmetric with `accept_stage_1` which DOES include the values. Cheap fix: add four extra fields per JSONB row.

**B-S6 (Backend): anthropic SDK exceptions return 500, not the documented 503**

`src/docket/web/admin.py:1009-1027, 1051-1075`. The plan and the service docstring claim `re_prompt_stage_2` "Bubbles up `AIBudgetExceeded` / `AITransientError` from the API call." `AIBudgetExceeded` doesn't exist (only `worker.BudgetExceededError`, internal). And `rewrite_item` calls `anthropic_client.messages.create()` directly with no wrapping, so transient API errors propagate as raw `anthropic.APIConnectionError` / `RateLimitError` / `InternalServerError` → Flask 500.

Fix options: wrap the LLM call in `_rerun_stage2` with try/except → service-level `ConflictRewriteUnavailable` → route maps to 503 + flash. OR document the 500 as acceptable for v1 admin workflows (but update the docstring to match).

**F-S1 (Frontend): Accept Stage 2 direct-submit form has no `hx-on:htmx:response-error` + `.form-error` pair → silent failure on race-loss 4xx**

`src/docket/web/templates/admin/review_conflicts.html:97-104`. The Accept Stage 2 affordance is a one-click form; it doesn't go through the form-expander step that the other three actions use, so it has no decision-#6 error-surfacing pair. On a TOCTOU race (another admin resolved first), the route returns 404 + plain-text body — HTMX 1.x silently ignores it; the admin sees nothing. They click again and STILL see nothing.

Cheapest fix (3 lines): add a `<span class="conflict-flash form-error" role="alert"></span>` after the form (still inside the actions cell) and route the response text into it. Mirrors the inline-form pattern.

**F-S2 (Frontend): audit rest of `.conflict-queue` CSS tokens while fixing F-R1**

`src/docket/web/static/tweaks.css:307-380`. Quick audit confirms all other token references (`--rule`, `--paper-2`) are correct. Just F-R1 needs the rename. (Recorded for completeness.)

**F-S3 (Frontend): listing template hard-codes "Stage 2 — Verdict: PROCEDURAL"**

`src/docket/web/templates/admin/review_conflicts.html:76-88`. Template assumes every `cross_stage_conflict` has Stage 2 saying procedural — true today (every reconcile reason in `reconcile.py` has the shape "Stage1=substantive vs Stage2=procedural") but it's a hidden contract dependency. If a future reconcile decision introduces conflicts in the other direction, the template would render "Verdict: PROCEDURAL" while `agenda_items.headline` is non-NULL — falsehood. Cheap fix (4 lines): drive the label from `{% if item.headline %}`. The helper already SELECTs both columns.

### NICE-TO-HAVE (~26 across both reviews — defer)

Mixed int/float in score-override JSONB payloads (B-N1); race-loss edge case if row was deleted (B-N2 — essentially impossible in production); 3-table join wasteful for `accept_stage_*` (B-N3); empty-dict vs None payload semantics (B-N4); `re_prompt_stage_2` doesn't accept `reason` kwarg (B-N5 — asymmetry vs `edit_stage_1_facts`); module-level import placed mid-file in `admin.py` (B-N6); unused `Literal` import (B-N7); test gap on score-overrides JSONB content (B-N8); `<time datetime>` not used in listing (F-N1); raw enum strings for conflict reasons (F-N2); GET `_form/re-prompt` vs POST `re-prompt-stage-2` URL asymmetry (F-N16); 3 form-expander GETs lack explicit anonymous-redirect tests (F-N17 — inherited from same hook so coverage is architectural). All of these are documented in the source reviews; none warrant the fix-up commit.

---

## III. Architectural concerns (cross-cutting themes)

The per-finding view misses three patterns the synthesis reveals.

### Theme 1: Race-condition model is incomplete

The plan's decision #12 protected the four LATE persistence UPDATEs in `re_prompt_stage_2` and `edit_stage_1_facts`, AND explicitly waived `accept_stage_*` from needing protection ("both run a single short transaction that locks the row briefly"). Both halves of that decision are partially wrong:

- **The waive is wrong.** Plain SELECT under READ COMMITTED doesn't lock; two `accept_stage_1` calls on the same item can both proceed and the loser's headline is silently overwritten (B-S1).
- **The protection has a gap.** `edit_stage_1_facts` has a FIFTH UPDATE — the early `extracted_facts` write — that decision #12 implicitly should cover ("every persistence UPDATE in these two paths") but doesn't (B-R1).
- **The frontend has a gap.** The Accept Stage 2 button has no error-surface for the race-loss 4xx that decision #12 produces (F-S1).

Holistic remediation: extend decision #12 to "every persistence UPDATE in service functions, full stop" — that's all 9 UPDATE statements in `conflict_resolution.py`. Plus give every form template that posts a state-change a `.form-error` slot, including the listing's direct-submit Accept Stage 2.

The simpler-and-cheaper alternative: add `FOR UPDATE` to `_load_conflict_item`'s SELECT. One line. Serializes all six service functions' read-then-write windows. Eliminates the read-side race in `accept_stage_*` AND in the early `extracted_facts` UPDATE of `edit_stage_1_facts` (the SELECT in `_load_conflict_item` would block if another transaction has the row locked). This would require changing the helper to return a row id along with the dict (so the UPDATE can target a known-locked row), and would force the LLM-touching paths to commit the SELECT transaction before the LLM call (which they already do — they exit `with db()`, releasing the lock).

There's a subtle wrinkle: `FOR UPDATE` only locks for the duration of the transaction. The LLM-touching paths can't hold the lock through the LLM call. So `FOR UPDATE` solves the `accept_stage_*` race and the `_load_conflict_item` portion of the LLM paths, but the LATE UPDATEs still need the TOCTOU predicate (which they already have) and the EARLY UPDATE in `edit_stage_1_facts` still needs it (which it doesn't). The minimal correct change is therefore: `FOR UPDATE` on the load + add the predicate on the early UPDATE. Five lines total.

### Theme 2: Asymmetry between `re_prompt_stage_2` and `edit_stage_1_facts`

Three findings reveal these two functions diverge in unexpected places:

- B-R2: `edit_stage_1_facts` wraps Pydantic; `re_prompt_stage_2` doesn't.
- B-S5 (and B-N5): both functions' success-branch audit payloads are different shapes.
- N5 specifically: `edit_stage_1_facts` accepts a `reason` kwarg; `re_prompt_stage_2` doesn't.

The pattern is consistent with `re_prompt_stage_2` having been written first and `edit_stage_1_facts` having been written better with lessons learned, but the lessons not being backported. This is symptomatic of TDD-per-task ordering rather than service-design-first thinking — the plan has Tasks 5 and 6 as separate tasks with separate commits, which is the right structure for incremental TDD but creates a copy-evolved-but-not-backported risk.

Holistic remediation: do a side-by-side reconciliation of the two functions' shapes during the fix-up. Make them isomorphic where possible. Where they MUST differ (input shape, what gets cleared, what gets written), document why.

### Theme 3: Token drift recurs — project-wide pattern

The G3 review packet flagged `--surface-2 / --border / --muted` drift; the G4 review surfaces `--mono` drift in two new locations. The G4 plan's own review-checklist line wrote `--mono` ("verify G4's CSS uses the established `--paper-2/--rule/--ink-3/--mono` tokens") — the wrong assumption propagated FROM the plan TO the implementer.

This is a project-wide risk worth solving once rather than per-task. Three options of increasing investment:

- **(a) One-time audit + lint script.** Grep for `var\(--[a-z-]+,` patterns across `static/*.css` and `templates/**/*.html`; produce a list of every token used; cross-reference against the canonical declaration in `styles.css`; fail CI on drift. Probably 30 lines of Python.
- **(b) Stylelint with `--custom-property-pattern`.** Industrial-strength but heavyweight for the size of this project.
- **(c) Ad-hoc — fix it when it surfaces.** Acceptable if drift is rare; given it's recurred twice now, probably not adequate.

If the user wants to bundle (a) into the G4 fix-up, ~30 lines of `scripts/check_css_tokens.py` would catch this category of bug at the next G-track or the B5 work. Otherwise, fix the F-R1 occurrences and accept that drift may recur.

### Theme 4: Documentation drift between plan/comment and code

Three sites where prose disagrees with code:

- B-R1's inline comment block (L610-618) describes the consequence as "silently affected 0 rows" — the UPDATE actually affects 1 row.
- B-R2's docstring says "surfaces cleanly" — code surfaces as 500.
- The plan's decision #12 prose says `accept_stage_*` "don't need" the guard — wrong about READ COMMITTED.
- The plan's reference to `AIBudgetExceeded` exception class — doesn't exist.
- The plan's `apply_score_floors(facts, item, rewrite)` signature — actual signature is 5-arg.

The implementer flagged the third and fourth as deviations and adapted the code. The first two were caught by the backend reviewer. The auditor-pattern lesson from G2/G3 applies here: **treat docstring/comment drift as fixable, not informational, especially when the prose suggests a behavior the code doesn't deliver.**

For the fix-up, every changed file should have its inline comments and docstrings re-reviewed against the post-fix-up code. Specifically the L610-618 comment block in `conflict_resolution.py` should be replaced with one that accurately describes the post-R1-fix behavior.

---

## IV. Recommended remediation strategy

This section is **not prescriptive** — it's a strawman the user can adopt, modify, or reject when authoring the remediation plan.

### Strawman scope for the single fix-up commit

**Required (in scope):**
- B-R1: add TOCTOU predicate + early-fail audit + raise-before-LLM to `edit_stage_1_facts`'s early `extracted_facts` UPDATE. **5-10 lines + 1 regression test** asserting `extracted_facts` unchanged after race-loss.
- B-R2: wrap `re_prompt_stage_2`'s `StructuredFacts.model_validate` in try/except → `ConflictValidationError`. **5 lines + 1 regression test** asserting 400 with the right body.
- F-R1: rename `--mono` → `--font-mono` in two locations. **2 lines.**

**Recommended bundle (Theme 1 holistic):**
- Add `FOR UPDATE` to `_load_conflict_item`'s SELECT — closes B-S1 + the read-side of B-R1 in one stroke. **1 line.** Plus update decision #12's prose in the plan and the inline comment at L610-618 to match actual semantics. **~10 lines of comments.**
- F-S1: add `.form-error` span + `hx-on:htmx:response-error` to the Accept Stage 2 form. **3 lines.**

**Recommended bundle (Theme 2 isomorphy):**
- B-S5: add `headline`, `why_it_matters`, `final_significance`, `final_consent` to the success-branch audit payloads of both LLM-touching paths. **4 lines × 2 sites.**
- B-S3: change `edit_stage_1_facts` to raise on `len(reason) > REASON_MAX` (matches `accept_stage_2`). **2 lines.**

**Recommended (Theme 3 prevention):**
- Optional: add `scripts/check_css_tokens.py` + a CI hook (or just a runbook entry). **~30 lines.** Prevents future drift.

**Recommended (Theme 4 documentation):**
- Replace L610-618 comment block in `conflict_resolution.py` with one accurately describing the post-fix behavior. Document the `apply_score_floors` and `AIBudgetExceeded` corrections in `_rerun_stage2`'s docstring.

**Defer (out of scope for fix-up):**
- B-S2 (still-conflicting score-column write): minor observability gap, no bug. Defer.
- B-S4 (`ai_generated_at` sort): no rendering bug; B5 can revisit when the v3 orchestrator lands.
- B-S6 (anthropic SDK exception → 503): documented today as 500-acceptable; defer or rewrite plan/docstring.
- F-S3 (hard-coded "Verdict: PROCEDURAL"): cheap insurance but not a current-direction bug. Author's call.
- All NICE-TO-HAVE (~26 items): defer.
- Pre-existing FK drift on `agenda_item_badges_audit`: separate investigation (see §VII).

### Strawman commit message

```
fix(admin): G4 review fix-up — TOCTOU completeness, Pydantic wrap, CSS token

Decisions per the technical-report remediation:

- B-R1: edit_stage_1_facts early extracted_facts UPDATE now carries the
  TOCTOU predicate AND fails-fast before the LLM call on lost race —
  closes the silent-overwrite window on a concurrently-resolved row
  AND saves the wasted LLM spend.
- B-R2: re_prompt_stage_2's defensive StructuredFacts.model_validate now
  wrapped in try/except → ConflictValidationError (matches the pattern
  edit_stage_1_facts already uses). Route returns 400 instead of 500.
- F-R1: var(--mono, ...) → var(--font-mono, ...) in tweaks.css:317 and
  _conflict_form_edit_facts.html:17. Editorial design system token
  alignment; recurring drift class previously surfaced in G3.
- B-S1 + Theme 1: _load_conflict_item now uses SELECT ... FOR UPDATE to
  serialize the read-then-write window in accept_stage_1/accept_stage_2;
  closes the dual-edit silent-overwrite race. Decision #12 prose
  updated.
- F-S1: Accept Stage 2 form now has .form-error span + hx-on handler;
  TOCTOU race-loss surfaces visibly instead of silently.
- B-S3 + B-S5: payload symmetry between re_prompt_stage_2 and
  edit_stage_1_facts; reason validation consistent (raise, not truncate).

Test additions: 2 regression tests (extracted_facts unchanged after
edit-facts lost race; 400 on stored-JSONB pydantic drift).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

Estimated diff size: ~80 lines of code + ~40 lines of test. Single commit.

---

## V. Cross-model convergence

Two pairs where backend and frontend reviewers (working independently on different scopes) caught the same underlying issue from different angles:

1. **Race-loss surface gap.** Backend B-R1 caught the silent-overwrite hazard at the persistence layer. Frontend F-S1 caught the silent-failure hazard at the form-submit layer. **Same gap from data-layer and UI-layer angles.** Underlying issue: decision #12 protected the LATE backend UPDATEs but didn't extend the protection (a) earlier in the same function, and (b) outward to the listing's direct-submit form.

2. **Documentation-vs-behavior drift.** Backend B-R2's docstring says "surfaces cleanly" while code surfaces as 500. Backend B-R1's inline comment claims "silently affected 0 rows" while the UPDATE affects 1. **Two manifestations of the same auditor-pattern category.** Recurring across G2 / G3 / G4 protocol runs.

The G2-pattern auditor lesson recurred again in G4 — even with the technical-report variant skipping a dedicated auditor step, the cross-model convergence on documentation drift is itself the auditor finding. The lesson holds: prose-and-docstring-vs-code drift is fixable, not informational.

---

## VI. Verified-correct (audit trail)

The following items were specifically called out in the review scope and verified by both reviewers:

- **Decision #2 — `_rerun_stage2` minimality.** Calls `rewrite_item → apply_score_floors → reconcile_stages` in correct order. No B5 scope creep.
- **LLM call OUTSIDE held DB connection.** Read tx commits before LLM; persistence tx is fresh.
- **Decision #11 — `already_retried=True`.** Both call paths correct.
- **Decision #12 — TOCTOU predicates on the four LATE UPDATEs.** All four present and correct.
- **Decision #13 — race-loss audit row commit ordering.** Audit writes inside `with db()` block, exits/commits, then raises. Correct vs `docket.db.db()` rollback-on-exception contract.
- **Decision #14 — score-overrides preservation.** `accept_stage_*` doesn't recompute; LLM-touching paths do.
- **`_get_enabled_policy_slugs` shim.** Correctly filters to `kind == "policy"` (verified vs `query.list_enabled_badges`'s UNION ALL output).
- **`apply_score_floors` cursor lifecycle.** Fresh short cursor opened AFTER LLM returns; no nested transactions.
- **Pydantic gates** on admin-input `new_facts_json` (correctly wrapped); `extra='forbid'` rejects unknown keys. (Stored-JSONB equivalent in `re_prompt_stage_2` is the B-R2 gap.)
- **Length caps** match `ItemRewrite` Pydantic Field constraints + decision #87 density rule.
- **`_load_conflict_item` filter** on `processing_status='cross_stage_conflict'`. Item-not-found AND wrong-state both → 404 (no silent overwrite of completed items at the SERVICE entry; the gap is in `edit_stage_1_facts`'s post-load early UPDATE — see B-R1).
- **HTMX correctness** — swap-target ids unique; form-expander GETs use `hx-target="#row-N .actions"` + innerHTML; direct submission for Accept S2 uses `hx-target="#row-N"` + outerHTML.
- **Decision #6 — HTMX 4xx UX.** All three form-expander forms have BOTH `hx-on:htmx:response-error` AND `<span class="form-error" role="alert">`. Handler uses `responseText` (correct for HTMX 1.x). Span is INSIDE the form so it persists on 4xx (form not swapped).
- **Decision #12 (frontend)** — TOCTOU 409 surfaces through the same `.form-error` slot; handler doesn't filter on status code. Verified end-to-end by `test_re_prompt_returns_409_when_item_resolved_during_llm_call`.
- **Auth coverage.** All 8 new routes mount on `admin.` blueprint; `before_request` hook fires; 5 routes have explicit `requires_login` tests, 3 form-expander GETs inherit through identical registration pattern.
- **GET vs POST hygiene.** 4 POST-only actions (405 on GET); 4 GET-only readers.
- **Anti-XSS.** Zero `|safe` filters; every user-controlled string autoescaped or routed through `tojson` (which uses `htmlsafe_dumps`).
- **`tojson(indent=2)` inside `<textarea>`** correctly preserves newlines.
- **CSRF.** Project-wide gap; G4 follows G2/G3 precedent. Out of G4 scope.
- **Cross-template `Conflicts` nav-link** added to all 6 admin pages.

---

## VII. Pre-existing issue surfaced during G4 review (not a G4 issue)

Migration 016 (the G3 fix-up's FK relaxation on `agenda_item_badges_audit.agenda_item_id` to `ON DELETE SET NULL`) was recorded as applied in `schema_migrations` (timestamp 2026-05-10 14:21) but `pg_constraint` showed the FK was still the pre-016 RESTRICT shape. The G3 test that was supposed to verify this (`test_list_badge_audit_log_left_joins_deleted_items`) was failing locally — the implementer flagged it during their report.

Manually applied the migration's `SQL_UP` directly via psql; constraint now correctly says `ON DELETE SET NULL`; test passes; full suite at 1164.

**Root cause: unknown.** The migration runner (`runner.py:67-73`) uses `cur.execute(mod.SQL_UP)` for multi-statement DDL. psycopg2 supports multi-statement execute; ALTER TABLE failures would raise (DDL doesn't fail silently in PG); the schema_migrations row was inserted, which means the runner believed all three ALTER statements succeeded. Possibilities to investigate (out of scope here):

1. The runner ran successfully on a different database connection/role that had its changes invisible to the connection pool the tests use.
2. A subsequent operation reverted the constraint without removing the schema_migrations row (test fixture? pg_dump/restore?).
3. The migration ran against a freshly-restored snapshot; that snapshot already had the schema_migrations row but not the post-016 constraint.

**This is a separate follow-up task.** The local DB is now correct. Recommend filing as task #49 (G3 follow-up: investigate migration 016 application drift). For the G4 fix-up, no action required.

---

## VIII. Open questions for the user

These are non-binary judgment calls the technical report can't decide for you. Each is a place where the remediation plan you author can give explicit guidance:

**Q1. Theme 1 holistic remediation: minimal vs comprehensive?**
- **Minimal (B-R1 + B-R2 + F-R1 only):** ships the three REQUIRED fixes; B-S1's accept-race remains as a known v1 hazard.
- **Comprehensive (+ `FOR UPDATE` on `_load_conflict_item` + F-S1 .form-error on Accept S2):** closes the entire race-condition cluster; ~5 extra lines.
- Recommend comprehensive.

**Q2. Theme 2 isomorphy: how aggressive?**
- **Minimal (B-S3 reason consistency + B-S5 payload completeness):** corrects the visible asymmetries.
- **Comprehensive (+ B-N5 `reason` kwarg on `re_prompt_stage_2` + cleanup of B-N6 import placement):** full reconciliation.
- Recommend minimal — N5 isn't user-visible and N6 is style.

**Q3. Theme 3 prevention: invest now or defer?**
- **Defer:** fix F-R1, accept that drift may recur; G5 or B5 reviewer catches it again.
- **Invest:** ship `scripts/check_css_tokens.py` + CI integration (~30 lines + 30 minutes of CI config).
- No recommendation — judgment call on long-term ROI.

**Q4. Theme 4 documentation: which sites get re-reviewed?**
- The L610-618 comment block in `conflict_resolution.py` clearly needs updating.
- The `_rerun_stage2` docstring should correct `apply_score_floors` signature reference and drop `AIBudgetExceeded`.
- The plan itself has decision #12 prose that needs tightening — but plan is a historical artifact, not executable code; updating it is optional.
- Recommend: update the two code-adjacent docs; leave the plan alone (it's the contract for what was implemented, with known errata).

**Q5. Should `accept_stage_2` and `accept_stage_1` get `FOR UPDATE` even though the actual race is microseconds-wide?**
- **Yes (recommended):** one-line change closes B-S1 cleanly and makes the plan's decision #12 prose accurate.
- **No:** the dual-`accept_stage_1` headline-overwrite is so rare it's not worth the lock contention (which itself is also negligible — `agenda_items` has no other write traffic on the same row).
- Recommend yes; same line of code that makes B-R1's early UPDATE protection correct.

**Q6. Test additions for the fix-up — how thorough?**
- B-R1 needs at least one test asserting `extracted_facts` unchanged on race-loss (the existing test only checks status + audit-action).
- B-R2 needs a test using a deliberately-malformed `extracted_facts` JSONB to fire the `ValidationError` path.
- B-S1 / Theme 1 — a `FOR UPDATE` test would need two concurrent admin clients which is hard in pytest; the value-add is low if the `FOR UPDATE` is one line and obviously correct. Recommend skip.
- F-S1 — a test asserting Accept S2 race-loss returns 4xx with a body the .form-error would render. Cheap.
- Recommend the four above.

**Q7. Should the pre-existing migration-016 drift be filed as an immediate task or batched into the FINAL-* work?**
- It's not a G4 blocker; the local DB is correct.
- Filing now creates a tracked follow-up; batching into FINAL-1's deploy validation creates a real-world test (Railway will apply the migration cleanly, or it won't).
- Recommend file now (task #49) and verify on Railway during FINAL-1.

---

## IX. Implementation deviations review

Recap of the four deviations from the implementer's report, with my disposition:

1. **`get_enabled_policy_slugs` shim** — accepted. Verified the shim filters correctly (B verified-correct list).
2. **`apply_score_floors` 5-arg signature** — accepted. Verified cursor lifecycle is clean (B verified-correct list). The plan's wrong signature should be corrected in the docstring of `_rerun_stage2`.
3. **`ai_generated_at` substitution for missing `updated_at`** — accepted with caveat (B-S4). No rendering bug; sort-semantic mismatch is mostly moot. Don't fix in G4; revisit during B5.
4. **TOCTOU audit-row commit ordering refactor** — accepted. Verified flag-then-commit-then-raise is correct vs `docket.db.db()`'s rollback-on-exception contract.

All four deviations are reasonable. None should be undone in the fix-up.

---

## X. Summary table

| Class | Count | In scope for fix-up |
|---|---|---|
| REQUIRED | 3 | All 3 |
| SUGGESTED — Theme 1 (race) | B-S1, F-S1 (2) | Recommended (Q1) |
| SUGGESTED — Theme 2 (asymmetry) | B-R2 (Required), B-S3, B-S5 | Recommended (Q2) |
| SUGGESTED — other | B-S2, B-S4, B-S6, F-S2, F-S3 (5) | Defer / author's call |
| NICE-TO-HAVE | ~26 | Defer all |
| Architectural | Theme 3 (token drift) | Optional script (Q3) |
| Architectural | Theme 4 (doc drift) | Recommend two docstring fixes (Q4) |

**Estimated remediation diff:** ~80 lines code + ~40 lines test if you take the recommended-comprehensive path. Single commit.

After the fix-up commits, push to origin and proceed to memory + CLAUDE.md update for "Track 3 16/17 done (~94%); B5 is the only remaining task."

---

*End of report. Author your remediation plan as a free-form response (not constrained to bullet decisions); the implementer applies it as a single fix-up commit and the protocol concludes with the standard memory + push.*
