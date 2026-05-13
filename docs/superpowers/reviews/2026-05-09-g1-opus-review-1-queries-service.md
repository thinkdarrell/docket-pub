# G1 Review #1 — Queries + Service (Opus)

**Commit:** 0549963
**Scope:** `src/docket/services/calibration.py` + data-path slice of `tests/integration/test_calibration.py`
**Reviewer:** Opus 4.7 (1M context)

## Summary

Six query helpers are well-structured, parameterized correctly (no string-concat
vulnerability), and degrade cleanly to `[]` on empty data (verified live against
local `docket_db`). Tests exercise real boundary conditions (3 vs 4, 29 vs 30,
20% vs 21%, 4 vs 5) — not substring-thin. One real spec-drift bug exists in B1
and B2 (extra `score_overrides IS NOT NULL` predicate that narrows the
denominator) and one window-function correctness wrinkle exists in Query C
(LAG running after the `n >= 10` filter introduces hidden gaps in week-over-week
deltas). All other implementer-flagged adaptations are defensible.

## REQUIRED

1. **B1/B2 add an undocumented `score_overrides IS NOT NULL` filter that changes
   the denominator semantics** — `src/docket/services/calibration.py:138` and
   `:197`. Spec §3.5 lines 1322-1325 (B1) and 1354-1357 (B2) define the WHERE as
   only `processing_status = 'completed' AND ai.updated_at > NOW() - INTERVAL
   '7 days'`. The implementation adds a third clause `AND ai.score_overrides IS
   NOT NULL` to both. That changes the denominator from "all completed items in
   the (action_type, prompt_version) group" to "items where Stage 2.5 produced
   an override audit row". The two are equivalent only if the v3 worker writes
   `score_overrides` for every completed item (even when zero triggers fire).
   Looking at `src/docket/ai/floors.py:272-278`, `compute_score_overrides`
   always returns a `ScoreOverrides` record with `triggers=[]` when nothing
   fires — so if the eventual atomic-commit path always persists that record,
   the divergence is harmless. But the contract is not yet enforced anywhere
   (no `process_item` exists yet — Track 1+2+3 convergence is B5, still
   pending). If a future implementer decides to skip persisting empty-triggers
   records as a storage optimization, B1/B2's percentage will silently invert
   meaning — "% of stage-2.5-fired items that got boosted" (always 100% by
   construction, useless) instead of "% of completed items in the category that
   got boosted" (the actual intent). Either remove the filter to match spec, or
   add an explicit comment + test guard that asserts every completed item with
   a v3 prompt version has `score_overrides IS NOT NULL`. Note Query A
   genuinely needs the filter — its SELECT extracts JSONB fields that NULL out
   the row otherwise. B1/B2 don't need it: they use `FILTER (WHERE ...)` which
   already returns 0 when the JSONB extract yields NULL.

## SUGGESTED

2. **Query C window function runs after the `n >= 10` filter, causing hidden
   gaps in `sig_delta_wow` / `volume_delta_wow`** — `calibration.py:255-271`.
   The SQL evaluates the outer `WHERE n >= 10` before the LAG window, so for
   action_type X with weeks {n=15, n=8, n=20}, the LAG for the n=20 row
   compares against the n=15 row (skipping n=8). The "week-over-week" label in
   the template (line 190 `Δ sig (w/w)`) is then misleading whenever a
   between-week falls below the noise floor. Two-row fix: compute the LAG
   inside the CTE over all weeks (no filter), and apply `WHERE n >= 10` in the
   outer query. The LAG values would then either (a) reflect the immediately
   prior week (whether or not it surfaced) or (b) you can keep `n >= 10`
   inside the CTE if the design intent is "delta only against weeks that also
   met the floor" — but that should be documented in the docstring, because
   the current setup gives behavior (b) without saying so.

3. **Empty-data run was clean but not asserted in CI** — `db_cursor()` returns
   `RealDictCursor` rows so `[dict(row) for row in cur.fetchall()]` will not
   crash on zero rows, and a live run against `docket_db` confirmed all six
   queries return `[]`. The integration tests cover the populated-data case
   well but never assert "empty DB → empty list" without indirection (the
   route-level test at `test_calibration.py:649` only asserts the empty-state
   marker shows on the rendered page, which is reviewer #2's surface). One
   small unit test per query function (`assert cal.query_X() == []` in a
   schema-clean DB context) would make the empty-data contract explicit and
   guard against accidental cast crashes if a column changes type.

4. **B1/B2 docstring should call out the avg semantics** — the
   `avg_boost_magnitude` (B1) and `avg_reduction_magnitude` (B2) CASE
   expressions return NULL for non-boosted/non-reduced items; AVG ignores
   NULLs, so the average is "magnitude across items that fired" not "magnitude
   across all items in the group". That's the right semantic for tuning
   judgments ("when the boost fires, how big is it on average") but it's not
   stated in the docstring. Three-line note in the function-level docstring
   would prevent future confusion.

## NICE-TO-HAVE

5. **`agenda_item_badges` already has a `city_id` column — the badge volume
   query doesn't need to join to `meetings` for it.** Migration 013 line 132
   adds `city_id INT NOT NULL REFERENCES municipalities(id)` directly on
   `agenda_item_badges`. The current query
   (`calibration.py:300-326`) joins `agenda_items` and `meetings` solely to
   read `m.municipality_id AS city_id`. Replacing
   `m.municipality_id AS city_id` with `aib.city_id` and dropping the two
   joins would simplify the plan and slightly reduce row work. The
   `top_false_positives` query (`agenda_item_badges_audit`) does not have this
   shortcut — that table has no `city_id` column — so the meeting JOIN there
   is necessary.

6. **`test_query_b1_pct_threshold_21_surfaces` is named misleadingly** —
   `test_calibration.py:394`. 7/30 = 23.3%, not 21%. The boundary is correctly
   exercised (just-over-20%), but the name should be `_threshold_above_20`
   or `_threshold_23_surfaces`. Cosmetic.

7. **Spec §5.7 line 80 vs spec line 2410 disagree on "5" vs ">5"** — spec
   text says "removed >5 times in 7 days" (decision #65 summary) but the
   spec SQL says `HAVING COUNT(*) >= 5` and the implementation matches the
   SQL. Test (`test_query_top_false_positives_threshold_5_surfaces` —
   `test_calibration.py:559`) confirms 5 surfaces. Spec internal
   inconsistency, not an impl issue, but the docstring at `calibration.py:26`
   ("admins removed >= 5 times") could note "spec text says >5 but spec SQL
   says >=5; tests match spec SQL".

8. **Query C `LAG()` with `ORDER BY week DESC` final ordering is fine but
   non-obvious** — the LAG is computed on `ORDER BY week` (ascending), then
   rows are returned with `ORDER BY action_type, week DESC`. So
   `sig_delta_wow` for the most-recent week always carries a real prior-week
   delta, but the oldest row in the series will have NULL. Template at
   line 207 already handles NULL. No action needed; flagging that this
   ordering pattern is correct and intentional.

9. **`badge_volume_calibration` returns ALL rows, threshold-checking deferred
   to template** — the spec's >40% deterministic-only / >40% llm-only callout
   is currently NOT in the SQL. The template at `calibration.html:228-230`
   describes the threshold in prose but doesn't visually highlight crossing
   rows. That's a defensible choice (fewer round-trips to drill down) but
   means admins will scan a full table looking for outliers. A future polish
   pass could add a CSS class on `pct_deterministic_only > 40 OR pct_llm_only
   > 40` rows, or push the threshold filter into a query parameter. Out of
   scope for G1 v1; worth a follow-up note.

10. **Empty `extracted_facts` rows surface as `action_type=NULL`** —
    `extracted_facts->>'action_type'` returns NULL for rows where
    `extracted_facts` is NULL or missing the key. B1/B2 then GROUP BY this
    NULL and the resulting row carries `action_type=NULL`. Template handles
    this with `{{ row.action_type or '—' }}`. Fine — but worth confirming
    that every completed item the v3 worker writes will have
    `extracted_facts` populated. Phase 2 Track 1 owns extraction; if Stage 1
    can complete without populating `action_type`, B1/B2 will surface a
    permanent `(NULL, version)` row at the top of the table. NICE-TO-HAVE
    test: assert NULL action_types are excluded or rendered as a labeled
    "(uncategorized)" row.

## Implementer-flagged question responses

1. **`ai_generated_at` vs spec's `updated_at`: defensible substitution.**
   - Schema check: `ai_generated_at` is added by Migration 012
     (`agenda_items` line 9, `meetings` line 19) as the AI worker's
     freshness signal; there is no `updated_at` on `agenda_items` in any
     migration. The spec text was likely written assuming a generic
     auto-update trigger.
   - The v2 worker (`src/docket/ai/worker.py:88, 113, 132, 152, 172`) sets
     `ai_generated_at = NOW()` on every successful AND every failed write.
     `ai_generated_at` does not yet have a write path bundled with
     `score_overrides` (no `process_item` orchestrator exists — that's the
     pending B5 convergence task), but the floors.py audit-record producer
     (`src/docket/ai/floors.py:272-278`) is wired to be called inside the
     same Stage 2.5 atomic commit. Once B5 lands, the freshness coupling
     will be by construction.
   - **Re-cascade behavior:** bumping `ITEM_PROMPT_VERSION` causes the
     worker to re-process eligible items and re-set `ai_generated_at`.
     For the 24h Query A window, this would surface re-cascaded items
     even if their `score_overrides` content was unchanged from the
     previous prompt version. This is **correct and desirable** — admins
     watching calibration after a prompt bump explicitly want to see what
     the new prompt did vs the old override floors. Document this as
     intentional in the docstring.
   - **Lag/lead concern:** in v2, `mark_item_failed`
     (`worker.py:108-115`) also sets `ai_generated_at`, but failed items
     never get `score_overrides` written. That's harmless — Query A
     filters by `score_overrides IS NOT NULL`, B1/B2 same, C uses
     `significance_score IS NOT NULL` (also NULL on failure). No false
     positives expected.

2. **`m.city_id` aliasing: works correctly, no risk.** Every query
   join condition is on `m.id = ai.meeting_id` (not on `municipality_id`),
   and the alias `municipality_id AS city_id` only reshapes the output
   dict key. Template (`calibration.html:236, 250, 283, 292`) reads
   `row.city_id`. Test fixtures (`test_calibration.py:239`) bootstrap
   from `municipalities WHERE slug='birmingham'` — no test depends on
   the column name being `city_id` vs `municipality_id`. Note the
   `agenda_item_badges` table has its own `city_id` column directly (see
   NICE-TO-HAVE #5), so the meeting JOIN in `query_badge_volume_calibration`
   is unnecessary work — but that's a perf nit, not a correctness issue.

3. **Query C flat vs grouped output: flat is correct.** The template at
   `calibration.html:194-214` iterates the result set as a single
   homogeneous table with `action_type` repeating in the first column
   per row. There is no nested loop or grouping in the template. The
   ordering (`ORDER BY action_type, week DESC`) places weeks within an
   action_type adjacent to each other, so the visual table reads as
   grouped without needing a Python-side grouping pass. Returning a
   `dict[str, list[row]]` would force the template to flatten it back
   anyway. Flat is the right shape for the current consumer. If a future
   surface (sparklines, overlay charts) wants pre-grouped data, that's a
   trivial transform at call site.

## Out-of-scope observations

(Deferred to reviewer #2 — covering `/admin/calibration` route, template
rendering, auth gating.)

- **Auth gate on `/admin/calibration`** is wired via the admin blueprint
  but I didn't audit the `before_request` hook chain. Reviewer #2 owns.
- **Template renders 6 panels with stable `data-panel="..."` test hooks**
  — looks structurally sound from the data path side but full UX review
  is reviewer #2.
- **Sign-out form CSRF posture** in `calibration.html:20-23` — outside my
  scope.
- **Empty-state copy ("No items match this query in the current window.")**
  is rendered by the macro at `calibration.html:13-15`. Singular for all
  six panels; no per-panel customization. Reviewer #2 may want to assess.

## Verification evidence

- Ran all six query functions live against `docket_db` (local PostgreSQL
  16, `postgresql://docket@localhost:5432/docket_db`) — every function
  returned `[]` cleanly with no JSONB-cast crashes (zero
  `score_overrides` rows in local DB confirms empty-data path).
- Verified PG `DATE_TRUNC('week', ...)` returns Monday-anchored
  (`'2026-05-09'::timestamptz` truncates to `2026-05-04`, DOW=1) —
  ISO 8601, locale-independent.
- Verified float boundary: PG returns `6::float / 30 = 0.2` exactly,
  `> 0.20` evaluates False (excluded); `7::float / 30 = 0.2333...`,
  `> 0.20` evaluates True (included). Boundary tests at
  `test_calibration.py:381-405` align.
- Confirmed `idx_badge_audit_recent` partial index
  (`migrations/013_impact_first_refactor.py:251-253`) is `(occurred_at
  DESC, badge_slug, action) WHERE actor_role = 'admin'` — matches the
  Top False Positives WHERE clause exactly. Planner will use the index.
- All 6 functions use `db_cursor()` (lines 71, 117, 176, 239, 297, 348) —
  RealDictCursor confirmed, dict-row access verified.
