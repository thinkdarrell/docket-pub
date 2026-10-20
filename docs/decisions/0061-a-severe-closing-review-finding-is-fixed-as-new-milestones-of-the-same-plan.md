# 0061 — A severe closing-review finding is fixed as new milestones of the same plan on the same branch, and the run is rerun

## Decision

When `cycle-run`'s closing review halts on a severe finding, the plan is revised in place with the milestones that fix it (open Progress entries, Decision Log entries recording what changed and what was declined, the milestone sections, and the Interfaces additions, with nothing already written reworded), committed as a plan revision, and `/cycle-run` is rerun with the same arguments; the rerun executes the new milestones and the closing review reads the whole range again.

## Rationale

The code a closing review names exists only on `plan/<slug>`, so a plan cut from `origin/main` by `cycle-plan` would have nothing to fix, and a fix committed by hand on the branch would land outside any milestone session, read by no judge and recorded in no plan (decision `0037`). A revised plan keeps one change's whole account in one file: the review record that found the defect, the decision that chose the fix, the milestone that made it, and the evidence it left. The cost is a second review record per rerun and a plan that grows with each round; `plans/completed/birmingham-city-briefing.md` carries three records after two halts. The alternative, a new plan per round, would split the history across files and leave the first plan completed with a severe finding on its branch. Milestones added this way are cut like any other: two were added each time because that round's code changes and its test additions were separable seams and together larger than the last milestone session.

## Date

2026-10-19, the operator and the plan author (Claude), in `plans/completed/birmingham-city-briefing.md`, chosen after the first closing review (21:40Z) and again after the second (23:30Z); graduated at the plan's retrospective on 2026-10-20.

## Status

accepted
