# G2 Final Audit — Opus 4.7

**Commit:** b2c053f
**Posture:** Final auditor pass before user gate. Three prior reviews incorporated.

## Top-line verdict

The existing R-T1 REQUIRED is correctly classified and fully covers the user-facing bug. I add **one new REQUIRED (R-T2)** that all three rounds missed: the `Migration 015 candidate` annotations in `admin.py:329`, `errors.html:14-15`, and (separately) `public.py:429` are **factually wrong** — `015_search_vector_v3.py` already exists in this branch (`src/docket/migrations/`), and 014 is reserved for Phase 4 to drop the legacy `summary` column (per CLAUDE.md). The next free number is **016**. This is a documentation defect that ships a misleading future-ticket signpost; it must be corrected before merge to avoid wasted lookup time when an implementer goes to claim 015 and finds it occupied. I also identify one cross-cutting **spec drift** finding (S-NEW): the spec at `docs/.../impact-first-refactor-design.md:2923` itself uses `?highlight=N` (query-param), so adopting Sonnet's Option A (fragment-only) is a deliberate deviation from the spec example. Either flag it in the commit message or use the hybrid `?highlight=N#item-N` shape Opus #1 endorsed.

## Re-verification of R-T1

- **R-T1 (?highlight=N half-implemented): CONFIRMED** — verified independently from source:
  - `admin.py:213-214` parses `offset` and `highlight` independently. **No coupling between them**: `offset` defaults to 0 from `request.args.get("offset")` and `list_data_debt_items` is called with `offset=offset` and `limit=51`. If `highlight=N` corresponds to an item at sort-position 60, the route still queries items 1–50 and the highlighted item is **not in the rendered HTML at all**.
  - `data_debt.html:76-77` applies `id="item-{{ it.id }}"` and `class="highlighted"` only to items **already rendered**. There is no offset-redirect logic.
  - `tweaks.css:224-226` defines `.queue-table tr.highlighted td { background: var(--accent-soft, #fff3e0); }`. The `--accent-soft` token at `styles.css:18` is `oklch(0.92 0.04 200)` — a **light teal-cyan, not orange**. Sonnet's `--accent-soft` token-mismatch is confirmed: the literal `#fff3e0` fallback never fires because `--accent-soft` is always defined; rendered color is teal, not orange. The fallback is dead code.
  - **Generation site:** verified `templates/partials/source_anchor_button.html:128` is the **only** call site emitting `?highlight=N` (`grep -rn "admin.data_debt"` returns three hits — two for `url_for('admin.data_debt')` without highlight, one for `url_for('admin.data_debt', highlight=item.id)` at line 128). Sonnet's "fix at one URL builder" is correct.
  - **Page-2+ silent no-op:** confirmed by code-trace. The route never tries to find `highlight` in the sort, never auto-paginates, never redirects. If `highlight=N` is past offset 50, the admin lands on offset=0 with **no visible highlight anywhere**. Sonnet's escalation to REQUIRED is correct.
  - **Test gap:** `test_admin_data_debt_highlight_query_param` (`tests/integration/test_admin_queues.py:259-272`) seeds exactly one item and asserts the class+id appear. It would still pass even if the page-2+ failure mode were the production reality. Implementer must add a "page 2+ → row visible" assertion when fixing.

## Downstream-effects audit

**a. R-T1 fragment vs query-param downstream.** No interactions found:
  - No analytics scripts (`grep` for `plausible|gtag|analytics|location.hash` in `src/docket/web/` returns nothing).
  - Browser `#item-N` fragment scrolls the row into view natively. Browser back-button after viewing a highlighted item **re-fires** the fragment scroll on return — admin-friendly behavior, not a regression.
  - Flask URL routing is fragment-agnostic (fragments are client-side only; never sent to the server). `url_for(...)` does not natively append `#fragment` — implementer will use `url_for(...) ~ "#item-" ~ item.id|string` Jinja string concat (Sonnet's Option A wording is correct).
  - One subtle issue: if the admin clicks a "Load more" link or any other admin nav, the fragment is dropped. That's fine — fragment-based highlight is a drive-by signal, not state.

**b. R-T1 + S4 simplification confirmation.** `.highlighted` is **G2-only**. Grep results:
```
src/docket/web/templates/admin/data_debt.html:77
src/docket/web/static/tweaks.css:205, 224
tests/integration/test_admin_queues.py:269, 272
```
Confirmed safe to drop the `.highlighted` CSS class entirely if Option A is adopted. The visual affordance question: with `:target { background: ... }` (browser-native fragment styling) the highlighted row would still get a color cue **AND** scroll into view automatically. So Option A delivers strictly more than the current implementation. Sonnet's elegant cross-finding insight is correct: one change closes both R-T1 and S4.

**c. Migration 015 → actual number.** `ls src/docket/migrations/` shows `015_search_vector_v3.py` is **already in the branch** (registered in `runner.py` at line 30). 014 is **reserved** for Phase 4 (drops legacy `summary` column per CLAUDE.md). Next free number is **016**. Three places state "Migration 015 candidate" incorrectly:
  1. `src/docket/web/admin.py:329` (escalate handler docstring)
  2. `src/docket/web/templates/admin/errors.html:14-15` (template comment)
  3. `src/docket/web/public.py:429` — **inherited from F5**, separate concern (`municipalities.admin_email`)

The G2 commit is responsible for #1 and #2. #3 is pre-existing F5 debt that should also be corrected for consistency, but that's not strictly G2 scope.

**d. B5 latency latent bug — REQUIRED or SUGGESTED?** Recommendation: **SUGGESTED-defer**, with a tagged follow-up issue.
  - Cost of fixing now: trivial (one-line `, backfill_session_id = NULL` in the UPDATE at `admin.py:290-298`, matching `, last_error_message = NULL, last_error_at = NULL`).
  - Cost of NOT fixing now: zero today (no code writes `failed_permanent`); becomes a hard bug only when B5 lands.
  - **My recommendation:** add the one-line fix now. The fix is defensive, the cost is one line, and it eliminates B5 integration debt. Putting it in the SAME commit lets B5 ship without coupling. But: this is a judgment call I won't escalate to REQUIRED — Opus #1 and Sonnet both rated SUGGESTED, the user-gate question should ask whether to fix-up-now or defer-to-B5.

**e. F5 regressions in public template.** Verified clean:
  - F5's `templates/data_debt.html` and `templates/rss/_macros.xml.j2` reference NONE of the new projection columns G2 added (`processing_attempts`, `last_error_message`, `score_overrides`, `last_error_at`). `grep` confirms zero hits.
  - The query helper `list_data_debt_items` extension to accept `city_id=None` is additive; the WHERE clause `m.id = %s` is conditionally inserted only when `city_id is not None`. F5's call passes `municipality["id"]` (always int) → behavior unchanged.
  - I ran `pytest tests/integration/test_f5_data_debt.py tests/integration/test_admin_queues.py -q`: **68 passed**. Also ran the full suite with the documented G1 deselect: **1080 passed, 2 skipped, 1 deselected, 4 xfailed** — Sonnet's baseline holds.

**f. G1 audit-table compat for G3.** Schema verified at `migrations/013_impact_first_refactor.py:206-217`:
```
id, agenda_item_id, from_status, to_status NOT NULL, action TEXT NOT NULL,
actor, actor_role CHECK ('admin','cron','on_write'), reason, payload JSONB, occurred_at
```
G2's writes:
- Retry: `from_status=<actual>, to_status='pending', action='retry', actor=<session>, actor_role='admin', reason=<text>, payload=NULL`.
- Escalate: `from_status=<actual>, to_status=<actual> (same)`, `action='escalate', actor_role='admin', reason=<text>, payload={admin_escalated: true}`.

Both shapes are schema-valid. **G3 will be able to read both** with a generic SELECT — no schema migration needed for G3. One caveat (already flagged by Opus #1 SUGGESTED #6): escalate writes `from_status=to_status`, which a naive G3 query that filters on `from_status != to_status` would skip. G3 should use `action` for filtering, not status delta. Document this when G3 lands.

**Atomicity confirmed:** retry's three writes (SELECT for from_status + UPDATE + INSERT audit) are inside a single `with db() as conn:` block; `db()` commits on success and rolls back on error (`src/docket/db.py:24-31`). Same for escalate's four writes (SELECT + dict-merge + UPDATE + INSERT audit). Atomic.

**g. xfail removal verification.** `tests/unit/test_source_anchor.py:861-876` verified:
  - Test name `test_data_debt_returns_200_when_queue_page_lands` no longer has `@pytest.mark.xfail`.
  - The body asserts only `resp.status_code == 200` after seeding `sess["admin_user"] = "tester"` and GET `/admin/data-debt/?highlight=42`. No subtle HTML assertions.
  - No `pytest.skip` or `pytestmark` magic in `test_source_anchor.py` that would silently skip it. The other 3 tests in `TestForcingFunctionsForE4Cleanups` retain xfail (as intended by the implementer).
  - Test passes in the run (xfailed=4 in the full-suite run, the 4 unrelated A8/timestamp_seconds tests).

## New findings (beyond the three rounds)

### REQUIRED (added or upgraded)

**R-T2 (NEW): "Migration 015 candidate" annotations are factually wrong.** `015_search_vector_v3.py` already exists in this branch (registered in `runner.py:30`). Future column for `requires_manual_review BOOLEAN` would be **016** (014 is reserved for Phase 4 dropping `summary`). Two G2-introduced sites must be corrected:
- `src/docket/web/admin.py:329` — escalate handler docstring
- `src/docket/web/templates/admin/errors.html:14-15` — template comment

These are misleading future-ticket signposts that would waste an implementer's time when claiming the migration. One-line edits, no test changes. Categorizing REQUIRED because it's a documentation correctness defect that ships in code comments AND the public-facing template comment block. (Opus #1 noted "015 already exists for a different purpose — when this lands, the migration will need to be 016 or higher" but did NOT escalate to a fix; Opus #2 mentioned the comment as out-of-scope deferred to reviewer #1; Sonnet didn't address it. All three rounds left this at "the implementer should fix" without classifying severity.)

A separate F5-inherited site at `src/docket/web/public.py:429` ("Migration 015 candidate" referring to `municipalities.admin_email`) has the same error but is **not G2 scope**. Flag as an F5 follow-up; do not block G2 ship on it.

### SUGGESTED (added)

**S-NEW-1 (this audit): Spec/code drift on `?highlight=N` shape.** Spec at `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md:2923` itself uses `url_for('admin.data_debt', highlight=item.id)` — query-param shape. Adopting Sonnet's Option A (fragment-only) deviates from the spec example. Two acceptable resolutions:
- (a) Update the spec to reflect Option A (it should: the spec's claim that "browser handles ... natively" at line 2931-2932 is wrong for query params), OR
- (b) Use the hybrid shape `url_for('admin.data_debt') ~ "?highlight=" ~ item.id|string ~ "#item-" ~ item.id|string` — keeps the spec faithful AND adds fragment-anchored scrolling. Opus #1 endorsed this hybrid in SUGGESTED #5.

I lean (a) for cleanliness, but the implementer should mention the deviation in the fix-up commit message either way. Categorize SUGGESTED — it's a docs/spec consistency note, not a correctness defect once R-T1 is fixed.

**S-NEW-2 (this audit): Empty-state copy alignment.** Confirming Sonnet's S-NEW-3: `data_debt.html:55-57` says "All extractable agenda content is up to date" (citizen-toned) while `errors.html:58` says "No items currently in `failed_permanent` state" (admin-precise). The OCR queue is admin-only (verified by `before_request` hook covering `admin.*`). Recommend aligning to the **admin-precise** form: rewrite `data_debt.html` empty state to e.g. "No items in `data_debt_priority` queue (`data_quality != 'ok'` or `processing_status = 'failed_permanent'`)." Admins read enums fluently and the citizen register on an admin page is misleading.

### Findings to downgrade or refute

**Sonnet's S4 ("--accent-soft renders teal not orange"): downgrade to MOOT after R-T1 fix (Option A).** If `.highlighted` is dropped entirely (per Sonnet's elegant cross-finding insight), the token mismatch ceases to exist. Implementer should not re-introduce `.highlighted` styling — use `:target { background: <fresh-token>; }` and pick the semantically appropriate color in one decision. Refute Sonnet's "after Option A, S4 is moot" was correctly stated; I'm reaffirming. Implementer should NOT keep `.highlighted` "just in case."

**Opus #1 SUGGESTED #6 (escalate `to_status = from_status` weirdness): keep as deferred follow-up.** Schema-change scope. The audit table accepts the shape; G3 query authors will key off `action`, not status delta. No need to escalate.

**Opus #2 SUGGESTEDs on UX/accessibility (aria-labels, mobile responsive, heading hierarchy, confirm-on-escalate, double-submit guard, `last_error_at` not rendered, pagination back-link, `escalated?` cell badge): defer.** All real, all minor, all post-ship-able. Admin surface, low traffic, blast radius bounded.

**CSRF stance (all three rounds confirmed pre-existing project-wide gap): defensible for v1.** With `SESSION_COOKIE_SAMESITE = "Lax"` (verified at `web/__init__.py:42`), cross-site form-POSTs from `attacker.com` to `/admin/errors/<id>/retry` are blocked by the browser before the request fires. The remaining CSRF surface is link-clicking attacks (only against GET endpoints — none of G2's mutation endpoints accept GET; 405 enforced and tested). G2 is consistent with the F2 council-CRUD precedent and inherits the same posture. Project-wide CSRF token retrofit is the correct long-term fix but it's not G2's to introduce alone.

## Recommended fix-up scope (final)

**Aggregate REQUIRED:**
1. **R-T1**: Adopt Sonnet's Option A. Change `templates/partials/source_anchor_button.html:128` to emit `url_for('admin.data_debt') ~ "#item-" ~ item.id|string`. Drop `?highlight=N` parsing from `admin.py:214` and the `highlight` template variable from `data_debt.html:77`. Replace `.queue-table tr.highlighted td` CSS with `.queue-table tr:target td { background: <warm token>; }` (pick `var(--paper-3)` or a literal warm color — `--accent-soft` is teal). Update test `test_admin_data_debt_highlight_query_param` to assert fragment in the source-anchor href and the row's `id="item-N"` is present (drop `class="highlighted"` assertion).
2. **R-T2 (NEW)**: Correct the migration number in two G2-introduced comments — `admin.py:329` ("Migration 015 candidate" → "Migration 016 candidate") and `errors.html:14-15` (same). One-line edits each, no test changes. (Optionally also fix the inherited F5 site at `public.py:429` for cross-cutting hygiene; flag it separately if scope is strict.)

**Aggregate SUGGESTED-accept (one-line, do now):**
1. **Opus #1 S1**: `retry` handler clears `backfill_session_id`. Add `, backfill_session_id = NULL` to the UPDATE at `admin.py:293-294`. Defensive against B5; cost negligible.
2. **Opus #1 S2**: `retry` handler clears `last_error_message` and `last_error_at`. Same UPDATE site. Hygiene.
3. **S-NEW-2 (this audit)**: Align `data_debt.html` empty-state copy to admin-precise tone matching `errors.html`. ~3 line edit.

**Aggregate SUGGESTED-defer (issue/follow-up tickets):**
1. **Opus #1 S3**: Worker re-pickup latency / flash-text accuracy. Runbook note for now.
2. **Opus #1 S4**: `/data-debt/` vs `/errors` trailing-slash inconsistency. Pick one shape post-ship.
3. **Opus #1 S6**: Escalate `from_status=to_status` audit row shape. Schema-change scope.
4. **Opus #2 SUGGESTEDs**: `last_error_at` not rendered, mobile responsive, heading hierarchy, aria-labels on Retry/Escalate, confirm-on-escalate, double-submit guard, escalated? cell badge, pagination back-link, queue-flash category styling. All admin-surface UX polish, post-ship.
5. **S-NEW-1 (this audit)**: Spec drift on `?highlight=N`. Update spec or note deviation in commit.

**NICE-TO-HAVE:** 7 (Opus #1 NTH #7-#10, Opus #2 NTH block, Sonnet's N-NEW-1).

## Sign-off question for the user

**Should the G2 fix-up loop apply BOTH REQUIREDs (R-T1 fragment-only via Sonnet's Option A, and R-T2 migration number correction) AND the three one-line SUGGESTED-accepts (S1 backfill_session_id clear, S2 last_error_* clear, S-NEW-2 admin-precise empty state copy) in a single commit, deferring everything else as labeled follow-ups?**
