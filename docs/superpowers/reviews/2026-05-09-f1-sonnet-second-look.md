# F1 Second-Look — Sonnet 4.6
**Commit:** d5b6d62
**Reviewer angle:** Cross-model second-look (test fidelity, spec drift, helper design, JSONB merge, boundary cases)
**Verdict:** REQUEST CHANGES

## Summary

Two findings Opus is unlikely to flag independently: (1) the spec named a specific in-Python helper `apply_policy_significance_gate(items, badge_slug, city_id)` that F3/G-track will need for Smart Brevity Card chip filtering — the implementer built `resolve_significance_threshold` (returns a threshold int, not a filtered list), which is a better design for SQL call sites but leaves the Jinja chip-loop call site without a working abstraction; this is a design divergence that will surface as duplicated threshold resolution in G-track unless addressed now. (2) The `COALESCE(c.matcher_hints_override, t.default_matcher_hints)` whole-object semantics mean that any city setting `matcher_hints_override = {"min_significance": 7}` silently discards all other defaults (keywords, action_types, topics, excluded_action_types) — both spec and impl do this, but the test for city override (`override_min_significance`) writes exactly `{"min_significance": 7}` as the full override object, which exercises the bug path without detecting it.

---

## REQUIRED

- [ ] **Spec helper name / signature divergence** (`docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md:3037`, `src/docket/services/query.py:699-753`) — Spec line 3037 explicitly names the shared helper `apply_policy_significance_gate(items, badge_slug, city_id)` — an in-Python filter that takes a list of items and returns a filtered subset. The implementer instead built `resolve_significance_threshold(city_id, badge_slug) -> int | None` — a threshold resolver useful for SQL injection but wrong for the Jinja chip-loop call site (Smart Brevity Card badge chips, spec §5.4 / §6.5 line 3035). The chip-loop call site cannot use a SQL predicate; it needs Python-level filtering of a `badges` list. F2/G-track will have to either: (a) duplicate threshold resolution inline in the template or route, or (b) accept the wrong abstraction. Either outcome violates the spec's explicit intent. **Fix:** Either add the in-Python `apply_policy_significance_gate(items, badge_slug, city_id) -> list` wrapper as a thin call to `resolve_significance_threshold` + list comprehension, OR patch the spec to bless `resolve_significance_threshold` and document the chip-loop pattern explicitly. Since the SQL design is better for F1 and the Python wrapper is trivially thin, the fix is additive (add the wrapper, keep the helper). **Opus blind spot:** Opus reviewers optimize for implementation correctness at the current task's scope; this requires tracing forward to F3/G-track call sites to spot the gap.

- [ ] **COALESCE whole-object semantics lose matcher defaults on city override** (`src/docket/services/query.py:735`, `tests/integration/test_list_items_by_badge.py:172-183`) — `COALESCE(c.matcher_hints_override, t.default_matcher_hints)` does whole-object replacement. If Birmingham's `priority_badges_config.matcher_hints_override` is set to `{"min_significance": 7}`, every other default key from `default_matcher_hints` (`keywords`, `action_types`, `topics`, `excluded_action_types`) is silently dropped. The test `override_min_significance` writes exactly `{"min_significance": 7}` as the entire override, which is the exact scenario where this bites — yet the test only checks `resolve_significance_threshold`, so the data-drop goes undetected. This is not F1's bug directly (the threshold helper only reads `min_significance`), but the test fixture creates a broken state that the matcher will inherit when it reads hints from the same COALESCE path. The fix at the spec level is Postgres `||` merge: `COALESCE(t.default_matcher_hints, '{}'::jsonb) || COALESCE(c.matcher_hints_override, '{}'::jsonb)` — defaults win, city keys override per-key. **Opus blind spot:** Opus reviewers check whether the override test passes (it does); they tend not to trace the side-effect of what the fixture writes into the DB against the COALESCE semantics that the matcher will read later.

- [ ] **Spec SQL uses `m.city_id` — column does not exist** (`docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md:3006`) — The spec's SQL pseudocode has `WHERE m.city_id = %s` but `meetings` uses `municipality_id`, not `city_id`. The implementation correctly avoids this by using `aib.city_id = %s` on the badge row — which is the right column and the right table. However, the spec is silently wrong: anyone copy-pasting the spec's SQL will get a runtime error. This needs a spec correction comment. The implementer flagged this but did not write a correction. **Fix:** Add an inline spec note: `-- NB: meetings table uses municipality_id, not city_id; implementation scopes via aib.city_id.` Alternatively, patch the spec line. Low cost to fix before F2 picks up the spec.

---

## SUGGESTED

- [ ] **No boundary test for `confidence` at exactly 0.6** (`tests/integration/test_list_items_by_badge.py:341-353`) — `test_confidence_floor_default_excludes_below_06` tests `0.4` (below) and `1.0` (above). No test covers `confidence=0.60` (should be included, `>=` semantics) or `confidence=0.59` (should be excluded). If `>` were accidentally used instead of `>=`, neither test would catch it. Add a test at the exact boundary: `confidence=0.60` included, `confidence=0.59` excluded.

- [ ] **No boundary test for `significance_score` at exactly the threshold (3)** (`tests/integration/test_list_items_by_badge.py:375-387`) — `test_significance_gate_excludes_low_sig_policy_default` uses `significance_score=5` (above) and `significance_score=2` (below), with `min_significance=3`. The `>=` operator means `significance_score=3` MUST be included. No test covers it. A `>` typo would pass both existing tests but break the at-threshold case. Add a test item with `significance_score=3` that asserts it appears.

- [ ] **Cross-filter confidence intentionally omitted — no regression test** (`src/docket/services/query.py:786-788`) — The docstring says cross-filter has no confidence floor (intentional). But no test guards this. A future reviewer who thinks the missing `x.confidence >= %s` is a bug will have no test to prevent the regression. Add one sentence to an existing cross-filter test that badges the cross-filter item with `confidence=0.1` and asserts it still returns.

- [ ] **`apply_policy_significance_gate` named helper: spec says 3 call sites, only 1 implemented** (`docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md:3037`) — F1 covers only the service-layer call site. The search call site (F-track or later) and Smart Brevity Card chip call site (G-track) are not F1 scope, but a comment in `resolve_significance_threshold` should note that these two call sites exist and point to where the helper should be wired. Otherwise F2/G-track developers may not know the helper exists.

---

## NIT

- [ ] **`cross_filter_slugs` type annotation mismatch between spec and impl** (`src/docket/services/query.py:761`, `docs/...:2976`) — Spec declares `list[str] = ()` (list annotated, tuple default — contradictory). Implementation uses `tuple[str, ...] = ()` which is correct and consistent. The spec should be updated to `tuple[str, ...] = ()`. Minor, but spec-as-documentation accuracy matters.

- [ ] **`test_include_low_significance_disables_policy_gate` doesn't assert the default excludes** (`tests/integration/test_list_items_by_badge.py:390-402`) — This test only checks that `include_low_significance=True` includes the item. It relies on a separate test (`test_significance_gate_excludes_low_sig_policy_default`) for the exclusion side. The two tests together cover the behavior, but the name implies a toggle test — it would read more clearly as a single test with both branches. Minor structural issue, not a correctness bug.

- [ ] **`badges` field not populated in `list_items_by_badge` — docstring says "Smart Brevity Card handles missing badges gracefully" but this is not tested** (`src/docket/services/query.py:794-797`) — The docstring explicitly calls out that `badges` will be empty for items returned by this function. No test asserts `item.badges == []` for returned items. `AgendaItem.from_row` defaults it to `[]` via `row.get("badges") or []` so it's not a crash risk, but worth a one-line assertion in `test_return_type_is_agenda_item`.

---

## Things I checked that came back clean

- **SQL injection audit**: All `cross_filter_slugs` entries are appended as `%s` parameters, never f-string-interpolated. ORDER BY columns are hardcoded strings, not user input. Clean.
- **`>=` vs `>` in the actual SQL**: `ai.significance_score >= %s` and `aib.confidence >= %s` — both use `>=`. Matches spec.
- **Parameterization of primary badge filter**: `aib.city_id = %s AND aib.badge_slug = %s AND aib.confidence >= %s` — all three are `%s`. No interpolation.
- **`processing_status` confounding in `test_processing_status_pending_excluded`**: The `pending` item has `significance_score=5` and `confidence=1.0` — no confounding from other filters. If the `processing_status` gate were removed, the pending item WOULD appear. The test correctly isolates the gate.
- **City scoping test has two cities**: `bag.other_city_id` is guaranteed by the fixture (inserts a new municipality if none exists). The test correctly adds a badge to `other_item` scoped to `other_city_id`. Two-city signal is present.
- **Cross-filter uniqueness**: `UNIQUE (agenda_item_id, badge_slug)` on `agenda_item_badges` means `x.city_id` filter in the EXISTS subquery is unnecessary — each (item, badge) pair is unique regardless of city. The implementer's decision to omit `x.city_id` is correct.
- **`LIMIT 0` behavior**: Implementation passes `limit` directly as a `%s` parameter. Postgres `LIMIT 0` returns 0 rows — correct.
- **`resolve_significance_threshold` for unknown slug returns `None`**: Tested by `test_resolve_threshold_unknown_slug_returns_none`. Implementation returns `None` when the template row is not found (correct — no gate).
- **Teardown restore of `NULL` `matcher_hints_override`**: `override_min_significance` saves `row[0]` which is Python `None` when the column is `NULL`. Cleanup runs `SET matcher_hints_override = None::jsonb` — psycopg2 sends `NULL`, which correctly restores the column to `NULL`. No silent state corruption.
- **`test_resolve_threshold_process_returns_none`**: Uses `hidden_on_consent` (kind=process). Implementation correctly returns `None` for `kind != 'policy'`. Gate behavior for process badges is correct.
- **`f-string` WHERE-clause construction in `list_meetings`**: The f-string in `list_meetings` interpolates a `where` string built from hardcoded literals (`"m.slug = %s"`, `"AND mt.meeting_type = %s"` etc.) with values always in `params`. Not a new concern introduced by this commit.
