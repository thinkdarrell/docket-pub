# F3 Sonnet 4.6 Second-Look

**Commit:** 281d68d
**Branch:** feat/impact-first-phase-2-track-3
**Reviewer:** Claude Sonnet 4.6 (independent second-look)

## Summary

All three Opus REQUIREDs are confirmed with primary-source evidence. The cross-angle
finding (empty-month rendering contradiction vs docstring + missing column-wide hit-area)
is also confirmed; the column-wide hit-area fix Opus #2 proposed is the right approach,
with one accessibility nuance to add. One new REQUIRED is added: the "Background bands
show which mayor presided" sentence renders as a factual lie on every non-BHM city page
(Mobile, Vestavia, Homewood) because `mayoral_terms` is only seeded for Birmingham —
Opus #2 flagged this as out-of-scope, but it ships broken copy to non-BHM citizens
today, making it block-worthy. The opacity drift (spec 0.08 vs code 0.10) and stale
`category_landing.html` comment are confirmed as SUGGESTED. The 16 tests are
substantively good for the data path but the route render test is genuinely thin
on the SVG structure it supposedly verifies.

---

## Verification of Opus REQUIREDs

### R-T1: Tooltip absent from substantive segment in mixed months

**CONFIRMED — and the template comment is internally self-contradicting.**

Reading `partials/volume_timeline.html` lines 59–91, the comment at line 60–62 says:
> "Each bar pair carries ONE `<title>` on the consent rect (the visually-topmost
> segment) so hover anywhere on the column shows the same tooltip."

The comment describes a column-wide hover intent, but the code does not implement it.
The three cases:

**Case 1: All-substantive month** (`height_consent == 0`, `height_substantive > 0`)

- Lines 64–70: the substantive `<rect>` is emitted with NO `<title>`.
- Lines 71–78: the `{% if point.height_consent > 0 %}` fails, so the consent rect with
  `<title>` is skipped.
- Lines 79–90: the `{% elif point.height_substantive > 0 %}` fires. A second transparent
  hit-area `<rect class="volume-bar--hit">` with `fill-opacity="0"` and `<title>` is
  emitted. This rect sits on top of the visible substantive rect.
- **Result:** hover works on the full substantive column. Single rect with tooltip.

**Case 2: All-consent month** (`height_substantive == 0`, `height_consent > 0`)

- Lines 64–70: `{% if point.height_substantive > 0 %}` fails — no substantive rect.
- Lines 71–78: `{% if point.height_consent > 0 %}` fires. The consent rect is emitted
  WITH a `<title>`.
- Lines 79–90: `{% elif %}` is not reached.
- **Result:** hover works on the consent rect. Single rect with tooltip. Correct.

**Case 3: Mixed month** (`height_substantive > 0` AND `height_consent > 0`)

- Lines 64–70: the substantive `<rect>` is emitted with NO `<title>`.
- Lines 71–78: the consent rect is emitted WITH `<title>`.
- Lines 79–90: `{% elif %}` is NOT reached because the `{% if point.height_consent > 0 %}`
  at line 71 was true — the `elif` only runs when consent is zero.
- **Result:** The consent rect (upper, lighter segment) has the tooltip. The substantive
  rect (lower, saturated segment) has NO tooltip and no hit-area.

The hit-area only fires in Case 1. Case 3 (the most common real-world case) leaves the
substantive bar — which is the editorial signal per decision #68, the part citizens read
first — without any hover response. The comment is wrong: the single `<title>` does NOT
make hover work "anywhere on the column." The citizen hovering the lower half of a mixed
bar gets nothing.

R-T1 is confirmed. The template comment at line 60–62 makes this worse: it documents
the intended behavior but not the actual behavior.

---

### R-T2: WCAG contrast ratio for `--accent-soft` on `--paper`

**CONFIRMED. CSS comment claiming AA pass is inaccurate. My computed ratio: 1.20:1.**

Token values from `src/docket/web/static/styles.css` lines 5 and 18:
- `--paper: oklch(0.985 0.005 85)`
- `--accent-soft: oklch(0.92 0.04 200)`

WCAG 2.1 relative luminance computation (OKLCH → OKLab → linear sRGB → WCAG Y):

```
--paper oklch(0.985 0.005 85):
  OKLab: (0.985, 0.005·cos(85°), 0.005·sin(85°)) = (0.985, 0.000436, 0.004981)
  linear sRGB: (0.9559, 0.9574, 0.9363) → luminance Y = 0.9557

--accent-soft oklch(0.92 0.04 200):
  OKLab: (0.92, 0.04·cos(200°), 0.04·sin(200°)) = (0.92, -0.03758, -0.01368)
  linear sRGB: (0.7852, 0.7959, 0.8048) → luminance Y = 0.7903

WCAG contrast ratio = (Y_lighter + 0.05) / (Y_darker + 0.05)
  = (0.9557 + 0.05) / (0.7903 + 0.05)
  = 1.0057 / 0.8403
  = 1.197 : 1
```

WCAG 2.1 SC 1.4.11 requires **3:1** for graphical objects that convey meaning. The
consent bar fails by a factor of 2.51x. The 0.5px stroke at 18% opacity
(`stroke: var(--accent-ink); stroke-opacity: 0.18; stroke-width: 0.5`) adds no
meaningful contrast contribution — at 18% opacity on a sub-pixel stroke it is
invisible at 1x DPI and barely perceptible at 2x.

There is no dark theme in the codebase (`prefers-color-scheme` media query is absent
from all CSS files), so this is not a light/dark split issue — there is one theme and
it fails.

The CSS comment at `layout.css:569` says "Both shades pass WCAG AA on the warm paper
background." This is incorrect for `--accent-soft`. `--accent-ink` (the substantive
bar fill) does pass — its luminance is ~0.039, giving a contrast ratio of ~11.3:1
against `--paper`. Only the consent bar fails.

R-T2 is confirmed. The 1.20:1 matches Opus #2's claimed "~1.2:1" (their number was
not a misread).

---

### R-R1: Stale F3-future-tense docstring on the route

**CONFIRMED.**

`src/docket/web/public.py` line 186 — the `category_landing` docstring reads:
> "volume timeline (F3 lands the real partial; F2 ships an empty stub)"

F3 has landed. The docstring now actively misdirects a future reader into believing an
"empty stub" is in play when the real partial is already wired. One-line fix.

Additionally confirmed: `src/docket/web/templates/category_landing.html` line 11 has
the same stale phrasing: "volume timeline (F3 stub)". Both files should be fixed in
the same edit pass. Opus #1 flagged the route docstring as REQUIRED; Opus #1's
out-of-scope note flags the template comment. Both are the same bug.

---

## Cross-angle finding: empty-month rendering vs docstring + column-wide hit-area

### What actually renders for a zero-month

Reading `badge_volume_series` in `query.py` lines 1310–1351 and the template lines
63–91:

The Python helper always emits a dict for every month in the window, including months
with `n_items == 0`. For those months: `height_substantive = 0`, `height_consent = 0`.
In the template, both `{% if point.height_substantive > 0 %}` (line 64) and
`{% if point.height_consent > 0 %}` (line 71) fail. The `{% elif %}` at line 79 also
fails (`height_substantive` is 0). **Nothing is emitted — not even a zero-height rect.**

So: a zero-month produces a silent gap in the SVG. No `<rect>`, no `<title>`, no
`data-period` attribute. A citizen hovering the gap sees nothing.

The docstring at `query.py:1226–1230` says:
> "Filling in the gaps in Python (rather than excluding them) preserves the 'every
> month is a column' property so adjacent bars never visually collide when one month
> happens to be empty."

This is correct about the *x-positioning* logic (each column gets a consistent `x`
derived from its month-index `i * col_width`, so no bars slide together). But the
docstring implies a visual "column" exists for empty months — it doesn't. The column
spacing between flanking non-zero bars is determined by `x` math, which does hold.
But the phrase "adjacent bars never visually collide" is not the problem the dense
list solves; the problem it solves is that the *x*-positioning of non-empty bars
stays proportional. The docstring should be narrowed to that claim.

Also note: the docstring at query.py:1303–1305 adds:
> "If every month is zero we still emit zero-height bars (so `<title>` tooltips work
> as a flat baseline)."

This claim is wrong. Zero-height bars do NOT emit `<title>` tooltips — the template
gates every `<rect>` on `height > 0`. The empty-state branch at line 40 of the
template (`{% if timeline and timeline | selectattr('n_items') | list %}`) will be
falsy when all months have `n_items == 0`, so the empty-state `<p>` renders instead
of the SVG. So "a flat baseline with tooltips" is not what happens: it's either the
empty-state paragraph (all-zero case) or silent column gaps (some-months-zero case).

### Verdict on column-wide hit-area approach

The column-wide full-height transparent `<rect>` per bucket (proposed by Opus #2) is
the right fix. It solves three problems simultaneously:

1. Gives the mixed-month substantive bar a tooltip (R-T1).
2. Gives zero-month buckets a hoverable `<title>` showing "0 items" (fixing the
   docstring claim and improving UX).
3. Removes the branchy `{% elif %}` logic, making the template a simple three-rect
   structure (visible substantive, visible consent, column-wide hit-area).

Alternatives considered:

- **`<g>` group with single `<title>`:** SVG `<title>` on a `<g>` does not reliably
  trigger browser tooltips — the tooltip fires on the visible fill area, not the
  group bounding box. Hit-area rect is more reliable.
- **`pointer-events: bounding-box` on the `<g>`:** Non-standard, limited support.
  The hit-area rect is universally supported.
- **Moving `<title>` to the substantive rect:** Fixes mixed-month case but not
  zero-month gaps, and doesn't clean up the `{% elif %}` structure.

The column-wide hit-area is the cleanest approach.

**Accessibility nuance Opus #2 did not flag:** The fix should include
`aria-hidden="true"` on the two visible bars (or on the whole `<g>` if grouped),
and `focusable="false"` on the hit-area rect, to prevent screen readers from
announcing the same bar three times. With `role="img"` on the SVG, NVDA/JAWS/
VoiceOver won't descend into the SVG in document mode anyway — but in browse mode
some AT does. Adding `aria-hidden="true"` to the visible rects and keeping the
`<title>` on the hit-area rect ensures AT that does read SVG internals gets one
clean announcement per column. This is a small addition to the proposed fix, not
a blocker on its own.

---

## New findings (missed by both Opus reviewers)

### REQUIRED

**R-S1: "Background bands show which mayor presided" ships as false copy on non-BHM city pages.**

`partials/volume_timeline.html` line 35:
> "Background bands show which mayor presided."

This sentence renders unconditionally in the header paragraph — it is outside the
`{% if mayoral_terms %}` guard and even outside the `{% if timeline %}` guard. It
appears for every city, every badge, regardless of whether any mayoral term overlay
actually renders.

`mayoral_terms` is seeded only for Birmingham (migration 013 lines 399–402). For
Mobile (`civicclerk`), Vestavia Hills, and Homewood, `mayoral_term_overlay()` returns
`[]`. The SVG renders with no overlay bands — but the header paragraph still claims
background bands exist.

The current category landing route is BHM-only in practice (only Birmingham has
priority badges configured). But the spec's stated scope is multi-city (Mobile,
Vestavia Hills are active cities in the schema), and the route itself (`/al/<slug>/
<badge_slug>/`) accepts any city slug. As soon as a non-BHM city gets priority badges
assigned, citizens will see "Background bands show which mayor presided" above a chart
with no bands.

Opus #2 flagged this in the out-of-scope section and called it "a lie," suggesting
either a `{% if mayoral_terms %}` guard or seeding `mayoral_terms` for all active
cities. It's in-scope for this PR because the partial that ships this false sentence is
the F3 deliverable, and the fix is a one-line Jinja guard. This review elevates it to
REQUIRED because it ships incorrect factual copy to users, not a visual or performance
issue.

**Fix:** Wrap the offending sentence:
```jinja
{% if mayoral_terms %}Background bands show which mayor presided.{% endif %}
```

---

### SUGGESTED

**S-1: Route render test is substring-thin for SVG structure verification.**

`test_route_renders_svg_with_term_band_and_title` (lines 474–495) asserts:
- `'<svg viewBox="0 0 800 200"'` in body — SVG opened
- `"term-overlay--D"` in body — at least one overlay class present
- `"<title>"` in body — at least one tooltip
- `"Each bar is one month"` in body — legend copy

What it does NOT verify:
- The correct number of `<rect>` elements. A regression that drops all bars but keeps
  the overlay band and the legend text would still pass.
- That both substantive AND consent segments render in a mixed month (the exact case
  R-T1 identifies as broken). Seeding `is_consent=False` only, the test never exercises
  the `height_consent > 0` branch.
- That the year-tick labels appear (5 `<text>` elements with years 2022–2026).
- That the empty-state path does not fire when data is seeded. (`"Visualizations coming
  soon"` check at line 495 is for F2 regression, not F3 empty-state regression.)

The test seeds one substantive item and asserts `"<title>"` exists — which will be true
once R-T1 is fixed but only via the `{% elif %}` hit-area path. It would still pass
even if the mixed-month path were broken. Recommend adding one seeded consent item to
exercise the dual-segment path, and counting `<rect class="volume-bar"` occurrences in
the response body.

**S-2: `category_landing.html` line 11 stale comment (companion to R-R1)**

Line 11 says "volume timeline (F3 stub)" — same staleness issue as the route docstring
(R-R1). Opus #1 noted this as out-of-scope for reviewer #2. Since both the route and
the template carry the stale comment, fix them in the same pass.

**S-3: `query.py:1303–1305` comment claims false zero-height baseline behavior**

The inline comment at lines 1303–1305 says:
> "If every month is zero we still emit zero-height bars (so `<title>` tooltips work
> as a flat baseline)."

This is doubly wrong: (a) the template gates every `<rect>` on `height > 0`, so no
rect emits for zero-height months; (b) the empty-state branch fires when all months
have `n_items == 0`, so no SVG renders at all in the all-zero case. The comment
describes a behavior that doesn't exist. Update it to accurately reflect that zero
months produce silent gaps in the SVG (non-zero window) or trigger the empty-state
paragraph (all-zero window).

---

### NICE-TO-HAVE

**N-1: Spec §6.6 SQL example vs actual implementation — minor divergence, not a bug.**

Spec §6.6 (lines 3094–3098) shows `badge_volume_series` returning
`[{period, n_items, total_dollars}]`. The actual implementation returns 10 keys per
dict (`period`, `n_items`, `n_consent`, `n_substantive`, `total_dollars`, `x`, `width`,
`y_substantive`, `height_substantive`, `y_consent`, `height_consent`). The spec sketch
was a minimal pre-implementation interface; the real function returns render-ready
geometry. Not a drift issue — the spec was intentionally underspecified at the time of
writing. The spec patch in the commit (`docs/superpowers/specs/...`) does not update
the function signature example to match. Low-priority cleanup.

**N-2: Opacity inline on `<rect>` — spec says 0.08, code says 0.10**

Spec §6.6 line 3113: `opacity="0.08"`. Template line 54: `opacity="0.10"`. The CSS
comment in `layout.css:584` says "(per spec line 3109)". As Opus #2 noted, this is a
single-source-of-truth inconsistency. At the visual level, 0.10 reads slightly darker
than 0.08 — still subtle against the warm paper background. The CSS comment referencing
the spec line implies the spec is authoritative; the inline value should match it.
Decision: pick one, document it, update the other. (Note: Opus #2 ranked this
SUGGESTED; I agree, keeping it NICE-TO-HAVE since the visual delta is imperceptible and
neither value breaks the design.)

**N-3: `_months_in_range` docstring still refers to "bars never visually touch"**

`query.py:1191–1192`: "preserves the 'every month gets a slot' property so adjacent
bars never visually touch when one month happens to have zero items." This is
technically correct (the x-positions are derived from the dense list, so non-empty bars
don't slide together), but it overloads "visual" — there IS no visual column for zero
months. The docstring is misleadingly close to the `badge_volume_series` docstring's
incorrect claim. Both should use consistent language: "preserves x-position
monotonicity" or "ensures each month occupies a consistent column slot in the x-axis
mapping, even when that month has no items to render."

---

## Findings to downgrade or refute

**Opus #1 SUGGESTED — MV refresh cron task:** Correctly rated SUGGESTED. Nothing in
F3 breaks without it today. The swallow is the right local-dev guard. The task is
definitely needed before Phase 3 backfill flip, but that is not an F3 blocker.

**Opus #1 NICE-TO-HAVE — `fetchall()` outside `with` block in `mayoral_term_overlay`:**
The concern is valid but minor. `fetchall()` materializes the result set before the
cursor closes, so `rows` is fully owned by the caller. There is no resource leak or
correctness issue. Cosmetic only, as Opus #1 stated.

**Opus #1 SUGGESTED — Future-month gaps in current year:** Correctly rated SUGGESTED.
Decision #95 explicitly chose calendar-year semantics. The trailing-off visual is an
intentional side effect of that choice, not an implementation bug. Does not need to
change for F3 to ship.

**Opus #2 SUGGESTED — Empty-state visually orphaned:** I partially downgrade this.
The empty-state copy ("No volume data yet for this category. The timeline will appear
as we index more meetings tagged with this badge.") renders inside the `.feed` section
with its `border-bottom` intact. It reads slightly orphaned but it doesn't look broken
— the section header above it explains the context. Reasonable for the pre-backfill
phase. Defer to post-backfill UX pass.

**Opus #2 SUGGESTED — `<title>` invisible to AT when SVG has `role="img"`:** Correctly
rated SUGGESTED. The `<details><table>` fallback is the right long-term fix but it's
too much scope for F3. The `aria-label` on the SVG ("Birmingham blight_accountability
volume by month, last 5 years") gives AT users the context. Defer.

**Opus #2 NICE-TO-HAVE — `viewBox` squish at ≤375px:** Per-spec F3 ships fixed monthly.
Not actionable in this PR.

**Opacity drift (0.08 vs 0.10):** Both Opus reviewers note this; I rate it NICE-TO-HAVE
rather than SUGGESTED. Visually inconsequential, and neither value is wrong in absolute
terms (both produce a readable-but-subtle overlay). The spec/code sync is worth doing
for hygiene but not worth delaying a fix-up merge.

---

## Final categorization recommendation for the user packet

### Aggregate REQUIRED list (all three reviews, deduplicated)

1. **R-T1 — Mixed-month substantive bar has no tooltip and no hit-area** (Opus #2,
   confirmed here). Fix: column-wide full-height transparent hit-area `<rect>` per
   bucket carrying the single `<title>`, replacing the `{% elif %}` hit-area path.

2. **R-T2 — `--accent-soft` on `--paper` is 1.20:1 contrast, failing WCAG 2.1 SC
   1.4.11's 3:1 requirement** (Opus #2, confirmed here with computed ratio). CSS
   comment at `layout.css:569` claiming AA pass is inaccurate. Fix: darken
   `--accent-soft` token to ~`oklch(0.78 0.06 200)` for a ~3:1 ratio while
   preserving the "lighter than substantive" visual story.

3. **R-R1 — Stale "F3 future-tense" docstring on `category_landing` route** (Opus #1,
   confirmed here). `public.py:186` says "F3 lands the real partial; F2 ships an
   empty stub." Fix: update to "volume timeline (5-year rolling window, decision #95)."
   Batch with the companion stale comment in `category_landing.html:11`.

4. **R-S1 — "Background bands show which mayor presided" renders unconditionally,
   false for all non-BHM cities** (new, this review). Fix: wrap the sentence in
   `{% if mayoral_terms %}...{% endif %}`.

---

### Aggregate SUGGESTED-accept (worth doing in fix-up)

1. **S-1 (this review)** — Route render test doesn't exercise mixed-month SVG structure.
   Add one consent item to the seed data and assert both segment classes appear.
2. **S-2 (this review + Opus #1 out-of-scope)** — `category_landing.html:11` stale
   "F3 stub" comment. Fix in same pass as R-R1.
3. **S-3 (this review)** — `query.py:1303–1305` and `1226–1230` docstring claims
   that zero-height bars emit tooltips — false. Update both to describe actual behavior.
4. **Opus #1 SUGGESTED #2** — `query.py:1271` comment says "Production refreshes this
   MV nightly via the cron worker" — not yet true. Soften to "Production should
   refresh..." until the cron task ships.

---

### Aggregate SUGGESTED-defer (acknowledge, ship anyway)

1. **Opacity drift 0.08 vs 0.10** — spec says 0.08, code says 0.10. Visually
   inconsequential. Defer to post-merge spec cleanup.
2. **Missing MV refresh cron task** — needed before Phase 3 backfill flip, not
   an F3 blocker. Track separately.
3. **Future-month trailing gaps** — intentional per Decision #95. Accept as-is.
4. **`<title>` invisible to AT under `role="img"`** — correct, but `<details>/<table>`
   fallback is post-F3 scope.
5. **Empty-state visually orphaned** — defer to post-backfill UX pass.

---

### NICE-TO-HAVE (deferred)

1. **N-1** — Spec §6.6 signature example doesn't reflect full 10-key return dict.
2. **N-2** — Opacity spec/code sync (0.08 vs 0.10). Pick one, document it.
3. **N-3** — `_months_in_range` and `badge_volume_series` docstrings use imprecise
   "visual" language for what is really an x-position monotonicity guarantee.
4. **Opus #1 N-1** — `_normalize_party` maps Green → "I" without note.
5. **Opus #1 N-2** — `fetchall()` consistency with rest of `query.py`.
6. **Opus #1 N-3** — Layout constants in Python vs hard-coded `y` values in template.
7. **Opus #2 N-1** — `fill-opacity="0"` vs `fill="transparent"` idiom.
8. **Opus #2 N-2** — `text-anchor` inline vs CSS.
9. **Opus #2 N-4** — New-category sparse chart reads as broken.
