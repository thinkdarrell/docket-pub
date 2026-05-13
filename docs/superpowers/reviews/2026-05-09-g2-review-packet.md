# G2 Review Packet — User Verification Gate

**Commit under review:** `b2c053f` on `feat/impact-first-phase-2-track-3`
**Worktree:** `~/docket-pub-pf2-track-3`
**Reviews synthesized:**
- Opus #1 (routes + helpers + retry semantics): `2026-05-09-g2-opus-review-1-routes-helpers-retry.md` — 0R / 6S / 4N
- Opus #2 (templates + UX + auth): `2026-05-09-g2-opus-review-2-templates-ux-auth.md` — 1R / 11S / 3N
- Sonnet 4.6 (second-look): `2026-05-09-g2-sonnet-second-look.md` — confirmed R-T1, validated Opus #2's escalation, added 1 SUGGESTED, traced R-T1+S4 simplification
- Final-auditor Opus 4.7: `2026-05-09-g2-final-audit.md` — re-verified R-T1, **added R-T2 (migration number correction)**, confirmed B5 latency one-line fix, downgraded S4 to MOOT after R-T1 Option A

**Aggregate verdict:** G2 ships after fix-up. **2 REQUIRED + 5 SUGGESTED-accept** in the fix-up commit, ~13 SUGGESTED-defer + 7 NICE-TO-HAVE deferred. All fixes are 1–5 line changes; no architectural rework. Implementation is otherwise solid (atomic transactions verified, JSONB merge non-clobber tested, parameterized SQL throughout, F5 regression slice 44/44 green, auth-on-POST works correctly via blueprint hook).

**This is the 13th run of the protocol.**

## Cross-model story (this round)

The chain produced one **convergent finding** on R-T1 (both Opus angles caught it from different directions, Sonnet escalated to REQUIRED, auditor confirmed) and one **scope correction** by the auditor on R-T2 (all three prior rounds left as informational; auditor elevated to REQUIRED).

| Stage | Catch |
|---|---|
| Opus #1 (routes) | Saw highlight as no-scroll UX degradation → SUGGESTED |
| Opus #2 (templates) | Saw highlight as half-implemented + items past offset 50 missing → REQUIRED |
| Sonnet | Validated Opus #2's REQUIRED escalation; **traced R-T1+S4 simplification** — fragment-fix drops `.highlighted` entirely, closes two findings together |
| Auditor | Re-verified R-T1 from source; **added R-T2 (migration number)**; downgraded S4 to MOOT |

**13th cross-model confirmation** of the multi-angle protocol value. One additional pattern this round: **the auditor caught documentation-correctness issues all three prior rounds saw but didn't classify as fixable.**

---

## Category 1 — REQUIRED (must fix in fix-up commit)

### R-T1. `?highlight=N` is half-implemented (Sonnet's Option A)
**Source:** Opus #2 (escalated by Sonnet from Opus #1's SUGGESTED), confirmed by auditor
**Files:**
- `src/docket/web/templates/partials/source_anchor_button.html:128` — generator of `?highlight=N` URLs
- `src/docket/web/admin.py:213-214` — route handler (parses highlight + offset independently with no coupling)
- `src/docket/web/templates/admin/data_debt.html` and `errors.html` — row-rendering (`id="item-N"` + `class="highlighted"`)
- `src/docket/web/static/tweaks.css` — `.highlighted` rule

**Evidence:**
1. Browser does NOT auto-scroll for query parameters; only fragments scroll.
2. Items past offset 50 are entirely absent from rendered HTML (no auto-paginate). Admin lands on `/admin/data-debt?highlight=42` with item 42 on page 2 → row simply doesn't appear.
3. `.highlighted` CSS uses `var(--accent-soft, #fff3e0)` but `--accent-soft` resolves to soft teal-cyan `oklch(0.92 0.04 200)`, NOT orange. The `#fff3e0` fallback is dead code (token always defined).

**Fix (Option A — fragment-only):**
- Change `source_anchor_button.html:128` to emit `#item-N` fragment instead of `?highlight=N` query param
- Browser-native scroll handles affordance
- Drop `.highlighted` CSS class entirely (closes S4 too — `.highlighted` is G2-only by grep)
- Drop the route's highlight-handling code path (it's not load-bearing)
- Update tests asserting class presence — change to fragment URL assertion

**Auditor downstream-check:** `.highlighted` is G2-only (no other usage in codebase). Dropping is safe. Browser back-button works as expected; analytics/Plausible doesn't capture fragments either way.

**Spec note (S-NEW-1):** spec at `design.md:2923` shows `?highlight=N` query-param shape. Option A deviates from spec; either update spec or accept the deviation as documented improvement.

### R-T2. Migration number annotations are factually wrong (NEW from audit)
**Source:** Final auditor (all three prior rounds saw the issue but didn't classify it as fixable)
**Evidence:** `015_search_vector_v3.py` already exists in this branch (`ls src/docket/migrations/` confirms; registered in `runner.py:30`). Migration 014 is reserved for Phase 4 (drop legacy `summary` column). Next free is **016**.

Three sites currently say "Migration 015 candidate":
1. `src/docket/web/admin.py:329` — escalate handler docstring (G2-introduced)
2. `src/docket/web/templates/admin/errors.html:14-15` — template comment (G2-introduced)
3. `src/docket/web/public.py:429` — inherited from F5 (not strictly G2 scope but flagged for hygiene)

**Fix:** update all three sites to say "Migration 016 candidate" (or "next available migration"). One-line each.

---

## Category 2 — SUGGESTED, accept in fix-up

### S1. Retry handler must clear `backfill_session_id` (B5 latency)
**Source:** Opus #1, confirmed by Sonnet
**File:** `src/docket/web/admin.py` (retry handler) and `src/docket/services/backfill_driver.py:81`
**Evidence:** B5's backfill driver requires `backfill_session_id IS NULL` to pick up an item. Retry sets `processing_status` to `pending` and resets `processing_attempts` to 0, but doesn't touch `backfill_session_id`. Latent bug: when B5 lands, retried items will silently fail to re-process.
**Fix:** add `backfill_session_id = NULL` to the UPDATE statement in the retry handler. One line.

### S2. Retry handler must clear `last_error_*` fields
**Source:** Opus #1
**Evidence:** Retry should look like a fresh attempt; stale error metadata on a `pending` row is misleading.
**Fix:** add `last_error_at = NULL`, `last_error_message = NULL` (whichever columns exist) to the same UPDATE. One line.

### S-NEW-2. Admin-precise empty-state copy (Sonnet → auditor)
**Source:** Sonnet, confirmed by auditor
**File:** `src/docket/web/templates/admin/data_debt.html` empty-state copy
**Evidence:** `data_debt.html` says "All extractable agenda content is up to date" (citizen-toned). `errors.html` correctly says "No items currently in `failed_permanent` state" (admin-toned). Inconsistent.
**Fix:** align `data_debt.html` to admin-precise tone, e.g., "No items in OCR queue (data_quality='ok' across all cities)."

### S3 (optional but cheap). Render `last_error_at` in `errors.html`
**Source:** Opus #2
**Evidence:** `last_error_at` is selected at `query.py:1968` but never rendered. Wasted query work + missing UX (admins want to know when failures happened).
**Fix:** add a "Last error" column to `errors.html`. Render as relative time ("3h ago") or absolute timestamp.

### S4 (optional but cheap). Trailing-slash consistency
**Source:** Opus #1
**Evidence:** `/admin/data-debt/` (with slash) vs `/admin/errors` (without). Flask's `strict_slashes=True` causes 308 redirects on mismatched URLs.
**Fix:** pick one shape and apply consistently. Either both with trailing slash or both without.

---

## Category 3 — SUGGESTED, defer with tracking

### Opus #2 SUGGESTED items that defer:
- Mobile-overflow on 6+ column tables
- Disabled-state on retry/escalate buttons during submission (double-click prevention)
- Confirmation prompt for escalate (terminal action)
- Visually distinguished retry vs escalate (warning color for escalate)
- Flash message rendering location (base template vs per-template `get_flashed_messages()`)
- Pagination consistency check (load-more vs numbered) across G1/G2/F2

### Opus #1 SUGGESTED items that defer:
- (Most of Opus #1's SUGGESTEDs are subsumed by S1/S2 above — the rest are NICE-TO-HAVE)

### From earlier protocol concerns:
- **CSRF (S6 from Opus #2):** project-wide gap, not G2-specific. `SESSION_COOKIE_SAMESITE = "Lax"` provides partial mitigation. Existing F2 council-CRUD precedent has same gap. File as separate roadmap item; G2 follows existing pattern.
- **Worker re-pickup latency:** when admin clicks retry, worker re-processes within cron interval (default 1 min for `ai_items`). No immediate-trigger needed for v1.

---

## Category 4 — NICE-TO-HAVE (declined)

7 items across the four reviews — including aria-labels on buttons, sticky retry/escalate distinction, table column right-alignment, sort indicators, and similar polish. All deferred.

---

## Decision-trace verifications (no action needed)

- **F5 regression:** all 44 F5 tests pass. `list_data_debt_items` refactor non-breaking; new `processing_attempts` projection is additive.
- **Auth-on-POST:** `@bp.before_request` hook checks `request.endpoint.startswith("admin.")` — fires before Flask dispatches handler. Anonymous POSTs to `/admin/errors/<id>/retry` redirected before handler runs.
- **JSONB merge correctness:** escalate handler uses `score_overrides || jsonb_build_object(...)` (concat). Existing keys preserved. Test asserts non-clobber at line 463-464 of `test_admin_queues.py`.
- **Atomic transactions:** retry/escalate handlers wrap UPDATE + audit-INSERT in `db_cursor()` context — psycopg2 commits on context exit, rolls back on exception. Verified atomic.
- **xfail removal:** `test_data_debt_returns_200_when_queue_page_lands` now passes (was xfail-strict). Asserts only `200`; no subtle HTML assertions.
- **G3 audit-table compat:** `processing_status_audit` row shape G2 writes is compatible with what G3's audit log viewer will read.
- **CSRF + SameSite:** `SESSION_COOKIE_SAMESITE = "Lax"` blocks form-submit cross-site POST. CSRF risk limited to specific attack vectors; v1 stance defensible.
- **Pre-existing flake (filed as task #48):** `tests/integration/test_calibration.py::test_query_c_returns_weeks_of_data` is date-sensitive due to `DATE_TRUNC('week', ...)` boundary. NOT a G2 regression — fails at `abb0a2a` HEAD too. Deselect when running suite. **Worth fixing in G3 or as a one-off** — the date-flake is a real bug in the G1 test fixture.

---

## What the user is being asked to verify

Per the F5 + G1 user-gate pattern, areas reviewers tend to under-cover:

1. **R-T1 Option A vs spec drift.** Auditor flagged S-NEW-1: spec at `design.md:2923` shows `?highlight=N` query-param shape. Option A deviates from spec. Either:
   - Accept the deviation (Option A is genuinely better — browser-native scroll, no JS, no CSS)
   - Update spec to fragment-based shape
   - Hybrid: route accepts both, all generators emit fragment

2. **R-T2 migration number.** Auditor caught a documentation-correctness issue all three prior rounds saw informationally. Worth confirming: do you want to fix all three sites (`admin.py:329`, `errors.html:14-15`, `public.py:429`) including the inherited F5 site? Or G2-scope only (skip `public.py:429`)?

3. **B5 latency (S1+S2).** One-line additions to retry handler. Trivial cost; defensive against B5 silent failures. Worth bundling.

4. **Empty-state copy alignment.** Admin-precise tone vs citizen-friendly tone — preference?

5. **Anything reviewers' angles structurally couldn't see.**

## Sign-off question

> Should the G2 fix-up loop apply BOTH REQUIREDs (R-T1 fragment-only via Sonnet's Option A, and R-T2 migration number correction across all three sites including the inherited F5 one) AND the three one-line SUGGESTED-accepts (S1 backfill_session_id clear, S2 last_error_* clear, S-NEW-2 admin-precise empty state copy) in a single commit, deferring everything else as labeled follow-ups?

Yes / no / further adjustments. Reflags welcome — auditor on standby for triage.
