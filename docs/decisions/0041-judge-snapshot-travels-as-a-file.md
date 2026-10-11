# 0041 — Inside `cycle-run`, the judge's snapshot travels between the snapshot agent and the judge agent as a file under the system temporary directory, never as text inside a structured result.

## Decision

The snapshot agent writes `tools/judge-milestone snapshot <plan>` to `${TMPDIR:-/tmp}/cycle-run-<slug>-<start sha>.snapshot` and returns that path in its result; the judge agent reads the file by that path. The snapshot's contents are never carried in an agent's JSON return value, and no agent re-types them.

## Rationale

The snapshot is tab-separated with long keys, and the judge identifies a Progress entry by that key (decision `0035`). Carrying it as text would make an agent's transcription the only copy, and one mangled tab or trimmed space is a wrong verdict with nothing to compare it against. Both agents run on the same machine inside the same run, so a file is the smaller risk; it is a few hundred bytes, the start SHA in its name keeps two reruns from colliding, and it may be deleted between runs. The obvious alternative, returning the snapshot in the schema so the run's result is self-contained, trades a verdict's correctness for a tidier result object, and a verdict is the one thing in the run that must not be approximately right.

## Date

2026-10-11, the plan author (operator's session, Claude) in `plans/completed/factory-workflows.md`; graduated from the plan's Decision Log at its retrospective.

## Status

accepted
