---
name: harness-init
description: Bootstrap this harness into a repository that has none — orient in whatever is already there, interview for the facts no file can supply, right-size the artifact set, fill every skeleton, install the procedures, and report what was created and what was deliberately left out.
---

# harness-init

This is the one procedure that runs before the harness exists. It turns a
repository with no agent-facing knowledge layer into one an agent can work in:
a map, the goals and the boundaries, the architecture, the docs tree, the plan
convention, the capability register, and the procedures that operate all of
it. It runs once per repository, and it stops before that repository's first
real change.

## When to invoke

Invoke it where the layer is absent — no map at `AGENTS.md`, no convention at
`plans/PLANS.md` — whether the repository is empty or holds ten years of code.
An empty repository is the easy case: every answer comes from the interview.
An existing codebase is the ordinary case, where most answers are already in
the tree and the missing ones are the boundaries nobody ever wrote down.

Do not invoke it where the layer already exists. A half-finished artifact set
is a gardening job under `skills/doc-garden/SKILL.md`, and a deliberate change
to an artifact the project already has is ordinary work — multi-file ordinary
work being a plan under `skills/plan-author/SKILL.md`. Do not invoke it to add
a mechanical check: this pass installs specifications only, and
`skills/capability-build/SKILL.md` is what turns one into a check.

## Locate what you are installing

The artifacts are copied, never retyped from memory, and they come from the
checkout you invoked this procedure from. That checkout's own `AGENTS.md` map
names the directory holding them; read the map, confirm the directory, and
copy from there. Retyping produces a plausible imitation whose wording has
already drifted from the source on the day it is installed.

Two classes of file arrive. Skeletons carry content slots and authoring
guidance, and each one's guidance states what that file owns, what it must not
absorb, and the anti-pattern it exists to prevent — read a skeleton's guidance
before filling it, because this procedure deliberately does not repeat it.
Shrinking is not in every skeleton's guidance and is not meant to be; the
section below is where it is decided. The rest are kept exactly as they
arrive, `docs/capabilities/CARD_FORMAT.md` and
`docs/decisions/DECISION_FORMAT.md` among them: a target project never edits a
format it is supposed to conform to.

## Right-sizing: what may be omitted, and when

The structure does not shrink. Every artifact in the map is named by some
procedure under `skills/`, so deleting one leaves a procedure pointing at a
file that is not there — and a procedure discovers that the first time
somebody invokes it, mid-task. A small project's artifacts are short, not
absent: for a one-component project, `ARCHITECTURE.md` is a paragraph, one
component entry, and the dependency rule that it talks to nothing else.

What does shrink is the starter capability register, which is project content
rather than structure. Leave a card out when the property it decides cannot
exist here — no layering to violate, no environment to isolate — or when
nobody would build it inside the horizon the project is planning for.
Omitting one means deleting three things together: the card file, its row in
`docs/capabilities/index.md`, and any row in `docs/MATURITY.md` that gates a
rung on it. A gate naming a card nobody has is worse than no gate, because the
rung above it looks earned.

Inside a file, delete a heading that would stand empty instead of leaving it
open. An empty heading reads as unfinished work and the next agent fills it
with invention.

If the owners nonetheless choose to omit an artifact, that is their decision
and not this pass's: delete its map line in the same edit, record the omission
in `GOALS.md` under scope so a later reader sees a choice rather than an
oversight, and name there which procedure just lost a reference. The
procedures themselves are never the thing that shrinks — they cite each other,
so a removed one dangles references inside the ones that remain.

## Procedure

1. **Orient.** Read the repository as it is before proposing anything: what it
   builds, how it is run and tested, which commands actually work, the shape
   of its directories, and the boundaries that shape implies. Write down the
   cheap verification command and the full test command you found. If neither
   exists, that absence is a finding for the register below, not a blank to
   fill with something plausible. In an empty repository this step produces
   one sentence and the interview does the rest.
2. **Interview for what the tree cannot say.** Purpose; who or what the
   project serves; the outcomes that would count as success; what is
   deliberately out of scope; the non-goals worth writing down because
   somebody will otherwise propose them; the constraints that outrank
   convenience, which are what `docs/PRINCIPLES.md` holds; and the questions
   the owners already know they cannot answer.
   Ask them in one pass. An answer nobody has becomes a recorded unknown —
   invented goals are worse than missing ones, because every future piece of
   work then gets graded against a fiction.
   One question is optional and asked in the same pass: where the artifact
   set and procedures being installed came from, and where that upstream
   keeps its guide for adopters. When the owners name a location, record it
   as one line in `GOALS.md` under scope, phrased as a location outside
   this repository — a URL or a checkout path — so no reference walk here
   is ever asked to resolve it; when they do not, write nothing, because
   provenance nobody supplied is provenance invented.
3. **Propose, then execute the answer.** State which artifacts will exist,
   which cards are kept, and which are left out with the reason for each.
   Right-sizing is the owners' call; this pass makes it visible before it
   becomes a tree full of files.
4. **Copy in one recursive pass**, then refuse to overwrite. If a destination
   path is already occupied, stop and reconcile that file deliberately: an
   existing guide or convention holds knowledge the copy would destroy, and
   merging it is a decision, not a step.
5. **Fill the skeletons, map last.** Goals and architecture first, then the
   docs tree, then the map — which by then describes what actually survived
   right-sizing. Replace every slot with real content and delete each file's
   guidance as you finish it, then confirm with the two searches the guidance
   itself names that no slot and no guidance block survives. Scaffolding left
   in a shipped artifact is a tax on every session that opens it.
6. **Start the ladder at the bottom.** In `docs/MATURITY.md` nothing is
   mechanically enforced yet, every card in the register is a specification,
   and the promotion rule stated in that file is the only thing that moves the
   rung. A higher rung claimed at bootstrap transfers trust to checks that do
   not exist.
7. **Seed `docs/DEBT.md` with what orientation found** and this pass is not
   fixing: the missing verification command, the boundaries the layout implies
   but nobody stated, the retrofit an existing codebase needs before a
   dependency check could pass on it. Each row carries why it is deferred and
   what ends the deferral, in the shape that file defines. A bootstrap
   reporting a clean slate over an old codebase is not believable.
8. **Install the procedures.** Copy the skill directories from that same
   checkout, whole and unedited, and add the map line naming `skills/` so a
   session starting cold can find them. They travel as a set.
9. **Make the entry points resolve in the environment you are in.** Two of
   them, and both are environment-specific rather than project-specific, so
   neither is written into the artifacts themselves. First, if the agent
   environment you are running in does not read `AGENTS.md` on its own, add
   one file at the repository root under the name that environment does read,
   holding nothing but a reference to `AGENTS.md` — that environment's
   include directive where it has one, a single pointing line where it does
   not. It owns no content of its own: a second guide is a second owner of
   every fact in the first. Second, if that environment loads procedures only
   from a location of its own choosing, make the installed set reachable
   there without moving it: by that environment's own configuration where it
   reads one from inside this repository, otherwise by a link created there
   and committed with the rest of the installation. Where every location it
   reads lies outside this repository, install nothing — a bootstrap
   configures the repository it runs in, never the machine it runs on — and
   leave the map's reference by path as the route, which is the one every
   environment can follow. The report this procedure ends with answers the
   two clauses separately: for the first, the entry-point file that was
   added or the reason the environment needed none; for the second, what
   was installed and where, or why nothing was. Installing nothing is an
   outcome, and it gets its own sentence rather than being left to be
   inferred from the other clause's answer.
10. **Verify by running, not by reading.** Walk every backticked
    repository-relative path across the filled artifacts and record what the
    walk reported; both finish searches come back empty; each card file has a
    register row and each register row a card file; every gating row names a
    card that exists; and the verification command now published in the map
    runs in this repository. Commit the installation.

    That walk does not come back empty here, and it is not meant to. The
    artifacts you just filled describe a project whose code is not written
    yet: the layering the owners stated, the module paths it is stated in
    terms of, the directories the first plan will create. Those paths are
    reserved rather than broken, which is the same judgement a reference
    check hands to a person and takes back as an allowlist key with a
    reason. Leave them written — an artifact reworded to cite only what
    exists today describes a project the owners did not describe — and open
    a row in `docs/DEBT.md` naming them, the keys that would excuse them to
    a reference check running here already, and what ends the deferral,
    which is the code arriving. The failure this step exists to catch is the
    third option: a walk run, read, and reported as though it had come back
    clean.
11. **Report.** What was created; what came from interview answers rather than
    from evidence in the tree; what was omitted and why; what went into the
    debt register; and what happens next — the project's first plan under
    `skills/plan-author/SKILL.md`, and its first mechanical check under
    `skills/capability-build/SKILL.md` once one is worth building.

## Never

- Never invent a project fact the interview could have supplied. An unanswered
  question is recorded as unanswered; a fabricated purpose or boundary is
  indistinguishable from a real one later, and it will be enforced as though
  it were.
- Never overwrite or delete a file the repository already had. Reconcile it in
  the open, or leave it and record the conflict.
- Never leave a content slot or a guidance block in an artifact you filled,
  and never declare a file finished without running the searches that decide
  it.
- Never keep a map line, a register row, or a gating row for something you
  left out, and never leave something out that a procedure names without
  writing down which reference just broke.
- Never claim a rung, a card status, or an enforced check that nothing
  demonstrates. When this pass ends, every card is still a specification.
- Never publish a command in the map that you did not run here. An
  aspirational command is discovered by the next agent, at the moment it
  needed to work.
- Never edit the arriving artifacts to suit this project instead of filling
  them. A defect in them is a change owned by the project they came from;
  patched here it becomes a fork nobody can update.
- Never install a partial set of procedures, and never drop one because this
  project seems not to need it. Each cites the others.
- Never begin the project's own work — no first feature, no first refactor,
  no first plan. Bootstrapping ends with an installed harness.

## Stop condition

Stop when the artifacts exist and are filled, the procedures are installed,
the entry point resolves, the checks in step 10 have been run and their
results recorded — clean, or with the reserved paths carried as a debt row —
and all of it is committed. Report what was created, what was
deliberately omitted with its reason, and what was deferred; then name the
next step without taking it. The first plan is authored in its own session, by
the procedure that owns authoring.
