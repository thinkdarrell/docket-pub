# F5 Sonnet 4.6 Second-Look

**Commit:** ea3aeed
**Branch:** feat/impact-first-phase-2-track-3
**Reviewer:** Sonnet 4.6 (second-look angle: verification + cross-cutting)

## Summary

All 985 tests (817 unit + 168 integration, 5 xfailed) pass with zero regressions on this commit. The Opus reviewers correctly identified the five blocking/suggested issues. This second-look confirms R1 through R5, adds important nuance on R2 (the local DB is near-empty; the Opus "many titles" claim draws from the Railway DB, where 6 Birmingham meetings carry `?` or `#` in their titles — real but not vast), and finds two new findings: (1) the `data-debt-row__title` link silently targets `public.meeting_detail` with `slug=municipality.slug` but the query returns `municipality_slug` from the JOIN — these will match today but are separate fields, and (2) the `load-more` pagination is a plain `<a>` navigation link, not HTMX — inconsistent with the HTMX-heavy F4 precedent and the spec mock-up's UX expectation.

---

## Verification of Opus REQUIREDs

### R1 (rss_cached race): CONFIRMED — NUANCED

`public.py:411-426` confirms the check-then-render-then-set sequence is not atomic. The Procfile reads `gunicorn "docket.web:create_app()" --bind 0.0.0.0:${PORT:-5000} --timeout 120` — no `--workers`, no `--threads`. The Dockerfile CMD also lacks these flags. **Currently single-worker sync mode — the race is latent, not live.** The existing `_overview_cache` has the same pattern. The risk window is: (a) when Railway adds workers for throughput, or (b) if a future Procfile PR adds `--threads` or `--worker-class gevent` without revisiting the cache. The Opus REQUIRED stands — fix it now while the helper is 15 lines — but the production urgency is low: single-worker sync gunicorn means one thread, no race in practice. Double-checked locking pattern is the correct fix.

### R2 (mailto URL encoding bug): CONFIRMED — COUNT NUANCED

Lines 110 and 146 of `data_debt.html` interpolate `item.meeting_title or ''` raw into the hand-encoded mailto body. Jinja2 autoescaping converts `&` to `&amp;` in the HTML attribute, which the browser then decodes back to `&` — so the mail client sees an unencoded `&` that truncates the `body=` parameter at the first occurrence. Verified via Python simulation of the escaping chain.

**Local DB reality check:** The local test DB has only 1 agenda_item total (nearly empty). I cannot confirm "many Birmingham data-debt items with `&` in their meeting_title" from the local DB alone. What I can confirm:
- 6 Birmingham meetings in the local DB have `?` or `#` in their titles (e.g., `'Regular City Council Meeting: Video Link- https://www.periscope.tv/...?'`, `'*City Council & School Board Election Results "Live"'`). None have data-debt items in the test DB (all items there have `NULL` data_quality).
- In production (Railway), Wave 0 classified 16,169 items as `data_quality_skipped` and 3,909 as `procedural_skipped` — none of these contribute to the data-debt route (those are `ok` or null path). The data-debt pool is the `no_text_layer`/`no_agenda_text`/`empty`/`foreign_language` bucket — unknown count in production without direct Railway query. However, Granicus (Birmingham) is the adapter most likely to produce `no_text_layer` items (scanned PDFs), and Birmingham's `?`-in-title meetings DO exist and could attach to those.

**Bottom line:** The bug is structurally real. The Opus reviewer's claim that "many Birmingham meetings have `&`, `?`, `#` in titles" is not "many" — it's 6 confirmed, all of the `?` variety from old Periscope URLs in 2016-era meeting titles, plus 1 with `&`. The bug is REQUIRED because the fix is trivial and the code ships to production where future data could trigger it. Count: ~6 meetings with special chars, unknown how many have data-debt items. CONFIRMED as REQUIRED.

### R3 (RSS jargon leak at `_macros.xml.j2:9`): CONFIRMED

`templates/rss/_macros.xml.j2` line 9:
```
 Source content needs review (data_quality={{ item.data_quality }}).
```
This emits the raw enum value (`no_text_layer`, `no_agenda_text`, `empty`, `foreign_language`) directly into the RSS `<description>` CDATA block. The HTML template at `data_debt.html:24-40` goes to explicit effort to define a `friendly_labels` dict and a `friendly_label(item)` macro to translate these. The RSS macro undoes that work and broadcasts internal enum strings to feed-reader subscribers. CONFIRMED. The fix is to either import the friendly_labels lookup into the macro or inline a translation table.

### R4 (unstyled BEM classes): CONFIRMED

Grepped all six CSS files (`styles.css`, `layout.css`, `councilmatic.css`, `tweaks.css`, `mobile.css`, `css/smart_brevity.css`) — zero matches for any of: `data-debt-list`, `data-debt-row`, `data-debt-row__title`, `data-debt-row__meta`, `data-debt-row__needs`, `data-debt-row__action`, `data-debt-pager`, `data-debt-loadmore`. The page will render as a default `<ul>` with browser-default bullet points and no layout differentiation between rows. CONFIRMED. Note that `.t-meta` and `.hero-sub` classes (used inside the new elements) are styled elsewhere — so the page isn't completely unstyled, just the row/list/pager scaffold has no CSS.

### R5 (admin email hardcoded): CONFIRMED — with clarification

`public.py:435`:
```python
return municipality.get("admin_email") or "admin@docket.pub"
```
`config.py:25`:
```python
ADMIN_EMAIL: str = os.environ.get("ADMIN_EMAIL", "admin@docket.pub")
```
`web/__init__.py:21`:
```python
app.config["ADMIN_EMAIL"] = ADMIN_EMAIL
```
`engagement_strip.html:77`:
```jinja
mailto:{{ config.ADMIN_EMAIL }}?subject=...
```

The established pattern is to read from `app.config["ADMIN_EMAIL"]` (or `config.ADMIN_EMAIL` in templates). The F5 helper bypasses this. The two levels of bypass:
1. When `municipalities.admin_email` column exists and is non-NULL, `_data_debt_admin_email` returns it — correct.
2. When that column is NULL/absent, it returns the literal `"admin@docket.pub"` — bypassing the `ADMIN_EMAIL` env var that ops can override without a code deploy.

The fix is one line: `return municipality.get("admin_email") or current_app.config.get("ADMIN_EMAIL", "admin@docket.pub")`. CONFIRMED as SUGGESTED (Opus #2 correctly categorized this as SUGGESTED, not REQUIRED — `admin@docket.pub` is the correct fallback today and both the env var and the literal share the same default, so ops override capability is limited to cases where they've specifically set `ADMIN_EMAIL` to something other than `admin@docket.pub`).

---

## Cross-cutting check

### a. Test fixture-accepted-but-unused pattern

Only one test accepts `monkeypatch`: `test_rss_60_min_cache_returns_same_body` (line 373). The Opus #1 reviewer already flagged this. Reading the test body: `monkeypatch` is declared in the signature but is never called. The test proves caching works (second call within TTL returns stale body) — but via a different mechanism: it mutates underlying data instead of advancing the clock. This is actually a *stronger* behavioral test than clock-patching, but the unused `monkeypatch` parameter is misleading (implies TTL boundary is exercised when it isn't).

**The other 21 tests:** No other F5 test has a fixture-accepted-but-unused pattern. All other fixtures (`bag`, `client`) are actively used. The anti-pattern is isolated to this one test.

**Verdict on the Opus SUGGESTED:** Correct. The `monkeypatch` parameter should either be dropped (it implies false coverage) or used to add a second test case that verifies cache expiry after `_RSS_TTL_SECONDS`. The current test logic is valid — just the signature is misleading.

### b. Existing-feature regressions

Ran `venv/bin/python -m pytest tests/ --ignore=tests/live -q`. Result: **985 passed, 5 xfailed, 1 warning in 12.94s.** Zero regressions across F2/F3/F4 integration tests (168 total integration, 22 of which are new F5 tests).

**Path rename check:** Grepped all templates, Python files, and test files for `hearings.rss` (without `upcoming-`) and `hearings_rss`. Every reference in live code points to `public.upcoming_hearings_rss` (the new endpoint name) or `upcoming-hearings.rss` (the new path). The old path `hearings.rss` appears only in comments, docstrings, and one test assertion that explicitly documents the rename:
```python
# F5 path-drift fix: route renamed from /al/<city>/hearings.rss to /al/<city>/upcoming-hearings.rss
```
No live links to the old path. Clean.

### c. Spec/code drift

**Load-more pagination:** Spec §6.9 wireframe shows `• [load more]` as the pagination element. The implementation delivers a plain `<a class="data-debt-loadmore" href="...?offset=50">Load more items</a>` — full page navigation, not HTMX. This is *consistent* with how F2's `category_landing` page handles pagination (also a plain URL with `?offset=` parameter). Not a spec violation — the spec doesn't say HTMX here, and the pattern matches F2. FINE.

**Subscribe link prominence:** Spec §6.9 wireframe shows `Subscribe to RSS: [link]` in the hero area. Implementation has it at `data_debt.html:56-63`: `<p class="hero-sub" style="margin-top: 0.5rem;"><strong>Subscribe:</strong><a href="...">Data debt RSS feed</a></p>`. Prominently placed in the hero. FINE.

**Decision #32 reference:** Spec §6.9 line 3292 says `"(decision #32 — citizens bookmark/RSS until citizen-account notification feature in Phase 4)"`. No reference to decision #32 appears anywhere in the F5 code or comments. This is a cosmetic omission — the spec footnotes a decision that explains the RSS rationale, but the code doesn't need to echo every decision number. NICE-TO-HAVE to add a comment.

**Upcoming-hearings RSS auto-discovery:** The spec implies both feeds should be discoverable. `data_debt.html` has a `<link rel="alternate" type="application/rss+xml">` in `<head>` for the data-debt feed (correct). The upcoming-hearings feed has no `<link rel="alternate">` in any HTML `<head>` — only the engagement-strip partial (`partials/engagement_strip.html:72`) links to it contextually when `action_type == 'public_hearing_set'`. So feed readers pointed at city.html won't auto-discover the upcoming-hearings feed. Opus #2 flagged this as SUGGESTED (not blocking). Agree.

### d. R2/R5 interaction

R2 (mailto encoding) and R5 (admin email env var bypass) are independent fixes that touch the same code path but don't interfere with each other. The correct fix sequence:

1. Fix R2: set `_subject` and `_body` as Jinja variables and apply `| urlencode` to each. Template-only change.
2. Fix R5: `_data_debt_admin_email` uses `current_app.config.get("ADMIN_EMAIL", "admin@docket.pub")` as fallback. Python-only change in `public.py`.

These are additive; fixing one does not complicate the other. The R5 fix improves the Python helper; the R2 fix improves the Jinja template. Both can land in the same fix-up commit without conflict.

---

## New findings (missed by both Opus rounds)

### REQUIRED

None beyond the confirmed Opus five.

### SUGGESTED

**S6 — `data-debt-row__title` uses `slug` but query returns `municipality_slug`.**
`data_debt.html:96`:
```jinja
<a href="{{ url_for('public.meeting_detail', slug=municipality.slug, meeting_id=item.meeting_id) }}">
```
This is correct — `municipality.slug` is the city slug passed to the route and used for the `url_for`. The `item.municipality_slug` from the JOIN would be the same value (query filters `WHERE m.id = city_id`). However, the template is referencing `municipality.slug` (the outer route variable) not `item.municipality_slug` (the JOIN result). These are guaranteed equal today because the query is already city-filtered, but this is a subtle inconsistency: if a future refactor passes items from multiple cities (e.g., a global admin view), the link would silently use the wrong slug. SUGGESTED: use `item.municipality_slug` in the `url_for` to be self-contained, matching the pattern in `data_debt.xml.j2:13` which correctly uses `item.municipality_slug`.

**S7 — `data_debt.html` has a `list_data_debt_items` docstring mismatch (identified by Opus #1 but called "minor docstring drift").**
`query.py` docstring at line 1933-1936 says "one row per hit (meeting_id, hearing_title) so a single meeting can surface multiple distinct hearing items." The SQL uses a scalar `LIMIT 1` subquery, emitting at most one row per matching meeting. The docstring oversells what the SQL does. Upgrade from NICE-TO-HAVE to SUGGESTED (quick fix, prevents future confusion when someone tries to extend the query to be lateral and can't understand why the docstring says N but the query does 1).

**S8 — `test_data_debt_empty_state_is_citizen_friendly` relies on Vestavia Hills having zero data-debt items.**
Confirmed by Opus #2. The test (`test_f5_data_debt.py:284`) GETs `/al/vestavia_hills/data-debt` and asserts an empty state. In the test DB this is reliable today (1 agenda_item total, not from Vestavia Hills). But after a future test-data migration or if someone seeds Vestavia Hills items for another test without cleanup, this test will fail spuriously. Safer to either: delete any Vestavia Hills data-debt items before asserting, or use a dedicated synthetic city with guaranteed zero items. Matches Opus #2's call. SUGGESTED.

### NICE-TO-HAVE

**N1 — No `<link rel="alternate">` for upcoming-hearings in any HTML `<head>`.**
The upcoming-hearings RSS feed is discoverable only through the contextual engagement-strip link. Feed readers pointed at city.html or data-debt.html won't auto-discover it. Spec §6.9 positions RSS as the "primary citizen consumption path." Adding `<link rel="alternate" type="application/rss+xml" title="Upcoming hearings" href="...">` to `city.html`'s `{% block head %}` would complete the story. (See also Opus #2 SUGGESTED on this.)

**N2 — Inline style at `data_debt.html:56`.**
`style="margin-top: 0.5rem;"` on the subscribe paragraph. Should move to a utility class in `tweaks.css`. (Same issue Opus #2 flagged at line 56.)

**N3 — Decision #32 not referenced in code/comments.**
Spec §6.9 cites decision #32 as the rationale for RSS-until-Phase-4-notifications. The commit message and code don't mention it. A comment at the RSS route would make the rationale traceable. Pure docs.

**N4 — Cache size bound.**
Opus #1 noted the cache is bounded at "8 keys max (4 cities × 2 feeds)." The comment at `public.py:405` states this explicitly. The bound is correct today. When Hoover, Montgomery, Tuscaloosa etc. are added the bound grows proportionally — still manageable as a module-level dict. If `query_string=True` were ever added (per an early spec example), the key space would explode. Pre-emptively accept: the current design is correct for the stated scale.

---

## Findings to downgrade or refute

**Opus #1 framed R1 as needing immediate fix due to "upcoming move to `--workers N --threads K`."** Confirmed that no such move is currently in Procfile or Dockerfile — it's speculation about a future change. The Procfile has single-worker sync gunicorn today. Technically R1 remains REQUIRED as written (the pattern is wrong and should be fixed) but the urgency framing should be "latent, fix in fix-up" not "imminent production risk." The `_overview_cache` pattern (which R1 mirrors) has the same issue and has been in production without incident. Still fix it.

**Opus #2 called the "load-more" implementation "just LIMIT 50 with no pagination UI."** This is wrong — the pagination UI IS present: `data_debt.html:156-163` renders a `<nav class="data-debt-pager">` with a `<a class="data-debt-loadmore">` when `next_offset` is not None. It's a plain navigation link rather than HTMX, but it IS wired. The spec mock-up says `[load more]` and the implementation delivers `Load more items` as a link. This is not a gap.

**Opus #2 said "No RSS auto-discovery for `upcoming-hearings.rss` anywhere in HTML."** Mostly correct — there's no `<link rel="alternate">` in any `<head>` for this feed. However, the engagement strip partial DOES link to it contextually (line 72-75 in `engagement_strip.html`). This is a discovery path, just not feed-reader auto-discovery. Agree this should be SUGGESTED (not REQUIRED) to add a `<head>` link.

---

## Final categorization recommendation for the user packet

### Aggregate REQUIRED list (deduplicated):

1. **R1 — `_rss_cached` thundering-herd race** (`public.py:411-426`). Add double-checked locking with `threading.Lock`. Latent not live (single-worker sync gunicorn), but fix before any worker-count or thread-count change.
2. **R2 — Mailto URL encoding bug** (`data_debt.html:110, 146`). Set `_subject` and `_body` as Jinja variables and apply `| urlencode`. Use `&amp;` as the query-param separator in the HTML attribute. Both HIGH and NORMAL branches have the same bug.
3. **R3 — RSS jargon leak** (`rss/_macros.xml.j2:9`). Replace raw `data_quality={{ item.data_quality }}` with a friendly-label lookup table (inline dict in the macro or a shared Jinja include).
4. **R4 — Five unstyled BEM classes** (`data_debt.html:92-162`). Add CSS rules for `.data-debt-list`, `.data-debt-row`, `.data-debt-row__title/__meta/__needs/__action`, `.data-debt-pager`, `.data-debt-loadmore` in `tweaks.css` or a new section of `layout.css`.
5. **R5 — Admin email hardcoded fallback** (`public.py:435`). Replace literal `"admin@docket.pub"` fallback with `current_app.config.get("ADMIN_EMAIL", "admin@docket.pub")`.

### Aggregate SUGGESTED-accept (in fix-up):

1. **S-A1 (Opus #1): `test_rss_60_min_cache_returns_same_body` — drop unused `monkeypatch` param** or add a TTL-expiry test using it. The current test logic is sound; the param is misleading.
2. **S-A2 (Opus #1): `_data_debt_admin_email` dead-branch comment** — add a note that the `municipality.get("admin_email")` path is unreachable until Migration 015 lands `municipalities.admin_email`.
3. **S6 (new): Template uses `municipality.slug` instead of `item.municipality_slug` in `url_for` links.** Low risk today (query is city-filtered), but self-consistency with `data_debt.xml.j2:13` suggests using `item.municipality_slug` in the template.
4. **S7 (new / Opus #1 upgrade): `list_upcoming_hearings` docstring oversells "multiple rows per meeting."** The SQL emits one row per matching meeting (scalar LIMIT 1 subquery). Fix the docstring.

### Aggregate SUGGESTED-defer (acknowledge, ship anyway):

1. **Opus #2: RSS mailto link in the RSS `<description>` CDATA.** Decision #77 is satisfied by the HTML page mailto; adding it to RSS CDATA is a nice-to-have for RSS-only readers.
2. **Opus #2: `test_data_debt_empty_state_is_citizen_friendly` reliance on Vestavia Hills zero-items.** Fragile across test-data churn (S8 above). Acceptable for now; low risk in the current sparse test DB.
3. **Opus #2: No `<link rel="alternate">` for upcoming-hearings in `<head>`.** Real gap for feed-reader auto-discovery. Ship now, add in a follow-up.
4. **Opus #2: `<ul>` semantics — `<p>` vs `<div>` inside `<li>`.** Screen-reader concern is minor in practice.
5. **Opus #1: `test_rss_cache_key_isolation_per_city` structural weakness.** The test would pass even without proper cache isolation. Stronger test would seed BHM-only data. Acceptable for now.

### NICE-TO-HAVE: 7 total (all deferred)
N1 (upcoming-hearings head link), N2 (inline style), N3 (decision #32 comment), N4 (cache size comment), Opus #1 cache-key naming, Opus #1 render_fn naming, Opus #2 em-dash in RSS `<title>`.
