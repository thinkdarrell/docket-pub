# G3 Review Packet — Synthesized for User Decision Gate

**Phase:** 2 Track 3 §G3 — Audit log viewer + manual badge HTMX endpoints
**Branch:** `feat/impact-first-phase-2-track-3` @ `edd9260` (6 G3 commits)
**Date:** 2026-05-10
**Review chain (13th protocol run, standard 4-stage):**
1. Implementer (Opus 4.7) — DONE, 6 commits, 40 G3 tests + 1122/1122 full suite
2. Two parallel Opus reviews (backend / frontend) — 1 REQUIRED + 12 SUGGESTED + 13 NICE-TO-HAVE
3. Sonnet 4.6 second-look — confirmed R1, found 1 cross-model convergence pair, elevated 3 documentation-correctness items (DC1-DC3)
4. Final auditor Opus 4.7 — confirmed R1 + DC1-DC3, refined DC1's slot assignment, added 2 auditor-only finds (A1-A2)

**Verdict:** mergeable as-is. The recommended fix-up is ~30-40 lines + one migration file, all in a single commit.

---

## What you're authoring decisions on

The four reviewers converged on a tight set of issues. I've grouped them into **5 numbered decisions**. Author one answer per decision — the implementer dispatches a single fix-up commit afterward.

---

## Decision 1: R1 — FK / LEFT JOIN architectural mismatch

**The problem.** Migration 013's `agenda_item_badges_audit.agenda_item_id` is declared `REFERENCES agenda_items(id)` with no `ON DELETE` clause — defaults to RESTRICT. So `agenda_items` deletes are **blocked** while audit rows reference them. But the G3 helper uses `LEFT JOIN agenda_items` as if orphan audit rows were possible, the test orphans by dropping/restoring the FK, and the template comment documents "deleted items surface with NULL columns" as present behavior. Three different contracts in the same diff.

All four reviewers agreed this needs a real call. Three options on the table:

- **(a) Migration 016 — relax FK to `ON DELETE SET NULL`.** Audit rows survive item deletion (the audit-table convention). LEFT JOIN becomes load-bearing for real. DC2 + DC3 + A1 self-resolve. Test FK gymnastics get removed. Migration body would be ~10 lines (DROP CONSTRAINT, ADD CONSTRAINT with `ON DELETE SET NULL`, mark `agenda_item_id` nullable). **All four reviewers recommend this.**
- **(b) Downgrade LEFT JOIN to INNER JOIN.** Accept that orphans are impossible by FK design. Drop the FK-gymnastics test, downgrade docstrings/template comments. Smaller change, but you lose audit-table durability — if you ever delete an item, you lose its history (or get blocked).
- **(c) Defer with TODO.** Ship as-is, file the migration as a follow-up task, leave the dead-code paths flagged.

**Recommendation: (a).** Audit tables conventionally survive their referent's deletion; (b) actively reverses that. Cost is negligible (one short migration).

**Your decision:**

---

## Decision 2: DC1 — Migration slot assignment (depends on Decision 1)

If Decision 1 = (a), we need to assign migration slots cleanly. The auditor refined Sonnet's catch: migration 014 is **reserved** (not just absent) for Phase 4's `DROP COLUMN summary`, per `CLAUDE.md:237` and the Phase 4 plan.

**Recommended assignment:**
- `014` → Phase 4 drop-column (reserved, untouched)
- `015` → already-shipped search_vector_v3
- `016` → R1's FK relaxation (this fix-up)
- `017` → G2's pending `agenda_items.requires_manual_review` column (the `admin.py:331` comment gets bumped from "016" to "017")

Both `admin.py:331` (G2 comment) and the helper docstring R1 introduces would say "016". One has to move; the cleaner move is to bump the G2 comment to "017" since the FK fix lands first.

**Your decision:**

---

## Decision 3: Documentation-correctness bundle (DC2 + A1 + A2 + DC3)

These are all "saw it informationally, didn't classify as fixable" items the G2 auditor pattern says to elevate. They're tightly coupled to the R1 fix:

- **DC2:** `query.py` G3 docstring says `login_required` — wrong; project uses blueprint `before_request`. Likely seeded by `auth.py`'s separate (real) `login_required` decorator. **Fixable in 1 word.**
- **A1:** Helper docstring says "audit rows live forever even if the item is deleted." Opposite of current RESTRICT behavior — but **becomes correct under Decision 1 = (a)**.
- **A2:** Helper docstring calls LEFT JOIN load-bearing; test docstring calls it defensive. Internal contradiction; **resolves to load-bearing under (a)**.
- **DC3:** `badges_audit.html` template comment claims "deleted items surface with NULL columns" as present behavior. **Becomes correct under (a)**.

If you pick Decision 1 = (a), DC2 stands alone and A1/A2/DC3 self-resolve. If you pick (b), all four flip direction (docstrings need the opposite correction). If (c), all four become "documented dead code, accept the smell."

**Your decision (free-form bundle): apply DC2-A2 corrections per Decision 1's outcome / skip / something else.**

---

## Decision 4: Frontend S1 — CSS custom-property drift

G3 invents three CSS custom-property names — `--surface-2`, `--border`, `--muted` — with hard-coded fallback colors. The existing design system in `static/styles.css` uses `--paper-2`, `--paper-3`, `--rule`, `--ink-3`. G2's `tweaks.css:208-233` correctly used the existing tokens.

This is the only review-#2 SUGGESTED that's a clean pre-merge fix. ~5 lines of `var(...)` renames in `tweaks.css`. Catches before the next G-track or B5 work spreads the drift further.

**Recommendation:** rename in fix-up. **Your decision:**

---

## Decision 5: Convergence pair — post-write HTMX feedback

Backend reviewer S1 saw "TOCTOU 404 after the commit succeeded" (error path); frontend reviewer S6 saw "no 'saved' affordance after a successful add/remove" (success path). **Same underlying gap, different angles** — exactly the kind of cross-model convergence the protocol elevates: the post-write HTMX swap response is underdefined.

Today: a successful add/remove returns the re-rendered panel; the user's only feedback is "the slug now appears in current-badges" or "it disappeared." No banner, no flash, no toast. An add for a slug that doesn't exist (TOCTOU window) gets a 404 page rendered into the swap target — looks ugly.

**Three options:**
- **(a) Add a small flash banner to the panel partial.** ~10 lines. Worth it now while context is hot.
- **(b) Accept as-is for v1; flag as a Phase 4 polish item.** Admin-only surface, low-traffic, no citizen exposure.
- **(c) Tighter: render an error-state panel for 4xx instead of the default Flask error page.** Defensible for the TOCTOU specifically; doesn't fully address the success-path "did anything happen?" UX.

**Recommendation:** (b) — admin surface, the panel-swap itself is the feedback. Defer (a) until a real complaint.

**Your decision:**

---

## What's NOT in this packet

These review items don't need user input — implementer applies as part of the fix-up if Decisions 1-4 are taken, or skips entirely:

- All other Opus #1 SUGGESTED (S2-S5): documented or low-impact polish.
- All other Opus #2 SUGGESTED (S2-S7): minor (manage-meta class collision, scope="col" on `<th>`, mobile polish).
- All NICE-TO-HAVE (13 items): defer.
- Spec §6.10 doc patch for the timezone contract: a separate spec-PR commit, same pattern as G2's `?highlight=N` → `#item-N` deviation patch.

---

## Reviewer file references

- `docs/superpowers/reviews/2026-05-10-g3-opus-review-1-backend.md`
- `docs/superpowers/reviews/2026-05-10-g3-opus-review-2-frontend-ux-auth.md`
- `docs/superpowers/reviews/2026-05-10-g3-sonnet-second-look.md`
- `docs/superpowers/reviews/2026-05-10-g3-final-audit.md`

(All untracked per Track 3 review-doc convention.)

---

## Sign-off

Author one answer per decision (1-5). The implementer applies them as a single fix-up commit; if any decision lands ambiguously I'll come back for clarification before dispatching.
