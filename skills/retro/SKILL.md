---
name: retro
description: Reconstruct what a finished piece of work intended versus what it actually did from the evidence it left, test each difference for materiality, and route every material lesson to exactly one owning artifact — or to no change, explicitly.
---

# retro

A project learns nothing from work that merely ended. This pass reads the
record a finished plan left behind, finds where reality diverged from
intention, and puts each lesson worth keeping into the one file that owns it.
Its output is edits to artifacts, not a document about the past.

## When to invoke

When a plan's milestones are all done, before it leaves `plans/active/` —
the lifecycle in `plans/PLANS.md` says what completion requires, and this
pass is how the lessons half of it gets decided. Also after a single episode
expensive enough to stand on its own: a milestone that had to be re-cut
twice, an acceptance that could not be met, a decision reversed under
implementation.

Not for a change that finished inside one session with no surprises: there
is no divergence to reconstruct, and a retro that manufactures one produces
rules nobody needed. Not as an assessment of an agent or a person. The
subject is the artifacts and the process that produced the outcome.

## Read before concluding

- The plan itself, whole: what each milestone said it would produce and what
  acceptance it stated, then the progress record, the recorded surprises, the
  decisions with their rejected alternatives, and the revision notes that
  show where the plan changed under contact.
- `GOALS.md` — the anchor the work is graded against. Outcomes, success
  conditions, scope, non-goals. A plan that delivered its milestones while
  drifting outside scope is a finding that only this file exposes.
- `docs/PRINCIPLES.md` — what the project already decided outranks
  convenience, so a lesson is not proposed as new when it exists as a rule.
- `docs/capabilities/index.md` — the invariants a machine already decides
  here, so a lesson about a check performed by hand over and over routes to
  a card rather than to another paragraph of prose.
- `docs/DEBT.md` — whether a difference the plan hit is already a known,
  deliberately deferred item.
- `plans/PLANS.md` — what the convention requires at completion, and the bar
  that recorded evidence had to meet.

## Reconstruct

Build two accounts and compare them. Intended: what the plan committed to
before execution — the purpose, each milestone's scope, the acceptance as
authored. Actual: what the evidence says happened — which acceptance checks
ran and printed what, where a carve-out was named, where a milestone split,
where a decision was superseded, what took a second attempt.

Differences are the material. Resist explaining them away; an explanation is
what the plan already recorded, and this pass is interested in whether the
difference was structural. Also read the absences: acceptance nobody could
run, a contract a later session had to invent, a surprise that appears in one
milestone and again in the next.

## The materiality test

A difference earns a lesson only if it passes all three questions. If any
answer is no, it routes to no change.

1. **Will it recur?** It already happened more than once, or the structure
   guarantees it happens again. A one-off caused by circumstances that no
   longer exist teaches nothing transferable.
2. **Does it cost more than its fix?** Against the cost of the artifact edit
   plus every future reader of it. A rule that costs more to carry than the
   mistake costs to repeat is a net loss, and a file of them is why nobody
   reads the file.
3. **Can it be stated as something checkable or applicable?** Either a
   property a machine could decide, or a rule a reader can apply to a
   concrete case without interpretation. "Be more careful" fails this and is
   the most common thing a retro produces.

Record the no-change conclusions with the question that failed. An
undocumented no-change is indistinguishable from an oversight, and the next
retro re-examines the same difference from scratch.

## Route to exactly one owner

Each material lesson goes to one file, chosen by what kind of thing the
lesson is:

- a statement of how the system now behaves → a file under `docs/specs/`,
  indexed in `docs/specs/index.md`;
- a rule that must outrank local convenience → `docs/PRINCIPLES.md`;
- reasoning that will be re-litigated once its context is forgotten → a
  record in `docs/decisions/`, in the shape
  `docs/decisions/DECISION_FORMAT.md` defines;
- a property a machine could decide instead of a human re-checking → a new
  card in `docs/capabilities/` with its register row, left unbuilt;
  building it is separately authorized under
  `skills/capability-build/SKILL.md`;
- a procedure an agent will repeat → the skill under `skills/` that owns that
  procedure;
- work that is real but deliberately not being done now → a row in
  `docs/DEBT.md` with its trigger;
- a correction to what this project is for or will not do → `GOALS.md`;
- a defect in how work itself is planned, sized, or evidenced →
  `plans/PLANS.md`, whose edit obliges the audit that
  `skills/doc-garden/SKILL.md` owns;
- nothing, with the failed question named.

One owner, always. A lesson that seems to need two homes is either two
lessons that separate cleanly, or one lesson pitched at the wrong altitude —
split it or restate it until each half lands in one file. Writing it in two
places produces two texts that drift apart, and afterwards no reader can tell
which one is current.

## Close

Write the plan's closing retrospective section: purpose against outcome, what
was not achieved and remains open, and where each lesson went — the routed
ones by owner, the discarded ones by the question they failed. Then make the
routed edits, each in its own commit so a reviewer can accept or reject one
lesson without the rest. Graduating a plan's durable decisions, reflecting
behavior into specs, and moving the file are the convention's lifecycle
steps; follow `plans/PLANS.md` for them rather than inventing an order here.

## Never

- Never route one lesson to two owners, and never copy a lesson's sentence
  into a second artifact "for visibility".
- Never invent a lesson to make the pass feel productive. "Nothing material"
  is a legitimate result and must be written as one, with reasons.
- Never grade a person, an agent, or an effort level. The unit of analysis is
  the artifact that failed to prevent the mistake.
- Never edit the plan's evidence so the record agrees with the conclusion.
  The conclusion is derived from the record; reversing that direction erases
  the only account of what happened.
- Never create a new artifact or a new skill for a lesson an existing owner
  covers. One file per lesson is how a knowledge layer becomes unreadable.
- Never treat unmet acceptance as evidence that the acceptance was wrong
  until the alternative is ruled out: that the milestone was too large, or
  that its acceptance was never runnable in the first place.
- Never leave a lesson routed to a card as though the invariant were now
  enforced. A card is a specification, and nothing is being checked until it
  is built and demonstrated.

## Stop condition

Stop when every reconstructed difference and recorded surprise has a
disposition — one named owner, or no change with the failed question — the
routed edits are committed, and the plan's closing section states the
comparison and the routing. Report the differences found, the lessons routed
with their owners, the ones discarded with their reasons, and anything the
pass could not decide. Do not also perform the work the lessons imply: a card
written here is unbuilt, and a debt row recorded here is unpaid.
