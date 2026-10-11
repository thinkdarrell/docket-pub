# Architecture

<!--
GUIDANCE — MARKERS
  {{FILL: ...}} is a slot you must replace with real content.
  Every HTML comment block in this file starts with the word GUIDANCE and is
  an authoring instruction. Delete all of them once the file is filled.

GUIDANCE — WHAT THIS FILE OWNS
  The shape of the system: the components that exist, what each one owns,
  where its code lives, and which components are allowed to depend on which.
  The dependency rules stated here are the specification that the
  `boundary-lint` capability card (see `docs/capabilities/`) mechanically
  enforces, so write them as rules a checker could evaluate, not as
  impressions.

GUIDANCE — WHAT IT MUST NOT ABSORB
  Why a component is shaped the way it is (`docs/decisions/`), what it does
  observably (`docs/specs/`), what is wrong with it (`docs/DEBT.md`), or
  planned changes to it (`plans/`).

GUIDANCE — ANTI-PATTERN THIS FILE EXISTS TO PREVENT
  Two failures, both fatal to an agent's ability to place new code. First,
  the file-by-file inventory: a listing of every module that rots within a
  week and teaches nothing about boundaries. Describe components and edges,
  never directory contents. Second, the undeclared layer map: with no
  written dependency direction, every agent invents a plausible one, import
  cycles accumulate, and no reviewer can point at the rule that was broken.

GUIDANCE — RIGHT-SIZING
  A single-component project still needs this file: fill Shape, name the one
  component, and state which external systems it may talk to. Delete the
  sections that would be empty rather than leaving headings with no content.
-->

## Shape

{{FILL: one paragraph — the system in the large. What runs, what it talks to,
and the single organizing idea a newcomer needs before reading any component
description below.}}

## Components

<!--
GUIDANCE
  One short entry per component. A component is a unit with its own
  responsibility and its own boundary — not a file, not a class. Each entry
  names where its code lives (repository-relative path), what it owns, and
  what it deliberately does not do. If you cannot state what a component
  does not do, the boundary is not yet real.
-->

### {{FILL: component name}}

- Lives in: {{FILL: repository-relative path}}
- Owns: {{FILL: the one responsibility}}
- Does not: {{FILL: the nearest responsibility that belongs elsewhere}}

### {{FILL: component name}}

- Lives in: {{FILL: repository-relative path}}
- Owns: {{FILL: the one responsibility}}
- Does not: {{FILL: the nearest responsibility that belongs elsewhere}}

## Layer map and dependency rules

<!--
GUIDANCE
  State the layers from outermost to innermost and the single allowed
  direction of dependency, then list every exception explicitly. Phrase each
  rule so that a violation is decidable by reading an import statement, for
  example "nothing under <path> may import from <path>". Exceptions are
  fine; undocumented exceptions are what make the map worthless.
-->

{{FILL: the layers, the allowed dependency direction, and each exception
with its reason.}}

## Cross-cutting invariants

<!--
GUIDANCE
  Properties that must hold across component boundaries — how errors
  propagate, what owns persistence, what may perform I/O, how configuration
  reaches code. Each invariant here is a candidate capability card: if it
  matters and can be checked mechanically, it should eventually be checked
  mechanically rather than remembered.
-->

- {{FILL: invariant}}
- {{FILL: invariant}}

## Known rough edges

<!--
GUIDANCE
  Places where the implementation does not match the map above, each with a
  pointer to its `docs/DEBT.md` entry. This section prevents the most
  expensive kind of drift: an agent trusting the map, finding reality
  different, and silently concluding the documentation cannot be trusted at
  all. Say where the map lies, and the rest of it stays believable.
-->

- {{FILL: where reality diverges from the map}} — tracked in `docs/DEBT.md`.
