# F3 Review #2 — Template + UX (Opus)

**Commit:** 281d68d
**Branch:** feat/impact-first-phase-2-track-3
**Reviewer angle:** Template + SVG rendering + CSS + UX (parallel review, non-overlapping with route/helpers angle)

## Summary

The partial is structurally clean: spec §6.6 is followed almost verbatim, the SVG is
server-rendered with no JS, the CSS slots into the existing design tokens, the
class names don't collide with anything in `styles.css` / `layout.css` /
`mobile.css` / `councilmatic.css` / `tweaks.css`, and the empty-state branch
correctly fires when every bucket has `n_items == 0` (not just on `timeline == []`).

Two REQUIRED items block prod-quality release: (1) for the **most-common rendering
path** — a month with both substantive AND consent items — the saturated lower bar
has NO `<title>` and no hit-area, so hovering the lower (saturated) half shows
nothing; only the lighter upper half is interactive. This breaks the implementer's
own intended "two-segment hoverable column" model. (2) the consent bar's pale-teal
fill (`oklch(0.92 0.04 200)`) against the warm-paper background (`oklch(0.985 0.005 85)`)
fails WCAG 2.1 SC 1.4.11 Non-Text Contrast (~1.2:1 vs the required 3:1) — the
0.5px @ 0.18 opacity stroke is sub-pixel and doesn't rescue it. The "lighter shade
= rubber-stamped" visual story disappears against the page background.

The remaining items are SUGGESTED polish (spec opacity drift 0.10 vs 0.08, empty
state visually orphaned, test substring-thinness, SVG `role="img"` makes `<title>`
elements invisible to screen readers) and NICE-TO-HAVE refinements.

## REQUIRED (must-fix before merge)

- **[Tooltip absent from substantive segment in mixed months]** at
  `src/docket/web/templates/partials/volume_timeline.html:64-78` — In the most-
  common rendering case (a month with BOTH `height_substantive > 0` AND
  `height_consent > 0`), the substantive `<rect>` (lines 65-69) is emitted with
  no `<title>` child and no overlay hit-area. The browser shows the tooltip
  only when hovering the upper (lighter) half. The implementer's `{% elif %}`
  on line 79 covers the all-substantive case but not the mixed case. Worse, the
  saturated lower portion is the *editorial* story per decision #68 — that's
  the bar a citizen reads first — but it's the half that doesn't respond to
  hover. Mobile is even worse: the lower half also doesn't respond to tap.
  
  **Fix:** emit a single full-height transparent hit-area `<rect>` per column
  (carrying the `<title>`) drawn AFTER the visible bars, replacing the current
  hit-area-on-substantive-only path. Sketch:
  
  ```jinja
  {% if point.n_items > 0 %}
  {# visible segments — no <title> #}
  {% if point.height_substantive > 0 %}
  <rect x=".." y=".." class="volume-bar volume-bar--substantive" />
  {% endif %}
  {% if point.height_consent > 0 %}
  <rect x=".." y=".." class="volume-bar volume-bar--consent" />
  {% endif %}
  {# single transparent column-wide hit area, owns the tooltip #}
  <rect x="{{ point.x }}" y="{{ VOLUME_TIMELINE_PLOT_TOP }}"
        width="{{ point.width }}" height="{{ VOLUME_TIMELINE_PLOT_HEIGHT }}"
        fill-opacity="0" class="volume-bar--hit">
    <title>{{ point.period }}: ...</title>
  </rect>
  {% endif %}
  ```
  
  This also doubles the touch target for mobile (44px-tall column hit area
  vs the current sub-bar size), addresses Q1 directly, and removes the
  branchy `{% elif %}` duplication.

- **[Consent bar fails WCAG 2.1 SC 1.4.11 against paper background]** at
  `src/docket/web/static/layout.css:573-578` — `--accent-soft: oklch(0.92 0.04 200)`
  on `--paper: oklch(0.985 0.005 85)` is roughly a 1.2:1 luminance ratio — well
  below the 3:1 required for graphical objects that convey meaning. The
  `stroke: var(--accent-ink); stroke-opacity: 0.18; stroke-width: 0.5;`
  consolation prize is a sub-pixel hairline at 18% opacity — invisible at any
  rendering scale below 2x DPR, and barely visible at 2x. Net effect: the
  "rubber-stamped on consent" story (decision #68's whole editorial point)
  vanishes against the page background, and a citizen reads bars as
  substantive-only. The CSS comment claims "Both shades pass WCAG AA on the
  warm paper background" — that's not accurate.

  **Fix options:** (a) darken `--accent-soft` to ~`oklch(0.78 0.06 200)` for a
  ~3:1 ratio while still reading as "lighter than substantive"; (b) keep the
  current shade but bump the stroke to `1px` at full opacity so the bar's
  edge is the contrast carrier; (c) use a lightly cross-hatched pattern
  (`<pattern>` defs) for consent — more work but it doubles as a
  not-color-only signal for color-blind users. Recommend (a) — small token
  change, no markup churn, preserves the L-axis story.

## SUGGESTED (should-fix, can be deferred)

- **[Spec opacity drift: 0.10 vs 0.08]** at
  `src/docket/web/templates/partials/volume_timeline.html:54` — partial
  hardcodes `opacity="0.10"` but spec §6.6 line 3113 specifies `0.08`. The
  CSS comment at `layout.css:584` even says "(per spec line 3109)". Either
  fix the inline value to `0.08` or update the spec — but the two should
  agree. (Visually, 0.08 vs 0.10 is borderline imperceptible; this is a
  consistency / single-source-of-truth issue.)

- **[Empty-state visually orphans the section]** at
  `src/docket/web/templates/partials/volume_timeline.html:102-107` and
  `layout.css:607-610` — when no buckets have data, only a `<p>` with
  `padding: 1rem 0 1.25rem; font-style: italic;` renders inside the
  `<section class="feed">`. The header ("Volume timeline · Items per
  month · Each bar is one month...") still shows above it. The result:
  the section rule (`.feed` adds `border-bottom: 1px solid var(--rule)`) plus
  italic gray text reads as "broken / nothing here" rather than "we know,
  data's coming." Compare to the F2 empty-state which has a bordered
  `.empty-state` block.

  **Fix:** wrap the empty paragraph in a styled box (e.g. dashed-outline
  card centered in the chart-area space) so the section reads as
  "intentionally placeholder" rather than "render failed." Or: hide the
  legend/header copy when empty, since the explanation has no chart to
  explain.

- **[`<title>` not exposed to screen readers when SVG has `role="img"`]**
  at `src/docket/web/templates/partials/volume_timeline.html:41-44` —
  the prompt's claim that "<title> elements are SR-readable in SVG" is true
  only when the SVG is treated as a document. `role="img"` (which the spec
  mandates) makes the SVG opaque: NVDA/JAWS/VoiceOver announce the
  `aria-label` once and skip everything inside. So the per-month numeric
  detail (counts, dollars, mayor band) is invisible to AT users.

  **Fix:** the simplest mitigation is to add a sibling `<details><summary>
  Show data table</summary><table>...</table></details>` (or a visually-
  hidden table linked to the SVG via `aria-describedby`) that exposes the
  per-month buckets. The partial already has the data — it's a Jinja loop.
  This also helps keyboard users who can't hover. Defer to a follow-up if
  a table-fallback is too much for F3 scope.

- **[Test coverage is substring-thin on the rendering path]** at
  `tests/integration/test_badge_volume_series.py:474-510` — the route
  render test asserts: SVG opens with `viewBox="0 0 800 200"`, contains
  `term-overlay--D`, contains `<title>`, contains "Each bar is one month".
  It does NOT verify (a) the correct number of `<rect class="volume-bar">`
  are present, (b) both substantive AND consent segments render in mixed
  months, (c) year ticks for all 5 calendar years appear, (d) the
  hit-area / tooltip pattern is correct on every month type
  (mixed / all-consent / all-substantive). A future regression that drops
  half the bars would still pass. Recommend at least counting `<rect>`
  occurrences: with seeded data in 2 different months and a 5-year window
  there should be N visible bar-rects + 1 overlay rect + the term-band rect.

  Empty-state test (lines 498-510) is solid — explicitly enumerates the
  jargon allowlist.

## NICE-TO-HAVE (optional polish)

- **[`fill-opacity="0"` vs `fill="transparent"` vs CSS-only]** at
  `volume_timeline.html:87` — `fill-opacity="0"` works but is a slightly
  unusual idiom; readers expect either `fill="transparent"` or
  `pointer-events="visiblePainted"` paired with no fill. Behavioral
  difference is nil; pick one for consistency.

- **[Inline `text-anchor="middle"` vs CSS]** at
  `volume_timeline.html:56,99` — `text-anchor` is an SVG presentation
  attribute that maps to a CSS property, so either inline or CSS works.
  Inline matches the partial's existing convention for layout attributes
  (`x`, `y`). Fine to leave alone, but if you want to push everything
  visual into CSS, `.term-label, .axis-label { text-anchor: middle; }`
  is the move.

- **[`viewBox="0 0 800 200"` is fine; aspect-ratio sometimes squishes
  on very narrow widths]** at `layout.css:555-562` — `width: 100%`,
  `height: auto`, `max-height: 280px` keeps the SVG legible at desktop
  and tablet. At ≤375px the chart renders ~93px tall (375 × 200/800)
  which is short but readable. Per-month bars at 60 buckets × ~6px each
  = a tight smear. Spec §6.6 doesn't mandate mobile responsiveness, but
  a mobile-only 1280-or-768px breakpoint that swaps to quarterly buckets
  (or a horizontal-scroll variant) would help. **Not gating** — F3
  ships fixed monthly per spec.

- **[Empty-bucket months emit zero rects]** at `volume_timeline.html:64-91`
  — when `n_items == 0`, neither `if` fires, so a zero-data month emits
  nothing. That's fine for visual rendering (no bar = no visual element)
  but means there's also no tooltip on those columns ("June 2024: 0
  items" — useful context). Minor polish; not a bug.

- **[`feed-title` reused at `font-size: 22px` via inline style is the
  F2 convention]** at `volume_timeline.html:28` — matches the precedent
  set by `category_landing.html:86`. Fine.

- **[Decision #95 5-yr window for new categories looks sparse]** —
  if a brand-new category badge has only 6 months of data, the chart
  renders 60 monthly buckets with 54 zeros and 6 narrow bars near the
  right edge. The empty-state branch won't fire (it requires ALL
  buckets zero). A citizen sees a mostly-empty chart that reads as
  broken-but-isn't. The spec mandates the fixed window, so this is a
  spec issue, not an implementation issue — flagging for the spec
  owner. Two mitigations worth considering: (a) auto-compress the
  window to (first-data-month - 1, end_date) when first-data-month is
  within the last 12 months, (b) emit a lightweight "data starts {month}"
  caption above the chart when the leftmost populated bucket is past
  the window's leftmost.

## Open-question responses (for the items the implementer flagged)

1. **Tooltip hit-area pattern.** Single full-height invisible hit-area
   rect per column is the right call — see the REQUIRED finding above.
   The current "tooltip on visually-topmost segment" pattern leaves the
   substantive bar (the editorial focus per decision #68) without a
   tooltip in mixed months, and the `{% elif %}` branch only covers the
   all-substantive case. A column-wide hit-area also doubles the mobile
   touch target and removes the branchy template logic. Worth noting:
   on most browsers the `<title>` tooltip is delayed (~1500ms) and
   *only* hover-driven — keyboard users get nothing regardless of
   layout. So even with the column-wide hit-area, AT users still need
   the SUGGESTED `<details><table>` fallback.

2. **Empty-state copy.** "No volume data yet for this category. The
   timeline will appear as we index more meetings tagged with this
   badge." passes the F2 jargon test (no Wave 0, Track 1, MV, matchers,
   backfill — verified by the integration test at lines 506-510).
   Citizen-friendly enough to ship. Two minor polish suggestions:

   - "tagged with this badge" — "badge" is mild project-speak; a
     reader unfamiliar with the homepage may not have built that
     mental model. Try "items tagged as {{ badge.name }}" or just
     "matching items."
   - The implicit promise "will appear" presumes an indexing pipeline
     the citizen has no model of. Could soften to "Once council
     meetings cover {{ badge.name }} items, they'll appear here."

   Not gating — current copy is fine.

3. **Inline `style="..."`.** Matches F2's `category_landing.html:86`
   precedent (same `feed-title t-display` + `style="font-size: 22px;"`
   pair) and the F2 review accepted that pattern. Don't refactor for
   F3 alone — that would split the convention. If/when someone moves
   it to a CSS class (e.g. `.feed-title--sub` or `.feed-title--secondary`),
   do it across both files at once. **Verdict: leave as-is for F3.**

## Out-of-scope observations

These are flagged for reviewer #1 (route/helpers) or for a follow-up:

- `src/docket/services/query.py:1306-1308` — `max_items` computed across
  the visible window. If a single month has a huge spike (e.g. 80 items
  in one month after the AI backfill), every other month's bar is 1/80
  the height — visually unreadable. Consider clamping to e.g. P95 or
  using a sqrt scale. Out of scope for me; the visual decision lives
  in the helper.

- `src/docket/services/query.py:1413` — `total_days = (end_date -
  start_date).days`. For the 5-year window 2022-01-01 to 2026-12-31
  this is ~1825 days with a sub-day rounding error in `px_per_day`
  that compounds across `mayoral_term_overlay` and `year_ticks`. Not
  a UX bug but worth a sanity check from reviewer #1 that the rightmost
  year-tick label doesn't fall off the SVG by 1-2px.

- The `mayoral_terms` seed only carries Bell + Woodfin for BHM; for the
  current 5-year window (2022-2026) only Woodfin overlaps, so a single
  band labeled "Randall Woodfin" spans the whole chart. No collision
  risk for BHM. Other cities (Mobile, Vestavia, etc.) have NO seeded
  mayoral_terms — for those, `mayoral_term_overlay` returns `[]` and
  the chart top has no overlay bands. The chart still renders, but the
  partial's section header copy ("Background bands show which mayor
  presided") becomes a lie. **Suggest:** wrap the "Background bands..."
  sentence in `{% if mayoral_terms %}` so it only appears when bands
  exist. Or seed mayoral_terms for every active city as part of F3.
  Either fits in this PR.
