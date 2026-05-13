# F4 Review Packet — User Verification Gate

**Commit under review:** `b3789a3` on `feat/impact-first-phase-2-track-3`
**Worktree:** `~/docket-pub-pf2-track-3`
**Reviews synthesized:**
- Opus #1 (route + helpers): `2026-05-09-f4-opus-review-1-route-helpers.md` — 1R / 4S / 3N
- Opus #2 (template + UX): `2026-05-09-f4-opus-review-2-template-ux.md` — 3R / 5S / 5N
- Sonnet 4.6 (second-look): `2026-05-09-f4-sonnet-second-look.md` — confirmed 3, downgraded 1, added 3S
- Final-auditor Opus 4.7: `2026-05-09-f4-final-audit.md` — re-verified 3, added 3S (S8/S9/S10), no new R

**Aggregate verdict:** F4 cannot ship as-is — 3 real correctness bugs (process-badge 404 on every city homepage; HTMX swap dumps full page; `aria-hidden` makes legend ungrammatical for SR users). All fixes are small (4-line SQL, 2-word HTMX attr, 1-attribute swap). After fix-up: ship.

**This is the 10th run of the protocol.**

## Cross-model story (this round)

F4 didn't show the strong cross-angle convergence F3 did (where two reviewers caught different facets of the same defect). Instead, four independent rounds found three independent serious bugs plus several smaller layered issues, with three downgrades / scope-corrections that materially changed the picture:

- **Opus #1** caught the **process-badge 404 chain** (its only REQUIRED) — F4's homepage tiles surface a pre-existing F2 bug. F2's `get_resolved_badge` requires a `priority_badges_config` row; process badges have none.
- **Opus #2** caught **HTMX wiring bugs** (3 REQUIRED) — the `#item-list` swap target, double-fire concern, and the aria-hidden grammar issue.
- **Sonnet 4.6** *downgraded* one Opus #2 REQUIRED to SUGGESTED — the "double-fire" finding turned out to be dead code, not a double-fire, because HTMX 2.0.4 doesn't issue requests from `<form>` elements with no verb. Opus #2 was 85% confident but didn't trace the no-verb case. Cleanup still warranted; merge no longer blocked.
- **Sonnet** also *expanded* R1 scope from "Birmingham only" to "all 5 cities" — `list_process_badges()` is city-agnostic.
- **Auditor** *re-corrected* Sonnet's scope expansion: it's 4 deployed cities, not 5 (Sonnet counted Montgomery, which isn't in local DB). And found Mobile's policy slugs **also 404** because Mobile has zero `priority_badges_config` rows — the F2 strict gate was fundamentally city-incomplete.
- **Auditor** added **S8** — a parallel to F3's R3: the badge legend over-promises "policy, like blight or housing" on non-BHM cities that have zero policy tiles.

The meta-pattern: each stage caught what prior stages missed. Sonnet caught Opus #2's confidence overreach. Auditor caught Sonnet's scope miscalibration. Both improvements net positive for fix-up scope.

---

## Category 1 — REQUIRED (must fix in fix-up commit)

### R1. Process-badge category landing pages 404 on every city
**Source:** Opus #1, scope-expanded by Sonnet, scope-corrected by Auditor (4 cities, not 5; Mobile policy slugs also affected)
**File:** `src/docket/services/query.py` — `get_resolved_badge`
**Evidence:** Auditor reproduced live: 28/28 dead links across 4 deployed cities × 7 process slugs. Plus `mobile/blight_accountability` 404s because Mobile has zero `priority_badges_config` rows.
**Fix:** LEFT-JOIN in `get_resolved_badge`:
```sql
SELECT t.slug,
       COALESCE(c.name_override, t.name) AS name,
       COALESCE(c.description_override, t.description) AS description,
       t.icon, t.kind,
       COALESCE(c.enabled, TRUE) AS enabled
FROM priority_badge_templates t
LEFT JOIN priority_badges_config c
       ON c.template_slug = t.slug
       AND c.city_id = %s
WHERE t.slug = %s
  AND (t.kind = 'process' OR c.enabled = TRUE)
```
**Test gap closed:** add a process-badge 200 test in `test_f4_browse_by_priority.py` (Sonnet had this as a NICE-TO-HAVE; auditor promoted it to part of the R1 fix to close the gap that hid this bug).
**Auditor downstream-check:** `get_resolved_badge` has only ONE call site (`category_landing`); the LEFT-JOIN fix is downstream-safe — no admin/search/RSS callers rely on the strict-config-required behavior.

### R2. HTMX swap dumps full page into `#item-list`
**Source:** Opus #2, confirmed by Sonnet and Auditor
**File:** `src/docket/web/templates/category_landing.html` — the `<select>` element
**Evidence:** No `hx-select` or `HX-Request` short-circuit anywhere in `public.py`. Selecting a filter today would dump the entire page into `#item-list`.
**Fix:** Add `hx-select="#item-list"` to the `<select>` (HTMX 2.0.4-correct). Two words.
**Auditor caveat:** This is sufficient for v1. The cleaner fix (an `HX-Request` partial-render path) saves ~5 DB queries per filter swap and resolves S9 (post-swap dropdown unsynced). Defer to a follow-up.

### R4. `✨` aria-hidden makes legend ungrammatical for SR users
**Source:** Opus #2, confirmed by Sonnet and Auditor
**File:** `src/docket/web/templates/city.html` — line 34, the `badge-spark` span in the legend
**Evidence:** `partials/badge_chip.html:33` already uses `aria-label="AI-verified"` correctly. Spec line 2745-2746 (decision #67) explicitly prescribes that wording. Legend's `aria-hidden="true"` is the inconsistency.
**Fix:** Change `aria-hidden="true"` to `aria-label="AI-verified"`. One attribute.

---

## Category 2 — SUGGESTED, accept in fix-up

### S5. Cross-filter slug validation
**Source:** Sonnet
**Evidence:** Spec §6.8 says the route "validates against enabled badges." Current code does not.
**Fix:** Filter `cross_filters` to slugs present in `list_enabled_badges(municipality["id"])`.

### S6. Strip dead HTMX attrs from `<form>` (or drop the form wrapper)
**Source:** Opus #2 → Sonnet recategorized
**Evidence:** `<form>` carries `hx-target`, `hx-trigger`, `hx-push-url` but no verb. HTMX 2.0.4 ignores it, so it's dead code, not double-fire (Sonnet's correction). Misleading for maintainers.
**Fix:** Remove the dead attrs OR drop the `<form>` wrapper entirely (spec example uses bare `<select>`).

### S7. Tile count integer assertions
**Source:** Sonnet
**Evidence:** Existing tile-count tests assert label text only ("this year", "last 30 days") — never the integer count itself. A regression that returns 0 instead of N would pass.
**Fix:** Add assertions that the integer count renders correctly next to each tile.

### S8. Badge legend over-promises on non-BHM cities (NEW, audit)
**Source:** Final auditor
**Evidence:** "Policy, like blight or housing" prose renders on non-BHM cities that have zero policy tiles. The legend promises a category the page doesn't deliver. Parallel to F3's R3 (mayoral overlay claim for non-BHM cities) — same "renders for cities where it doesn't apply" pattern.
**Fix:** Gate the policy parenthetical on `{% if city_policy_badges %}…{% endif %}` OR reword.

### Opus #1 S1. `list_enabled_badges` missing `description` field
**Source:** Opus #1
**Evidence:** Sibling helpers return `description`; this one doesn't. Shape inconsistency.
**Fix:** Add `description` to the return shape.

### Opus #2 S4. Trailing `?and=` on blank-option selection
**Source:** Opus #2
**Evidence:** Selecting "(none)" leaves a trailing empty `?and=` in the URL.
**Fix:** Strip empty `and` param cleanly (URL cosmetic).

---

## Category 3 — SUGGESTED, defer with tracking

### Opus #1 S2. 11 COUNT queries on cold homepage load
Cache absorbs the cost; per-badge significance gate doesn't fold cleanly into a single GROUP BY. Acceptable v1.

### Opus #2 S5. Warm/cool palette unimplemented
Spec §6.3 calls for it. Polish pass.

### Opus #2 S6. Process-only city heading mismatch
UX judgment. Defer.

### S9 (NEW, audit). Post-swap `<select>` DOM unsynced
After filter swap, the browser preserves the `<select>` element across the swap, so a freshly-computed `available_badges` list won't refresh in the dropdown. Functionally fine today (dropdown contents are stable per page load). Document constraint; revisit if dropdown contents become dynamic.

### S10 (NEW, audit). `_overview_cache` lacks per-year salt
Cache key is keyed only on `slug`, no calendar-year salt. After Dec 31→Jan 1 rollover, "this year" counts go stale up to 5 min. Edge-case acceptable; document in runbook.

### HX-Request partial-render path (the cleaner R2 fix)
Saves ~5 DB queries per filter swap and resolves S9. Defer to a small follow-up — `hx-select` is sufficient for v1.

---

## Category 4 — NICE-TO-HAVE (declined)

8 items across the three reviews (collapse helpers, module-level constants, inline-style extraction, `hx-include="this"` → spec form, etc.). All deferred indefinitely.

---

## Decision-trace verifications (no action needed)

- **`badge_volume_recent` SQL boundary:** Opus #1 verified `meeting_date >= CURRENT_DATE - %s * INTERVAL '1 day'` is mathematically correct, parameterization-safe, and timezone-sane against the DATE-typed column. Day 29/30 in, day 31 out — matches "last 30 days" intent.
- **`list_enabled_badges` UNION ALL shape:** Opus #1 confirmed the union of process + policy is the right shape for the dropdown. The strict opt-in gate that 404s process-badge category pages (R1) is a SEPARATE bug; the dropdown shouldn't be subject to it.
- **F2/F3 regression:** Auditor ran the F2 + F3 integration suites against `b3789a3` — 70/70 passing in 4.61s. No regressions.
- **`get_resolved_badge` call sites:** Auditor confirmed only ONE call site (`category_landing`). The R1 fix is downstream-safe.
- **`_overview_cache`:** Sonnet verified the cache stores rendered HTML AFTER tile zip-up — the cache covers the new tile data correctly.

---

## What the user is being asked to verify

The F2 user gate caught 4 things reviewers missed; the F3 user gate produced reflags that the auditor pass triaged. Apply the same lens here. Areas reviewers tend to under-cover:

1. **Citizen interpretation.** After R1 + R2 lands, follow a process-badge tile from `/al/birmingham/` — does the destination page carry meaningful content for a "hidden_on_consent" or "split_vote" item? Or does it render an empty list because no items currently match the badge? If empty, does the empty-state copy work for a citizen who just clicked "process transparency → split vote"?
2. **Browse-by-Priority placement on `city.html`.** Hero → Browse-by-Priority → existing KPIs → topic browse → council. Does the new section sit above or below where it makes sense? Pulling attention from the existing flow, or complementing it?
3. **Mobile.** Two grids on `city.html` + the cross-filter `<select>` on category landing. F2 caught a CSS grid + breakpoint collision; F3 didn't introduce new mobile issues but neither did F2's reviewers catch the F2 grid issue at first. Reviewers verified the new classes don't collide with existing rules but didn't deeply test mobile rendering.
4. **The auditor's sign-off question:** verbatim below.

## Sign-off question

> Proceed with the F4 fix-up loop addressing **R1 + R2 + R4 + S5 + S6 + S7 + S8 + Opus#1-S1 + Opus#2-S4** in a single fix-up commit (process-badge 200 test bundled with R1), and defer the HX-Request partial-render path, warm/cool palette, calendar-year cache salt, and remaining NICE-TO-HAVE items to post-merge follow-ups?
