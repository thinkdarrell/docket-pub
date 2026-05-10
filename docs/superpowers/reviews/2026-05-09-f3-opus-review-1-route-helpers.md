# F3 Review #1 — Route + Helpers (Opus)

**Commit:** 281d68d
**Branch:** feat/impact-first-phase-2-track-3
**Reviewer angle:** Route + service-layer helpers (parallel review, non-overlapping with template/UX angle)

## Summary

Solid implementation. Window math, parameterization, helper composition, and test rigor are all good. The single REQUIRED finding is documentation only: the route docstring still describes the F3 partial as "F2 ships an empty stub" (i.e. future-tense F3) — a future maintainer reading this in six months will be confused. The MV-refresh swallow flagged by the implementer is acceptable as a local-dev guard but the cron-refresh task is genuinely missing and should ship before backfill — I'm landing it as SUGGESTED rather than REQUIRED because nothing in F3 itself depends on it (production renders an empty-state branch when the MV is unrefreshed, which is correct behaviour for the brand-new pre-backfill state).

## REQUIRED (must-fix before merge)

- **Stale F3-future-tense docstring on the route** at `src/docket/web/public.py:186` — `category_landing` docstring says `volume timeline (F3 lands the real partial; F2 ships an empty stub)`. F3 has now landed; the docstring describes a state that no longer exists. Replace with `volume timeline (5-year rolling window, decision #95)` or similar. This is a "REQUIRED" only because it's actively misleading documentation in a hot path the next implementer will read; a one-line edit. (The same stale phrasing appears on line 11 of `category_landing.html` — that's reviewer #2's territory but flagged below as out-of-scope so the fixes can be batched.)

## SUGGESTED (should-fix, can be deferred)

- **No cron task refreshes `mv_badge_volume_monthly`** in `src/docket/worker/scheduler.py` / `tasks.py`. Migration 013 created the MV `WITH NO DATA` and the only `REFRESH MATERIALIZED VIEW` call site in the entire codebase is the *test* fixture (`tests/integration/test_badge_volume_series.py:64-68`). The implementer's claim in the spec patch ("Production refreshes this MV nightly via the cron worker") is aspirational — there is no code that does this today. The existing `try/except ObjectNotInPrerequisiteState` in `query.py:1278-1294` makes this safe (page renders empty-state instead of 500ing), so it's not a release-blocker, but: (1) once Phase 3 backfill runs, the MV will silently stay empty until somebody manually `REFRESH`-es it; (2) the spec patch claim should match reality. Recommend adding a sixth task to `worker/tasks.py` (e.g. `refresh_mv_badge_volume_monthly`) and registering it in `scheduler.py` after `vote_matching` (10:00 AM Chicago, after upstream ingest+AI+matching settles). Also update the runbook (`docs/runbooks/cron-worker.md`) and the comment in `query.py:1271` from "Production refreshes this MV nightly via the cron worker" to "Production should refresh..." until the task ships.

- **Empty-month bars are emitted in Python but never rendered** — `query.py:1311-1351` builds dicts with zero `height_substantive`/`height_consent` for months with no data, but the partial template (`partials/volume_timeline.html:64,71,79`) gates every `<rect>` on `point.height_substantive > 0` or `point.height_consent > 0`. The docstring at `query.py:1226-1230` justifies the dense series by saying "every month is a column so adjacent bars never visually collide" — but since zero-month columns produce zero `<rect>` elements, the "consistent column spacing" argument is moot at the SVG level. The dense list does still serve `x` monotonicity and the test `test_badge_volume_series_x_monotonic_and_bounded`, but the docstring claim about visual collision is wrong as written. Either: (a) update the docstring to admit that empty months are silent gaps in the rendered SVG and the dense list is for `x`-positioning consistency only, or (b) emit a zero-height "phantom" rect with `data-period` so hover shows "0 items" tooltips on empty months (matches the implementer's stated intent). Option (a) is the smaller fix; option (b) is what the docstring reads like.

- **Future-month bars in the current calendar year are zero-height by construction** — when run on 2026-05-09, the window is 2022-01-01 to 2026-12-31, which means June-Dec 2026 have no data and surface as gaps. Per Decision #95 wording this is intentional ("inclusive of `current_year`"), and the spec patch is explicit about the rolling-on-Jan-1 semantics, but it's worth noting that the right edge of the SVG visually communicates "trailing off" until the year completes. If reviewer #2 reports this looks like a data gap in their UX pass, the easiest fix is `end_date = min(date(current_year, 12, 31), date.today())` — but Decision #95 explicitly chose the calendar-year semantics and this should be a deliberate spec change, not a quiet patch.

## NICE-TO-HAVE (optional polish)

- `_normalize_party` at `query.py:1355-1367` silently maps `"Green"`, `"Libertarian"`, etc., to `"I"`. Acceptable per the spec, but the docstring says "non-partisan municipal elections, third parties, etc." — Green Party isn't really an "Independent." Consider extending the class hooks to a 4th color or document that `I` is "everything that isn't D or R" in citizen-facing terms. Low priority — Alabama mayoral races are uniformly D/R/I in practice.

- `mayoral_term_overlay` query at `query.py:1399-1411` does `cur.fetchall()` inside the `with` block then iterates the materialized list outside it. Correct (because `fetchall` materializes), but inconsistent with the rest of `query.py` which keeps row iteration inside the `with` (e.g. `list_municipalities` at line 30-40, `get_resolved_badge` at line 1017-1036). Cosmetic only; no functional bug. The `badge_volume_series` helper at line 1278-1294 also drops `db_cursor` before iterating `rows_by_month` — same pattern applied consistently to the new helpers, so this is more of a style-divergence note than a bug.

- Layout constants at `query.py:1177-1183` are well-named and discoverable (the test imports them, which is a good sign — `test_badge_volume_series.py:42-49`). Minor suggestion: the comment block at lines 1168-1175 says `<text y="14">` for the term-overlay band and `<text y="195">` for year-tick labels — those are *template* literals (in `volume_timeline.html`), not Python constants. If the template's hard-coded `y="14"` ever drifts from the Python `VOLUME_TIMELINE_TOP_PAD`, nothing catches it. Consider either passing the constants through to the template or adding a comment in the partial pointing at the Python source. Out-of-scope-ish for me but worth flagging from the contract-cleanliness angle.

- The `import psycopg2` at `query.py:1275` is local to `badge_volume_series`. The rest of the module imports at the top. This was likely deliberate to keep the dependency localized to the swallow site, but it's also the only place in `query.py` that needs `psycopg2.errors.*`, so a top-of-file import would also be fine. Style-only.

## Open-question responses

### 1. Zero-bucket policy

**Verdict: the dense-series approach is correct, but the rationale in the docstring is overstated.** The Python helper rightly produces 60 entries (one per month) so consumers can iterate by month-index without per-row date math. However, the partial's `{% if point.height_substantive > 0 %}` / `{% if point.height_consent > 0 %}` gates mean zero-data months produce zero `<rect>` elements — so "consistent column spacing" claim in the docstring isn't quite right. The visual *does* read as "no data this month" rather than "data unavailable" because there's no rect at all (not a stubby sliver). This is the right model for a transparency platform — citizens shouldn't see a flat baseline that they might mistake for actual zero-volume data when in reality the badge wasn't applied. But the docstring should match the rendered behaviour. (Captured as a SUGGESTED finding above.)

### 2. Leap-day distortion

**Quantification, by year:**

| Window end year | total_days | px_per_day | leap days | distortion vs theoretical 365.25*5 |
| --- | --- | --- | --- | --- |
| 2025, 2026, 2027 | 1825 | 0.4384 | 1 | -0.07% |
| 2028 | 1826 | 0.4381 | 2 | -0.01% |
| 2029, 2030 | 1825 | 0.4384 | 1 | -0.07% |

The mayoral-term band positions are computed from `(clipped_start - start_date).days * px_per_day`. A 1-day error in band-end position translates to ~0.44 px on an 800px viewBox (0.05% of width). Over the 5-year window the leap-day variation cannot accumulate beyond 2 days (= ~0.88px). **Verdict: bounded, well below SVG anti-aliasing threshold, acceptable.**

Note that the *bar* positions are immune — they're computed from `i * col_width` (60 buckets evenly spaced over 800px), not from days. So the only place leap-day distortion appears is the mayoral band overlay, where the visual is already an approximate background band, not a precise data carrier. Accept as-is.

### 3. MV refresh / swallow

**Swallow itself: acceptable.** The `try/except psycopg2.errors.ObjectNotInPrerequisiteState` is the right local-dev guard — it's a known `WITH NO DATA` MV state that would otherwise 500 the page on any new install. The empty-state branch in the partial gracefully handles `[]`, so citizens see a useful "indexing in progress" message instead of a broken page.

**But the deferred refresh is a real gap.** No cron task refreshes the MV. Today this doesn't matter much — Phase 2 hasn't backfilled enough badges to fill it anyway, and the pre-backfill state is "no data" by design. After Phase 3 backfill, the MV will continue to look empty until someone manually `REFRESH`-es it. This *will* bite somebody if not addressed before backfill flip.

**Recommendation:** before Phase 3 deploy, add a `refresh_mv_badge_volume_monthly` task to `src/docket/worker/tasks.py` and register it in `scheduler.py` (suggest 10:00 AM America/Chicago, after `vote_matching` at 09:00). The task body is one line (`REFRESH MATERIALIZED VIEW CONCURRENTLY mv_badge_volume_monthly` if there's data, plain `REFRESH` first time). Add a Healthchecks UUID env var per the existing pattern. Update `docs/runbooks/cron-worker.md`. Out-of-scope for *F3* literally, but on the critical path before public-flag flip — captured as SUGGESTED.

The spec patch's claim "Production refreshes this MV nightly via the cron worker" should be softened to "Production should refresh this MV nightly..." until the task actually ships, otherwise a future debugger will assume the refresh exists and waste cycles trying to find it. The same wording lives at `query.py:1271`.

## Out-of-scope observations

(Flagged for reviewer #2 / not blocking my approval.)

- **Stale "F3 stub" comment in `category_landing.html:11`** — same content issue as the route docstring REQUIRED above, but on the template side. Worth fixing in the same pass.

- **Partial template has tooltip-rendering branch logic** (`volume_timeline.html:64-91`) that emits a transparent "hit area" rect when only the substantive segment exists, so hover works. The contract that `<title>` lives on the consent rect when both segments exist is not documented in the Python-side helper; reviewer #2 should evaluate whether this is the right hover-target model and whether the screen-reader experience is consistent (a sighted user gets a tooltip on consent-only and substantive-only months equally, but an SR user iterating tabbable elements may not — depends on whether SVG `<rect>` is in the tab order, which it isn't by default).

- **`test_route_renders_empty_state_when_no_data` (line 498)** depends on running before any other test seeds data in the `bag` fixture's lifetime. Fixture is function-scoped (cleanup happens after each), so this is fine — but worth noting that order independence is a quiet contract here. If a future test seeds data and forgets to `bag.cleanup()`, this test could flake.

- **`category_landing.html` — F3-stub comment in the file's top docstring (line 11)** — `Sections in order: header → KPI strip → volume timeline (F3 stub) → ...`. Now reads incorrectly. Pair with the route fix.
