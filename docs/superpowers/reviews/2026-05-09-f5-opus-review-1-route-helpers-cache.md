# F5 Review #1 — Route + Helpers + Cache (Opus)

**Commit:** ea3aeed
**Branch:** feat/impact-first-phase-2-track-3
**Reviewer angle:** Route + service-layer helpers + cache mechanics (parallel review, non-overlapping with template/RSS-XML/UX)

## Summary

The two new helpers are clean, fully parameterized, and Pythonic; the route surface mirrors the F2 sentinel-pagination pattern faithfully; the dict cache mirrors the established `_overview_cache` idiom. Tests pass (22/22 locally — `test_f5_data_debt.py` and `test_engagement_strip.py`). The `xfail` interpretation is verified — the surviving `xfail-strict` test targets the admin queue at `/admin/data-debt/`, not the public page F5 ships.

The one **REQUIRED** finding is in the cache helper: `_rss_cached` is a thundering-herd race inside a single gunicorn worker — under high concurrent first-request load (Slack-link unfurl, a single feed reader pinging twice on the same connection) the same RSS body can be rendered N times before the first writer lands. Trivially fixed with `threading.Lock` (or a `setdefault`-style atomic check). Everything else is suggested-or-nice-to-have polish. The 60-min TTL test does not actually exercise TTL expiry — it accepts a `monkeypatch` parameter but never uses it.

## REQUIRED

- **`_rss_cached` has a benign-but-real thundering-herd race** at `src/docket/web/public.py:411-426`. The dict access is GIL-atomic but the *check-then-render-then-set* sequence is not. Two concurrent requests that both observe a cache miss will both call `render_fn()` — for RSS that means two parallel DB round-trips to `list_data_debt_items` / `list_upcoming_hearings`, two render passes, two writebacks to the dict. Not a correctness bug (last writer wins, both bodies are equivalent modulo `lastBuildDate`), but on cold deploy the concurrent feed-reader poll could multiply the work pointlessly. The existing `_overview_cache` has the same race, so this isn't strictly worse than the established pattern — but it's worth noting because RSS is the surface most likely to receive concurrent polls (feed readers, Slack/Discord link-unfurl, search engine bots all hit the same URL). One-line fix:
    ```python
    _rss_cache_lock = threading.Lock()

    def _rss_cached(cache_key: str, render_fn) -> str:
        import time, threading
        now = time.time()
        cached = _rss_cache.get(cache_key)
        if cached and (now - cached[0]) < _RSS_TTL_SECONDS:
            return cached[1]
        with _rss_cache_lock:
            # Re-check inside the lock (double-checked locking).
            cached = _rss_cache.get(cache_key)
            if cached and (now - cached[0]) < _RSS_TTL_SECONDS:
                return cached[1]
            rendered = render_fn()
            _rss_cache[cache_key] = (now, rendered)
            return rendered
    ```
    Even with gunicorn's default sync worker (single thread per worker), the upcoming move to `--workers N --threads K` (which the project will eventually want for memory headroom on Railway) makes this hot. Verdict: lock it now while the helper is small; don't pay the debt later.

## SUGGESTED

- **`test_rss_60_min_cache_returns_same_body` does not actually exercise TTL expiry** at `tests/integration/test_f5_data_debt.py:373-392`. The signature accepts `monkeypatch` but the body never patches `time.time` or `_RSS_TTL_SECONDS`. The test only proves "two calls within milliseconds return the cached body" — which the dict-cache idiom can't fail at. The boundary case ("a call after `_RSS_TTL_SECONDS` re-renders") is the one with regression risk if a future refactor flips a `<` to `<=` or swaps a TTL constant. Recommend either:
    1. Drop the `monkeypatch` parameter (its presence implies test coverage that doesn't exist), OR
    2. Add a `monkeypatch.setattr(public_module, "_RSS_TTL_SECONDS", 0)` test that verifies cache miss after expiry. Two-line addition.

- **`test_rss_cache_key_isolation_per_city` is structurally weak** at `tests/integration/test_f5_data_debt.py:395-401`. It asserts `body_bhm != body_mob` and that each contains the right city name — but the channel `<title>` and `<link>` differ regardless of cache implementation, so this would pass even if `_rss_cache` had a single shared key. The stronger test inserts a data-debt item into BHM only, hits both URLs, and asserts the BHM-only item title appears in `body_bhm` but not `body_mob`. ~5 added lines. Optional but increases regression value.

- **`list_upcoming_hearings` ILIKE pattern is sequential-scan territory if the dataset grows** at `src/docket/services/query.py:1948-1981`. The query is bounded today by `meeting_date >= CURRENT_DATE AND meeting_date <= CURRENT_DATE + 60 days`, which on `idx_meetings_date` (migration 001 line 61) is selective enough — at 4 cities × ~weekly meetings × 60-day window, that's <50 rows post-filter, so the ILIKE on the meeting title is cheap, and the `EXISTS` subquery on agenda_items is bounded by the per-meeting agenda count. Verdict: fine for v1. Worth a comment on the helper that the index dependency is `idx_meetings_date` (the helper's existing index callout names `idx_agenda_items_data_debt` for `list_data_debt_items` but doesn't name the meeting-date index for `list_upcoming_hearings`). Pure docs polish.

- **`_data_debt_admin_email` always returns `admin@docket.pub`** at `src/docket/web/public.py:429-435` — the `municipality.get("admin_email")` will never be truthy until Migration 015 lands the column, because `get_municipality` does `SELECT *` and `admin_email` simply isn't a column. The fallback chain is correct in concept but the code path that picks up a real admin_email is currently unreachable. Recommend either:
    1. Comment the helper to note "this is currently `admin@docket.pub` for every city — Migration 015 will activate the per-city path", OR
    2. Hard-code `"admin@docket.pub"` and remove the dead-branch lookup, then re-add the lookup when the migration ships.
    Either is fine; option 1 keeps the diff for Migration 015 minimal. Today's helper is already idiomatic so the cost is negligible.

- **`list_data_debt_items` could surface `last_error_message` truncation guidance** at `src/docket/services/query.py:1891`. The helper SELECTs `ai.last_error_message` raw — for `failed_permanent` items this could be a multi-paragraph traceback. The data-debt page is citizen-facing so the *template* probably already handles this, but exposing the raw column to the template (rather than truncating in SQL) leaves the choice to the renderer. That's defensible — but worth a docstring note that the consumer is responsible for length-bounding. Pure polish; not blocking.

## NICE-TO-HAVE

- The cache key choice `f"data-debt:{city}"` / `f"upcoming-hearings:{city}"` at `public.py:519,549` is fine but the colon delimiter is a little unusual; consider `f"rss:data-debt:{city}"` to namespace away from any future non-RSS dict caches. Bikeshed-y.

- `_rss_cached` accepts a `render_fn` callable rather than the standard `cache.get_or_set(key, callable)` shape. Pythonic enough, but if you ever swap to `flask-caching` proper the call sites all need editing. Consider `_rss_cache_get_or_set(key, render_fn)` for naming clarity. Bikeshed-y.

- The data-debt route hard-codes `page_size = 50` at `public.py:468` while F2's `category_landing` hard-codes `25`. Different surfaces, different defaults — fine. If you ever want consistency-by-default, factor a `DEFAULT_PAGE_SIZE_DATA_DEBT = 50` module constant. Pure style.

- `list_upcoming_hearings` `days_ahead` parameter defaults to 60 (`query.py:1921`); the route call site at `public.py:541` doesn't pass an override. The spec doesn't pin a window. 60 days feels right for a citizen feed — a 14-day version would miss "next month's budget hearing"; a 365-day version would dilute the feed. The default seems well-chosen. No change requested.

## Implementer-flagged question responses

1. **`list_upcoming_hearings` v1 heuristic** — defensible for v1. Sampled the local DB: `meetings` table titles ILIKE `%hearing%` overwhelmingly capture true positives ("Budget Hearing", "Special Adjourned Budget Hearing", "Public Hearing on Rezoning of..." in test seed). Searched for known FP patterns (`%rehearing%`, `%hearing aid%`) — zero hits in current data. Sampled non-hearing zoning/annexation/variance meetings — only one candidate FN ("Standing Annexation Committee", a recurring committee meeting that's not specifically a hearing). False-negative class is real but small in the meeting-title scope; the agenda-item-title arm catches additional cases. **The "Public Comment on Zoning" example in the prompt is a real FN class** — Birmingham council does occasionally surface "public comment" agenda items that ARE de-facto hearings under city procedural rules. v1 will miss these. That's acceptable for a citizen RSS feed (over-inclusive feeds are noisier than slightly-under-inclusive ones; "more accurate when the structured signal lands" is the right framing). The docstring at `query.py:1925-1942` flags this honestly.

   **`days_ahead` parameter:** correct to expose it. The docstring should make explicit that the route caller currently uses the default (60) but admins / future callers can shorten or extend. Not blocking.

   **Meeting-vs-item title fallback precedence:** correct as written. The agenda-item title is more specific (e.g., "Public hearing on rezoning of 123 Main St" beats "Regular Council Meeting" as an RSS headline), so when an agenda-item match exists, surfacing it is the right call. The COALESCE picks `MIN(ai.id)` ordering by `ai.id ASC LIMIT 1`, which gives a deterministic-but-arbitrary first hit — fine for RSS where one row per meeting is the goal; if a meeting has multiple hearings, only the first surfaces. The docstring at `query.py:1933-1936` says "one row per hit (meeting_id, hearing_title) so a single meeting can surface multiple distinct hearing items" but the actual SQL at line 1956-1968 uses a scalar subquery that returns ONE match per meeting (since the COALESCE wraps a `LIMIT 1` subquery, not a lateral join). **Minor docstring drift — the docstring oversells what the SQL does.** The actual behavior is "one row per matching meeting, with the agenda-item title preferred over the meeting title when an item matches." The implementer's intent is plausibly fine for v1; just align the docstring.

2. **`municipalities.admin_email` fallback** — land as-is with Migration 015 follow-up. Reasoning:
   - The hard-coded `admin@docket.pub` is a working fallback today (the project mailbox per CLAUDE.md / decision #77 retired the in-app queue in favor of mailto).
   - Blocking the merge would force a schema-migration sidequest into a UI-track commit, which is the wrong scope.
   - Omitting the mailto entirely would silently break decision #77 (whose entire premise is "issue reports flow via email").
   - Keep the fallback; tag a TODO for Migration 015 to add `municipalities.admin_email TEXT NULL` and seed per-city addresses. The route helper at `public.py:435` already handles a non-NULL value automatically — Migration 015 will activate the per-city path without code changes.

3. **xfail decorator interpretation: VERIFIED.** Read `tests/unit/test_source_anchor.py:868-890` directly. The xfail-strict test asserts `client.get("/admin/data-debt/?highlight=42") → 200`. Three independent confirmations:
   - The URL path begins with `/admin/`, which is registered on the `admin` blueprint (per `web/admin.py`), not `public`. F5 ships `/al/<city>/data-debt` on the public blueprint — different route entirely.
   - The xfail reason text says "admin.data_debt is currently a 501 stub" and references "the queue page" — this is the admin operator queue, not the citizen-facing data-debt landing.
   - Ran `pytest tests/unit/test_source_anchor.py -k data_debt_returns_200 -v` against this commit: still XFAIL (1 xfailed, 0 passed). If F5 had accidentally satisfied the admin assertion, strict-mode would have flipped XFAIL → FAILED. It didn't.
   The implementer is correct to leave the xfail in place. Removing it would lose the forcing function for the admin queue follow-up.

## Out-of-scope observations

The following are flagged for reviewer #2 (template + RSS XML + UX), included here only because they appeared during route-tracing:

- The `data_debt.xml.j2` template at `templates/rss/data_debt.xml.j2:9` emits `<lastBuildDate>` via `rss_now_rfc822()` — captured *inside* the cached render, so cached responses freeze the timestamp at first-render time. This is correct behavior (the body is cached as a string verbatim; mutating `lastBuildDate` would defeat the cache) but worth verifying that RSS readers don't punish stale `lastBuildDate`. (Most don't — they use HTTP `Last-Modified` / `ETag` if present, neither of which the route emits today. That's a reviewer #2 / future header concern.)

- The RSS templates use `{{ url_for('public.meeting_detail', ..., _external=True) }}` for `<link>` and `<guid>` — these depend on `SERVER_NAME` being set in the Flask config. If `SERVER_NAME` is unset, `_external=True` raises in test contexts. The test fixture `app = create_app()` should be checked by reviewer #2 for whether it correctly seeds `SERVER_NAME`; the tests pass locally so it presumably does, but worth flagging.

- The `data-debt.html` template's mailto URL at `templates/data_debt.html:110,146` URL-encodes the body params with `%20` and `%0A` — but does NOT escape the dynamic `item.id`, `item.meeting_title`, or `item.meeting_date` interpolations against URL-injection. A meeting title with a `&` or `#` would corrupt the mailto. Reviewer #2 should verify Jinja's default autoescape covers this (it does for HTML attributes, but mailto query strings are URL-encoded, not HTML-encoded — so `&` in a meeting title would be HTML-escaped to `&amp;` inside the href but interpreted as an `&` query-param separator by the mail client). Likely a real bug, but template-domain.
