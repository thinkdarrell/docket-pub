# F2 Review — Template, UX, Accessibility (Opus #2)
**Commit:** b2c93b0
**Reviewer scope:** Template structure, UX, accessibility, design-system fit, partial reuse
**Verdict:** REQUEST CHANGES

## Summary

The template is structurally faithful to the spec §6.5 ASCII layout: 5 sections in
the right order (header → KPI strip → volume timeline → filter controls → item list →
load more), `extends "base.html"`, blocks named `title` + `content` matching parent
conventions, leans on the existing dispatcher partial for per-item rendering, and
defensively handles empty `cross_filters`. The Smart Brevity dispatcher choice is
correct for a v3-only surface (no `SMART_BREVITY_UI` gate).

Two REQUIRED issues block prod-quality release: (1) the empty-state body leaks
internal codenames "Wave 0", "Track 1", "D2" to citizen-facing copy, and (2) the
KPI strip will render with broken visual rhythm because `.kpi-grid` is locked to
4 columns but F2 ships 2-3 KPIs, leaving the bottom rule with phantom empty cells.

The remaining items are SUGGESTED design-system polish + accessibility nits, plus
one consistent test-coverage gap (template content is asserted only via a couple
of substring matches; KPI formatting, mayor-priority rendering, "Clear filters"
visibility, badge.icon, and the empty-state copy are all unverified).

## REQUIRED

- [ ] **Empty-state copy leaks internal jargon to citizens.**
  `src/docket/web/templates/category_landing.html:153-162` —
  > "Wave 0 has classified items but the matchers that assign priority badges
  > (Track 1 / D2) haven't shipped production results — items will start
  > appearing as the backfill runs."
  "Wave 0", "Track 1", and "D2" are internal project codenames — a citizen has
  zero context for them. Implementer also flagged this. Replace with citizen-
  facing language, e.g.:
  > "No items match this badge yet. As Birmingham's agendas are processed,
  > items tagged with this priority will appear here."
  Hide the "matchers haven't shipped" framing entirely — it'll read as broken
  software to a journalist, not transparency.

- [ ] **KPI grid renders broken with 2-3 cells against a 4-column grid.**
  `src/docket/web/templates/category_landing.html:32-57` ships 2 KPIs (or 3 with
  `mayor_priority_quote`), but `static/layout.css:169-175` defines
  `.kpi-grid { grid-template-columns: repeat(4, 1fr); border-bottom: 2px solid var(--ink); }`.
  Result: a bold ink border underlines 1.5–2 columns of empty space to the
  right of the last KPI cell, since `.kpi:last-child { border-right: 0; }` only
  affects the empty-cell column, not the underline. Compare to `city.html`
  which always ships exactly 4. Fix options:
  1. Add a category-specific class `kpi-grid--category` with
     `grid-template-columns: repeat(auto-fit, minmax(220px, 1fr))` and use it on
     this page only.
  2. Inline `style="grid-template-columns: repeat({{ 3 if kpis.mayor_priority_quote else 2 }}, 1fr);"`.
  3. Pad with a third "Most recent" KPI so the row always has 3 cells, then
     ship a `repeat(3, 1fr)` variant.
  Either way, do not ship the 4-column grid with 2 cells.

## SUGGESTED

- [ ] **Empty-state copy "Volume timeline / Coming soon" h2 is the wrong
  heading text.** `category_landing.html:71-74` — eyebrow says "Volume
  timeline" but the h2 says "Coming soon". Screen-reader users hit
  "Heading level 2: Coming soon" with no semantic anchor for what's coming.
  Move "Coming soon" into the body copy and make the h2 say "Volume
  timeline" — or omit the section entirely until F3. The current shape forces
  a placeholder section with `padding: 48px 0` and a bottom rule that splits
  the page visually for no payoff.

- [ ] **Filter section h2 reads as a filter label, not a section title.**
  `category_landing.html:98-104` — when no filters are active the h2 is
  "All confidence", and when filters are active it's "Showing items also
  tagged". Both read as filter UI, not page structure. Screen readers
  announce "Heading level 2: All confidence" which is confusing. Suggest
  always-h2="Filters" (already in the eyebrow) and move the dynamic copy to a
  paragraph below, e.g. `<p class="t-meta">Showing items also tagged</p>`.

- [ ] **Heading text "of many" is unidiomatic.** Line 133:
  `{{ items | length }} item{{ 's' if items | length != 1 else '' }} {% if next_offset %}of many{% endif %}`.
  "25 items of many" reads oddly. Use "(showing first 25)" or
  "(more available)" — and ideally surface the real total via the listing
  query rather than the placeholder phrase. Spec doesn't pin this; you have
  latitude to write it well.

- [ ] **Cross-filter chips are read-only and not individually removable.**
  `category_landing.html:114-122` — each chip is a `<span>`, not an `<a>`.
  Users can only "Clear filters" wholesale; they can't drop a single
  cross-filter while keeping the rest. Implementer flagged this is a
  read-only summary until F4. Acceptable for F2 scope, but flag in the F4
  ticket: each chip should be a link to the same page with that filter
  removed from `?and=...`. Without this, multi-filter UX is "clear all + re-
  apply", which is hostile.

- [ ] **Cross-filter chip labels rendered via string transform, not the
  badge-resolution helper.** Line 118: `{{ cf | replace('_', ' ') | title }}`
  hand-rolls "housing_stability" → "Housing Stability". This bypasses any
  city-specific `name_override` from `priority_badges_config`. If the user
  applies `?and=housing_stability` and Birmingham overrode that badge to
  "BHM Housing Watch", the chip will still say "Housing Stability". Fix:
  for each cross-filter slug, look up the resolved name (could be a route-
  level pre-fetch or a Jinja filter that wraps `get_resolved_badge`).

- [ ] **".rail-link" is the wrong design-system class for a centered
  call-to-action.** Lines 168-178: the load-more `<a>` uses
  `class="rail-link"` which is defined in `layout.css:439-446` for the
  side-rail's vertical link list (display: flex, justify-content: space-
  between, narrow padding, soft border). Putting it inline-block with
  `min-width: 200px` in main flow looks like a borrowed component. Suggest
  adding a `.load-more-btn` class to one of the stylesheets, or reusing
  `.feed-filter` (which is already designed for an inline chip-button).
  Lower priority since `.rail-link` does render usably; flag for cleanup.

- [ ] **`feed` section padding amplifies the placeholder timeline's
  emptiness.** With volume timeline rendered as just an h2 + paragraph + a
  truly empty `<div class="timeline-placeholder">` (no CSS hook lands its
  visual style — see grep below), the section is mostly whitespace between
  hero and filters. Either give `.timeline-placeholder` a min-height with a
  light background pattern, or omit the section in F2 and re-add it in F3.

- [ ] **Inconsistent `<div class="feed-head">` vs `<header class="feed-head">`
  within F2.** Line 70 uses `<div>`, lines 95 and 127 use `<header>`. The
  `<header>` is semantically better (each section header). Pick one — prefer
  `<header>` everywhere — and update line 70.

- [ ] **Test coverage gap: template content is asserted only via 4-5
  substring matches in `tests/integration/test_category_landing.py`.**
  Missing assertions:
    - `kpis.total_dollars` rendered as `$15,000` (verify `format_dollars`
      filter is wired correctly when amount is non-zero).
    - `mayor_priority_quote` rendered when truthy, hidden when None.
    - "Clear filters" link present when `cross_filters` is non-empty,
      absent when empty.
    - `badge.icon` appears in HTML when set on the template.
    - Empty-state copy renders when `items=[]`.
    - `?and=...&offset=...` URL form is correctly emitted (vs `?offset=...`
      when no cross-filters).
  Today the integration test catches "did the page 200" but would not catch
  e.g. someone replacing `format_dollars` with `format_date` in the KPI
  strip. Add 4-6 light template-content assertions.

- [ ] **KPI strip is a candidate `partials/kpi_strip.html` for reuse.**
  city.html (lines 26-47), category_landing.html (lines 32-57), and the
  forthcoming admin pages all repeat the `.kpi-grid > .kpi > .kpi-label /
  .kpi-value / .kpi-sub` shape. If F4/F5 add another category-style page,
  the duplication grows. Lift to a partial that takes a list of dicts:
  `[{label, value, sub, accent?, warn?}]`. Not blocking F2.

- [ ] **Cross-filter chip row is a candidate `partials/cross_filter_chips.html`
  for reuse.** F4 will iterate on this same UI (with HTMX), and the city
  homepage may also surface a chip row. Lifting it now is cheap and lets F4
  swap behaviour without re-doing markup.

## NIT

- [ ] **Inline styles instead of CSS classes for the KPI mayor-priority
  font sizing.** Line 51: `style="font-size: 18px; line-height: 1.3;"`. Fine
  for now, but the KPI grid has `.kpi-value { font-size: 38px; }` as the
  baseline; a quote shouldn't visually share the "huge number" treatment.
  Add a `.kpi-value--quote` modifier when the design pass lands.

- [ ] **`?offset=N` pagination diverges from the rest of the codebase.**
  `meetings.html:92,95` uses `?page=N&type=...`; F2 uses `?offset=N`. Spec
  doesn't pin this either way and F4/F5 may iterate on URLs. Flag for
  consistency review at the end of F-track.

- [ ] **`{{ badge.kind | title }} badge`** at line 19 turns `policy` →
  "Policy badge" and `process` → "Process badge". For citizens "Policy
  badge" / "Process badge" is engineering jargon — they only see the icon +
  name and don't care about kind. Suggest dropping the kind word or
  replacing with neutral text like "Birmingham priority area" / "Birmingham
  council practice". Lower priority since the design pass may rework the
  hero anyway.

- [ ] **`badge_chip` partial is NOT reused for the cross-filter chips.**
  The dedicated `partials/badge_chip.html` (used by `_badge_row.html`)
  produces `.badge-chip` markup with confidence-aware styling. F2 hand-
  rolls a `<span class="badge-chip">` without going through the partial.
  If `badge_chip.html` evolves (e.g. ARIA labels added), the cross-filter
  chips will silently miss the change. Use the partial — it'll likely
  warrant minor refactoring of the partial's expected context.

- [ ] **`cursor: pointer` on KPI cells with no click handler is a small
  accessibility lie.** `static/layout.css:180` sets `cursor: pointer` on
  `.kpi`, plus a hover-background transition. Sighted users will try to
  click. Pre-existing pattern (city.html does the same), but worth
  flagging for the design pass — `.kpi-grid` cells should either become
  buttons (with real handlers) or lose `cursor: pointer`. Not new in F2.

## Audit notes

### A. Template structure & spec fidelity
- All 5 spec §6.5 sections present and in the right order.
- `{% extends "base.html" %}` at line 1, no masthead/footer duplication.
- Block names `title` + `content` match `base.html:7,26`.
- F3 stub gracefully degrades with `{% if timeline %}` — F3 lands the real
  partial as a one-line swap. Good forward compatibility.

### B. Smart Brevity Card include
- Uses `partials/smart_brevity_card.html` (the dispatcher, not a leaf
  variant). Correct.
- Includes pass `item` via the Jinja `for` loop's implicit context plus
  `municipality` from the route. Card_smart_brevity then re-aliases
  `municipality` → `city` for `engagement_strip.html`. This works.
- F2 deliberately skips the `SMART_BREVITY_UI` flag gate (route is v3-only).
  The dispatcher itself routes per-item between v3/v2/pending, so v2
  fallback works for items pre-Phase-3 backfill. Acceptable.

### C. Empty state quality
- Two empty-state branches: empty `items` (line 152-163) and empty
  `cross_filters` (no chips rendered, no Clear filters link). Both render
  gracefully without 500.
- KPI strip when `item_count == 0` and `total_dollars == 0`: shows `0` and
  `—` respectively. The em-dash for dollars is good (clearer than `$0`).
- Filter chips when `cross_filters == []`: the entire `.cross-filter-chips`
  div is hidden via `{% if cross_filters %}`. Good.
- See REQUIRED #1 for the citizen-jargon issue.

### D. Accessibility (WCAG 2.1)
- Heading hierarchy: h1 (badge name) → h2 ("Coming soon" / filter label /
  item count). No skipped levels but two of the h2s are oddly worded
  (SUGGESTED).
- Decorative icons: `aria-hidden="true"` on the badge-icon span at line 22
  ✓; `aria-hidden="true"` on `.timeline-placeholder` ✓. The `↓` glyph in
  the load-more link (line 176) is NOT aria-hidden, so it'll be announced
  as "down arrow" — minor cosmetic SR noise.
- "Clear filters" is `<a>` ✓; load-more is `<a>` ✓. Both work without JS.
- Cross-filter chips are `<span>`, not links — see SUGGESTED #4.
- Color contrast: `.badge-chip.badge-conf-medium` and `.badge-conf-high`
  contrast ratios are defined in `static/css/smart_brevity.css`; F2 uses
  the bare `.badge-chip` class for cross-filter chips, which only gets the
  default `rgba(0,0,0,0.05)` background — should be readable but unverified
  against the page's `--paper` background.
- F2 does NOT follow the dollar-tier sr-only pattern — but that's OK, the
  KPI strip's dollar amount is sighted-only labeled (the `kpi-label` says
  "Total dollars" so SR users get context). No regression.

### E. Design-system fit
- Typography: uses `t-display`, `t-eyebrow`, `t-meta`, `t-mono`, `t-tnum`,
  `t-label` — all existing tokens from `static/styles.css`. No hand-rolled
  fonts.
- Color tokens: relies on existing `.kpi.is-accent` modifier; no new color
  literals introduced.
- No new `<link>` to font CDNs added — base.html already loads them. ✓
- KPI grid mismatch is the headline issue — see REQUIRED #2.

### F. URL / "load more" behavior
- Load-more URL correctly omits `and=` when `cross_filters` is empty:
  `?{% if cross_filters %}and=...&{% endif %}offset=N` produces
  `?offset=25` cleanly. Implementer's flagged "annoying leading equals"
  concern is wrong — the conditional already prevents it.
- `?offset=N` divergence from rest of codebase — see NIT #2.

### G. Cross-filter chip UX
- "Clear filters" link points at `url_for('public.category_landing', ...)`
  with no query args — produces a clean URL. ✓
- No fake "▼" dropdown arrows — chips are honestly chips, not pretending to
  be selects. ✓
- Multiple cross-filter slugs: each gets its own `<span class="badge-chip">`
  via the `for cf in cross_filters` loop. ✓ (But not individually
  removable — see SUGGESTED #4.)

### H. Test coverage gaps (template-side)
- See SUGGESTED #9 for the full list.

### I. Reusable partials
- KPI strip and cross-filter chip row are both candidates — see SUGGESTED
  #10 and #11.
- `badge_chip` partial NOT reused for the cross-filter chips — see NIT #4.

### Sanity checks performed
- Read full template `category_landing.html` (181 lines).
- Confirmed `partials/smart_brevity_card.html` is the dispatcher (19
  lines, branches on processing_status / data_quality / ai_rewrite_version).
- Confirmed `card_smart_brevity.html` aliases `municipality` → `city` for
  `engagement_strip.html`.
- Cross-checked `.kpi-grid` CSS in `static/layout.css:169-175` (4-column
  fixed) vs F2's 2-3 cells.
- Cross-checked `.rail-link` CSS (`layout.css:438-447`) — designed for
  side rail, repurposed for main-flow load-more.
- Cross-checked `?offset=N` vs `meetings.html`'s `?page=N` pattern.
- Read full integration test file
  `tests/integration/test_category_landing.py` (~604 lines) for assertion
  coverage; confirmed only ~5 body substring matches.
