# F4 Review #1 — Route + Helpers (Opus)

**Commit:** b3789a3
**Branch:** feat/impact-first-phase-2-track-3
**Reviewer angle:** Route + service-layer helpers (parallel review, non-overlapping with template/UX angle)

## Summary

The 5 new helpers are clean, correct, well-commented, and parity-faithful with F2's `category_kpis` / `list_items_by_badge` (significance gate, confidence gate, status gate all match). SQL is fully parameterized; the 30-day boundary is mathematically correct. Tests pass (22/22 green locally).

The blocking finding is **not in F4's helpers** but in the route surface F4 newly exercises: `category_landing` (F2) calls `get_resolved_badge`, which inner-joins on `priority_badges_config` and 404s on every process-badge slug. F4 ships 7 homepage tiles linking citizens straight at those URLs. Reproduced live: `GET /al/birmingham/hidden_on_consent/ → 404`. F4's homepage section ships 7 dead-end tiles.

## REQUIRED (must-fix before merge)

- **Process-badge category landing pages 404, but F4 ships 7 homepage tiles linking to them** at `src/docket/web/public.py:244` (the F2 line `badge = query.get_resolved_badge(...)`). Evidence:
  - `get_resolved_badge` (`query.py:1017-1036`) inner-joins `priority_badge_templates t` against `priority_badges_config c` and requires `c.enabled = TRUE`. Process badges are intentionally **not** seeded into `priority_badges_config` (per migration 013 lines 390-394 — only policy badges are CROSS JOIN'd into the config table). So `get_resolved_badge(birmingham_id, 'hidden_on_consent')` returns `None`.
  - `category_landing` (line 244-246): `if not badge: abort(404)` → every process-badge URL 404s.
  - **Reproduced live** against local DB: `client.get('/al/birmingham/hidden_on_consent/') → 404`.
  - F4 in this commit (`city.html:117-118`, confirmed via grep) emits `<a href="{{ url_for('public.category_landing', ..., badge_slug=b.slug) }}">` for each of the 7 process badges. Citizens clicking any of them land on a 404. The Browse-by-Priority "Process transparency" subsection becomes a row of dead links the moment this commit deploys.
  - Test gap that masked it: `test_city_homepage_renders_seven_process_tiles` (lines 435-443) only asserts the LINK is present in the HTML — it doesn't follow the link. The dropdown tests all use a policy slug (`blight_accountability`) for the primary, so they never exercise the process-badge route.
  - Recommended fix (route-side, simplest): teach `get_resolved_badge` to fall back to the template alone when `kind = 'process'`. Process badges are always-on per the spec (decision #11, §4.2); requiring a config row was a F2 oversight, not a deliberate gate. Sketch:
    ```sql
    SELECT t.slug, t.name, t.description, t.icon, t.kind, COALESCE(c.enabled, TRUE) AS enabled
    FROM priority_badge_templates t
    LEFT JOIN priority_badges_config c
      ON c.template_slug = t.slug AND c.city_id = %s
    WHERE t.slug = %s
      AND (t.kind = 'process' OR (c.enabled = TRUE))
    ```
    With name/description override applied via `COALESCE(c.name_override, t.name)` etc. This keeps the existing F2 contract for policy badges (enabled=TRUE required) and unblocks process badges.
  - Also add a test in `test_f4_browse_by_priority.py` that exercises a process-badge category page end-to-end (e.g., `client.get('/al/birmingham/hidden_on_consent/').status_code == 200` plus a check that the dropdown is present).

## SUGGESTED (should-fix, can be deferred)

- **`badge_volume_year` and `badge_volume_recent` are not exercised through the cache** at `src/docket/web/public.py:73-75`. The `_overview_cache` short-circuits BEFORE the badge-tile precompute, so on cache hits the 11 COUNT queries are skipped (good). On cache miss, all 11 fire serially. With 33K active links and the seed index `idx_agenda_item_badges_city_slug_conf (city_id, badge_slug, confidence DESC)`, each query should be well under 10ms — but post-Phase-3 backfill (~37K LLM-eligible items added) the picture changes. The implementer's own comment at `public.py:99-104` flags the GROUP BY refactor as a follow-up; recommend leaving the comment AND filing a TODO ticket, OR refactoring now since the refactor is small. The single-query form would be:
  ```sql
  SELECT badge_slug, COUNT(*) AS n
  FROM agenda_item_badges aib
  JOIN agenda_items ai ON ai.id = aib.agenda_item_id
  JOIN meetings m      ON m.id = ai.meeting_id
  WHERE aib.city_id = %s
    AND aib.confidence >= 0.6
    AND ai.processing_status = 'completed'
    AND m.meeting_date >= %s
    -- (significance gate is per-badge so it can't fold cleanly here without a CASE)
  GROUP BY badge_slug
  ```
  The per-badge significance gate is the wrinkle — for policy badges with min_sig=3 vs. process badges with no gate, you'd need a CASE inside the WHERE or two queries (one per kind). Not a clean win; the helper-per-tile shape is fine if the cache holds. Verdict: keep current shape, but add a Railway-side EXPLAIN smoke check in the post-deploy runbook to confirm the index is actually used at scale.

- **`list_enabled_badges` returns inconsistent dict shape vs. its policy/process siblings** at `src/docket/services/query.py:1711-1731`. Both UNION arms project `slug, name, icon, kind` (4 keys), but `list_city_policy_badges` returns 5 keys (`+ description`) and `list_process_badges` returns 5 keys (`+ description`). The dropdown template only consumes `slug, name, icon` so this is currently harmless — but a future caller that does `b['description']` on `list_enabled_badges` output will hit `KeyError`. Recommend adding `description` to both UNION arms (with override COALESCE in the policy arm) to keep the four helpers shape-symmetric. Pure consistency play; not blocking.

- **`badge_volume_year` and `badge_volume_recent` integer-coerce the COUNT correctly, but the count value is unconstrained for negative `days`.** At `query.py:1614`, `days` is interpolated as a parameter. `days=-5` would yield `meeting_date >= CURRENT_DATE - (-5) * INTERVAL '1 day'` = `CURRENT_DATE + 5 days` (future), which silently returns whatever items have future meeting dates. Not a security issue (not user-controlled — the route always passes `days=30`), but defensive programming would `assert days >= 0` or clamp. Suggested.

- **`list_city_policy_badges` sorts `ORDER BY name` in SQL on the override column.** At `query.py:1661`, the SQL sort uses the alias `name` after the COALESCE. This works in PostgreSQL (column aliases are honored in ORDER BY), but in some other engines (and historically in MySQL pre-8.0) it'd be ambiguous. Pure portability nit; PostgreSQL is the only target. Leave as-is.

## NICE-TO-HAVE (optional polish)

- The two helpers `badge_volume_year` and `badge_volume_recent` are 90% identical. Both could collapse into a single private `_badge_volume_in_window(city_id, slug, start_date, end_date)` taking a date range, with `badge_volume_year` and `badge_volume_recent` as thin wrappers. Saves ~30 LOC and one place to fix the next significance-gate refinement. F-track established the precedent of letting helpers stay shape-aligned with their consumers, so this isn't urgent.

- `process_alarm_order` is duplicated verbatim in `list_enabled_badges` (line 1694) and `list_process_badges` (line 1764). Lift to a module-level constant. Saves a copy-paste drift hazard if alarm order changes.

- The implementer's docstring for `badge_volume_recent` (lines 1597-1600) candidly explains the `days=0` edge case ("returns the count for today alone"). This is honest and useful. Leave as-is.

## Implementer-flagged question responses

1. **`list_enabled_badges` UNION ALL shape:** **Right shape.** The dropdown should offer process badges as cross-filter options (a citizen on `/blight_accountability` should be able to refine to "...also tagged hidden_on_consent"). `get_resolved_badge`'s strict gate is the wrong model for the dropdown because (a) it gates on per-city opt-in, which doesn't apply to process badges, and (b) cross-filter slugs feed into `list_items_by_badge`'s `EXISTS` subquery, which doesn't itself require a config row. The UNION-ALL split correctly mirrors the actual data model: process = template-only, policy = template + config. The fact that `get_resolved_badge` 404s on process badges is the OTHER side of this same disconnect (see REQUIRED finding) — that's the bug, not `list_enabled_badges`'s shape.

2. **`badge_volume_recent` SQL boundary:** **Correct** on all three sub-questions:
   - **Spec intent:** "last 30 days" is inclusive of today and 30 days ago. The expression `CURRENT_DATE - 30 * INTERVAL '1 day'` resolves to a `timestamp without time zone` at `00:00:00` of the boundary date. With `meeting_date` as `DATE`, the implicit cast yields `boundary_date 00:00:00`, and `meeting_date >= boundary_date 00:00:00` is TRUE for `meeting_date == boundary_date` (calendar-inclusive on the back boundary). Day 29 in, day 30 in, day 31 out — verified by `test_badge_volume_recent_30_day_boundary` against live DB.
   - **Parameterization safety:** `days` is bound as `%s` and psycopg2 coerces the Python int to a PostgreSQL integer. The expression `%s * INTERVAL '1 day'` is a multiplication of an integer parameter against a literal interval — no string concatenation, no injection vector. Confirmed safe.
   - **Timezone behavior:** `CURRENT_DATE` returns the session's date in the server's configured timezone. `meeting_date` is stored as `DATE` (no timezone). Both sides see "calendar day" semantics, which is correct for "last 30 days" UX. The only risk is if Railway's server timezone drifts from the user's expectation around midnight UTC vs. America/Chicago — but homepage counts don't need second-level precision and the 5-min cache absorbs it.

3. **11 COUNT queries on homepage cold load:** **Acceptable for v1, defer GROUP BY refactor.** Reasoning:
   - The 5-min `_overview_cache` absorbs repeated hits; a cold render does the 11 queries once per 5 minutes per city slug.
   - All 11 queries hit the same composite index `idx_agenda_item_badges_city_slug_conf (city_id, badge_slug, confidence DESC)` from migration 013 (line 263). At Railway scale (~33K active links, mostly Birmingham), each query is small-row-count + index-leading-predicate-driven; single-digit ms per query is the realistic budget.
   - Local EXPLAIN shows Seq Scan due to tiny test data — not representative. A Railway-side EXPLAIN check should land in the deploy runbook (see SUGGESTED #1).
   - The single-GROUP-BY refactor is **not** clean because the per-badge significance gate (default 3 for policy badges, none for process) doesn't fold into one WHERE clause without a CASE expression keyed off badge kind. Two separate aggregate queries (one for policy with sig gate, one for process without) would work but the savings vs. the current 11-helper-call shape are marginal once the cache is warm.
   - Action: keep the current shape, but file a follow-up note for the post-Phase-3 perf review.

## Out-of-scope observations

- **Template/UX angle (defer to reviewer #2):** The badge legend text, the BHM-specific copy, the responsive grid layout, the `priority-tile` class styling, and the legend `<p>...</p>` content are all in `city.html` lines 80+. The legend test (`test_badge_legend_has_no_internal_jargon`) does a substring scan against a region delimited by `id="badge-legend"` and the next `</p>` — works for a single-paragraph legend but would silently pass if the legend grew to multiple paragraphs and jargon landed in the second paragraph. Reviewer #2 should also gut-check the citizen-readability of the legend prose itself, which is out of my SQL/route scope.

- **Substring-thin tests (mixed scope):** `test_city_homepage_policy_tile_shows_count_with_year_label` (line 446) and `test_city_homepage_process_tile_shows_count_with_30day_label` (line 458) insert a single item, render the page, and only assert the literal text "this year" / "last 30 days" appears. They don't assert the COUNT VALUE renders correctly (e.g., that "1" appears next to the policy tile after one matching item is inserted). A stronger test would parse the tile's `priority-tile__count` div and assert the integer matches `badge_volume_year(...)`. Recommend tightening — but this is also partly a template-rendering concern.

- **Test data ordering invariant (nice-to-have observation):** `test_list_enabled_badges_combines_policy_and_process` (line 316) asserts `max(process_idx) < min(policy_idx)` — process before policy. Good. But it doesn't assert that `process_alarm_order` is preserved verbatim within the process bucket. A test that asserts the FIRST process slug is `hidden_on_consent` and the LAST is `amends_prior_contract` is at line 331-332 — that catches the boundary but not the middle. Could be tightened to assert the full 7-element slice equals the expected list. Not blocking.

- **Decision-log integrity:** F4 commit doesn't add a new decision number, and the implementation faithfully follows §6.7 + §6.8 + decision #74. No silent invention spotted in the helper layer. The "tile shows 0" empty-state behavior is implicit (the template renders `{{ b.count }}` which would render "0" when no items match) and not explicitly spec'd, but a "0 this year" tile is the obvious natural fallback and matches citizen expectation.
