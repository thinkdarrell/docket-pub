# 0039 — `cycle-run` resumes after a halt by an idempotent rerun of the same command, not by the Workflow tool's result cache, and a halt names the agent label and stage rather than a transcript path; both depart from design section 7.

## Decision

A halted `cycle-run` is resumed by fixing the cause in the worktree, committing, and running `/cycle-run` again with the same arguments. The script is written so that a rerun is safe: preflight runs again, the snapshot is taken again, and milestones already ticked are skipped. The run never relies on the Workflow runtime replaying cached agent results. The fourth line of a halt and the `where` field of its result name the agent label and the stage that halted (`judge 2, milestone loop`; `publish, closing stage 7 publish`), not the path of an agent transcript. Section 7 of `docs/superpowers/specs/2026-10-10-factory-cycle-design.md` is history and is not edited.

## Rationale

The design assumed that a relaunched run would replay its cached results up to the halt and continue. The Workflow documentation read on 2026-10-11 ("Resume after you leave the session") says the cache is replayed only inside the same session or one resumed with `claude --resume`; a fresh session starts over, and a halt is exactly the moment the operator is likely to close the session, fix something, and come back later. Building on the cache would make resume work in the demonstration and fail in practice. Idempotence costs one preflight per rerun, about 150 seconds of `./tools/verify`, which is cheap against the alternative of a run that cannot be continued. The milestone loop is idempotent by construction; the closing sequence is not, and after the retro stage has moved the plan a rerun with the same arguments is refused by preflight. That gap is `D43` in `docs/DEBT.md`, accepted at L0 because the operator reads the plan before merging and can finish the last stages by hand.

The design also asked each halt to print the transcript path of the agent that ran. A workflow script receives only an agent's return value; the runtime hands it no path, and inventing one would be a planned value posing as an observed one. The run's launch message carries the run id and the transcript directory, and `/workflows` shows every agent, so the label and stage are enough to find the transcript in two steps. An agent that later "restores" the transcript path to the halt will have to fabricate it.

## Date

2026-10-11, the plan author (operator's session, Claude) in `plans/completed/factory-workflows.md`; graduated from the plan's Decision Log at its retrospective.

## Status

accepted
