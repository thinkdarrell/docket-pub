# F4 Sonnet 4.6 Second-Look

**Commit:** b3789a3
**Branch:** feat/impact-first-phase-2-track-3
**Reviewer:** Sonnet 4.6 (mandatory second-look, independent of Opus angles)

## Summary

Both Opus REQUIREDs R1 and R2 are confirmed with live reproduction evidence. R3 (double-fire) is
downgraded to SUGGESTED: in HTMX 2.0.4 a form element without a verb (hx-get/hx-post/etc.) does
not issue an HTMX request when its trigger fires, so the form's hx-trigger is dead code rather
than a second-request source. R4 (aria-hidden grammar) is confirmed. The cross-cutting check adds
one important scope clarification to R1: the 404 affects every city's process-badge tiles (all 5
real cities), not only Birmingham. No regressions in the full 131-test integration suite and no
regressions in the 817-unit suite.

---

## Verification of Opus REQUIREDs

### R1 (process-badge 404): CONFIRMED — scope expanded

Reproduced directly with Flask test client:

```python
client.get('/al/birmingham/hidden_on_consent/')   # → 404
client.get('/al/birmingham/sole_source/')          # → 404
client.get('/al/birmingham/contested/')            # → 404
client.get('/al/birmingham/blight_accountability/')  # → 200  (control)
```

Root cause confirmed in `src/docket/services/query.py:1017-1036`: `get_resolved_badge` uses an
INNER JOIN against `priority_badges_config`, and process badges are intentionally absent from that
table. All 7 process badge slugs return `None` from this function → `category_landing` line 245-246
aborts with 404.

**Scope expansion:** The Opus review described this as a Birmingham issue (7 dead tiles). The Browse-
by-Priority section in `city.html:68-133` renders process tiles for ALL cities — `list_process_badges()`
reads from `priority_badge_templates` directly (no city filter). Verified:

```python
client.get('/al/mobile/hidden_on_consent/')        # → 404
```

Mobile's homepage also renders 7 process tiles (confirmed in test run), and all 7 link to 404
pages. The bug affects every city that renders a Browse-by-Priority section, which is all cities
with `process_badges or city_policy_badges` (the template guard at `city.html:68`). Since
`list_process_badges()` always returns 7 badges regardless of city, every deployed city has 7 dead
process-badge tile links.

The Opus #1 LEFT JOIN fix is sound — tested the proposed SQL:
```sql
SELECT t.slug, t.kind, c.enabled
FROM priority_badge_templates t
LEFT JOIN priority_badges_config c
  ON c.template_slug = t.slug AND c.city_id = %s
WHERE t.slug = %s
  AND (t.kind = 'process' OR c.enabled = TRUE)
```
Returns the correct row for process badges (enabled=NULL, passes `kind='process'` branch) and
policy badges (enabled=TRUE, passes the OR branch). Fix is confirmed correct.

### R2 (HTMX swap dumps full page into #item-list): CONFIRMED

`category_landing` extends `base.html` (verified: `category_landing.html:1`). There is no HTMX
partial path — confirmed by grepping the entire `src/` tree:

- `grep -rn "hx-select" src/` → no results
- `grep -rn "HX-Request" src/` → no results

The `<select>` carries `hx-get` pointing to `category_landing`, which returns a full HTML document.
Without `hx-select`, HTMX 2.0.4 uses the entire response body as the swap content and injects it
into `#item-list`'s `innerHTML`. The result is a page-within-a-page: masthead, hero, KPIs, filter
section, item list, and footer all nested inside the items section. This is a UX break, not
deferred polish — `hx-push-url` updates the address bar (giving an illusion of correctness) but
the visual result is unusable.

The implementer's comment at `category_landing.html:156-160` describes this as "bookmark-friendly
today via hx-push-url + the route always returns a full page" — this misidentifies the problem.
Bookmark-friendliness (full-page reload) works; the HTMX interaction does not.

Fastest fix: add `hx-select="#item-list"` to the `<select>`. HTMX will then extract just the
`#item-list` section from the full-page response and swap it in. This is a two-word change.
Cleaner fix: detect `HX-Request` header in the route and return a partial.

### R3 (form + select double-fire): NUANCED — downgrade to SUGGESTED

The Opus #2 reviewer rated this 85% confident. After examining HTMX 2.0.4 semantics, I believe
this is not a double-fire bug in practice.

In HTMX 2.x, an element with `hx-trigger` but **no verb** (`hx-get`, `hx-post`, `hx-put`,
`hx-patch`, `hx-delete`) registers event listeners but does NOT issue an HTMX request when the
trigger fires. The form at `category_landing.html:109-112` has:

```html
<form class="cross-filter-form" style="padding: 8px 0;"
      hx-target="#item-list"
      hx-trigger="change from:select.cross-filter"
      hx-push-url="true">
```

No verb is present. When the `<select>`'s change event bubbles to the `<form>`, HTMX registers the
trigger match but `issueAjaxRequest()` is never called (no method to determine request URL and
type). Native form submission does not trigger from a `change` event — only a `submit` event does.
So the form fires no HTMX request and no native GET.

The form's `hx-target`, `hx-trigger`, and `hx-push-url` attributes are **dead code**: they express
intent but produce no behavior. This is a code-clarity and maintainability issue (SUGGESTED), not a
functional double-fire.

**Note:** I cannot browser-test this (read-only environment). If the maintainer wants absolute
certainty before the fix-up, they should open DevTools Network tab, pick a filter, and verify 1 vs.
2 requests fire. My assessment is that HTMX 2.0.4 requires a verb and thus only 1 request fires.

The clean fix (per Opus #2 and the spec's own example) is to strip the HTMX attrs from the
`<form>` entirely and keep them on the `<select>`. The spec's §6.8 example shows a bare `<select>`
with no form wrapper.

### R4 (✨ aria-hidden makes legend sentence ungrammatical for SR): CONFIRMED

`city.html:34`:
```html
A <span class="badge-spark" aria-hidden="true">✨</span>
means independent sources agree on the tag.
```

A screen reader user hears: "A means independent sources agree on the tag." The subject is missing.

Correct pattern from `partials/badge_chip.html:33`:
```html
{% if conf >= 1.0 %}<span class="badge-spark" aria-label="AI-verified">✨</span>{% endif %}
```

The chip uses `aria-label="AI-verified"` (not `aria-hidden`), so screen readers hear the semantic
meaning. Two fixes satisfy the spec (§line 2745-2746):

1. **Preferred:** Change `aria-hidden="true"` to `aria-label="AI-verified"` on the legend spark —
   matches the chip pattern exactly.
2. **Alternative:** Rewrite surrounding copy so the sentence is grammatical without the glyph: "The
   ✨ sparkle icon means independent sources agree on the tag." (`aria-hidden="true"` then works
   because the sentence's subject is the surrounding text, not the glyph).

---

## Cross-cutting check

### a. Test coverage gap pattern

Audit of all 22 new F4 tests for "asserts structure without exercising behavior":

**Confirmed gap — tile count values not asserted.** Tests
`test_city_homepage_policy_tile_shows_count_with_year_label` (line 446) and
`test_city_homepage_process_tile_shows_count_with_30day_label` (line 458) each insert one item with
a matching badge, render the homepage, and then only assert:

```python
assert "this year" in body      # line 455
assert "last 30 days" in body   # line 466
```

Neither test asserts that the COUNT VALUE (e.g., "1") appears next to the tile. A route bug that
passed `count=0` for all tiles would pass these tests. The query-layer tests (`test_badge_volume_year_*`,
`test_badge_volume_recent_*`) correctly test the count logic in isolation, but the template rendering
of the count is not covered end-to-end.

**Confirmed gap — no test follows process badge tile links.** `test_city_homepage_renders_seven_process_tiles`
(line 435) asserts the href appears in the rendered HTML — it never does
`client.get('/al/birmingham/hidden_on_consent/')`. This is the exact gap that masked R1. There is
no test in the entire F4 suite that requests a process-badge category page and checks `status_code == 200`.

**No other structural-assertion gaps found** in the remaining 18 tests. The query helper tests (lines
194-332) all assert actual return values from the DB. The dropdown tests (lines 340-408) assert
specific HTML attribute values and pre-selection patterns. The legend tests check content within the
legend region. These are all adequate.

### b. Existing-feature regressions

Ran the full integration suite with zero regressions:

```
Full integration suite (without F4): 109 passed in 5.44s
F2 category_landing tests:           31 passed in 2.34s
F4 new tests:                        22 passed in 1.74s
Total integration:                   131 passed in 7.32s
```

Unit suite: `817 passed, 5 xfailed` (no change from pre-F4 baseline).

Specific spot-checks:
- `category_landing.html` F3 volume timeline (lines 66-74): `{% if timeline is defined %}` guard
  is unchanged; the new filter controls block (lines 103-132) is inserted AFTER the timeline
  section, not inside it. F3 surface intact.
- `category_landing.html` F2 KPI strip and chip filtering: chip row (`cross_filter_badges` render)
  at lines 134-152 is unchanged. F2 surface intact.
- `city.html` hero, KPIs, topic browse: all unchanged above and below the new Browse-by-Priority
  section (lines 68-133). The guard `{% if city_policy_badges or process_badges %}` means the
  section is silently absent if both lists are empty — no layout breakage.

### c. Spec/code drift

Spec §6.7 (line 3196-3229) uses Jinja template calls `{{ badge_volume_year(city.id, badge.slug) }}`
as illustrative pseudocode. The implementation correctly adopts F2's route-side pre-compute pattern
instead (counts are computed in the route and passed as context), which is the established F2
convention. This is a deliberate, appropriate deviation — not a bug or an uncaught divergence.

The one non-spec addition: the implementation wraps the `<select>` in a `<form>` element. The spec's
§6.8 example shows a bare `<select>` with no form wrapper. The `<form>` is the source of the dead
code in R3 and also contributes to the code-clarity issue Opus #2 flagged (finding #8: form-without-
action is an accessibility smell).

### d. Other F2-era latent bugs F4 might surface

**Cross-filter slug validation gap.** The route at `public.py:253-254` accepts any string as a
cross-filter slug without validating it against `list_enabled_badges`. Spec §6.8 says "validates
against enabled badges." An invalid or unrelated slug silently returns 0 items (the EXISTS subquery
in `list_items_by_badge:960-970` doesn't city-scope the sub-query — it only checks `badge_slug`, not
`city_id` on the `x` alias). This is a pre-F2 gap. F4 surfaces it via the new dropdown: if a citizen
manually edits the URL to `?and=fake_badge`, they get an empty list with no error. Low severity
(data is read-only), but contradicts the spec's validation intent. Classify SUGGESTED.

**Also note:** the EXISTS subquery in `list_items_by_badge` has a subtle omission — it doesn't
filter by `x.city_id`. This means a cross-filter for `blight_accountability` on Birmingham would
also match items tagged `blight_accountability` by a DIFFERENT city if that item happened to appear
in Birmingham's meeting list. In practice this can't happen because items belong to only one city's
meetings, but the intent would be cleaner with `AND x.city_id = %s` added to the EXISTS clause.
Pre-F4 gap; F4 doesn't worsen it.

---

## New findings (missed by both Opus rounds)

### REQUIRED

None beyond R1/R2. All four Opus REQUIREDs are addressed above.

### SUGGESTED

**S5 — Cross-filter validation omitted (spec §6.8 requires it).** Route accepts arbitrary `?and=`
slugs without validating against `list_enabled_badges`. A handcrafted URL with an unknown slug
silently returns 0 items. Fix: after building `cross_filters`, filter to slugs that appear in
`list_enabled_badges(municipality["id"])`. One list-comprehension addition in the route.

**S6 — R3 cleanup: strip dead HTMX attrs from `<form>`.** Even if R3 doesn't double-fire (see
above), the form's `hx-target`, `hx-trigger`, and `hx-push-url` with no verb are misleading.
Remove them, or remove the `<form>` entirely (per spec's bare-select pattern). If `<form>` is
kept for no-JS fallback, add `action="{{ url_for('public.category_landing', ...) }}"
method="get"` and a `<noscript>` submit button. If it's not kept, use a `<div>` wrapper.

**S7 — Tile count render not tested end-to-end.** Add assertions that the count integer appears in
the rendered tile, not just the label text. E.g., after inserting 1 item with a blight badge, assert
`"1 this year"` appears in the HTML (not just `"this year"`). Without this, a route regression that
passed `count=0` to all tiles would go undetected.

### NICE-TO-HAVE

**N1 — Process-badge test for category page 200.** Add a test in `test_f4_browse_by_priority.py`
that does `client.get('/al/birmingham/hidden_on_consent/')` and asserts `status_code == 200` (after
the R1 fix lands). This is the exact test that would have caught R1 in the original suite.

**N2 — Spec's `hx-include` vs implementation.** Spec §6.8 uses `hx-include="[name='and']"`;
implementation uses `hx-include="this"` on the select. Functionally equivalent for a single
`<select name="and">`, but the spec's form is more defensive if a second `name='and'` input were
ever added. Worth aligning for consistency; not blocking.

---

## Findings to downgrade or refute

**R3 (Opus #2: "form + select double-fire" → REQUIRED):** Downgraded to SUGGESTED. The form has
`hx-trigger` and `hx-target` but no HTMX verb. In HTMX 2.0.4, a verb is required to issue a
request. The form's attributes are dead code, not a live double-fire source. The Opus #2 reviewer
said 85% confidence but did not account for the no-verb case. Clean-up is still warranted (S6
above), but this should not block merge.

**Opus #2 performance concern about cache not covering tile data:** Not a bug. The cache stores the
fully-rendered HTML string (including tile counts). The tile queries fire at cache-miss time
(before `render_template`), the result is baked into `rendered`, and `rendered` is what's cached.
Cache hits return the pre-rendered HTML with tiles included. Opus #2 did not explicitly claim this
was a bug — it was a concern flagged for Opus #1 to verify — but I am confirming it is correct.

---

## Final categorization recommendation for the user packet

### Aggregate REQUIRED list (deduplicated):

1. **R1 — Process-badge category landing pages 404.** All 7 process tiles on every city's homepage
   are dead links. Fix: LEFT JOIN + `(t.kind = 'process' OR c.enabled = TRUE)` in
   `get_resolved_badge`. Add a test that follows process-badge tile links.

2. **R2 — HTMX swap dumps full page into `#item-list`.** Filter selection breaks the page
   visually. Fix: add `hx-select="#item-list"` to the `<select>` (two words). Alternatively detect
   `HX-Request` header in the route and return a partial.

3. **R4 — `✨` `aria-hidden` makes legend sentence ungrammatical for screen readers.** "A means
   independent sources agree on the tag." Fix: use `aria-label="AI-verified"` (matching the chip
   pattern) or rewrite surrounding copy to make the sentence grammatical with the glyph silenced.

### Aggregate SUGGESTED-accept (in fix-up):

1. **S5 (new) — Cross-filter slug validation.** Spec §6.8 requires validation; route accepts
   arbitrary slugs, returning empty list silently.

2. **S6 (new, = R3 recat) — Strip dead HTMX attrs from `<form>`.** Form has trigger + target +
   push-url but no verb; attributes are inert and misleading. Clean up or remove form wrapper.

3. **S7 (new) — Tile count value not tested end-to-end.** Tile tests assert "this year" label text
   but not the rendered integer count. Add count-value assertions.

4. **Opus #1 S1 — `list_enabled_badges` missing `description` field.** Only 4 keys vs. 5 in
   sibling helpers. Harmless today but KeyError risk for future callers.

5. **Opus #2 S4 — Trailing `?and=` on blank-option selection.** Ugly-but-functional URL; clean up
   with `hx-on::config-request` or accept cosmetic hit.

### Aggregate SUGGESTED-defer (acknowledge, ship anyway):

1. **Opus #1 S2 — 11 COUNT queries on cold homepage load.** Cached for 5 min; each query hits the
   composite index; acceptable for v1. Monitor with EXPLAIN smoke check post-deploy.

2. **Opus #2 S5 — Warm/cool palette unimplemented.** `priority-tile--policy` vs
   `priority-tile--process` have no CSS differentiation. Spec §6.3 calls for it; acceptable
   deferred follow-up.

3. **Opus #2 S6 — Process-only city heading mismatch.** "Browse by priority" header reads as
   policy-priority but only oversight-signal tiles show for non-BHM cities. UX judgment call;
   defer to post-phase clarity.

4. **Opus #2 S8 — Form without semantic submit purpose.** `<form>` with no action/submit is an
   accessibility smell. Addressed by S6 above; if S6 is deferred separately, this falls out.

### NICE-TO-HAVE (deferred):

1. **N1 — Process-badge page 200 test.** Add after R1 fix.
2. **N2 — `hx-include` alignment with spec.** Functionally equivalent; cosmetic.
3. **Opus #1 NTH-1 — Collapse `badge_volume_year`/`badge_volume_recent` into one helper.** ~30
   LOC saved; not urgent.
4. **Opus #1 NTH-2 — `process_alarm_order` module-level constant.** Deduplication of list
   duplicated in two helpers.
5. **Opus #2 NTH-9 — Extract inline styles to CSS.** The `.priority-grid` / `.priority-tile`
   declarations are duplicated in `city.html:93-94` and `city.html:114-115`. Lift to stylesheet
   in next polish pass.
