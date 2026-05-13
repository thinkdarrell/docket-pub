# F3 Final Audit — Opus 4.7

**Commit:** 281d68d
**Posture:** Final auditor pass before fix-up. Three prior reviews + user reflag list incorporated.

## Top-line verdict

The four REQUIREDs in the synthesized packet are correct and sufficient as a release-gate set, but the audit promotes **one new REQUIRED** (R5: a within-bar contrast guardrail when darkening `--accent-soft`) so the R2 fix doesn't silently flatten Decision #68's editorial story, plus **two new SUGGESTED-accepts** (test-coverage tightening that goes beyond S1+S2). Reflags-1 through 5 hold (1, 5 partially overstated; 2, 3, 4 dead-on). Reflag-6 is real but correctly classified as a defer — adding it as a NEW SUGGESTED-defer (D4).

## User reflag verifications

### Reflag-1 (R1 hit-area + aria-hidden)

- **ARIA summary completeness — HOLDS.** The current consent rect's `<title>` (line 77) carries: `period`, `n_items`, `n_consent`, `n_substantive`, optional `total_dollars`. The Case-1 "all-substantive" hit-area `<title>` (line 88) carries the *same* string. The proposed column-wide hit-area carrying that same `<title>` is a strict superset of what either segment carries today — no information is lost. `aria-hidden="true"` on the two visual segments + `<title>` on the hit-area is the right structure.
- **Hit-area overlap with other interactive elements — REFLAG OVERSTATED.** Inside the SVG (`viewBox="0 0 800 200"`) the only other elements are: (a) `term-overlay` `<rect>`s (no events, no `<title>`, decorative), (b) `term-label` and `axis-label` `<text>` elements (no `<title>`, no events, decorative). There are no `<a>`, no HTMX targets, no buttons inside the SVG. The column-wide rect cannot capture clicks on anything outside the SVG (it lives inside the viewBox). And `category_landing.html` places the SVG in its own `<section class="feed">` — the item list, KPI strip, and filter chips are in *separate* sections. **No realistic overlap risk.** The reflag is a generic accessibility heuristic that doesn't apply to F3's actual layout.

### Reflag-2 (R2 WCAG threshold — 3:1 vs 4.5:1)

Audit of every `--accent-soft` use site:

| File:line | Use | Class of object | Threshold |
|---|---|---|---|
| `councilmatic.css:33` | `box-shadow` on `.tw-dot-upcoming` | Graphical (focus halo) | 3:1 |
| `councilmatic.css:90` | `box-shadow` on `.legc.is-selected` | Graphical (focus ring) | 3:1 |
| `styles.css:132` | `.cite` background (text color = `--accent-ink`) | Background-for-text — NOT contrast-against-paper | n/a (cite-text vs cite-bg is the relevant pair, currently ~9.4:1) |
| `layout.css:50` | `box-shadow` city-switcher focus | Graphical | 3:1 |
| `layout.css:90` | `.city-switcher-item.is-active` background | State indicator (graphical) | 3:1 |
| `layout.css:126` | `box-shadow` `.topsearch:focus-within` | Graphical | 3:1 |
| `layout.css:234` | `.feed-row.is-selected` background | State indicator (graphical) | 3:1 |
| `layout.css:271` | `.notable-row.is-selected` background | State indicator (graphical) | 3:1 |
| `layout.css:306` | `box-shadow` on `.cc.is-selected` | Graphical | 3:1 |
| `layout.css:453` | `:hover` color-mix derived | Hover state | 3:1 |
| `layout.css:574` | `.volume-bar--consent` fill | Graphical (data carrier) | 3:1 |

**Required threshold for the F3 fix-up: 3:1.** Every use site is a graphical/UI object, never standard body text. Reflag-2 is a correct heuristic question but on inspection the answer is: 3:1 is sufficient. **However**, see new finding R5 below — darkening to hit 3:1-vs-paper has a side-effect on the cite text-on-bg pair (currently ~9.4:1, will drop) and on the within-bar substantive-vs-consent visual gap (Decision #68's editorial story).

### Reflag-3 (R3 mayoral_terms gap handling)

- **Gap handling in `mayoral_term_overlay` (`query.py:1419-1444`):** Each term is rendered independently. If a date range has no covering row, no `<rect>` is emitted for that range — the user sees the page background through the chart. There is no stretch-to-fill behavior. Layout will not break — adjacent term bands don't shift to cover gaps.
- **Seed data state (`migrations/013:399-402`):** Birmingham seed is Bell `2010-01-26 → 2017-11-28` then Woodfin `2017-11-28 → NULL`. Adjacent dates (no gap), and Woodfin's NULL `term_end` is handled by `term_end = row["term_end"] or end_date` in the overlay function. **For the current 5-year window (2022-2026) Woodfin covers the entire window — single band, no gaps possible today.** The reflag is a future-proofing concern and the gap handling is already graceful (transparent gap, not broken layout).
- **"HistoricalBackfill worker" — REFLAG MISCONCEPTION.** `mayoral_terms` is populated *only* by the migration 013 seed. There is no worker that backfills it. The user's wording suggests a worker exists; it doesn't. New mayoral data lands by adding migration rows. So the gap concern is purely "what if a future migration leaves a hole" — answer: gap renders as transparent, layout intact.
- **Interim-mayor party fallback — handled.** `_normalize_party` (`query.py:1355-1367`) defaults NULL/empty/lowercase/odd-string party values to `"I"` (Independent), which has CSS at `layout.css:590` (`.term-overlay--I { fill: var(--ink-3); }`). No CSS class falls through to "no class". Safe.

### Reflag-4 (R4 other stale placeholders)

F3-introduced stale strings only:
- `category_landing.html:11` — "F3 stub" (already in R4)
- `public.py:186` — "F3 lands the real partial; F2 ships an empty stub" (already in R4)
- `query.py:1303-1305` comment — "If every month is zero we still emit zero-height bars (so `<title>` tooltips work as a flat baseline)" — this is **wrong as written** and Sonnet caught it as S-3 (the docstring describes behavior that doesn't exist). Already absorbed via packet S3 / Sonnet S-3.
- `query.py:1226-1230` docstring — claims "consistent column spacing" justification for dense series; rendered behavior produces silent gaps. Same docstring-vs-reality divergence; absorbed via packet S3.

Other "stub"/"TODO" strings in the F3 surface area belong to OTHER routes (item_detail E5, upcoming_hearings_rss F5, item_badges_overflow F-track, mayor_priority_quote KPI stub) — pre-existing, not F3-introduced. **No additional citizen-visible placeholder text needs scrubbing.** Reflag-4 holds with the existing R4 + S3 scope.

### Reflag-5 (dollar-tier interaction)

- **Layout / focus-capture risk — NO RISK.** `.tier-*` and `.dollars--*` classes are used in Smart Brevity Cards (`partials/card_smart_brevity.html`), `_facts_strip.html`, `dollar_tier.html`, `meeting_detail.html`, `topic_detail.html`, etc. None of these render inside the SVG. In `category_landing.html`, dollar-tier badges live in the **item list** section (separate `<section class="feed">` from the timeline), well below the timeline. The timeline SVG and the dollar-tier elements share no DOM ancestor below `<main>`. The column-wide hit-area rect cannot intercept clicks/focus on dollar-tier badges.
- **Reflag-5 OVERSTATED.** It's a sensible heuristic but doesn't apply to F3's actual structure.

### Reflag-6 (mobile touch parity for SVG `<title>`)

- **Behavior on touch devices — REFLAG IS REAL.** Browser-native `<title>` in SVG renders as a hover tooltip on desktop. **On iOS Safari and Android Chrome, tapping an SVG `<rect>` does NOT show its `<title>`.** This is documented behavior. The fix-up's column-wide hit-area improves the *touch target size* but does not solve the touch-tooltip-display gap.
- **Recommendation: defer with explicit acknowledgment.** A proper mobile parity fix requires either (a) `aria-describedby` + visible per-bar caption strip below the chart, or (b) JS click handler showing a popover, or (c) a `<details><summary>` data table fallback Opus #2 already proposed (which would also solve the AT gap from D2). Right path is to bundle this with **D2** — a single follow-up task that ships a data-table fallback solves both the screen-reader gap (D2) and the mobile-touch gap (D4 below). Not a new REQUIRED for the fix-up.

## New findings (beyond the user reflags)

### REQUIRED (added)

**R5. The R2 darkening must preserve the substantive-vs-consent within-bar contrast that carries Decision #68's editorial story.**

The packet's R2 fix darkens `--accent-soft` to hit ~3:1 contrast against `--paper`. Sonnet suggested `oklch(0.78 0.06 200)`. But this token is also one half of the **within-bar** visual story per Decision #68: the saturated lower segment (substantive) reads as visibly darker than the lighter upper segment (consent), making the rubber-stamped portion legible as such at a glance.

- Current state: substantive `--accent-ink` L=0.32 vs consent `--accent-soft` L=0.92 → ~9.4:1 within-bar.
- After Sonnet's proposed darken: substantive L=0.32 vs consent L=0.78 → ~3.4:1 within-bar.

That's still distinguishable, but the *editorial gap* compresses. The fix-up must verify that the post-darken consent shade remains visibly lighter than substantive at the chart-rendered scale (60 narrow columns × ~10px wide bars × varying heights). Required action:

- Specify the new `--accent-soft` value with **two** measured ratios in the commit message: (a) consent-vs-paper ≥ 3:1 (the WCAG fix), (b) consent-vs-substantive ≥ 2:1 (the Decision #68 editorial gap). The 2:1 floor is a soft target, not a WCAG line — it just enforces that the lighter/darker visual story doesn't collapse.
- Also explicitly re-state in the commit message that `.cite` text-on-bg (text = `--accent-ink`, bg = `--accent-soft`) still passes WCAG AA 4.5:1 after the change. At post-darken L_bg=0.78 vs L_text=0.32, the ratio is approximately 4.0:1 — that's BELOW AA 4.5:1 for body text. **The cite chip is small (~10px font, 500-weight) and is small text, so 4.5:1 applies.** This may force a slightly less-aggressive darken (e.g. L=0.82 instead of 0.78) or a token split (`--accent-soft` for surfaces, `--accent-soft-bar` for the bar fill). The fix-up loop must measure all three pairs.

This isn't a re-architecture — it's a constraint set the fix-up must respect when picking the new value. Promoting from "implementer's choice" to REQUIRED because the proposed value (0.78) silently fails the cite-text body-text contrast and risks flattening Decision #68 in the chart itself.

### SUGGESTED (added)

**S4. Test that `aria-hidden="true"` is rendered on the visible segments.**

The fix-up adds aria-hidden to the substantive and consent visible rects (per R1). S1+S2 tighten render-test substring assertions but do not enumerate aria-hidden. Add an assertion to `test_route_renders_svg_with_term_band_and_title` (or a new test) that:
- the visible substantive rect carries `aria-hidden="true"`
- the visible consent rect carries `aria-hidden="true"`
- the column-wide hit-area rect carries the `<title>` and does NOT carry aria-hidden
- the column-wide hit-area's `<title>` text matches what the per-segment `<title>` carries today (period, n_items, n_consent, n_substantive, optional total_dollars).

This is the regression-trap that catches a future implementer accidentally restoring the per-segment `<title>` pattern.

**S5. Test that mixed-month rendering produces a hit-area rect with the full `<title>` content.**

S1 in the packet asks for a mixed-month seed, but does not specify the assertion shape. The mixed-month test should:
- Seed 1 substantive + 1 consent in the same month
- Assert exactly THREE rects for that bucket: `volume-bar--substantive` + `volume-bar--consent` + `volume-bar--hit`
- Assert the `<title>` text contains both "1 on consent" and "1 substantive"

This locks in the correct three-rect-per-bucket pattern as a structural test.

### Findings to downgrade or refute

- **Reflag-1's "showstopper" framing of overlap risk** — refuted in the verifications above. Inside the SVG there are no other interactive elements. Outside the SVG the rect cannot reach.
- **Reflag-5's focus-swallow concern** — refuted. Dollar-tier elements are in a separate page section and far below the SVG.
- **Sonnet's aggressive `oklch(0.78 0.06 200)` suggestion** — accepted in spirit (3:1 vs paper) but constrained by R5 above. The implementer must measure all three contrast pairs and may need to land at L=0.82 or split the token.

## Recommended fix-up scope (final)

### Aggregate REQUIRED list (5 items — packet's 4 + R5 from this audit)

1. **R1.** Column-wide transparent hit-area `<rect>` per bucket; add `aria-hidden="true"` to the two visible segment rects; update the docstrings at `query.py:1303-1305` and `1226-1230` to match the new structure.
2. **R2.** Darken `--accent-soft` until consent-fill-vs-paper ≥ 3:1. Update the misleading "Both shades pass WCAG AA" comment at `layout.css:568-569`.
3. **R3.** Wrap "Background bands show which mayor presided" in `{% if mayoral_terms %}…{% endif %}`.
4. **R4.** Remove "F3 stub" stale phrasings at `public.py:186` and `category_landing.html:11`.
5. **R5 (new).** When picking the new `--accent-soft` value for R2, the fix-up commit message must record three measured contrast ratios: (a) consent-vs-paper ≥ 3:1, (b) consent-vs-substantive ≥ 2:1 (Decision #68 within-bar gap), (c) `--accent-ink` text on the new `--accent-soft` background ≥ 4.5:1 (the `.cite` chip body-text path). If a single value can't satisfy all three, split the token (`--accent-soft` for non-bar surfaces, `--accent-soft-bar` for the volume-bar fill) — keep the cite/state/focus uses on the old shade, only darken the bar fill.

### Aggregate SUGGESTED-accept (5 items — packet's S1+S2+S3 + S4+S5 from this audit)

1. **S1.** Mixed-month render test seed (packet).
2. **S2.** Tighten render-test substring assertions (packet).
3. **S3.** Update `query.py:1226-1230` and `1303-1305` docstring claims (packet).
4. **S4 (new).** Test that `aria-hidden="true"` is on visible segments and absent on hit-area; assert hit-area `<title>` text content.
5. **S5 (new).** Mixed-month test asserts exactly three rects per bucket (substantive + consent + hit-area).

### Aggregate SUGGESTED-defer (4 items — packet's D1+D2+D3 + D4 from this audit)

1. **D1.** MV refresh cron task — needed before the public flag flip (`SMART_BREVITY_UI=true`); add to FINAL-N pre-flip checklist. Audit confirms: no F3 break without it today; defer holds.
2. **D2.** SVG `<title>` not announced under `role="img"` — defer with `<details><table>` fallback as the planned solution.
3. **D3.** Future-month gaps in current calendar year — Decision #95 explicit choice.
4. **D4 (new — reflag-6).** Mobile-touch parity for `<title>` tooltips. Browser-native SVG `<title>` doesn't display on tap. Bundle the fix with D2 (the data-table fallback solves both AT and mobile-touch in one task). **Tracking note:** if mobile usage exceeds desktop in early analytics, this gets promoted to FINAL-N pre-flip blocker; today the volume-timeline is information-dense supporting context, not a primary tap-target, so deferring is acceptable.

## Sign-off question for the user

**Do you approve this fix-up scope: 5 REQUIREDs (R1–R5), 5 SUGGESTED-accepts (S1–S5), and 4 SUGGESTED-defers (D1–D4) — with the explicit constraint that the new `--accent-soft` value (R2/R5) must be picked with measured contrast ratios for all three pairs (vs paper, vs substantive, vs `--accent-ink` text), and a token split is permitted if one value can't satisfy all three?**
