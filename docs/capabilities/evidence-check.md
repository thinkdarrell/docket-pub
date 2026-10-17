# evidence-check

## Invariant

Every plan file in `plans/active/` carries the living sections the plan
convention requires — Progress, Surprises & Discoveries, Decision Log, and
Outcomes & Retrospective — each present and non-empty, and every Progress
entry marked complete carries a timestamp.

`plans/PLANS.md` owns what those sections mean and why they exist. This card
owns only the two mechanically decidable facts: the sections are there, and a
completed entry says when it completed. Those are exactly the failures that
appear when a session runs out of room — the work lands, the record does not,
and the next fresh-context session inherits a plan that no longer describes
the state of the tree.

Deliberately out of scope: whether the recorded evidence is true. "Never
report a planned command as passing evidence" is a judgement about text no
checker can make, and it stays a working rule in `AGENTS.md` enforced by
review. A check that claimed to verify it would be the vague wish that
`CARD_FORMAT.md` in this directory warns about — passing on everything,
failing on nothing, and trusted anyway.

An empty `plans/active/` is a passing state, not an error: the check says
there are no active plans and exits zero.

## Enforcement point

`tools/check-plans`, the sixth check in `./tools/verify` (the cheap
verification command named under Commands in `AGENTS.md`), over every file in
`plans/active/`. The same script with `--staged` is `tools/hooks/pre-commit`,
which runs on any commit that stages a file under `plans/active/` in a clone
where `core.hooksPath` is set to `tools/hooks` (`docs/specs/operations.md`
Local environment), because that is the moment the record is cheapest to fix.
Both decide each plan with `tools/judge-milestone snapshot`.

## Acceptance

Passing case: on a clean checkout the check exits zero and prints one line per
active plan naming the four sections it found, or a single line stating that
there are no active plans.

Failing case: in an active plan, delete the `## Decision Log` heading and run
the check — observe a nonzero exit naming the plan file and the missing
section. Restore it, then mark any Progress entry complete without a
timestamp and run again — observe a nonzero exit naming the plan file and that
entry. Restore. Both halves must be demonstrated before the card is `built`,
because they are separate code paths and a checker that only counts headings
passes the second one blind.

## Remediation message

As built, for an undated tick (the defect line is the judge's; the two lines
under it are the check's own, each printed as one line):

    plans: plans/active/add-search.md ... FAILED
      judge: defect plans/active/add-search.md has a completed Progress entry with no date at line 15 ("M2: index writer")
      Completed entries record when the work was observed: - [x] (YYYY-MM-DD HH:MMZ) <entry>. Use the time you observed, not an estimate.
    plans: 1 of 1 failed

and, for a missing section (an empty section prints the judge's `carries the
required section ... with nothing under it` and the same guidance):

    plans: plans/active/add-search.md ... FAILED
      judge: defect plans/active/add-search.md is missing the required section `## Decision Log`
      plans/PLANS.md requires Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective in every plan. Add the heading and the entries the work produced; an empty section is also a failure.
    plans: 1 of 1 failed

## Per-stack hints

A shell script over `grep -n '^## '` and a date regex covers both halves in
under thirty lines and stays readable for whoever has to extend it. Where the
project already runs a markdown linter with custom rules, express it there
instead so plans are checked by the same pass as the rest of the docs.
Parsing the whole plan file is unnecessary: presence of headings, non-emptiness
between them, and a timestamp on completed checklist entries is the entire
contract.
