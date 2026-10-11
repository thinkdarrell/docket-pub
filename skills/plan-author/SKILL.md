---
name: plan-author
description: Author or revise an ExecPlan for work spanning more than one file or one session, cutting it into milestones whose acceptance is observable, and stopping before any of the work is implemented.
---

# plan-author

Turn intended work into a plan file under `plans/active/` that a later agent,
holding nothing but that file and a checkout of the repository, can execute one
milestone at a time. This skill ends when the file exists. It never starts the
work the file describes.

## When to invoke

Work that touches several files, or that cannot finish inside one session,
gets a plan before it starts. So does work whose plan already exists but whose
milestones turned out to be the wrong shape — because a milestone nobody can
finish in a session is re-cut, not powered through — and a plan in flight that
has to be checked against a convention which changed under it.

A change one session finishes inside one file needs no plan. Authoring is not
free: the file is read in full by every session that touches the work, so a
plan for a small change costs more than the change.

## Read before writing

`plans/PLANS.md` is the contract this skill serves. Read it in full first,
every time; its requirements are not reproduced here, and a plan is judged
against it rather than against this file. Then read, for what each one
constrains:

- `GOALS.md` — scope and non-goals. Work outside them is not a milestone; it
  is a scope change, and it has to be agreed and written as one before a plan
  can contain it.
- `ARCHITECTURE.md` — components and which dependency directions are allowed.
  Work needing an edge the layer map forbids is a design question to settle
  while authoring, never a surprise to hand to an executing session.
- `docs/PRINCIPLES.md` — the rules that outrank local convenience, including
  in the plan you are about to write.
- `docs/capabilities/index.md` — which invariants are mechanically enforced
  here. An enforced check is acceptance you can borrow by naming it; an
  unenforced one is acceptance you have to state, and observe, by hand.
- `docs/DEBT.md` — whether this work trips a deferred item or pays one down.
- `docs/specs/` — the behavior that exists today and that your change alters.
- `plans/active/` — work in flight that touches the same files.
- The files the work will actually change. A plan authored without opening
  them names paths that do not exist and invents interfaces that do not fit,
  and both failures surface mid-milestone in someone else's session.

## Procedure

1. State the purpose as a difference an outside reader notices: what someone
   can do after the work that they cannot do now, and how they would see it.
   If the only honest answer is internal, say which observation stands in for
   it — a check that fails today and passes afterwards, for instance.
2. Research until every unknown is either settled in the plan or named as
   unknown. Where feasibility itself is in doubt, the first milestone is a
   prototype whose acceptance is a measurement, and the plan says what result
   promotes it and what result abandons it.
3. Write each candidate milestone's acceptance before its narrative.
   Acceptance is a small number of checks a different person can run or read
   and agree on: a command together with the output it prints, or a named
   artifact with a property that is true or false on inspection. Take the
   acceptance-first order seriously — it is the only reliable sizing test, and
   writing the story first produces milestones whose acceptance is invented
   afterwards to fit.
4. Size each milestone to one session, counting the whole session: reading the
   plan and the files, editing, running the checks, and writing the evidence
   back. Half a session of work with no room left to record it is an oversized
   milestone.
5. Order milestones so each one leaves the repository coherent. A milestone
   whose output only makes sense once the next one lands cannot be verified on
   its own, so it is either one milestone with the next or cut on a different
   seam.
6. Write down the contracts later sessions cannot rediscover: names and file
   layouts to be created, formats to conform to, identifiers already spent,
   and the reasoning behind each one. A fresh session re-derives none of this
   and will invent a second convention beside yours.
7. Initialize the living sections to the true current state. Nothing has been
   executed, so nothing is checked off and no evidence exists; the authoring
   decisions themselves, however, are decisions, and they belong in the log
   now while their alternatives are still in mind.
8. Reread the file in the position of the agent who will execute it, holding
   only this file and a checkout: every path repository-relative and real,
   every term of art defined where it is first used, every choice already
   made. Anything you would have to ask about is a hole to fill now.
   An expected command line is run before it is written down, as far as the
   first refusal the environment can produce without doing the work —
   argument parsing, authentication, a version banner — and the point it
   reached is recorded beside it. A line composed from individually correct
   flags is not a line anyone has run.
9. Commit the plan by itself, and report: its path, the milestone count, what
   the first milestone is, and what you deliberately left out of the plan.

## Revising a plan

Revisions keep the file's history legible: a correction is added alongside
what it corrects, and a superseded decision keeps its original text plus the
reason it was superseded. Rewriting the record to look as though the mistake
never happened destroys the only evidence that the alternative was tried.

When milestones are re-cut mid-flight, the state of partially finished work
stays visible in the plan rather than being absorbed into a new milestone
boundary, and the re-cut is itself a logged decision.

When a plan is audited against a convention that changed under it, record the
audit's outcome in the plan even if nothing needed to change — an audit that
leaves no trace has to be redone by the next person who wonders. What triggers
such an audit is not this skill's to declare.

## Never

- Never begin implementing. Authoring ends at a committed plan file, however
  small the first milestone looks; execution is separately authorized and runs
  under `skills/plan-execute/SKILL.md`.
- Never accept a milestone whose acceptance cannot be stated as a few
  observable checks. That milestone is too big, too vague, or not yet
  understood, and each of those is fixed by re-cutting rather than by more
  prose.
- Never phrase acceptance as an internal attribute — a type added, a file
  created, a function renamed. Those are steps; acceptance is what someone can
  now observe.
- Never write a command's output you did not obtain. At authoring time an
  expected transcript is labelled as expected, and no plan section may read as
  though work already happened.
- Never answer "this is too big for one file" with structure: not a child
  plan, not one file per milestone, not a per-phase hierarchy.
  `plans/PLANS.md` states the one composition that is allowed; use it instead
  of inventing a tree here.
- Never leave a decision to the executing session that your research could
  settle. Ambiguity costs a mid-milestone stall in a session that cannot see
  what you knew.
- Never write a placeholder milestone — "polish", "cleanup", "misc". A
  milestone with no acceptance is a wish with a checkbox.

## Stop condition

Stop when the plan file is written, self-contained, and committed, with every
milestone carrying acceptance and the living sections initialized. Report the
path and the first milestone, and stop there. Do not execute it, and do not
ask whether to.
