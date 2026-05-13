# F2 Review Packet — Category Landing Route + Template

**Commit:** `b2c93b0`
**Branch:** `feat/impact-first-phase-2-track-3`
**Date:** 2026-05-09
**Pipeline:** Opus implementer + 2 parallel Opus reviews + Sonnet 4.6 cross-model second-look

## Verdict roll-up

| Reviewer | Verdict | REQUIRED | SUGGESTED | NIT |
|---|---|---|---|---|
| Opus #1 (route + helpers + security) | APPROVE w/ suggestions | 0 | 5 | 4 |
| Opus #2 (template + UX + accessibility) | REQUEST CHANGES | 2 | 11 | 4 |
| Sonnet 4.6 (cross-model) | REQUEST CHANGES | 2 | 5 | 2 |

The cross-model gap shows up in TWO directions this time:
- **Opus #1 → Sonnet promotion**: Opus #1 downgraded the KPI/list count divergence to SUGGESTED ("latent — admin tooling concern"); Sonnet correctly traced it back to the F1+F2 cross-task semantic and flagged REQUIRED.
- **Opus #2 → unique find**: Opus #2 caught a CSS grid layout break (4-column grid renders 2-3 cells, leaves phantom underline gaps) that neither Sonnet nor Opus #1 saw — UX/visual review is Opus #2's specific lane.

Three REQUIREDs to address, all convergent.

## Category 1 — REQUIRED

### F2-R1. KPI count diverges from rendered item count for policy badges

**Severity:** REQUIRED (Sonnet) / SUGGESTED w/ "latent" caveat (Opus #1) — promoted
**File:** `src/docket/services/query.py` (`category_kpis` body)

`category_kpis` filters by `confidence >= 0.6` + `processing_status = 'completed'` only. `list_items_by_badge` additionally applies `resolve_significance_threshold` for policy badges (default `min_significance=3`). For `blight_accountability` (`min_significance=3` per migration 013 seed), items at significance 0-2 with confidence ≥ 0.6 are **counted in the KPI strip but not rendered in the list below**. Citizens see "Items this year: 47" with 31 cards. This is the F1↔F2 cross-task drift that Opus reviewers naturally miss.

**Fix:** Apply the same significance gate inside `category_kpis`. Either:
- Inline the check: call `resolve_significance_threshold(city_id, badge_slug)` and append `AND ai.significance_score >= %s` when policy
- Or factor a shared SQL fragment used by both helpers

Add a test that inserts a low-significance policy item and asserts `kpis.item_count == listed item count`.

### F2-R2. Citizen-visible internal jargon in empty-state copy

**Severity:** REQUIRED (Sonnet AND Opus #2)
**File:** `src/docket/web/templates/category_landing.html:153-162`

Empty-state body renders to any public visitor:
> "Wave 0 has classified items but the matchers that assign priority badges (Track 1 / D2) haven't shipped production results — items will start appearing as the backfill runs."

The route has no feature-flag gate; it's live at deploy time. "Wave 0" / "Track 1 / D2" / "matchers" / "backfill" are internal vocabulary citizens shouldn't see.

**Fix:** Replace with citizen copy. Suggested:
> "No items tagged for this category yet. Check back as we continue indexing meeting records."

Or split into admin-only vs public empty states (admin sees the diagnostic copy; public sees neutral language). The admin path is more work — recommend the simple replacement for v1.

### F2-R3. KPI grid breaks visually when fewer than 4 cells render

**Severity:** REQUIRED (Opus #2 only — caught by template lane)
**File:** `src/docket/web/static/layout.css:169` + `src/docket/web/templates/category_landing.html` (KPI strip)

`.kpi-strip` is defined as `grid-template-columns: repeat(4, 1fr)` with a `2px solid var(--ink)` bottom border spanning full width. F2's KPI strip ships only 2 cells (item_count + total_dollars; 3rd if mayor_priority_quote is truthy). Result: phantom empty cells on the right with the ink underline still drawn full-width — visual misalignment any citizen will see.

**Fix:** Either
- Add a category-specific class with `grid-template-columns: repeat(auto-fit, minmax(...))` or `repeat(N, 1fr)` where N is dynamic
- Pad to 3 KPIs always (e.g., add a "since YYYY" or "active years" tile)
- Use a different layout for category-landing KPIs (flex row, separate widths)

Recommend the auto-fit variant — most flexible, no template gymnastics.

## Category 2 — Recommended SUGGESTED to take during fix-up

### F2-S1. Strip whitespace from cross-filter slugs

**From:** Opus #1
**File:** `src/docket/web/public.py:218-219`

`?and=blight,%20housing_stability` (URL-encoded space) → `["blight", " housing_stability"]` — second token silently fails to match any badge. Fix: `[s.strip() for s in raw.split(",") if s.strip()]`. Worth landing before F4's HTMX dropdown ships.

### F2-S2. Replace hardcoded `year=2026` with `date.today().year`

**From:** All 3 reviewers
**File:** `src/docket/web/public.py` route + `src/docket/web/templates/category_landing.html` (any year display)

Trivial fix; prevents stale data when the year rolls over. If template displays "this year" semantically, no extra change needed. If it displays "2026" literally, swap to `{{ kpis.year }}` and pass the year through.

### F2-S3. Fix pagination boundary at exactly 25 items

**From:** Opus #1, Sonnet
**File:** `src/docket/web/public.py` route

Current logic: `next_offset = offset + 25 if len(items) == 25 else None`. If exactly 25 items exist total, `next_offset=25` is set, user clicks "load more", page 2 is empty. Fix: ask `list_items_by_badge` for `limit=26`, slice off the 26th, set `next_offset` only when 26 came back:

```python
items_plus_one = query.list_items_by_badge(..., limit=26, offset=offset)
items = items_plus_one[:25]
next_offset = (offset + 25) if len(items_plus_one) > 25 else None
```

### F2-S4. Improve "Coming soon" h2 SR text

**From:** Opus #2
**File:** `category_landing.html` (timeline placeholder)

`<h2>Coming soon</h2>` is bad screen-reader semantics — the heading shouldn't describe the loading state. Either drop the heading and use a `<p>` placeholder, or label the section: `<h2>Volume Timeline</h2>` + `<p>Visualizations coming soon.</p>`.

### F2-S5. Resolve cross-filter chip labels via `get_resolved_badge`

**From:** Opus #2
**File:** `category_landing.html` cross-filter chip render

Current chips use hand-rolled display names (probably title-casing the slug). `get_resolved_badge` already returns the proper `name` (with `name_override` applied). Loop the cross-filter slugs, resolve each via the helper, render the resolved name. This also surfaces city-specific overrides (e.g., Birmingham's "Blight Accountability" vs the generic template name).

Cost: one extra DB call per chip (or batch via a sibling helper). For F2 scope where cross-filter chips are typically 0-2, the per-call cost is negligible.

## Category 3 — Defer (NIT + low-impact SUGGESTED)

- **KPI strip + chip row → partials** (Opus #2) — premature; F2 is the only category landing right now. Extract when a second consumer appears.
- **Werkzeug literal-priority routing collision** (Opus #1) — future risk if a badge slug collides with `meetings`/`items`/`council`/`hearings.rss`. Phase 4 onboarding-time concern.
- **Test substring assertions are thin** (Opus #2) — tests check status codes more than rendered content. Take this when F2 fix-up tests are written anyway (S1-S5 all benefit from new template assertions).
- **`.rail-link` class wrong for centered CTA** (Opus #2) — cosmetic; replace with appropriate token.
- **Cross-filter chips lack individual remove links** (Opus #2) — UX nicety; F4 may rebuild this section anyway.
- **`get_resolved_badge` returns dict vs dataclass consistency** (Opus #1 NIT) — dict matches `get_municipality` precedent; dataclass migration is a refactor task.
- **All other NITs** across reviewers.

## Recommendation

Take all of Category 1 (3 REQUIRED) + Category 2 (5 SUGGESTED) in a single fix-up commit. Defer Category 3 entirely — none are blockers, and F4/F5/G-track will rebuild adjacent surface area anyway.

Estimated fix-up scope:
- ~30 LOC service-layer change (significance gate in `category_kpis` + helper sharing)
- ~40 LOC template content edits (empty state copy + grid fix + h2 + chip labels + year)
- ~50 LOC test additions (assertions for fixed behaviors + content)
- ~10 LOC route changes (whitespace strip, LIMIT 26 pagination, `date.today().year`)

One commit. ~130 LOC delta.
