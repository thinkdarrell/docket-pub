# Make the `search_submit` analytics event fire by emitting it after the deferred tracker scripts have run

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

Before this plan, the search results page emitted `docketTrack('search_submit', ...)` from an inline script at the bottom of `search.html`. `base.html` loads the Umami script and `track.js` with `defer`, and an inline script in the body runs during parsing, before any deferred script has executed. The emit's guard (`if (typeof docketTrack !== 'function') return;`) therefore always returned, and `search_submit` had zero rows in `v_event_counts_daily` from the day analytics shipped (2026-05-17) to 2026-11-11, across months of real traffic to `/search`. The `outbound_source_click` event was unaffected because it is a click listener that runs long after load.

After this plan, the emit is a function registered on `DOMContentLoaded` (or called at once if the document has already finished loading). Deferred scripts finish before `DOMContentLoaded` fires, so `docketTrack` and `window.umami` both exist when it runs. The gate that fires only on the first page of results (`page == 1 and tpage == 1`) is unchanged. The query cheat sheet's Alabama filter also changes from `region = 'AL'` to `region = 'US-AL'`, the ISO 3166-2 code Umami v3 actually stores.

## Progress

- [x] (2026-11-12 03:20Z) M1: `tests/web/test_search_submit_event.py` (3 tests) written first and seen failing on the old template (`1 failed, 2 passed`); `src/docket/web/templates/search.html` wraps the emit in `emit()` registered on `DOMContentLoaded`; `docs/analytics-queries.md` Alabama filter uses `US-AL` with a sentence saying why; the new tests print `3 passed in 1.20s` against a disposable database.
- [x] (2026-11-12 03:30Z) M1 closing: `./tools/verify` printed `verify: unit+web+services ... ok (82s)`, `verify: integration ... ok (86s)`, `verify: judge-fixtures ... ok (3s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (9s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 180s.`; pull request opened from `feat/search-submit-timing`.

## Surprises & Discoveries

- Observation (investigation, 2026-11-11): the event had never fired, not merely rarely.
  Evidence: `SELECT event_name, SUM(event_count) FROM v_event_counts_daily GROUP BY 1` on the Umami reader returned `outbound_source_click` rows and no `search_submit` row at all, while `v_pageviews_daily` showed steady `/search` pageviews over the same period.
- Observation (investigation, 2026-11-12): the cause is script timing, not the template gate or `sanitizeProps`.
  Evidence: `base.html` line 29 is `<script src=".../track.js" defer>`; `search.html` lines 193 to 211 ran the emit as an immediately invoked function at parse time, guarded by `typeof docketTrack !== 'function'`. Deferred scripts execute after parsing completes, so the guard was always true.
- Observation (investigation, 2026-11-12): Umami v3 stores `region` as `US-AL`.
  Evidence: `SELECT region, SUM(sessions) FROM v_geo_daily WHERE country='US' AND day >= current_date - 30 GROUP BY 1 ORDER BY 2 DESC LIMIT 6` printed `US-CA|3841`, `US-AL|165`, `|151`, `US-IA|138`, `US-VA|60`, `US-GA|46`.

## Decision Log

- Decision: register the emit on `DOMContentLoaded` inside the template rather than move `track.js` out of `defer` or make the emit poll for `docketTrack`.
  Rationale: `defer` is right for both tracker scripts (they must not block rendering), and `DOMContentLoaded` is the documented point at which all deferred scripts have run. The `readyState` branch keeps the emit correct if the template is ever rendered into an already-loaded document.
  Date/Author: 2026-11-12, Claude.
- Decision: the test asserts the shape of the rendered script (`addEventListener('DOMContentLoaded', emit)` and the `readyState` branch) rather than executing it.
  Rationale: the repository has no JavaScript test runner and adding one for a single assertion is not worth it. The shape assertion fails on the exact regression (a top-level call) and on silent removal of the event.
  Date/Author: 2026-11-12, Claude.

## Outcomes & Retrospective

- The event will show its first rows in `v_event_counts_daily` on the day the deploy lands; the first real check is `SELECT day, event_count FROM v_event_counts_daily WHERE event_name = 'search_submit' ORDER BY day DESC LIMIT 7` a day after deploy.
- Verify passed on the first run after the fix (`all 6 checks passed in 180s`); no other test touched the search page's script.
