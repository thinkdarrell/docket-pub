# F1 Review — Tests & Helper API (Opus #2)
**Commit:** d5b6d62
**Reviewer scope:** Test coverage adequacy, helper API design, commit hygiene, AgendaItem dataclass alignment, spec-drift potential
**Verdict:** APPROVE with SUGGESTED follow-ups

## Summary

The 19 integration tests are high quality — almost every test asserts both **inclusion** of a positive case and **exclusion** of a negative case (a stronger pattern than typical AI-generated `assert len > 0` tests). Helper signature is workable for the listing call site, but the implementer's flagged concern about the per-item chip-rendering call site is real: `resolve_significance_threshold(city_id, badge_slug)` will trigger an unbounded number of DB round-trips when called inside a Jinja loop. Commit hygiene is clean (single commit, focused diff, full Co-Author trailer, well-written body explaining deviations). All 19 tests pass locally against `docket_db`.

## REQUIRED

(none — implementation is correct and well-tested for the F1 listing call site; helper-API concerns below are forward-looking, not bugs.)

## SUGGESTED

- [ ] **Helper is N+1-prone for chip-rendering call site** (`src/docket/services/query.py:699`) — Spec §6.5 line 3034-3037 names three call sites for the gate; the third (Smart Brevity Card chip filtering) iterates badges per item in a Jinja partial. With the current per-call shape, rendering a 25-item page with ~3 badges/item = 75 DB round-trips just for thresholds. There is **no existing badge-config cache** (commit `0993572` "TTL cache + admin refresh" was for source-domain allowlist only — confirmed via grep of `web/source_security.py`). Recommend either (a) a sibling helper `resolve_significance_thresholds(city_id, badge_slugs: Iterable[str]) -> dict[str, int | None]` that does one query for many slugs, or (b) a per-request memoization layer (e.g., `flask.g`-scoped) before F2/F3 lands. Implementer flagged this; agreed it's a **forward-looking** concern, not a bug in F1.

- [ ] **Helper name diverges from spec without rationale in commit body** (`src/docket/services/query.py:699`) — Spec §6.5 line 3037 names the helper `apply_policy_significance_gate(items, badge_slug, city_id)` (in-Python filter shape); implementer chose `resolve_significance_threshold(city_id, badge_slug) -> int | None` (SQL-side threshold lookup). The new shape is **objectively better for the listing call site** (lets the DB do filtering with the index), but the spec-divergence on the *name* should be noted in the commit message alongside the existing "Spec deviations:" section so future readers understand the intent shift. Cosmetic but improves traceability.

- [ ] **Missing test: list (not tuple) input for `cross_filter_slugs`** (`tests/integration/test_list_items_by_badge.py:488-558`) — Implementer-flagged concern #4. F2's planned route handler (`docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-2.md:1881`) does `request.args.get('and', '').split(',')` which yields a `list[str]`, then passes it to `list_items_by_badge(...)`. All current cross-filter tests pass tuples. Add one test that explicitly passes a `list` to verify the duck-typed iteration works (the `for cross_slug in cross_filter_slugs:` loop will work with either, but a regression test pins the contract). Type annotation says `tuple[str, ...]` — either tighten the annotation to `Iterable[str]` or add the test.

- [ ] **Missing test: city has no `priority_badges_config` row → fall back to `default_matcher_hints`** (`tests/integration/test_list_items_by_badge.py:266-289`) — The helper docstring (`query.py:715-719`) explicitly calls out this fallback: "If the city has no priority_badges_config row for this template, we still fall back to default_matcher_hints." But no test exercises this path. The four helper tests (policy/process/unknown/override) all rely on BHM having a config row from migration 013 seed. Easy fix: insert a test-only municipality without an opt-in row, assert the helper still returns the default `min_significance=3`.

- [ ] **Missing test: cross_filter_slugs containing the SAME slug as primary** (`tests/integration/test_list_items_by_badge.py:488`) — Implementer-flagged audit checklist concern. `list_items_by_badge(city, "blight", cross_filter_slugs=("blight",))` currently produces `WHERE aib.badge_slug = 'blight' AND EXISTS (SELECT 1 FROM aib WHERE badge_slug = 'blight')` — harmless no-op (the EXISTS is always true given the JOIN), but worth pinning so a future SQL refactor doesn't regress it.

- [ ] **Missing test: confidence boundary at exactly `min_confidence`** (`tests/integration/test_list_items_by_badge.py:341-368`) — Existing tests use `confidence=1.0` (above) and `confidence=0.4` (well below). SQL is `>= %s` (inclusive). A test with `confidence=0.6` and the default `min_confidence=0.6` would pin the off-by-one boundary. Same for `min_confidence=1.0` (only-highest-confidence admin scenario) — would catch a regression to `>` instead of `>=`.

- [ ] **Missing test: degenerate pagination** — No test for `limit=0` (should return empty, not error) or `offset` past the end of available results (should return empty, not error). Both are easy to add and would flush out any silent crash on edge inputs from the F2 route handler.

- [ ] **`extracted_facts` projection inconsistent with `list_agenda_items`** (`src/docket/services/query.py:834`) — `list_items_by_badge` selects the **full** `ai.extracted_facts` JSONB blob; `list_agenda_items` (commit `4409120`/`ff6cabb`) carefully extracts only the lean keys via `jsonb_extract_path`. Both eventually feed Smart Brevity Card partials, so the divergence means category landing pages will ship a heavier payload than meeting-detail pages. Either intentional (caller may need full blob — but the F2 route in the plan only renders Smart Brevity Cards), or an oversight. Match the lean projection for consistency, or document the divergence in the docstring.

- [ ] **Pagination test filters by id-set, weakening the assertion** (`tests/integration/test_list_items_by_badge.py:566-590`) — `test_pagination_limit_offset` uses `[it.id for it in page if it.id in test_id_set]` to isolate from prior test rows. If pagination silently returned all rows (limit ignored), the filter would mask the bug. Stronger version: insert items on a unique meeting_date that no other test in this file uses, drop the filter, assert the raw page slice. Minor — same pattern is used by `test_orders_by_date_desc...` so isolated dates would help both.

- [ ] **Test fixtures don't set v3 columns** (`tests/integration/test_list_items_by_badge.py:92-117`) — `add_item` only writes `meeting_id, title, significance_score, dollars_amount, processing_status`. The v3 columns from A8 (`headline`, `why_it_matters`, `extracted_facts`, `data_quality`, `data_debt_priority`, `ai_extraction_version`, `ai_rewrite_version`, `ai_confidence`) are all NULL in test rows. The SELECT projection still returns them (as NULL), so `AgendaItem.from_row()` is exercised on the NULL path only. Realistic v3 fixtures (one row with `headline + why_it_matters + extracted_facts` populated) would catch any future regression in the row→dataclass mapping for badge-listed items. Implementer-flagged audit checklist concern (D).

## NIT

- [ ] **Sentinel comment on `ORDER BY` is missing the cross-reference to `list_agenda_items`** (`src/docket/services/query.py:862-866`) — `list_agenda_items` has a 19-line comment block explaining the natural-sort regex on `item_number`. `list_items_by_badge` orders by `meeting_date DESC, dollars_amount DESC NULLS LAST` (different shape), but a one-liner cross-referencing why this listing doesn't need natural-sort (it's a cross-meeting listing, not in-meeting) would help future readers comparing the two functions.

- [ ] **No type for `cross_filter_slugs` allowing both list and tuple** (`src/docket/services/query.py:761`) — `tuple[str, ...] = ()` is the right default. But Flask routes will pass `list[str]`. Annotation could be `Iterable[str]` or `Sequence[str]` to advertise the contract; current annotation (per type-checker) would warn on `list` input.

- [ ] **Helper test `test_resolve_threshold_honors_city_override` could double-check it doesn't leak across tests** (`tests/integration/test_list_items_by_badge.py:285-289`) — The fixture's `cleanup()` restores the override at teardown, but verifying via a second-call assertion (re-run `resolve_significance_threshold` after teardown to confirm it returns 3 again) would document the cleanup guarantee. Belt-and-suspenders.

- [ ] **Test file docstring is excellent but says "19 tests"** — actual count is 19 (4 helper + 15 listing). Header docstring at line 1-28 is well-structured; consider promoting it to a class-level module docstring summary for navigability.

## Audit notes

Things that came back clean:

1. **Test fidelity** — Reviewed all 19 tests. Every single test that names a behavior actually asserts the behavior:
   - `test_significance_gate_excludes_low_sig_policy_default` correctly inserts BOTH an above-threshold item AND a below-threshold item, then asserts `above in ids AND below not in ids`. This is the gold-standard pattern; no `assert len > 0` slop anywhere.
   - `test_other_city_items_not_returned` correctly tags the cross-city item to `other_city_id` so the test exercises the `aib.city_id` predicate, not just an absence of badges.
   - `test_process_badge_has_no_significance_gate` cleverly tests both `include_low_significance=True` AND `=False` in a loop, asserting process badges ignore the flag — this catches regressions where the process-vs-policy branch in `resolve_significance_threshold` could be weakened.
   - `test_orders_by_date_desc_then_dollars_desc_nulls_last` includes a NULL dollars row positioned correctly (after non-NULL dollars on the same date, before older-date items) — exercises both ORDER BY clauses.

2. **Test isolation** — `_Bag` cleanup pattern is correct: tracks every `meeting_id` and `item_id` it inserted, deletes in dependency order (badges → items → meetings), restores `priority_badges_config` overrides. The `try/yield/finally` pattern in the fixture survives test failures. The Railway-DB safety guard at line 46-49 prevents accidental destructive runs against production.

3. **Commit hygiene** — Single commit. Diff = `src/docket/services/query.py` (only additive, zero deletions, `list_agenda_items` and other functions untouched — verified via `git diff d5b6d62~1..d5b6d62`) + `tests/integration/test_list_items_by_badge.py` (new file). Co-Author trailer present. Commit body follows the project's pattern: subject + bulleted body explaining what + why, separate "Spec deviations:" section calling out tuple-vs-list default and the `aib.city_id` vs `m.city_id` SQL substitution. No `.pyc`, log files, or IDE drift in the diff.

4. **AgendaItem dataclass alignment** — SELECT projection at lines 808-834 of `query.py` includes all v3 columns from A8 (`data_quality::text`, `data_debt_priority::text`, `processing_status::text`, `ai_extraction_version`, `ai_rewrite_version`, `ai_confidence`, `headline`, `why_it_matters`, `source_anchor`, `extracted_facts`). The casts to `::text` for the enum columns match `list_agenda_items`. `badges` is intentionally omitted (docstring at 794-797 explains why); `AgendaItem.from_row()` at `models/agenda.py:139` defaults `badges=row.get("badges") or []` so the dataclass instantiation is safe. `test_return_type_is_agenda_item` confirms the round-trip yields a real `AgendaItem` instance. Sub-key lifts (`counterparty`, `funding_source`, etc.) work because the full `extracted_facts` blob is in the row.

5. **Spec-drift potential (E6 pattern)** — F1 introduces no second copy of the listing SQL anywhere (no inline `_LOOP_BODY` or fixture string that mirrors the function's SQL). The drift-detection contract from E6 doesn't apply here. No new marker/constant needed.

6. **All 19 tests pass locally** (`pytest tests/integration/test_list_items_by_badge.py --override-ini='pythonpath=src'`, 0.78s).

7. **Helper resolves Decimal/int correctly** — `confidence` is `NUMERIC(3,2)` per migration 013, but `min_confidence` parameter is `float` and the SQL `>= %s` comparison works through psycopg's Decimal/float promotion. No type confusion.

8. **`include_low_significance` semantics** — Verified the flag flows correctly in all four combinations (process/policy × True/False). `test_process_badge_has_no_significance_gate` covers process×{True,False}; `test_significance_gate_excludes_low_sig_policy_default` covers policy×False; `test_include_low_significance_disables_policy_gate` covers policy×True. Matrix complete.
