# 0029 — The agent harness artifacts (AGENTS.md, GOALS.md, ARCHITECTURE.md, the docs tree, plans/PLANS.md) and the procedures under skills/ come from bholzer/factory-loop and are not edited locally. New multi-file work is planned under plans/PLANS.md; docs/superpowers/ is history.

## Decision

The agent harness artifacts (AGENTS.md, GOALS.md, ARCHITECTURE.md, the docs tree, plans/PLANS.md) and the procedures under skills/ come from bholzer/factory-loop and are not edited locally. New multi-file work is planned under plans/PLANS.md; docs/superpowers/ is history.

## Rationale

A local fork of the convention cannot take upstream fixes and drifts into a second convention nobody can audit. One plan format, the ExecPlan with its four living sections, is also what the factory's judge script parses to decide whether a milestone landed, so a second format would blind the judge. The design that commissioned this is docs/superpowers/specs/2026-10-10-factory-cycle-design.md.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-10-11)

## Status

accepted
