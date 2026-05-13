# F1 Review — SQL & Semantics (Opus #1)
**Commit:** d5b6d62
**Reviewer scope:** SQL correctness, index usage, runtime behavior
**Verdict:** APPROVE

## Summary

The SQL is correct, hits the intended composite index `idx_agenda_item_badges_city_slug_conf`, and the helper resolves significance thresholds in line with spec §5.1. The implementer's deviation from the literal spec (using `aib.city_id` instead of `m.city_id`) is the right call — the spec example was wrong (`meetings.city_id` does not exist; the FK column is `meetings.municipality_id`) and `aib.city_id` is also more index-selective. The biggest concern is documentation/follow-up — there is **no production INSERT site for `agenda_item_badges` yet** (Tasks C1 / D2 ship the writers later in Phase 2), so the integrity assumption "`aib.city_id == meetings.municipality_id` for the joined item" cannot be verified by reading current code. Phase 2 coordination needs to keep that invariant explicit when those tasks land.

## REQUIRED

_(none — no blocking SQL correctness issues)_

## SUGGESTED

- [ ] **City-id integrity has no DB-level guard yet** (`src/docket/migrations/013_impact_first_refactor.py:129-140`) — `agenda_item_badges.city_id` is a denormalization of `agenda_items → meetings.municipality_id` but there's no CHECK / trigger / FK composite preventing an admin-tooling or future matcher path from writing a mismatched `city_id`. With F1 filtering on `aib.city_id`, a buggy/manual write that pairs `agenda_item_id=N` (whose meeting belongs to BHM) with `city_id=Mobile` would silently mis-include the row on Mobile's category page. Plan §C1 (line 1363) explicitly says writers must JOIN `meetings` to derive the value, and the eventual Track 1 integration tests will cover the happy path, but neither defends against drift. Recommended fix: add a follow-up task to introduce either (a) a deferred trigger on INSERT/UPDATE that asserts `city_id = (SELECT municipality_id FROM meetings WHERE id = (SELECT meeting_id FROM agenda_items WHERE id = NEW.agenda_item_id))`, or (b) a composite FK from `(agenda_item_id, city_id)` to a generated column on `agenda_items`. Either is a Phase 2 hygiene ticket, not an F1 blocker — but flagging here so it doesn't fall through the cracks once C1/D2 land.

- [ ] **`COALESCE` on JSONB is whole-object, not per-key** (`src/docket/services/query.py:735`) — `COALESCE(c.matcher_hints_override, t.default_matcher_hints)` returns the entire override JSONB if non-NULL, so a city that overrides only `min_significance` loses every other key (keywords, topics, action_types, excluded_action_types). This **matches spec §5.1 line 1943** (`row.matcher_hints_override or template.default_matcher_hints`) so the implementer is faithful, and for the F1 scope (only `min_significance` is read) the helper is correct. But this is a foot-gun for the matcher write path (Track 1 / Section D2) which reads keywords from the same dict. Recommended: leave the helper as-is (faithful to spec), but add a one-line note in the docstring warning future readers that the override is whole-object and any matcher-side `matcher_hints_override` must be a complete dict — and consider a Phase-2 ticket to switch to `COALESCE(t.default_matcher_hints, '{}'::jsonb) || COALESCE(c.matcher_hints_override, '{}'::jsonb)` (PostgreSQL `||` is shallow merge, right wins) once a city actually wants partial-override semantics.

- [ ] **`processing_status = 'completed'` literal vs. enum cast** (`src/docket/services/query.py:841`) — `processing_status` is `processing_status_enum` (migration 013 line 28). PostgreSQL will coerce the unknown-typed literal `'completed'` to the enum at parse time, so the predicate works. But every other write in this codebase uses an explicit `'completed'::processing_status_enum` cast (`src/docket/ai/wave0.py:206, 225, 236`, `src/docket/ai/extraction.py:216`). Stylistic inconsistency only — psycopg2 will not auto-cast Python str → enum the way it does for booleans, but a literal string compared in WHERE goes through the parser's enum coercion path and does work. Recommended (NIT-leaning): cast for consistency with the rest of the codebase, e.g. `AND ai.processing_status = 'completed'::processing_status_enum`. No behavioral fix needed.

- [ ] **Cross-filter EXISTS does not require `x.city_id` match** (`src/docket/services/query.py:853-857`) — the subquery filters by `x.agenda_item_id = ai.id AND x.badge_slug = %s` only. Because `ai.id` was already city-filtered via the primary join (and an item has exactly one meeting / one city), this is logically correct: a cross-filter badge row for the same item must necessarily share the same `city_id`. If the city-id integrity invariant is ever violated (see SUGGESTED #1), the cross-filter would inherit the corruption. Recommended: optionally add `AND x.city_id = aib.city_id` belt-and-suspenders; index `idx_agenda_item_badges_item (agenda_item_id)` already covers the EXISTS, and the additional predicate is satisfied at scan time. Defensive-only.

- [ ] **`ai.dollars_amount DESC NULLS LAST` ordering — confirmed correct** (`src/docket/services/query.py:864`) — PostgreSQL's default for `DESC` is `NULLS FIRST`; the explicit `NULLS LAST` overrides that so items with NULL dollar amounts sort to the end of each meeting_date group. This matches spec line 3026. No fix.

## NIT

- [ ] **Decimal vs. float min_confidence comparison** (`src/docket/services/query.py:840`) — `min_confidence` is a Python float; `aib.confidence` is `NUMERIC(3,2)`. psycopg2 binds the float as `float8`, and PostgreSQL casts `numeric >= float8` losslessly via implicit promotion. No precision concern at 0.01 granularity — `0.6` is representable exactly enough that the floor is sharp. Stylistic: nothing to fix.

- [ ] **Tuple default for `cross_filter_slugs`** (`src/docket/services/query.py:761`) — implementer correctly used `tuple` instead of `list` to dodge the mutable-default-argument bug. Spec said `list[str]`. Tuple iteration is functionally identical for the `for cross_slug in cross_filter_slugs` loop. Documented in commit message. NIT only.

- [ ] **Helper is single-connection** (`src/docket/services/query.py:731-744`) — `resolve_significance_threshold` opens its own `db_cursor()`, then `list_items_by_badge` opens a second one for the main query. Two round-trips and two snapshots. At F1's scale (one helper call per page render) this is fine; phantom-read concern is theoretical (an admin would have to update `priority_badges_config.matcher_hints_override` between the two queries inside one HTTP request). Plausible to fold the threshold lookup into the main query as a CTE or LATERAL join, but not worth the readability cost. NIT only.

## Audit notes

Investigations that came back clean:

- **Index match (decision #92):** `idx_agenda_item_badges_city_slug_conf (city_id, badge_slug, confidence DESC)` exists in migration 013 line 263-264 exactly as the implementer claims. F1 predicates `aib.city_id = %s AND aib.badge_slug = %s AND aib.confidence >= %s` walk this index in column order with `confidence DESC` letting the planner range-scan from the high end down to the floor. Optimal.

- **Cross-filter EXISTS index coverage:** `idx_agenda_item_badges_item (agenda_item_id)` (migration 013 line 245-246) covers the EXISTS subquery's `x.agenda_item_id = ai.id` lookup. `badge_slug` filter inside each item-group is at most a handful of rows (an item rarely carries more than 5-10 badges), so per-EXISTS cost is constant.

- **ORDER BY sort cost at scale:** memory note says ~37K LLM-eligible items per city. Badge selectivity will further trim that — spec §5.7 expects 100s-1000s of items per badge per city. With LIMIT 25 and an in-memory sort over the post-filter set, this is sub-millisecond even worst-case. EXPLAIN at synthetic scale was already established as a Track 3 prerequisite (memory note: synth-172K-row scale satisfied Railway EXPLAIN gate); F1 is well within that envelope.

- **Spec §6.5 deviation: `m.city_id` is wrong, `aib.city_id` is right.** Spec line 3007 reads `WHERE m.city_id = %s` but `meetings.city_id` does not exist (the schema column is `municipality_id`; see `tests/integration/test_list_items_by_badge.py:82` which inserts `(municipality_id, ...)` directly). The implementer's choice of `aib.city_id` is both schema-correct and more index-friendly. The spec itself needs a follow-up patch. **Action item:** open a spec-fix ticket to update §6.5 lines 3001-3030 to read `aib.city_id = %s` (matching the implementation) so the next reader doesn't trip on the same drift.

- **`badges` aggregate intentionally not populated on returned items:** confirmed safe. `_badge_row.html:15` short-circuits on `{% if item.badges %}` and `AgendaItem.from_row()` line 139 defaults to `[]` when the SELECT doesn't ship a `badges` key. Smart Brevity Card partials route through `_badge_row.html` for chip rendering; an empty list collapses cleanly with no header div. card_smart_brevity.html, card_v2_fallback.html, card_pending.html, card_degraded.html all degrade gracefully. Implementer's reasoning ("listing is already badge-scoped, redundant chips") is sound for the category-landing context.

- **Unknown badge slug → empty result:** confirmed harmless. `resolve_significance_threshold` returns `None` (no gate); the main query's `aib.badge_slug = 'no_such_badge'` then filters out every row because no badge matches the slug. Returns `[]`. F2 (route handler) is responsible for 404'ing on unknown slugs. Test `test_unknown_badge_slug_returns_empty` covers this.

- **Cost expectation of duplicate slug in cross-filter:** if a caller passes the primary badge_slug as a cross-filter (e.g. `list_items_by_badge(city, "blight", cross_filter_slugs=("blight",))`), the EXISTS subquery is a no-op (the primary JOIN already guarantees the row exists). Doesn't double-count, doesn't error. Not worth defending against in code.

- **No production INSERT site for `agenda_item_badges` exists yet** in the worktree (`grep -rn "INSERT INTO agenda_item_badges" src/`). Plan §C1 (line 1308-1331, 1366-1373) lays out the on-write pattern with `m.municipality_id` derivation. Phase 2 Tracks 1/2 will land those writers — once they ship, the integrity assumption underlying F1's `aib.city_id` filter has a concrete code path to verify against.
