# G3 Sonnet 4.6 Second-Look

**Reviewer:** Sonnet 4.6
**Mandate:** confirm REQUIREDs, scan cross-model convergence, elevate documentation correctness
**Commits reviewed:** 76c526e..edd9260 (6 commits)
**Date:** 2026-05-10

---

## Summary

The Opus pair landed it. The implementation is tight, faithful to the plan's 11
decisions, and the only architectural question is R1 (FK / LEFT JOIN mismatch),
which the implementer self-flagged. The second-look adds one new documentation-
correctness finding (DC1: a Migration 016 slot collision that neither Opus
reviewer caught) and confirms no cross-model convergence at the REQUIRED tier.

---

## Confirmation pass on REQUIRED findings

### R1 (FK / LEFT JOIN architectural mismatch)

**Agree, with one additional precision.**

The `agenda_item_badges_audit.agenda_item_id` column is declared as
`INT NOT NULL REFERENCES agenda_items(id)` at
`src/docket/migrations/013_impact_first_refactor.py:144` with no `ON DELETE`
clause — PostgreSQL default is `NO ACTION`, which behaves like `RESTRICT` at
statement end (not `NO CASCADE` as the plan's earlier prose implied; the
implementer self-corrected this in their deviation report). The current state:

- Schema says: orphan audit rows are **impossible** — any delete of an
  `agenda_items` row that has audit rows will raise an FK violation.
- Helper says (`query.py:2078-2082`, LEFT JOIN chain): orphan audit rows are
  **expected** and will surface with NULL context columns.
- Test says (`test_list_badge_audit_log_left_joins_deleted_items`, per Opus
  R1's line references): the FK must be **dropped and re-added** to exercise
  the LEFT JOIN path at all.

The three components are aligned to three different contracts. Opus R1's analysis
is correct and the severity is correctly set as REQUIRED (architectural decision,
not a code bug).

**My read on the three options:** option (a) — Migration 016 with
`ON DELETE SET NULL` — is correct for an audit table. However, the Opus
reviewer's proposed migration number itself has a documentation-correctness
problem: see DC1 below. The mechanics of (a) are right; the migration number
label needs attention before it becomes the implementation prompt.

**One reframe vs Opus R1:** Opus 1 states the `test_list_badge_audit_log_left_joins_deleted_items`
test "has to drop and re-add the FK constraint to exercise the LEFT JOIN path."
This is accurate. An additional implication worth noting: the cleanup section
of `_Bag.cleanup()` (plan docstring at `test_admin_badge_audit.py:113-118`)
documents that `agenda_item_badges_audit` has "no CASCADE" — confirming the
implementer understood the FK semantics but deliberately wrote the helper and
the test to match a *different future state* where CASCADE-to-null is in effect.
That intent is well-placed; it just needs the schema to catch up (option a) or
the code to back down (option b).

---

## Cross-model convergence scan

I looked for each SUGGESTED item from Opus 1 and asked whether Opus 2 approached
the same defect from a different angle, and vice versa.

**Convergence found: one pair.**

**Opus 1 S1** — `_render_manage_panel` re-fetches item context after commit;
the `abort(404)` branch is a TOCTOU race that the operator sees as "change
committed but page shows 404 instead of updated panel."

**Opus 2 S6** — No user-facing confirmation after add/remove: "on a slow
connection where the swap takes 800ms, the lack of any 'saved' affordance is
unsettling."

These are two different angles on the same underlying gap: **the post-commit
user experience of the HTMX swap path is not fully specified.** Opus 1 looked
at the error path (TOCTOU 404 after commit); Opus 2 looked at the happy path
(no "saved" confirmation). Both converge on "the UX after a successful write
is underdefined for v1." Neither is a blocker; combined they are a signal that
a v2 polish pass should cover the full post-write response (flash message or
`HX-Trigger` banner + graceful 404 handling in `_render_manage_panel`).

**Escalation:** Soft-escalate to SUGGESTED tier for the combined issue. A single
`HX-Trigger: {"showFlash": "Badge added"}` header from the add/remove handlers,
consumed by a small JS snippet in `base.html`, would cover both: the happy path
gets a "saved" toast, and the TOCTOU path can fall back to a visible error state
rather than a raw 404. This is v2 polish; merge is not blocked.

**No other convergence.** The remaining items are independent:

- Opus 1 S3 (actor `"unknown"` fallback unreachable) and Opus 2 S5 (no-JS form
  fallback broken) are distinct failure modes on unrelated code paths.
- Opus 1 N5 (partial index not hit) and Opus 2 S1 (CSS token drift) are
  completely orthogonal.
- Opus 1 N3 (loose pagination assertion) and Opus 2 N4 (table renders on
  separate lines) are both test-quality nits with no overlap.

---

## Documentation-correctness elevation (G2 auditor pattern)

### DC1 — Migration 016 slot collision: two independent features claim the same number

**File:** `src/docket/web/admin.py:331`
**Context:** G2 `errors_escalate` handler (pre-G3 code, present at base commit
`ea8fc93`)

The comment at `admin.py:331` reads:

```python
Migration 016 candidate (next available migration slot): add a
dedicated ``requires_manual_review BOOLEAN`` column on
``agenda_items``. The JSONB stopgap avoids a schema change for v1...
```

The Opus 1 R1 recommendation independently names the FK-relaxation fix as
"Migration 016":

> *New migration 016 (idempotent): `016_relax_audit_fk_for_history_retention.py`*

Both claims are numerically correct — the runner at
`src/docket/migrations/runner.py:16-31` confirms the sequence is:
013 → 015 (migration 014 is absent; 015 is `015_search_vector_v3.py`), making
016 the next available slot. But 016 is now **claimed by two independent
features**:

1. `requires_manual_review BOOLEAN` column on `agenda_items` (G2 escalate
   handler stopgap comment).
2. `ON DELETE SET NULL` FK relaxation on `agenda_item_badges_audit` (Opus R1
   proposed fix for the left-join mismatch).

**Why this matters:** if the user greenlights Opus R1's Migration 016 and a
developer later sees the `admin.py:331` comment while working on the escalate
handler, they will either (a) implement a second migration that also claims
slot 016 (runner collision at apply time) or (b) assume their work is already
done and skip it.

**Recommended fix (fixable today):** Update `admin.py:331` to say
"Migration 017 candidate" (or whichever slot is actually next after 016 is
assigned to the FK fix). If R1 option (b) or (c) is chosen instead (no new
migration), the `admin.py:331` comment should stay at 016 and be the first
migration in queue. The key is: **close this ticket before either migration is
dispatched so the slot assignment is unambiguous.**

Two-word fix: change `016` to `017` at `admin.py:331` if R1 option (a) is
accepted. Or, preferably, add a comment at `admin.py:331` naming the competing
claim explicitly:

```python
# Migration 016 reserved for FK relaxation on agenda_item_badges_audit
# (see G3 R1). This stopgap targets Migration 017 instead.
```

**Severity:** Fixable (documentation bug with real coordination risk). The
collision is harmless today (neither migration exists yet), but becomes a
race condition the moment implementation starts on either track.

---

### DC2 — `query.py:2037` docstring says `login_required`; auth is a blueprint `before_request` hook

**File:** `src/docket/services/query.py:2036-2037`

The `list_badge_audit_log` docstring says:

```
That's acceptable for v1 — admin traffic is bounded by
``login_required`` and the table is small...
```

There is no `@login_required` decorator in this codebase. The auth mechanism
for every admin route — including the G3 viewer — is the blueprint-level
`before_request` hook at `admin.py:27-35`. The correct phrasing is
"bounded by the blueprint `before_request` auth hook" or simply "admin-gated."

This is a new G3 docstring (added in commit `76c526e`). Calling it
`login_required` is not wrong in intent but is wrong in terminology — it names
a Flask-Login concept that this project doesn't use. A future maintainer reading
the docstring and then `grep`ping for `login_required` will find nothing,
which undermines the docstring's purpose as navigation aid.

Neither Opus reviewer flagged this.

**Recommended fix:** Replace ```login_required``` with `the blueprint
``before_request`` auth hook` at `query.py:2037`.

**Severity:** Fixable (minor terminology). One-word change. Lower priority than
DC1.

---

### DC3 — `badges_audit.html:19` comment correctly cites migration line but describes wrong FK behavior for current schema

**File:** `src/docket/web/templates/admin/badges_audit.html:18-21`

The template comment reads:

```
NB: agenda_item_badges_audit's agenda_item_id FK has no ON DELETE
CASCADE (migration 013:144). Deleted items still surface in the log
with NULL item_title / meeting_date / municipality_slug — the
helper LEFT JOINs accordingly.
```

This is accurate for the *intended future* schema state (ON DELETE SET NULL,
per R1 option a), but **inaccurate for the current schema** (ON DELETE
NO ACTION / RESTRICT). Under the current schema, "deleted items still surface
in the log" is **never true in production** — any delete of `agenda_items`
that has associated audit rows will raise an FK violation before the delete
succeeds. The comment documents aspirational behavior as present behavior.

The migration line number (013:144) is accurate; the behavioral claim is not.

**This is the same root issue as R1 — the comment is its third manifestation**
(after the helper and the test). But unlike those two, this comment lives in a
template that is read by people debugging production — it could lead an operator
to confidently expect NULL-context rows in the audit viewer and be confused when
they never appear.

**Recommended fix:** Either (a) add "once R1 migration is applied" to the
comment, or (b) fix with R1 option (a) and the comment becomes accurate. If R1
option (b) or (c) is chosen, rewrite the comment to reflect that orphaned rows
are impossible under the current FK.

**Severity:** Informational (paired with R1 — same fix). Flagging because the
comment is in a template file the Opus reviewers both read but neither called
out explicitly.

---

## Net delta

My second-look **adds** to the combined Opus output:

1. **DC1 (REQUIRED-adjacent):** Migration 016 slot collision — two independent
   features claim the same migration number. The Opus R1 fix names "016" for
   the FK relaxation; a pre-existing G2 comment at `admin.py:331` also claims
   "016" for the `requires_manual_review` column stopgap. One of these labels
   must change before implementation starts on either track. This is fixable
   today with a one-word change and should be done regardless of which R1 option
   is chosen.

2. **DC2 (fixable, minor):** `query.py:2037` docstring says `login_required`
   — wrong terminology for this project's blueprint-hook auth. New G3 docstring;
   not caught by either Opus reviewer.

3. **DC3 (informational, paired with R1):** `badges_audit.html:18-21` documents
   "deleted items surface with NULL columns" as present behavior, but under the
   current RESTRICT FK that situation never occurs in production. The comment
   describes the intended post-R1 state, not the current state. Third manifestation
   of the same R1 root.

4. **Convergence signal:** Opus 1 S1 + Opus 2 S6 converge on "post-write UX is
   underdefined for v1" — one reviewer saw the error path, the other the success
   path. Soft-escalated to SUGGESTED, v2 polish.

**Net new items:** 3 documentation-correctness findings (DC1, DC2, DC3) +
1 convergence flag. No new REQUIRED findings. No new SUGGESTED code changes
beyond the Opus pair's already-thorough S1-S7 lists.
