# F4 Final Audit — Opus 4.7

**Commit:** b3789a3
**Posture:** Final auditor pass before user gate. Three prior reviews incorporated.

## Top-line verdict

The three REQUIREDs (R1, R2, R4) are confirmed with independent live evidence and are sufficient to unblock merge — but R2's recommended fix (`hx-select="#item-list"`) keeps the route doing a full server render on every filter change (KPIs, F3 timeline series, mayoral overlay, year ticks, item list, dropdown, plus 11 process+policy COUNTs… wait — those 11 are on `city_overview`, not `category_landing`). The actual extra cost on filter swap is `category_kpis` + `badge_volume_series` + `mayoral_term_overlay` + `year_ticks` + `list_items_by_badge` + `list_enabled_badges` + `resolve_badges`. That's the F3-helper N+1-on-filter-change cost the prior rounds did not quantify. I am NOT upgrading this to a REQUIRED — the helpers are individually cheap, the dropdown isn't a hot path, and partial-render is the spec-aligned cleaner fix that can land later. But I am adding it as SUGGESTED and ensuring the user is informed.

I am also adding **one new SUGGESTED** finding the three rounds missed: the BHM-centric badge legend on `city.html` references "policy, like blight or housing" on every city page, including the 3 non-BHM cities that render zero policy tiles (legend promises a category that doesn't exist on the page). This is a citizen-facing copy mismatch, parallel to Opus #2's S6 about the "Browse by priority" header but specifically about the legend prose.

## Re-verification of the three REQUIREDs

- **R1 (process-badge 404): CONFIRMED — scope corrected.** Live-reproduced 28/28 dead links across 4 cities × 7 process slugs (Birmingham, Mobile, Vestavia Hills, Homewood — Sonnet's "5 cities" appears to count Montgomery, but that city is not in the local DB; deployed-cities count is 4). Bonus finding: `mobile/blight_accountability` also 404s because Mobile has zero `priority_badges_config` rows — making the BHM-only "blight" control test in Sonnet's evidence slightly misleading (it 200s on BHM only). Root cause confirmed in `query.py:1017-1036`. The proposed LEFT-JOIN fix has **no downstream call sites** (R1 fix is safe): `get_resolved_badge` is grepped to one caller — `public.py:244` in `category_landing`. No admin/search/RSS path consumes it. The strict-config-required behavior was not load-bearing anywhere except `category_landing`'s 404 gate.

- **R2 (HTMX swap dumps full page): CONFIRMED.** No `hx-select` or `HX-Request` short-circuit anywhere in `src/` (verified via grep). Route extends `base.html` and always returns full HTML. The recommended `hx-select="#item-list"` is HTMX-2.0.4-correct: HTMX fetches the response, picks `#item-list` from the parsed body, and swaps. `hx-push-url` works orthogonally to `hx-select` — it pushes the request URL (not the response). One subtlety: with `hx-select` the response still contains the *new* `<select>` markup (with the post-change `selected` option), but that's nested inside `#item-list` only on the SERVER's render of the page-after-filter. Since the dropdown lives OUTSIDE `#item-list` (sibling section before the item list), the dropdown DOM is **not** updated on swap — the user's selection stays visually correct because the browser preserves the `<select>` element across the swap. Verdict: `hx-select="#item-list"` works, but the dropdown becomes "uncontrolled" after swap (its `selected` doesn't sync to URL state until a full page reload). For v1 this is acceptable; the full-page-reload bookmark path keeps it consistent.

- **R4 (aria-hidden grammar): CONFIRMED.** `city.html:34` reads "A ✨ means…" with the glyph `aria-hidden="true"`. AT users hear "A means…". Spec line 2745-2746 explicitly prescribes `aria-label="AI-verified"` for the Verification Spark (decision #67). The recommended copy is correct — `aria-label="AI-verified"` matches both decision #67 spec text AND the chip pattern at `partials/badge_chip.html:33`. I considered "Verification Spark" or "verification spark" as alternative copy (decision #74's term), but rejected: decision #67's "AI-verified" is the **rendering convention** for this glyph; decision #74 only introduces the legend feature, not a rename of the glyph's aria value. Use `aria-label="AI-verified"`.

## Downstream-effects audit

**a. R1 fix downstream.** Single call site (`public.py:244`). The proposed LEFT-JOIN fix returns one extra column (`enabled` is `NULL` for process badges with no config row), but the consumer (`category_landing`) only uses `slug`, `name`, `description`, `icon`, `kind` — all unaffected. No admin/search/RSS path reads the resolved badge. **Safe to relax.** New test (recommended in plan: process-badge 200 test) closes the regression-detection gap.

**b. R2 fix downstream — perf cost on filter change.** With `hx-select="#item-list"` the full route runs every filter swap. The full-route cost includes: `category_kpis` (1 query), `list_items_by_badge` (1 query, with EXISTS subqueries), `badge_volume_series` (1 query, monthly grouping over 5 years × badge), `mayoral_term_overlay` (1 query), `year_ticks` (pure Python), `list_enabled_badges` (1 UNION query), `resolve_badges` (1 query). That's ~6 DB queries per filter change. All hit indexed paths from migration 013 — single-digit-ms each at current scale. The Railway-OOM concern documented in project memory is for landing-page contested-vote/recent-vote JOINs, not this surface. **No upgrade to REQUIRED.** SUGGESTED follow-up: detect `HX-Request` and render only `partials/item_list.html` for HTMX requests — saves 4–5 DB queries per dropdown change, and avoids the "dropdown DOM not synced after swap" stale-state issue noted in R2 verification.

**c. R4 fix downstream — ✨ consistency.** Two render sites only: `partials/badge_chip.html:33` (uses `aria-label="AI-verified"`) and `city.html:34` (currently `aria-hidden="true"`). After R4 fix both use `aria-label="AI-verified"`. Two doc-comment occurrences (`city.html:19`, `_badge_row.html:7`, `badge_chip.html:11,19`) reference "Verification Spark" prose — those are HTML comments, no AT exposure. Post-fix consistency is clean.

**d. F4 + F3/F2 interaction (regressions).** Ran `tests/integration/test_f4_browse_by_priority.py`, `test_category_landing.py` (F2), `test_badge_volume_series.py` (F3): **70 passed, 0 failed in 4.61s**. F2 KPI strip and F3 SVG volume timeline are inserted ABOVE the new dropdown section in `category_landing.html` and are not affected by the dropdown markup. DOM order is correct.

**e. 5-city blind spots.** Three blind spots:
   1. **Non-BHM cities render Browse-by-Priority as 7-process-tile-only sections, ALL of which 404 (R1 multiplier).** R1 fix dissolves this.
   2. **Legend prose drift on non-BHM cities.** `city.html:24-35` legend reads "policy, like blight or housing" on every city, but Mobile/Vestavia/Homewood render zero policy tiles. Citizens see legend promising "policy" tiles, then no policy section. Parallel to Opus #2's S6 ("Browse by priority" header is policy-coded) but specifically about the legend's parenthetical examples. New finding (S8 below).
   3. **R1 fix unblocks process-badge category pages city-wide; need to confirm `list_items_by_badge` works for Mobile/Vestavia where process badges may have zero items.** Spot-checked: `list_items_by_badge(mobile_id, 'hidden_on_consent')` returns `[]` cleanly (no error). Empty-state UX falls through to F2's "No items found" treatment. Acceptable.

**f. _overview_cache correctness.** Verified by reading `public.py:62-139`: cache stores the post-`render_template` HTML string (line 138), AFTER the 11 COUNTs and the tile dicts are zipped into context. Cache hit returns the pre-rendered HTML with tiles included. **Sonnet's analysis is correct.** Cache key is `slug` only (no badge/year salt) — when the calendar year rolls over, stale cached HTML serves "this year" counts for the OLD year for up to 5 minutes. Acceptable v1 quirk. Note: `_overview_cache` does NOT cover the 11 COUNTs as a separate layer — they fire on every cache miss (TTL refresh) including post-deploy when the dict is reset. At 1 cache miss/5min/city × 4 cities = ~12 cache misses/hour = 132 COUNTs/hour worst case. Trivial.

## New findings (beyond the three rounds)

### REQUIRED (added or upgraded)

**None.** R1, R2, R4 plus the existing SUGGESTEDs are sufficient.

### SUGGESTED (added)

- **S8 (new) — Legend's "policy" parenthetical promises tiles non-BHM cities don't render.** `city.html:24-35` legend reads on EVERY city's homepage: "Badges flag oversight signals (process, like sole-source contracts or split votes) and city priorities (policy, like blight or housing). A ✨ means independent sources agree on the tag." On Mobile/Vestavia/Homewood, `city_policy_badges == []` so the policy grid is suppressed — but the legend still references "policy, like blight or housing." A citizen on Mobile reads the legend, then sees only "Process transparency / Oversight signals" tiles, all 404 (until R1 fix). After R1 fix, the legend still over-promises on non-BHM cities. Recommended fix options: (a) gate the policy parenthetical on `{% if city_policy_badges %}`, (b) reword the legend to be process-only-aware on non-BHM, or (c) accept the cosmetic mismatch on non-BHM since BHM is the lead city for v1. Confidence 70%.

- **S9 (new) — `hx-select="#item-list"` leaves the dropdown DOM unsynced after filter swap.** With the R2 fix as proposed, after a filter change the URL updates (hx-push-url) and `#item-list` re-renders, but the `<select>` element is preserved in-place by the browser — so its options list (which depends on `available_badges` excluding the current `badge_slug`) does NOT refresh. Functionally fine for v1 because the dropdown options don't change between filter swaps on the same primary badge (only `selected` changes, which the browser preserves correctly). But IF a future change introduces dynamic dropdown contents, this will become a bug. Document the constraint or move to `HX-Request` partial-render path (Sonnet's "cleaner fix"). Confidence 80%.

- **S10 (new) — `_overview_cache` has no per-year salt; tile counts go stale across calendar-year rollover.** Cache key is `slug` only. On Dec-31→Jan-1 rollover, the cached HTML serves "0 this year" for the OLD year (now empty) for up to 5 minutes. Acceptable for v1, but worth noting in the post-deploy runbook so the cache is manually flushed at calendar-year rollover (or the cache key bumped to `(slug, current_year)`). Confidence 95%.

### Findings to downgrade or refute

- **None.** All three rounds' REQUIREDs and SUGGESTEDs are well-founded. R3 (Opus #2 → Sonnet downgrade) was correctly downgraded by Sonnet — I confirm: HTMX 2.x requires a verb (`hx-get`/`hx-post`/etc) on an element to issue an HTMX request from a trigger; the `<form>` has no verb so its `hx-trigger="change from:select.cross-filter"` is dead code, not a double-fire source. SUGGESTED treatment (S6 in the user packet) is correct.

## Recommended fix-up scope (final)

### Aggregate REQUIRED (the 3 from the chain, no upgrades from this audit)

1. **R1 — Process-badge category landing pages 404.** `get_resolved_badge` LEFT-JOIN fix: `SELECT t.slug, COALESCE(c.name_override, t.name) AS name, COALESCE(c.description_override, t.description) AS description, t.icon, t.kind, COALESCE(c.enabled, TRUE) AS enabled FROM priority_badge_templates t LEFT JOIN priority_badges_config c ON c.template_slug = t.slug AND c.city_id = %s WHERE t.slug = %s AND (t.kind = 'process' OR c.enabled = TRUE)`. Add a process-badge 200 test in `test_f4_browse_by_priority.py` (was N1 in Sonnet's NICE-TO-HAVE; promote to part of R1 fix to close the test gap).

2. **R2 — HTMX swap dumps full page into `#item-list`.** Add `hx-select="#item-list"` to the `<select>` in `category_landing.html`. (Consider HX-Request partial-render path in a follow-up — see S9 below.)

3. **R4 — `✨` aria-hidden makes legend ungrammatical for SR.** Change `aria-hidden="true"` to `aria-label="AI-verified"` on the `badge-spark` span at `city.html:34`. Matches `partials/badge_chip.html:33` and decision #67 spec line 2745-2746.

### Aggregate SUGGESTED-accept (in fix-up)

1. **S5 (Sonnet) — Cross-filter slug validation.** Filter `cross_filters` to slugs present in `list_enabled_badges(municipality["id"])` to honor spec §6.8 "validates against enabled badges."

2. **S6 (Opus #2 → Sonnet recat) — Strip dead HTMX attrs from `<form>`.** Remove `hx-target`, `hx-trigger`, `hx-push-url` from the `<form>`, OR drop the `<form>` wrapper entirely (spec example uses bare `<select>`).

3. **S7 (Sonnet) — Tile count value not tested end-to-end.** Add assertion that the integer count appears next to the tile (e.g., `"1 this year"`).

4. **S8 (NEW, this audit) — Legend over-promises on non-BHM cities.** Gate the "policy" parenthetical on `{% if city_policy_badges %}` OR reword.

5. **Opus #1 S1 — `list_enabled_badges` missing `description` field.** Shape symmetry with siblings.

6. **Opus #2 S4 — Trailing `?and=` on blank-option selection.** Cosmetic URL cleanup.

### Aggregate SUGGESTED-defer (acknowledge, ship anyway)

1. **Opus #1 S2 — 11 COUNT queries on cold homepage load.** Cached for 5 min, indexed paths, acceptable v1.

2. **Opus #2 S5 — Warm/cool palette unimplemented.** Spec §6.3 calls for it; defer to polish pass.

3. **Opus #2 S6 — Process-only city heading mismatch.** UX judgment call.

4. **Opus #2 S8 — Form without semantic submit purpose.** Folded into S6 above.

5. **S9 (NEW, this audit) — Post-swap dropdown DOM unsynced.** Functionally fine for v1; document constraint, revisit if dropdown contents become dynamic.

6. **S10 (NEW, this audit) — `_overview_cache` lacks per-year salt.** Acceptable; document in runbook.

7. **HX-Request partial-render path** (the cleaner R2 fix). Saves ~5 DB queries per filter swap and resolves S9. Defer to a small follow-up — `hx-select` is sufficient for v1.

### NICE-TO-HAVE

- 8 items across the three reviews (collapse helpers, module-level constants, inline-style extraction, `hx-include="this"`→spec form, etc.) — defer.

## Sign-off question for the user

**"Proceed with the F4 fix-up loop addressing R1 + R2 + R4 + S5 + S6 + S7 + S8 + Opus#1-S1 + Opus#2-S4 in a single fix-up commit (process-badge 200 test bundled with R1), and defer the HX-Request partial-render path, warm/cool palette, calendar-year cache salt, and remaining NICE-TO-HAVE items to post-merge follow-ups?"**
