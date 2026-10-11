---
name: plan-execute
description: Execute exactly one milestone of an existing ExecPlan in a fresh session — read the plan and only what it names, do that milestone's work, record observed evidence in the plan's living sections, and stop.
---

# plan-execute

Take one plan under `plans/active/`, execute its next unfinished milestone,
write back what you observed, and stop. `plans/PLANS.md` is the governing
convention; this file is the procedure for one session under it, not a second
copy of its rules.

## Assume only the file and the worktree

There is no conversation history behind you and none ahead. What the
repository does not say did not happen, and what you learn during this session
exists only once it is written into the plan. If the plan is not self-contained
enough to act on — a path that does not resolve, an interface it never names,
acceptance nobody can run — that is a defect in the plan, and the repair is to
fix the plan under `skills/plan-author/SKILL.md`, not to guess and proceed.

## Read, in this order

1. `AGENTS.md` — the map, the commands available, and the working rules.
2. `plans/PLANS.md` — the convention the plan and your evidence are judged
   against.
3. The named plan, whole: its progress record first, so you learn what is
   actually done; then the milestone you will execute; then the contract and
   decision sections bearing on it, which is where earlier sessions left the
   names, formats, and spent identifiers you are required to reuse.
4. Only what the plan names, plus what those files point you to. Reading
   broadly for background spends the context the milestone itself needs, and a
   plan that requires unnamed background reading has a hole worth recording.

Execute the first unfinished milestone unless the plan designates another. If
the progress record and the repository disagree about what is done, the
repository is the fact and the record is the bug: correct the record, in a way
that shows it was corrected, before starting work.

## Execute

Observe the starting state before editing: run the cheap verification command
from `AGENTS.md` first. A failure that was already there is a finding to
record, and it is not this milestone's job to quietly absorb it.

Do this milestone's work and nothing adjacent to it. Improvements you notice
in passing go to `docs/DEBT.md`, or into the plan as a later milestone, or
nowhere — never into this commit, where they arrive unacceptanced and
unreviewed.

Resolve ambiguity inside the milestone's boundary instead of stopping to ask,
and record both the ambiguity and the resolution. Ambiguity about the
milestone's boundary is the exception: widening scope is not a resolution
available to this session.

Commit at each coherent step rather than once at the end — `plans/PLANS.md`
asks for frequent commits — so a session that dies leaves landed work rather
than a dirty tree.

Prove acceptance by running it. Every acceptance check the milestone states
gets executed, and what it printed is what you record. An acceptance check you
could not run is an unmet acceptance, and the milestone is complete only with
that gap named.

## Write the evidence back

Write as you observe, not in a final push. Evidence recorded incrementally
survives a session that ends early; evidence deferred to the end is lost
exactly when it would have mattered most.

What the plan must hold before you stop: a timestamped progress entry naming
the milestone and any carve-out against its stated acceptance; the commands
you ran with concise, real results, linked rather than pasted when the output
is large; the decisions you made and why the alternatives lost; and the
contracts a later session would otherwise have to invent.

State divergence against the acceptance it diverges from, in the same session
that caused it. A completion claim with an unnamed deviation cannot be audited
by anyone later, which makes every other claim in the plan worth less.

## When the milestone will not fit

Split it in place, in the shape `plans/PLANS.md` requires: the progress record
shows what was completed and what remains, the split is logged as the decision
it is, the work so far is committed, and the session ends. Do not push on with
a context that has been summarized out from under you — evidence written from
a summary of observations is a recollection, and the next session cannot tell
which is which.

## Never

The first two restate rules `plans/PLANS.md` owns; they are here because a
session reads this file at the moment it is tempted to break them.

- Never start a second milestone. Finishing early is not permission; the
  cadence that advances milestones is not operated from inside a session.
- Never record evidence for a command you did not run, and never convert an
  expectation into a result. "Should pass" is not an observation.
- Never call a milestone complete while its acceptance is unmet. Either meet
  it, or name the shortfall against the specific acceptance clause and leave
  the entry honest.
- Never tidy the plan's history. Failed attempts and corrected mistakes stay
  visible, because they are the only record of what has already been tried.
- Never widen scope, refactor opportunistically, or fix unrelated breakage
  inside this milestone's commits.
- Never leave the tree in a state the next session cannot read: no
  half-applied edits without a progress entry describing them, no uncommitted
  work, no evidence held only in your own context.

## Stop condition

Stop when the milestone's work is committed, its acceptance is met or its
shortfall is named, and the plan's living sections carry the evidence. Report
the milestone executed, what you observed, any carve-out, and which milestone
is next. Naming the next one is a handoff, not a licence to begin it.
