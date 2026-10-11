---
name: doc-garden
description: Sweep the repository's knowledge artifacts for drift — unresolvable references, statements that stopped being true, duplicated facts, unreflected outcomes, stale debt, plans left behind by a convention change — and land the smallest fix each finding needs.
---

# doc-garden

Entropy in a document system is silent: nothing breaks when an artifact
stops being true, so the cost lands on whoever reads it next and believes
it. This is the pass that goes looking. It finds drift, fixes what is small,
routes what is not, and reports what no command could decide.

## When to invoke

Run this pass on four occasions. When a convention or knowledge artifact
changed while work was in flight — `plans/PLANS.md` above all, because every
plan under `plans/active/` was authored against whichever text existed at
the time. When a plan has just finished, since completion is when specs
reflection and decision graduation are either done or quietly skipped. At a
cadence the project states — measured in landed changes rather than in days,
because drift tracks commits. And before authoring a plan whose research
will lean on these artifacts being accurate.

Do not run it inside a milestone's own commits: gardening widens scope into
files that milestone never claimed. Do not run it as a substitute for a
mechanical check that a card in `docs/capabilities/` already specifies —
that gap is built, not swept, under `skills/capability-build/SKILL.md`.

## The convention-change trigger

A commit that edits `plans/PLANS.md` obliges an audit of every plan in
`plans/active/` against the new text, and this pass owns that obligation.
Check each plan for the sections the convention now requires, for evidence
that meets its current bar, and for milestone acceptance still stated the
way it now demands. Record the outcome in each plan audited, in the decision
log `plans/PLANS.md` requires of it, including the plans that needed nothing
— an audit that leaves no trace gets run again by the next person who wonders
whether it happened, and a rule that fires only when somebody worries is not
a rule. How a plan is revised without erasing its history belongs to
`skills/plan-author/SKILL.md`.

## Read before sweeping

- `AGENTS.md` — the map, which doubles as the routing registry naming which
  file owns which fact, and the commands this project can actually run.
- `ARCHITECTURE.md` — the components, the dependency rules, and any
  structural correspondence this project declares between parts of its own
  tree. Those declarations are the sweep's specification: an invariant
  stated there and enforced by nobody is exactly what this pass checks.
- `docs/PRINCIPLES.md` — one-owner-per-fact and whatever else outranks local
  convenience, since most findings here are violations of these.
- `plans/PLANS.md` — what a plan must carry, for the plan sweeps below.
- `docs/capabilities/index.md` — which invariants are already checked by
  machine. Those you skip; run the check instead of re-deriving its result
  by reading.

## Sweep

Work from cheapest to most expensive, and prefer a command to a reading
everywhere the finding is decidable. Each sweep below is a separate question
with a separate answer; run all of them, and report the ones that found
nothing as well.

1. **References.** Every repository-relative path written in backticks or
   used as a link target resolves to something that exists. Four classes of
   miss are legitimate and get left alone: a sibling filename cited from
   inside the directory that owns it, an illustrative filename inside a
   format document, a path inside a fenced or indented block, which is
   transcript rather than citation, and a deliberate mention of a file that
   does not or must not exist. Everything else is a defect.
2. **Leftover scaffolding.** No artifact still carries a fill slot or an
   authoring-guidance comment block from the skeleton it was filled from.
   These are self-describing where they survive — an unfilled skeleton's own
   guidance explains its markers — so the sweep needs no external
   definition. A live artifact holding a placeholder is a file nobody
   finished.
3. **Statements that stopped being true.** Walk the claims that name
   concrete things — the map's entries, the component descriptions, the rung
   the ladder in `docs/MATURITY.md` claims and the gating rows behind it, the
   register in `docs/capabilities/index.md` against the card files beside it.
   Each of these says something about the tree that the tree can contradict.
4. **Duplicated facts.** Any sentence that appears in two artifacts is a
   finding, because one copy will go stale and no reader can tell which. The
   fix is deletion plus a pointer, never a synchronized edit to both.
5. **Unreflected outcomes.** Every plan in `plans/completed/` either has its
   observable outcome written into `docs/specs/` and indexed there, or says
   in its own closing section that there was nothing outward to reflect.
   Neither one present is the finding.
6. **Plan conformance.** Plans in `plans/active/` carry what the convention
   requires today, with progress that matches the tree rather than the tree
   as intended. A record contradicted by the repository is the record's bug.
7. **Debt.** Each row in `docs/DEBT.md` is still real, still deferred for the
   reason it states, and still carries enough for a cold reader to pick up.
   A row whose stated trigger has already fired is overdue, not deferred; a
   row whose item is quietly done is deleted.
8. **Declared correspondence.** Any structural invariant `ARCHITECTURE.md`
   declares between parts of this tree — counterpart files, mirrored
   structure, byte-identical copies — gets walked, using the comparison that
   file specifies rather than a naive diff, which reports false drift
   wherever a heading is itself content.

## Disposition

Every finding gets exactly one of four outcomes, chosen before anything is
edited.

Fix in place, when the repair is the smallest edit that makes the statement
true and touches only the artifact that owns it. One finding, one commit:
a sweep whose fixes arrive as one large commit cannot be reviewed or
reverted per finding.

Record in `docs/DEBT.md`, when the fix is real work rather than a correction
— with the reason it is deferred and the trigger that ends the deferral.

Hand to `skills/plan-author/SKILL.md`, when the repair spans several files or
needs more than one session. Gardening does not grow into a redesign.

Leave alone with the reason written down, when the apparent drift is one of
the legitimate classes above or a judgement the sweep cannot make.

## Never

- Never fix a finding by weakening what was claimed. If an artifact promises
  more than the tree delivers, the finding is the gap; softening the promise
  hides it and teaches readers that claims are decorative.
- Never resolve a duplicated fact by editing both copies. Two owners is the
  defect, not two divergent texts.
- Never add an exception, allowlist entry, or carve-out to make a real defect
  stop reporting.
- Never rewrite a plan's history while sweeping it. Corrections are added
  where the mistake is visible; a tidy record destroys the evidence of what
  was already tried.
- Never redesign, restructure, or improve prose that is merely not to your
  taste. This pass repairs untrue statements; style is not one.
- Never bundle unrelated fixes, and never carry a fix for a file the sweep
  did not find a finding in.
- Never report a sweep you did not run, and never infer a sweep's result from
  another sweep's outcome.
- Never leave a finding with no disposition. Silence on a finding is how it
  is found again, identically, next pass.

## Stop condition

Stop when every sweep has been run and answered, and every finding carries
one of the four dispositions. Report what was swept, what each sweep found,
which fixes landed, what was deferred or handed off, and which questions were
left to a reader because no command decides them. A pass that reports only
its fixes is indistinguishable from a pass that only looked where it already
suspected a problem.
