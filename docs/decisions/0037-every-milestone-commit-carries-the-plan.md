# 0037 — Every commit a milestone session lands changes the plan file by more than whitespace; a commit that leaves the plan untouched is work landed without a record, and the judge halts on it.

## Decision

In a session executing a milestone of a plan under `plans/active/`, every commit changes that plan file, and the change is more than whitespace. The plan edit in a commit is the record of what that commit landed: a progress note, an observation, a decision, a transcript. `tools/judge-milestone` enforces this as its second rule, and a session that breaks it is halted, not accepted.

## Rationale

The rule existed in the design document and in the judge's rule list from the start, but the first session of the factory-tools plan was briefed with "include the plan if you changed it in that step", committed its test fixes in two commits and the plan in a third, and the judge halted on M1. The reviewer accepted M1 by hand because the work and the record were consistent, and ruled that the rule stands from M2 on. The lesson of that halt is not that the judge was wrong; it is that a rule living only in a session brief is a rule nobody can audit, which is why it is recorded here and stated for sessions in `AGENTS.md` Working rules.

The obvious relaxation, requiring only that the last commit of a session touch the plan, was rejected. A session that dies after its code commits and before its plan commit leaves landed work with no record, which is exactly the failure the judge exists to catch; under the per-commit rule, a session that dies between commits leaves a record of everything that landed. The cost of the rule is small because `skills/plan-execute/SKILL.md` already asks that evidence be written as it is observed, so a commit made at a coherent step has a plan change to carry. Whitespace does not count since M5, when the review found that a trailing space satisfied the M3 judge; the check is `git diff --ignore-all-space --ignore-blank-lines` against the commit's parent, per commit, with a root commit compared against the empty tree.

## Date

2026-10-11, the reviewer (operator's session, Claude) after M1; graduated from the plan's Decision Log at its retrospective.

## Status

accepted
