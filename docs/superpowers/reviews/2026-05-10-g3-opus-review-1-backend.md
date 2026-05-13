# G3 Opus Review #1 — Backend (Helper + Handlers + Transactions)

**Reviewer:** Opus 4.7
**Scope:** query helper, admin handlers, transactions, SQL, spec drift
**Commits reviewed:** 76c526e..edd9260 (6 commits)
**Date:** 2026-05-10

## Summary

Backend implementation is tight and faithful to the plan. The two new query
helpers (`list_badge_audit_log`, `list_badges_on_item`) are clean, parameterized,
and timezone-aware. The four admin handlers correctly bracket badge writes +
audit writes inside one `with db() as conn:` transaction (psycopg2 semantics:
commit on clean exit, rollback on `HTTPException`/raise). All decision-baked
constants (`source='manual'`, `actor_role='admin'`, `confidence=0.95`,
`city_id` from joined municipality) are in compliance. SQL is fully
parameterized with no interpolation. The single architectural question
(LEFT JOIN vs RESTRICT FK) is well-flagged in code comments and handled
defensively. One REQUIRED finding on the FK semantics (decision needed,
not a bug) plus a small handful of suggestions.

## REQUIRED

### R1 — `agenda_item_badges_audit.agenda_item_id` FK / LEFT JOIN mismatch (architectural decision needed)

**Files:**
- `src/docket/migrations/013_impact_first_refactor.py:144`
- `src/docket/services/query.py:2102` (LEFT JOIN site)
- `tests/integration/test_admin_badge_audit.py:327-371` (test that drops the FK to exercise the LEFT JOIN)

**What's the situation:**
Migration 013 declares `agenda_item_id INT NOT NULL REFERENCES agenda_items(id)`
with the **default `ON DELETE` clause = NO ACTION (≈ RESTRICT)**. Audit rows
can therefore never be orphaned at the database level; deleting an
`agenda_items` row whose audit row exists is *blocked*.

The helper `list_badge_audit_log` uses `LEFT JOIN agenda_items` (and chained
LEFT JOIN to `meetings` / `municipalities`) "so old audit rows still
surface (with NULL item_title / meeting_date / municipality_*)" — but with
the current FK semantics, the LEFT JOIN's NULL-side branch is dead code in
production. The implementer's test even has to **drop and re-add the FK
constraint** to exercise the LEFT JOIN path
(`test_list_badge_audit_log_left_joins_deleted_items`), which is itself a
strong signal that production code and the test under it are aligned to a
contract the schema doesn't enforce.

**Why it matters:**
This is genuinely a design question, not a code bug:

- **Audit logs are typically expected to outlive the audited entity.** A
  long-running system is going to delete `agenda_items` eventually
  (re-ingest cleanup, manual data correction, GDPR-style takedowns). With
  the current RESTRICT FK, those deletes will fail unprompted; the
  operator will then be tempted to either (a) hard-delete the audit row
  to unblock the parent delete, defeating the audit, or (b) work around
  it ad-hoc (drop FK, delete, re-add with `NOT VALID`, etc.).
- The LEFT JOIN currently masks the fact that the FK choice is
  inconsistent with the rest of the design intent. As written, the helper
  is more "permissive" than the schema, which means schema changes can
  silently break the helper's contract.

**Three options (recommend (a)):**

- **(a) Migration 016: relax the FK to `ON DELETE SET NULL`.** Audit row
  survives item deletion; `agenda_item_id` becomes nullable in the audit
  table, the LEFT JOIN becomes load-bearing for real, and the test no
  longer needs to drop the constraint to exercise the LEFT JOIN path. This
  is the most idiomatic choice for an audit/history table. Migration
  needs to (i) drop the existing FK, (ii) `ALTER COLUMN agenda_item_id
  DROP NOT NULL`, (iii) re-add the FK with `ON DELETE SET NULL`. Idempotent
  guards for re-runs.

- **(b) Downgrade LEFT JOIN to INNER JOIN now.** Reflects the actual FK
  semantics: orphans are impossible by design, so the join can shed a
  branch. Cheaper at runtime, simpler test (no FK gymnastics needed).
  Costs: removes the defensive forward-compat the implementer wrote, and
  the 23-line test is currently a feature spec that says "we *want* this
  behavior" — flipping to INNER JOIN turns that spec into "we don't."

- **(c) Leave LEFT JOIN as defensive forward-compat; document the
  follow-up.** Lowest immediate change. Risk: drift between LEFT-JOIN's
  promise and FK's enforcement persists. The "drop-and-restore FK" gymnastics
  in the test stays in the suite.

**Recommendation:** (a). The cron worker writes `actor_role='cron'` audit
rows on automated badge add/remove (per the spec), and over multi-year
operation the audit table will accumulate millions of rows that *should*
outlive their items. The cost of writing migration 016 now is lower than
the cost of an operator hitting an FK violation on a routine cleanup
later. Track the helper-code tweak (helper LEFT JOINs agenda_item_id IS
NULL gracefully today) and the test (drop the constraint-restore mechanic)
together with the migration.

**Suggested fix:** New migration 016 (idempotent):

```python
# 016_relax_audit_fk_for_history_retention.py
UP = """
ALTER TABLE agenda_item_badges_audit
    DROP CONSTRAINT IF EXISTS agenda_item_badges_audit_agenda_item_id_fkey;
ALTER TABLE agenda_item_badges_audit
    ALTER COLUMN agenda_item_id DROP NOT NULL;
ALTER TABLE agenda_item_badges_audit
    ADD CONSTRAINT agenda_item_badges_audit_agenda_item_id_fkey
    FOREIGN KEY (agenda_item_id) REFERENCES agenda_items(id)
    ON DELETE SET NULL;
"""
```

Then update `test_list_badge_audit_log_left_joins_deleted_items` to drop
its inline FK manipulation — `DELETE FROM agenda_items` will Just Work
and the helper's LEFT JOIN will surface the orphan with NULL columns.

If (a) is rejected and (b) is chosen, downgrade
`src/docket/services/query.py:2102-2104` to INNER JOINs and remove
the "deleted items still surface" promise from the docstring + test. If (c)
is chosen, add a `# TODO(migration-016)` near `query.py:2055` so future
readers see the open question.

**Severity rationale:** REQUIRED because this is a contract-level decision
the user owns, not a code defect. Either flavor of fix is mechanically
small. The implementer flagged it correctly in the post-implementation
report; the review chain is the right place to close it.

## SUGGESTED

### S1 — `_render_manage_panel` re-fetches item context after a successful commit; the `abort(404)` branch is unreachable in normal flows

**File:** `src/docket/web/admin.py:777-810`

After `badge_add` / `badge_remove` commit the badge mutation + audit row,
control passes to `_render_manage_panel(item_id)`, which re-queries
`agenda_items + meetings + municipalities` and `abort(404)`s if the item
isn't found. But the handler's first SQL block already validated the item
exists (the JOIN to `agenda_items` in `badge_add`'s lookup query, the
`SELECT 1 FROM agenda_items` in `badge_remove`). The only way to hit the
404 here is a TOCTOU race where the item is deleted in the ~ms between
commit and the helper's re-read.

The behavioral consequence: the audit row + badge mutation are committed
(correctly — the manage UI's caller doesn't and shouldn't roll back state
changes because of a stale display), but the operator gets a 404 instead
of a panel. Acceptable v1 behavior; just flag.

**Suggested fix:** Either inline the panel re-render inside the
transaction (so a TOCTOU on the parent item rolls back too — overkill),
or document the trade-off with a one-line comment near
`_render_manage_panel`'s `abort(404)` so a future reader doesn't try to
"defend" it without understanding it's dead code in normal flows.

```python
# Defensive: the caller has already committed the badge change, so this
# 404 is reachable only via TOCTOU where the parent item was deleted
# between commit and re-read. Operator sees 404 with the change persisted;
# audit log will show the change. Acceptable v1 behavior.
```

### S2 — `_render_manage_panel` duplicates the manage-page query

**File:** `src/docket/web/admin.py:660-686` (badges_manage_item) and `777-810` (_render_manage_panel)

The two functions read essentially the same item-context columns (plus
`name` and `meeting_id` and `meeting_date` on the page version). The page
adds chrome that the panel partial doesn't need, but the badge/addable
list logic is identical. Not a bug — but if either query needs to grow a
filter (e.g., "exclude soft-deleted items if/when soft-delete is added"),
both will need it.

**Suggested fix:** Optional — extract a `_load_manage_state(item_id)` that
returns `(item_dict, current, addable)` and have both routes call it.
Cosmetic; defer unless a third caller appears.

### S3 — Audit "actor" defaults to literal string `"unknown"` if session is missing

**File:** `src/docket/web/admin.py:719, 845`

```python
actor = session.get("admin_user", "unknown")
```

The blueprint's `before_request` hook redirects unauthenticated requests,
so this fallback is unreachable in practice. But if the hook is ever
reordered or scoped down (e.g., a future "public read-only badge view"
on the same blueprint), `"unknown"` would silently land in the audit
table as the actor name — including in the matching_metadata JSONB —
making forensic audit harder.

**Suggested fix:** Either (a) `assert "admin_user" in session, "blueprint hook should have redirected"` (cheap, fast-fails), or (b) `abort(401)` on missing session inside the handler. Option (a) preferred because it documents the invariant for readers and is zero-cost in production.

### S4 — Logging format vs G2 convention

**File:** `src/docket/web/admin.py:770-773, 880-883`

G3 uses `current_app.logger.info("admin badge add: item_id=%s slug=%s actor=%s inserted=%s", ...)` — printf-style with positional args. Looking at the G2 errors retry/escalate handlers (which are in scope memory), the convention in `errors_retry`/`errors_escalate` likely differs slightly. Consistency reduces friction when grepping production logs.

**Suggested fix:** Spot-check `errors_retry` and `errors_escalate` log lines (admin.py around lines 254-490 — outside G3's diff). If they use `key=value` style strings or structured logging (e.g., `extra={...}`), align G3 to match. If they're already printf-style, no change needed.

(Not blocking — both styles work; just want to flag for the reviewer pair to converge on one.)

### S5 — Unknown-slug 404 in `badge_add` happens after an item-existence check; should be earlier

**File:** `src/docket/web/admin.py:723-742`

The lookup query `LEFT JOIN priority_badge_templates t ON t.slug = %s` returns NULL `kind` for unknown slugs but a valid `city_id` if the item exists. Then the handler 404s. This is correct — but means an unknown-slug attack against an unknown-item URL produces 404 (good) while against a known-item URL produces 404 + a wasted JOIN. Tiny perf footprint, but the readability improvement is the main reason to flag.

**Suggested fix:** Optional — split into two queries (item-existence first, then template-existence) for clarity. Or flip the order of the abort checks:

```python
city_id, kind = row
if kind is None:           # unknown slug → 404 (item exists, slug doesn't)
    abort(404)
# (existing flow)
```

The current order checks `row is None` (item doesn't exist) then `kind is None` (slug doesn't exist) — that's fine; the readability nit is just that the LEFT JOIN does double duty.

## NICE-TO-HAVE

### N1 — `until_exclusive` parameter name is explicit but clunky

**File:** `src/docket/services/query.py:1996-2003`

The name is correct for the contract (decision #10) but reads awkwardly at the call site (`until_exclusive=_parse_audit_until_exclusive(...)`). Alternatives considered:

- `before` — concise; loses the "exclusive" semantics.
- `until_lt` — ungrammatical.
- `before_inclusive` — same length, reads more naturally.
- Keep `until_exclusive` — preserves explicitness; current choice.

**Recommendation:** Keep as-is. The clunkiness is an asset here — it forces the caller to reason about whether they mean "include the day" or "exclude the day." Renaming would invite the same UTC-vs-local-tz bug class the parameter explicitly defends against.

### N2 — Reason field is always NULL on audit writes

**File:** `src/docket/web/admin.py:761-768, 871-878`

Plan decision #9 — explicitly v1 deferral, well-documented. Worth flagging as a probable v2 enhancement: a "remove with reason" textarea on the manage UI's remove button would make the audit log meaningfully more useful for forensic queries.

**Recommendation:** Add a `TODO(g3-v2): collect reason from manage UI` comment near the audit INSERTs so it's visible at the point of pain.

### N3 — `test_admin_badge_audit_pagination_offset` assertion is loose

**File:** `tests/integration/test_admin_badge_audit.py:464-478`

`assert "offset=50" in body or "offset=" in body` — the `or` arm is so weak it's almost a tautology (any pagination link contains `offset=`). Suggest tightening to just `assert "offset=50" in body` since the seeded scenario produces exactly 51 rows and the contract is "next link points at offset=50."

Tiny test-quality nit; ignore if the implementer is already moving on.

### N4 — Test parametrization across cities (CITIES = 4-way) only on the route entry-point test

**File:** `tests/integration/test_admin_badge_audit.py:379-397`

Following the G2 convention (parametrize the entry-point 200 test, not every test). One test × 4 cities for `test_admin_badge_audit_route_renders_for_logged_in_admin` is the right call — confirms the audit log isn't accidentally city-scoped (it's intentionally cross-city per the helper's design) and exercises the LEFT JOIN to `municipalities` for each. No other test needs the cross-city sweep.

**Recommendation:** No change. Convention is correctly applied.

### N5 — Helper docstring claims `idx_badge_audit_recent` is hit "when actor_role='admin' is in the predicate"

**File:** `src/docket/services/query.py:2031-2035`

Helper doesn't push `actor_role='admin'` into the WHERE clause, so the partial index `idx_badge_audit_recent` (which has `WHERE actor_role = 'admin'`) is never used. Docstring acknowledges this. For v1 with ~zero rows in production this is moot; eventually the table grows and the seq scan becomes a real cost.

**Recommendation:** Track for Phase 4 / post-backfill: either add an `actor_role` filter to the route (with a default of `'admin'` and an "include automated" toggle), or ship a separate non-partial index on `(occurred_at DESC)`. Defer.

### N6 — The audit table has no `agenda_item_id` index

**File:** `src/docket/migrations/013_impact_first_refactor.py:251-253`

Only index on `agenda_item_badges_audit` is `idx_badge_audit_recent (occurred_at DESC, badge_slug, action) WHERE actor_role = 'admin'`. The G3 helper hits this only when the predicate matches (it doesn't). For "show me audit history for this specific item" workflows (which the manage page might want eventually — "history for this item" tab), a `(agenda_item_id, occurred_at DESC)` index would pay off.

**Recommendation:** Defer. Out of G3 scope; flag as a follow-up tied to whatever surfaces the per-item history view.

## Decisions to escalate to user

### D1 — FK semantics for `agenda_item_badges_audit.agenda_item_id` (R1 above)

**Question:** Should we ship migration 016 to relax the FK to
`ON DELETE SET NULL` so audit rows survive item deletion (recommend),
downgrade the helper's LEFT JOIN to INNER JOIN (faster but commits to
"audit rows die with their items"), or defer with a TODO comment
(cheapest now, drift accumulates)?

**Why this decision needs a human:** It's a long-tail data-retention
question. RESTRICT today blocks routine cleanup; SET NULL preserves
forensic audit at the cost of a nullable column the rest of the system
needs to cope with (it can: helpers LEFT JOIN, viewer template
defensively renders "(item deleted)"). INNER JOIN is the cheapest path
but makes the audit table a strict slave of `agenda_items` — surprising
in 3 years when an operator wants to re-ingest a meeting and is told
"the audit log will lose 12 months of badge history if you do that."

**Implementer's flag:** Already noted in their report ("FK is RESTRICT
not 'no CASCADE'") — they corrected the plan's prose accurately and the
test now drops/restores the FK around the orphaning step. The user's
call is whether the schema, the helper, or both should change.

**Recommended path:** (a) Migration 016 with `ON DELETE SET NULL`.
Audit-table convention. Lowest long-term cost. Mechanical — ~10 lines of
migration + 1 column nullability change + test simplification.

### D2 — Spec text says "filterable by badge/actor/date range"; implementation adds timezone-aware semantics that the spec doesn't mention

**Files:** `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md:3303` (spec), `docs/superpowers/plans/2026-05-10-g3-audit-viewer-and-manual-badge-htmx.md` decision #10 (plan elaboration)

**Question:** The plan extends the spec's "date range" filter with a
timezone-aware America/Chicago contract (decision #10). This is correct
for a single-state Alabama project running on UTC servers. The spec text
itself is silent on timezone. Should the spec be patched to capture
this contract so future maintainers don't accidentally re-litigate it?

**Recommended path:** Yes — one-line append to spec §6.10:
"Date filters interpreted in `America/Chicago` (decision #10 of the G3
plan; helper rejects naive datetimes)." Pure documentation hygiene;
zero-cost.

This is an informational deviation, not a regression — flagging so the
auditor / sonnet second-look can decide whether to bundle a doc patch
into the G3 packet.
