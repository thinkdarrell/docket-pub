# Factory cycle for docket.pub: design

Date: 2026-10-10
Status: approved in conversation, awaiting written review
Upstream: https://github.com/bholzer/factory-loop (the "harness blueprint")

## Purpose

docket.pub development today runs as a series of hand-driven Claude Code sessions. Each one re-reads a 383-line CLAUDE.md, works from a superpowers spec and plan, and depends on the operator to remember what was decided last time. The operator wants to state a goal, approve a plan, and have a factory carry that plan through implementation, review, and documentation upkeep in one sitting, with as few interruptions as the work allows.

After this design is implemented, the operator can type two commands. The first turns a stated goal into a committed, milestone-sized plan and stops. The second executes that plan milestone by milestone, reviews the result, closes out the documentation, and opens a pull request. The operator reads the plan between the two commands and reads the pull request after the second. Halts in between happen only when a milestone did not land, and every halt says why and where to resume.

## Decisions already made

These were settled in the design conversation on 2026-10-10 and are not reopened here.

- The orchestrator is a saved Workflow script in the docket-pub repository, not the interactive session and not factory-loop's shell loop runner. Control flow is code. Judgement of whether a milestone landed is made from git, never from what an agent said about itself.
- docket-pub adopts factory-loop's artifact layer in full through its harness-init procedure: `AGENTS.md`, `GOALS.md`, `ARCHITECTURE.md`, the `docs/` tree, `plans/PLANS.md`, and the six skills.
- One execution run goes from plan to pull request and halts only on a defect. The operator does not read between milestones.
- The operator states the goal. The factory does not choose what to build next.
- Deploying to Railway stays a human action outside the cycle.

## What factory-loop provides and what this design adds

factory-loop is a markdown-only harness. It treats the repository as the only memory a project has. Its artifact layer is a short entry map, goals, architecture, principles, a maturity ladder, a debt register, decision records, behaviour specs, and capability cards. Its process layer is the ExecPlan convention in `plans/PLANS.md`: a self-contained plan file with four living sections (Progress, Surprises and Discoveries, Decision Log, Outcomes and Retrospective) that a fresh session can execute one milestone at a time. Six skills are the procedures: harness-init, plan-author, plan-execute, capability-build, doc-garden, retro.

Its loop runner is a shell script that starts one `claude -p` session per milestone and decides from the commits whether to continue. factory-loop names multi-agent orchestration and unattended automation as non-goals and keeps a human reading between milestones.

This design keeps everything above except the shell runner and the between-milestone human read. It replaces the runner with two Workflow scripts and moves the human read to plan boundaries only. It adds a scoping step before plan authoring, a review panel after the last milestone, and a committed judge script that reimplements the runner's stop rule.

## Components

### 1. The artifact layer

Installed once by following `skills/harness-init/SKILL.md` from a checkout of factory-loop. The skeletons are copied, never retyped. The operator answers the interview questions the tree cannot: purpose, outcomes, non-goals, principles, known unknowns.

Where the current CLAUDE.md content goes:

- CLAUDE.md becomes one line, `@AGENTS.md`.
- `AGENTS.md` is the map, capped near 100 lines: one paragraph on what docket.pub is, the ownership map, the verify and test commands, the working rules.
- The layout tree and the architecture section (adapter-per-platform, service layer is canonical, scoring model, dollar tiers) go to `ARCHITECTURE.md`.
- The Data Honesty Protocol, the editorial no-false-balance rule, and the constraints that outrank convenience go to `docs/PRINCIPLES.md`.
- Each entry in "Key decisions to preserve" becomes one file under `docs/decisions/` in the shape `docs/decisions/DECISION_FORMAT.md` defines.
- Operator runbook content (Railway deploy script, lockfile workflow, `railway run` versus `railway ssh`, local Postgres setup) goes to `docs/specs/operations.md`. The existing `docs/runbooks/` files are linked from there, not moved.
- Goals, scope, and the private-development status go to `GOALS.md`.
- `docs/DEBT.md` is seeded from: the 14 open GitHub issues, the "known issues / next steps" notes in CLAUDE.md, the two pre-existing test failures recorded below, and the deferred follow-ups in the operator's memory files for this project.
- `docs/MATURITY.md` starts at L0 with every card a specification.

What stays where it is: the whole `docs/superpowers/` tree (specs, plans, reviews, scratch) remains as history. New plans are authored under `plans/active/` in the factory-loop format, which is stricter than the superpowers plan format because the judge script has to parse it. New specs for system behaviour go under `docs/specs/`.

The six skill directories are installed at `skills/<name>/SKILL.md`. A symlink from `.claude/skills` to `skills/` is committed so Claude Code can also find them by name, matching what factory-loop's recorded Claude Code trial did. Agent prompts in the workflows name the skill file by path, not by slash command, because reading a file at its path works identically in every session and cannot decline silently.

### 2. `cycle-plan`: goal to committed plan

A saved Workflow at `.claude/workflows/cycle-plan.js`. Invoked by name with the goal as `args`. Two agents run in sequence, each with a fresh context.

The scope agent reads `AGENTS.md`, `GOALS.md`, `docs/DEBT.md`, the open GitHub issues, and the code the goal touches. It returns a structured brief: the goal restated as an outcome an outside reader can observe, the files it touches, the debt rows it pays or trips, the existing specs it alters, and a list of questions only the operator can answer. If that list is non-empty the workflow stops and reports the questions. It does not plan against an invented answer. The operator answers by rerunning with the answers appended to the goal.

Before the plan-author agent starts, the scope agent also creates the working branch and worktree described under Isolation. The plan-author agent then follows `skills/plan-author/SKILL.md` with the brief in its prompt. The brief's content folds into the plan's Purpose and Context sections; the brief is not committed as a separate file, because the plan must be self-contained by rule. The agent writes `plans/active/<slug>.md`, commits it alone, and stops.

The workflow's result reports: the branch, the worktree path, the plan path, the milestone count, the first milestone's title and acceptance, and what the plan deliberately left out.

The operator reads the plan. Changes the operator wants go into the plan's Decision Log as dated entries with the operator named as author, matching how factory-loop records reviewer findings. The operator commits that edit in the worktree before running `cycle-run`.

### 3. `cycle-run`: plan to pull request

A saved Workflow at `.claude/workflows/cycle-run.js`. Invoked by name with the plan path (and therefore the worktree) as `args`.

The milestone loop. For each unfinished milestone, in order:

1. A judge step records the current HEAD and parses the plan with `tools/judge-milestone --snapshot`, refusing to start if the record has a defect (missing living section, ticked entry without a date). This is the same precondition factory-loop's runner applies.
2. A plan-execute agent runs with a fresh context. Its prompt is the factory-loop brief verbatim, plus three lines: the worktree path to `cd` into on every shell call, the plan path, and a pointer to the previous milestone's commit range ("the previous milestone landed in commits X..Y"). It follows `skills/plan-execute/SKILL.md`, executes the first unfinished milestone, writes evidence into the plan, commits, and stops.
3. A judge step runs `tools/judge-milestone --judge <start-sha>` and the verify command. It continues only when all of these hold: at least one new commit; every new commit touches the plan file; exactly one Progress entry went from open to done; that entry carries a date; no previously done entry reverted; `./tools/verify` passes at HEAD.
4. Any miss halts the whole run.

The judge is a committed shell script, not an agent's opinion. It is invoked by a low-effort agent whose only job is to run it in the worktree and return its output as structured data, because workflow scripts cannot touch the filesystem themselves.

The closing sequence, after the last milestone lands:

1. A review panel. Three agents run in parallel over the branch diff against main, one per lens: correctness, scope against the plan's acceptance, and data honesty (every new data point links back to a source; OCR and minutes stay distinguished; nothing hidden). Each is told to refute before confirming. Findings are returned as structured data with a severity. A fourth agent writes the surviving findings into the plan's Decision Log as a dated review record. If any finding is severe, the run halts here and names them.
2. A retro agent follows `skills/retro/SKILL.md`.
3. A doc-garden agent follows `skills/doc-garden/SKILL.md`.
4. The judge runs `./tools/verify` once more at HEAD.
5. The workflow pushes the branch and opens a pull request against main. The body is the plan's Outcomes and Retrospective section followed by the review record. The result reports the PR URL.

### 4. `tools/judge-milestone`

A POSIX shell script in docket-pub, derived from the plan-parsing and commit-judging parts of factory-loop's `tools/loop-runner`, with the harness-invocation half removed. Two modes:

- `--snapshot` parses the plan and prints one record per Progress entry (OPEN, DONE, NOSTAMP) plus any MISSING or EMPTY living section. Exit 0 if the record holds, 2 if it has a defect.
- `--judge <start-sha>` compares the snapshot taken before the session with the plan at HEAD and the commits since `<start-sha>`. Exit 0 to continue, 1 to halt. Its output is the four-line halt message or the one-line advance message.

Date tolerance: a ticked entry counts as dated if any `YYYY-MM-DD` appears anywhere on the line, in parentheses, square brackets, or bare. This is looser than factory-loop's parenthesised-date rule, on purpose, because a halt caused by bracket style is a halt nobody wanted.

Fixture plans under `tools/fixtures/judge/` cover each stop-rule miss: no commit, commit not touching the plan, two entries ticked, one ticked without a date, a done entry reverted. `./tools/verify` runs the judge against each fixture and fails if any verdict is wrong. This is the one mechanical check this design builds, and its card lives at `docs/capabilities/judge-milestone.md`.

### 5. Isolation and branching

`cycle-plan` creates branch `plan/<slug>` from `origin/main` and a worktree at `.claude/worktrees/<slug>`. That directory is already gitignored. Every agent in both workflows is told to run every shell command from that worktree path. The operator's main checkout is never touched by the factory.

One `cycle-run` at a time. All worktrees share one local Postgres, so two runs would collide in the integration tier.

The PR targets `main`. After merge the operator removes the worktree with `git worktree remove`.

### 6. Verify command

Published in `AGENTS.md` as `./tools/verify`. Observed on 2026-10-10 against branch `feat/archived-meetings-backfill`:

- `pytest tests/unit tests/web tests/services`: 1554 passed, 1 failed, 4 xfailed, 52 seconds.
- `pytest tests/integration`: 529 passed, 1 failed, 50 seconds. Requires local Postgres with `docket_db` migrated.

The two failures are pre-existing: `tests/web/test_blog_routes.py::test_city_route_filters_to_city_and_shared` (builds a URL for `public.city_overview` with a `slug` argument the route no longer takes) and `tests/integration/test_033_migration.py::test_033_up_refreshes_mv_with_filter`. Both become debt rows and are fixed in the first plan's first milestone so the factory starts green.

In its first version `./tools/verify` runs the unit, web, and services tiers plus the judge fixtures. The integration tier runs against the developer's `docket_db` with hand-written cleanup and no rollback, which means a milestone that corrupts state can fail the next milestone's tests for reasons the next agent cannot see. So the integration tier joins `./tools/verify` only after a disposable `docket_test` database, rebuilt from migrations on each run, exists. Until then `cycle-run` runs integration once, at plan end, before the review panel. Building `docket_test` is the first plan the factory executes on itself.

Live tests (`-m live`) stay opt-in and never run inside the cycle.

### 7. Halts and resume

Every halt message has four lines: plan path, milestone title, the rule that failed, and the transcript path of the agent that ran. Examples of rules: "no commit landed", "commit 3f2a1c did not touch the plan", "two Progress entries changed state", "entry at line 41 is ticked but carries no date", "./tools/verify failed (see transcript)", "review found 1 severe finding".

To resume, the operator fixes the cause in the worktree (usually a one-line plan edit, a test fix, or a Decision Log entry answering an ambiguity), commits, and reruns `cycle-run` with the same arguments. The Workflow tool's resume replays completed agent calls from cache and runs live from the point of change. Because the first judge step re-snapshots the plan, a plan edited by hand between runs is accepted as the new starting record.

An agent that dies mid-milestone leaves whatever it committed. The judge sees either no advance or a partial record and halts. The plan-execute skill already requires committing at each coherent step and splitting a milestone in place when it will not fit, so a dead session leaves landed work and a Progress entry describing the split.

### 8. Testing the factory itself

Two levels.

The judge script is tested mechanically by the fixtures in section 4, on every `./tools/verify`.

The workflows are tested by a live trial: the first real plan is small and internal (the `docket_test` database, the two failing tests, and the `./tools/verify` script itself). A defect in the factory discovered on that plan costs little. The trial's observations go into that plan's Surprises and Discoveries section like any other evidence, and anything that changes this design is recorded as a decision there and reflected back here.

### 9. Deliberately out of scope

- No deploy to Railway from inside the loop. The operator deploys after merge with `scripts/deploy.sh`.
- No autonomous goal discovery. `cycle-plan` scopes a goal the operator stated.
- No climbing of the maturity ladder. The rung stays L0 until the promotion rule in `docs/MATURITY.md` is met.
- No parallel milestones and no concurrent runs.
- No edits to factory-loop's skills or `plans/PLANS.md`. A defect in them is reported upstream to bholzer/factory-loop. `plans/PLANS.md` stays byte-identical to upstream.
- No structured-tool-call editing of plan files. Plans are plain markdown any session can read; that is the point.
- No per-milestone review by the operator. The review panel and the judge are the between-milestone readers.

## Review feedback incorporated

An outside assessment of the first half of this design (pasted into the conversation on 2026-10-10) raised seven roadblocks. Four were already closed by factory-loop's conventions: rationale continuity (the plan is self-contained with a Decision Log), routing friction (plan-execute fixes the reading order and `@AGENTS.md` is injected into every agent), debt staleness (doc-garden prunes the register every run), and blind planning (plan-author must open the files and run commands before writing them down). Three changed the design: the tolerant date regex in the judge, the disposable test database, and the previous-milestone commit-range pointer in each brief. The alternative of pasting the previous diff into each prompt was rejected as the context tax the harness exists to avoid.

## Order of work

This spec is implemented as factory-loop plans once the artifact layer exists, except the first step, which creates it.

1. Bootstrap: run harness-init against docket-pub with the operator's interview answers. Ends at a committed artifact layer and installed skills, with CLAUDE.md reduced to `@AGENTS.md`. No feature work.
2. Plan one, authored by hand following plan-author and executed by `cycle-run` as its live trial: `tools/judge-milestone` with fixtures, `./tools/verify`, the two failing tests fixed, and the `docket_test` database.
3. Plan two: the two workflow scripts, `cycle-plan` and `cycle-run`, with the judge integrated.
4. From then on, the operator states goals and the factory runs.

Steps 2 and 3 may be re-cut by the plan-author step into a different number of plans. That re-cut is the author's call and is recorded in the plan's Decision Log.

## Known unknowns

- Whether a Workflow run tolerates a multi-hour duration without being cut off. The live trial on plan one measures this. If it does not, `cycle-run` takes a `--limit <n>` of milestones per invocation, as factory-loop's runner does, and the operator reruns to continue.
- Whether the plan-execute agent, given the factory-loop brief plus three lines, reliably stays inside the worktree. The memory of past sessions says subagents inherit the wrong working directory unless told on every call; the brief says so, and the judge catches any commit that landed outside the worktree because no commit appears in the worktree's branch.
- How much of the 383-line CLAUDE.md survives routing. The goal is a map under 100 lines; the bootstrap report records the actual count.
