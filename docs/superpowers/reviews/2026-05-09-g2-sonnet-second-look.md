# G2 Sonnet 4.6 Second-Look

**Commit:** b2c053f
**Branch:** feat/impact-first-phase-2-track-3
**Reviewer angle:** Verification of REQUIRED items, cross-cutting checks, and additions beyond the Opus rounds.

## Summary

Both Opus reviewers converged correctly on R-T1 (`?highlight=N` partial implementation) as the only REQUIRED. All code was read and tests were run (1080 passed, 2 skipped, 1 deselected, 4 xfailed — baseline intact). No new REQUIREDs were found beyond R-T1. The color-token mismatch flagged by Opus #2 is a real visual defect but is a SUGGESTED, not a REQUIRED: `.highlighted` rows will render soft teal-cyan (the `--accent-soft` token, `oklch(0.92 0.04 200)`) rather than orange, which is visible but semantically inconsistent with the `.cal-alert` orange used elsewhere as an attention-signal. The `backfill_session_id` gap (Opus #1 SUGGESTED #1) is verified as a concrete latent bug activated by B5.

## Verification of the REQUIRED

**R-T1 (`?highlight=N` is half-implemented): CONFIRMED**

Evidence chain:
1. **Source**: `templates/partials/source_anchor_button.html:128` generates `url_for('admin.data_debt', highlight=item.id)` — a query-param URL, not a fragment URL.
2. **Route**: `admin.py:214` receives `highlight` as an int via `_parse_int_or_none(request.args.get("highlight"))` and passes it to the template context. No offset computation, no page-selection logic.
3. **Template**: `data_debt.html:77` applies `class="highlighted"` to the matching row via `{% if highlight is not none and highlight == it.id %}`. The row has `id="item-{{ it.id }}"`.
4. **CSS**: `tweaks.css:224-226` styles `.queue-table tr.highlighted td { background: var(--accent-soft, #fff3e0); }`. This is CSS-only.
5. **No JS**: Global search for `scrollIntoView` and `location.hash` returns nothing in templates or static JS files.

**Auto-paginate behavior (page 2+ failure mode):** The route fetches `items_plus_one = query.list_data_debt_items(None, limit=51, offset=offset)` where `offset` comes from `request.args.get("offset")` — defaulting to 0, not computed from the `highlight` ID. If an item with `highlight=N` is at position 60 in the sort order, the route renders offset=0 (items 1–50), the matching row is absent from the rendered HTML entirely, and the `.highlighted` class never fires. The admin sees the page top with no visible highlight — silent no-op. This is the full failure mode Opus #2 described: both "row off-screen but present" (positions 1–50) and "row not rendered at all" (positions 51+) are real cases.

**Minimal fix (pick one):**
- Option A (zero-JS): Change `source_anchor_button.html:128` from `url_for('admin.data_debt', highlight=item.id)` to `url_for('admin.data_debt') + '#item-' + item.id|string`. Browser native scroll, no route changes. Drop the `highlight` query-param entirely. Add `:target { background: var(--accent-soft); }` to CSS.
- Option B (preserves query-param): Keep the query param but compute the right page offset: `offset = (position_of_highlight_in_full_sort / 50) * 50` and add `scrollIntoView` JS. More code, more testing.

Option A is simpler and was endorsed by both Opus reviewers.

**Test gap**: `test_admin_data_debt_highlight_query_param` (line 259–272) only asserts `id="item-N"` and `class="highlighted"` appear in the rendered body. It does NOT test "if highlight ID is at position 51, route redirects to correct offset." This test would pass even after R-T1 is fully broken for page 2+ items.

## Cross-cutting checks

**a. R-T1 convergence verification:**

The two Opus rounds described distinct failure modes, not the same defect:
- **Opus #1 (SUGGESTED #5)**: Framed as "at scroll height >50, CSS-only doesn't auto-scroll." Proposed `?highlight=N#item-N` to add fragment-based scrolling. Did not explicitly flag the page-2+ scenario where the row is absent entirely.
- **Opus #2 (REQUIRED)**: Flagged both "row off-screen" and "row past offset 50 — never rendered." Explicitly noted the test only checks HTML class presence, not visibility. Escalated to REQUIRED because silent no-op is the dominant failure case.

**Conclusion**: Opus #1 saw the UX degradation (no scroll for on-page rows), Opus #2 saw the correctness failure (off-page rows never appear). These are two facets of the same root cause (query-param vs fragment) but the severity differs: the on-screen case is a UX annoyance, the off-page case is a silent functionality failure. Opus #2's REQUIRED classification is correct. Opus #1 should have also classified this REQUIRED — it underestimated the off-page case by framing it only as "position 49 just outside viewport."

**b. F5/F2/F3/F4 regression check:**

- `pytest tests/integration/test_f5_data_debt.py`: **44 passed**. No regression.
- `pytest tests/integration/test_admin_queues.py`: **24 passed**. No regression.
- `pytest tests/ --deselect <G1 flaky>`: **1080 passed, 2 skipped, 1 deselected, 4 xfailed**. Full baseline holds.
- `query.list_data_debt_items(city_id=None)` extension: The `city_id=None` path skips the `m.id = %s` WHERE clause correctly. The public F5 path calls with `municipality["id"]` (an integer); the admin path calls with `None`. Both call sites tested. Row shape confirmed: the function returns the same columns at both call sites (`id`, `meeting_id`, `item_number`, `title`, `is_consent`, `data_quality`, `data_debt_priority`, `processing_status`, `processing_attempts`, `last_error_message`, `meeting_date`, `meeting_title`, `municipality_id`, `municipality_slug`, `municipality_name`). The G2-only helper `list_failed_permanent_items_all_cities` adds `last_error_at` and `score_overrides` on top — no overlap conflict.

**c. Spec/code drift:**

- **`login_required` vs blueprint hook**: Spec §6.10 says "require `login_required`." G2 uses a `@bp.before_request` hook at `admin.py:25-33` that checks `request.endpoint.startswith("admin.")`. The hook fires before Flask dispatches to any handler; an anonymous POST to `/admin/errors/123/retry` gets the 302-to-login redirect before the handler executes. Behaviorally equivalent to per-view `@login_required`. The `login_required` decorator still exists in `auth.py:23-31` but is unused by G2 routes (all admin routes now go through the hook). This is a G2 extension to the prior pattern — cleaner, acceptable, no gap. The blueprint hook does NOT cover `auth.*` endpoints (they start with `auth.`, not `admin.`), so login/logout remain accessible to anonymous users, as required.

- **Decision #79 vs plan §G2.2 "significance-sorted"**: `query.py:1943-1949` docstring explains the deliberate reconciliation: priority sort (`data_debt_priority DESC`) is used instead of raw `significance_score DESC` because priority is derived from significance heuristics (decision #31). Both queues use the same sort, which is consistent and documented. No semantic divergence — the docstring correctly notes the deviation and its rationale.

- **Decision #77 (data_issue_reports) retired**: Confirmed. G2 adds exactly 4 routes as spec §6.10 enumerates. No `data_issue_reports` queue attempted.

**d. Audit trail symmetry:**

Migration 013 `processing_status_audit` table at line 206-217:
```
id, agenda_item_id, from_status, to_status, action TEXT NOT NULL,
actor TEXT, actor_role CHECK('admin','cron','on_write'), reason TEXT,
payload JSONB, occurred_at TIMESTAMPTZ DEFAULT NOW()
```

Retry handler writes: `from_status`, `to_status='pending'`, `action='retry'`, `actor`, `actor_role='admin'`, `reason='Admin retry from errors queue'`. No `payload`. Matches schema exactly.

Escalate handler writes: `from_status`, `to_status=from_status` (status unchanged — escalate is not a status transition), `action='escalate'`, `actor`, `actor_role='admin'`, `reason='Admin escalated from errors queue...'`, `payload={"admin_escalated": true}`. Matches schema exactly.

One semantic note confirmed from Opus #1: escalate writes `from_status = to_status` because `to_status NOT NULL` constraint requires a value but escalate doesn't change the status. This is technically correct but produces audit rows where `from_status = to_status`, which looks like a no-op to naive queries. Flagged as a follow-up by Opus #1 (SUGGESTED #6) — agreed, but not a v1 blocker.

Both action values (`'retry'`, `'escalate'`) are not constrained by a CHECK — `action TEXT NOT NULL` accepts any string. G3 audit-log viewer (not yet built) will need to know these string values; they're undocumented outside the handler code. Low risk for now.

**e. R-T1 + S4 (--accent-soft token mismatch) interaction:**

Current state: `.highlighted` uses `var(--accent-soft, #fff3e0)`. The `--accent-soft` token is defined in `styles.css:18` as `oklch(0.92 0.04 200)` — a light teal-cyan (hue 200 = teal/cyan family). The fallback `#fff3e0` (orange) only fires if `--accent-soft` is not defined, which it always is. So the fallback is dead code and `.highlighted` rows render **teal-cyan**, not orange.

`.cal-alert` at `tweaks.css:197-198` uses `background: #fff3e0` (literal orange) — intentionally warm for "alert" semantics. The `--accent-soft` token was introduced for cite-chip backgrounds and focus halos, where it IS the right color (teal for "selection" states). Using `--accent-soft` for "highlighted row" conflates two different semantic states (selection vs alert) with different appropriate colors.

**If R-T1 fix adopts Option A (fragment-based):** The `?highlight=N` query param is dropped entirely, so the `.highlighted` CSS class is also dropped. S4 (token mismatch) becomes moot — the `:target { ... }` approach in Option A uses browser-native fragment targeting and can use whatever color is semantically correct, chosen fresh.

**If R-T1 fix adopts Option B (keep query param):** S4 remains — the implementer should replace `var(--accent-soft, #fff3e0)` with a warm token like `var(--warn, #fff3e0)` or the literal `#fff3e0` to match the `.cal-alert` pattern.

S4 severity is SUGGESTED regardless of which option is picked.

**f. S1 B5-latency reality (backfill_session_id on retry):**

Confirmed real gap. `backfill_driver.py:81` pickup query: `WHERE ai.processing_status = %s AND ai.backfill_session_id IS NULL`. An item that B5 processes (setting `backfill_session_id`) and then fails into `failed_permanent` will have `backfill_session_id` set. The retry handler (`admin.py:290-298`) resets `processing_status = 'pending'` and `processing_attempts = 0` but does NOT touch `backfill_session_id`. After retry, the item has `processing_status = 'pending'` AND `backfill_session_id IS NOT NULL` — the B5 pickup query will skip it silently.

This is latent today (no B5 code yet writes `failed_permanent`) but will become a hard bug when B5 lands. The fix is a one-line addition to the UPDATE: `, backfill_session_id = NULL`. Opus #1 correctly categorized this SUGGESTED (not REQUIRED today) and I agree with that classification.

## New findings (beyond the Opus rounds)

### REQUIRED
(none beyond R-T1)

### SUGGESTED

**S-NEW-1: `data_debt.html` comment says "scrolls/highlights" but the implementation doesn't scroll.** Line 17 reads: `?highlight=N query param scrolls/highlights row id="item-N" so the source-anchor button can deep-link to a specific item.` The comment is wrong — it doesn't scroll. Minor doc-debt, but it's in the template that ships; a future developer reading the comment will assume scroll works. Fix when R-T1 is fixed.

**S-NEW-2: `before_request` hook has a dead `import flask` at line 29.** `admin.py:29` does `from flask import session` inside `require_login()`. But `session` is already imported at module level at line 16. The local import is dead code. (This is a slightly different formulation of Opus #1's NICE-TO-HAVE #7 which says "session at line 7" — Sonnet confirms: module-level import at line 16 has `session`, local import at line 29 is redundant. Classify NICE-TO-HAVE, already flagged.)

**S-NEW-3: `errors.html` empty-state tone is admin-precise; `data_debt.html` empty-state is citizen-grade.** Confirmed: `errors.html:58` says "No items currently in `failed_permanent` state." — admin tone. `data_debt.html:56` says "All extractable agenda content is up to date." — citizen-facing register. Opus #2 flagged this (last SUGGESTED). I confirm it's real and agree it's a SUGGESTED. The OCR queue is an admin-only surface; the citizen-grade copy leaks mental model. Fix: align to the errors.html pattern, e.g. "No items with `data_quality != 'ok'` or `processing_status = 'failed_permanent'`."

### NICE-TO-HAVE

**N-NEW-1: `list_data_debt_items` docstring at line 1891 claims the city_id filter uses `m.id = %s` against the `municipalities` table, but there's no explicit comment clarifying that `city_id` IS `municipalities.id`.** The naming is accurate (it is the municipalities PK) but the alias `m` could confuse a reader who thinks `m` might be `meetings`. The query uses `JOIN municipalities m`, so `m.id = city_id` is correct. Consider renaming the parameter or adding a short docstring clarification.

## Findings to downgrade or refute

**Opus #1 SUGGESTED #5 (highlight): should have been REQUIRED.** Opus #1 classified it as SUGGESTED with the note "CSS-only is sufficient for v1 with one tweak." The "one tweak" (adding `#item-N` to the URL) is the actual fix. But the page-2+ silent failure — where the admin clicks "OCR needed" on a low-sorted item, lands at offset=0, and sees NO highlighted row anywhere — is a correctness failure, not a UX polish issue. The REQUIRED classification from Opus #2 is more accurate.

**Opus #2 S4 (--accent-soft token mismatch): accurately categorized as SUGGESTED, not REQUIRED.** The color renders as teal-cyan (visible but semantically inconsistent with orange alert patterns). Does not affect functionality. Keep as SUGGESTED.

**Opus #1 and #2 agree on CSRF as a pre-existing gap, not G2-introduced.** Confirmed: grep for `csrf`, `CSRF`, `WTF_`, `flask_wtf` in `src/` returns nothing. The F2 council-CRUD precedent (add/edit/deactivate member forms) has no CSRF either. G2 is consistent with the existing pattern. The `SESSION_COOKIE_SAMESITE = "Lax"` setting in `__init__.py:42` provides partial CSRF mitigation for same-origin navigation. A dedicated CSRF token is the right long-term fix but it's a project-wide gap, not G2's to introduce alone.

## Final categorization recommendation for the user packet

**Aggregate REQUIRED:**
1. **R-T1** (both Opus rounds): `?highlight=N` is half-implemented — CSS class fires but no scroll, and items past offset 50 aren't rendered at all. Fix: change `source_anchor_button.html:128` to emit `#item-N` fragment URL and add `:target { background: var(--accent-soft); }` CSS rule (Option A — no JS, no route changes). Delete the `highlight` query-param plumbing from `admin.py` and `data_debt.html`. Update `test_admin_data_debt_highlight_query_param` to assert fragment in `href`, not CSS class in HTML.

**Aggregate SUGGESTED-accept (for this PR or as labeled follow-ups):**
1. **S1 from Opus #1**: `retry` handler must clear `backfill_session_id` before B5 lands. One-line fix; defer to B5 ticket if preferred.
2. **S2 from Opus #1**: `retry` handler should clear `last_error_message` / `last_error_at` for row-state hygiene.
3. **S4 from Opus #2 / cross-check e**: `--accent-soft` token renders teal-cyan on `.highlighted` rows, not orange. After R-T1 fix (Option A), S4 is moot — drop the CSS class entirely. After Option B, fix the color.
4. **S-NEW-3 (this review)**: `data_debt.html` empty-state copy is citizen-grade on an admin-only surface. Align to `errors.html` pattern.

**Aggregate SUGGESTED-defer:**
1. Trailing-slash inconsistency (`/data-debt/` vs `/errors`) — cosmetic, well-described by Opus #1.
2. Escalate `from_status = to_status` audit row shape — schema-change scope, follow-up.
3. Worker re-pickup latency flash text ("retry queued" implies immediate action, but B5 isn't live yet) — runbook note is fine for now.
4. All Opus #2 UX/accessibility SUGGESTEDs (aria-labels, confirm on escalate, mobile responsive, heading hierarchy, pagination back link).

**NICE-TO-HAVE:** 6 items (Opus #1 #7–#10, Opus #2 NTH block, N-NEW-1 from this review).

---

**Top-line verdict:** G2 ships after R-T1 fix. The fix is small (one URL change in `source_anchor_button.html`, one CSS rule, test update) and does not touch the service layer or auth. All 1080 tests pass on the current commit. The data path, audit writes, and auth are correct.
