# 0035 — The milestone judge is a form check: it identifies Progress entries by their text with dates removed, counts as progress only an entry that was open in the snapshot and is done and dated at HEAD, halts when a done entry is lost, an open entry is gone, a commit left the plan unchanged beyond whitespace, or the tree is dirty, and guarantees nothing about the work itself.

## Decision

What `tools/judge-milestone` guarantees on `advanced` is exactly this: one or more commits since the start revision, each changing the plan by more than whitespace; exactly one entry that was open in the snapshot is done and dated at HEAD; no entry that was done at the start is open or missing; no entry that was open at the start is missing; the tree is clean. An entry's identity is its text lowercased with every date and run of punctuation removed, so an entry whose text changed during the session is, to the judge, one entry gone and another arrived. Nothing about the work, the tests, or the truth of the evidence is checked.

## Rationale

The review panel after M4 asked whether a judge that accepts a plan edit as proof of work is worth trusting. The reviewer's ruling, kept here, is that the judge is a form check and `./tools/verify` is the work check (decision `0034`); the form check is still worth having because the failure it catches, landed commits with no record, is the one a dead session produces and the one no test detects.

Keying entries by their text was carried over from factory-loop's `loop-runner` and kept against the alternative of a stable identifier per entry. The ExecPlan format in `plans/PLANS.md` has no such identifier, and adding one would be a local fork of the convention (decision `0029`). The cost of text keying is that rewording an entry reads as losing it: a done entry reworded reads as reverted, and an open entry reworded reads as removed. Both verdicts are accepted as correct. `plans/PLANS.md` already requires that corrections be appended rather than rewritten, so a reworded done entry is a rule broken, not a false halt. An open entry split in place, as `plans/PLANS.md` asks when a milestone will not fit, also halts as a removal; that is the right verdict for a session that ended without a milestone done, and the operator reads the halt and continues.

Two defects the review found were fixed in M5 and bind the rule set: an entry counts as newly done only if its key was open in the snapshot, so an invented ticked line cannot be the one that changed state, and a deleted open line is named in a halt rather than ignored; and a commit counts as touching the plan only when `git diff --ignore-all-space --ignore-blank-lines` against its parent is non-empty for the plan file. One loophole was recorded rather than closed: an invented ticked line added beside a legitimate tick still reads `advanced`, because the invented line simply does not count. The guarantee as stated above is not violated by it, M5's acceptance fixed the self-test at twelve cases, and a thirteenth case is the fix if the loophole ever matters. Before any rule runs, the start revision must resolve to a commit; otherwise a typo in the start SHA would read as "no commit landed", which sends the operator looking for the wrong thing. The split between a halt (exit 1) and a refusal (exit 2) is decision `0038`.

## Date

2026-10-11, the M3 and M5 sessions (Claude) and the reviewer (operator's session, Claude); graduated from the plan's Decision Log at its retrospective.

## Status

accepted
