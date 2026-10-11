---
name: capability-build
description: Turn one capability card into a working mechanical check in whatever stack the project actually uses, prove it by watching it fail on a real violation with its remediation text visible, wire its enforcement point, and update its status in the register.
---

# capability-build

A card in `docs/capabilities/` is a promise that some invariant will stop
being enforced by a human reading carefully. This pass keeps that promise for
exactly one card: it builds the check, proves it catches what it claims, puts
it where it cannot be skipped, and records the new status. Everything about
what the card means belongs to the card and to
`docs/capabilities/CARD_FORMAT.md`; this file is how one gets built.

## When to invoke

Invoke it when a card is worth building now: the invariant is being checked
by hand repeatedly, or a rung on the ladder in `docs/MATURITY.md` is gated by
that card and the project wants the rung. One card per pass — a pass that
builds two checks cannot report which one the failing case proved.

Do not invoke it to write or repair a card. If the card does not exist, or
its invariant is an aspiration rather than a decidable property, there is
nothing to build yet: the specification is the work, and it is the card's own
change to make. Do not invoke it to claim a rung either; the ladder's
promotion rule is the ladder's, and it needs green cycles this pass cannot
produce.

## Read before building

- The card, whole. Its invariant is the contract, its acceptance is the proof
  you must produce, and its remediation text is the output your check emits.
- `docs/capabilities/CARD_FORMAT.md` — what each section of a card means and
  what a status transition requires.
- `docs/capabilities/index.md` — current statuses and the concrete places
  other checks are already enforced. A second enforcement mechanism beside an
  existing one is a maintenance cost for nothing.
- `docs/MATURITY.md` — which rung this card gates and what the promotion rule
  will lean on it for. A gate that over-claims is worse than an absent one,
  because trust gets transferred to it.
- `AGENTS.md` — the commands this project publishes, since the cheap
  verification command is usually the enforcement point.
- `ARCHITECTURE.md` — for any card whose invariant is a dependency rule; the
  layer map is the specification of what the check must decide.
- The project's real toolchain: what language it is in, what runner or task
  file exists, what already runs on commit and in continuous integration, and
  what dependencies it already carries.

## Build

1. **Confirm the card is buildable.** The invariant must be decidable without
   judgement, the acceptance must carry a failing case written as an
   instruction someone can follow, and the remediation text must name an
   offender and a next action. A missing piece stops this pass; report which.
2. **Choose the mechanism inside what exists.** Extend the pass this project
   already runs before adding a new tool, and prefer the plainest thing that
   decides the invariant. A card's per-stack hints are starting points, not
   requirements; the constraint that matters is that a contributor can run the
   check locally without setup.
3. **Implement the decision, not an approximation of it.** Where the check
   cannot cover the whole invariant, cover the part that is decidable exactly
   and keep the remainder out — then say so in the card as a stated
   limitation with the owner of the uncovered part named. A check that
   half-decides an invariant is the failure mode where everyone believes the
   property holds.
4. **Make failure useful.** Nonzero exit, and output built from the card's
   remediation text with the real offender substituted: file, line, symbol,
   whichever locates it. It names what was violated, where, and what to do
   next, because the failure message is the only documentation read at the
   moment someone is wrong.
5. **Make success legible.** One brief line on a clean run stating what was
   checked and how much of it. A check that prints nothing cannot be
   distinguished from a check that found nothing to examine, and the second
   one passes forever.
6. **Run the passing case** on a clean tree, and confirm the count it reports
   is greater than zero. An empty scope is the most common silent failure —
   a wrong path, a glob matching nothing, a filter that excludes everything.
7. **Run the failing case exactly as the card instructs.** Introduce the
   violation, run the check, and observe both the nonzero exit and the
   remediation text in the output. Then revert the violation and observe the
   pass return. If the check does not fail on a violation, the check is
   wrong — do not adjust the card to match what was built.
8. **Wire the enforcement point the card names**, and confirm it fires there
   by triggering it in that context rather than only from a shell.
9. **Update the register row** in `docs/capabilities/index.md`: the status,
   and the concrete command, hook, or job under the column that records where
   it runs. `built` requires the observed failing case. `enforced` requires it
   to run somewhere it cannot be quietly skipped.
10. **Record what you observed** — the violating change, the exact command,
    and the failure text it printed — in the plan that authorized this work,
    never into the card. Where that evidence lives, and why the card must not
    absorb it, is stated in `docs/capabilities/CARD_FORMAT.md`.

## Never

- Never mark a card `built` on the strength of a check that has only been
  seen to pass. The promotion bar in `docs/capabilities/CARD_FORMAT.md` is
  there because a status resting on an undemonstrated check asserts nothing.
- Never write a status onto a card file. Status has one home, and a second
  copy of it goes stale in whichever place is read less.
- Never weaken the invariant so the check passes. A violation the check finds
  in the existing tree is a finding to route, not a reason to narrow the
  card.
- Never ship a failure message that names neither the offender nor the next
  action. A message forcing the reader to re-derive what the check already
  knew is why checks get switched off.
- Never land the check as advisory, warning-only, or excluded from the gate to
  get it in. A gate that does not block is a gate the ladder must not count.
- Never add an allowlist or exclusion entry for a real violation. Exclusions
  exist for cases the invariant was never about, and each one carries its
  reason.
- Never build two invariants into one check, however related they look. The
  card format allows one per card precisely so a failure is actionable.
- Never introduce a dependency the project does not already have without
  recording it where a contributor will find it before the check fails for
  them.
- Never leave the violating change in the tree after the demonstration.

## Stop condition

Stop when one card's check exists, its passing and failing cases have both
been observed, its enforcement point is wired and confirmed to fire there,
its register row carries the new status and where it runs, and the evidence
is written into the plan. Report the card, the mechanism chosen and what it
was built on, the exact failure output observed, the status transition, and
any part of the invariant the check does not decide. Then stop: the next card
is a separate pass with its own proof.
