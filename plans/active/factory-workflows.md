# Give the factory its two commands: `cycle-run` carries a plan to a pull request and `cycle-plan` turns a stated goal into a plan

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

Today the operator of this repository drives every plan by hand: start a fresh session for a milestone, run `tools/judge-milestone` before and after it, run `./tools/verify`, read the result, start the next session, and at the end convene reviewers, run the retro and gardening procedures, push, and open the pull request. The previous plan (`plans/completed/factory-tools.md`) built the tools those steps use; the orchestration itself still lives in the operator's head and in a conversation that is gone when the window closes. After this plan, the operator types two commands in Claude Code. `/cycle-plan <goal>` turns a goal they state into a committed plan on its own branch, worktree, and Python environment, or stops and asks the questions only they can answer. `/cycle-run plans/active/<slug>.md`, typed in a session started in that worktree, executes the plan milestone by milestone with a fresh agent per milestone, judges each one from git with `tools/judge-milestone`, verifies with `./tools/verify`, halts on the first defect with a message that says where to resume, and when the last milestone lands runs a three-lens review panel, writes the findings into the plan, runs the retro and gardening procedures, pushes the branch, and opens the pull request. You can see it working because this plan's own milestones two to four are executed by the first version of `cycle-run`, and the pull request that carries this plan is opened by it.

## Progress

- [x] (2026-10-11 21:04Z) M1: `.claude/workflows/cycle-run.js` runs preflight and the milestone loop with a limit and halts on the judge; `tools/check-workflows` guards every saved workflow inside `./tools/verify`.
- [x] (2026-10-11 21:20Z) M2: `cycle-run` closes a finished plan: review panel, review record, retro, doc-garden, final verify, push, pull request.
- [x] (2026-10-11 21:41Z) M3: `.claude/workflows/cycle-plan.js` turns a stated goal into a committed plan on its own branch, worktree, and venv, or stops with the operator's questions.
- [x] (2026-10-11 22:16Z) M4: `AGENTS.md`, `docs/specs/operations.md`, the judge card and register, `GOALS.md`, and `docs/DEBT.md` say what the factory now does.

## Surprises & Discoveries

- Observation (authoring, 2026-10-11): a subagent launched with the Agent tool does not have the Workflow tool. A probe agent reported `workflow_tool: not available (not in tool list; ToolSearch select:Workflow returned "No matching deferred tools found")`. So a milestone session of this plan can write a workflow script but cannot run one; the live runs belong to the operator's interactive session. This shapes every milestone's acceptance (Context and Orientation, "Who runs what").
  Evidence: the probe's three-line report, quoted above.
- Observation (authoring, 2026-10-11): agents started by a workflow, and plain subagents, inherit the current working directory of the session that launched them, and that directory follows the session's last shell `cd`. A one-agent probe workflow launched while the session's shell sat in `.claude/worktrees/factory-tools` returned `{"pwd":"/Users/darrellnance/docket-pub/.claude/worktrees/factory-tools","toplevel":"/Users/darrellnance/docket-pub/.claude/worktrees/factory-tools","branch":"plan/factory-tools","dotclaude":"skills"}`, and the run's script file was stored under a project directory named after that same path. The design's isolation argument (start the session in the worktree) holds, and the backstop `cd` line in every prompt stays.
  Evidence: the probe result, quoted above.
- Observation (authoring, 2026-10-11): `node --check` refuses a workflow script as written, because the scripts end with a top-level `return` and `node --check` parses a file as a module: `SyntaxError: Illegal return statement`. The shape check in M1 therefore wraps the body in an async function before parsing it (Plan of Work, M1).
  Evidence: `printf 'export const meta = { name: "x", description: "y" }\nconst r = await agent("hi")\nreturn r\n' > /tmp/x.js; node --check /tmp/x.js` printed the error above and exited 1.
- Observation (authoring, 2026-10-11): building this worktree's venv took 18 seconds, not the two to four minutes `GOALS.md` lists as a known unknown: `python3.10 -m venv venv && venv/bin/pip install -q -e ".[dev]"` in `.claude/worktrees/factory-workflows` printed `venv exit=0 seconds=18`. The pip cache was warm from the previous worktree's build; a cold-cache time is not measured here. M4 writes the measured number into `GOALS.md`.
  Evidence: the timing line, quoted above.
- Observation (M4 session, 2026-10-11): `docs/specs/operations.md` Deploying says the wrapper writes `./COMMIT_SHA (gitignored)`, but `.gitignore` lines 40 to 46 say the file is intentionally not ignored, because the Railway CLI honours `.gitignore` for uploads and an ignored `COMMIT_SHA` was what stamped the first wrapper deploy `unknown`; `git check-ignore -v ./COMMIT_SHA` exits 1. The sentence predates this plan and is outside M4's boundary, so it is left for the doc-garden pass in the closing sequence; recorded here so that pass finds it.
  Evidence: `grep -n COMMIT_SHA .gitignore` printed the three comment lines; `git check-ignore -v ./COMMIT_SHA; echo exit=$?` printed `check-ignore exit=1`.

## Decision Log

- Decision: this plan's branch `plan/factory-workflows` is cut from `plan/factory-tools` at `3e1e365`, not from `origin/main`, and the worktree is `.claude/worktrees/factory-workflows`.
  Rationale: pull request #111, which carries `tools/verify`, `tools/test-db`, and `tools/judge-milestone`, is open and unmerged, and every milestone here calls those tools. Cutting from `origin/main` would mean a branch with no judge and no verify. When #111 merges, `main` contains this branch's base and the pull request for this plan shows only its own commits; until then the pull request shows both plans' commits and its description says so. The design (`docs/superpowers/specs/2026-10-10-factory-cycle-design.md` section 5) has `cycle-plan` cut from `origin/main`; that stands for plans the factory creates, and this hand-authored plan is the exception.
  Date/Author: 2026-10-11, plan author (operator's session, Claude).
- Decision: because a milestone session cannot call the Workflow tool (Surprises & Discoveries), each milestone's acceptance is split into a static half the session proves itself and a live half the operator's session proves by running the workflow. The live half is recorded in this plan by the operator's session, in Artifacts and Notes, signed `operator session`, as reviewer entries were in the previous plan. A milestone session never writes live-run evidence it did not observe.
  Rationale: the alternative, having the session claim the live half from reading the script, is the "planned command as passing evidence" failure `AGENTS.md` forbids. Splitting the acceptance keeps every recorded observation attributable to the session that made it.
  Date/Author: 2026-10-11, plan author.
- Decision: the live trial schedule is fixed now. M1 is executed by a hand-launched fresh session and judged by hand with `tools/judge-milestone`, exactly as the previous plan's milestones were. M2 is executed by running M1's `cycle-run` with `limit` set to 1. M3 is executed by running M2's `cycle-run` (which now carries the closing sequence) with `limit` 1. M4 is executed by running `cycle-run` with no limit, so that after M4 lands the same run performs the closing sequence on this plan: review panel, record, retro, doc-garden, final verify, push, pull request. `cycle-plan`'s live trial runs after M3 lands, from the operator's session, with the goal stated under Validation and Acceptance.
  Rationale: this is the design's section 8 (the workflows are tested by a live trial on a small internal plan) applied to the plan that builds them, and it mirrors how the previous plan's judge judged its own plan from M3 on. A defect in `cycle-run` found this way costs one halt on an internal plan.
  Date/Author: 2026-10-11, plan author.
- Decision: `cycle-run` takes an optional `limit` (number of milestones to execute in this run) from its arguments, from the first version.
  Rationale: the design listed `--limit` as the fallback if a run cannot survive a multi-hour plan. The trial schedule above needs it regardless, so that M2 runs under M1's script and M3 under M2's, and an operator at rung L0 who wants to read between milestones has a way to. Without a limit the run executes every unfinished milestone and then closes the plan.
  Date/Author: 2026-10-11, plan author.
- Decision: resuming after a halt means rerunning `/cycle-run` with the same arguments, and the run is made idempotent rather than relying on the Workflow tool's result cache.
  Rationale: the Workflow documentation (read 2026-10-11 at https://code.claude.com/docs/en/workflows.md, "Resume after you leave the session") says a run's cached results are replayed only within the same session or one resumed with `claude --resume`; a fresh session starts over. The design's section 7 assumed cache replay. Idempotence is cheap here: preflight re-runs, the first judge step re-snapshots the plan, done milestones are skipped because they are ticked, and the cost is one preflight (`./tools/verify`, about 150 seconds) per rerun. The closing sequence is not fully idempotent (a rerun after a halt inside it writes a second review record); that is accepted at L0 and recorded in `docs/DEBT.md` by M4.
  Date/Author: 2026-10-11, plan author.
- Decision: the fourth line of a halt names the agent label and the stage that halted, not an agent transcript path. The run id and the `/workflows` view hold the transcripts.
  Rationale: the design's section 7 asked for the transcript path of the agent that ran. A workflow script receives only an agent's return value; the runtime does not hand the script a path. The run's result message (which the Workflow tool prints) carries the transcript directory and run id, so the operator can still find the transcript in two steps. Deviation from the design, recorded here as the design asks.
  Date/Author: 2026-10-11, plan author.
- Decision: the judge snapshot travels between agents as a file in the system temporary directory, `${TMPDIR:-/tmp}/cycle-run-<slug>-<start sha>.snapshot`, written by the snapshot agent and read by the judge agent, with its path carried in the structured result. It is not carried as text in the structured result.
  Rationale: the snapshot is tab-separated with long keys; an agent re-typing it into JSON would be the only copy, and a mangled tab is a wrong verdict. Both agents run on the same machine in the same run. The file is small and the name carries the start sha so two reruns cannot collide.
  Date/Author: 2026-10-11, plan author.
- Decision: `tools/check-workflows` uses `node` (present at `/opt/homebrew/bin/node`, version 26.8.2 on the operator's machine) and is the fourth check in `./tools/verify`. `node` becomes a documented local requirement in `docs/specs/operations.md` (M4). No capability card is written for it in this plan; the retro decides whether one is warranted.
  Rationale: the scripts are JavaScript and the only honest syntax check is a JavaScript parser. The check runs in well under a second. A card would be a specification for a check that already exists; `skills/capability-build/SKILL.md` builds cards, and the retro's routing rule decides whether this invariant earns one.
  Date/Author: 2026-10-11, plan author.
- Decision: preflight checks one thing the design did not list: that `venv/bin/python -c 'import docket; print(docket.__file__)'` prints a path inside the worktree.
  Rationale: `docs/specs/operations.md` Local environment says why a borrowed venv tests the wrong checkout, and `./tools/verify` cannot detect it because it uses `venv/bin/python` relative to the checkout and would happily test the other tree. The check costs one command.
  Date/Author: 2026-10-11, plan author.
- Decision: the milestone agent is started with a stall window of thirty minutes (`stallMs: 1800000`); every other agent uses the default.
  Rationale: the Workflow documentation says time spent waiting on a tool call does not count toward the stall window, so `./tools/verify` inside a milestone is safe either way, but a milestone session reads and thinks for long stretches and a restart would redo a half-landed milestone from a fresh prompt. Thirty minutes is longer than any silence a productive session should have.
  Date/Author: 2026-10-11, plan author.
- Decision: review findings carry one of three severities, `severe`, `important`, `minor`; `severe` halts the run after the record is committed. The record-writing agent, not the three reviewers, deduplicates findings that two lenses report.
  Rationale: the design says "if any finding is severe, the run halts". Committing the record before halting means the halt is readable in the plan, not only in the run output. Deduplication needs all three reports at once, which is the one place a barrier is justified.
  Date/Author: 2026-10-11, plan author.
- Decision: `cycle-plan`'s live trial goal is the production bug in GitHub issue #110 (`score_overrides` floats cast with `::int` in the calibration queries). The branch and worktree it creates are left in place for the operator and named in Outcomes & Retrospective.
  Rationale: a real, small, already-diagnosed goal exercises the scope agent (it must read the issue and the two files) and the plan-author agent without inventing work, and its product is a plan the operator asked about earlier and can run or discard. The factory does not fix the bug in this plan; it plans it.
  Date/Author: 2026-10-11, plan author.
- Decision: a milestone's Progress line is ticked by changing `- [ ]` to `- [x] (YYYY-MM-DD HH:MMZ)` and changing nothing else on that line; all acceptance evidence goes to Outcomes & Retrospective, Concrete Steps, and Artifacts and Notes.
  Rationale: `tools/judge-milestone` identifies an entry by its text with dates removed (decision `0035`); appending evidence to the line, as the previous plan did before the judge keyed on the snapshot, would now read as an open entry removed and a done entry invented, and halt. The milestone brief in `cycle-run` states this rule.
  Date/Author: 2026-10-11, plan author.
- Decision: the preflight agent's prompt opens with a variant of the two common lines ("Work only in the git worktree that is your current working directory; print it with `pwd -P` first and use that path as <worktree> below ..."), because the worktree path is what preflight discovers; every later prompt substitutes the observed path verbatim.
  Rationale: Plan of Work says the path is not known before any agent runs. Inventing a path for the first prompt would be a planned value posing as an observed one; the variant keeps the rule (one directory, every command prefixed) without the value.
  Date/Author: 2026-10-11, M1 session.
- Decision: `finished_at` is computed from the last agent's observed `date +%s` (the `epoch` field already in the snapshot and judge schemas) with integer arithmetic in the script (`isoFromEpoch`, proleptic Gregorian), not from a `date -u` string added to those schemas and not with `new Date(epoch)`.
  Rationale: Plan of Work fixes the snapshot and judge schemas and says `finished_at` "comes from the last agent's observed `date -u`"; the two were reconciled by deriving the UTC string from the epoch the agent did observe rather than widening the schemas. `new Date(epoch)` with an argument is documented as allowed, but the session cannot run the Workflow runtime to confirm the runtime's `Date` shim accepts it, and a throw there would lose the whole run's result after every milestone had landed; thirty lines of arithmetic carry no such risk. The function is exercised nowhere until the live run, which is recorded under the live half of M1's acceptance.
  Date/Author: 2026-10-11, M1 session.
- Decision: a `null` from any awaited agent (the agent died or was stopped) is already a halt in M1, with the rule `agent <label> returned no result`, although Plan of Work lists that rule under M2.
  Rationale: without the guard, `pre.checks` or `snap.clean` on `null` throws a TypeError, and Plan of Work M1 requires that a halt be a returned object, not a thrown error. Applying the rule to the three agents M1 creates is the only way to meet M1's own halt shape; M2 extends it to the closing agents.
  Date/Author: 2026-10-11, M1 session.
- Decision: the preflight checks carry fixed names in the prompt (`worktree`, `branch`, `plan-file`, `clean-tree`, `origin`, `ls-remote`, `gh-user`, `venv-import`, `verify`, `snapshot`), and the `verify` check's detail is `<last line>; <seconds>s`, so the script can find the verify record by name for its `preflight ok` log line.
  Rationale: Plan of Work numbers the checks but does not name them; a name chosen by the agent at run time would make the `log()` line depend on text the script cannot predict.
  Date/Author: 2026-10-11, M1 session.
- Decision: when `args` is an array, its second element is read as the limit; a string limit (`"1"`) is parsed as a number; anything that is not a positive integer is `Infinity`.
  Rationale: Plan of Work covers the array form only as "first element is the plan path"; a slash-command invocation such as `/cycle-run plans/active/x.md 1` plausibly arrives as either an array or an object with a string value, and the cheapest honest handling is to accept all three without guessing at a default other than "no limit".
  Date/Author: 2026-10-11, M1 session.
- Decision: `tools/check-workflows` does the meta extraction in `awk` (one pass, character by character, tracking single, double, and backtick quotes with backslash escapes) and reads `name` and `description` with `grep -oE` on the flattened meta text; `node` is used only for `node --check` on the wrapped body.
  Rationale: Plan of Work asks for POSIX sh; `awk` is POSIX and present everywhere `sh` is, so the only non-POSIX dependency stays the one the plan already accepted (`node`). The key lookup requires the key to follow `{` or `,`, so a `name:` inside a description string is not mistaken for the property.
  Date/Author: 2026-10-11, M1 session.
- Decision: the diffstat agent returns `fetch_exit` alongside the four fields Plan of Work names (`base`, `head`, `diffstat`, `commits`), and a nonzero fetch halts the run with the rule `git fetch origin exited <n>; the review range cannot be measured against a current origin/main`.
  Rationale: `git merge-base origin/main HEAD` succeeds against a stale `origin/main` and the panel would then review a range that includes commits already merged. Preflight's `ls-remote` proved the remote reachable at the start, not at the close, which may be hours later.
  Date/Author: 2026-10-11, M2 session.
- Decision: in the closing sequence `finished_at` is the publish agent's observed `date -u +%Y-%m-%dT%H:%M:%SZ` (the final verify agent returns the same field as a fallback), not `isoFromEpoch` of an epoch; `isoFromEpoch` remains the source for a run that returns `advanced`.
  Rationale: Plan of Work M2 names `date -u` for the final verify agent and the closing schemas are this milestone's to define, so the string can be observed directly; M1's arithmetic exists because the snapshot and judge schemas were fixed with `epoch` only.
  Date/Author: 2026-10-11, M2 session.
- Decision: the publish stage halts when the push fails (`git push -u origin plan/<slug> failed: <output>`) and when no pull request URL comes back (`gh pr create failed after the push: <output>`); when `gh pr create` reports that a pull request for the branch already exists, the publish agent returns that pull request's URL from `gh pr view` and says so in `detail`, and the run completes.
  Rationale: Plan of Work gives the publish agent's return shape but not what the script does with `pushed: false` or an empty `pr_url`; a result of `complete` with no URL would be the silent failure the design's halt shape exists to prevent. The existing-pull-request case is the first rerun after a halt inside closing (`D43` from M4): the push is idempotent, the record and retro are not, and refusing to finish because the pull request already exists would leave the run with no way to complete.
  Date/Author: 2026-10-11, M2 session.
- Decision: the record entry's `After <last milestone>` clause is filled from the run's own `milestones` list when this run landed one, and otherwise the record agent is told to take the text of the last `- [x]` line in Progress.
  Rationale: a run launched with `limit` set on the plan's last milestone returns `advanced` without closing; the next run finds no open entries, has an empty `milestones` list, and still owes the record a milestone name. The snapshot schema (fixed in M1) returns only `open_entries` and `done_count`, so the plan file is the only source.
  Date/Author: 2026-10-11, M2 session.
- Decision: the retro and doc-garden agents are started with the same thirty-minute stall window as the milestone agent (`stallMs: 1800000`); this extends the M1 decision that only the milestone agent had it. The diffstat, final verify, publish, record, and reviewer agents keep the default.
  Rationale: the M1 rationale (long silent reading, and a restart from the same prompt would redo half-landed commits) applies to the retro and the gardening pass exactly, since each makes several commits; a restarted retro would write a second closing section and attempt a second `git mv`. The record agent makes one commit from a prompt that already holds its inputs, and the reviewers commit nothing.
  Date/Author: 2026-10-11, M2 session.
- Decision: the data-honesty lens's closing parenthetical reads `(run output, log lines, halt messages, records written into documents)` in the script, where Plan of Work wrote `(for this plan: run output, halt messages, review records)`; the complete result also carries `plan_path_now` beside `plan`, since the retro moves the file.
  Rationale: the script serves every plan, so a lens paragraph naming this plan would be wrong for the next; the addition of `plan_path_now` lets the operator open the plan the result refers to without knowing the lifecycle.
  Date/Author: 2026-10-11, M2 session.
- Decision: before `./tools/verify`, the closing path's control flow was exercised with a stub runtime in the session's scratchpad (a Node script defining `agent`, `parallel`, `log`, `phase`, and `args` with canned returns keyed by label, wrapping the body as `tools/check-workflows` does) across four scenarios: complete, severe finding, a null reviewer, a failed fetch. The stub is not committed.
  Rationale: `node --check` proves the file parses, not that a variable is spelled the same twice or that a halt returns before the next stage; the real runtime is not available to a milestone session (Surprises & Discoveries). The stub cannot show that the Workflow runtime accepts the schemas or prompts, so the live half of M2's acceptance stays with the closing run after M4.
  Date/Author: 2026-10-11, M2 session.
- Decision: `cycle-plan`'s common lines come from `confine(kind, dir)`, which reads `Work only in the git checkout at <dir>` for the directory the operator launched from (the guard, scope, and check agents) and `Work only in the git worktree at <dir>` for the one the run creates (the plan-author agent); the guard's prompt uses the "print it with `pwd -P` first" variant as `cycle-run`'s preflight does, and the setup prompt names both the main checkout and the worktree it creates beneath it.
  Rationale: Plan of Work M3 says every prompt carries "the two common lines", whose M1 wording says "worktree"; `/cycle-plan` runs from any checkout, including the main one, so the noun follows what the directory is and the rule (one directory, every command prefixed) is unchanged. The setup agent must run `git worktree add` from the main checkout and then build the venv inside the new worktree, so its confinement names both.
  Date/Author: 2026-10-11, M3 session.
- Decision: the script validates the scope agent's `slug` against `^[a-z0-9-]{1,40}$` and refuses (`status: 'refused'`, with the brief in the result) when it does not match, rather than sanitising it or proceeding.
  Rationale: Plan of Work puts the slug rule in the scope brief but says nothing about a slug that breaks it; a sanitised slug would be a name the operator never saw, chosen by the script, and proceeding would put an unquoted name into the setup and check stages' shell commands. The branch-exists check stays with the scope agent, which can run `git branch -a --list` and choose again; the script cannot.
  Date/Author: 2026-10-11, M3 session.
- Decision: a `null` from any of the five agents ends the run with `{ status: 'refused', reason: 'agent <label> returned no result', where }`, and a failed check stage ends with `status: 'refused'` (reason `check failed: <detail>`); from the setup stage onward a refused result also carries `branch`, `worktree`, `plan_path` when known, and a `cleanup` string (`from <main>: git worktree remove --force .claude/worktrees/<slug>; git branch -D plan/<slug>`).
  Rationale: Interfaces and Dependencies fixes `cycle-plan`'s statuses as `refused`, `questions`, `planned`; Plan of Work names `refused` for the guard and setup stages and gives no status for a null agent or a failed check, so `refused` is the only one of the three that fits. The `cleanup` string is what Idempotence and Recovery tells the operator to run, carried from the stage that created the worktree so they need not compose it. A failed check leaves the worktree and the committed plan in place and logs that the plan is to be fixed there, because Plan of Work says what setup created is left for the operator.
  Date/Author: 2026-10-11, M3 session.
- Decision: when `args` is an array, its first element is the goal and its second the answers; a string is the goal; an object gives `goal` and `answers`. Answers, when present, are appended to the goal under the line "The operator's answers to the questions a previous run of /cycle-plan asked:", and the combined text is what the scope and plan-author agents read.
  Rationale: mirrors the M1 decision on `cycle-run`'s argument forms, since a slash-command invocation may arrive in any of the three shapes. Plan of Work says the operator "appends" the answers to the goal; the script does the appending whether they come inline or as a separate field, so the plan-author sees them beside the brief either way.
  Date/Author: 2026-10-11, M3 session.
- Decision: the plan-author agent runs with `stallMs: 1800000`, as `cycle-run`'s milestone, retro, and doc-garden agents do; the guard, scope, setup, and check agents keep the default.
  Rationale: the M1 and M2 rationale applies: `skills/plan-author/SKILL.md` has the agent read nine documents and every file the brief names before writing, a long silence without a tool call, and a restart from the same prompt after its commit would attempt a second `plan: <slug>, authored` commit. The scope agent also reads for long stretches but commits nothing, so a restart there costs only time.
  Date/Author: 2026-10-11, M3 session.
- Decision: the guard runs a seventh check, `tools`: `test -x tools/judge-milestone && test -x tools/verify` in the launching checkout.
  Rationale: the check stage runs `tools/judge-milestone snapshot` from the launching checkout, and the plan the run writes is executed with both tools; a checkout without them (an old branch, or another repository with the same remote name) would fail at stage 5 after the branch, worktree, and venv exist. The check costs one command and fails before anything is created.
  Date/Author: 2026-10-11, M3 session.
- Decision: the plan-author prompt states the rules `tools/judge-milestone snapshot` enforces on the file (a `## Progress` section whose lines begin `- [ ] ` with none ticked; `## Surprises & Discoveries`, `## Decision Log`, and `## Outcomes & Retrospective` present with at least one sentence each; Progress lines written to stand unchanged and ticked later by prefixing a date), and that every milestone session starts and ends with `./tools/verify`.
  Rationale: `tools/judge-milestone` (lines 64 and 99 to 102, read 2026-10-11) prints `MISSING` or `EMPTY` for any of the four required sections with nothing under it and the snapshot exits 2; `skills/plan-author/SKILL.md` and `plans/PLANS.md` require the sections but do not say an empty one fails a mechanical check, so a plan-author that left Outcomes & Retrospective blank until completion, a reasonable reading of `plans/PLANS.md`, would fail the check stage after the worktree and venv exist. Stating the rule costs one paragraph.
  Date/Author: 2026-10-11, M3 session.
- Decision: before `./tools/verify`, the script's control flow was exercised with a stub runtime in the session's scratchpad (`dryrun-plan.mjs`: a Node script defining `agent`, `parallel`, `log`, `phase`, and `args` with canned returns keyed by label, wrapping the body as `tools/check-workflows` does) across ten scenarios: empty goal; planned with string, array, and object arguments; questions; guard miss; bad slug; setup failure; check failure; null scope agent; null plan-author. The five rendered prompts were printed and read back. The stub is not committed.
  Rationale: as in M2, `node --check` proves the file parses, not that a refusal returns before the next stage or that a substituted value lands where intended, and the Workflow runtime is not available to a milestone session. The stub cannot show that the runtime accepts the schemas or prompts, so the live half of M3's acceptance stays with the operator's run (Validation and Acceptance).
  Date/Author: 2026-10-11, M3 session.
- Decision: the `GOALS.md` venv line is replaced, not deleted, and stays a question: the cold-cache build time is the remaining unknown, and the sentence carries the two warm-cache measurements this plan recorded (18 s in this worktree, Surprises & Discoveries; 15 s in the `cycle-plan` live trial, Artifacts and Notes).
  Rationale: Plan of Work M4 offers "replace with the measured fact in one sentence or delete"; a bare measured fact under a heading named Known unknowns would be a statement in the wrong section, while deleting it would lose the number the plan said to write there. The multi-hour line is left for the retro as Plan of Work says.
  Date/Author: 2026-10-11, M4 session.
- Decision: the `AGENTS.md` Factory line carries the commands and paths in backticks (`/cycle-plan <goal>`, `/cycle-run plans/active/<slug>.md`, `.claude/worktrees/<slug>`), where Plan of Work gives the line's text as one code span; the words are otherwise the plan's.
  Rationale: every other Commands line in `AGENTS.md` sets commands and paths in backticks; a line without them would read as the one exception.
  Date/Author: 2026-10-11, M4 session.
- Decision: the `## Running the factory` section in `docs/specs/operations.md` also states how a saved workflow is invoked (by `meta.name` as `/<name>`, picked up after `/reload-skills`, or by path with `Workflow({scriptPath})`) and describes the shape check `tools/check-workflows` performs in the Tests paragraph, beyond the items Plan of Work M4 lists for the section.
  Rationale: the section owns "how they are run" per the `AGENTS.md` map line this milestone adds, and an operator who edits a script and finds `/cycle-run` running the old one has no other present-tense document to consult; the invocation facts are copied from this plan's Context and Orientation, which is about to become an archive. The shape-check sentence is what "gains `tools/check-workflows` as verify's fourth check" has to say for a reader who has not seen the script.
  Date/Author: 2026-10-11, M4 session.
- Decision: the path walk is mechanical, not by eye: every backticked token in the six edited files that contains a `/` or ends in a file extension is extracted with `grep -o` and tested with `test -e`; tokens with placeholders (`<slug>`, `<name>`) are listed separately as templates, and tokens that are names relative to a parent given earlier in the same sentence (`admin.py` after `src/docket/web/auth.py`, `fixtures/judge/run` under `tools/`) are resolved against that parent by hand.
  Rationale: Plan of Work M4 says "`ls` each" and the six files hold well over a hundred paths; a by-eye walk would be the "planned command as passing evidence" failure in miniature. The transcript is in Artifacts and Notes.
  Date/Author: 2026-10-11, M4 session.
- Decision: review record. After M4: `AGENTS.md`, `docs/specs/operations.md`, the judge card and register..., three fresh reviewers (correctness, scope against the plan, data honesty) read the range b17400817c64176cb2ca713fd12071ad54000443..76c23c076b12ae241345558d4f1f8e97d608549f, each told to refute. Counts: 0 severe, 3 important, 6 minor.
  important: Publish prompt's --title "<title>" is a shell quoting trap: this plan's backticked title is command-substituted (.claude/workflows/cycle-run.js:562): Stage 7 tells the publish agent to build the title from the plan's first `# ` line cut to 70 characters and run `gh pr create ... --title "<title>"` in double quotes. This plan's title line contains `cycle-run` in backticks, and the 70-character cut keeps both backticks, so inside double quotes the shell runs `cycle-run` as a command and substitutes its (empty) output; the pull request is created with the title `Give the factory its two commands:  carries a plan to a pul` and gh exits 0, so nothing in the script notices. A cut that lands between a backtick pair would instead be a shell syntax error and the command would not run at all. Any plan whose title names a command or file in backticks (the house style in this repository) hits the same trap; evidence: `title=$(head -1 plans/active/factory-workflows.md | sed 's/^# //' | cut -c1-70); PATH=/usr/bin:/bin sh -c "printf '%s' \"$title\""` printed `sh: cycle-run: command not found` and then `Give the factory its two commands:  carries a plan to a pul`; `head -1 ... | cut -c1-70 | tr -cd '`' | wc -c` printed 2.
  important: Halt message and D43 promise a resume that preflight refuses once the retro has moved the plan (.claude/workflows/cycle-run.js:90): Every halt ends with `fix the cause in the worktree, commit, and re-run /cycle-run with the same arguments`, and `docs/specs/operations.md` Running the factory plus `docs/DEBT.md` D43 say a rerun after a halt inside closing re-runs the retro and gardening stages and the publish stage picks up the existing pull request. But stage 4 (retro) does `git mv` of the plan to `plans/completed/<slug>.md`, so for a halt in stage 5 (doc-garden null), 6 (final verify failed or dirty tree) or 7 (push or `gh pr create` failed) a rerun with the same arguments fails preflight check 3 (`test -f plans/active/<slug>.md` exits 1) and check 10 (`tools/judge-milestone snapshot` on a missing file exits 2), and a rerun with the new path is refused at line 41 because the regex accepts only `plans/active/`. The operator following the halt message gets a second, unrelated halt and the documented resume path does not exist for those three stages; evidence: `node -e` with the script's regex printed `plans/active/factory-workflows.md true` and `plans/completed/factory-workflows.md false`; `git show --stat c2dcfde` shows the previous plan's retro moving `plans/{active => completed}/factory-tools.md`; `plans/PLANS.md:174` says completion moves the file to `plans/completed/`; the retro prompt at cycle-run.js line 509 instructs `git mv` to `plans/completed/${slug}.md`; the halt text is at lines 90-93 and the preflight `plan-file` check at line 122.
  important: doc-garden and retro reports are cut to 200 characters of their first line and dropped from the run result (.claude/workflows/cycle-run.js:523): The closing sequence asks the doc-garden agent to report 'what was deferred or handed off, and which questions were left to a reader because no command decides them' (skills/doc-garden/SKILL.md Stop condition), and the retro agent to report lessons discarded with reasons and anything undecided; the script then logs only `garden.report.split('\n')[0].slice(0, 200)` (line 523) and `retro.report.split('\n')[0].slice(0, 200)` (line 509) and the `complete` result (lines 596-605) carries neither report. The garden pass's 'leave alone with the reason written down' dispositions and its questions for a reader therefore reach no committed document and no run result; they survive only in the agent transcript under ~/.claude-personal/, outside the repository, against AGENTS.md line 42 ('Nothing material lives outside the repo'). The retro is partly covered because its skill writes the routing into the plan's closing section; doc-garden has no such home; evidence: `grep -n "garden.report\|retro.report\|session.report" .claude/workflows/cycle-run.js` printed lines 281, 509, 523, each `.split('\n')[0].slice(0, 200)`; `sed -n 596,605p .claude/workflows/cycle-run.js | grep -c report` printed `0`; `sed -n 142,150p skills/doc-garden/SKILL.md` printed the stop condition quoted above; `grep -n "Nothing material lives outside" AGENTS.md` printed line 42.
  minor: `advanced` result logs 'the plan still has open milestones' even when the limit stopped the run on the last one (.claude/workflows/cycle-run.js:308): When `limit` is reached, the loop exits without taking another snapshot, so `allDone` is false and the script logs `cycle-run: advanced N milestone(s) of <plan>; the plan still has open milestones`. If the limited run landed the plan's last milestone, that sentence is false; the script has not looked and does not know. The Decision Log (M2 session, the `After <last milestone>` entry) records that such a run returns `advanced` and the next run closes the plan, but the log line asserts a fact the run did not observe, against the script's own rule that every fact comes back from an agent; evidence: `sed -n 300,310p .claude/workflows/cycle-run.js` shows `if (!allDone) { log(\`cycle-run: advanced ${milestones.length} milestone(s) of ${plan}; the plan still has open milestones\`) ... }` with `allDone` set only when a snapshot returned zero open entries (line 287); the loop condition at line 254 exits on `milestones.length < limit` before any further snapshot.
  minor: Decision Log says the pull request description will explain that it carries both plans' commits; nothing in the publish stage or the PR body source does so (.claude/workflows/cycle-run.js:575): The first Decision Log entry states that until PR #111 merges 'the pull request shows both plans' commits and its description says so', but the publish prompt builds the body only from the plan's Outcomes & Retrospective section, the review record, and the attribution line, and neither the prompt nor that section mentions factory-tools, #111, or the base; so the PR this run opens (64 commits, 48 of them from plan/factory-tools touching 24 unrelated files) will not say so unless the retro agent happens to add it; evidence: `git merge-base origin/main 76c23c0` printed b17400817c64176cb2ca713fd12071ad54000443; `git merge-base --is-ancestor 3e1e365 origin/main; echo exit=$?` printed exit=1; `git rev-list --count b174008..3e1e365` printed 48 and `git rev-list --count 3e1e365..76c23c0` printed 16; `grep -n -E '111|factory-tools|both plans' .claude/workflows/cycle-run.js` printed nothing (exit 1); the same grep over the plan's `## Outcomes & Retrospective` section printed nothing (exit 1).
  minor: The review record's `After <last milestone>` clause is filled from the judge's shortened entry text, so it will carry a 72-character truncation with an ellipsis (scope, data-honesty) (.claude/workflows/cycle-run.js:330): Plan of Work M2 and the M2 Decision Log entry say the record opens `After <last milestone>` taken from the run's `milestones` list; that list's `entry` is the snapshot agent's `open_entries[0]`, which is the third tab-separated field of `tools/judge-milestone snapshot`, and that field is `shorten(t)`: the first 72 characters plus `...`. For this plan the clause will read `After M4: \`AGENTS.md\`, \`docs/specs/operations.md\`, the judge card and register, \`GO...`, a name no Progress line carries verbatim; a run that landed nothing is instead told to copy the full `- [x]` line (line 453), and an entry whose cut falls inside a backtick span would also leave unbalanced markdown in the record; evidence: `grep -n -i -E 'short' tools/judge-milestone` printed `60:    function shorten(t) {` and `61:        if (length(t) > 72) { return substr(t, 1, 72) "..." }`; `tools/judge-milestone snapshot plans/active/factory-workflows.md | cut -f1,3` printed four DONE records each ending in `...`, e.g. `DONE\t(2026-10-11 22:16Z) M4: \`AGENTS.md\`, \`docs/specs/operations.md\`, the jud...`; cycle-run.js line 330 reads `const lastLanded = milestones.length ? milestones[milestones.length - 1].entry : null` and the snapshot prompt defines `open_entries` as 'the third tab-separated field (the shortened text)'; `git show c84c8a1:plans/active/factory-workflows.md > <scratch>/plan-c84c8a1.md && tools/judge-milestone snapshot <scratch>/plan-c84c8a1.md | awk -F'\t' '{print $1, $2, $3}'` printed `OPEN 16 M4: \`AGENTS.md\`, \`docs/specs/operations.md\`, the judge card and register...` with exit 0; `grep -n lastLanded .claude/workflows/cycle-run.js` printed lines 330, 451, 452.
  minor: operations.md asserts `node` works with 'any current release', a compatibility claim the plan asked for nowhere and observed nowhere (docs/specs/operations.md:13): Plan of Work M4 asked that Local environment 'gains the `node` requirement in one sentence'; the sentence added also says `(Homebrew's /opt/homebrew/bin/node; any current release)`. The only version anything in this plan observed is v26.8.2 (Decision Log and the M1 Artifacts), so 'any current release' is a statement the commits do not support; evidence: `grep -n 'any current release' docs/specs/operations.md` printed line 13 with the sentence; `grep -n '26.8.2' plans/active/factory-workflows.md | head -2` printed the Decision Log line 54 (`version 26.8.2 on the operator's machine`) and Artifacts line 394 (`node --version printed v26.8.2`); no other version appears in the plan or the diff.
  minor: operations.md says the test database builds 'in under a second'; the recorded timings include 1 s and 3 s (docs/specs/operations.md:45): The Tests paragraph states `tools/test-db` builds the disposable database 'by applying every migration, in under a second', but the verify summaries recorded in the two plans in this range show `test-db ... ok (1s)` ten times and `ok (3s)` once (plans/active/factory-workflows.md, M1 starting state), so the stated number is contradicted by the project's own observations; evidence: `grep -n "under a second" docs/specs/operations.md` printed line 45; `grep -n "test-db \.\.\. ok" plans/active/factory-workflows.md plans/completed/factory-tools.md | sed 's/.*verify: //' | sort | uniq -c` printed 6 lines at `(0s)`, 10 at `(1s)`, 1 at `(3s)`; `git log --format='%h' -1 -S'under a second' -- docs/specs/operations.md` printed `1920684`, inside the range.
  minor: AGENTS.md and MATURITY.md describe verify as tiers plus judge fixtures after a fourth check was added (AGENTS.md:27): `./tools/verify` runs four checks (lines 62-65 of tools/verify) and prints `verify: all 4 checks passed`, and docs/specs/operations.md line 45 lists all four, but AGENTS.md line 27 ('runs every non-live tier (unit, web, services, integration) and the judge fixtures against it') and docs/MATURITY.md line 5 ('every non-live test tier on a disposable database plus the judge fixtures') still describe three; a reader of either file sees a `verify: workflows ... ok` line nothing told them about; evidence: `grep -n "judge fixtures" AGENTS.md docs/MATURITY.md | grep -v check-workflows` printed AGENTS.md:27 and docs/MATURITY.md:5 with the text quoted; `grep -n 'all \$TOTAL checks\|^check ' tools/verify` printed four `check` lines (62-65) and the summary at 71.
  Declined: isoFromEpoch could be off by one around leap days or era boundaries: a 200,000-sample comparison against `new Date(e*1000).toISOString()` plus six fixed values (1970-01-01, 2000-02-29, 2000-03-01, 2024-02-29, 2099-12-31T23:59:59) printed `mismatches 0`; tools/check-workflows might accept a renamed or malformed meta: run on the committed tree it printed `workflows: 2 of 2 ok`, exit 0, and the awk exit-3/exit-4 paths flow through END correctly because awk's `exit` in a main rule still runs END, which re-exits with the same code; M1's Outcomes also record the renamed-meta and Date.now failures observed; tools/judge-milestone compare_records uses the `FNR == NR` idiom, which misreads the second file when the snapshot is empty: an empty snapshot needs a plan with zero Progress entries, which cycle-run never judges (zero open entries goes straight to closing), and by hand the result is a halt on rule 3, not a false advance; tools/verify marks judge-fixtures and workflows `FAILED (not run: no test database)` although they need no database: the summary says exactly what happened and operations.md Tests documents the failed-build exception, so no reader is misled; pyproject `addopts = "-m 'not live'"` might still collect live tests or block `-m live`: `pytest tests/live --collect-only` printed `no tests collected (12 deselected)` and with `-m live` printed `12 tests collected`; test_meeting_detail_source_links_below_executive_summary now looks for `kpi-strip`: `grep -rn kpi-strip src/docket/web/templates/` shows meeting_detail.html line 59 uses that class, and `kpi-grid` survives only in the admin ai_panel template; test_query_c_returns_weeks_of_data moving the second seed from 6.5 to 8.0 days ago could fall outside the query's window: the query's docstring describes a 12-week per-(action_type, week) trend, so 8 days is inside the window and never shares a week with day 0; The twelve judge fixture cases might be tests that cannot fail: `tools/fixtures/judge/run` printed `12 of 12 passed`, and reading each case shows the inverse outcome (advanced instead of halt, or vice versa) would change the asserted exit code and first word; the card's recorded failing-case demonstration confirms the runner reports a wrong verdict; cycle-plan's guard check 2 (`cd "$(git rev-parse --git-common-dir)/.."`) could misresolve from a subdirectory: check 1 tells the agent to use the top level as <checkout> before check 2 runs, and in this linked worktree `git rev-parse --git-common-dir` printed the absolute `/Users/darrellnance/docket-pub/.git`, as the preflight prompt assumes; cycle-plan's setup assumes `.claude/worktrees/` is gitignored: `.gitignore` line 35 is `.claude/worktrees/`; tools/check-workflows' meta_string could pick a `name:` inside a string: the regex requires `{` or `,` before the key and `head -1` takes the first match, and in both scripts `name` is the first property, so the decision recorded in M1 holds for the files present; docs/MATURITY.md still describes verify as the test tiers plus the judge fixtures without the fourth check: a documentation staleness question for the scope lens, not a code-correctness defect; 48 of the 64 commits in the range (b174008..3e1e365, 24 files including tests, pyproject.toml, the deletion of scripts/import_video_ocr.py, and decisions 0034–0038) are plan factory-tools' work, not this plan's: the first Decision Log entry records that plan/factory-workflows was cut from plan/factory-tools because PR #111 is unmerged, so the review range measured from origin/main is expected to include them; The data-honesty lens paragraph in cycle-run.js differs from Plan of Work M2's wording and the complete result carries plan_path_now: both are recorded as an M2 Decision Log entry; The guard's seventh `tools` check, cycle-plan's array-form arguments, the slug-pattern refusal, the `cleanup` string on refusals, and the plan-author prompt's judge rules are not in Plan of Work M3: each is recorded as an M3 Decision Log entry; GOALS.md's venv line is two sentences and remains a question where Plan of Work M4 said 'one sentence or delete': the M4 Decision Log entry records keeping it as a question with the two measured times, and the 15 s figure is supported by the operator-session entry committed in c84c8a1 before fb472fa; AGENTS.md's Factory line uses backticks where Plan of Work gave one code span, and the file changed by exactly four diff lines (one removed, three added) staying at 48 lines: recorded in the Decision Log and confirmed with `git diff c84c8a1 fb472fa -- AGENTS.md` and `wc -l` (48, from 46); `gh pr create` is given `--head ${branch}` and the review-range log line appends `(<n> commits)`, neither named in Plan of Work M2: harmless additions inside the stage's stated intent, not scope changes; The M4 claim that `git diff --stat` printed `6 files changed, 25 insertions(+), 12 deletions(-)`: `git diff --stat c84c8a1 fb472fa -- AGENTS.md GOALS.md docs/DEBT.md docs/capabilities/index.md docs/capabilities/judge-milestone.md docs/specs/operations.md | tail -1` printed exactly that line; The Artifacts line-number listings for 094a50d (313 lines), a03e5e8 (605), and 3ebf38c (316): `wc -l` on each committed file matched, and spot checks of lines 249 and 304–313, 311–320, 463 and 596–605, and 172–178 and 303–316 showed the code the listings name; The cycle-plan live-trial claims (worktree on branch plan/calibration-float-scores, one commit over origin/main, plan of 276 lines): `git worktree list`, `git branch --list`, `git log --oneline origin/main..plan/calibration-float-scores` (one line, c172549), and `git show --stat` (only plans/active/calibration-float-scores.md, 276 insertions) agree; the snapshot on that file was not rerun here because it lives outside this worktree; The scope prompt tells the agent to read ARCHITECTURE.md beyond Plan of Work M3's reading list: additive reading with no change to the brief's fields or the run's behaviour; The setup prompt's statement that `.claude/skills` is a committed symlink and `.claude/worktrees/` is gitignored: `git ls-files .claude` lists `.claude/skills` and `.gitignore` line 35 reads `.claude/worktrees/`; Progress line text was not reworded across the plan's life, as the Decision Log requires: the four lines at c309ace and at 76c23c0 are identical once checkboxes and dates are stripped (`diff` printed nothing); `tools/check-workflows` and its wiring meet Plan of Work M1 as written (meta first-line rule, name/description checks, wrapped `node --check`, the four forbidden calls, zero-files failure, `check "workflows"` after `judge-fixtures` at tools/verify:65): running it printed `workflows: 2 of 2 ok` with exit 0; The judge reads `advanced` when an invented ticked line is added beside a legitimate tick: decision 0035 records this loophole explicitly as 'recorded rather than closed', so it is a recorded decision, not a finding; `isoFromEpoch` could render a wrong `finished_at`: a node check of 20000 random epochs against `new Date(e*1000).toISOString()` printed `mismatches: 0`, so the arithmetic is correct; The review record drops each finding's `refutation` text and does not name the lens for a single-lens finding: Plan of Work M2 item 3 fixes the record's line shape as `<severity>: <title> (<location>): <claim>; evidence: <evidence>.`, so the script follows the plan; The pull request title is cut at 70 characters mid-word: Plan of Work M2 item 7 specifies 'the plan's first heading, up to 70 characters', and the cut is cosmetic; A milestone's `seconds` in the log and result includes the judge agent's verify run: Plan of Work M1 defines `seconds` as the judge agent's epoch minus the snapshot agent's epoch, and the plan's live-run notes report it under that definition beside the wall time; Deleting `scripts/import_video_ocr.py` could blur OCR-derived from minutes-derived votes: `grep -n video_ocr -r src` shows `source` still typed `'video_ocr' | 'minutes_text' | 'api' | 'manual'` in migration 001 and read in `vote_matcher.py` and `admin.py`; the deleted script was a one-off importer the D19 row already called deprecated; Preflight halts name only the first failing check and the result carries no `checks` list: Plan of Work M1 says the halt names 'the first failing check and its detail', so the omission is specified; `tools/verify` reports `judge-fixtures` and `workflows` as 'FAILED (not run: no test database)' when the database build fails although neither needs the database: the message says they were not run, which is honest, and the design choice to run nothing without a database is stated in the script's comment and in operations.md; `tools/check-workflows` reports node's line number relative to the wrapped body rather than the file: the message says '(body after the meta object, wrapped; line 1 is the wrapper)', which discloses the offset; The milestone session's `report` (including carve-outs against acceptance) is logged only to 200 characters and not returned: skills/plan-execute/SKILL.md requires the session to write its evidence and carve-outs into the plan's living sections, which the M1 to M4 Outcomes entries show happened, so the plan is the committed record.
  Rationale: the design's closing sequence writes the panel's findings into the plan so they are read with it, and halts before the pull request when a finding is severe.
  Date/Author: 2026-10-11, review panel (cycle-run), from the three panel reports.

## Outcomes & Retrospective

Nothing has been executed. This section is filled as milestones land, one entry per milestone, and closed by the retro that `cycle-run`'s closing sequence runs after M4.

M1 (2026-10-11, hand-launched milestone session; commits `094a50d` and the commit carrying this entry, on top of `c309ace`). Landed: `.claude/workflows/cycle-run.js` (313 lines: argument handling, the ten-check preflight, the snapshot / milestone / judge loop with `limit` and a hard cap of 20, the halt shape) and `tools/check-workflows` (POSIX sh plus `awk` and `node --check`), wired into `./tools/verify` as the fourth check. Static acceptance met and observed: `tools/check-workflows` printed `workflows: 1 of 1 ok` with exit 0 on the committed tree; exit 1 naming the file on the renamed meta (`meta.name "cycle-runn" does not match file cycle-run.js`) and on the appended `Date.now()`; `./tools/verify` printed `verify: workflows ... ok (0s)` as its fourth check and `verify: all 4 checks passed in 139s.` with exit 0; the script's contents are listed by line number in Artifacts and Notes. Carve-outs: none against the static half. Not observed by this session, by design (Decision Log, second entry): the live half, which is the run of this script that executes M2; in particular no agent prompt, schema, `stallMs`, or `isoFromEpoch` has been exercised by the Workflow runtime, and the first live run is where a runtime-shape mistake would show. The starting-state `./tools/verify` took 160 s and the post-change run 139 s; both within the 180 s budget `AGENTS.md` states.

M2 (2026-10-11, milestone session launched by `cycle-run` with `limit` 1; commits `a03e5e8` and the commit carrying this entry, on top of `f0f7b6a`). Landed: the closing sequence in `.claude/workflows/cycle-run.js` (lines 311 to 605: diffstat, three-lens review panel in `parallel()`, review record committed into the plan's Decision Log, retro, doc-garden, final verify, publish, and the `complete` result with `review` and `pr_url`), replacing M1's three placeholder lines. Static acceptance met and observed: `tools/check-workflows` printed `workflows: 1 of 1 ok` with exit 0; `./tools/verify` printed `verify: all 4 checks passed in 157s.` with exit 0; the seven stages with their lens paragraphs, schemas, and record shape are listed by line number in Artifacts and Notes. Beyond the stated acceptance, a stub runtime exercised the closing path through the complete result and three halts (Decision Log; Artifacts and Notes). Carve-outs: none against the static half. Not observed by this session, by design: the live half, which is the closing run after M4; in particular no closing prompt or schema has met the Workflow runtime, the record agent's Decision Log edit has not been parsed by `tools/judge-milestone snapshot` on a real plan, and the retro and publish agents have not run. The starting `./tools/verify` took 156 s and the post-change run is in the transcript above; both within the 180 s budget.

M3 (2026-10-11, milestone session launched by `cycle-run` with `limit` 1; commits `3ebf38c` and the commit carrying this entry, on top of `4a731fd`). Landed: `.claude/workflows/cycle-plan.js` (316 lines: argument handling with the empty-goal refusal, the guard, scope, setup, plan-author, and check agents with their schemas and prompts, the `questions` stop, the slug rule, the `refused` shape with its `cleanup` string, and the `planned` result with its `next` sentence). Static acceptance met and observed: `tools/check-workflows` printed `workflows: 2 of 2 ok` with exit 0; `./tools/verify` printed `verify: all 4 checks passed in 150s.` with exit 0; the five stages with their schemas and prompts are listed by line number in Artifacts and Notes. Beyond the stated acceptance, a stub runtime exercised the script through the `planned` result, the `questions` stop, and seven refusals (Decision Log; Artifacts and Notes). Carve-outs: none against the static half. Not observed by this session, by design: the live half, which is the operator's run of `cycle-plan` from this worktree with the issue #110 goal after this milestone is judged (Validation and Acceptance); in particular no prompt or schema here has met the Workflow runtime, no scope agent has read a real issue, no `git worktree add` or venv build has been run by the setup prompt, and the plan-author prompt has not produced a plan that `tools/judge-milestone snapshot` has parsed. The starting `./tools/verify` took 156 s and the post-change run 150 s; both within the 180 s budget.

M4 (2026-10-11, milestone session launched by `cycle-run` with no limit; commits `fb472fa` and the commit carrying this entry, on top of `c84c8a1`). Landed: `AGENTS.md` (the `tools/` map line gains `check-workflows`, a `.claude/workflows/` map line, a Factory line in Commands; 48 lines), `docs/specs/operations.md` (`node` in Local environment, `tools/check-workflows` as the fourth check in Tests, and a new `## Running the factory` section owning `/cycle-plan`, `/cycle-run`, the `limit`, the closing sequence, the halt shape and resume, one run at a time, `/workflows` and the transcript directory, `node`, and the closing-sequence rerun debt), `docs/capabilities/judge-milestone.md` (Enforcement point in present tense), `docs/capabilities/index.md` (`judge-milestone` row enforced at `cycle-run`), `GOALS.md` (the venv unknown rewritten around the measured 18 s warm-cache build), and `docs/DEBT.md` (`D6` deleted as paid, `D43` added). Acceptance met and observed: `wc -l AGENTS.md` printed `48`; every repository-relative path in the edited files resolves (the walk is in Concrete Steps and Artifacts and Notes); `./tools/verify` printed `verify: all 4 checks passed in 155s.` with `exit=0`; `grep -c '^| D6 ' docs/DEBT.md` printed `0` and `grep -c '^| D43 ' docs/DEBT.md` printed `1`; `grep -c planned docs/capabilities/index.md` printed `0`. Carve-outs: none against the stated acceptance. Not observed by this session, by design: the live half of this plan, which is the closing sequence this same `cycle-run` performs after the judge passes this milestone: review panel, record, retro, doc-garden, final verify, push, pull request. One finding outside the boundary is left for that pass (Surprises & Discoveries, `COMMIT_SHA`). The starting `./tools/verify` took 134 s; the post-change run's time is in the summary line above; both within the 180 s budget.

Closing retrospective (2026-10-11, the retro agent of `cycle-run`'s own closing sequence, following `skills/retro/SKILL.md`; the Progress lines and every entry above were left as written).

Purpose against outcome. The purpose was two commands that take the orchestration out of the operator's head: `/cycle-plan <goal>` to a committed plan on its own branch, worktree, and venv, and `/cycle-run` from a plan to a pull request with a fresh agent per milestone, judged from git. Both exist and both ran on this plan. `cycle-run` executed M2 and M3 under `limit` 1 (runs `wf_03f7780e-f69` and `wf_5e4ca6e6-e88`, 903 and 1008 seconds, each judged `advanced` at the first attempt) and M4 with no limit, then wrote the review record (`7b64ff3`: 0 severe, 3 important, 6 minor) and started this retro. `cycle-plan` authored `plans/active/calibration-float-scores.md` on `plan/calibration-float-scores` with its own worktree and a 15-second venv (run `wf_7f51e6c3-55e`) without a question stop. Four milestones were authored and four executed, in 17 commits through the review record, and no live run needed a hand correction. The whole-plan acceptance in Validation and Acceptance is met as far as this stage can see: M4 was executed by `cycle-run` and the record holds zero severe findings; the doc-garden, final verify, push, and `pr_url` stages had not run when this section was written, and the operator's session records their result after the run returns, as that section says.

Differences between intended and actual, reconstructed from the record. (1) The design's section 7 assumed a halted run resumes by cache replay; the Workflow documentation makes the cache session-bound, so resume became an idempotent rerun of the same command, and the review then found that for a halt after the retro has moved the plan (doc-garden, final verify, publish) the rerun is refused by preflight, so the path M4 documented as "not idempotent" is for those three stages not available at all. (2) The design asked each halt to print a transcript path; the runtime hands the script none, so halts name the agent label and stage. (3) Subagents do not have the Workflow tool, so every milestone's acceptance was split into a static half the session proved and a live half the operator's session ran and recorded; all four live runs passed at the first attempt. (4) The M2 and M3 sessions each went beyond their stated acceptance with a stub runtime that exercised the script's control flow, written twice in a scratchpad and committed neither time. (5) The sessions resolved a long list of details Plan of Work left open (null agents in M1, the preflight check names, the argument forms, `finished_at` from an epoch, `fetch_exit`, the publish stage's failure handling, the source of the `After <milestone>` clause, `confine()`, slug validation, the guard's `tools` check, the plan-author's judge rules), each in one Decision Log entry and none as a carve-out. (6) The closing review found three important and six minor defects that neither the static halves nor the stub runs exercised: the publish stage interpolates the plan's title into a double-quoted `--title` (this plan's own heading keeps two backticks under the 70-character cut, so the pull request this run opens arrives with `cycle-run` substituted away from its title); the resume gap in (1); the retro and doc-garden reports cut to 200 characters and dropped from the result; an `advanced` log line that asserts open milestones remain without looking; a pull request body silent on the branch's base; the record's `After <milestone>` clause carrying the judge's 72-character shortened text, visible in the record above; `operations.md` claiming any `node` release works and a sub-second `tools/test-db`; and `AGENTS.md` line 27 and `docs/MATURITY.md` line 5 still describing verify as three checks. (7) The venv unknown in `GOALS.md` was measured (18 s and 15 s, warm cache); the multi-hour unknown was left for this pass, which has the durations. (8) The branch was cut from `plan/factory-tools` rather than `origin/main` (first Decision Log entry) and pull request #111 is unmerged, so the pull request that carries this plan shows both plans' commits, 48 of them from `factory-tools` by the review's count, until #111 merges; the Decision Log said the description would say so, and this paragraph, which the publish stage copies into the body, is where it says it. (9) Plan of Work M4 named five documents and the milestone edited six files. (10) The M4 session found the `COMMIT_SHA` sentence in `operations.md` Deploying false (`.gitignore` deliberately does not ignore the file) and left it for the gardening pass. (11) One milestone's run spends about 630 of its 900 to 1000 seconds in four `./tools/verify` runs: preflight, the session's start and end, the judge.

What remains open. `D43`, widened by this pass to the resume gap; `D44`, the four script defects in (6); `D45`, the uncommitted stub runtime. The last stages of the whole-plan acceptance are the operator's to record. The `plan/calibration-float-scores` branch, worktree, and plan are left in place for the operator (issue #110), as the Decision Log says. Handed to the doc-garden pass that follows this retro, because they are drift in documents this plan did not author rather than lessons: the `COMMIT_SHA` sentence in (10), and `AGENTS.md` line 27 and `docs/MATURITY.md` line 5 in (6). The multi-hour question in `GOALS.md` stays a question. `isolated-env` and `evidence-check` stay `specced`, untouched by this plan.

Where each lesson went, one owner each; `docs/decisions/` continues from `0038`. Resume by idempotent rerun and halts naming label and stage, both departures from design section 7 (differences 1 and 2): decision `0039`. Acceptance for a saved workflow proven in a static half and a live half because subagents have no Workflow tool (3): decision `0040`. The judge snapshot carried between agents as a file, never as text (a Decision Log entry an agent would otherwise simplify away): decision `0041`. The resume gap (1): `D43`'s row now states it, and `docs/specs/operations.md` Running the factory now says what the operator does after a halt past the retro's move; the spec states the behaviour and the row states the deferred work, and the spec points at the row. The four script defects (6): one row, `D44`, with the trigger that the title trap fires on every plan whose heading holds a backtick. The stub runtime written twice (4): `D45`, with the trigger that the next workflow edit commits it. The two unsupported claims in `operations.md` (6) are corrected in place, because that section is this plan's own reflection: the `node` sentence names the release observed, and `tools/test-db` builds in one to three seconds as the recorded summaries show. The `docs/specs/index.md` row for `operations.md` now names the Running the factory section and verify's fourth check, which M4 added to the spec without listing them. The run durations (7 and 11) go to `GOALS.md` Known unknowns, where the multi-hour line now carries them. The pull request's base (8) is stated in this section and nowhere else. The question the Decision Log left to this pass, whether `tools/check-workflows` earns a capability card: no change, failing question one; nothing recurs, the check is built and runs inside `./tools/verify`, its contract has one owner in `operations.md` Tests, and a card would be a second copy of that paragraph (the judge has a card because its contract is what `cycle-run` was written against; the register lists cards, not every check verify runs).

Discarded, each with the materiality question it failed. Details left to the sessions (5): question two, as the previous plan's retro also found; a plan that fixed every schema field and refusal shape in advance would be longer than the scripts, and each resolution cost one Decision Log entry and no carve-out. Five documents against six files (9): question two. Verify's share of a milestone's wall time (11): question two; each of the four runs is a different session's own evidence (preflight's, the milestone session's start and end as `skills/plan-execute/SKILL.md` asks, the judge's), dropping one trades a recorded observation for about 150 seconds, and the number is now in `GOALS.md` for the day the multi-hour question is answered by verify time. A rule against interpolating plan text into a double-quoted shell argument (6): question two; the one occurrence is `D44`, and a rule every session reads for one line in one script costs more than the defect. `node --check` refusing a top-level `return`: question one, resolved once inside `tools/check-workflows`. The `cycle-plan` trial's plan-author noting that `origin/main` lacks the tools: question one, a circumstance that ends when #111 merges. The truncated `After <milestone>` clause as a lesson about the judge's `shorten()`: no new lesson; the snapshot's third field is documented as shortened, and the defect is `cycle-run`'s use of it, in `D44`. The stub runs finding no defect in two uses: not a lesson against them; `D45` records the cost of rewriting them and the trigger, and whether a committed stub earns a card is decided when it exists and has been seen to fail.

## Context and Orientation

docket.pub is a Flask and PostgreSQL application whose code lives under `src/docket/` and whose tests live under `tests/`. This plan changes none of that code. It adds two JavaScript files under `.claude/workflows/`, one shell script under `tools/`, and edits to five documents. Everything here is about how work on the repository is orchestrated.

The agent harness. The repository's agent harness is a set of markdown files installed from the blueprint at https://github.com/bholzer/factory-loop. `AGENTS.md` is the map every session reads first (Claude Code injects it into every session through `CLAUDE.md`, whose whole content is `@AGENTS.md`). `plans/PLANS.md` is the plan convention this file follows. `skills/<name>/SKILL.md` are six procedures: `plan-author` (write a plan), `plan-execute` (execute one milestone of a plan in a fresh session and stop), `retro` (reconstruct what a finished plan intended against what it did and route each lesson to one owning file), `doc-garden` (sweep the documents for drift), `capability-build`, and `harness-init`. The same files are reachable as `.claude/skills/<name>/SKILL.md` through a committed symlink. `docs/DEBT.md` is the debt register with stable row ids `Dn`; closed rows are deleted and numbers never reused. `docs/capabilities/` holds one card per mechanical check, statuses in `docs/capabilities/index.md`. `docs/decisions/NNNN-slug.md` are durable decisions; the last number spent is `0038`. `docs/specs/operations.md` is how the system is run. `GOALS.md` holds purpose, scope, constraints, and known unknowns.

A "plan" is a file like this one under `plans/active/`. Its Progress section holds one checkbox line per milestone. A line is "open" when it begins `- [ ]` and "done" when it begins `- [x]` and carries a date `YYYY-MM-DD` anywhere on it. A "milestone session" is one fresh agent that reads `AGENTS.md`, `plans/PLANS.md`, and the plan, executes the first open milestone following `skills/plan-execute/SKILL.md`, writes what it observed into the plan, commits, and stops.

The tools from the previous plan. `./tools/verify` (POSIX sh, no arguments) builds a disposable database `docket_test_<hash>` with `tools/test-db`, runs the unit, web, services, and integration test tiers and the judge's fixture self-test against it, prints one `verify: <name> ... ok (Ns)` or `verify: <name> ... FAILED (Ns)` line per check and a final `verify: all M checks passed in Ss.` or `verify: N of M checks failed in Ss.`, drops the database, and exits zero only when every check passed. It takes about 150 seconds. `tools/judge-milestone snapshot <plan>` parses a plan's Progress and living sections and prints one tab-separated record per entry (`OPEN`, `DONE`, `NOSTAMP`, `MISSING`, `EMPTY`; then line number, shortened text, key); it exits 0 when the record holds and 2, with one `judge: defect ...` line on stderr, when a required section is missing or empty or a ticked entry has no date. `tools/judge-milestone judge <plan> <snapshot-file> <start-sha>` reads the plan as committed at `HEAD`, compares it with the snapshot, lists the commits `<start-sha>..HEAD`, checks the working tree, and prints `judge: advanced "<entry>"` with exit 0, or a four-line halt (`judge: halt <plan>`, `judge: entry "<entry>"` or `judge: no entry`, `judge: <rule sentence>`, `judge: Fix the cause, commit in the worktree, and re-run.`) with exit 1, or `judge: defect ...` with exit 2 when the plan at `HEAD` is structurally defective or the start sha is unknown. The judge's rules: at least one commit since the start; every commit changes the plan by more than whitespace; exactly one entry that was open in the snapshot is done and dated at `HEAD`; no done entry reverted; no open entry removed; clean tree. The judge identifies an entry by its text with dates stripped, so rewording a Progress line, open or done, reads as one entry removed and another invented. Its contract is `docs/capabilities/judge-milestone.md`.

Worktrees and venvs. A git worktree is a second checkout of the same repository in another directory, sharing one `.git`. This repository keeps plan worktrees under `.claude/worktrees/<slug>` (gitignored) on branch `plan/<slug>`. Each worktree needs its own `venv/`, built with `python3.10 -m venv venv && venv/bin/pip install -e ".[dev]"`, because the editable install pins the `docket` package to the checkout it was installed from; `docs/specs/operations.md` Local environment says so. All worktrees share one local PostgreSQL 16 server; `tools/test-db` names its database from the checkout path so two checkouts do not collide, but two concurrent `cycle-run`s are still not supported.

The Workflow tool and saved workflows. Claude Code (version 2.1.287 on the operator's machine) has a tool named Workflow that runs a JavaScript script in an isolated runtime. The script coordinates agents; it has no filesystem, shell, module loading, or clock (`Date.now()`, `Math.random()`, and a no-argument `new Date()` throw, so that a relaunched run repeats the same agent calls). Its API, as documented in the `workflow-authoring` bundled skill and at https://code.claude.com/docs/en/workflows.md: `agent(prompt, opts)` spawns one subagent and resolves to its final text, or, when `opts.schema` (a JSON Schema with `type: 'object'` at the root) is given, to a validated object; `opts.label` names it in the progress view, `opts.phase` groups it, `opts.effort` (`'low'` to `'max'`) sets reasoning effort, `opts.stallMs` sets how long the agent may be silent (time inside its own tool calls does not count) before it restarts from the same prompt, and `opts.model` overrides the model and is omitted here so every agent inherits the session's. `agent()` resolves to `null` if the agent is stopped or dies after retries. `parallel([thunks])` runs tasks concurrently and waits for all; `pipeline(items, ...stages)` runs items through stages independently; `log(message)` prints a line above the progress tree; `phase(title)` opens a progress group. The global `args` is whatever the caller passed. The script must begin with `export const meta = { name, description }` as a pure literal, may list `phases` and `whenToUse`, and ends by returning a value, which becomes the run's result. A saved workflow is a `.js` file under `.claude/workflows/` whose `meta.name` is the command name; it runs as `/<name> <input>` in any session whose working directory is inside the repository, and Claude passes the input as structured data. A file added or edited during a session is picked up after `/reload-skills`, or can be run by path with `Workflow({scriptPath})`. Every run writes its script and the agents' transcripts under the session's directory in `~/.claude-personal/projects/` (this machine's config directory); the tool's launch message prints the run id, the transcript directory, and the script path. A run continues while the session is open or backgrounded; a run stopped with the session is relaunched from cache only in the same session or one resumed with `claude --resume`. Agents an `agent()` call spawns are ordinary subagents: they have the Bash, Read, Edit, Write, Grep, and Glob tools and get `AGENTS.md` injected, and they do not have the Workflow tool (Surprises & Discoveries). Runs are watched in `/workflows`.

Who runs what. Three kinds of session appear in this plan. The operator's session is the interactive Claude Code session started in `.claude/worktrees/factory-workflows`; it is the only one that can call the Workflow tool, so it launches every workflow run and appends each run's observed result to this plan under Artifacts and Notes, signed `operator session`. A milestone session is a fresh agent executing one milestone of this plan under `skills/plan-execute/SKILL.md`; for M1 the operator's session launches it directly with the Agent tool and judges it by hand; for M2 to M4 `cycle-run` launches and judges it. Workflow-internal agents are the preflight, snapshot, judge, reviewer, record, retro, doc-garden, and publish agents that `cycle-run` and `cycle-plan` spawn; what each is told is written below, because those prompts are the contracts a later session would otherwise invent.

The design this plan implements is `docs/superpowers/specs/2026-10-10-factory-cycle-design.md`, sections 2, 3, 5, 7, and 8. Where this plan departs from it, the Decision Log says so.

## Plan of Work

### M1: `cycle-run` preflight and milestone loop, and the workflow shape check

Create `.claude/workflows/cycle-run.js`. It begins with the literal

    export const meta = {
      name: 'cycle-run',
      description: 'Execute an ExecPlan milestone by milestone with a fresh agent per milestone, judged from git, then close it to a pull request',
      whenToUse: 'From a Claude Code session started in the plan worktree: /cycle-run plans/active/<slug>.md, optionally with a limit on milestones for this run',
      phases: [{ title: 'Preflight' }, { title: 'Milestones' }, { title: 'Closing' }],
    }

(`Closing` is used from M2; listing it now costs nothing.) The body reads its arguments tolerantly: `args` may be a string (the plan path), an array whose first element is the plan path, or an object with `plan` and optional `limit`. Normalise to `plan` (string) and `limit` (a positive integer or `Infinity`). The slug is the plan's basename without `.md`; the branch is `plan/<slug>`. A plan path that is not under `plans/active/` ends the run with a one-line result refusing it.

Every agent prompt in this script begins with the same two lines, with the real values substituted:

    Work only in the git worktree at <worktree>. Every shell command you run starts with `cd <worktree> &&`; you may not touch any other directory.
    Report only what you observed. Never state a result for a command you did not run.

`<worktree>` is not known to the script before any agent runs, so the preflight agent returns it (`pwd -P`) and every later prompt uses that value.

Preflight (phase `Preflight`). One agent, `effort: 'low'`, label `preflight`, with a schema, runs these checks in order from the current directory and returns every result, passing or not. The checks and what each must print:

1. `pwd -P` prints a path containing `/.claude/worktrees/`, and `git rev-parse --git-common-dir` prints an absolute path (a linked worktree; in a main checkout it prints `.git`).
2. `git rev-parse --abbrev-ref HEAD` prints `plan/<slug>`.
3. `test -f <plan>` succeeds.
4. `git status --porcelain` prints nothing.
5. `git remote get-url origin` prints a URL ending in `thinkdarrell/docket-pub.git` or `thinkdarrell/docket-pub`.
6. `GIT_TERMINAL_PROMPT=0 git ls-remote origin HEAD` exits 0.
7. `gh api user --jq .login` prints `thinkdarrell`.
8. `venv/bin/python -c 'import docket; print(docket.__file__)'` prints a path beginning with the worktree path.
9. `./tools/verify` exits 0; record its last line and its wall time. The agent must run it with a tool timeout of at least 300 seconds.
10. `tools/judge-milestone snapshot <plan>` exits 0; record the count of `OPEN` and `DONE` records.

The schema:

    { type: 'object', required: ['worktree', 'started_at', 'checks'],
      properties: {
        worktree: { type: 'string' }, started_at: { type: 'string' },
        checks: { type: 'array', items: { type: 'object', required: ['name', 'ok', 'detail'],
          properties: { name: { type: 'string' }, ok: { type: 'boolean' }, detail: { type: 'string' } } } } } }

`started_at` is `date -u +%Y-%m-%dT%H:%M:%SZ` observed by the agent. If any check has `ok: false`, the run halts (see Halts) naming the first failing check and its detail; `log()` prints `cycle-run: preflight ok, verify <last line>` otherwise.

The milestone loop (phase `Milestones`). A `while` loop, bounded by `limit` and by a hard cap of 20 iterations. Each iteration:

Step 1, snapshot. One agent, `effort: 'low'`, label `snapshot <n>`, runs `git status --porcelain` (must print nothing), `git rev-parse HEAD`, `date +%s`, and `tools/judge-milestone snapshot <plan> > ${TMPDIR:-/tmp}/cycle-run-<slug>-<head>.snapshot; echo "exit=$?"`, then prints the snapshot file. It returns:

    { type: 'object', required: ['clean', 'head', 'epoch', 'snapshot_exit', 'snapshot_path', 'open_entries', 'done_count', 'defect'],
      properties: { clean: { type: 'boolean' }, head: { type: 'string' }, epoch: { type: 'integer' },
        snapshot_exit: { type: 'integer' }, snapshot_path: { type: 'string' },
        open_entries: { type: 'array', items: { type: 'string' } }, done_count: { type: 'integer' }, defect: { type: 'string' } } }

`open_entries` is the shortened text of every `OPEN` record in file order; `defect` is the stderr line when `snapshot_exit` is 2, else empty. The script halts on `clean: false` with the rule `worktree has uncommitted changes from a previous session`, and on `snapshot_exit` 2 with the defect line. If `open_entries` is empty the loop ends: all milestones are done.

Step 2, the milestone session. One agent, label `milestone: <first open entry, first 60 characters>`, `stallMs: 1800000`, default effort and model, with the schema `{ type: 'object', required: ['report'], properties: { report: { type: 'string' } } }`. Its prompt is the two common lines, then the blueprint's brief verbatim, then the three design lines and the two rules the previous plan learned the hard way:

    You are working in a git repository whose agent harness is already
    installed, and which has a plan in flight at <plan>. Nothing outside
    this repository is available to you, and you must not go looking for it.

    Task: execute the first unfinished milestone of that plan, following the
    repository's own execution procedure, and then stop.

    The procedure is skills/plan-execute/SKILL.md; read it first, then AGENTS.md, then plans/PLANS.md, then the plan.
    The worktree is <worktree>. The plan is <plan>. The previous milestone landed in commits <range>.
    Every commit you make changes the plan file by more than whitespace (AGENTS.md Working rules, decision 0037). Tick a Progress line by changing `- [ ]` to `- [x] (YYYY-MM-DD HH:MMZ)` and change nothing else on that line; evidence goes in the other living sections. Never disable or bypass git hooks.
    When you are done, return a short report: the milestone executed, what you observed, any carve-out against its acceptance, and which milestone is next.

`<range>` is `<previous start sha>..<previous end sha>` from the previous iteration, or `none; this is the first milestone of this run` on the first.

Step 3, judge. One agent, `effort: 'low'`, label `judge <n>`, runs, in this order and recording each exit status and output: `tools/judge-milestone judge <plan> <snapshot_path> <head>` (the `head` from step 1); `./tools/verify` with a tool timeout of at least 300 seconds, recording its exit, last line, and wall time; `git rev-parse HEAD`; `date +%s`. It returns:

    { type: 'object', required: ['judge_exit', 'judge_output', 'verify_exit', 'verify_last_line', 'verify_seconds', 'head', 'epoch'],
      properties: { judge_exit: { type: 'integer' }, judge_output: { type: 'string' }, verify_exit: { type: 'integer' },
        verify_last_line: { type: 'string' }, verify_seconds: { type: 'integer' }, head: { type: 'string' }, epoch: { type: 'integer' } } }

The script halts when `judge_exit` is not 0, with the judge's own lines as the rule, and when `verify_exit` is not 0, with the rule `./tools/verify failed at <head>: <last line>`. Otherwise it appends `{ entry, start, end, seconds, verify_last_line }` to the run's `milestones` list, where `seconds` is the judge agent's epoch minus the snapshot agent's epoch, and logs `cycle-run: advanced "<entry>" in <seconds>s, verify <last line>`. The loop then continues, or stops if `limit` is reached.

Halts. A halt is a returned object, not a thrown error, so the run's result is readable:

    { status: 'halt', plan, milestone: <first open entry or 'none'>, rule: <sentence>, where: <agent label and stage>, milestones: [...] }

and `log()` prints the four lines `cycle-run: halt <plan>`, `cycle-run: milestone <...>`, `cycle-run: <rule>`, `cycle-run: fix the cause in the worktree, commit, and re-run /cycle-run with the same arguments` before returning. A completed run (in M1, one whose loop ended with no open entries or whose limit was reached) returns `{ status: 'advanced' | 'complete', plan, milestones: [...], started_at, finished_at }`, where `finished_at` comes from the last agent's observed `date -u`.

Create `tools/check-workflows` (POSIX sh, executable). For every `.claude/workflows/*.js`: read the file; require its first non-blank, non-comment line to begin `export const meta = {`; extract the meta object text from that `{` to its matching `}` (count braces outside string literals; the meta is a pure literal so this is enough); require `name` in it to equal the file's basename without `.js` and `description` to be a non-empty string; write the rest of the file, wrapped as `(async () => {\n<body>\n})`, to a temporary file and run `node --check` on it; and refuse any body containing `Date.now(`, `Math.random(`, `new Date()`, or `import(`. Output: one `workflows: <file> ... ok` line per file and a final `workflows: N of N ok` on success, exit 0; on failure the offending file and the reason (node's own error text, or `meta.name "<x>" does not match file <y>`), exit 1. Zero files is a failure (`workflows: no scripts under .claude/workflows/`), because an empty scope passing forever is the silent failure `skills/capability-build/SKILL.md` warns about. Add it to `./tools/verify` as one more `check` line, named `workflows`, after `judge-fixtures`.

### M2: the closing sequence

Extend `cycle-run.js` so that when the milestone loop ends with no open entries, phase `Closing` runs:

1. A diffstat agent, `effort: 'low'`, label `diffstat`: `git fetch -q origin`, `base=$(git merge-base origin/main HEAD)`, `git diff --stat $base..HEAD | tail -1`, `git log --reverse --format=%h $base..HEAD`. Returns `{ base, head, diffstat, commits: [...] }`. The script logs `cycle-run: review range <base>..<head>, <diffstat>`.
2. Three reviewer agents in `parallel()`, labels `review: correctness`, `review: scope`, `review: data-honesty`, default effort and model, each read-only, each told it may not spawn subagents, each given the range and the plan path and told to read the diff file by file with `git diff <base>..<head> -- <file>` and `git show`, never to paste the whole diff into its context at once, and to try to refute every candidate finding before keeping it. The lens paragraphs:
   - correctness: does the code do what its surrounding code and tests assume; off-by-one, wrong exit status, unhandled failure, a test that cannot fail, a shell quoting or locale trap.
   - scope: compare the diff with the plan's milestone acceptance and Decision Log; name work the plan did not ask for, acceptance the plan asked for and the diff does not meet, and evidence in the plan that the commits do not support.
   - data honesty: every new data point a reader could see links back to a source; OCR-derived and minutes-derived facts stay distinguished; no code path silently drops rows or swallows an exception without logging it; nothing is hidden from a reader. Where the diff touches no reader-facing data, say so and check the same properties of whatever the diff does produce (for this plan: run output, halt messages, review records).
   Each returns:

        { type: 'object', required: ['lens', 'findings', 'declined'],
          properties: { lens: { type: 'string' },
            findings: { type: 'array', items: { type: 'object', required: ['severity', 'title', 'location', 'claim', 'evidence', 'refutation'],
              properties: { severity: { type: 'string', enum: ['severe', 'important', 'minor'] }, title: { type: 'string' }, location: { type: 'string' },
                claim: { type: 'string' }, evidence: { type: 'string' }, refutation: { type: 'string' } } } },
            declined: { type: 'array', items: { type: 'string' } } } }

   `evidence` is a command and what it printed; `refutation` is the attempt to refute and why it failed. `severe` means a reader of the site, the operator, or the next session is misled or blocked if this ships; `important` means wrong but contained; `minor` is everything else.
3. A record agent, label `review record`, receives the three results as JSON in its prompt, removes duplicates (same location and claim), and appends to the plan's Decision Log one entry in the plan's existing shape: `Decision: review record. After <last milestone>, three fresh reviewers (correctness, scope against the plan, data honesty) read the range <base>..<head>, each told to refute. Counts: <n> severe, <n> important, <n> minor.` followed by each finding as `<severity>: <title> (<location>): <claim>; evidence: <evidence>.`, the declined items, a `Rationale:` line stating that the design's closing sequence writes findings into the plan and halts before the pull request when a finding is severe, and `Date/Author: <date>, review panel (cycle-run), from the three panel reports.` It commits that edit alone with the message `plan: <slug>, review record` and returns `{ severe: n, important: n, minor: n, commit: sha }`. If `severe` is greater than zero the run halts with the rule `review found <n> severe finding(s); see the review record in <plan>`.
4. A retro agent, label `retro`, follows `skills/retro/SKILL.md` on the plan, commits as that skill says (each routed edit in its own commit, the closing section in the plan, the plan moved to `plans/completed/<slug>.md`), and returns `{ report: string, plan_path_now: string }`.
5. A doc-garden agent, label `doc-garden`, follows `skills/doc-garden/SKILL.md` and returns `{ report: string }`.
6. A final verify agent, `effort: 'low'`, label `final verify`: `./tools/verify` (timeout at least 300 seconds), `git status --porcelain` (must be empty), `git rev-parse HEAD`, `date -u`. Halts on a nonzero verify or a dirty tree.
7. A publish agent, `effort: 'low'`, label `publish`: `GIT_TERMINAL_PROMPT=0 git push -u origin plan/<slug>` (exit must be 0; a credential prompt fails instead of hanging); build the pull request body from the `## Outcomes & Retrospective` section of the plan at `plan_path_now` followed by the review record entry, written to a temporary file; `gh pr create --base main --title "<the plan's first heading, up to 70 characters>" --body-file <file>` with the attribution line `🤖 Generated with [Claude Code](https://claude.com/claude-code)` at the end of the body; return `{ pushed: boolean, pr_url: string, detail: string }`. The run's result then is `{ status: 'complete', plan, milestones, review: {severe, important, minor}, pr_url, started_at, finished_at }`.

Every step logs one line. A `null` from any awaited agent (the agent died) is a halt with the rule `agent <label> returned no result`.

### M3: `cycle-plan`

Create `.claude/workflows/cycle-plan.js` with meta `name: 'cycle-plan'`, `description: 'Turn a stated goal into a committed ExecPlan on its own branch, worktree, and venv, or stop with the questions only the operator can answer'`, `whenToUse: 'From any checkout of docket-pub: /cycle-plan <goal in a sentence or two>'`, phases `Scope`, `Setup`, `Author`. `args` is the goal: a string, or an object with `goal` and optional `answers` (a string the operator appends after a questions stop). The script refuses an empty goal.

1. A guard agent, `effort: 'low'`, label `guard`: `pwd -P`; `git rev-parse --show-toplevel`; `git rev-parse --git-common-dir` (the main checkout is its parent directory; compute `main=$(cd "$(git rev-parse --git-common-dir)/.." && pwd -P)`); `git remote get-url origin` names `thinkdarrell/docket-pub`; `gh api user --jq .login` is `thinkdarrell`; `GIT_TERMINAL_PROMPT=0 git fetch -q origin` exits 0; `git rev-parse origin/main`. Returns `{ checkout, main, ok, detail, origin_main }`. Any miss ends the run with `{ status: 'refused', reason }`.
2. A scope agent, label `scope`, default effort and model, read-only, works in the current checkout and reads `AGENTS.md`, `GOALS.md`, `docs/DEBT.md`, `docs/capabilities/index.md`, the open GitHub issues (`gh issue list --state open --limit 50`), and the code the goal touches. It returns the brief:

        { type: 'object', required: ['outcome', 'slug', 'files', 'debt_paid', 'debt_tripped', 'specs_altered', 'out_of_scope', 'questions'],
          properties: { outcome: { type: 'string' }, slug: { type: 'string' },
            files: { type: 'array', items: { type: 'string' } }, debt_paid: { type: 'array', items: { type: 'string' } },
            debt_tripped: { type: 'array', items: { type: 'string' } }, specs_altered: { type: 'array', items: { type: 'string' } },
            out_of_scope: { type: 'array', items: { type: 'string' } }, questions: { type: 'array', items: { type: 'string' } } } }

   `outcome` is the goal restated as something an outside reader can observe; `slug` is lowercase letters, digits, and hyphens, at most 40 characters, not already a branch (`git branch -a --list 'plan/<slug>'` prints nothing); `questions` holds only questions the operator alone can answer, each with why the plan cannot proceed on an assumption. If `questions` is non-empty the run returns `{ status: 'questions', questions, brief }` and stops, with a log line telling the operator to rerun `/cycle-plan` with the answers appended to the goal.
3. A setup agent, `effort: 'low'`, label `setup`: from `<main>`, `git worktree add -b plan/<slug> .claude/worktrees/<slug> origin/main`; then in the new worktree `date +%s; python3.10 -m venv venv && venv/bin/pip install -q -e ".[dev]"; echo "exit=$?"; date +%s`; `venv/bin/python -c 'import docket; print(docket.__file__)'` must print a path inside the new worktree; `mkdir -p .claude` is not needed because `.claude/skills` is committed. Returns `{ worktree, branch, venv_seconds, import_path, ok, detail }`. A failure ends the run with `{ status: 'refused', reason }` and leaves whatever was created for the operator to remove, named in the result.
4. A plan-author agent, label `plan-author`, default effort and model, works in the new worktree (its prompt carries the two common lines with that path), is given the brief as JSON and the goal text, and follows `skills/plan-author/SKILL.md`: reads `plans/PLANS.md`, `GOALS.md`, `ARCHITECTURE.md`, `docs/PRINCIPLES.md`, `docs/capabilities/index.md`, `docs/DEBT.md`, the specs, and the files the brief names; writes `plans/active/<slug>.md` with the brief's content folded into Purpose and Context (the brief is not committed as its own file); commits the plan alone with the message `plan: <slug>, authored`; returns `{ plan_path, milestone_count, first_milestone, first_acceptance, left_out }`.
5. A check agent, `effort: 'low'`, label `check`: from the launching checkout, `tools/judge-milestone snapshot <worktree>/plans/active/<slug>.md; echo "exit=$?"` must exit 0 with at least one `OPEN` record and no `DONE`; `git -C <worktree> status --porcelain` must print nothing; `git -C <worktree> log --oneline origin/main..HEAD` must print exactly one line. Returns `{ ok, detail, open_count }`.

The result is `{ status: 'planned', branch, worktree, plan_path, milestone_count, first_milestone, first_acceptance, left_out, venv_seconds, next: 'Read the plan. Record any change you want as a dated Decision Log entry naming yourself as author, commit it in the worktree, then start a new Claude Code session in <worktree> and run /cycle-run plans/active/<slug>.md' }`.

### M4: the documents

Edit `AGENTS.md`: in Map, the `tools/` line gains `check-workflows` (every saved workflow parses and its meta names its file), and a line is added for `.claude/workflows/`: the factory's two commands, `cycle-plan` and `cycle-run`, with the sentence that `docs/specs/operations.md` Running the factory says how they are run. In Commands, add one line: `Factory: /cycle-plan <goal> from any checkout; /cycle-run plans/active/<slug>.md from a session started in .claude/worktrees/<slug>. One run at a time.` Keep the file under 100 lines and change nothing else.

Edit `docs/specs/operations.md`: a new section `## Running the factory` after Tests, present tense, owning the procedure: what `/cycle-plan` does and returns and what the operator does with the plan before running; what `/cycle-run` does per milestone, the `limit` argument, the closing sequence, what a halt looks like and that resuming is rerunning the same command after fixing and committing; that one run happens at a time because all worktrees share one PostgreSQL; where runs are watched (`/workflows`) and where transcripts live; that `node` is required for `tools/check-workflows`; and that a rerun after a halt inside the closing sequence writes a second review record (the debt row). Local environment gains the `node` requirement in one sentence. The Tests paragraph gains `tools/check-workflows` as verify's fourth check.

Edit `docs/capabilities/judge-milestone.md` Enforcement point: replace the two sentences about `cycle-run` being the next plan with the present tense: `cycle-run` runs `snapshot` before each milestone session and `judge` after it; exit 1 halts the run, exit 2 refuses to start the session. Edit `docs/capabilities/index.md`: the `judge-milestone` row's enforcement column becomes `./tools/verify` (the fixture self-test); `cycle-run` (the judge itself, before and after every milestone session)`.

Edit `GOALS.md` Known unknowns: replace the venv line with the measured fact in one sentence (18 seconds with a warm pip cache, cold not measured) or delete it, and leave the multi-hour line for the retro, which will have this plan's run durations.

Edit `docs/DEBT.md`: delete `D6` (paid: `cycle-plan` builds the venv). Add `D43`: a `cycle-run` rerun after a halt inside the closing sequence appends a second review record and may rerun retro and doc-garden; where: `.claude/workflows/cycle-run.js`; why deferred: idempotence of the closing stages needs each stage to detect its own prior commit, and at L0 the operator reads the plan before merge; trigger: the first time it happens on a real plan. Also `D31` is overdue and its trigger says gardening; this plan's doc-garden pass may delete the stale branches only if it is the operator who runs it, because agents of this factory do not delete remote branches; M4 leaves `D31` alone.

Walk every repository-relative path in the edited files and confirm each resolves (`ls` each).

## Concrete Steps

Working directory for every command: `/Users/darrellnance/docket-pub/.claude/worktrees/factory-workflows`, on branch `plan/factory-workflows`, with `venv/` already built there.

Before any edit, in every milestone session, observe the starting state: `./tools/verify; echo "exit=$?"`. Expected (not yet observed in this plan; the previous plan's final run printed it): four `verify:` summary lines ending `verify: all 3 checks passed in <about 145>s.` and `exit=0`. From M2 on, expect `all 4 checks passed`.

M1. Write `.claude/workflows/cycle-run.js` and `tools/check-workflows` as Plan of Work describes; `chmod +x tools/check-workflows`; add the `check workflows tools/check-workflows` line to `tools/verify`. Run `tools/check-workflows; echo "exit=$?"`. Expected: `workflows: .claude/workflows/cycle-run.js ... ok`, `workflows: 1 of 1 ok`, `exit=0`. Demonstrate the check fails: change `name: 'cycle-run'` to `name: 'cycle-runn'` and run it again. Expected: a line naming the file with `meta.name "cycle-runn" does not match file cycle-run.js`, exit 1. Revert. Insert `return r` at the top level without the wrapper, or temporarily add a line `const t = Date.now()`, and run again. Expected: exit 1 naming the forbidden call. Revert. Run `./tools/verify; echo "exit=$?"`. Expected: a `verify: workflows ... ok (0s)` or `(1s)` line and `verify: all 4 checks passed in <N>s.`, `exit=0`. Commit at coherent steps; every commit touches this plan.

Observed in the M1 session (2026-10-11): every expectation in the M1 paragraph above held as written, with these specifics: the starting `./tools/verify` printed `all 3 checks passed in 160s.`; the renamed-meta run printed exactly `meta.name "cycle-runn" does not match file cycle-run.js`; the `Date.now()` run printed `forbidden call in body (the runtime has no clock or module loader): 309:const t = Date.now()`; the post-change `./tools/verify` printed `verify: workflows ... ok (0s)` and `all 4 checks passed in 139s.` Transcripts are in Artifacts and Notes. Two extra cases were also run: a syntax error in the body (exit 1, node's message naming the workflow file) and an empty `.claude/workflows/` (exit 1, `workflows: no scripts under .claude/workflows/`).

M2. Extend `cycle-run.js` with the closing sequence. Run `tools/check-workflows` (expected `1 of 1 ok`) and `./tools/verify` (expected `all 4 checks passed`). Read the script once more against Plan of Work M2 and list in Artifacts and Notes each stage with the line numbers that implement it.

Observed in the M2 session (2026-10-11), starting from `f0f7b6a`: the starting `./tools/verify` printed `verify: all 4 checks passed in 156s.` and `exit=0` (test-db 0s, unit+web+services 61s, integration 91s, judge-fixtures 4s, workflows 0s). After the closing block replaced the three placeholder lines (311 to 313) `tools/check-workflows` printed `workflows: .claude/workflows/cycle-run.js ... ok`, `workflows: 1 of 1 ok`, `exit=0`; the file is 605 lines. The stub dry run (Decision Log) printed the expected log lines and results for all four scenarios; transcript in Artifacts and Notes. The post-change `./tools/verify` printed `verify: all 4 checks passed in 157s.` with `exit=0`; transcript in Artifacts and Notes.

M3. Write `.claude/workflows/cycle-plan.js`. Run `tools/check-workflows` (expected `workflows: 2 of 2 ok`) and `./tools/verify`. In Artifacts and Notes list each stage with its line numbers.

Observed in the M3 session (2026-10-11, launched by `cycle-run` with `limit` 1), starting from `4a731fd`: the starting `./tools/verify` printed `verify: all 4 checks passed in 156s.` and `exit=0` (test-db 0s, unit+web+services 66s, integration 87s, judge-fixtures 3s, workflows 0s). After writing `.claude/workflows/cycle-plan.js` (316 lines) `tools/check-workflows` printed `workflows: .claude/workflows/cycle-plan.js ... ok`, `workflows: .claude/workflows/cycle-run.js ... ok`, `workflows: 2 of 2 ok`, `exit=0`. The stub dry run (Decision Log) printed the expected log lines and results for all ten scenarios; transcript in Artifacts and Notes. The post-change `./tools/verify` on `3ebf38c` printed `verify: all 4 checks passed in 150s.` with `exit=0`; transcript in Artifacts and Notes.

M4. Make the edits. Run `wc -l AGENTS.md` (expected: at most 100). Walk the paths: for every backticked repository-relative path in the five edited files, `ls` it. Run `./tools/verify`. Expected: `all 4 checks passed`.

Observed in the M4 session (2026-10-11, launched by `cycle-run` with no limit), starting from `c84c8a1`: the starting `./tools/verify` printed `verify: all 4 checks passed in 134s.` and `exit=0` (test-db 0s, unit+web+services 59s, integration 71s, judge-fixtures 4s, workflows 0s). The six edits (Plan of Work M4 names five documents; `docs/capabilities/judge-milestone.md` and `docs/capabilities/index.md` are two files) were applied by one exact-string replacement script that exits when an anchor is not found exactly once; `git diff --stat` printed `6 files changed, 25 insertions(+), 12 deletions(-)`. `wc -l AGENTS.md` printed `48` (46 before). `grep -c '^| D6 ' docs/DEBT.md` printed `0`, `grep -c '^| D43 ' docs/DEBT.md` printed `1`, `grep -c planned docs/capabilities/index.md` printed `0`. The path walk and the post-change `./tools/verify` are recorded in the next paragraph once observed.

Observed in the M4 session, continued: the mechanical path walk (Decision Log) extracted the backticked path-like tokens from the six files and `test -e` found 132 of them in the worktree; the 26 tokens it reported missing were each resolved by hand: names relative to a parent given earlier in their sentence (`fixtures/judge/run` under `tools/`; `index.md` and `operations.md` under `docs/capabilities/` and `docs/specs/`; `admin.py`, `admin_badge_review.py`, `admin_transcripts.py`, `create_admin.py`, `public.py`, `source_security.py` after `src/docket/web/auth.py`; `badges_policy.py`, `batch_ingest.py` after `src/docket/ai/pipeline.py`; `compare.py`, `events.py` after `src/docket/ai/transcripts/ab.py`; `analysis/minutes_parser.py` and `ai/`, `services/` under `src/docket/`; `cycle-plan.js`, `cycle-run.js` under `.claude/workflows/`), all of which `test -e` found at the full path; `origin/main` (a git ref, `git rev-parse --verify` resolves it); `thinkdarrell/docket-pub`, `thinkdarrell/al-municipal-meetings`, `thinkdarrell/docket-pub-site`, `thinkdarrell/docket-pub-archived` (GitHub repositories, not paths); `DATABASE_URL=postgresql://...` (an assignment); `./COMMIT_SHA` (a deploy-time scratch file, not in the tree, and not gitignored either: Surprises & Discoveries); and `.claude/worktrees/factory-workflows` (relative to the main checkout, and this session's own `pwd -P`). Eleven templated tokens (`<slug>`, `<name>`) were listed and not tested. `~/.claude-personal/projects`, the transcript location named in Running the factory, exists on this machine. The post-change `./tools/verify` on the tree committed as `fb472fa` printed `verify: all 4 checks passed in 155s.` and `exit=0` (test-db ... ok (1s) postgresql://docket@localhost:5432/docket_test_7da4fd23; unit+web+services ... ok (62s); integration ... ok (88s); judge-fixtures ... ok (4s); workflows ... ok (0s)). The tick commit is `fb472fa`'s successor, `6cb9cde`. Judge self-check after that commit: `git show c84c8a1:plans/active/factory-workflows.md` was snapshotted (`DONE 13, DONE 14, DONE 15, OPEN 16`, exit 0) and `tools/judge-milestone judge plans/active/factory-workflows.md <that snapshot> c84c8a1` printed `judge: advanced "(2026-10-11 22:16Z) M4: `AGENTS.md`, `docs/specs/operations.md`, the jud..."` with `judge exit=0`; `./tools/verify` was not rerun after the plan-only commits, since they change no file verify reads. The commit carrying this sentence is the third and last of the session.

Live runs (operator's session, not a milestone session). After M1 is judged advanced by hand: with the shell in the worktree, launch `cycle-run` on this plan with `limit` 1, by name if `/reload-skills` has been run or else by path (`Workflow({scriptPath: '.claude/workflows/cycle-run.js', args: {plan: 'plans/active/factory-workflows.md', limit: 1}})`). Expected: `cycle-run: preflight ok, verify ...`, then one milestone agent, then `cycle-run: advanced "M2: ..." in <seconds>s, verify verify: all 4 checks passed in <N>s.`, result status `advanced`. Append the result to Artifacts and Notes. Repeat with `limit` 1 for M3. Then run `cycle-plan` by path from the worktree with the goal under Validation and Acceptance; append its result. Then launch `cycle-run` with no limit: expected M4 advances, then `Closing` logs the review range, the record commit, the retro and doc-garden reports, `final verify`, and a `pr_url`.

## Validation and Acceptance

M1 is accepted when, in the milestone session: `tools/check-workflows` prints `workflows: 1 of 1 ok` and exits 0 on the committed tree; it exits 1 with the file named on the renamed meta and on the forbidden `Date.now(`; `./tools/verify` prints `verify: workflows ... ok` as its fourth check and `verify: all 4 checks passed in <N>s.`, exit 0; and `.claude/workflows/cycle-run.js` contains the preflight checks one to ten, the snapshot, milestone, and judge agents with the schemas and prompt text above, the `limit` handling, and the halt shape, which the session confirms by reading its own file and listing line numbers in Artifacts and Notes. The live half (the run that executes M2) is recorded by the operator's session.

M2 is accepted when `tools/check-workflows` and `./tools/verify` pass as above and the script contains the seven closing stages with the lens paragraphs, schemas, and record shape above, listed by line number in Artifacts and Notes. The live half is the closing run after M4.

M3 is accepted when `tools/check-workflows` prints `workflows: 2 of 2 ok`, `./tools/verify` passes, and `cycle-plan.js` contains the five stages above, listed by line number. The live half, run by the operator's session from this worktree with the goal `Fix GitHub issue #110: score_overrides values are written as floats and the calibration queries in src/docket/services/calibration.py and src/docket/ai/calibration.py cast them with ::int, so the daily calibration_report task fails silently and the admin calibration page returns 500; cast with ::numeric::int and add a test that fails on a float value`, is accepted when the result's status is `planned`, `.claude/worktrees/<slug>` exists on branch `plan/<slug>` with one commit over `origin/main` and a green `tools/judge-milestone snapshot`, and `venv_seconds` is reported.

M4 is accepted when `wc -l AGENTS.md` is at most 100, every repository-relative path in the five edited files resolves, `./tools/verify` passes, `docs/DEBT.md` has no `D6` row and has a `D43` row, and `docs/capabilities/index.md` no longer says `cycle-run` is planned.

The plan as a whole is accepted when `cycle-run`, launched once with no limit after M3, executes M4, writes a review record with zero `severe` findings, runs retro and doc-garden, passes the final verify, pushes `plan/factory-workflows`, and returns a `pr_url`; the operator's session records that result here before the pull request is read.

## Idempotence and Recovery

Every milestone's edits are to new files or to documents, and each is committed with the plan; a session that dies leaves landed commits and a plan whose Progress still shows the milestone open, which `cycle-run` or the operator picks up by rerunning. `tools/check-workflows` and `./tools/verify` can be run any number of times. A `cycle-run` halt is resumed by fixing the cause in the worktree, committing, and rerunning the same command; preflight and the snapshot run again, done milestones are skipped. A halt inside the closing sequence is resumed the same way but writes a second review record (`D43` after M4). `cycle-plan`'s setup stage is not idempotent: a second run with the same slug fails at `git worktree add` because the branch exists, and the operator removes the worktree with `git worktree remove .claude/worktrees/<slug>` and the branch with `git branch -D plan/<slug>` before retrying. The temporary snapshot files under `${TMPDIR:-/tmp}` are small and may be deleted at any time between runs.

## Artifacts and Notes

Filled by the sessions as they observe. Operator-session entries are signed `operator session` and carry the run id the Workflow tool printed.

Operator session, live run 1 (run id `wf_03f7780e-f69`, launched 2026-10-11 21:06:46Z by path with `args {plan: 'plans/active/factory-workflows.md', limit: 1}`, shell in the worktree, M1's script at `f0f7b6a`). Observed from the run's result and its journal: preflight returned all ten checks `ok` (`worktree /Users/darrellnance/docket-pub/.claude/worktrees/factory-workflows; /Users/darrellnance/docket-pub/.git`, `branch plan/factory-workflows`, `origin https://github.com/thinkdarrell/docket-pub.git`, `ls-remote fc63c75 HEAD; exit=0`, `gh-user thinkdarrell`, `venv-import .../factory-workflows/src/docket/__init__.py`, `verify: all 4 checks passed in 153s.`, `snapshot open=3 done=1`), `started_at 2026-10-11T21:06:58Z`. Snapshot 1: clean, head `f0f7b6a`, snapshot file under `/var/folders/.../T//cycle-run-factory-workflows-f0f7b6a....snapshot`, three open entries, one done. The milestone session landed `a03e5e8`, `4c3ecf6`, `d362e09`. Judge 1: `judge: advanced "(2026-10-11 21:20Z) M2: ..."`, exit 0; `./tools/verify` exit 0, `verify: all 4 checks passed in 165s.` in 165 s; head `d362e09`. Result: `status advanced`, one milestone, `seconds 903`, `finished_at 2026-10-11T21:25:01Z`; four agents, no errors, no empty results; wall time from launch to result about 18 minutes. The limit of 1 stopped the loop as designed. Nothing in the run needed a hand correction. Appended by the operator session in a plan-only commit before run 2.

Operator session, live run 2 (run id `wf_5e4ca6e6-e88`, launched 2026-10-11 about 21:26Z by path with the same arguments, M2's script at `4a731fd`). Preflight: all ten checks `ok`, `verify: all 4 checks passed in 161s.`, `snapshot open=2 done=2`, `started_at 2026-10-11T21:26:09Z`. Snapshot 1: clean, head `4a731fd`, two open entries, two done. The milestone session landed `3ebf38c` (`.claude/workflows/cycle-plan.js`, 316 lines), `c621267`, `a1cf435`. Judge 1: `judge: advanced "(2026-10-11 21:41Z) M3: ..."`, exit 0; `./tools/verify` exit 0, `verify: all 4 checks passed in 161s.` in 162 s; head `a1cf435`. Result: `status advanced`, `seconds 1008`, `finished_at 2026-10-11T21:46:09Z`; four agents, no errors; wall time about 20 minutes. `tools/check-workflows` run by hand afterwards printed `workflows: 2 of 2 ok`. Appended by the operator session in a plan-only commit before the `cycle-plan` trial.

Operator session, `cycle-plan` live trial (run id `wf_7f51e6c3-55e`, launched 2026-10-11 about 21:48Z by path from this worktree with the goal stated under Validation and Acceptance, M3's script at `f9b562a`). Guard: `ok`, checkout `/Users/darrellnance/docket-pub/.claude/worktrees/factory-workflows`, main `/Users/darrellnance/docket-pub` (resolved from the common git directory of a linked worktree), origin `thinkdarrell/docket-pub.git`, gh user `thinkdarrell`, fetch `exit=0`, `origin/main fc63c75`. Scope: no questions; slug `calibration-float-scores`; the brief confirmed the cast failure read-only on the local server (`('{"a": 7.0}'::jsonb->>'a')::int` errors, `::numeric::int` returns 7) and corrected two of its own counts from observation. Setup: `git worktree add -b plan/calibration-float-scores .claude/worktrees/calibration-float-scores origin/main` exit 0; venv built in 15 s (warm cache); `import docket` resolved to the new worktree's `src/docket/__init__.py`. Plan-author: `plans/active/calibration-float-scores.md`, 276 lines, two milestones, committed alone as `c172549 plan: calibration-float-scores, authored`. Check: snapshot exit 0 with `OPEN=2 DONE=0`, clean tree, exactly one commit over `origin/main`. Result `status planned`, `venv_seconds 15`; five agents, no errors; wall time about 17 minutes. Verified again by the operator session afterwards: `git worktree list` shows the new worktree on its branch, `git log origin/main..HEAD` prints the one commit, `tools/judge-milestone snapshot` on the new plan exits 0 with two `OPEN` records. The plan-author noted that `origin/main` does not yet carry `tools/verify`, `tools/test-db`, or `tools/judge-milestone` (they are on pull request #111) and wrote the plan with that fallback stated. The branch and worktree are left for the operator, as the Decision Log says. Appended by the operator session in a plan-only commit before the final run.

M1 session, 2026-10-11 (hand-launched milestone session). Starting state, observed before any edit, in `/Users/darrellnance/docket-pub/.claude/worktrees/factory-workflows` at `c309ace`:

    ./tools/verify; echo "exit=$?"
    ...
    verify: test-db ... ok (3s) postgresql://docket@localhost:5432/docket_test_7da4fd23
    verify: unit+web+services ... ok (79s)
    verify: integration ... ok (74s)
    verify: judge-fixtures ... ok (4s)
    verify: all 3 checks passed in 160s.
    exit=0

    tools/judge-milestone snapshot plans/active/factory-workflows.md; echo "exit=$?"
    OPEN	13	M1: ...	OPEN	14	M2: ...	OPEN	15	M3: ...	OPEN	16	M4: ...   (four records, one per line)
    exit=0

`.claude/` held only the `skills -> ../skills` symlink; `.claude/workflows/` did not exist. `which node` printed `/opt/homebrew/bin/node`, `node --version` printed `v26.8.2`.

M1 session, `tools/check-workflows` on the written tree (before the verify line was added), observed:

    tools/check-workflows; echo "exit=$?"
    workflows: .claude/workflows/cycle-run.js ... ok
    workflows: 1 of 1 ok
    exit=0

The failure demonstrations, each followed by restoring the file (`cmp` against a copy printed nothing; `git status` showed only the intended changes):

    # name: 'cycle-run' -> name: 'cycle-runn'
    workflows: .claude/workflows/cycle-run.js ... FAILED: meta.name "cycle-runn" does not match file cycle-run.js
    workflows: 1 of 1 failed
    exit=1
    # appended: const t = Date.now()
    workflows: .claude/workflows/cycle-run.js ... FAILED: forbidden call in body (the runtime has no clock or module loader): 309:const t = Date.now()
    workflows: 1 of 1 failed
    exit=1
    # appended: const = broken(
    workflows: .claude/workflows/cycle-run.js ... FAILED: node --check: .claude/workflows/cycle-run.js (body after the meta object, wrapped; line 1 is the wrapper):310 const = broken(       ^
    workflows: 1 of 1 failed
    exit=1
    # appended a bare top-level `return 1` (the wrapper exists so this parses)
    workflows: .claude/workflows/cycle-run.js ... ok
    workflows: 1 of 1 ok
    exit=0
    # cycle-run.js moved out of the directory
    workflows: no scripts under .claude/workflows/
    exit=1

The first run of the syntax-error case printed node's temporary path (`/private/var/folders/.../check-workflows.dkW7iw/cycle-run.wrapped.js:310`) instead of the workflow file, because macOS sets `TMPDIR` under `/var/` and node prints the resolved `/private/var/` path, so a literal `sed s|$wrapped|...|` matched nothing. The substitution now matches any path ending in `<base>.wrapped.js`; the transcript above is the second run.

M1 session, `./tools/verify` after adding `check "workflows" tools/check-workflows` after the `judge-fixtures` line, observed (full log was 141 lines; the `workflows` check's own output was the two `workflows:` lines above):

    ./tools/verify > /tmp/cw-verify.log 2>&1; echo "exit=$?"
    exit=0
    verify: test-db ... ok (1s) postgresql://docket@localhost:5432/docket_test_7da4fd23
    verify: unit+web+services ... ok (59s)
    verify: integration ... ok (75s)
    verify: judge-fixtures ... ok (4s)
    verify: workflows ... ok (0s)
    verify: all 4 checks passed in 139s.

M1 session, `.claude/workflows/cycle-run.js` as committed in `094a50d` (313 lines), read back with `grep -n`; the parts Plan of Work M1 requires and where they are:

    1-6      meta literal: name, description, whenToUse, phases Preflight / Milestones / Closing
    21-35    args normalised to `plan` (string) and `limit` (positive integer or Infinity); string, array, and object forms
    37-44    refusals: no plan path; path not matching ^plans/active/<name>.md$ (result { status: 'refused', plan, reason })
    46-48    slug, branch `plan/<slug>`, HARD_CAP = 20
    55-60    common(worktree): the two lines every later prompt begins with
    65-89    isoFromEpoch(epoch): finished_at from an agent-observed epoch, integer arithmetic
    94-100   halt(rule, where, milestone): logs the four `cycle-run:` lines, returns { status: 'halt', plan, milestone, rule, where, milestones }
    108      phase('Preflight')
    110-125  PREFLIGHT_SCHEMA (worktree, started_at, checks[name, ok, detail])
    127-144  preflight prompt; checks 1 to 10 on lines 133-142 (worktree, branch, plan-file, clean-tree, origin, ls-remote, gh-user, venv-import, verify with a 300000 ms timeout, snapshot); started_at from `date -u +%Y-%m-%dT%H:%M:%SZ`
    146-156  preflight agent (effort low, label preflight); null and first failing check halt; `cycle-run: preflight ok, verify <detail>`
    163      phase('Milestones')
    165-178  SNAPSHOT_SCHEMA (clean, head, epoch, snapshot_exit, snapshot_path, open_entries, done_count, defect)
    180      REPORT_SCHEMA ({ report })
    182-194  JUDGE_SCHEMA (judge_exit, judge_output, verify_exit, verify_last_line, verify_seconds, head, epoch)
    196-209  snapshot prompt: git status, rev-parse HEAD, date +%s, snapshot to ${TMPDIR:-/tmp}/cycle-run-<slug>-<head>.snapshot
    211-227  milestone prompt: common lines, the blueprint brief verbatim, the three design lines, the two rules
    229-247  judge prompt: judge <plan> <snapshot_path> <head>, verify (300000 ms), rev-parse HEAD, date +%s
    249      while (milestones.length < limit && iteration < HARD_CAP)
    252-272  step 1: snapshot agent (effort low, label `snapshot <n>`); halts on null, clean false (`worktree has uncommitted changes from a previous session`), exit 2 (defect line), other nonzero; loop ends on no open entries
    274-281  step 2: milestone agent (label `milestone: <entry, 60 chars>`, stallMs 1800000, default effort and model); halt on null
    283-293  step 3: judge agent (effort low, label `judge <n>`); halts on null, judge_exit != 0 (judge output as rule), verify_exit != 0 (`./tools/verify failed at <head>: <last line>`)
    295-297  milestones.push({ entry, start, end, seconds, verify_last_line }); `cycle-run: advanced "<entry>" in <s>s, verify <last line>`; range for the next brief
    300-302  hard-cap notice (logged, not silent)
    304-313  results: { status: 'advanced' | 'complete', plan, milestones, started_at, finished_at }; the comment at 311 marks where M2's Closing phase attaches

M1 session, self-check with the judge after commits `094a50d` and `6beaf10`, using a snapshot taken from the plan as committed at the session's start sha (`git show c309ace:plans/active/factory-workflows.md`), observed:

    tools/judge-milestone snapshot /tmp/fw-start-plan.md > /tmp/fw-start.snapshot; echo "snapshot exit=$?"
    snapshot exit=0
    tools/judge-milestone judge plans/active/factory-workflows.md /tmp/fw-start.snapshot c309ace; echo "judge exit=$?"
    judge: advanced "(2026-10-11 21:04Z) M1: `.claude/workflows/cycle-run.js` runs preflight ..."
    judge exit=0

This is the session's own check, not the operator's hand judgement the trial schedule calls for; the commit carrying this note lands after it, so the operator's judge sees three commits since `c309ace`.

M2 session, 2026-10-11 (milestone session launched by the operator's `cycle-run` with `limit` 1, per the trial schedule). Starting state, observed before any edit, at `f0f7b6a`:

    ./tools/verify > <scratch>/verify-start.log 2>&1; echo "exit=$?"
    verify: test-db ... ok (0s) postgresql://docket@localhost:5432/docket_test_7da4fd23
    verify: unit+web+services ... ok (61s)
    verify: integration ... ok (91s)
    verify: judge-fixtures ... ok (4s)
    verify: workflows ... ok (0s)
    verify: all 4 checks passed in 156s.
    exit=0

The repository has no active git hooks (`git config core.hooksPath` printed nothing; `.git/hooks` holds only `.sample` files), so the retro and doc-garden prompts carry no commit rule beyond what their skills say.

M2 session, after replacing lines 311 to 313 of `cycle-run.js` (the M2 placeholder) with the closing block:

    tools/check-workflows; echo "exit=$?"
    workflows: .claude/workflows/cycle-run.js ... ok
    workflows: 1 of 1 ok
    exit=0
    wc -l .claude/workflows/cycle-run.js
    605

M2 session, stub dry run of the closing path (Decision Log; the stub is `dryrun.mjs` in the session scratchpad, not committed). The stub's preflight passes and its snapshot returns no open entries, so each scenario runs straight into `Closing`; two of the three canned reviewers return the same minor finding, and the canned record agent reports one minor after deduplication. The `LOG` lines are the script's `log()` calls, `RESULT` the returned value:

    === scenario complete ===
    PHASE Closing
    LOG cycle-run: review range bbbbbbb2..aaaaaaa1,  3 files changed, 10 insertions(+) (2 commits)
    LOG cycle-run: review panel reported 0 severe, 0 important, 2 minor before deduplication
    LOG cycle-run: review record committed as ccccccc: 0 severe, 0 important, 1 minor
    LOG cycle-run: retro done, plan now at plans/completed/x.md: retro report line 1
    LOG cycle-run: doc-garden done: garden report
    LOG cycle-run: final verify ok at ddddddd, verify: all 4 checks passed in 150s. (150s)
    LOG cycle-run: complete; plans/active/x.md closed to https://github.com/thinkdarrell/docket-pub/pull/999
    RESULT {"status":"complete","plan":"plans/active/x.md","plan_path_now":"plans/completed/x.md","milestones":[],"review":{"severe":0,"important":0,"minor":1},"pr_url":"https://github.com/thinkdarrell/docket-pub/pull/999","started_at":"2026-10-11T00:00:00Z","finished_at":"2026-10-11T01:01:00Z"}
    === scenario severe === (record returns severe 1)
    LOG cycle-run: halt plans/active/x.md
    LOG cycle-run: milestone none
    LOG cycle-run: review found 1 severe finding(s); see the review record in plans/active/x.md
    LOG cycle-run: fix the cause in the worktree, commit, and re-run /cycle-run with the same arguments
    RESULT {"status":"halt",...,"rule":"review found 1 severe finding(s); see the review record in plans/active/x.md","where":"review record, closing stage 3 review record","milestones":[]}
    === scenario reviewnull === (the scope reviewer returns null)
    LOG cycle-run: agent review: scope returned no result
    RESULT {"status":"halt",...,"where":"review: scope, closing stage 2 review panel",...}
    === scenario fetchfail === (fetch_exit 128)
    LOG cycle-run: git fetch origin exited 128; the review range cannot be measured against a current origin/main
    RESULT {"status":"halt",...,"where":"diffstat, closing stage 1 diffstat",...}

The rendered `review record`, `publish`, and `review: scope` prompts were printed from the stub and read back; the substituted values (range, commit list, slug, branch, plan path after the move) appeared where intended.

M2 session, `./tools/verify` on the tree committed in `a03e5e8` (script and the first batch of plan evidence), observed:

    ./tools/verify > <scratch>/verify-after.log 2>&1; echo "exit=$?"
    verify: test-db ... ok (1s) postgresql://docket@localhost:5432/docket_test_7da4fd23
    verify: unit+web+services ... ok (64s)
    verify: integration ... ok (88s)
    verify: judge-fixtures ... ok (4s)
    verify: workflows ... ok (0s)
    verify: all 4 checks passed in 157s.
    exit=0

M2 session, `.claude/workflows/cycle-run.js` as committed in `a03e5e8` (605 lines; lines 1 to 310 are M1's and unchanged except that the three placeholder lines 311 to 313 are gone), read back with `grep -n`; the parts Plan of Work M2 requires and where they are:

    311-318  closing comment: the seven stages and the contract
    320      phase('Closing')
    324-326  closingNull(label, stage): the `agent <label> returned no result` halt for every closing agent, milestone 'none'
    330      lastLanded: the last entry this run landed, or null (Decision Log)
    333-343  DIFFSTAT_SCHEMA (fetch_exit, base, head, diffstat, commits)
    345-356  stage 1 diffstat prompt: fetch, merge-base origin/main HEAD, rev-parse HEAD, diff --stat | tail -1, log --reverse --format=%h
    358-364  diffstat agent (effort low, label diffstat); halts on null and nonzero fetch; `cycle-run: review range <base>..<head>, <diffstat> (<n> commits)`
    368-390  REVIEW_SCHEMA (lens, findings[severity enum severe/important/minor, title, location, claim, evidence, refutation], declined)
    392-408  LENSES: the correctness (394), scope (399), and data-honesty (404) paragraphs
    410-426  reviewPrompt(lens): read-only, no subagents, range and plan path, --stat and log first, `git diff <range> -- <file>` and `git show`, never the whole diff, refute before keeping, evidence and location definitions, the three severities
    428-430  stage 2: parallel() over the three lenses, labels `review: <lens>`, phase 'Closing', default effort and model
    431-433  a null reviewer halts naming its lens
    434-435  pre-deduplication counts logged
    439-448  RECORD_SCHEMA (severe, important, minor, commit)
    450-479  recordPrompt(): the three reports as JSON, dedupe on location and claim, the entry text (Decision: review record. After ..., 463), finding lines, Declined, Rationale, Date/Author, commit alone as `plan: <slug>, review record`
    481-487  stage 3: record agent (label `review record`); null halt; `cycle-run: review record committed as <sha>: <counts>`; severe > 0 halts with `review found <n> severe finding(s); see the review record in <plan>`
    491-495  RETRO_SCHEMA (report, plan_path_now)
    497-504  stage 4 retro prompt: skills/retro/SKILL.md, the lifecycle steps from plans/PLANS.md, each routed edit its own commit, move to plans/completed/<slug>.md, clean tree
    506-509  retro agent (label retro, stallMs 1800000); null halt; planNow = plan_path_now
    512      GARDEN_SCHEMA (report)
    514-519  stage 5 doc-garden prompt: skills/doc-garden/SKILL.md, one fix per commit, clean tree
    521-523  doc-garden agent (label doc-garden, stallMs 1800000); null halt
    526-538  FINAL_SCHEMA (verify_exit, verify_last_line, verify_seconds, clean, status, head, finished_at)
    540-550  stage 6 final verify prompt: verify (300000 ms timeout), status --porcelain, rev-parse HEAD, date -u
    552-560  final verify agent (effort low); halts on null, nonzero verify (`./tools/verify failed at <head>: <last line>`), dirty tree
    564-573  PUBLISH_SCHEMA (pushed, pr_url, detail, finished_at)
    575-584  stage 7 publish prompt: GIT_TERMINAL_PROMPT=0 push -u, title from the first `# ` line cut to 70, body = Outcomes & Retrospective + review record + attribution line via sed/awk to a temp file, gh pr create --base main --body-file, existing-pull-request fallback, date -u
    586-594  publish agent (effort low); halts on null, pushed false, empty pr_url; `cycle-run: complete; <plan> closed to <pr_url>`
    596-605  result { status: 'complete', plan, plan_path_now, milestones, review, pr_url, started_at, finished_at }

M2 session, self-check with the judge after commits `a03e5e8` and `4c3ecf6`, using a snapshot taken from the plan as committed at the session's start sha (`git show f0f7b6a:plans/active/factory-workflows.md`), observed:

    tools/judge-milestone snapshot <scratch>/fw-m2-start-plan.md > <scratch>/fw-m2-start.snapshot; echo "snapshot exit=$?"
    snapshot exit=0
    tools/judge-milestone judge plans/active/factory-workflows.md <scratch>/fw-m2-start.snapshot f0f7b6a; echo "judge exit=$?"
    judge: advanced "(2026-10-11 21:20Z) M2: `cycle-run` closes a finished plan: review panel..."
    judge exit=0

This is the session's own check; `cycle-run`'s judge agent runs the same command from its own snapshot after this session returns, and the commit carrying this note lands after the check, so that judge sees three commits since `f0f7b6a`.

M3 session, 2026-10-11 (milestone session launched by the operator's `cycle-run` with `limit` 1, per the trial schedule). Starting state, observed before any edit, at `4a731fd`:

    ./tools/verify > <scratch>/verify-baseline.txt 2>&1; echo "exit=$?"
    verify: test-db ... ok (0s) postgresql://docket@localhost:5432/docket_test_7da4fd23
    verify: unit+web+services ... ok (66s)
    verify: integration ... ok (87s)
    verify: judge-fixtures ... ok (3s)
    verify: workflows ... ok (0s)
    verify: all 4 checks passed in 156s.
    exit=0

M3 session, after writing `.claude/workflows/cycle-plan.js`:

    tools/check-workflows; echo "exit=$?"
    workflows: .claude/workflows/cycle-plan.js ... ok
    workflows: .claude/workflows/cycle-run.js ... ok
    workflows: 2 of 2 ok
    exit=0
    wc -l .claude/workflows/cycle-plan.js
    316

M3 session, stub dry run (Decision Log; `dryrun-plan.mjs` in the session scratchpad, not committed). Canned returns: a passing guard (`checkout /repo/.claude/worktrees/fw`, `main /repo`), a brief with slug `fix-110` and no questions, a setup with `venv_seconds 18`, a two-milestone plan, a passing check; each scenario overrides one agent's return. The `LOG` and `RESULT` lines, trimmed where marked `...`:

    === scenario emptygoal === (args '   ')
    LOG cycle-plan: refused: no goal given; run /cycle-plan <goal in a sentence or two>
    RESULT {"status":"refused","reason":"no goal given","where":"arguments"}
    === scenario planned === (args 'Fix GitHub issue #110'; the array form ['Fix GitHub issue #110', 'answers here'] printed the same lines)
    PHASE Scope
    LOG cycle-plan: guard ok, checkout /repo/.claude/worktrees/fw, main /repo, origin/main abcdef0
    LOG cycle-plan: scope ok, slug fix-110: 1 file(s), 0 debt paid, 1 debt tripped, 0 spec(s) altered, 1 out of scope
    PHASE Setup
    LOG cycle-plan: setup ok, worktree /repo/.claude/worktrees/fix-110 on plan/fix-110, venv built in 18s
    PHASE Author
    LOG cycle-plan: plan authored at plans/active/fix-110.md, 2 milestone(s); first: M1: failing test
    LOG cycle-plan: check ok, 2 open milestone(s), clean tree, one commit over origin/main
    LOG cycle-plan: planned; plans/active/fix-110.md on plan/fix-110 in /repo/.claude/worktrees/fix-110
    RESULT {"status":"planned","branch":"plan/fix-110","worktree":"/repo/.claude/worktrees/fix-110","plan_path":"plans/active/fix-110.md","milestone_count":2,"first_milestone":"M1: failing test","first_acceptance":"pytest fails before, passes after","left_out":"nothing","venv_seconds":18,"next":"Read the plan. Record any change you want as a dated Decision Log entry naming yourself as author, commit it in the worktree, then start a new Claude Code session in /repo/.claude/worktrees/fix-110 and run /cycle-run plans/active/fix-110.md"}
    === scenario questions === (scope returns one question)
    LOG cycle-plan: questions: the scope agent asks 1 question(s) only the operator can answer; rerun /cycle-plan with the answers appended to the goal
    LOG cycle-plan: question 1: Which page shows the result? (the goal names none; the plan cannot pick one)
    RESULT {"status":"questions","questions":["Which page shows the result? ..."],"brief":{...}}
    === scenario guardmiss === (guard ok false)
    LOG cycle-plan: refused: guard check failed: MISS gh-user: nobody
    RESULT {"status":"refused","reason":"guard check failed: MISS gh-user: nobody","where":"guard, stage 1"}
    === scenario badslug === (slug "Fix_Issue 110")
    LOG cycle-plan: refused: scope agent returned slug "Fix_Issue 110", which is not lowercase letters, digits, and hyphens of at most 40 characters
    RESULT {"status":"refused",...,"where":"scope, stage 2","brief":{...}}
    === scenario setupfail === (setup ok false)
    LOG cycle-plan: refused: setup failed: step 3 failed; exists: branch plan/fix-110, dir .claude/worktrees/fix-110, venv/ partial
    RESULT {"status":"refused",...,"where":"setup, stage 3","branch":"plan/fix-110","worktree":"/repo/.claude/worktrees/fix-110","cleanup":"from /repo: git worktree remove --force .claude/worktrees/fix-110; git branch -D plan/fix-110"}
    === scenario checkfail === (check ok false)
    LOG cycle-plan: the plan is committed in /repo/.claude/worktrees/fix-110 but failed the check; fix it there, commit, and read it before running /cycle-run
    LOG cycle-plan: refused: check failed: MISS snapshot: exit=2 judge: defect ... is missing the required section `## Decision Log`
    RESULT {"status":"refused",...,"where":"check, stage 5","branch":"plan/fix-110","worktree":"/repo/.claude/worktrees/fix-110","plan_path":"plans/active/fix-110.md","cleanup":"from /repo: ..."}
    === scenario nullscope === (scope returns null)
    LOG cycle-plan: refused: agent scope returned no result
    RESULT {"status":"refused","reason":"agent scope returned no result","where":"scope, stage 2"}
    === scenario nullauthor === (plan-author returns null)
    LOG cycle-plan: refused: agent plan-author returned no result
    RESULT {"status":"refused",...,"where":"plan-author, stage 4","branch":"plan/fix-110","worktree":"/repo/.claude/worktrees/fix-110","cleanup":"from /repo: ..."}

The rendered `guard`, `scope`, `setup`, `plan-author`, and `check` prompts were printed from the stub with `{goal, answers}` arguments and read back; the checkout, main checkout, worktree, slug, branch, plan path, goal, appended answers, and brief JSON appeared where intended.

M3 session, `./tools/verify` on the tree committed in `3ebf38c` (script and the first batch of plan evidence), observed:

    ./tools/verify > <scratch>/verify-after.txt 2>&1; echo "exit=$?"
    verify: test-db ... ok (0s) postgresql://docket@localhost:5432/docket_test_7da4fd23
    verify: unit+web+services ... ok (65s)
    verify: integration ... ok (81s)
    verify: judge-fixtures ... ok (4s)
    verify: workflows ... ok (0s)
    verify: all 4 checks passed in 150s.
    exit=0

M3 session, `.claude/workflows/cycle-plan.js` as committed in `3ebf38c` (316 lines), read back with `grep -n`; the parts Plan of Work M3 requires and where they are:

    1-6      meta literal: name cycle-plan, description, whenToUse, phases Scope / Setup / Author
    25-38    args normalised to `goal` and `answers`: string, array (goal, answers), and object ({ goal, answers }) forms
    40-43    refusal of an empty goal (result { status: 'refused', reason: 'no goal given', where: 'arguments' })
    47-49    goalText: the goal, plus the operator's answers under their heading when present
    59-64    confine(kind, dir): the two lines every later prompt begins with (`checkout` or `worktree`)
    69-72    refuse(reason, where, extra): logs `cycle-plan: refused: <reason>`, returns { status: 'refused', reason, where, ...extra }
    75-77    noResult(label, where, extra): the `agent <label> returned no result` refusal
    85       phase('Scope')
    87-97    GUARD_SCHEMA (checkout, main, ok, detail, origin_main)
    99-113   stage 1 guard prompt: the `pwd -P` first variant; checks 1 to 7 on lines 105-111 (checkout via show-toplevel, main via git-common-dir/.., origin, gh-user, fetch, origin-main, tools)
    115-120  guard agent (effort low, label guard); null and `ok` false refuse; `cycle-plan: guard ok, checkout <c>, main <m>, origin/main <sha7>`
    127-140  SCOPE_SCHEMA: the brief exactly as Plan of Work gives it (outcome, slug, files, debt_paid, debt_tripped, specs_altered, out_of_scope, questions)
    142-161  stage 2 scope prompt: read-only, the goal text, the reading list (AGENTS.md, GOALS.md, docs/DEBT.md, docs/capabilities/index.md, gh issue list/view, the code the goal touches), the eight fields on lines 154-161 with the slug and questions rules
    163-164  scope agent (label scope, default effort and model); null refuses
    166-170  questions: log line telling the operator to rerun with the answers appended, one log line per question, result { status: 'questions', questions, brief }
    172-178  slug validated against ^[a-z0-9-]{1,40}$ (refusal carries the brief); branch plan/<slug>; planPath plans/active/<slug>.md; `cycle-plan: scope ok, slug <slug>: ...` counts
    185      phase('Setup')
    187-198  SETUP_SCHEMA (worktree, branch, venv_seconds, import_path, ok, detail)
    200      expectedWorktree = <main>/.claude/worktrees/<slug>
    202-213  stage 3 setup prompt: confinement to <main> and the new worktree; steps 1 to 4 on lines 208-211 (git worktree add -b plan/<slug> .claude/worktrees/<slug> origin/main; pwd -P and abbrev-ref; venv + pip install -e ".[dev]" timed with date +%s under a 600000 ms timeout; import docket path inside the worktree); detail names what exists on a failure
    215-222  setup agent (effort low, label setup); cleanup string; null and `ok` false refuse with branch, worktree, cleanup; `cycle-plan: setup ok, worktree <w> on <branch>, venv built in <n>s`
    229      phase('Author')
    231-241  AUTHOR_SCHEMA (plan_path, milestone_count, first_milestone, first_acceptance, left_out)
    243-262  stage 4 plan-author prompt: common lines for the new worktree, skills/plan-author/SKILL.md and its reading list, the goal text, the brief as JSON, folding into Purpose and Context (256), the judge's section rules (258), write plans/active/<slug>.md, commit alone as `plan: <slug>, authored`, never bypass hooks, do not start the work
    264-266  plan-author agent (label plan-author, stallMs 1800000, default effort and model); null refuses with branch, worktree, cleanup; `cycle-plan: plan authored at <path>, <n> milestone(s); first: ...`
    274-282  CHECK_SCHEMA (ok, detail, open_count)
    284-293  stage 5 check prompt: from the launching checkout; tools/judge-milestone snapshot <worktree>/plans/active/<slug>.md exit 0 with OPEN and no DONE (289); git -C <worktree> status --porcelain empty (290); git -C <worktree> log --oneline origin/main..HEAD exactly one line (291)
    295-301  check agent (effort low, label check); null and `ok` false refuse with branch, worktree, plan_path, cleanup and a log line saying the plan is committed but to be fixed in the worktree; `cycle-plan: check ok, <n> open milestone(s), clean tree, one commit over origin/main`
    303-316  result { status: 'planned', branch, worktree, plan_path, milestone_count, first_milestone, first_acceptance, left_out, venv_seconds, next } with the `next` sentence from Plan of Work

M3 session, self-check with the judge after commits `3ebf38c` and `c621267`, using a snapshot taken from the plan as committed at the session's start sha (`git show 4a731fd:plans/active/factory-workflows.md`), observed:

    tools/judge-milestone snapshot <scratch>/fw-m3-start-plan.md > <scratch>/fw-m3-start.snapshot; echo "snapshot exit=$?"
    snapshot exit=0
    tools/judge-milestone judge plans/active/factory-workflows.md <scratch>/fw-m3-start.snapshot 4a731fd; echo "judge exit=$?"
    judge: advanced "(2026-10-11 21:41Z) M3: `.claude/workflows/cycle-plan.js` turns a stated..."
    judge exit=0

This is the session's own check; `cycle-run`'s judge agent runs the same command from its own snapshot after this session returns, and the commit carrying this note lands after the check, so that judge sees three commits since `4a731fd`.

### M4 session transcript (2026-10-11)

Starting `./tools/verify; echo "exit=$?"` on `c84c8a1`, summary lines only:

    verify: test-db ... ok (0s) postgresql://docket@localhost:5432/docket_test_7da4fd23
    verify: unit+web+services ... ok (59s)
    verify: integration ... ok (71s)
    verify: judge-fixtures ... ok (4s)
    verify: workflows ... ok (0s)
    verify: all 4 checks passed in 134s.
    exit=0

Acceptance greps after the edits:

    AGENTS lines:       48
    D6 rows: 0
    D43 rows: 1
    index 'planned' mentions: 0
    judge card: no 'next plan'/'planned'

Path walk: for each of the six files, backticked tokens were extracted with `grep -o '`[^`]*`'`, reduced to their first word, stripped of a trailing `:NN`, kept when they contain `/` or end in a file extension, dropped when absolute, a URL, or holding `<`, `$`, `*`, `{`, and tested with `test -e`. Result: `132` found; `26` reported missing and resolved by hand as Concrete Steps describes (every one that is a path exists at its full path; the rest are refs, repository slugs, an assignment, and two files outside the tree). The hand resolution command and its output:

    ok      tools/fixtures/judge/run
    ok      docs/capabilities/index.md
    ok      docs/specs/operations.md
    ok      src/docket/web/admin.py ... src/docket/web/source_security.py (six files)
    ok      src/docket/ai/badges_policy.py, src/docket/ai/batch_ingest.py
    ok      src/docket/ai/transcripts/compare.py, src/docket/ai/transcripts/events.py
    ok      src/docket/analysis/minutes_parser.py, src/docket/services/, src/docket/ai/
    ok      .claude/workflows/cycle-plan.js, .claude/workflows/cycle-run.js
    MISSING .claude/worktrees/factory-workflows   (relative to the main checkout; `pwd -P` printed /Users/darrellnance/docket-pub/.claude/worktrees/factory-workflows)
    ok      /Users/darrellnance/.claude-personal/projects
    origin/main: git ref resolves

Post-change `./tools/verify; echo "exit=$?"` on the tree committed as `fb472fa`, summary lines only:

    verify: test-db ... ok (1s) postgresql://docket@localhost:5432/docket_test_7da4fd23
    verify: unit+web+services ... ok (62s)
    verify: integration ... ok (88s)
    verify: judge-fixtures ... ok (4s)
    verify: workflows ... ok (0s)
    verify: all 4 checks passed in 155s.
    exit=0

## Interfaces and Dependencies

`.claude/workflows/cycle-run.js`: plain JavaScript for the Workflow runtime, no TypeScript syntax, no `import`, no clock. Arguments: a plan path string, or `{ plan, limit }`. Result: an object with `status` one of `refused`, `halt`, `advanced`, `complete`, and the fields named in Plan of Work. Depends on `tools/judge-milestone`, `./tools/verify`, `git`, `gh`, and `skills/plan-execute/SKILL.md`, `skills/retro/SKILL.md`, `skills/doc-garden/SKILL.md` as read by its agents.

`.claude/workflows/cycle-plan.js`: same runtime. Arguments: a goal string, or `{ goal, answers }`. Result: `status` one of `refused`, `questions`, `planned`, with the fields named in Plan of Work. Depends on `git`, `gh`, `python3.10`, `pip`, and `skills/plan-author/SKILL.md` as read by its agents.

`tools/check-workflows`: POSIX sh, no arguments, requires `node` on `PATH`. Exit 0 and `workflows: N of N ok` when every `.claude/workflows/*.js` passes; exit 1 and the offending file and reason otherwise; exit 1 when there are no scripts.

`tools/verify`: gains the line `check workflows tools/check-workflows` after the `judge-fixtures` check; its summary then reads `all 4 checks passed`.

`tools/judge-milestone`: unchanged. Called as `snapshot <plan>` and `judge <plan> <snapshot-file> <start-sha>`.

Documents edited in M4: `AGENTS.md`, `docs/specs/operations.md`, `docs/capabilities/judge-milestone.md`, `docs/capabilities/index.md`, `GOALS.md`, `docs/DEBT.md`.

## Revision notes

- 2026-10-11, authored by hand in the operator's session following `skills/plan-author/SKILL.md`, from sections 2, 3, 5, 7, and 8 of `docs/superpowers/specs/2026-10-10-factory-cycle-design.md`. Four milestones. Deliberately left out: any change to `tools/judge-milestone`; a capability card for the workflow shape check; closing-stage idempotence (recorded as `D43` in M4); deletion of the stale `origin/worktree-*` branches (`D31`, an operator action); any fix for issue #110 (planned by the `cycle-plan` trial, not executed); climbing the maturity ladder.
