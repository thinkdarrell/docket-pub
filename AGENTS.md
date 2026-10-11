# {{FILL: project name}} — agent guide

<!--
GUIDANCE — MARKERS
  {{FILL: ...}} is a slot you must replace with real content.
  Every HTML comment block in this file starts with the word GUIDANCE and is
  an authoring instruction. Delete all of them once the file is filled; they
  are scaffolding, not project content.
  A template file is fully filled when `grep -rn '{{FILL' <file>` and
  `grep -rn GUIDANCE <file>` both come back empty.

GUIDANCE — WHAT THIS FILE OWNS
  The entry-point map for any agent working in this repository: what the
  project is in one paragraph, where every other artifact lives and what
  that artifact owns, the commands agents run, and the rules agents follow.

GUIDANCE — WHAT IT MUST NOT ABSORB
  Architecture detail (`ARCHITECTURE.md`), rationale (`docs/decisions/`),
  behavior descriptions (`docs/specs/`), invariant specs
  (`docs/capabilities/`), or any plan content (`plans/`).

GUIDANCE — ANTI-PATTERN THIS FILE EXISTS TO PREVENT
  The encyclopedia: an agent guide that grows to hundreds of lines, is
  re-read in full at the start of every session, and rots because no
  individual claim in it has an owner. Every line here is a per-session
  context tax paid by every future agent. Hard cap is about 100 lines. When
  a section wants to grow, move it into `docs/` and leave one map line
  pointing at it.
-->

{{FILL: one paragraph — what this project is, who or what it serves, and the
single most important thing an agent should understand before editing it.}}

## Map

<!--
GUIDANCE
  This map is the ownership registry: each line names an artifact and what
  it owns, so an agent can route a new piece of knowledge to exactly one
  file. Delete lines for artifacts this project deliberately does not have —
  a map entry pointing at a missing file is a broken cross-link, and
  omission is a legitimate right-sizing choice for a small project. Record
  such omissions in `GOALS.md` under scope.
-->

- `GOALS.md` — purpose, outcomes, success conditions, scope, non-goals,
  constraints, known unknowns. Read first.
- `ARCHITECTURE.md` — components, layer map, allowed dependency directions.
- `docs/PRINCIPLES.md` — the few rules that override local convenience.
- `docs/MATURITY.md` — the autonomy ladder and what gates each rung.
- `docs/DEBT.md` — known debt and deferred work, each with enough context to
  pick up cold.
- `docs/decisions/` — one short file per durable decision.
- `docs/specs/` — living descriptions of how the system currently behaves.
- `docs/capabilities/` — spec cards for mechanical enforcers, with status.
- `plans/PLANS.md` — the plan convention. All multi-file or multi-session
  work follows it.
- `plans/active/` — work in flight. `plans/completed/` — done.

## Commands

<!--
GUIDANCE
  Only commands an agent actually runs, with the exact command line. The
  cheap verification command matters most: it is the one an agent can run
  after every edit without thinking about cost. If the project has no such
  command yet, say so here and track it as the `fast-verify` capability
  card rather than leaving this section aspirational.
-->

- Verify (cheap, safe to run after any edit): {{FILL: command}}
- Full test suite: {{FILL: command}}
- {{FILL: build / run / lint commands, or delete this line}}

## Working rules

<!--
GUIDANCE
  Rules an agent must follow in this repository. The first six below are the
  harness contract and should survive unchanged; add project-specific rules
  under them. A rule belongs here only if an agent could plausibly violate
  it while doing ordinary work.
-->

- Multi-file or multi-session work requires an ExecPlan per `plans/PLANS.md`.
- Execute one milestone per session. Update every living section
  `plans/PLANS.md` requires, with observed evidence. Stop.
- Never report a planned command as passing evidence. Run it, record what you
  observed.
- Decisions with lasting effect go in the plan's Decision Log; durable ones
  graduate to `docs/decisions/`.
- Nothing material lives outside the repo. If it was decided, it is written
  here.
- This file is a map, not an encyclopedia. Keep it under ~100 lines; content
  that wants to grow moves into `docs/` and leaves a one-line map entry.
- {{FILL: project-specific rules — or delete this line if there are none}}
