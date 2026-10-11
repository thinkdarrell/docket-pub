# 0038 — tools/judge-milestone takes the subcommands snapshot <plan> and judge <plan> <snapshot-file> <start-sha> rather than the --snapshot and --judge <start-sha> flags of design section 4, and exits 2 for "cannot decide" where the design named only exit 0 and exit 1.

## Decision

The judge's command line is `tools/judge-milestone snapshot <plan>` and `tools/judge-milestone judge <plan> <snapshot-file> <start-sha>`; every input a verdict depends on is an explicit argument. In `judge` mode, exit 0 is `advanced`, exit 1 is a halt (the session's record says the work did not land correctly), and exit 2 is a defect (the judge could not read the record: a required living section missing or empty, the plan absent at HEAD, the snapshot file missing, or a start revision the repository does not know). Section 4 of `docs/superpowers/specs/2026-10-10-factory-cycle-design.md` is history and is not edited; the as-built interface is the contract in `docs/capabilities/judge-milestone.md`.

## Rationale

The design sketched `--snapshot` and `--judge <start-sha>`, which implies a default snapshot location and a remembered plan path. Explicit arguments mean the judge has no hidden state: `cycle-run` passes exactly what it stored, two plans in flight cannot share a snapshot by accident, and a human can re-run the same command from a plan's Artifacts section and get the same verdict. The design's flag form described behaviour, not a command line, and nothing downstream had been written against it when M3 built the subcommands.

Exit 2 exists because a halt and a refusal need different handling. A halt means a human reads the four-line message and fixes the cause in the worktree; the loop on that plan stops. A refusal means the record itself cannot be read, which `cycle-run` must treat as "do not start a session on this plan" rather than "a session failed". The design already gave `snapshot` mode an exit 2 for a defective record, and factory-loop's `loop-runner`, which the judge adapts, draws the same line with the same code; `judge` mode matching them is the smaller surprise. M5 extended the refusal to an unknown start revision after the review found that a mistyped SHA produced the false halt "no commit landed".

Both departures were built in M3 and recorded only in M5, after the review panel found them undocumented. That gap is why this record exists: an as-built interface that differs from its design document and has no record of why invites a confident revert to the flags.

## Date

2026-10-11, the M3 session (Claude) for the shape, recorded by the M5 session; graduated from the plan's Decision Log at its retrospective.

## Status

accepted
