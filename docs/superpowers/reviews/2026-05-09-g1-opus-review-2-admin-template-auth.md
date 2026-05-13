# G1 Review #2 — Admin Route + Template + Auth (Opus)

**Commit:** 0549963

## Summary

The G1 admin route, template, and auth slice are tight, correct, and consistent with the existing admin templates (`members.html`, `ai_panel.html`). Auth gating is wired through the same blueprint-level `before_request` hook as the rest of `admin.py`, redirect-with-`next` works, and the four route-layer tests cover the meaningful auth + render behaviors. Two real issues — `cal-panel` is referenced in markup but undefined in any stylesheet (panel boundaries collapse to default browser flow), and Panel A's `triggers_fired` cell renders a Python list-of-dicts via `__str__` (Jinja autoescape treats it as a string), so admins see ``[{'trigger': 'yellow_settlement'}]`` rather than anything readable. Everything else is acceptable for a v1 admin surface.

## REQUIRED

- **`cal-panel` class is referenced but never defined.** `src/docket/web/templates/admin/calibration.html` lines 39, 82, 127, 173, 225, 272 attach `class="cal-panel"` to each `<section>`, but `grep` across all six stylesheets (`styles.css`, `layout.css`, `councilmatic.css`, `tweaks.css`, `css/smart_brevity.css`, `mobile.css`) returns zero matches for `cal-panel`. Six `<section>` elements stack with zero spacing, no rule, no padding — visually they bleed into one another (the default `<section>` margin is 0). For an admin scanning surface this hurts triage even at v1. Either (a) drop the class entirely (it's dead markup) or (b) add a 4-line rule in `tweaks.css`: `.cal-panel { margin: 32px 0; padding-top: 16px; border-top: 1px solid var(--rule); } .cal-panel:first-of-type { border-top: 0; }`. This is a 5-minute fix and required for the page to feel like a dashboard rather than a dump.

- **Panel A `triggers_fired` renders Python `repr`, not raw JSON.** `src/docket/services/calibration.py:84` returns `ai.score_overrides->'triggers'` — psycopg2 deserializes JSONB to a native Python `list[dict]`. `calibration.html:68` then renders `{{ row.triggers_fired }}` which calls `__str__` on the list, producing ``[{&#39;trigger&#39;: &#39;yellow_settlement&#39;}]`` (single quotes, HTML-escaped). The implementer's framing assumes JSON-as-text; what admins actually see is Python repr with escaped apostrophes. Two acceptable v1 fixes:
  - Cast in SQL: change `ai.score_overrides->'triggers'` to `ai.score_overrides->>'triggers'` (text) — at least admins get valid JSON.
  - Humanize in the template: `{% for t in row.triggers_fired %}<span class="t-mono">{{ t.trigger }}</span>{% if not loop.last %}, {% endif %}{% endfor %}`. This is the implementer's `floors.py FloorTrigger.name` follow-up but actually the trigger names already live inside the JSONB payload (key `trigger`); no `floors.py` import needed for v1.
  - Either is required because the current rendering is neither the JSON the implementer described nor anything legible.

## SUGGESTED

- **`data-panel="..."` should stay as-is, not become a class.** The template currently uses these as test hooks (the four route-layer tests in `test_calibration.py:637-644` assert their presence). Promoting them to classes would conflate styling and testing concerns — the F4/F5 reviews have called out exactly this pattern as good. Verdict: keep the data-attributes, see REQUIRED above for the actual styling fix.

- **6 fresh DB connections per page load.** Each query function in `calibration.py` opens its own `db_cursor()`, which (per `db.py:23-34`) calls `psycopg2.connect()` and closes it. The route invokes 6 of them sequentially, so a single `/admin/calibration` GET costs 6 TCP handshakes + 6 auth roundtrips. On Railway's external proxy that's ~300ms of pure connection overhead. Two cleanup options for a follow-up: (a) add a service helper `query_all() -> dict[str, list]` that opens one connection and runs all six queries on it, or (b) add a connection pool. Acceptable for v1 since traffic is essentially single-digit/day and `login_required` blocks accidental hits.

- **Sequential vs parallel orchestration.** `admin.py:243-248` invokes the six queries inline as keyword arguments to `render_template`. Python evaluates left-to-right, so they're sequential. For an admin-only page, sequential is the right choice (parallel via `concurrent.futures` would multiply the connection problem above by 6). Flag for the future if/when the page slows down: parallel + shared connection isn't trivial.

- **Heading hierarchy is correct but page lacks navigational landmarks.** `<h1>Calibration</h1>` at line 19, six `<h2>` per panel — clean semantic structure, screen-reader-friendly. The page is missing a "skip to content" link and there's no `<nav>` landmark on the breadcrumb-y "Council Members ← AI Pipeline →" line, but neither is on `members.html` or `ai_panel.html` either, so this is a global admin-template gap, not a G1 regression.

- **No caching for v1 — concur with implementer's choice.** Admin traffic is ~zero, the page is gated behind `login_required`, and the F5 cache helper requires `threading.Lock` + double-checked locking which is non-trivial. Adding a TTL cache here for v1 is premature optimization. The docstring at `admin.py:232-237` already explains the F5 fallback path if the page slows down later. Verdict: keep no-cache.

- **Empty-state copy is admin-appropriate.** `calibration.html:13-15` defines `{% macro empty_state() %}` rendering "No items match this query in the current window." — precise, technical, no smiley-face citizen tone. Same string in all six panels, which is fine because per-panel windows are documented in each panel's own `t-meta` description above. Could be sharper ("No rows in 24h window" / "No (action_type, prompt_version) categories above 20%/30 threshold") but the shared macro is fine for v1.

- **No alert thresholds visualized.** Spec calls out two clear thresholds (>40% deterministic_only/llm_only on the badge volume panel; >20% boost on B1; >5 removals on FP). The query already pre-filters above threshold for B1, B2, and FP, so any row that surfaces is by definition an alert. Badge volume returns *all* rows in the 12-week window (no threshold applied at SQL layer), so the >40% threshold from spec needs eyeball work on the admin's side. A 1-line CSS rule like `.cal-alert { background: #fff3e0; }` plus a Jinja `{% if row.pct_deterministic_only > 40 or row.pct_llm_only > 40 %}cal-alert{% endif %}` on the row would solve this. Suggested, not required, since the fix is small but the design pass might want to control this color choice.

## NICE-TO-HAVE

- **Numbers are right-aligned via `t-tnum`** (`styles.css:78`) which sets `font-feature-settings: tnum 1, lnum 1` — that's tabular numerals, not `text-align: right`. The columns *look* right-aligned-ish because of fixed-width digits, but a strict admin scan benefit (decimal column alignment) would need an explicit `text-align: right` either on the class or per `<td>`. Low-priority since admin tables don't need to be financial-statement-grade.

- **Tables on narrow viewports overflow.** Five of the six tables have ≥6 columns; on a 768px tablet they'll either horizontally scroll (browser default) or compress unreadably. `mobile.css` has no rule for admin tables. Admin pages are desktop-first, but a `.cal-panel { overflow-x: auto; }` or wrapping each `<table>` in `<div style="overflow-x: auto">` would be cheap and avoid layout breakage. Optional.

- **Per-panel descriptions use back-tick-equivalent `<code>` blocks** which is good for admin tone (`action_type`, `prompt_version`, `pct_deterministic_only`). Consistent across all six panels.

- **`t-mono` font-size override hardcoded inline** at lines 68, 198, 252 (`style="font-size: 12px;"`) — three repeated inline styles. Could move to a `.cal-panel .t-mono { font-size: 12px; }` rule when adding the panel-spacing rule above. Cosmetic.

- **No `loop.index` row numbers.** When the badge_volume panel returns 30+ rows of `(city, badge, week)` tuples it'll be a wall of similar-looking data. A `<th>#</th>` column or `tr:nth-child(even) { background: var(--paper-2); }` would help. Minor.

## Implementer-flagged question responses

1. **Raw-JSON `triggers_fired` rendering:** Not acceptable as currently shipped — but for a different reason than the implementer stated. The cell renders Python `repr()` of a list-of-dicts (because `score_overrides->'triggers'` returns JSONB → list, not text), so admins see ``[{'trigger': 'yellow_settlement'}]`` HTML-escaped. Either cast to text in SQL (`->>` not `->`) or render `{% for t in row.triggers_fired %}{{ t.trigger }}{% if not loop.last %}, {% endif %}{% endfor %}`. The `floors.py FloorTrigger.name` lookup the implementer suggested is *unnecessary* for v1 — the trigger name (`yellow_settlement`) is already what `floors.py` calls it. Just render the names. See REQUIRED.

2. **`data-panel` test hooks vs. class:** Keep as `data-panel`. The four tests at `test_calibration.py:637-644` rely on these as stable test hooks; promoting to classes would conflate test contract with style contract. The actual problem is that `class="cal-panel"` *exists* alongside `data-panel` but *isn't* styled — fix the styling on `cal-panel` (REQUIRED), keep `data-panel` for tests.

3. **No caching for v1:** Concur. Login-gated admin surface, single-digit daily traffic, F5's threading-lock pattern is non-trivial to port for marginal benefit. The docstring at `admin.py:232-237` already documents the upgrade path. Keep no-cache.

## Out-of-scope observations

(deferred to reviewer #1 — SQL queries + service module)

- `triggers_fired` returned as JSONB list rather than text affects template rendering (REQUIRED above) but the call site is reviewer #1's `query_a_per_item_divergence` SQL on line 84 of `calibration.py`. Either side can fix.
- `query_badge_volume_calibration` returns *all* rows in window with no SQL-side threshold filtering for the >40% spec rule — admins see noise mixed with alerts. Reviewer #1 to evaluate if the threshold belongs at SQL layer or at render time.
- 6 separate psycopg2 connections per page load is a service-module concern (each query function opens its own `db_cursor()`); a `query_all()` helper would belong in reviewer #1's scope.
- Spec/code drift around `ai.updated_at` vs `ai_generated_at` (called out in module docstring + test docstring) is reviewer #1's call.
