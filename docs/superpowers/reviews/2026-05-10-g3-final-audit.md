# G3 Final Audit — Opus 4.7

**Auditor:** Opus 4.7 (fourth read)
**Date:** 2026-05-10
**Commits reviewed:** 76c526e..edd9260 (6 commits)

## Summary

The prior three reviewers (two parallel Opus + one Sonnet 4.6) landed it.
Backend is correct, frontend is clean, auth is closed, R1 is well-flagged,
and Sonnet's DC1-DC3 elevations are accurate. This auditor pass adds two
small documentation-correctness finds (A1, A2) in the same vein as G2's
auditor pattern, plus one signpost correction the prior chain missed:
the migration runner has a deliberately reserved gap at slot 014 (Phase 4
will use it to drop legacy `summary`), which means Sonnet's "next
available is 016" framing for DC1 is right but underspecified — the
collision actually pulls in three slots, not two.

## R1 verification (FK / LEFT JOIN)

**Read from source independently:**

- **Migration 013, line 142-151** declares `agenda_item_badges_audit` with
  `agenda_item_id INT NOT NULL REFERENCES agenda_items(id)` — **no `ON DELETE`
  clause**. PostgreSQL default is `NO ACTION`, which (with the FK not deferred)
  is functionally `RESTRICT` at statement end. Confirmed.
- **Helper at `src/docket/services/query.py:2055-2058`** docstring promises:
  *"the audit table's `agenda_item_id` FK to `agenda_items` has no
  `ON DELETE CASCADE`, so audit rows live forever even if the item is
  deleted. Use a LEFT JOIN so old audit rows still surface."* The
  helper SQL at `query.py:2102-2104` indeed uses three chained `LEFT JOIN`s.
  But the docstring's claim — "audit rows live forever even if the item is
  deleted" — is **factually wrong against the current schema**. The default
  `NO ACTION`/RESTRICT FK *blocks* the parent delete; audit rows don't
  outlive their items, the items can't be deleted while audit rows exist.
- **Test at `tests/integration/test_admin_badge_audit.py:327-371`** has to
  `ALTER TABLE ... DROP CONSTRAINT` before `DELETE FROM agenda_items` and
  then re-`ADD CONSTRAINT` afterward. The test docstring at lines 328-336
  acknowledges this is a deviation from plan and frames the LEFT JOIN as
  "defensive code in case a future migration relaxes the FK."

**Verdict:** Agree with Opus 1 + Sonnet. The schema, the helper, and the
test are aligned to three different contracts. **Recommend option (a) —
Migration 016 with `ON DELETE SET NULL`.** The FK gymnastics in the test
is a strong signal that the implementer wrote the helper for a future
state that hasn't shipped; bringing the schema along is cleaner than
walking the helper back.

**Concrete migration body** (idempotent, safe to re-run):

```sql
-- 016_relax_audit_fk_for_history_retention.py UP

-- Drop the existing FK constraint (NO ACTION semantics).
ALTER TABLE agenda_item_badges_audit
    DROP CONSTRAINT IF EXISTS agenda_item_badges_audit_agenda_item_id_fkey;

-- Allow orphans: agenda_item_id becomes nullable for survived audit rows.
ALTER TABLE agenda_item_badges_audit
    ALTER COLUMN agenda_item_id DROP NOT NULL;

-- Re-add the FK with SET NULL semantics so deleting the parent
-- nulls the FK rather than blocking the delete.
ALTER TABLE agenda_item_badges_audit
    ADD CONSTRAINT agenda_item_badges_audit_agenda_item_id_fkey
    FOREIGN KEY (agenda_item_id) REFERENCES agenda_items(id)
    ON DELETE SET NULL;
```

**DOWN** is mechanical (re-add NOT NULL + RESTRICT FK), but production
will already have NULL-id orphan rows post-promotion, so the DOWN should
either DELETE orphans or refuse to run. Mark DOWN as
`raise NotImplementedError("Forward-only: NULL audit rows accumulated post-016")`
and trust the Phase 1 backup tag for emergency recovery — same pattern
the project uses for migration 011 (drop deprecated columns).

**After migration lands, simplify the test:** delete lines 347-353
(constraint drop) and 361-371 (constraint restore). Replace with a bare
`cur.execute("DELETE FROM agenda_items WHERE id = %s", (iid,))` followed
by the existing assertions. The LEFT JOIN becomes load-bearing and the
docstring at `query.py:2055-2058` (with a small word-fix — see A1)
becomes accurate.

## DC1-DC3 verification

### DC1 — Migration 016 slot collision

**Verified.** `src/docket/web/admin.py:331` reads exactly what Sonnet
quotes: *"Migration 016 candidate (next available migration slot): add a
dedicated `requires_manual_review BOOLEAN` column on `agenda_items`."*
The G3 appends pushed the comment from its original location, but it's
still in the `errors_escalate` handler block (line 331 confirmed via
direct grep).

**One refinement to Sonnet's DC1 framing:** Sonnet says "the runner is
013 → 015 (014 is absent), making 016 the next available." Accurate, but
**014 is not just absent — it's reserved.** Per `CLAUDE.md:237` and
`docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md` lines
49, 98, 2709, 3683, and 4178: **Migration 014 is reserved for Phase 4 —
drop the legacy `agenda_items.summary` column once v3 backfill completes.**
Sonnet's DC1 didn't address this; both the G2 escalate-handler comment
*and* Opus 1's R1 proposal could in principle have grabbed slot 014, but
that slot is taken by Phase 4's plan-of-record.

**Slot assignment recommendation:**

- **016 → R1's FK relaxation** (this audit's recommended fix; small,
  mechanical, can ship with G3 fix-up).
- **017 → G2 escalate's `requires_manual_review BOOLEAN` column**
  (still a future stopgap-promotion, not in flight).
- **014 → unchanged, reserved for Phase 4 `DROP COLUMN summary`.**

**Required edit to `admin.py:331`:** change `Migration 016 candidate` to
`Migration 017 candidate` (and optionally append a parenthetical so the
next reader doesn't repeat the search: `(016 reserved for FK relaxation
on agenda_item_badges_audit, see G3 audit; 014 reserved for Phase 4)`).

### DC2 — `login_required` docstring drift

**Verified.** `src/docket/services/query.py:2036-2038` reads:

> *"That's acceptable for v1 — admin traffic is bounded by
> ``login_required`` and the table is small (one row per badge..."*

**Confirmed wrong.** This codebase has no `@login_required` decorator on
admin routes. Auth is enforced exclusively by the blueprint
`before_request` hook at `admin.py:27-35`:

```python
@bp.before_request
def require_login():
    """All admin routes require authentication."""
    from flask import session
    if request.endpoint and request.endpoint.startswith("admin."):
        if "admin_user" not in session:
            return redirect(url_for("auth.login", next=request.path))
```

Note that the project *does* have a function named `login_required` in
`src/docket/web/auth.py` — it's used as a `@login_required` decorator on
the auth blueprint's own `/admin/logout` route, not on `admin.*` routes.
So the term isn't from training-data hallucination; it's just borrowed
from a sibling blueprint and isn't the mechanism for the route this
docstring is describing.

**Required edit:** Replace the term ` ``login_required`` ` at
`query.py:2037` with ``the admin blueprint's `before_request` hook ``.

### DC3 — dead-code template documentation

**Verified.** `src/docket/web/templates/admin/badges_audit.html:18-21`
reads:

> *"NB: agenda_item_badges_audit's agenda_item_id FK has no ON DELETE
> CASCADE (migration 013:144). Deleted items still surface in the log
> with NULL item_title / meeting_date / municipality_slug — the
> helper LEFT JOINs accordingly."*

The migration line reference (`013:144`) is correct. The behavioral
claim ("Deleted items still surface in the log...") is **dead code under
the current schema** — RESTRICT semantics make the deletion path itself
impossible.

**Severity dependency on R1:** if the user accepts R1's option (a)
(Migration 016 with `ON DELETE SET NULL`), this comment becomes
**accurate** post-migration; no edit needed at that point. If R1 is
deferred (option c), this comment must be hedged: change "Deleted items
still surface" to "Once Migration 016 relaxes the FK to SET NULL, deleted
items will surface...". If R1 takes option (b) (downgrade LEFT JOIN to
INNER), this comment must be deleted entirely.

**Recommendation:** Pair fix with R1. Single fix-up commit can land both
the migration and the comment update; no churn.

## Auditor-only finds

### A1 — Helper docstring asserts a falsehood about row survival under current schema

**File:** `src/docket/services/query.py:2055-2058`

**Quote:**
> *"NB: the audit table's `agenda_item_id` FK to `agenda_items` has no
> `ON DELETE CASCADE`, so audit rows live forever even if the item is
> deleted."*

**Why this is wrong:** The absence of `ON DELETE CASCADE` doesn't mean
"audit rows live forever" — it means **audit rows block parent deletes
entirely**. The "live forever" claim is the post-`SET NULL` behavior the
implementer was anticipating; the current schema has the *opposite*
behavior (parent can't be deleted at all while a child references it).

This is the same root issue as DC3 (template) and the test workaround
(`DROP CONSTRAINT`/`ADD CONSTRAINT`), but **manifests in the helper's
own docstring** — which is the contract the route handler relies on, and
which a future operator searching for "FK behavior" will read first.
None of the prior three reviewers flagged this specific phrasing; Sonnet
came closest with DC3 (the template variant) but didn't extend the call
to the helper docstring.

**Severity:** Fixable (documentation correctness, paired with R1). If R1
ships with option (a), the rephrasing is one word — change "no `ON DELETE
CASCADE`" to "`ON DELETE SET NULL` (per migration 016)" and "live forever
even if the item is deleted" stays correct. If R1 defers, change "live
forever even if the item is deleted" to "are protected from cascading
deletion (the FK is `RESTRICT`)" and remove the LEFT JOIN's "future
forward-compat" framing because today it's not forward-compat — it's
unreachable defensive code.

### A2 — Test docstring labels the LEFT JOIN as "defensive code" but the helper's own docstring claims it's load-bearing

**File:** `tests/integration/test_admin_badge_audit.py:328-336`

**Quote (test docstring):**
> *"The LEFT JOIN remains correct defensive code in case a future
> migration relaxes the FK."*

**File:** `src/docket/services/query.py:2055-2058` (helper docstring)

**Quote (helper docstring):**
> *"audit rows live forever even if the item is deleted. Use a LEFT
> JOIN so old audit rows still surface (with NULL item_title /
> meeting_date / municipality_*)."*

**The drift:** The helper docstring frames LEFT JOIN as *load-bearing
behavior* ("audit rows live forever ... use LEFT JOIN so old rows
surface"). The test docstring frames the same LEFT JOIN as
*defensive forward-compat* ("in case a future migration relaxes the
FK"). They cannot both be right under one schema.

Under current schema (RESTRICT): test's "defensive" framing is correct;
helper's "load-bearing" framing is fiction. Under R1 option (a) schema
(SET NULL): helper's framing is correct; test's "defensive" framing
becomes stale — the LEFT JOIN's NULL branch is reachable in production.

**Severity:** Fixable (documentation correctness). Whoever lands R1
should resolve the contradiction; if R1 ships, update the test
docstring at lines 328-336 to drop "defensive in case a future
migration ..." and replace with "audit rows survive item deletion via
`ON DELETE SET NULL` (migration 016)."

This is the same R1 root manifesting in a fourth location: schema,
helper docstring, template comment, and test docstring all in disagreement.

## Final verdict

**Mergeable as-is.**

Track 3 14/17 → 15/17 should advance on this PR; G3 functionality is
correct, complete, and tested. R1 is genuinely a contract-level decision
the user owns, not a defect blocking merge. DC1-DC3 + A1 + A2 are all
fixable in a tight follow-up — none of them produce wrong runtime
behavior; they produce wrong *documentation* about runtime behavior.
Pattern matches the G2 auditor pass: ship the implementation, schedule
a small fix-up commit for the documentation-correctness items.

If the user picks R1 option (a), the right shape is one fix-up commit
that covers (in order):

1. New migration `016_relax_audit_fk_for_history_retention.py`.
2. Register in `runner.py:MIGRATIONS`.
3. Update `admin.py:331` migration-slot annotation.
4. Update `query.py:2037` docstring (`login_required` → blueprint
   `before_request`).
5. Update `query.py:2055-2058` docstring (FK semantics).
6. Update `badges_audit.html:18-21` template comment.
7. Simplify `test_admin_badge_audit.py:327-371` to drop the
   `DROP/ADD CONSTRAINT` gymnastics; update the test docstring.

If the user defers R1 (option c), the doc-correctness items still ship,
but with hedged language ("once migration 016 relaxes the FK ...").

## Recommended remediation order for fix-up

```
[ ] 1. Decide R1 option (a/b/c). Default: (a).

[ ] 2. (option a only) Create src/docket/migrations/016_relax_audit_fk_for_history_retention.py
       UP per body in §R1 verification above. DOWN raises NotImplementedError.

[ ] 3. (option a only) Add "docket.migrations.016_relax_audit_fk_for_history_retention"
       to MIGRATIONS list at src/docket/migrations/runner.py:30 (insert
       after 015_search_vector_v3, keeping list sorted).

[ ] 4. src/docket/web/admin.py:331 — change "Migration 016 candidate"
       to "Migration 017 candidate" (DC1). Optionally append:
       "(016 reserved for FK relaxation on agenda_item_badges_audit;
        014 reserved for Phase 4 DROP COLUMN summary)".

[ ] 5. src/docket/services/query.py:2037 — replace ``login_required``
       with "the admin blueprint's `before_request` hook" (DC2).

[ ] 6. src/docket/services/query.py:2055-2058 — replace the
       "no ON DELETE CASCADE / live forever" narrative (A1). If option (a):
       "the audit table's `agenda_item_id` FK uses `ON DELETE SET NULL`
        (migration 016), so audit rows survive item deletion with
        agenda_item_id nulled out". If option (c): "the audit table's
        `agenda_item_id` FK is `RESTRICT` (NO ACTION), so deletion of
        the parent item is blocked while audit rows reference it; the
        LEFT JOIN is forward-compat for a planned `ON DELETE SET NULL`
        relaxation (TODO migration 016)".

[ ] 7. src/docket/web/templates/admin/badges_audit.html:18-21 — align
       the template NB to whichever R1 option is chosen (DC3).

[ ] 8. (option a only) tests/integration/test_admin_badge_audit.py:327-371
       — delete the constraint drop/restore gymnastics; the test
       becomes a bare DELETE FROM agenda_items + assertion that the
       LEFT JOIN surfaces a row with item_title=None. Update the
       test docstring (A2) to reflect that this is load-bearing
       behavior, not defensive forward-compat.

[ ] 9. Run pytest tests/integration/test_admin_badge_audit.py -xvs;
       confirm 25/25 pass without the FK gymnastics.

[ ] 10. (post fix-up) Apply migration 016 in production via
        railway ssh --service docket-web "python -m docket.migrations.runner".
```

Total: ~30-40 lines of code change + one new migration file. Mechanical;
no Wave 0/Stage 1/Stage 2 logic touched.
