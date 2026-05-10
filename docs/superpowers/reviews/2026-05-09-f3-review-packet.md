# F3 Review Packet — User Verification Gate

**Commit under review:** `281d68d` on `feat/impact-first-phase-2-track-3`
**Worktree:** `~/docket-pub-pf2-track-3`
**Reviews synthesized:**
- Opus #1 (route + helpers): `2026-05-09-f3-opus-review-1-route-helpers.md` — 1R / 3S / 4N
- Opus #2 (template + UX): `2026-05-09-f3-opus-review-2-template-ux.md` — 2R / 4S / 5N
- Sonnet 4.6 (second-look): `2026-05-09-f3-sonnet-second-look.md` — confirmed all 3, added 1 new R

**Aggregate verdict:** F3 can ship after a single fix-up commit. 4 REQUIRED, no architectural rework needed.

## Cross-model corroboration (the value-add)

The two strongest findings were caught **from different angles** and converge on **the same fix**:

- **Opus #1** spotted that the service emits zero-height dicts for empty months but the template only renders `<rect>` when `height > 0` — service/template data-model mismatch.
- **Opus #2** spotted that mixed-content months render the consent (upper) rect with a `<title>` but the substantive (lower) rect — the editorial focus per Decision #68 — has no tooltip.
- **Sonnet** confirmed both, walked through the `{% if … %}{% elif %}` template logic line by line to show the elif branch is unreachable in the mixed case, and added that the existing template comment claiming "hover works anywhere on the column" is aspirational, not actual.

**Convergent fix:** one full-height transparent column-wide hit-area `<rect>` per bucket. Resolves both findings + simplifies the elif branch logic + improves mobile touch targets + makes empty months hit-targetable + lets us add `aria-hidden="true"` to the two visual segment rects so AT doesn't triple-announce.

This is the **9th cross-model confirmation** that the multi-angle protocol catches things single-angle review misses.

---

## Category 1 — REQUIRED (must fix in fix-up commit)

### R1. Column-wide hit-area rect per bucket
**Source:** Opus #1 + Opus #2 (cross-angle), confirmed by Sonnet
**Files:** `src/docket/web/templates/partials/volume_timeline.html:64-78`, `src/docket/services/query.py:1303-1305` (docstring)
**Evidence:** Mixed-month case (`n_substantive > 0` AND `n_consent > 0`) — the `{% if height_consent > 0 %}` branch fires, giving the consent rect a `<title>`, but the `{% elif %}` is never reached, leaving the substantive rect tooltip-less. Empty months (`n_items == 0`) render no `<rect>` at all (silent gap) — contradicting the docstring's "consistent column spacing" justification.
**Fix:** Add a single full-height transparent `<rect>` per bucket, `pointer-events="all"`, carrying the `<title>` with full counts (substantive + consent + total + dollars). Add `aria-hidden="true"` to the two visible segment rects. Update the docstring at `query.py:1303-1305` to match the new model.

### R2. WCAG contrast failure on consent shade + inaccurate CSS comment
**Source:** Opus #2, confirmed by Sonnet (independently computed ratio)
**File:** `src/docket/web/static/layout.css:573-578`
**Evidence:** `--accent-soft` (L=0.92) on `--paper` (L=0.985) gives **1.197:1** computed ratio (Sonnet showed math: `(0.9557 + 0.05) / (0.7903 + 0.05)`). WCAG 2.1 SC 1.4.11 requires **3:1** for graphical objects. The 0.5px @ 0.18-opacity stroke is sub-pixel hairline and doesn't rescue it. The CSS comment claiming "Both shades pass WCAG AA" is inaccurate — Decision #68's editorial story (lighter shade = rubber-stamped) is invisible.
**Fix:** Darken `--accent-soft` (or pick a different consent-shade token) until contrast ratio against `--paper` reaches ≥3:1. Confirm with computed math in the fix-up commit message. Update the inline comment to reflect the actual passing ratio.
**Note:** No dark theme exists in the codebase, so light-mode is the only check needed.

### R3. Mayoral overlay claim renders for non-BHM cities
**Source:** Opus #2 (out-of-scope flag), elevated to REQUIRED by Sonnet
**File:** `src/docket/web/templates/partials/volume_timeline.html` (header section text)
**Evidence:** Template renders "Background bands show which mayor presided" unconditionally, but `mayoral_terms` is only seeded for Birmingham. Mobile, Vestavia Hills, Homewood — and any future city — see a factual claim about bands that aren't in the SVG.
**Fix:** Wrap the sentence in `{% if mayoral_terms %}…{% endif %}`. One-line Jinja guard.

### R4. Stale "F3 stub" docstring
**Source:** Opus #1, confirmed by Sonnet
**Files:** `src/docket/web/public.py:186`, `src/docket/web/templates/category_landing.html:11`
**Evidence:** Both say "F3 lands the real partial; F2 ships an empty stub." F3 has now landed.
**Fix:** Update both to remove the future-tense.

---

## Category 2 — SUGGESTED, accept in fix-up

### S1. Test gap: mixed-month rendering case
**Source:** Sonnet (added)
**File:** `tests/integration/test_badge_volume_series.py`
**Evidence:** Sonnet noted the route render test is data-path-solid but doesn't seed an item in a mixed-content month, so R1's brokenness wouldn't have been caught by tests. After the hit-area fix, add a render test that asserts the column-wide hit-area `<rect>` is present in mixed-month output.
**Fix:** Seed at least one mixed-content month (1 substantive + 1 consent in the same `month` bucket) and assert `<rect>` count + `<title>` text on the hit-area.

### S2. Render-test substring thinness
**Source:** Opus #2
**Evidence:** Existing render tests assert presence of strings like `<svg`, `<rect`, `term-overlay` — but don't validate **counts** (e.g. exactly N rects for N visible months) or structural correctness (e.g. each bucket has exactly one hit-area rect).
**Fix:** Tighten 2-3 of the render tests with structural assertions. Bundle with S1 above.

### S3. Spec opacity drift (0.10 vs 0.08)
**Source:** Opus #2
**File:** `src/docket/web/templates/partials/volume_timeline.html` (`opacity="0.10"`)
**Evidence:** Spec §6.6 line 3109 says `opacity="0.08"`; partial uses `0.10`. Drift small but confusing for a future reader cross-referencing.
**Fix:** Bring partial to `0.08` to match spec, OR amend spec to `0.10` if 0.08 is too faint at the new contrast. Two-letter change either way.

---

## Category 3 — SUGGESTED, defer with acknowledgment

### D1. Materialized view refresh has no cron task
**Source:** Opus #1 (and out-of-scope flag from Opus #2 implicitly)
**Evidence:** `mv_badge_volume_monthly` is created `WITH NO DATA` in migration 013. Nothing in `src/docket/worker/` calls `REFRESH MATERIALIZED VIEW`. Only the test fixture does. The implementer added an `ObjectNotInPrerequisiteState` swallow for local dev; that masks but doesn't solve a stale/empty MV in production.
**Why defer:** The swallow keeps the page from breaking. The MV will get its first refresh as part of Phase 3 backfill. **Hard requirement before the public flag flip** (`SMART_BREVITY_UI=true`) is to add a 6th cron task: `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_badge_volume_monthly` on a daily or post-AI-cascade schedule.
**Tracking:** Add to the FINAL-N pre-flip checklist in the Phase 2 plan.

### D2. SVG `<title>` not exposed to assistive tech
**Source:** Opus #2
**Evidence:** SVG `role="img"` causes AT to read only the `aria-label`; the per-bar `<title>` elements are not announced. Citizens using a screen reader cannot get the per-month numbers.
**Why defer:** Real accessibility gap, but solving correctly requires either (a) a `<details><summary>` data-table fallback below the SVG, or (b) `role="figure"` + ARIA description structure. Not a one-line fix; merits its own task.
**Tracking:** Add as a follow-up task. May land alongside G-track admin views (which will face the same issue with their charts).

### D3. Future-month gaps in current calendar year
**Source:** Opus #1
**Evidence:** When `current_year` is the active window end, months that haven't occurred yet (e.g. June–December if it's currently May) emit no data, leaving visual gaps on the right edge of the chart.
**Why defer:** Cosmetic, not broken. After R1 lands the hit-area rects will fill the visual width. Could later trim the end of the window dynamically to "last full month," but that's a Decision #95 amendment, not a fix-up scope item.

---

## Category 4 — NICE-TO-HAVE (deferred indefinitely)

- **N1** *(Opus #1)* — `_normalize_party` party-normalization edge cases (handles "D"/"R"/"I" but not lowercase/extra whitespace; current data is clean so non-issue).
- **N2** *(Opus #1)* — `fetchall` outside the `with cursor` block; stylistic, no leak risk given psycopg2 contract.
- **N3** *(Opus #1)* — Layout-constant duplication between Python helpers and template literals. Real, but extracting to a shared place is over-engineered for the current size.
- **N4** *(Opus #1)* — Local `import psycopg2.errors` inside `badge_volume_series` for the swallow. Could be top-of-file; functional impact zero.
- **N5** *(Opus #2)* — Empty-state visually orphaned (bare paragraph, no padding/centering). Cosmetic; if the empty state is hit it means a brand-new badge with no data, which is rare.

---

## Decision-trace verifications (no action needed)

- **Decision #95 numbering:** verified. Existing decisions ran through #94 (Anthropic SDK hardening); #95 is correctly the next available number.
- **Window math:** `date(yr-4, 1, 1)` to `date(yr, 12, 31)` is 5 calendar years inclusive. `meeting_date` is a `DATE` column (not `TIMESTAMP`), so no boundary edge cases. Rolls forward annually on Jan 1 per Decision #95. Confirmed by Opus #1 and Sonnet independently.
- **Leap-day distortion in mayoral overlay:** Opus #1 quantified at ~0.88px on an 800px viewBox (0.11% of width). Below visual threshold. Acceptable.
- **SQL parameterization:** all queries use `%s` placeholders with parameter tuples, matching established service-layer pattern. No injection risk.

---

## What the user is being asked to verify

The F2 user gate caught **4 things all 3 reviewers missed**. Apply the same lens here. Specifically — areas reviewers tend to under-cover:

1. **Citizen interpretation.** Open the rendered page (after R1+R2 land) and read it cold. Does the consent-baseline split tell the editorial story Decision #68 promises ("rubber-stamped is the lighter portion")? Does the chart make the priority-vs-deliberation gap obvious, or do you have to know what to look for?

2. **Empty/edge cases.** What does a brand-new policy badge with 2 months of data look like? Mostly empty 5-year frame, or compress to populated range? (Reviewers answered theoretically; you'd be the first to see it.)

3. **Cross-page coherence.** Does the timeline visually fit alongside the existing F2 KPI strip and the upcoming F4 cross-filter chips? F2's review caught a CSS grid collision via shared `.kpi-grid` — anything similar here? (`.volume-timeline` etc. are all newly named, but `.term-label` and `.axis-label` could potentially collide with future SVG components — flag if you want them more strongly namespaced.)

4. **Anything reviewers' angles structurally couldn't see** — copy tone, cross-page navigation, performance feel, brand voice, decisions you've already made elsewhere that this contradicts.

If approved with no additions, the fix-up loop will land R1–R4 + S1–S3 in a single commit, defer D1–D3 with tracking, and skip N1–N5.
