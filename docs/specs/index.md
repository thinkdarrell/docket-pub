# Behavior specs

<!--
GUIDANCE — MARKERS
  {{FILL: ...}} is a slot you must replace with real content.
  Every HTML comment block in this file starts with the word GUIDANCE and is
  an authoring instruction. Delete all of them once the file is filled.
  This index ships with no spec files beside it; that is the correct initial
  state. Fill the table as behavior lands.

GUIDANCE — WHAT THIS DIRECTORY OWNS
  How the system behaves right now, described from the outside: inputs,
  outputs, states, and the edges where it refuses. Written in the present
  tense, with no history and no plan. A spec is the answer to "what does it
  do today" for someone who will not read the code.

GUIDANCE — WHAT IT MUST NOT ABSORB
  Internal structure (`ARCHITECTURE.md`), reasoning (`docs/decisions/`),
  known wrongness (`docs/DEBT.md`), or the narrative of any change
  (`plans/`). If a sentence contains "now" or "used to", it belongs
  elsewhere.

GUIDANCE — ANTI-PATTERN THIS DIRECTORY EXISTS TO PREVENT
  Behavior truth rotting inside `plans/completed/`. A completed plan is an
  archive of one change, correct only as of the day it landed; three plans
  later, reconstructing current behavior means reading all of them in order
  and hoping none contradicts another. Specs collapse that stack into one
  present-tense description with a single owner.
-->

## The reflection rule

A plan does not complete until its behavioral outcome is reflected here.
Before a plan moves to `plans/completed/`, whatever a user or caller can now
observe that they could not before is written into a spec file in this
directory — as a new file, or as an edit to the file that already owns that
behavior — and listed in the index below.

A plan whose outcome is purely internal (a refactor, a dependency bump)
reflects nothing and says so in its own Outcomes section. Silence is only
acceptable when it has been stated.

Spec files are overwritten freely: they describe the present, so an edit
that contradicts last month's text is a correct edit, not a lost one. The
history lives in version control and in `plans/completed/`.

## Index

<!--
GUIDANCE
  One row per spec file. Keep the "Covers" column narrow enough that routing
  a new behavior to exactly one file is obvious; overlapping rows are how
  two files end up describing the same thing differently.
-->

| Spec | Covers |
| --- | --- |
| {{FILL: filename.md}} | {{FILL: the behavior this file owns}} |
