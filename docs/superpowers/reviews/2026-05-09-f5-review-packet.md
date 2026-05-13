# F5 Review Packet — User Verification Gate

**Commit under review:** `ea3aeed` on `feat/impact-first-phase-2-track-3`
**Worktree:** `~/docket-pub-pf2-track-3`
**Reviews synthesized:**
- Opus #1 (route + helpers + cache): `2026-05-09-f5-opus-review-1-route-helpers-cache.md` — 1R / 5S / 4N
- Opus #2 (template + RSS XML + UX): `2026-05-09-f5-opus-review-2-template-rss-ux.md` — 4R / 11S / 5N
- Sonnet 4.6 (second-look): `2026-05-09-f5-sonnet-second-look.md` — confirmed all 5; 0 new R; 2 new S; refuted 1 false-positive
- Final-auditor Opus 4.7: `2026-05-09-f5-final-audit.md` — re-verified all 5; **upgraded R2 scope 18.5×**; nuanced R3 fix shape; added R6 GUID uniqueness

**Aggregate verdict:** F5 cannot ship as-is — 6 REQUIRED with one (R2) materially wider than the early packet stated. All fixes are small (4 are 1–5 lines; R4 CSS is the largest). After fix-up: ship.

**This is the 11th run of the protocol.**

## Cross-model story (this round)

The audit chain on F5 produced **two material scope corrections** and **one new REQUIRED** beyond the three Opus/Sonnet rounds:

| Finding | Route | Outcome |
|---|---|---|
| R2 mailto pool size | Opus #2 (Birmingham only) → Sonnet (6 BHM titles) → **Auditor (111+ across BHM + Homewood)** | Scope upgraded 18.5× |
| R3 fix shape | Opus #2 (translate the enum) → **Auditor (helper inaccessible from macro context — needs Jinja global registration)** | Fix complexity went from "swap a string" to "promote `friendly_labels` to a global" |
| R6 GUID uniqueness | (NEW, audit) | Caught before fix-up — would have silently deduped feed items if a future refactor honored the SQL docstring |

The audit also clarified two latent-vs-live distinctions:
- **R1 (cache race) is latent today** — Procfile + Dockerfile confirm single-worker sync gunicorn; the race only fires under `--workers > 1` or threaded workers. Still REQUIRED because the fix is one line and the risk grows silently.
- **`municipalities.admin_email` does not exist** — verified via `\d municipalities`. The hardcoded literal isn't bypassing a column; both paths fall back through `config.ADMIN_EMAIL` env var. R5 fix is for consistency with `engagement_strip.html`'s precedent.

The Sonnet round refuted one Opus #2 claim (no pagination UI — load-more does exist at `data_debt.html:156-163`, plain nav consistent with F2 pattern), saving a follow-up.

---

## Category 1 — REQUIRED (must fix in fix-up commit)

### R1. `_rss_cached` thundering-herd race
**Source:** Opus #1, confirmed Sonnet + Auditor
**File:** `src/docket/web/public.py` — `_rss_cached` helper
**Evidence:** No `threading.Lock` around the cache-miss + render + set sequence. Latent today (single-worker sync gunicorn confirmed via Procfile + Dockerfile), but becomes a live race if `--workers > 1` or threaded workers are introduced.
**Fix:** Add `threading.Lock` + `with lock:` pattern around the read-or-render block. One-line addition.
**Note:** Auditor flagged downstream consideration — `_overview_cache` (the precedent) doesn't have a lock either. Either lock both for symmetry, or document the asymmetry. Recommend locking both since the cost is trivial.

### R2. Mailto URL encoding bug — affects 111+ meetings across BHM + Homewood
**Source:** Opus #2, scope dramatically upgraded by Auditor
**File:** `src/docket/web/templates/data_debt.html:110, 146`
**Evidence:**
- Opus #2 found raw `meeting_title` interpolation into hand-percent-encoded mailto.
- Sonnet's local-DB count: 6 Birmingham meetings with `&`/`?`/`#` in titles.
- **Auditor's SQL widened scope to 111+: `homewood|105 + birmingham|6`**, driven by Homewood's recurring "Planning & Development Committee" meeting type. The mailto link will silently break for every Homewood data-debt item with that meeting type plus 6 Birmingham titles.
- Compare correct pattern at `partials/engagement_strip.html:77` using `| urlencode`.
**Fix:** Replace raw interpolation with `| urlencode` filter. Trace through what the precedent does to ensure structural `&` / `?` separators stay literal while user-content values get encoded.
**Auditor downstream-check:** R2's `urlencode` fix and R5's `config.ADMIN_EMAIL` fix touch the same code path. R5 changes the body content; R2 changes the encoding of that body content. Order doesn't matter; both fixes additively compose.

### R3. RSS jargon leak — `data_quality` enum reaches feed subscribers
**Source:** Opus #2, fix shape nuanced by Auditor
**File:** `src/docket/web/templates/rss/_macros.xml.j2:9`
**Evidence:** Macro emits `(data_quality={{ item.data_quality }})` — same enum (`no_text_layer`, `failed_permanent`, etc.) that the HTML page goes out of its way to translate via the `friendly_labels` dict.
**Fix shape (nuanced by auditor):** `friendly_labels` is template-local in `data_debt.html` — the RSS macro can't access it from its own template scope. Three options:
  a. **Register `friendly_labels` as a Jinja global in `filters.py`** (recommended — mirrors the `rss_now_rfc822` global pattern F5 already established; single source of truth)
  b. Pass `friendly_labels` to the macro as a kwarg (verbose at every call site)
  c. Precompute the friendly label in the route and inject as `item.friendly_data_quality` (couples route to template)
Recommend (a). Implementer's choice; the Jinja global is the cleanest match for the existing F5 pattern.

### R4. Five unstyled BEM classes — page renders with default `<ul>` bullets
**Source:** Opus #2, confirmed by Sonnet (zero matches across all 6 stylesheets) + Auditor
**Files:** `src/docket/web/static/{styles,layout,mobile,councilmatic,tweaks,smart_brevity}.css` — none of them style:
- `.data-debt-list`
- `.data-debt-row`
- `.data-debt-row__title` / `__meta` / `__needs` / `__action`
- `.data-debt-pager`
- `.data-debt-loadmore`
**Evidence:** Reviewer pulled rendered HTML; the empty-state path is actually prettier than the populated path because the populated list falls back to default browser styling.
**Fix:** Add CSS rules. Auditor recommends `tweaks.css` for desktop component CSS + a `mobile.css` `@media` block. Match F2/F3/F4 conventions for spacing, color tokens (`--accent-ink`, `--paper`, etc.).

### R5. Admin email hardcoded fallback bypasses precedent
**Source:** Opus #2, confirmed by Sonnet + Auditor
**File:** `src/docket/web/public.py` — `_data_debt_admin_email` helper
**Evidence:**
- Helper returns the literal `"admin@docket.pub"`.
- `partials/engagement_strip.html:77` already uses `{{ config.ADMIN_EMAIL }}` (env-var-driven).
- Auditor verified `municipalities.admin_email` column does NOT exist (`\d municipalities`); both code paths fall back through `config.ADMIN_EMAIL`.
**Fix:** Replace hardcoded literal with `current_app.config.get("ADMIN_EMAIL", "admin@docket.pub")`. One-line swap. Maintains fallback while honoring precedent.

### R6 (NEW from audit). Upcoming-hearings RSS GUID is non-unique within a feed
**Source:** Final auditor
**File:** `src/docket/web/templates/rss/upcoming_hearings.xml.j2`
**Evidence:** Every item's `<guid>` resolves to `meeting_url#hearing` — same fragment for every item from the same meeting. Latent today (SQL emits 1 row/meeting via scalar `LIMIT 1` subquery), but the docstring at `query.py:1933` promises N rows per meeting. If a future refactor honors the docstring (multiple hearing items per meeting), all N items in that meeting will share a GUID and feed readers will silently dedupe.
**Fix:** Either (a) include hearing-title slug or hash in the fragment so each row gets a unique GUID, OR (b) align the docstring to "1 row per meeting" and reuse `meeting_id` alone. Recommend (a) — defensive against future refactor.

---

## Category 2 — SUGGESTED, accept in fix-up

### S1. TTL boundary test stub
**Source:** Opus #1, confirmed Sonnet
**File:** `tests/integration/test_f5_data_debt.py` — `test_rss_60_min_cache_returns_same_body`
Test accepts `monkeypatch` fixture but never patches `time.time` or `_RSS_TTL_SECONDS` — the boundary case is not actually exercised. Use `monkeypatch.setattr` on the time source and assert the cache flips after TTL expires.

### S2. Docstring drift on `list_upcoming_hearings`
**Source:** Opus #1 NICE-TO-HAVE → upgraded by Sonnet
**File:** `src/docket/services/query.py:1933` (approx)
Docstring says "multiple rows per meeting" but the SQL emits exactly one via scalar `LIMIT 1` subquery. Either align docstring to current behavior, or rewrite the query to honor the docstring (which then triggers R6 if we don't unique-ify the GUID first).

### S3. Template scope inconsistency on `municipality.slug`
**Source:** Sonnet
**File:** `data_debt.html` — `url_for` links use outer-scope `municipality.slug` instead of `item.municipality_slug` from the JOIN row. Self-consistent with `data_debt.xml.j2:13`, safe today, but cleaner to use the join-row field for clarity.

### S4. RSS `Cache-Control` HTTP headers
**Source:** Final auditor
**Files:** `public.py` — `data_debt_rss`, `upcoming_hearings_rss`
The 60-min `_rss_cached` is server-side. Adding `Cache-Control: public, max-age=3600` lets intermediate caches and feed-reader-side caches absorb traffic too. One header per response.

### S5. Extract `data_debt_row()` Jinja macro
**Source:** Auditor (suggested in §1c discussion)
**File:** `_macros.xml.j2`
The R3 fix introduces `friendly_labels` as a Jinja global. Once that lands, the per-row rendering pattern can collapse into a shared `data_debt_row()` macro callable from both the HTML and the RSS, reducing drift risk between surfaces.

---

## Category 3 — SUGGESTED, defer with tracking

### D1. RSS auto-discovery on city.html
Implementer added `<link rel="alternate">` only on `data_debt.html`. Adding to `city.html` for both feeds would help feed-reader auto-discovery from the city homepage. Polish; defer.

### D2. RSS `<![CDATA[]]>` content edge case
If a meeting title or description contains `]]>` literal, CDATA wrapping breaks. Rare in practice. Add escape or switch to `|e` in CDATA-wrapped fields. Defer with watch.

### D3. RSS feed validator pass
Run rendered output through W3C Feed Validator post-deploy. Likely passes given the audit found dates are RFC-822, atom self-link present, GUIDs declared as permalinks — but defer formal validation to a smoke step.

### D4. `_overview_cache` lock symmetry (paired with R1)
If R1 adds `threading.Lock` to `_rss_cached`, the same race exists in `_overview_cache`. Either lock both in fix-up (preferred for symmetry) or open a follow-up. Auditor's recommendation is to lock both; defer flag is here in case scope creep is a concern.

### D5. Path rename downstream callers (re-grep)
Implementer renamed `/hearings.rss` → `/upcoming-hearings.rss` and updated `test_engagement_strip.py`. Auditor + Sonnet both grepped for stale references; none found. But a periodic re-grep before push wouldn't hurt — flagged for the fix-up implementer's verification step.

### D6. Mobile responsiveness for `data_debt.html`
F2/F3/F4 caught CSS / breakpoint issues. F5's HTML page hasn't been tested at narrow viewports. After R4 lands, smoke-check via browser dev tools or a media-query test. Defer to user verification.

### D7. RSS HTTP `If-Modified-Since` / `ETag` support
Cleaner cache contract for feed readers. Real win for bandwidth on a popular feed. Out of v1 scope.

### D8. Docstring oversells (general audit)
Opus #1 noted the `list_upcoming_hearings` docstring drift (S2 above). A broader pass over query.py docstrings might surface more drift. Defer; not specific to F5.

---

## Category 4 — NICE-TO-HAVE (declined)

7 items across the four reviews (collapse helpers, module-level constants, wider CSS extraction, RSS namespace prefixes, etc.). All deferred indefinitely.

---

## Decision-trace verifications (no action needed)

- **xfail interpretation verified twice** (Sonnet + Auditor): `test_data_debt_returns_200_when_queue_page_lands` targets `/admin/data-debt/?highlight=42`, a different blueprint from F5's public route. Test correctly stays xfail-strict; will trip when G2 lands the admin queue page.
- **`list_upcoming_hearings` v1 heuristic** (title-substring "hearing" within 60 days): Opus #1 sampled local DB and confirmed FP class essentially empty; FN class ("Public Comment on Zoning") small enough for v1 RSS. Documented as replaceable when a structured `action_type='hearing'` signal lands.
- **RSS structure verification:** RSS 2.0 + `xmlns:atom`, `<atom:link rel="self">`, RFC-822 dates via `email.utils.format_datetime`, CDATA-wrapped descriptions, `_external=True` for absolute URLs, proper `|e` escaping on item titles. All correct.
- **Pagination correctness:** Sonnet refuted Opus #2's "no pagination UI" — load-more is at `data_debt.html:156-163`, plain nav link consistent with F2 pattern.
- **Path rename complete:** all stale `hearings.rss` references removed; `test_engagement_strip.py` updated; auditor regrepped and confirmed.

---

## What the user is being asked to verify

The F4 user gate escalated R2 from `hx-select` band-aid to the cleaner partial-render path (35× response reduction). Apply the same lens here. Areas reviewers tend to under-cover:

1. **R2 scope across cities.** Auditor found 111+ affected meeting titles. If F5 ships without R2, every Homewood data-debt item from a "Planning & Development Committee" meeting will have a broken mailto. Is that acceptable for any duration, or does R2 need to land before F5 hits Railway? (Recommendation: land in fix-up; mailto bugs in citizen-facing surfaces are reputational.)

2. **R3 fix shape.** Auditor recommends promoting `friendly_labels` to a Jinja global. That has cross-template effects (any future template can use it) and is a small architectural commitment. Fine with that, or prefer kwarg-passing or route-precompute?

3. **R4 styling tone.** Five new BEM classes need CSS. The empty-state currently looks better than the populated state (no styling fallback). Reviewers verified the classes don't collide with existing rules but didn't deeply visual-test the populated state on mobile. Worth a smoke-check after fix-up.

4. **R6 GUID future-proofing.** Latent today. Worth fixing now so a future refactor doesn't silently dedupe feed items? (Recommendation: yes, costs near zero.)

5. **Anything reviewers' angles structurally couldn't see** — copy tone, cross-page navigation flow, RSS subscription discoverability from the homepage (D1).

## Sign-off question

> Proceed with the F5 fix-up loop addressing **R1 + R2 + R3 + R4 + R5 + R6** (six REQUIREDs) **+ S1 + S2 + S3 + S4 + S5** (five SUGGESTED-accepts including TTL monkeypatch fix, hearings docstring alignment, `municipality.slug` consistency, RSS `Cache-Control` headers, and `data_debt_row()` macro extraction) in a single fix-up commit, with R3's fix shape being **register `friendly_labels` as a Jinja global** in `filters.py` mirroring `rss_now_rfc822`? The 8 SUGGESTED-defer + 7 NICE-TO-HAVE items land as post-merge follow-ups.

Yes / no / further adjustments.
