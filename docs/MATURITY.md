# Maturity ladder

## Current rung

L0, human-gated. Two cards in `docs/capabilities/index.md` are `built`: `fast-verify`, which is `./tools/verify` (every non-live test tier on a disposable database plus the judge fixtures, one summary line per check, about 150 seconds), and `judge-milestone`, which is `tools/judge-milestone` with its eight-case self-test running inside verify. Both were seen to fail on a deliberately broken tree before promotion. Nothing is `enforced` yet: verify runs when a session chooses to run it, not where it cannot be skipped. The one thing moving this project toward L1 is twenty consecutive landed changes with `./tools/verify` green and no check skipped or made advisory, counted from the merge of the `plan/factory-tools` branch. `evidence-check` stays `specced`: the judge's `snapshot` mode decides its two facts for one plan, but the card asks for a check over every plan in `plans/active/`, and that aggregation is a separate small build.

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
