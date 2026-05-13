# F5 Final Audit — Opus 4.7

**Commit:** ea3aeed
**Posture:** Final auditor pass before user gate. Three prior reviews
incorporated (Opus #1 route+helpers+cache, Opus #2 template+RSS+UX,
Sonnet 4.6 second-look). All 22 F5 integration tests pass on this
commit.

## Top-line verdict

The five REQUIREDs are real and the prior reviews are accurate in
shape. **One material scope correction**: the R2 mailto bug pool is
not 6 meetings — it's at least **111 meetings in the local DB
(birmingham 6 + homewood 105)**, dominated by Homewood's recurring
"Planning & Development Committee" meeting type. Sonnet only counted
Birmingham. **One new REQUIRED candidate added** (R6: GUID instability
in the upcoming-hearings RSS — `#hearing` fragment gives the SAME guid
to every item in a city, so feed readers de-dupe legitimate entries).
Everything else lands as the prior packet had it.

## Re-verification of the 5 REQUIREDs

- **R1 (cache race): CONFIRMED — NUANCED.** `_rss_cached`
  (`public.py:411-426`) has the check-then-render-then-set sequence
  with no lock. Procfile says `gunicorn ... --bind ... --timeout 120` —
  no `--workers`, no `--threads`, no `--worker-class`. Dockerfile CMD
  matches. **Single-worker sync today → race is latent, not live.**
  Existing `_overview_cache` has the same pattern and has shipped
  without incident. Fix it now while the helper is small; production
  urgency is low.

- **R2 (mailto encoding): CONFIRMED — POOL UPGRADED.** `data_debt.html`
  L110 + L146: `meeting_title` interpolated raw into a hand-encoded
  mailto. Sonnet's "6 Birmingham meetings" was a Birmingham-only
  count. My SQL: `SELECT muni.slug, count(*) FROM meetings mt JOIN
  municipalities muni ... WHERE mt.title ~ '[&?#]' GROUP BY muni.slug`
  returns `homewood|105, birmingham|6` — **111 meetings total in the
  local sparse DB**. Homewood ships a recurring "Planning &
  Development Committee" meeting type — every one of those 105 has the
  bug. Plus item titles can also contain `&`/`?`/`#` (not measured
  here, but Granicus titles like "Resolution authorizing $X for ABC &
  Co." are common). Bug is real and high-volume. Fix is one-line
  `| urlencode` swap.

- **R3 (RSS jargon leak): CONFIRMED — FIX SHAPE NUANCED.**
  `_macros.xml.j2:9` emits raw `data_quality={enum}`. The HTML's
  `friendly_labels` dict is a `{% set %}` local to `data_debt.html`
  template scope. **The RSS macro has no access to it** — Jinja
  imports between templates are namespaced and `friendly_labels` is
  not registered as a global. Fix shape options:
    1. Inline a dict in `_macros.xml.j2` (mirrors HTML's
       template-local strategy; **two copies of the dict — drift risk**).
    2. Move the dict to a Jinja global via `register()` in
       `filters.py` (single source of truth; both surfaces import it).
    3. Pre-resolve in the route, pass each item with a
       `friendly_label` key already filled in.
  Recommend option (2) — it's the cleanest and matches the
  `rss_now_rfc822` global pattern F5 already established.

- **R4 (unstyled BEM): CONFIRMED.** Grepped all 6 stylesheets
  (`styles.css, layout.css, councilmatic.css, tweaks.css, mobile.css,
  css/smart_brevity.css`): zero matches for any of `.data-debt-list,
  .data-debt-row, .data-debt-row__title/__meta/__needs/__action,
  .data-debt-pager, .data-debt-loadmore`. The page renders as a
  default `<ul>` with browser bullets. The wrapper section uses
  `.feed`/`.feed-head`/`.feed-title`/`.hero-sub` (all styled in
  `layout.css`/`styles.css`), so the chrome is fine — but the list
  items have no row separation, no spacing, no layout grid. Visually
  this is a citizen-facing regression at deploy.

- **R5 (admin email hardcoded): CONFIRMED.** Verified end-to-end:
    - `config.py:25` — `ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@docket.pub")`.
    - `web/__init__.py:21` — `app.config["ADMIN_EMAIL"] = ADMIN_EMAIL`.
    - `engagement_strip.html:77` — `{{ config.ADMIN_EMAIL }}` (precedent).
    - F5 `_data_debt_admin_email` → `municipality.get("admin_email") or "admin@docket.pub"` (literal bypass).
  Verified: `\d municipalities` shows no `admin_email` column, so the
  `municipality.get("admin_email")` arm always returns None — the
  literal is the *only* path today. Fix: replace literal with
  `current_app.config.get("ADMIN_EMAIL", "admin@docket.pub")`. One
  line, matches engagement_strip precedent.

## Downstream-effects audit

a. **R1 fix downstream (lock interaction with `_overview_cache`):**
   The two caches are independent dicts with independent purposes
   (city HTML overview vs RSS XML body), so adding a lock to
   `_rss_cached` does NOT create a cross-cache inconsistency. The
   `_overview_cache` has the same race and that ships without
   incident; if the user wants symmetry, lock both at once. Recommend
   locking only `_rss_cached` in the F5 fix-up — adding a lock to
   `_overview_cache` is out of scope and the migration is independent.

b. **R2 fix downstream (`urlencode` separator semantics):** Verified
   in a Python shell that Jinja's `| urlencode` percent-encodes `&`,
   `?`, `#`, and spaces correctly. The `engagement_strip.html:77`
   precedent uses `?subject={{ _subject | urlencode }}&amp;body={{
   _body | urlencode }}` — the structural `&amp;` is the literal
   query-param separator (HTML-attribute-escaped), and only the
   *values* go through urlencode. **F5's fix-up should mirror this
   exactly: `&amp;` separator, `| urlencode` on values.** No
   structural risk.

c. **R3 fix downstream (macro access to friendly_labels):** Confirmed
   the macro is not registered as a global and no context_processor
   ships it. **Recommended fix: register `friendly_labels` (and a
   `friendly_label(item)` helper) as Jinja globals in `filters.py`
   alongside `rss_now_rfc822`** so both HTML and RSS surfaces share
   one source of truth. The HTML template can then drop its local
   `{% set %}` block and `{% macro %}` definition. Side benefit: the
   dict becomes Python-testable (no need to render a template to
   verify a translation).

d. **R4 fix downstream (which stylesheet, mobile rules, collisions):**
   Best home is `tweaks.css` (where F2/F3/F4 added narrow
   feature-specific rules). Mobile concern: the data-debt list rows
   already use `.t-meta` (styled in `styles.css`), but the row
   itself has no padding/border — at <= 600px the `<li>` rows will
   stack with no gap. Recommend a single `@media (max-width: 600px)`
   block in `mobile.css` for `.data-debt-row` adding tighter
   padding, OR inheriting from a reused `.feed-row`-family class.
   Class-name collision check: grepped for `data-debt` across all
   CSS — zero existing rules, so no collisions. Greenfield.

e. **R5 fix downstream (config.ADMIN_EMAIL unset behavior):**
   `ADMIN_EMAIL` is `os.environ.get("ADMIN_EMAIL", "admin@docket.pub")`
   — the default is a real string, never None. So even with no env
   var set, `current_app.config.get("ADMIN_EMAIL", ...)` returns
   `"admin@docket.pub"`. **No degradation risk.** F5 will render
   identically in unconfigured environments and pick up an override
   automatically when ops sets `ADMIN_EMAIL=...` in Railway env.
   Engagement_strip already uses this pattern in production with no
   issues.

f. **Cross-bug R2 + R5 interaction:** R5 changes the *recipient*
   half of the mailto (the `mailto:{{ admin_email }}` portion). R2
   changes the *query-string* half (subject + body encoding). The
   two halves of the URL are independent — fixing R5 does not change
   the body content, and fixing R2 does not change the recipient.
   They can land in any order in a single commit. No interaction.

g. **F5 + F4/F3/F2 interaction (filter collisions, path rename):**
    - **`rss_rfc822` and `rss_now_rfc822` registration**: grepped
      filters.py and __init__.py — no name collisions with existing
      filters/globals. Safe.
    - **Path rename `/al/<city>/hearings.rss` → `/al/<city>/upcoming-hearings.rss`**:
      grepped all of `src/` and `tests/` — every reference points to
      the new endpoint name `public.upcoming_hearings_rss` (used as
      `url_for(...)` everywhere). Old path appears only in commit
      messages and one test comment documenting the rename. No
      callers to break.
    - **`block head` in `data_debt.html`**: confirmed `base.html:19`
      defines `{% block head %}{% endblock %}` — F5's first override
      lands cleanly. (Worth flagging in PR description so future
      template authors know the slot exists, per Opus #2 NICE-TO-HAVE.)

h. **5-city blind spots:** F5 has TWO citizen-experience oddities for
   non-Birmingham cities:
    - **Mobile, Vestavia Hills, Homewood have ZERO meetings with
      "hearing" in the title** in the local DB. The upcoming-hearings
      RSS for those 3 cities will be permanently empty under the v1
      heuristic. Not a bug (empty RSS is valid) but a citizen pointed
      at, e.g., `/al/mobile/upcoming-hearings.rss` will see an empty
      feed forever — and the F5 RSS is the spec-promised "primary
      consumption path." This is the v1 limitation the implementer
      already flagged in the docstring; recommend leaving as-is for
      v1 ship and addressing when the structured `action_type='hearing'`
      lands. **Not a fix-up blocker, but worth surfacing to user.**
    - **`municipality.admin_email` column doesn't exist** — verified
      via `\d municipalities`. Every city falls back to
      `admin@docket.pub` (or the env var override per R5 fix). No
      city has its own admin email today. Decision #77 is satisfied
      by the project mailbox; per-city addresses are a Migration 015
      follow-up.

## New findings (beyond the three rounds)

### REQUIRED (added or upgraded)

- **R6 (NEW): Upcoming-hearings RSS GUID is non-unique within a city
  feed.** `templates/rss/upcoming_hearings.xml.j2:18`:
  ```jinja
  <guid isPermaLink="true">{{ url_for(... meeting_id=item.meeting_id ...) }}#hearing</guid>
  ```
  The fragment is the literal string `#hearing` — same suffix for
  every item. The query happens to return one row per meeting today
  (scalar `LIMIT 1` subquery), which makes the URL part unique per
  item. **But two future cases break this:**
    1. Two different meetings on the same day to the same URL would
       both have `meeting_url#hearing` — fine here because URLs differ
       per meeting.
    2. **The structural risk is real if the docstring ever matches
       reality.** `query.py:1933-1936` says "one row per hit
       (meeting_id, hearing_title)" — Sonnet S7 already flagged the
       docstring drift. If a future refactor changes the SQL to
       genuinely emit N rows per meeting (matching the docstring),
       all N will share the same GUID and feed readers will dedupe
       them silently. Most readers (Feedly, NetNewsWire) treat GUID
       as the de-dup key.

  **Recommended GUID shape:** include the `hearing_title` slugified
  or a hash so the GUID is unique per (meeting, hearing) pair. E.g.,
  `meeting_url#hearing-{{ item.hearing_title | hash }}`. **Upgrade
  from latent to REQUIRED** because the spec docstring already
  promises N-rows behavior and a future fix to align the SQL with
  the docstring would silently break feed dedup. Cheap to fix now.

  *Counter-argument:* current SQL emits one row per meeting, so the
  bug is theoretical until the docstring/SQL is reconciled. If the
  user prefers, downgrade R6 to SUGGESTED and tackle in the same
  fix-up that resolves Sonnet's S7. Either way, the two findings
  are linked.

### SUGGESTED (added)

- **S-NEW-1: HTTP `Cache-Control` headers absent on RSS responses.**
  `data_debt_rss` and `upcoming_hearings_rss` return
  `Response(rendered, mimetype="application/rss+xml")` with no
  `Cache-Control` header. The 60-min in-memory cache is server-side
  only; intermediate caches and feed-reader-side caches will re-poll
  freely. Setting `Cache-Control: public, max-age=3600` matches the
  TTL and lets readers honor it. ~3 lines per route. Low-priority
  but a real gap because RSS is poll-driven.

- **S-NEW-2: `<![CDATA[]]>` close-detection unguarded.** Both RSS
  templates (`data_debt.xml.j2:14`, `upcoming_hearings.xml.j2:14`)
  wrap macro output in CDATA. Opus #2 noted this; verifying it's
  still latent. The standard mitigation is to escape `]]>` →
  `]]]]><![CDATA[>` inside the wrapped content, or skip CDATA and
  use entity escaping throughout. **Real risk is essentially zero
  in municipal-meeting text** (no one writes `]]>` in a meeting
  title) — defer.

- **S-NEW-3: RFC-822 / GUID validity not asserted by tests.** Opus
  #2 already flagged this. The integration tests check elements
  exist, not that the dates parse via `email.utils.parsedate_tz` and
  not that the GUIDs pass uniqueness within a feed. ~5 lines per
  test to add real validator-style assertions; gives much stronger
  regression value than the current shape-only checks.

- **S-NEW-4: Route helper `_data_debt_admin_email` lives in
  `web/public.py`, not `services/`.** F2-F4 patterns put business
  logic in `services/`. This helper is 5 lines and arguably "view
  glue" — not a clean violation — but worth flagging that a future
  per-city admin email lookup (post-Migration 015) should land in
  `services/query.py` alongside `get_municipality`, not in the route
  module. Pure architecture polish.

### Findings to downgrade or refute

- **Opus #2 SUGGESTED ("RSS auto-discovery for upcoming-hearings in
  HTML head") — keep deferred.** The engagement-strip contextual
  link is a discovery path. Adding `<link rel="alternate">` to
  `city.html` is correct but architectural drift (city.html doesn't
  have a `block head` override path today and overriding it
  city-wide for 4 cities ships extra HTML for 99% of pageviews who
  don't subscribe to RSS). Sonnet correctly downgraded this; agree.

- **Opus #1 SUGGESTED ("`test_rss_60_min_cache_returns_same_body`
  monkeypatch unused") — accept, but the *better* version is
  Opus #1's option 2** (use the param to test TTL-expiry), not the
  weaker option 1 (drop the param). The current test mutates data
  to prove "cache returns stale body" but does NOT prove "cache
  miss after TTL boundary" — that's the regression risk Opus #1
  named. Recommend the fuller fix.

- **Opus #1's "list_upcoming_hearings docstring drift" + Sonnet's
  S7 are the same finding.** Track as one. Aligned with R6's
  structural concern (the SQL emits 1 row per meeting; docstring
  says N).

## Recommended fix-up scope (final)

### Aggregate REQUIRED:

1. **R1 — `_rss_cached` thundering-herd race.** Add `threading.Lock`
   with double-checked locking. Latent (single-worker sync gunicorn
   today) but cheap to fix while helper is small. Mirror the lock
   pattern; do NOT also lock `_overview_cache` in this commit (out
   of scope).
2. **R2 — Mailto URL encoding bug** (`data_debt.html:110, 146`).
   Lift `_subject` and `_body` to Jinja `{% set %}` vars and apply
   `| urlencode` to each. Use `&amp;` as the structural query
   separator. Match `engagement_strip.html:77` exactly. Pool: 111+
   meetings in local DB; production count higher. Both HIGH and
   NORMAL branches. Refactor into a `data_debt_row()` macro to
   land the fix once.
3. **R3 — RSS jargon leak** (`_macros.xml.j2:9`). **Fix shape
   recommendation: register `friendly_labels` dict and
   `friendly_label(item)` helper as Jinja globals in `filters.py`**.
   Both HTML and RSS surfaces import them — single source of truth,
   no drift risk.
4. **R4 — Five+ unstyled BEM classes**. Add CSS in `tweaks.css` for
   `.data-debt-list, .data-debt-row, .data-debt-row__{title,meta,needs,action},
   .data-debt-pager, .data-debt-loadmore`. Mobile: one
   `@media (max-width: 600px)` block in `mobile.css` for tighter row
   padding.
5. **R5 — Admin email hardcoded fallback** (`public.py:435`).
   Replace `"admin@docket.pub"` with
   `current_app.config.get("ADMIN_EMAIL", "admin@docket.pub")`.
   Matches `engagement_strip.html:77` precedent.
6. **R6 — Upcoming-hearings RSS GUID non-uniqueness** (NEW).
   Either include `hearing_title` slug/hash in the GUID fragment,
   OR explicitly tie the GUID to `meeting_id` only and reconcile
   the docstring at `query.py:1933` to "one row per matching
   meeting" (matching the SQL's actual scalar-LIMIT-1 behavior).
   Pick one path; document the choice in the macro.

### Aggregate SUGGESTED-accept (in fix-up):

1. **`test_rss_60_min_cache_returns_same_body` — use
   `monkeypatch`** to test post-TTL expiry (Opus #1 option 2 — the
   stronger fix).
2. **`list_upcoming_hearings` docstring** alignment with
   actual SQL behavior (one row per meeting). Couples with R6.
3. **Template uses `municipality.slug` not `item.municipality_slug`**
   (Sonnet S6). One-line consistency fix; matches RSS template.
4. **HTTP `Cache-Control` headers on RSS responses** (S-NEW-1).
   `Response(..., headers={"Cache-Control": "public, max-age=3600"})`
   on both RSS routes. Matches the in-memory TTL.
5. **Mailto `data_debt_row()` macro extraction** (Opus #2 SUGGESTED).
   Couples with R2. Lands the fix once instead of twice.

### Aggregate SUGGESTED-defer:

1. **RSS auto-discovery for upcoming-hearings in `city.html` head**
   (Opus #2). Architectural drift; engagement-strip contextual link
   is sufficient for v1.
2. **`test_rss_cache_key_isolation_per_city` structural weakness**
   (Opus #1). Stronger test would seed BHM-only data; current test
   passes structurally. Acceptable for now.
3. **`test_data_debt_empty_state_is_citizen_friendly` reliance on
   Vestavia Hills emptiness** (Opus #2 + Sonnet S8). Test-data
   churn risk; defer.
4. **`<![CDATA[]]>` close-detection** (S-NEW-2). Vanishingly low
   risk in municipal-meeting text.
5. **Eyebrow copy "Data debt"** (Opus #2). Citizens won't recognize
   the phrase; H1 is fine. Minor copy polish, not blocking.
6. **RFC-822 + GUID validator-style test assertions** (S-NEW-3 +
   Opus #2). Stronger test rigor; defer.
7. **`_data_debt_admin_email` location** (S-NEW-4). Architecture
   polish; the post-Migration-015 callsite migration handles this.
8. **Mailto in RSS `<description>`** (Opus #2). Decision #77 is
   satisfied by the HTML mailto.

### NICE-TO-HAVE: 7+ deferred

N1 (upcoming-hearings head link), N2 (inline style on
`data_debt.html:56`), N3 (decision #32 reference comment), N4
(cache size comment), Opus #1 cache-key naming + render_fn naming,
Opus #2 em-dash in RSS title, Opus #2 channel-level
`municipality.name` not escaped (4-cities-safe today), Opus #2
empty-state period-doubling.

## Sign-off question for the user

**Ship the fix-up commit covering R1 + R2 + R3 + R4 + R5 + R6 (six
REQUIREDs) plus the five SUGGESTED-accept items above (TTL
monkeypatch, hearings docstring, `municipality.slug` consistency,
RSS Cache-Control headers, `data_debt_row()` macro extraction)?**
The remaining 8 SUGGESTED-defer + 7 NICE-TO-HAVE land as
follow-ups. R6 is the new finding this audit added (latent today,
real after the docstring/SQL reconcile). All other items mirror the
prior packet with one scope correction (R2 pool is 111+ meetings,
not 6 — Homewood's recurring "Planning & Development Committee"
dominates).
