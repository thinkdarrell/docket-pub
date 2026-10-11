# 0034 — The milestone judge decides from the git history and the plan file alone; it never runs the test suite, and the caller runs ./tools/verify beside it as a separate step.

## Decision

`tools/judge-milestone` reads the plan at HEAD, the snapshot taken before the session, the commits since the start revision, and `git status`, and nothing else. It does not run tests. Whoever calls it (the operator by hand today, `cycle-run` when it exists) runs `./tools/verify` at HEAD as a second step after the judge prints `advanced`.

## Rationale

One check per concern. The judge answers "did the session land exactly one milestone and record it"; verify answers "does the tree pass its checks". A judge that also ran the suite would take over two minutes per verdict, and its twelve-case self-test, which builds twelve scratch repositories, could not run inside the verify budget `AGENTS.md` states. A verify that also judged the plan would fail a green tree for a record defect and a complete record for a red test, and the operator would read one message for two different remedies. Kept apart, a halt and a red are different lines with different fixes, and the fixture self-test stays a two-second check.

The obvious alternative, one script doing both, is the shape factory-loop's `loop-runner` had before its harness half was removed; the design document separated them (section 3 runs the judge and then verify as consecutive steps) and this plan kept that separation. A consequence to hold onto: the judge guarantees nothing about whether the recorded evidence is true. That is `evidence-check`'s concern and the reviewer's, and decision `0035` states what the judge does guarantee.

## Date

2026-10-11, the factory-tools plan author (Claude, for the operator); graduated from the plan's Decision Log at its retrospective.

## Status

accepted
