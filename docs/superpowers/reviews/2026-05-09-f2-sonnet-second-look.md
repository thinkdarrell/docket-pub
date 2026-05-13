# F2 Second-Look — Sonnet 4.6
**Commit:** b2c93b0
**Reviewer angle:** Cross-model (test fidelity, spec drift, content/UX, off-by-one, XSS-via-slug)
**Verdict:** REQUEST CHANGES

## Summary

Two REQUIRED issues that Opus is likely to miss: (1) **KPI count semantically diverges from list count** — `category_kpis` does not apply the significance gate that `list_items_by_badge` does, so the "Items this year: N" KPI strip can show a higher number than items actually rendered on the page for policy badges. (2) **Citizen-visible internal jargon** in the empty-state copy ("Wave 0 has classified items but the matchers that assign priority badges (Track 1 / D2) haven't shipped") is rendered directly to any public visitor when a city's badge page has zero results — this is live on deploy with no feature flag gate.

The test suite has real fidelity gaps (empty-state test checks `status 200` twice and page title, never the empty-state div or its copy; pagination test never validates which items appear on each page), but the tests aren't wrong-for-the-wrong-reason — they're just shallow.

## REQUIRED

- [ ] **KPI count diverges from rendered list for policy badges** — `category_kpis` filters by `confidence >= 0.6` and `processing_status = 'completed'` but does NOT apply `resolve_significance_threshold`. `list_items_by_badge` (via `resolve_significance_threshold`) adds `AND ai.significance_score >= N` for policy badges (e.g. `blight_accountability` has `min_significance=3` from migration 013 seeds). A citizen sees "Items this year: 47" in the KPI strip but only 31 items in the list below — the 16 items below the threshold are counted but not shown. Fix: `category_kpis` must call `resolve_significance_threshold(city_id, badge_slug)` and, when non-None, add the same `AND ai.significance_score >= %s` predicate that `list_items_by_badge` does. _Opus blind spot: Opus audits one commit at a time and both helpers appear correct individually; the cross-task semantic drift only emerges by reading F1 and F2 together._

- [ ] **Citizen-visible internal jargon in empty-state copy** — `category_landing.html` lines 158-161: `"Wave 0 has classified items but the matchers that assign priority badges (Track 1 / D2) haven't shipped production results — items will start appearing as the backfill runs."` This text is rendered unconditionally when `items` is empty. The route has no `SMART_BREVITY_UI` flag gate and no other gating — it's live the moment this commit ships. Any citizen visiting `/al/birmingham/blight_accountability/` before D2 backfill runs sees "Wave 0", "Track 1 / D2", "backfill" in production. Fix: replace with citizen-facing copy such as `"No items have been tagged with this badge yet. Check back as we continue reviewing meeting records."` _Opus blind spot: Opus focus on code correctness; content review of empty-state copy in a template is not a natural Opus audit path._

## SUGGESTED

- [ ] **`test_route_empty_state_renders_gracefully` asserts `rv.status_code == 200` twice and only `"Blight Accountability" in body`** — the test never checks that the empty-state `<div class="empty-state">` or the "No items yet" text is present. A regression that crashed on empty `items` (e.g., a template `{{ items[0] }}` reference) could still return 200 for some states. Suggested fix: also assert `"No items yet" in body` or `"empty-state" in body`. The double `assert rv.status_code == 200` at lines 586 and 590 is also a dead duplicate.

- [ ] **`category_kpis` hardcodes `confidence >= 0.6` as a literal rather than sharing the default from `list_items_by_badge`'s `min_confidence=0.6` parameter** — if the default confidence threshold is ever adjusted in `list_items_by_badge`, `category_kpis` will silently drift. Consider extracting to a module-level constant `_DEFAULT_BADGE_CONFIDENCE = 0.6` shared by both helpers.

- [ ] **`year=2026` hardcoded in route + `"tagged in 2026"` literal in template** — the route passes `year=2026` to `category_kpis` and the template renders the sub-label "tagged in 2026" (line 36) and "stated 2026 priority" (line 54). In 2027, KPIs will silently show 2026 data while saying "Items this year." The implementer flagged this; it deserves at minimum a `TODO(F2): derive year from date.today().year` comment in the route, or a concrete fix now: `year=date.today().year`. The `date.today()` import is already present inline in the same route function. _Note: the `date(2026, 12, 31)` end-date for `badge_volume_series` has the same 2027 expiry problem._

- [ ] **`test_route_pagination_offset` never validates which items appear on which page** — the test inserts 26 items and checks `"offset=25" in body` for page 1 and `"offset=50" not in body` for page 2, but never asserts that page 2 shows item 26 and page 1 doesn't. A bug that returned all 26 items on page 1 (ignoring limit) would pass both assertions. Suggested: assert `"Item-Number-25" not in body` for page 1, `"Item-Number-25" in body2` for page 2.

- [ ] **`from datetime import date` inside the route body (line 239)** — Python caches module-level imports on first load; an inline import inside a hot request handler is a code smell even though it doesn't re-import on every call. Move to the module's top-level `import` block alongside `from flask import ...`.

## NIT

- [ ] **`next_offset` off-by-one on exactly-25 case** — implementer's own note: when exactly 25 items exist total, page 1 shows 25, sets `next_offset=25`, user clicks "Load more", page 2 returns 0 items with an awkward "No items yet" empty state. The standard fix is `LIMIT 26` and `show_more = len(items) > 25; items = items[:25]`. Not blocking: the behavior is well-documented and not broken, just slightly awkward UX. Worth a `# NOTE:` comment in the route at minimum.

- [ ] **`test_route_empty_state_renders_gracefully` does not insert any badge rows** — the test relies on an empty `agenda_item_badges` table for Birmingham's `blight_accountability` badge in a clean test run, which is true by fixture isolation. This works correctly; just note that it's implicitly relying on the absence of badge rows, not explicitly creating a zero-match condition (e.g., items that exist but don't carry the badge). Works fine, but a future test-data cleanup that seeds badge rows globally could make this test flaky.

## Things I checked that came back clean

- **`test_route_404_disabled_badge`** — `bag.set_enabled(...)` is called synchronously before the HTTP request. The DB commit happens inside `set_enabled`'s `with db()` context manager. The route's own DB connection is a fresh cursor. Correct sequencing confirmed.
- **Route ordering conflict** — verified with `app.url_map` inspection: `/al/<slug>/meetings/`, `/al/<slug>/council/`, `/al/<slug>/_rail/default` etc. are all correctly routed to their specific handlers. Flask's Werkzeug router gives static path segments priority over variable segments — `meetings` beats `<badge_slug>` in the same position. No collision.
- **URL case-sensitivity** — `get_municipality(slug)` does `WHERE slug = %s AND active = TRUE` with no `LOWER()`. `/al/Birmingham/blight_accountability/` correctly returns 404 (no redirect). This is a deliberate behavior choice with a correct 404, not a silent failure. Acceptable since slugs are generated from city names at migration time and are always lowercase.
- **XSS via `badge_slug` or `cross_filter` chip** — Jinja auto-escape confirmed active: `<script>alert(1)</script>` in `?and=` renders as `&lt;script&gt;` in the HTML attribute and text. `badge.slug` is used only in `url_for(...)` (Flask's `url_for` encodes the value), not rendered into CSS class names or HTML ids. Clean.
- **`test_route_cross_filter_filters_items`** — correctly inserts both items and both badge rows before the request. Asserts both `"Both badges" in body` and `"Only blight" not in body`. This test has genuine assertive power for the cross-filter wiring. The `housing_stability` template is seeded in migration 013, and `priority_badges_config` for BHM includes `housing_stability` — badge insertion in the test goes to `agenda_item_badges`, not `priority_badges_config`, so no missing config issue.
- **`get_resolved_badge` three-None-case collapse** — deliberate and correct. All three cases (unknown template / no config row / disabled config) map to 404 via the `None` sentinel. Spec §6.5 says "404 if badge is not active for this city" — this is correct.
- **`badge_volume_series` stub** — returns `[]`. Template `{% if timeline %}` evaluates falsy on `[]`. The timeline placeholder section renders. F3's real implementation will return a non-empty list, flipping the branch. This is the intended forward-compat mechanism and it works.
- **SQL parameterization** — all SQL in `get_resolved_badge`, `category_kpis`, `list_items_by_badge` uses `%s` placeholders with psycopg2 cursor. No f-string SQL or string interpolation. Safe from SQL injection.
