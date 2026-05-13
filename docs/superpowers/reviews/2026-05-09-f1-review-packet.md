# F1 Review Packet — `list_items_by_badge`

**Commit under review:** `d5b6d62`
**Branch:** `feat/impact-first-phase-2-track-3`
**Date:** 2026-05-09
**Pipeline:** Opus implementer + 2 parallel Opus reviews + Sonnet 4.6 cross-model second-look

## Verdict roll-up

| Reviewer | Verdict | REQUIRED | SUGGESTED | NIT |
|---|---|---|---|---|
| Opus #1 (SQL & semantics) | APPROVE | 0 | 5 | 3 |
| Opus #2 (tests & helper API) | APPROVE | 0 | 9 | 4 |
| Sonnet 4.6 (cross-model) | REQUEST CHANGES | **3** | 4 | 3 |

The cross-model gap is the headline: **all three of Sonnet's REQUIREDs are issues that one or both Opus reviewers downgraded to SUGGESTED or treated as deferred-to-spec-fix.** Sonnet's E6 superpower (catching what Opus systematically misses) replicated here. Triage below leans on the converged findings.

## Category 1 — Convergent findings (REQUIRED to address before reviewer sign-off)

### F1-R1. Add the in-Python wrapper the spec named, alongside the SQL helper

**Severity:** REQUIRED (Sonnet) / SUGGESTED (Opus #2 forward-looking)
**Files:** `src/docket/services/query.py:699-757`
**Spec line:** §6.5 line 3037

Spec explicitly named the shared helper `apply_policy_significance_gate(items, badge_slug, city_id) -> list` — an in-Python filter for the **3** call sites: this listing (SQL-pushdown), search-narrowing (SQL-pushdown), and **Smart Brevity Card chip rendering** (per-item, per-badge, in a Jinja loop). Implementer built `resolve_significance_threshold(city_id, badge_slug) -> int | None` instead — a SQL-fragment helper. The chip-loop call site (G-track) cannot use a SQL fragment; it needs Python-side list filtering.

**Fix (additive, low cost):** Keep `resolve_significance_threshold` (it's the right shape for SQL pushdown). Add a thin wrapper:

```python
def apply_policy_significance_gate(items, badge_slug, city_id):
    """In-Python list filter, for callers that have items in memory (chip rendering)."""
    threshold = resolve_significance_threshold(city_id, badge_slug)
    if threshold is None:
        return list(items)
    return [it for it in items if (it.significance_score or 0) >= threshold]
```

Add a unit test for each branch (process → no filter, policy → filters by threshold, unknown slug → no filter).

### F1-R2. JSONB whole-object COALESCE silently drops matcher defaults

**Severity:** REQUIRED (Sonnet) / SUGGESTED w/ "matches spec, foot-gun for matchers" caveat (Opus #1)
**Files:** `src/docket/services/query.py:735` (helper SQL)
**Test path that creates the dangerous fixture:** `tests/integration/test_list_items_by_badge.py:172-183`

`COALESCE(c.matcher_hints_override, t.default_matcher_hints)` returns the *whole* override JSONB if non-NULL. A city setting `matcher_hints_override = {"min_significance": 7}` silently loses every other default key (`keywords`, `action_types`, `topics`, `excluded_action_types`). For F1 (which only reads `min_significance`) this is benign — but the helper's SQL is what Track 1 / D2 matchers will copy when they read keywords. The integration test fixture writes exactly the dangerous shape (`{"min_significance": 7}` as the entire override), exercising the bug path without detecting it.

**Fix:** Switch to per-key JSONB merge, defaults first then overrides win on duplicate keys:

```sql
COALESCE(t.default_matcher_hints, '{}'::jsonb) || COALESCE(c.matcher_hints_override, '{}'::jsonb)
```

Add a test that overrides only `min_significance` and asserts the other default keys still resolve.

### F1-R3. Spec §6.5 line 3007 has a column that doesn't exist

**Severity:** REQUIRED (Sonnet) / Action item (Opus #1)
**File:** `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md:3006`

Spec pseudocode reads `WHERE m.city_id = %s`, but `meetings` has `municipality_id`, not `city_id`. The implementer correctly used `aib.city_id` (which is also more index-friendly — hits `idx_agenda_item_badges_city_slug_conf` from decision #92). The spec needs a correction so the next reader (F2 author) doesn't trip.

**Fix:** Patch spec §6.5 lines 3001-3030 to read `aib.city_id = %s`. Add a one-line note explaining the index-selectivity rationale. This is a separate commit on the spec — does not require touching `query.py`.

## Category 2 — Recommended SUGGESTED to take during fix-up

### F1-S1. Add boundary tests for `confidence` and `significance_score` thresholds

**From:** Sonnet, Opus #2
**File:** `tests/integration/test_list_items_by_badge.py`

Add four cheap tests:
- `confidence=0.60` with `min_confidence=0.6` → included (>= boundary)
- `confidence=0.59` with `min_confidence=0.6` → excluded
- `significance_score=3` with default policy gate → included (>= boundary)
- `significance_score=2` with default policy gate → excluded (already covered, keep as control)

A `>` typo in either predicate would silently pass all current tests; boundary tests pin it.

### F1-S2. Add fallback test: city has no `priority_badges_config` row

**From:** Opus #2
**File:** `tests/integration/test_list_items_by_badge.py`

Helper docstring promises fallback to `default_matcher_hints` when no city config row exists. No test exercises this. Insert a test-only municipality without an opt-in row and assert `resolve_significance_threshold` still returns the default (3).

### F1-S3. Match `extracted_facts` projection to `list_agenda_items`

**From:** Opus #2
**File:** `src/docket/services/query.py:834`

`list_items_by_badge` selects the full `ai.extracted_facts` blob; `list_agenda_items` extracts lean keys via `jsonb_extract_path`. Both feed Smart Brevity Card partials, so divergence means the F2 category landing page ships heavier payloads than the meeting-detail page. Either match the lean projection, or document the divergence in the docstring.

### F1-S4. Add `list[str]` cross-filter test (Flask route contract)

**From:** Opus #2, Sonnet
**File:** `tests/integration/test_list_items_by_badge.py`

F2's planned route does `request.args.get('and', '').split(',')` → `list[str]`. All current tests pass tuples. Either add one test passing a list, or relax the annotation to `Sequence[str]`.

## Category 3 — Defer (SUGGESTED + NIT)

These are real but not blocking F1. Either Phase 2 hygiene or follow-up tickets:

- **City-id integrity guard** (Opus #1) — no DB-level CHECK/trigger preventing `aib.city_id ≠ meetings.municipality_id`. Defer until C1/D2 ship the production INSERT path; revisit then.
- **N+1 in chip-rendering call site** (Opus #2) — only matters when G-track lands. Add `resolve_significance_thresholds(city_id, slugs) -> dict` as a sibling helper, or per-request memoization. Open a G-track ticket; F1 doesn't need it.
- **`processing_status = 'completed'` literal cast inconsistency** (Opus #1) — works fine; stylistic. Take during a future cleanup pass if at all.
- **Cross-filter same-as-primary slug regression test** (Opus #2) — harmless no-op today; pin if a SQL refactor lands.
- **Pagination tests for `limit=0` and offset-past-end** (Opus #2, Sonnet) — defensive; F2 route handler will surface bad inputs anyway.
- All four NITs across reviewers (helper docstring cross-reference, `Iterable[str]` typing, double-check teardown leak, test docstring polish).

## Category 4 — Spec follow-ups (separate from F1 fix-up)

Single spec-patch commit on `feat/impact-first-phase-2-track-3` (or directly on `main` later):

1. Spec §6.5 line 3007: `m.city_id` → `aib.city_id` with rationale.
2. Spec §6.5 line 2976: `cross_filter_slugs: list[str] = ()` → `tuple[str, ...] = ()` (or `Iterable[str]`).
3. Spec §6.5 line 3037: name the helper `apply_policy_significance_gate` AND document `resolve_significance_threshold` as the SQL-pushdown sibling.
4. Spec §5.1 line 1943: change override semantics from `or` (whole-object replace) to per-key `||` merge, document precedent.

## Recommendation

Take all of Category 1 (3 REQUIREDs) plus Category 2 (4 SUGGESTEDs) in a single fix-up commit. Open a separate spec-patch commit for Category 4. Defer Category 3.

Estimated fix-up scope: ~30 LOC implementation + ~80 LOC tests + 1 spec patch commit.
