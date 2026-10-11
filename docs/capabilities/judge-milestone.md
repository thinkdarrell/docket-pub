# judge-milestone

## Invariant

A session that executes a milestone of a plan under `plans/active/` lands
exactly one milestone, and lands it fully recorded. Decided from the git
history and the plan file alone, between the commit the session started on
and `HEAD`, that means all of the following hold: at least one new commit
exists; every new commit changes the plan file; exactly one Progress entry
went from open (`- [ ]`) to done (`- [x]`); that entry carries a date, where
any `YYYY-MM-DD` anywhere on its line counts, in parentheses, in square
brackets, or bare; no entry that was done at the start is open at the end;
and `git status --porcelain` prints nothing. A plan whose Progress,
Surprises & Discoveries, Decision Log, or Outcomes & Retrospective section is
missing or empty cannot be judged at all, and is refused before the session
starts.

`plans/PLANS.md` owns why these rules exist (one milestone per session,
observed evidence, no uncommitted work). This card owns only the decision.
Whether the recorded evidence is true is out of scope, as it is for
`evidence-check`; the judge does not run tests, and the caller runs
`./tools/verify` as a separate step after the judge says the record advanced.

## Enforcement point

Two places. The judge's self-test, `tools/fixtures/judge/run`, runs as one
check inside `./tools/verify`, the cheap verification command named in
`AGENTS.md`; a wrong verdict on any of its eight cases fails `./tools/verify`.
The judge itself, `tools/judge-milestone`, runs between sessions: `snapshot`
before a session starts and `judge` after it ends. Until the `cycle-run`
workflow (the next plan) exists, the operator runs both by hand; once it
exists, `cycle-run` runs them, and exit 1 halts the loop on that plan while
exit 2 refuses to start a session on a plan whose record is defective.

## Acceptance

Passing case: from the repository root, `tools/fixtures/judge/run` prints one
`judge fixture: <case> ... ok` line for each of the eight cases and then
`judge fixtures: 8 of 8 passed`, and exits 0; `./tools/verify` includes a
`verify: judge-fixtures ... ok` line; and `tools/judge-milestone snapshot
plans/active/<plan>.md` exits 0 for every plan under `plans/active/`.

Failing case, for the self-test: in `tools/fixtures/judge/run`, change the
expected exit code in the line `assert clean-advance 0 advanced ...` from `0`
to `1` and run `./tools/verify`. Observe the runner print `judge fixture:
clean-advance FAILED (want exit 1 word advanced; got exit 0: ...)` and `judge
fixtures: 1 of 8 failed: clean-advance`, and verify print `verify:
judge-fixtures ... FAILED` and exit nonzero. Revert the change.

Failing case, for the judge: in a scratch git repository holding a plan with
the four living sections, take `tools/judge-milestone snapshot plan.md >
snap`, note `HEAD`, tick one open entry with a date and commit it, then
commit a change to any other file without touching the plan, and run
`tools/judge-milestone judge plan.md snap <noted sha>`. Observe exit 1 and
the four-line halt below naming the second commit. Both halves must be
demonstrated before the card is `built`; the first shows the self-test can
fail, the second shows the judge can.

## Remediation message

The judge halts with four lines: the plan, the entry it stopped on (or `no
entry`), the rule that failed, and what to do next.

    judge: halt plans/active/add-search.md
    judge: entry "(2026-04-08 11:20Z) M2: index writer"
    judge: commit 3f9c2ab did not touch the plan.
    judge: Fix the cause, commit in the worktree, and re-run.

The third line is one of: `no commit landed since <sha>.`; `commit <sha> did
not touch the plan.`; `<n> Progress entries changed state (exactly one
must).`; `entry at line <n> is ticked but carries no date.`; `entry "<text>"
was done at the start and is no longer.`; `the working tree has uncommitted
changes.`

When the plan's record is structurally defective, the judge refuses instead
of halting, with one line and exit 2:

    judge: defect plans/active/add-search.md is missing the required section `## Decision Log`

The self-test reports a wrong verdict by case name:

    judge fixture: untouched-commit         FAILED (want exit 1 word halt; got exit 0: advanced "...")
    judge fixtures: 1 of 8 failed: untouched-commit
