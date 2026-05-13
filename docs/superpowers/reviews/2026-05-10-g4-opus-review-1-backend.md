# G4 Opus Review #1 — Backend (Service + Routes + Transactions)

**Reviewer:** Opus 4.7 (1M context)
**Scope:** service layer, route handlers, transaction semantics, SQL correctness, Pydantic gates, `_rerun_stage2` helper, spec/plan drift
**Commits reviewed:** `602b4d5..3f91b12` (7 commits, excluding nav cross-link `8dcd406` which is template-only)
**Date:** 2026-05-10

## Summary

The backend is well-architected and faithfully follows the most consequential
parts of the plan: the LLM call runs strictly outside any held DB connection,
`_rerun_stage2` is minimal and B5-cleanable, `already_retried=True` is used
in both call sites, and the four UPDATE TOCTOU predicates in the LLM-touching
paths are intact with the audit-then-commit-then-raise ordering correctly
handling psycopg2's rollback-on-exception semantics. The `_get_enabled_policy_slugs`
shim correctly filters to `kind == "policy"`, the `apply_score_floors` cursor
lifecycle adapts cleanly to the actual signature drift, and `_ItemView` exposes
the exact attribute surface `rewrite.build_user_message` / `floors.apply_score_floors`
/ `reconcile.reconcile_stages` consume.

Two REQUIRED findings worth blocking on:

1. The early `extracted_facts` UPDATE inside `edit_stage_1_facts` lacks
   the TOCTOU predicate that the late UPDATE has. A concurrent admin who
   resolves the row in the gap between `_load_conflict_item` and that
   early UPDATE will see the **completed row's `extracted_facts` silently
   overwritten** — and the inline comment block at L610-618 documents a
   different (incorrect) outcome ("silently affected 0 rows").
2. The defensive `StructuredFacts.model_validate(item["extracted_facts"])`
   call inside `re_prompt_stage_2` raises `pydantic.ValidationError` on
   drift, which escapes uncaught past the route's `except ConflictValidationError`
   clause → bubbles to a 500. The implementer's intent (per docstring,
   "surface cleanly") was almost certainly to wrap it the same way
   `edit_stage_1_facts` does at L573-577.

Plus a small handful of SUGGESTED and NICE-TO-HAVE items. Tests cover the
happy path, the still-conflicting path, and the TOCTOU race-loss path for
both LLM-touching actions — including a clever monkeypatched `rewrite_item`
that flips the row to `completed` during the mock so the race window is
exercised deterministically.

---

## REQUIRED

### R1 — `edit_stage_1_facts` early facts UPDATE has no TOCTOU guard; silently overwrites a concurrently-resolved row

**Files:**
- `src/docket/services/conflict_resolution.py:580-591` — early `extracted_facts` UPDATE
- `src/docket/services/conflict_resolution.py:610-618` — comment block documenting (incorrectly) the race outcome

**What's happening:**
`edit_stage_1_facts` does the work in two separate DB transactions with the
LLM call between them:

1. **Tx 1 (L580-591)** — `_load_conflict_item` (which DOES filter on
   `processing_status='cross_stage_conflict'`) then `UPDATE agenda_items
   SET extracted_facts = %s::jsonb WHERE id = %s`. **No status predicate
   on this UPDATE.**
2. LLM call via `_rerun_stage2` (no DB held).
3. **Tx 2 (L619-695)** — late UPDATE with the TOCTOU predicate
   (`AND processing_status = 'cross_stage_conflict'`), `cur.rowcount == 0`
   check, race-loss audit, then raise.

Under PostgreSQL's default READ COMMITTED isolation, two transactions
running concurrent SELECTs against the same row both succeed without
locking. So:

- Admin A starts `edit_stage_1_facts` → `_load_conflict_item` returns
  the conflict item → Tx 1 ends having UPDATEd `extracted_facts` (uses
  only `WHERE id = %s`). LLM call starts.
- Admin B starts `accept_stage_2` → flips status to `completed` (or
  `accept_stage_1` with manual headline/why). Commits.
- Admin A's LLM finishes. Tx 2 fires the late UPDATE; `cur.rowcount == 0`
  fires; race-loss audit row written; `ConflictAlreadyResolvedError`
  raised; route returns 409.

**The bad outcome:** by the time the 409 lands, the now-`completed` row's
`extracted_facts` has already been silently overwritten by the admin A's
edit in step 1. Admin B's resolution semantically depended on a particular
`extracted_facts` (either preserved-as-was for accept_stage_1 or cleared
for accept_stage_2). Admin A's losing-race edit corrupts the audit trail
and (for accept_stage_1) the data used by downstream Stage 2 re-runs if
the conflict ever re-opens.

The inline comment at L610-618 says:

> "if a concurrent admin flipped the row to 'completed' between
> `_load_conflict_item` and that UPDATE, the early UPDATE silently
> affected 0 rows but the LLM call still ran."

This is **incorrect**. The early UPDATE only filters on `WHERE id = %s`,
so it affects 1 row regardless of status. The implementer's mental model
matches what a TOCTOU-guarded UPDATE would do, but the UPDATE statement
itself doesn't have that guard.

**Fix:** apply the same predicate. Change L588-591 from:

```python
cur.execute(
    "UPDATE agenda_items SET extracted_facts = %s::jsonb WHERE id = %s",
    (json.dumps(canon_facts), item_id),
)
```

to:

```python
cur.execute(
    """
    UPDATE agenda_items
       SET extracted_facts = %s::jsonb
     WHERE id = %s
       AND processing_status = 'cross_stage_conflict'::processing_status_enum
    """,
    (json.dumps(canon_facts), item_id),
)
if cur.rowcount == 0:
    # Lost the race before even reaching the LLM call. No work
    # done; skip the LLM call entirely; raise the same exception
    # the late UPDATE would raise.
    cur.execute(
        "SELECT processing_status::text FROM agenda_items WHERE id = %s",
        (item_id,),
    )
    current = cur.fetchone()
    current_status = current[0] if current else "unknown"
    # write a lost-race audit row with the early-fail variant action,
    # then raise outside the `with db()` block.
```

The bonus prize: catching the race before the LLM call saves the API
spend (~$0.0026 per Stage 2 call). The implementer's L617-618 note about
"the cost of running an extra LLM call on a lost race is the tradeoff
we accept for v1" frames the trade-off as LLM-call-or-no-LLM-call, but
the real choice is "early TOCTOU guard saves money AND prevents the
silent overwrite" vs "late-only guard does neither." The cheaper,
safer option is also the shorter diff.

**Test coverage gap:** `test_edit_facts_returns_409_when_item_resolved_during_llm_call`
flips the status from inside the `rewrite_item` mock (i.e., AT the LLM-call
window) — which gets the late TOCTOU guard to fire, but the early UPDATE
already ran before the mock. The test doesn't observe the
`extracted_facts` overwrite because the asserts only check status and
audit-row action. A regression test for this issue should additionally
assert that the row's `extracted_facts` is unchanged from what
admin B set (or that the resolution was `accept_stage_2` and
`extracted_facts is None`).

---

### R2 — `re_prompt_stage_2`'s defensive `StructuredFacts.model_validate` returns 500 instead of 4xx on drift

**Files:**
- `src/docket/services/conflict_resolution.py:413` — bare `StructuredFacts.model_validate(item["extracted_facts"])`
- `src/docket/services/conflict_resolution.py:407-412` — docstring/comment claiming it "surfaces it cleanly"
- `src/docket/web/admin.py:1013-1025` — route's exception-mapping block

**What's happening:**
The implementer wraps `edit_stage_1_facts`'s admin-supplied Pydantic
validation in a try/except → `ConflictValidationError` (L573-577 of
service module). For `re_prompt_stage_2`, the same Pydantic call against
stored `extracted_facts` is NOT wrapped (L413). If the stored JSONB
drifted (e.g., a schema migration tightened `StructuredFacts`),
`pydantic.ValidationError` bubbles past the route's
`except conflict_svc.ConflictValidationError` clause and Flask returns
a generic 500.

The implementer's intent is clearly to surface as a clean error — the
docstring at L407-408 says "Validate stored extracted_facts via
Pydantic before re-running. If the JSONB drifted, this surfaces it
cleanly." But the current code surfaces it as a 500, not cleanly.

**Two reasonable fixes:**

- **(a) Wrap it the same way `edit_stage_1_facts` does:**
  ```python
  try:
      facts = StructuredFacts.model_validate(item["extracted_facts"])
  except Exception as e:
      raise ConflictValidationError(
          f"stored extracted_facts failed validation: {e}"
      )
  ```
  Route returns 400. Defensible: admin can use a different action
  (`edit_stage_1_facts` with corrected facts, or `accept_stage_2` to
  clear them entirely).

- **(b) Catch it, write an audit row, and 500.** Drift in stored data
  is genuinely a 5xx-class problem — admins didn't cause it and admins
  can't fix it from the form. But the test pattern would be harder to
  exercise, and the 500 page isn't actionable from the admin UI.

Either is acceptable; (a) matches `edit_stage_1_facts`'s pattern and
keeps the route logic uniform.

**Adjacent observation:** the `extracted_facts is None` branch at L409-412
raises `ConflictValidationError` ("item has no extracted_facts — re_prompt_stage_2
needs Stage 1 facts"). A 400 isn't quite right for a state-impossible
situation (an item in `cross_stage_conflict` should always have
`extracted_facts` by definition of decision #93's escalation path). But
this is a defensible defensive guard and doesn't need to change.

---

## SUGGESTED

### S1 — `accept_stage_1` / `accept_stage_2` are also race-prone under READ COMMITTED, but the plan says they aren't

**Files:**
- `src/docket/services/conflict_resolution.py:194-228` — `accept_stage_1`
- `src/docket/services/conflict_resolution.py:259-291` — `accept_stage_2`
- `src/docket/services/conflict_resolution.py:125-157` — `_load_conflict_item` (no `FOR UPDATE`)

**What's happening:**
Decision #12's prose (plan L32 and Decisions section) claims
`accept_stage_1` / `accept_stage_2` don't need a TOCTOU guard because
"both run a single short transaction that locks the row briefly;
whichever admin commits first wins, and the second admin's
`_load_conflict_item` call in the same transaction returns None (because
the load query also filters on `processing_status = 'cross_stage_conflict'`)."

That reasoning is **not quite right** for PostgreSQL READ COMMITTED.
Plain `SELECT` does not lock the row. Two concurrent admins can BOTH
pass `_load_conflict_item` simultaneously, BOTH UPDATE successfully,
and the later writer silently wins (the UPDATEs in `accept_stage_*`
have only `WHERE id = %s`, no status predicate). For two
`accept_stage_2` calls the outcome is idempotent (both clear the same
fields, both flip to `completed`), so it's harmless. For two
`accept_stage_1` calls with different manual headlines, the later
writer overwrites the earlier admin's headline — silently, with no
audit-trail signal that there were competing edits.

The window is small (no LLM between SELECT and UPDATE, so we're talking
about microseconds, not seconds). But the contract the plan claims
("clean LookupError → 404 for the loser") isn't what the code delivers.

**Cheap fix:** add `FOR UPDATE` to `_load_conflict_item`'s SELECT, OR
add the same TOCTOU predicate (`AND processing_status = 'cross_stage_conflict'::processing_status_enum`)
to the four `accept_stage_*` UPDATEs and check `cur.rowcount == 0`.
Either makes the plan's claim accurate. `FOR UPDATE` is simpler — one
clause change in one place — and gives both accept actions the
serialized behavior the plan promised.

**Why it's SUGGESTED and not REQUIRED:** the dual-`accept_stage_1`
collision is extraordinarily rare in practice (two admins on the same
item within the same few-millisecond window), and the failure mode is
"later admin's headline wins" rather than data corruption. Worth a
follow-up but not a blocker for shipping G4 today.

---

### S2 — `re_prompt_stage_2` / `edit_stage_1_facts`: still-conflicting branch writes `score_overrides` JSONB but not the underlying score columns

**Files:**
- `src/docket/services/conflict_resolution.py:462-473` — re-prompt still-conflicting UPDATE
- `src/docket/services/conflict_resolution.py:642-651` — edit-facts still-conflicting UPDATE

**What's happening:**
When `_rerun_stage2` returns `mark_cross_stage_conflict`, the late UPDATE
in both LLM-touching paths refreshes `score_overrides` JSONB with the
new conflicts list and the new `final_significance`/`final_consent`
computed values — but does NOT update the `significance_score` /
`consent_placement_score` table columns themselves. The row's
`score_overrides->'final_significance'` (e.g., 7) and `significance_score`
(e.g., 4, the value before Stage 2.5 re-ran) become inconsistent.

The row stays at `cross_stage_conflict` so citizen-facing rendering
never sees these scores. But:

- The admin UI listing template (out of scope for this review)
  may surface either column.
- Replay-from-audit can't reconstruct the scores the admin saw at
  the time of the run.

**Cheap fix:** also write `significance_score` and `consent_placement_score`
in the still-conflicting branch. Or document this as intentional in
the comment.

---

### S3 — Inconsistent `reason` handling between `accept_stage_2` and `edit_stage_1_facts`

**Files:**
- `src/docket/services/conflict_resolution.py:251-257` — `accept_stage_2` raises on `reason` too long
- `src/docket/services/conflict_resolution.py:570-571` — `edit_stage_1_facts` silently truncates

**What's happening:**
```python
# accept_stage_2 (correct):
if len(reason) > REASON_MAX:
    raise ConflictValidationError(f"reason must be at most {REASON_MAX} chars")

# edit_stage_1_facts (silently truncates):
if reason is not None:
    reason = reason.strip()[:REASON_MAX] or None
```

Pick one. Silent truncation hides admin intent; raising is more
honest. Recommend raising consistently — admin can resubmit with
a shorter reason.

---

### S4 — `ai_generated_at` substitution for `updated_at` in listing sort: semantic mismatch for accept_stage_1 resolutions

**Files:**
- `src/docket/services/query.py:2054` — `ORDER BY … ai.ai_generated_at DESC NULLS LAST, ai.id DESC`
- `src/docket/services/conflict_resolution.py:194-228` — `accept_stage_1` (no AI run, no `ai_generated_at` touch)

**What's happening:**
Per the implementer's deviations report, `agenda_items` has no
`updated_at` column, so the listing helper uses `ai_generated_at` as
the freshness proxy. But `ai_generated_at` is set only when the AI
pipeline writes — `accept_stage_1` and `accept_stage_2` don't run the
pipeline, so they don't touch `ai_generated_at`. After an
`accept_stage_1`, the row's processing_status flips to `completed`
(so it falls out of the listing entirely — fine), but if an admin
explicitly re-opens the queue and the original `ai_generated_at` is
NULL (item that flipped to `cross_stage_conflict` via Wave 0 without
ever running v3 Stage 2), the row sinks to the bottom via `NULLS LAST`.

In practice this is mostly fine: rows in `cross_stage_conflict` reach
that state via Stage 2 reconcile, which means Stage 2 ran, which means
`ai_generated_at` is set. So the NULL case is unlikely. And once an
admin resolves the row, it falls out of the listing entirely. The
sort is "good enough" for v1 admin UX — flag for future cleanup if
the sort behavior gets feedback.

Two cleanup paths if you decide to fix it:

- Add an `agenda_items.updated_at` column populated by a trigger on
  every row write.
- Or sort by the latest `processing_status_audit.occurred_at` for the
  item (more complex query, but precisely captures "most recently
  flipped to/in conflict").

Both are over-engineered for v1; mention in `dev-debt-notes.md`.

---

### S5 — `score_overrides_payload` does not include the new headline/why_it_matters/scores written

**Files:**
- `src/docket/services/conflict_resolution.py:511-518` — `re_prompt_stage2` audit payload
- `src/docket/services/conflict_resolution.py:688-694` — `edit_stage1_facts` audit payload

**What's happening:**
The success-branch audit payloads carry `override_instruction` /
`new_facts_json` (admin input) + `reconcile_action` + `conflicts` +
`served_model` + `is_substantive` — but NOT the actual values written
to the row (`headline`, `why_it_matters`, `final_significance`,
`final_consent`). Replay-from-audit can't reconstruct the post-action
state without re-running the LLM.

Decision #10 of the plan says the payload "carries action-specific
metadata (manual_headline, override_instruction, new_facts_json, etc.)"
— a strict reading lets this be minimal, so the implementer's choice
is defensible. But for accept_stage_1, the payload DOES include the
written values (manual_headline, manual_why_it_matters) — so there's
an asymmetry.

**Cheap fix:** add `headline`, `why_it_matters`, `final_significance`,
`final_consent` to the success-branch payloads for symmetry with
accept_stage_1. ~4 extra fields per JSONB row, no extra Anthropic
spend.

---

### S6 — `rewrite_item` exception bubbling: anthropic SDK errors return 500, not 503

**Files:**
- `src/docket/web/admin.py:1009-1027` — `conflict_re_prompt_stage_2` route
- `src/docket/web/admin.py:1051-1075` — `conflict_edit_stage_1_facts` route
- `src/docket/ai/rewrite.py:263-272` — direct `anthropic_client.messages.create(...)` call (no transient/budget wrapping)

**What's happening:**
The plan and the service docstring say `re_prompt_stage_2` "Bubbles up
`AIBudgetExceeded` / `AITransientError` from the API call." Actually
`rewrite_item` calls `anthropic_client.messages.create(...)` directly
with no wrapping — so transient API errors propagate as raw anthropic
exceptions (e.g., `anthropic.APIConnectionError`, `anthropic.RateLimitError`,
`anthropic.InternalServerError`). These are not caught at the route, so
Flask returns 500.

Additionally: there is no `AIBudgetExceeded` exception class — only
`worker.BudgetExceededError`, which is internal to the worker. So the
budget-exceeded path the plan referenced doesn't fire here at all.

**Cheap fix:** wrap the LLM call in `_rerun_stage2` with a try/except
that maps anthropic exceptions to a service-level exception
(`ConflictRewriteUnavailable` or similar), then route maps that to
503 + flash. Or just document that anthropic exceptions return 500 and
that's acceptable for v1 admin workflows.

---

## NICE-TO-HAVE

### N1 — `score_overrides_payload` types are mixed `int | float | None`

**Files:**
- `src/docket/services/conflict_resolution.py:423-431` (re_prompt) and `:600-608` (edit_facts)

`ScoreOverrides.original_ai_significance` comes from `ItemRewrite.significance_score: float | None`,
while `final_significance` after floors becomes an `int` (from the
trigger's `bound: int`). The JSONB will sometimes carry float, sometimes int,
sometimes null for the same field. JSON-serializes fine but admin-side
consumers (e.g., the listing template) need defensive code.

Cleanup: cast `final_*` to `int` (or `float`) consistently when building
the payload dict. Or normalize in `ScoreOverrides`.

### N2 — Race-loss audit's `from_status` reads "unknown" if the row was deleted

**Files:**
- `src/docket/services/conflict_resolution.py:480-485` and `:655-660`

If the lost-race `SELECT processing_status::text FROM agenda_items WHERE id = %s`
returns `None` (row deleted), `current_status = "unknown"` — which is
not a valid `processing_status_enum` value. The subsequent `_audit`
insert would then fail with a Postgres cast error, the `with db()`
block rolls back, AND the function raises the cast error instead of
`ConflictAlreadyResolvedError`.

`agenda_items` has no normal deletion path (FK references in many
tables), so this is essentially impossible in production. Worth a
comment or a defensive guard regardless — e.g., if `current is None`,
skip the audit and raise a different exception ("item disappeared").

### N3 — `_load_conflict_item` joins 3 tables for every action; could be cached or simplified for `accept_stage_*`

**Files:**
- `src/docket/services/conflict_resolution.py:125-157`

The full join (`agenda_items` → `meetings` → `municipalities`) is
necessary for `_rerun_stage2` (needs `city_name` + `municipality_id`).
For `accept_stage_1` / `accept_stage_2` (which don't run the LLM), the
join is wasted — only `processing_status` is consulted. Tiny micro-opt
not worth the complexity, but flag it for B5 if/when the helper gets
restructured.

### N4 — `_audit` payload column receives `None` (not `'null'::jsonb`) when payload kwarg is None

**Files:**
- `src/docket/services/conflict_resolution.py:121` — `json.dumps(payload) if payload else None`

This is correct (`None` → SQL `NULL`), and the column is nullable. But
note that the boolean check `if payload else None` will also pass
through `None` for an empty dict `{}` — which is "payload was
attempted but is intentionally empty" vs "no payload at all." Different
semantics. For G4 the call sites only pass non-empty dicts or omit
the kwarg, so this doesn't fire. Documentation-only.

### N5 — `re_prompt_stage_2` does not write the `reason` column

**Files:**
- `src/docket/services/conflict_resolution.py:505-518` (audit on success)

The signature is `re_prompt_stage_2(item_id, *, override_instruction, actor)` —
no `reason` kwarg. The plan didn't ask for one. But the audit row's
`reason` column is left NULL. Compare `edit_stage_1_facts` which DOES
accept and persist `reason`. Asymmetry; defensible.

### N6 — Module-level `from docket.services import conflict_resolution as conflict_svc` is at function-scoped line 934 of admin.py

**Files:**
- `src/docket/web/admin.py:934`

Imports usually go at the top of the file. The implementer placed this
mid-file (after `# --- Cross-Stage Conflict Resolution UI ---` section
header) — works, but stylistically out of place. Move to the top of
admin.py with the other service imports.

### N7 — `Literal` import in `conflict_resolution.py` is unused

**Files:**
- `src/docket/services/conflict_resolution.py:45`

`from typing import Any, Literal` — `Literal` is not referenced anywhere
in the module. Drop it.

### N8 — Test gap: no positive assertion on `score_overrides` JSONB content after happy-path re-prompt or edit-facts

**Files:**
- `tests/integration/test_conflict_resolution.py:675-700` — re-prompt happy path
- `tests/integration/test_conflict_resolution.py:866-894` — edit-facts happy path

Tests check `headline`, `why_it_matters`, `processing_status`, and
audit-row contents — but never read back the row's `score_overrides`
to confirm the floor-computation pipeline actually wrote the
expected `final_significance` / `triggers`. The mock returns
`significance_score=4.0` + `dollars_amount=75_000` (yellow tier) — at
that combo, `apply_score_floors` should NOT fire any trigger (yellow
tier floors require `funding_source` / `procurement_method` / etc.
predicates the SAMPLE_FACTS doesn't trip). So the expected
`final_significance=4.0, final_consent=8.0, triggers=[]`. Worth one
positive assertion.

---

## Decisions to escalate

### D1 — Should the early `extracted_facts` UPDATE in `edit_stage_1_facts` be TOCTOU-guarded? (See R1.)

The plan's decision #12 lists the predicate as required for "every
persistence UPDATE in these two paths" — strictly that includes the
early `extracted_facts` write. The implementer's comment block frames
the absence as a deliberate tradeoff but the framing is incorrect.

Recommendation: yes, add the guard. Cheap, prevents silent overwrite,
and saves the wasted LLM spend on a known-lost race. The implementer
agrees in the comment that "Hardening the early facts UPDATE the same
way is possible" — pull the trigger.

### D2 — Should `re_prompt_stage_2`'s defensive Pydantic validation map to 400 or 500? (See R2.)

The implementer's docstring says "surfaces cleanly" (implying 400),
but the code surfaces as 500. Need to confirm which the plan intends.
Recommendation: 400 (admin can pick a different action), consistent
with `edit_stage_1_facts`.

### D3 — Should `accept_stage_*` get `FOR UPDATE` locking? (See S1.)

Low-frequency race, low-impact outcome (later admin's headline wins
silently). If we never expect two admins on the same row at the same
millisecond, leave as-is. If we want the plan's claimed semantics
("clean LookupError → 404 for the loser"), add `FOR UPDATE` to
`_load_conflict_item`'s SELECT.

---

## Verified items (no issues)

The following items were specifically called out in the review scope and
checked — no issues found:

- **Decision #2: `_rerun_stage2` minimality.** Calls `rewrite_item →
  apply_score_floors → reconcile_stages` in the correct order
  (`conflict_resolution.py:347-367`). No B5-territory scope creep.
- **LLM call OUTSIDE any held DB connection.** In both
  `re_prompt_stage_2` (`:402-418`) and `edit_stage_1_facts`
  (`:580-595`), the read transaction commits/exits before
  `_rerun_stage2` runs. Inside `_rerun_stage2`, the LLM call at
  `:351-356` precedes the short `with db()` block at `:360-363`
  for `apply_score_floors`.
- **Decision #11: `already_retried=True`.** Both call paths through
  `_rerun_stage2` end in `reconcile_stages(..., already_retried=True)`
  at `:367`. Correct — admin re-runs are explicit, not the
  worker's auto-retry path.
- **Decision #12: TOCTOU predicates on the four LATE UPDATEs.**
  - `re_prompt_stage_2` success branch: `:451` ✓
  - `re_prompt_stage_2` still-conflicting branch: `:470` ✓
  - `edit_stage_1_facts` success branch: `:631` ✓
  - `edit_stage_1_facts` still-conflicting branch: `:648` ✓
  (The early `extracted_facts` UPDATE at `:589-590` of `edit_stage_1_facts`
  is the gap — see R1.)
- **Decision #13: race-loss audit row ordering.** In both
  `re_prompt_stage_2` (`:475-518` then raise at `:524-528`) and
  `edit_stage_1_facts` (`:653-695` then raise at `:699-703`), the
  audit row writes BEFORE the `with db()` block exits (so it commits),
  and the `raise ConflictAlreadyResolvedError` fires AFTER the
  block (so the rollback semantic doesn't discard the audit). Correct
  with respect to `docket.db.db()`'s contract.
- **Decision #14: score-overrides preservation.** `accept_stage_*`
  paths don't recompute scores; LLM-touching paths do. Verified at
  `:194-228`, `:259-291`, `:441-461`, `:621-641`.
- **`_get_enabled_policy_slugs` shim correctness.**
  `list_enabled_badges` (`query.py:1722-1746`) returns process+policy
  via a UNION ALL that tags each row with `t.kind`. The shim at
  `conflict_resolution.py:97-98` filters `r.get("kind") == "policy"`
  → exactly the policy-only slugs `rewrite.build_user_message`
  expects.
- **`apply_score_floors` signature + cursor lifecycle.** The actual
  signature `(cur, item, facts, ai, city_id)` is correctly matched at
  `:361-363`. The `with db() as conn, conn.cursor() as cur:` block at
  `:360` opens a fresh, short connection AFTER the LLM call returns;
  no nested transactions; commits on exit.
- **Pydantic gates:** `StructuredFacts.model_validate(new_facts_json)`
  at `:575` is correctly wrapped in try/except → `ConflictValidationError`.
  Pydantic's `extra='forbid'` (`extraction_schema.py:65`) catches
  unknown keys.
- **Length caps consistency with `ItemRewrite` Pydantic model.**
  Service uses 10-60 headline (matches rewrite_schema `max_length=60`
  + density validator `>=10`); 1-200 why_it_matters (matches
  rewrite_schema `max_length=200` + density validator non-empty);
  1-500 override_instruction; 0-500 reason. ✓
- **`_load_conflict_item` filter on `processing_status='cross_stage_conflict'`.**
  Line 155. Item-not-found AND wrong-state both → None at the helper,
  which surfaces as LookupError → 404 at the route.
- **Audit-row payload completeness (within the implementer's design
  choices).** Each action records action verb + actor + `actor_role='admin'`
  + action-specific input. Reconcile outcome and `served_model` included
  on LLM-touching paths.
- **`_ItemView` adapter surface.** Exposes `id`, `title`, `description`,
  `sponsor`, `dollars_amount`, `topic`, `is_consent`, `city_name` —
  exactly what `rewrite.build_user_message`, `floors.apply_score_floors`,
  and `reconcile.reconcile_stages` consume.

---

## Pre-existing G3 anomaly note

The migration runner / migration 016 drift mentioned in the prompt is
out of scope for G4 review. No similar drift observed in the G4 code
changes — G4 ships no new migrations and only references already-applied
schema (`processing_status_audit`, `agenda_items.extracted_facts`,
`processing_status_enum.cross_stage_conflict`, `data_debt_priority_enum`).
The implementer correctly identified that no migration is needed for G4.

---

## Files reviewed

- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/services/conflict_resolution.py` (720 lines, NEW)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/services/query.py` (lines 1996-2060 — new `list_cross_stage_conflicts`)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/admin.py` (lines 887-1099 — new G4 routes)
- `/Users/darrellnance/docket-pub-pf2-track-3/tests/integration/test_conflict_resolution.py` (990 lines, NEW — backend-relevant tests only)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/ai/rewrite.py` (read for signature + exception surface)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/ai/floors.py` (read for `apply_score_floors` signature)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/ai/reconcile.py` (read for `already_retried=True` semantics)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/ai/extraction_schema.py` (read for `StructuredFacts` model_config)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/ai/rewrite_schema.py` (read for `ItemRewrite` length caps + density validator)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/migrations/013_impact_first_refactor.py` (read for `processing_status_audit` schema)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/db.py` (read for `db()` rollback-on-exception contract)
- `/Users/darrellnance/docket-pub-pf2-track-3/docs/superpowers/plans/2026-05-10-g4-cross-stage-conflict-resolution.md` (decisions #2, #11, #12, #13, #14, file structure, audit-shape decision #10)
