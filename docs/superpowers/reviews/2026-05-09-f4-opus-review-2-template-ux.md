# F4 Review #2 — Template + UX (Opus)

**Commit:** b3789a3
**Branch:** feat/impact-first-phase-2-track-3
**Reviewer angle:** Template + HTMX + CSS + UX + citizen copy (parallel review, non-overlapping with route/helpers angle)

## Summary

The dropdown wiring has two material problems: (1) the route returns the
full HTML page but neither `hx-select` nor an `HX-Request` partial path
is used, so an actual selection will dump the entire page into
`#item-list` (broken UX, not just a deferred polish item), and (2) the
`<form>` and `<select>` carry duplicate HTMX attributes which will
double-fire requests on `change`. The Browse-by-Priority section and
badge legend are otherwise solid: copy is jargon-free, accessibility is
mostly correct (one ✨-`aria-hidden` regression), and the inline-styles
cluster is a defensible v1 expedient EXCEPT that the
`priority-tile--policy` vs `priority-tile--process` modifiers carry no
visual differentiation today (warm/cool palette per spec §6.3 line
2738-2740 is unimplemented).

## REQUIRED (must-fix before merge)

1. **HTMX swap will render a broken page on filter change.** The route
   `category_landing` (`src/docket/web/public.py:213-344`) always
   returns the full Jinja page (`{% extends "base.html" %}`).
   `category_landing.html:116-122` declares `hx-target="#item-list"` on
   the `<select>` with default `hx-swap="innerHTML"`. HTMX 2.x does not
   auto-pluck `#item-list` from the response — without `hx-select` or
   an `HX-Request` partial path, the entire page HTML (masthead, hero,
   browse-by-priority, KPI strip, filter section *including the
   dropdown itself*, item list, footer) is stuffed inside
   `#item-list`'s `innerHTML`. The implementer's comment at
   `category_landing.html:156-160` flags this as a deferred refactor
   ("the dropdown is bookmark-friendly today via hx-push-url + the
   route always returns a full page"), but bookmark-friendliness only
   covers full-page reloads; the actual HTMX interaction is broken.
   Fastest fix: add `hx-select="#item-list"` to the `<select>`.
   Cleaner fix: detect `request.headers.get("HX-Request")` in the route
   and `render_template("partials/item_list.html", ...)` for HTMX
   requests. Either is small. Confidence: 90%+ — verified by reading
   HTMX 2.x default swap semantics and confirming no `hx-select` /
   header check exists anywhere in the codebase
   (`grep -rn "hx-select" src/` returns empty;
   `grep -rn "HX-Request" src/` returns empty).

2. **Form + select will double-fire on change.** At
   `category_landing.html:109-131`, both elements carry HTMX
   attributes:
   - `<form>` line 109-112: `hx-target="#item-list"`,
     `hx-trigger="change from:select.cross-filter"`, `hx-push-url="true"`
   - `<select>` line 116-122: `hx-get="..."`, `hx-target="#item-list"`,
     `hx-include="this"`, `hx-trigger="change"`, `hx-push-url="true"`

   When the user picks an option:
   1. The select's `change` event fires its own HTMX request (with
      `hx-get` URL).
   2. The change bubbles to the form. The form's
      `hx-trigger="change from:select.cross-filter"` matches and fires
      a *second* request — to the form's `action` (missing), so
      defaults to the current URL with method GET.

   Both requests target `#item-list` and both push URL — race
   condition. Pick one. Recommended: keep the `<select>` HTMX attrs
   (it has the `hx-get` URL anyway), strip `hx-target`/`hx-trigger`/
   `hx-push-url` from the `<form>`. The `<form>` is then either kept
   for graceful no-JS fallback (add `action=` and `method="get"`) or
   removed entirely (the `<label for="cross-filter-select">` doesn't
   need a form parent). Confidence: 85% — HTMX 2.x trigger filter
   `from:` semantics confirm both will fire.

3. **`✨` in the legend is `aria-hidden="true"` — screen readers hear
   nothing meaningful.** `city.html:34`:

   ```jinja
   A <span class="badge-spark" aria-hidden="true">✨</span>
   means independent sources agree on the tag.
   ```

   AT users hear: "A means independent sources agree on the tag." —
   the subject is missing. Compare `partials/badge_chip.html:33` which
   correctly uses `aria-label="AI-verified"`. Either give the legend
   spark the same `aria-label`, or write the surrounding copy so the
   sentence reads correctly with the glyph silenced (e.g. "The ✨
   sparkle icon means…" with `aria-hidden="true"` on the glyph). Spec
   line 2745-2746 explicitly calls out the SR meaning: "The
   `aria-label='AI-verified'` ensures screen readers convey the same
   meaning." Confidence: 95%.

## SUGGESTED (should-fix, can be deferred)

4. **Picking "(none)" leaves a trailing `?and=` in the URL.** At
   `category_landing.html:123` the blank option has `value=""`; selecting
   it pushes `/al/birmingham/blight_accountability/?and=`. The route
   tolerates it (`request.args.get("and", "")` → `""` →
   `cross_filters=[]`), but the URL is ugly when shared / bookmarked.
   Cleaner: drop the param when empty. Easiest path is a tiny
   `hx-on::config-request` listener that strips `and=""` from
   `event.detail.parameters`, or accept the cosmetic hit. Confidence:
   75% — depends on whether ugly-but-functional URLs are acceptable for
   v1.

5. **`priority-tile--policy` and `priority-tile--process` modifiers
   carry no visual differentiation.** The spec at §6.3 lines 2738-2740
   prescribes "`.badge-process` warm palette" vs "`.badge-policy` cool
   palette (blue/green/purple per badge)". The new tiles have BEM-style
   modifiers but no CSS rules anywhere
   (`grep priority-tile src/docket/web/static/` returns nothing). The
   only visual difference between the two grids is `padding: 16px` /
   `font-size: 28px` (policy) vs `padding: 14px` / `font-size: 24px`
   (process). A citizen scanning the homepage can't tell at a glance
   that "Hidden on Consent" is a process signal vs. "Blight" being a
   policy priority — they're both white tiles with the same border.
   Either land color tokens in CSS (preferred, matches spec) or document
   the visual differentiation as a Phase 4 follow-up. Confidence: 90%
   — spec explicitly asked for it.

6. **Process-only cities (everywhere except Birmingham) will see a
   "Browse by priority" heading followed only by oversight signals.**
   `list_city_policy_badges` returns `[]` for non-BHM cities, so the
   policy grid is omitted (correct). But the section's top heading is
   "Browse by priority / What's on the docket" with intro "Pick a topic
   to see every recent item the city is acting on" — for a citizen
   looking at Mobile or Vestavia Hills, "priority" reads as policy
   priority but only oversight-signal tiles appear. Either: (a) suppress
   the upper "Browse by priority" header when only process renders,
   (b) reword the intro to be process-aware ("Pick a topic — or check
   for oversight signals — to see what the city is acting on"), or
   (c) note this as a known UX wrinkle until non-BHM cities get policy
   badges. Confidence: 70% — judgment call, not a hard bug.

7. **"Items this year" KPI on the category page vs. "this year" on
   the homepage tile — gating divergence risk.** The implementer's
   comment at `public.py:96-98` claims "Counts are gated identically to
   list_items_by_badge / category_kpis so a tile reading '12 this year'
   matches what the citizen will see when they click into the category
   page." This is route-side helper logic — out of scope for this
   review. Flag for reviewer #1 to verify `badge_volume_year` gating
   (significance threshold + confidence threshold + processing_status
   filter) matches `list_items_by_badge` exactly. Test
   `test_badge_volume_year_respects_significance_gate` covers one gate
   but not the full set. Confidence: deferred.

8. **The `<form>` wraps `<select>` with no semantic submit purpose.**
   Even after fixing finding #2, the form is mostly cosmetic: a
   single-select that auto-submits on change doesn't need a form
   wrapper. Either add a no-JS fallback (`<form action="..."
   method="get">` + `<noscript>` submit button) or drop the form and
   keep just the `<label>` + `<select>` pair. Form-without-action is a
   small accessibility smell — assistive tools may announce "form" to
   AT users for no reason. Confidence: 65%.

## NICE-TO-HAVE

9. **Inline styles can be lifted to CSS in a small follow-up commit.**
   New classes that should have rules in
   `src/docket/web/static/css/smart_brevity.css` (or a new
   `priority_tiles.css`):

   - `.priority-grid` — the `display: grid; gap: 12px;
     grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));`
     declaration appears verbatim twice in `city.html:93-94` and
     `city.html:114-115` (with 220px vs 200px minmax).
   - `.priority-tile` — the 6-property declaration at
     `city.html:96-98` and `city.html:117-119` is duplicated.
   - `.priority-tile__icon` — `font-size: 28px` (policy) /
     `font-size: 24px` (process) with `aria-hidden`.
   - `.priority-tile__name` — `font-size: 16px; font-weight: 600`
     (policy) / `font-size: 15px; font-weight: 600` (process).
   - `.cross-filter-form` — `padding: 8px 0;` and child `<label>` /
     `<select>` rules at `category_landing.html:109,113,122`.

   The `style="..."` on `<header class="feed-head"
   style="margin-top: 24px;">` (city.html:108) and
   `<h3 class="feed-title t-display" style="font-size: 22px;">`
   (city.html:111) are one-off spacing/typography overrides that read
   as defensible inline use. The grid + tile styles are the cluster
   that warrants extraction. Confidence: defensible v1, but the next
   round of polish should lift these.

10. **The legend's wording extension ("like sole-source contracts or
    split votes" / "like blight or housing") is well-chosen.** Each
    parenthetical names exact slugs from the rendered tile grid, so
    the legend functions as both definition AND examples. The spec's
    one-liner is shorter but less self-explanatory; the implementer's
    expansion improves citizen comprehension without leaking
    implementation jargon. Same F2/F3 lens applied — no "Wave 0",
    "matchers", "Track 1", etc. — and the integration test
    `test_badge_legend_has_no_internal_jargon`
    (`tests/integration/test_f4_browse_by_priority.py:493-506`)
    enforces this. Verdict: keep.

11. **DOM order is fine.** Hero (with embedded legend) → KPI grid →
    Browse-by-Priority → This Week → Contested → Recent Votes →
    Topics → Notable → Meetings → Council. The new section sits at
    the right level — after introducing the city, before chronological
    activity. The volume timeline on `category_landing.html` renders
    BEFORE the cross-filter dropdown (line 72-74), so the citizen sees
    "trends → filter the list" which is the right read order.

12. **Mobile responsiveness should hold.** `auto-fit minmax(220px,
    1fr)` on a 360px-wide phone collapses to a single column. The
    `min-width: 280px` on the select at line 122 fits within
    `app-main` mobile padding. No `@media (max-width: 768px)` rules
    were added for `.priority-grid`, but `auto-fit minmax` handles it
    declaratively — same approach as `.feed-table` elsewhere. Caveat:
    if the priority-tile CSS extraction in finding #9 happens, watch
    for any tile-level mobile rules that might collide with `kpi-grid`
    flex-override patterns at `mobile.css:88-104`.

13. **No CSS class collisions with existing rules.** Verified by
    grepping all six CSS files for `priority-tile`, `priority-grid`,
    `cross-filter`, `cross-filter-form`, `browse-by-priority`,
    `badge-legend`, `badge-process-sample`, `badge-policy-sample`. The
    only existing rule for any of these classes is
    `.badge-spark { font-size: 0.875em; }` in `smart_brevity.css:8`,
    which is correctly reused. Clean.

## Implementer-flagged question responses

1. **Inline `style=` attributes:** Defensible for v1 — the priority
   tiles are a brand-new component and the inline styles capture the
   designer's intent without polluting the global stylesheet
   prematurely. BUT: the `priority-tile--policy` vs
   `priority-tile--process` warm/cool palette is unimplemented (spec
   §6.3), and the inline style block is duplicated between the two
   grids in `city.html`. Fine to ship as-is, but file a P2 follow-up
   to land `.priority-tile` rules in `smart_brevity.css` (or a new
   `priority_tiles.css`) before the public flag flip. The
   `cross-filter-form` styles at `category_landing.html:109-122` are
   also defensible v1, similar follow-up.

2. **Badge legend copy:** Just right. The expansion ("like sole-source
   contracts or split votes" / "like blight or housing") tracks the
   exact slugs of the rendered tiles — citizens see the legend, then
   the matching tile, and can map definition to instance. No internal
   jargon. The "independent sources agree on the tag" phrasing is
   clearer than spec's "AI-verified by multiple sources" for a
   non-technical reader. Compare F2's win against "Wave 0" leakage and
   F3's mayoral-claim wrap — same lens, passes. ONE issue: the ✨ is
   `aria-hidden="true"`, which makes the surrounding sentence
   ungrammatical for screen readers (see REQUIRED #3).

3. **`public.about_badges` stub vs omit:** Omit was correct for v1.
   The spec referenced the link (line 2760) but `public.about_badges`
   doesn't exist and creating a 404-stub route would be misleading
   ("Learn more" leading to a 404 is a UX paper cut). The implementer's
   inline comment at `city.html:21-25` correctly notes the link can be
   wired later as a permalink without restructuring. Compare with the
   `upcoming_hearings_rss` stub at `public.py:347-351` — that one
   exists because F5 plan landed it as a stub explicitly. F4's "Learn
   more" omission is consistent with not stubbing what isn't yet built.

4. **Form vs `<select>` HTMX placement:** Keep on the `<select>`,
   strip from the `<form>`. See REQUIRED #2 — the duplication will
   double-fire requests. The select has the `hx-get` URL anyway and is
   the natural anchor for the request. The form serves no submit
   purpose for an auto-submitting single-select.

## Out-of-scope observations

The following are flagged for reviewer #1 (route + helpers angle):

- Verify `badge_volume_year` and `badge_volume_recent` gates (sig +
  confidence + processing_status) match `list_items_by_badge` exactly,
  so the homepage tile counts equal the category-page item counts. The
  implementer claims this in `public.py:96-98` but tests only cover
  individual gates, not equivalence. (Finding #7 above.)
- Verify `list_enabled_badges` ordering matches the `order_badges`
  helper used elsewhere (process-alarm-order first, then policy by
  -confidence, slug). Test
  `test_list_enabled_badges_combines_policy_and_process` confirms
  process-before-policy and process alarm-order, but not policy
  ordering.
- The `_overview_cache` cache-bust in the F4 test fixture
  (`test_f4_browse_by_priority.py:185`) is a test-only side effect.
  Production cache-bust strategy when policy badges are added/removed
  for a city — out of this review's scope.
- 11 SELECT COUNT queries per cold homepage render
  (`public.py:99-101`, claimed). Performance characteristic for
  reviewer #1 to verify against the
  `idx_agenda_item_badges_city_slug_conf` index.
