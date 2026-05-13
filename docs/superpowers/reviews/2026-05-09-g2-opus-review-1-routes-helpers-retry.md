# G2 Review #1 — Routes + Helpers + Retry Semantics (Opus)

**Commit:** b2c053f
**Branch:** feat/impact-first-phase-2-track-3
**Reviewer angle:** Routes + service-layer helpers + retry/escalate semantics + audit integration

## Summary

G2's data path (admin.py routes, query.py helpers, retry/escalate handlers) is implemented to a high standard: atomic transactions, JSONB merge done correctly, parameterized SQL, defensive int parsing, audit integration via the existing migration-013 table. The 24 integration tests verify state mutations end-to-end (SELECT after POST), 405 enforcement, auth enforcement on POSTs, cross-city aggregation, and priority sort order. Test baseline holds: 1080 passed + 4 xfailed (with the documented G1 calibration deselect). Two SUGGESTED items emerged on lower-stack interactions that won't be wired up until B5 lands the v3 atomic process_item.

## REQUIRED

(none)

## SUGGESTED

1. **Retry handler does not clear `backfill_session_id`.** `src/docket/web/admin.py:290-298` flips status `failed_permanent` → `pending` and zeroes `processing_attempts` but leaves `backfill_session_id` untouched. The v3 backfill driver's pickup query (`src/docket/ai/backfill_driver.py:75-85`) requires `backfill_session_id IS NULL`, so a future item that the v3 pipeline (B5) flipped to `failed_permanent` would have its session_id still set, and an admin retry would silently fail to re-queue it. Today this is theoretical (no production code currently writes `failed_permanent`), but B5 will land that path and this stale session_id will become a footgun. Add a third assignment to the UPDATE: `, backfill_session_id = NULL`. One-line fix; preserves the audit row's witness of the actual prior state.

2. **Retry handler does not clear `last_error_message` / `last_error_at`.** Same UPDATE site. After a successful retry → recovery, the row will still carry the old failure-context fields, and the worker (when B5 lands) would either need to clear them on success or operators would see stale errors against `processing_status='completed'` rows. Cleaner to clear at the retry site so the row state is consistent. (Note: no current code reads `last_error_at` for decision-making, so this is a hygiene item, not a correctness bug.)

3. **Worker re-pickup latency is up to ~24h, and not actually wired today.** The cron `ai_items` task at `src/docket/worker/scheduler.py:50-55` runs daily at 07:00 Chicago, and it calls v2's `docket.ai.worker.run_once`, whose claim query (`src/docket/ai/worker.py:21-30`) uses `ai_prompt_version`, NOT `processing_status`. So a flip from `failed_permanent` → `pending` does NOT reach the v2 worker at all — until B5 atomic `process_item` is wired into the cron, retry is symbolic. This isn't a G2 defect (the spec/plan put B5 downstream), but the operator-facing flash "Item #N retry queued" implies an action that today is a no-op. Either (a) document this in the runbook, or (b) downgrade the flash text to "Item #N marked for retry — next worker pass picks it up after B5 lands." The first is fine for v1 since failed_permanent items don't currently exist in production.

4. **Trailing-slash inconsistency between sibling routes.** `/data-debt/` (`admin.py:187`) has trailing slash; `/errors` (`admin.py:233`) does not. Flask's default `strict_slashes=True` means `/admin/errors/` returns 404 and `/admin/data-debt` redirects 308 to `/admin/data-debt/`. Operators typing the URL will trip on this. Pick one shape (most other admin routes use no trailing slash on collection routes — `/members/` excepted). Cosmetic — won't block ship.

5. **`?highlight=N` CSS-only is sufficient for v1, but worth a single-line JS scrollIntoView at scroll height >50.** With the page-size of 50 and the highlighted row potentially being in position 49, the browser's anchor-fragment fallback (`#item-N`) doesn't fire on `?highlight=N` (different mechanism). Two options: (a) update the source-anchor button to use `?highlight=N#item-N` so the fragment-anchor scrolling works for free, or (b) add 4 lines of inline JS in the template `{% block scripts %}` that runs `document.getElementById('item-{{ highlight }}')?.scrollIntoView()` when the param is set. Option (a) is zero-JS and the cleanest fix.

6. **Escalate's `to_status` populating is conceptually awkward.** `admin.py:374-382` sets `to_status = from_status` because the audit table CHECK requires `to_status NOT NULL`. Functionally correct, but a future reader querying "all status transitions" will pull escalate rows where `from_status = to_status`. Consider adding a `WHERE from_status != to_status` filter on the conflict-resolution query or letting `to_status` be nullable for non-status-change actions. Schema-change scope, not v1 scope; flag as a follow-up.

## NICE-TO-HAVE

7. **Redundant `from flask import session` at `admin.py:29`.** Module-level import at line 7 already imports `session`. The local import inside `require_login` is dead. One-line removal.

8. **Both sort-order tests assert ordinal positions via `body.find()`.** Tests at `tests/integration/test_admin_queues.py:248-254` and `369-374` use `body.find("MARKER")` substring searches to compare positions. Works, but it's substring-fragile — if a marker title accidentally appears inside another row's HTML (e.g., a meeting title repeats it), the assertion can pass for the wrong reason. Lower-friction follow-up: parse the rendered HTML with a tiny regex over `<tr id="item-N">` to extract ordered IDs and assert against the expected ID sequence. Not blocking.

9. **`list_failed_permanent_items_all_cities` doesn't filter `data_quality_skipped`.** The WHERE clause is `processing_status = 'failed_permanent'` only — correct per decision #79. But once B5 lands, items can transition through `failed_permanent` → operator-retry → `pending`. A historical failed-and-recovered item would no longer surface here (correct). A second consideration: consider whether items at `cross_stage_conflict` (the third terminal-ish state per migration 013 line 31) belong on the errors queue too. Spec is silent; v1 scope says only `failed_permanent`. Flag for the spec author.

10. **Docstring claim vs. behavior on `list_failed_permanent_items_all_cities`.** `query.py:1942-1949` says: "Although decision #79 originally framed errors-queue ordering as 'significance-sorted,' priority is built from significance-driven heuristics (decision #31), so reusing the priority sort keeps behavior consistent across both admin queues." This is a reasonable interpretation but it's the implementer's call, not a literal read of decision #79. Worth documenting as a deliberate deviation in the review packet so the spec author can either bless it or push back.

## Implementer-flagged question responses

1. **`processing_status_audit` choice:** **APPROVED — better than the plan minimum.** Migration 013 line 206-217 defines the table with the exact columns the handlers need: `from_status`, `to_status`, `action TEXT`, `actor`, `actor_role` (CHECK accepts `'admin'`), `reason`, `payload JSONB`, `occurred_at`. Both handlers populate it correctly. The `idx_processing_status_audit_open_conflicts` partial index (line 274-277) filters on conflict-resolution actions — `'retry'` and `'escalate'` aren't in that filter, but that's fine because the index is for a different use case; the primary `idx_processing_status_audit_item` lookup-by-item index covers retry/escalate audit reads. Writing structured audit rows beats `current_app.logger.info` for forensics: every retry/escalate is queryable by item id with timestamps. The implementer's stronger choice should stay.

2. **`failed_permanent` retriability + worker re-pickup:** **PARTIALLY VERIFIED with one concrete gap.**
   - The partial index `idx_agenda_items_processing_status` (migration 013:221-223) excludes `completed` and `failed_permanent`, so a flipped `pending` row IS in the index. Good.
   - **BUT today nothing actually flips items into `failed_permanent`** — `grep -rn failed_permanent src/docket/` finds only enum/index definitions, route/template references, and ai/exceptions placeholders. The B5 v3 atomic `process_item` is the not-yet-built writer. So the queue is empty in production by code-flow, and any tests/manual ops using it fabricate the row.
   - **Concrete gap (SUGGESTED #1):** `backfill_session_id` is not cleared on retry, so once B5 lands the failure path the v3 backfill driver will skip retried items.
   - **Infinite-loop concern:** `processing_attempts` is reset to 0 on retry. No worker code today actually enforces a `processing_attempts` cap. Future B5 must use `processing_attempts >= MAX_ATTEMPTS` to flip into `failed_permanent`; if MAX is 3 and the underlying error is deterministic, retry → 3 retries → `failed_permanent` again. Bounded loop, not infinite. OK.
   - **Verdict:** Today retry is symbolic. Once B5 lands, item #1 in SUGGESTED becomes a hard requirement.

3. **Highlight UX (CSS-only vs scroll):** **CSS-only is sufficient for v1 with one tweak.** At 50 items per page and modest pixel height, a highlighted row at position 49 is just outside the typical viewport — admin would scroll. Easiest no-JS fix: change the source-anchor button at `templates/partials/source_anchor_button.html:128` from `?highlight={{ item.id }}` to `?highlight={{ item.id }}#item-{{ item.id }}` so the browser's native fragment-anchor scrolling kicks in. Pure CSS+URL fragment, no JS.

4. **Escalate flag JSONB stopgap + Migration 015 timing:** **Acceptable v1 stopgap. JSONB merge is correct.** `admin.py:355-356` does `merged = dict(existing_overrides) if existing_overrides else {}; merged["admin_escalated"] = True; merged["admin_escalated_by"] = actor` — preserves all other keys (like `final_significance`, Stage 2.5 floor data, future override keys). Test on line 463-464 verifies the merge by seeding `final_significance: 7`, escalating, and asserting both `admin_escalated == True` AND `final_significance == 7` survive. Migration 015 (renaming to `requires_manual_review BOOLEAN`) is appropriate Phase 2 follow-up scope, NOT G2 scope — a real column would index cheaply for "all escalated items" admin views, but G2 doesn't need such a view yet. The follow-up is clearly flagged in the docstring and commit message. **`015_search_vector_v3.py` already exists for a different purpose** — when this lands, the migration will need to be 016 or higher. Mention this in the follow-up.

## Out-of-scope observations (deferred to reviewer #2)

- Template rendering details: `templates/admin/data_debt.html` and `errors.html` UX choices, CSS-class additions in `tweaks.css` (lines 201+), accessibility, button styling, jargon-in-table-headers (e.g., `data_quality`, `processing_status` shown verbatim).
- Anonymous-POST flow on the auth side (whether 302-to-login is right vs. 401 vs. 403 — reviewer #2 verifies UI-side, I verified state did NOT mutate on auth-rejected POST at `tests/integration/test_admin_queues.py:493-513`).
- Sign-Out form placement in the queue templates.
- Flash-message styling.
- Escalated row visual distinction (the "Escalated?" column at `errors.html:94-96` simply says "yes" — visual signal could be richer).

## Verdict

LGTM with two SUGGESTED follow-ups (`backfill_session_id` clear + last_error_* clear) that become required at B5 time, not now. Six smaller suggestions and four nice-to-haves. No REQUIRED changes for ship.
