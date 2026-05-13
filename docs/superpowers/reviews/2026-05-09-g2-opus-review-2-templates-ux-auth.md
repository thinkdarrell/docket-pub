# G2 Review #2 — Templates + UX + Auth (Opus)

**Commit:** b2c053f
**Branch:** feat/impact-first-phase-2-track-3
**Reviewer angle:** Templates + UX + auth + accessibility + admin copy tone

## Summary

G2's two new admin templates are workmanlike: BEM classes have CSS rules (no R-T1 repeat), JSONB readback is correctly defended (no R-T2 repeat), auth integrates cleanly with the blueprint `before_request` hook, and pagination follows the F5 "Load more" precedent. **One real UX bug**: `?highlight=N` highlights via CSS but doesn't scroll the row into view — admins clicking the source-anchor "[admin queue]" affordance for a row not on the first 50-item page will silently see the queue with no visible highlight. CSRF is absent across admin POSTs (consistent with the F2 council-CRUD precedent — pre-existing project-wide gap, not G2-introduced).

## REQUIRED

- **`?highlight=N` is half-implemented.** `data_debt.html:17` comment says "scrolls/highlights row id=item-N" but the actual implementation is CSS-only:
  - The URL is a query param (`?highlight=42`), not a fragment (`#item-42`). Browsers do NOT auto-scroll for query params — only for fragments.
  - No JS `scrollIntoView` / `location.hash` hook anywhere (`grep -n scrollIntoView` returns nothing in `data_debt.html` or `source_anchor_button.html`).
  - The caller in `templates/partials/source_anchor_button.html:128` is `url_for('admin.data_debt', highlight=item.id)` — admins land at `/admin/data-debt/?highlight=42`, the page renders with row #42 styled `.highlighted` (orange-soft background), but the viewport is at the page top. The highlighted row may be 30+ rows down (page size 50) and entirely below the fold.
  - Worse — if the targeted item is on page 2+ (offset >= 50), it won't be on the rendered page at all. The route doesn't compute the right offset for the requested highlight ID. The admin lands on offset=0 with no visible highlighted row anywhere — silent no-op.
  - **Two acceptable fixes**, pick one:
    1. Convert `?highlight=N` to `#item-N` fragment in the source-anchor URL builder + add `:target { background: ... }` CSS, get free browser-native scroll. Drop the route's `highlight` query-param plumbing entirely.
    2. Keep the query param + add a tiny inline `<script>` at end of `data_debt.html` that does `document.getElementById('item-' + new URLSearchParams(location.search).get('highlight'))?.scrollIntoView({block: 'center'})`. Plus route-level: if the highlight ID isn't in the current page slice, redirect to the offset that contains it.
  - The existing test `test_admin_data_debt_highlight_query_param` (lines 259–272) only confirms the class is in the HTML — it doesn't verify the row is actually visible, which is the user-facing bug. Add a test covering "highlight ID on page 2 → route handles it" once #2 is picked, or once #1 is picked, the test becomes "fragment in href, not query param."

## SUGGESTED

- **`last_error_at` is selected but never rendered.** `query.py:1968` includes it; `errors.html` only renders `last_error_message`. Either drop the column from the SELECT or surface it as a "Last failed" timestamp column. Admins triaging an errors queue care about *when* the failure happened (vs. an old failure that's been sitting). The reviewer prompt asked specifically about last-error-at shape — current shape is "missing entirely from UI."

- **`tweaks.css:218` `border-bottom: 1px solid var(--rule, #ddd)` fallback chain is fine, but `tweaks.css:225` `var(--accent-soft, #fff3e0)` is a different orange than the `cal-alert` rule on line 198 (`#fff3e0` literal vs. token).** Inconsistent — use the token everywhere. `--accent-soft` is defined at `styles.css:18` (`oklch(0.92 0.04 200)`) — that's a soft cyan-blue, not orange. So `.highlighted` will render blue-ish on the OCR queue and `.cal-alert` will render orange on calibration. Confirm the visual intent — if highlighted should be orange-warm to call attention, use `--accent-soft` consistently or pick a warm token like `--paper-3` instead.

- **Mobile responsiveness — no table override in `mobile.css`.** `grep -n queue-table src/docket/web/static/mobile.css` returns nothing. The 8/9-column `queue-table` will horizontally overflow on tablets/phones (an admin checking the queue from a phone is plausible — the source-anchor link also fires on mobile). Either:
  - Add `.queue-table { display: block; overflow-x: auto; }` or `min-width: 0;` for tablets at `@media (max-width: 768px)`.
  - Or wrap the table in `<div style="overflow-x: auto;">` to prevent horizontal page scroll while letting the table itself scroll horizontally.
  - The existing `cal-panel` wrapper has no overflow handling either (verified at `tweaks.css:185`). Defer to "admins use desktop only" if that's the explicit decision, but flag.

- **Heading hierarchy.** `data_debt.html` and `errors.html` both use `<h1>` for page title and `<h2>` for the "Empty" state — but the section that renders the table has NO `<h2>`. Screen-reader users navigating by heading will skip from page title straight to "Empty" only when empty, and from page title to nothing when populated. Add `<h2 class="t-meta-only-visual" hidden>OCR queue items</h2>` (or similar visually-hidden but SR-readable) inside the populated `<section class="cal-panel">`. Calibration dashboard has this right (every panel gets `<h2>A. Per-item divergence...`).

- **`<button>` lacks accessible label disambiguation when many "Retry" buttons stack.** A screen reader navigating the errors queue hears "Retry, Retry, Retry, Retry, Escalate, Retry, Escalate..." with no item context. Add `aria-label="Retry item #{{ it.id }} ({{ it.title or 'untitled' }})"` to each button. Same fix on the data_debt template's per-row Retry button. Same pattern as `members.html`'s Deactivate button (which has the same gap — pre-existing, but G2 doubled the surface area).

- **Confirmation prompt for Escalate.** Escalate is a terminal-ish action (worker stops auto-retrying; only manual intervention restores normal flow). One stray click escalates an item. Add `onclick="return confirm('Escalate item #{{ it.id }} for manual review? Worker will stop auto-retrying it.');"` on the escalate button — defensive against fat-finger clicks. Retry is non-destructive (re-runs the worker), so no confirm needed.

- **No visual distinction between Retry and Escalate.** Both are plain buttons at `font-size: 0.85rem`. Escalate is the more consequential action — it should be visually heavier (e.g., `style="background: var(--paper-3); border: 1px solid var(--rule-strong);"` or distinctive color). Today they read identically.

- **No "no double-submit" guard.** A slow click → spinner → click again → two POSTs. Retry is idempotent (resets to pending; second POST does the same), but escalate's audit trail will write two `processing_status_audit` rows (one with `payload={admin_escalated: true}`, both same actor, same item). Add `onclick="this.disabled=true; this.form.submit();"` or HTMX `hx-post` with a debounce. Low severity since the audit table tolerates dupes, but cumbersome to read.

- **Admin copy: "data_quality" / "priority" / "processing_status" column headers are intentionally jargon-precise (admin surface — fine).** But the empty state on data_debt.html uses citizen-grade copy ("All extractable agenda content is up to date") while errors.html uses admin-grade ("No items currently in `failed_permanent` state"). Pick one tone for admin emptys. Recommend the errors.html shape — admins read enum values fluently; "extractable agenda content is up to date" is the F5 public page register.

- **`escalated?` cell — boolean rendering.** `errors.html:95` renders `<strong>yes</strong>` for escalated, em-dash for not. A subtle visual badge (e.g., `<span class="cal-alert">⚑ escalated</span>` reusing the existing `cal-alert` orange) would scan faster than scanning a column of em-dashes for the rare strong-yes.

- **Pagination — no "back" link.** F5 public data-debt page has the same shape (load-more only, no "previous"). G2 inherits it. Once an admin clicks "Load more" they can't return to page 1 without re-typing the URL. Cheap fix: render `<a href="{{ url_for('admin.data_debt') }}">← Back to top</a>` next to the "Load more" link when `offset > 0`.

- **`.queue-flash` styling is bare bones — no success vs. error category.** Login flashes use `with_categories=true`; G2 flashes don't pass categories from `flash()` and don't read them in template. If a future failure path wants to flash an error, there's no styling distinction. Low severity for v1; flag for the Migration 015 follow-up.

## NICE-TO-HAVE

- **`it.title or '—'`** — the public F5 page does the same. But several Birmingham items have titles that are full agenda-body paragraphs (>120 chars triggers the title-fallback rule). Truncating to ~80ch with `… see item` link to item detail would keep the table scannable. Defer if this is actually rare.

- **`<code>` wrapping** of enum values (`data_quality`, `processing_status`, `data_debt_priority`) — the JetBrains Mono load and 16-byte tokens are visually heavy in cells. Worth A/B-ing whether plain text (no `<code>`) reads cleaner at table density. Calibration dashboard does the same `<code>` wrapping; consistent if not optimal.

- **`first_of_type` selector in `cal-panel`** (`tweaks.css:190`) — if both data_debt.html and errors.html nest two `cal-panel` sections (the "Empty" state vs. the populated state are mutually exclusive `if/else`, so only ONE `cal-panel` ever renders), the rule has no effect on these templates. No harm, but evidence the rule was authored for calibration.html (multi-panel) and is silently dead here.

## Implementer-flagged question responses

1. **JSONB readback for "Escalated?" column.** **Safe.** `errors.html:80-81` does `{% set overrides = it.score_overrides or {} %}` then `overrides.get('admin_escalated') == true`. Psycopg2 returns JSONB columns as Python dicts (or None when SQL NULL) when using RealDictCursor (verified — `query.py:1992` returns `[dict(row) for row in cur.fetchall()]`). The `or {}` guard handles None. `.get('admin_escalated')` returns whatever the dict has (True / not present → None / unexpected non-bool). Comparison to Jinja `true` (= Python `True`) is strict equality — a string `"true"` or int `1` won't match, but the writer at `admin.py:356` only ever writes Python `True`, so this is closed. **No R-T2 repeat.** The G1 lesson — never `{{ obj }}` a dict — isn't applicable; the template does field-level access throughout. Minor: a string-shaped legacy value would silently render as "—" instead of "yes," but that's defensive degradation, not a leak.

2. **Highlight UX scope.** **Half-implemented; user-visible bug.** CSS-only `id="item-N" + class="highlighted"` would be sufficient IF the URL were `/admin/data-debt#item-42` (fragment) — browsers auto-scroll to fragment IDs. But the implementation uses `?highlight=42` (query param) which does NOT auto-scroll. Confirmed: `grep` for `scrollIntoView` / `location.hash` returns nothing. The admin lands at the page top with row #42 highlighted somewhere below the fold (or off the page entirely if N is past offset 50). The implementer's CSS-only assertion is technically true, but the resulting affordance is not what "highlight" implies. Page-anchor navigation (option 1 — convert to fragment) is sufficient and simpler; the JS option (2) is needed only if the route also needs to compute the right offset. See REQUIRED #1.

## Out-of-scope observations

(deferred to reviewer #1)

- Route logic, query helpers (`list_data_debt_items` cross-city extension, `list_failed_permanent_items_all_cities`), retry/escalate semantics, audit-row writes, 405-on-GET enforcement, parallelism / `SELECT FOR UPDATE` interaction with the worker.
- The "Migration 015 candidate" comment at `errors.html:14-15` flagging `requires_manual_review` as a future column.
- Multi-city parametrization correctness in `test_admin_queues.py` lines 177–196 / 280–303.
- Decision-#79 vs. plan-§G2.2 ordering reconciliation noted at `query.py:1944-1949`.
- `processing_status_audit` schema constraints (specifically whether `payload` accepts the `{"admin_escalated": true}` shape on retry too — currently only escalate writes payload, retry doesn't).
- Whether `score_overrides` clobber-merge at `admin.py:355` correctly preserves Stage 2.5 floor data in the worst case (existing keys preserved by `dict(existing_overrides)` then `merged["admin_escalated"] = True` only adds, doesn't remove — looks fine, but the worker contract is reviewer #1's scope).
