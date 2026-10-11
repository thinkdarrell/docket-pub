# 0040 — A plan that writes or changes a saved workflow states each milestone's acceptance in two halves: a static half the milestone session proves itself, and a live half only the operator's interactive session can observe and record.

## Decision

When a milestone produces or edits a script under `.claude/workflows/`, its acceptance names a static half (the shape check, `./tools/verify`, the script read back against the plan with line numbers, and whatever dry run the session can perform without the Workflow runtime) and a live half (the run of that script). The milestone session proves and records the static half only. The live half is run by the operator's interactive session and appended to the plan's Artifacts and Notes, signed `operator session`, with the run id. A milestone session never writes live-run evidence it did not observe, and a plan never states the live half as the session's acceptance.

## Rationale

A subagent started by the Agent tool, and therefore every milestone session `cycle-run` launches, does not have the Workflow tool: a probe on 2026-10-11 reported `workflow_tool: not available (not in tool list; ToolSearch select:Workflow returned "No matching deferred tools found")`. A session can write a workflow but cannot run one, so acceptance phrased as "the run prints X" is acceptance no session can meet, and the session's choices are to carve it out every time or to claim it from reading the script, which is the planned-command-as-evidence failure `AGENTS.md` forbids.

The alternative of having the operator's session execute the milestone itself was rejected: it would give up the fresh-context session that `plans/PLANS.md` requires and that the judge exists to check. Splitting the acceptance keeps every recorded observation attributable to the session that made it, at the cost of two signatures in one Artifacts section. In the plan that built the factory, all four live runs passed on the first attempt, and the three important defects the closing review found were in behaviour neither half had exercised (shell quoting inside an agent's command, and a resume path across stages), which is a limit of the split, not a reason to abandon it.

## Date

2026-10-11, the plan author (operator's session, Claude) in `plans/completed/factory-workflows.md`; graduated from the plan's Decision Log at its retrospective.

## Status

accepted
