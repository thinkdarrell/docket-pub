# Maturity ladder

<!--
GUIDANCE — MARKERS
  {{FILL: ...}} is a slot you must replace with real content.
  Every HTML comment block in this file starts with the word GUIDANCE and is
  an authoring instruction. Delete all of them once the file is filled.

GUIDANCE — WHAT THIS FILE OWNS
  How much an agent is allowed to do without a human in the loop, today and
  later. It holds the rung definitions (L0 through L3), the rule by which a
  project moves up a rung, the rule by which it falls back down, and which
  mechanical checks from `docs/capabilities/` gate each rung.

GUIDANCE — WHAT IT MUST NOT ABSORB
  How any individual check works or what it enforces — that is the owning
  spec card in `docs/capabilities/`. This file only names cards and states
  what they must subsume before a gate can retire.

GUIDANCE — ANTI-PATTERN THIS FILE EXISTS TO PREVENT
  Autonomy by drift: nobody decides an agent may now merge unreviewed work,
  it just gradually stops being reviewed, and the first serious failure has
  no one to attribute it to. Naming the current rung makes the level of
  trust a written, revisable claim. The mirror failure is autonomy by
  optimism — granting a rung because the agent has been doing well rather
  than because a check now catches the class of mistake the human gate was
  catching.

GUIDANCE — WHAT TO EDIT HERE
  The rung definitions, the promotion rule, and the demotion rule below are
  generic and should survive unchanged; they are the ladder, not this
  project's position on it. What this project owns is the Current rung
  section, the green-cycle count if twenty is wrong for this change rate,
  and the Gating capabilities table, whose rows must name only cards that
  exist in `docs/capabilities/`. Every project starts at L0 and most stay
  below L2 for a long time. Keep the higher rungs written anyway: they are
  what make the current rung a deliberate position rather than the only
  thing anyone imagined.
-->

## Current rung

{{FILL: the rung this project is on today, and the single thing that would
have to become mechanical for it to move up.}}

## Rungs

Four rungs, from fully human-gated to bounded autonomy. Each states what the
agent may do unsupervised, what still requires a human, and what evidence
every change carries. The definitions are deliberately concrete enough that
two people looking at a landed change agree on which rung it was performed
under.

### L0 — Human-gated

The agent may read, plan, implement, run whatever checks exist, and revise its
own work. It may not merge. A human reads every change before it lands, and
approves every edit to `GOALS.md`, `docs/PRINCIPLES.md`, `ARCHITECTURE.md`,
and every capability status change.

Evidence every change carries: the plan's living sections updated with output
the agent actually observed, including the commands it ran and what they
printed.

### L1 — Self-verifying

A cheap verification command exists and is enforced, so "this works" is a
claim a human can re-check in one command instead of by reading. The agent may
land changes whose entire risk surface is covered by enforced checks; anything
outside that surface — public interfaces, the knowledge artifacts named at L0,
anything with no check behind it — still needs a human.

Evidence every change carries: the verification command's own output, recorded
in the plan, plus the statement of which parts of the change the enforced
checks do not cover.

### L2 — Agent-reviewed

A reviewing agent reads the change before a human does, and reviews against
the artifacts — principles, architecture, the card set, the plan's acceptance
— rather than against taste. The human reviews escalations and a sample. This
rung requires the structural checks to be enforced, because a review pass is
otherwise the only thing between drift and the repository.

Evidence every change carries: the review record, naming what it checked and
what it could not check, alongside the verification output from L1.

### L3 — Bounded autonomous classes

For named classes of work, the agent plans, implements, verifies, and merges
with no human in the loop. The classes are listed explicitly and their
boundary is mechanically decidable — a change touching a file outside a
class's allowed set is not in that class and falls back to the rung below.
There is no general autonomy at L3, only enumerated autonomy.

Evidence every change carries: the L1 and L2 evidence plus a per-class audit
trail a human samples at a stated cadence, which is what makes the boundary
claim checkable after the fact rather than at the moment of merge.

## Promotion rule

Trust is transferred to machinery, never to reputation. A rung may be claimed
only when every card in the Gating capabilities table for that rung has status
`enforced` in `docs/capabilities/index.md`, and every one of them has been
green for twenty consecutive landed changes with no gating check disabled,
skipped, or made advisory during that run. A named human confirms the claim in
the commit that edits the Current rung section above.

"The agent has been doing good work" is not an input to this rule. The
question is never whether the agent is trustworthy; it is whether the specific
mistake the human gate was catching is now caught by something that runs every
time.

## Demotion rule

<!--
GUIDANCE
  Demotion has to be as mechanical as promotion, or the ladder only ever
  points one way. Keep all three triggers; add project-specific ones under
  them if some class of escape is peculiar to this project.
-->

The current rung drops by one immediately on any of three triggers: a failure
escapes that a gating card was supposed to catch; a gating card leaves
`enforced` by being disabled, skipped in continuous integration, or made
advisory; or a gating check is spot-checked against a violation and fails to
fail.

Re-earning the rung requires more than restoring the previous state. The gate
must first be extended to catch the case that escaped, demonstrated with the
failing case its card requires, and the green-cycle count then restarts from
zero. The drop and the reason are recorded in the Current rung section, since
a ladder with no record of falling reads as one that only ever rose.

## Gating capabilities

<!--
GUIDANCE
  One row per gate. The card must exist in `docs/capabilities/` and its
  status there must be `enforced` before the rung it gates can be claimed.
  Name only cards that exist; a row pointing at an imagined check is how a
  rung gets claimed on paper. Delete rows for cards this project deleted
  during right-sizing, and add rows for cards it wrote itself.
-->

| Rung | Gating card | What it must subsume |
| --- | --- | --- |
| L1 | `fast-verify` | a human re-running the project's checks by hand before believing a change works |
| L1 | `evidence-check` | a human reading each active plan to confirm its record was updated |
| L2 | `doc-integrity` | a human noticing in review that a reference no longer resolves |
| L2 | `boundary-lint` | a human catching a dependency that points the wrong way |
| L2 | `isolated-env` | a human reproducing a result by hand before trusting it |

L3 has no row. The check that decides whether a change falls inside an
autonomous class is specific to the classes this project names, so it has to
be written as its own card before the rung can be claimed — and writing it is
the first real work of reaching L3.
