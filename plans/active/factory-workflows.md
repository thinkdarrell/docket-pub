# Give the factory its two commands: `cycle-run` carries a plan to a pull request and `cycle-plan` turns a stated goal into a plan

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

Today the operator of this repository drives every plan by hand: start a fresh session for a milestone, run `tools/judge-milestone` before and after it, run `./tools/verify`, read the result, start the next session, and at the end convene reviewers, run the retro and gardening procedures, push, and open the pull request. The previous plan (`plans/completed/factory-tools.md`) built the tools those steps use; the orchestration itself still lives in the operator's head and in a conversation that is gone when the window closes. After this plan, the operator types two commands in Claude Code. `/cycle-plan <goal>` turns a goal they state into a committed plan on its own branch, worktree, and Python environment, or stops and asks the questions only they can answer. `/cycle-run plans/active/<slug>.md`, typed in a session started in that worktree, executes the plan milestone by milestone with a fresh agent per milestone, judges each one from git with `tools/judge-milestone`, verifies with `./tools/verify`, halts on the first defect with a message that says where to resume, and when the last milestone lands runs a three-lens review panel, writes the findings into the plan, runs the retro and gardening procedures, pushes the branch, and opens the pull request. You can see it working because this plan's own milestones two to four are executed by the first version of `cycle-run`, and the pull request that carries this plan is opened by it.

## Progress

- [x] (2026-10-11 21:04Z) M1: `.claude/workflows/cycle-run.js` runs preflight and the milestone loop with a limit and halts on the judge; `tools/check-workflows` guards every saved workflow inside `./tools/verify`.
- [x] (2026-10-11 21:20Z) M2: `cycle-run` closes a finished plan: review panel, review record, retro, doc-garden, final verify, push, pull request.
- [ ] M3: `.claude/workflows/cycle-plan.js` turns a stated goal into a committed plan on its own branch, worktree, and venv, or stops with the operator's questions.
- [ ] M4: `AGENTS.md`, `docs/specs/operations.md`, the judge card and register, `GOALS.md`, and `docs/DEBT.md` say what the factory now does.

## Surprises & Discoveries

- Observation (authoring, 2026-10-11): a subagent launched with the Agent tool does not have the Workflow tool. A probe agent reported `workflow_tool: not available (not in tool list; ToolSearch select:Workflow returned "No matching deferred tools found")`. So a milestone session of this plan can write a workflow script but cannot run one; the live runs belong to the operator's interactive session. This shapes every milestone's acceptance (Context and Orientation, "Who runs what").
  Evidence: the probe's three-line report, quoted above.
- Observation (authoring, 2026-10-11): agents started by a workflow, and plain subagents, inherit the current working directory of the session that launched them, and that directory follows the session's last shell `cd`. A one-agent probe workflow launched while the session's shell sat in `.claude/worktrees/factory-tools` returned `{"pwd":"/Users/darrellnance/docket-pub/.claude/worktrees/factory-tools","toplevel":"/Users/darrellnance/docket-pub/.claude/worktrees/factory-tools","branch":"plan/factory-tools","dotclaude":"skills"}`, and the run's script file was stored under a project directory named after that same path. The design's isolation argument (start the session in the worktree) holds, and the backstop `cd` line in every prompt stays.
  Evidence: the probe result, quoted above.
- Observation (authoring, 2026-10-11): `node --check` refuses a workflow script as written, because the scripts end with a top-level `return` and `node --check` parses a file as a module: `SyntaxError: Illegal return statement`. The shape check in M1 therefore wraps the body in an async function before parsing it (Plan of Work, M1).
  Evidence: `printf 'export const meta = { name: "x", description: "y" }\nconst r = await agent("hi")\nreturn r\n' > /tmp/x.js; node --check /tmp/x.js` printed the error above and exited 1.
- Observation (authoring, 2026-10-11): building this worktree's venv took 18 seconds, not the two to four minutes `GOALS.md` lists as a known unknown: `python3.10 -m venv venv && venv/bin/pip install -q -e ".[dev]"` in `.claude/worktrees/factory-workflows` printed `venv exit=0 seconds=18`. The pip cache was warm from the previous worktree's build; a cold-cache time is not measured here. M4 writes the measured number into `GOALS.md`.
  Evidence: the timing line, quoted above.

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

## Outcomes & Retrospective

Nothing has been executed. This section is filled as milestones land, one entry per milestone, and closed by the retro that `cycle-run`'s closing sequence runs after M4.

M1 (2026-10-11, hand-launched milestone session; commits `094a50d` and the commit carrying this entry, on top of `c309ace`). Landed: `.claude/workflows/cycle-run.js` (313 lines: argument handling, the ten-check preflight, the snapshot / milestone / judge loop with `limit` and a hard cap of 20, the halt shape) and `tools/check-workflows` (POSIX sh plus `awk` and `node --check`), wired into `./tools/verify` as the fourth check. Static acceptance met and observed: `tools/check-workflows` printed `workflows: 1 of 1 ok` with exit 0 on the committed tree; exit 1 naming the file on the renamed meta (`meta.name "cycle-runn" does not match file cycle-run.js`) and on the appended `Date.now()`; `./tools/verify` printed `verify: workflows ... ok (0s)` as its fourth check and `verify: all 4 checks passed in 139s.` with exit 0; the script's contents are listed by line number in Artifacts and Notes. Carve-outs: none against the static half. Not observed by this session, by design (Decision Log, second entry): the live half, which is the run of this script that executes M2; in particular no agent prompt, schema, `stallMs`, or `isoFromEpoch` has been exercised by the Workflow runtime, and the first live run is where a runtime-shape mistake would show. The starting-state `./tools/verify` took 160 s and the post-change run 139 s; both within the 180 s budget `AGENTS.md` states.

M2 (2026-10-11, milestone session launched by `cycle-run` with `limit` 1; commits `a03e5e8` and the commit carrying this entry, on top of `f0f7b6a`). Landed: the closing sequence in `.claude/workflows/cycle-run.js` (lines 311 to 605: diffstat, three-lens review panel in `parallel()`, review record committed into the plan's Decision Log, retro, doc-garden, final verify, publish, and the `complete` result with `review` and `pr_url`), replacing M1's three placeholder lines. Static acceptance met and observed: `tools/check-workflows` printed `workflows: 1 of 1 ok` with exit 0; `./tools/verify` printed `verify: all 4 checks passed in 157s.` with exit 0; the seven stages with their lens paragraphs, schemas, and record shape are listed by line number in Artifacts and Notes. Beyond the stated acceptance, a stub runtime exercised the closing path through the complete result and three halts (Decision Log; Artifacts and Notes). Carve-outs: none against the static half. Not observed by this session, by design: the live half, which is the closing run after M4; in particular no closing prompt or schema has met the Workflow runtime, the record agent's Decision Log edit has not been parsed by `tools/judge-milestone snapshot` on a real plan, and the retro and publish agents have not run. The starting `./tools/verify` took 156 s and the post-change run is in the transcript above; both within the 180 s budget.

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

M4. Make the edits. Run `wc -l AGENTS.md` (expected: at most 100). Walk the paths: for every backticked repository-relative path in the five edited files, `ls` it. Run `./tools/verify`. Expected: `all 4 checks passed`.

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

## Interfaces and Dependencies

`.claude/workflows/cycle-run.js`: plain JavaScript for the Workflow runtime, no TypeScript syntax, no `import`, no clock. Arguments: a plan path string, or `{ plan, limit }`. Result: an object with `status` one of `refused`, `halt`, `advanced`, `complete`, and the fields named in Plan of Work. Depends on `tools/judge-milestone`, `./tools/verify`, `git`, `gh`, and `skills/plan-execute/SKILL.md`, `skills/retro/SKILL.md`, `skills/doc-garden/SKILL.md` as read by its agents.

`.claude/workflows/cycle-plan.js`: same runtime. Arguments: a goal string, or `{ goal, answers }`. Result: `status` one of `refused`, `questions`, `planned`, with the fields named in Plan of Work. Depends on `git`, `gh`, `python3.10`, `pip`, and `skills/plan-author/SKILL.md` as read by its agents.

`tools/check-workflows`: POSIX sh, no arguments, requires `node` on `PATH`. Exit 0 and `workflows: N of N ok` when every `.claude/workflows/*.js` passes; exit 1 and the offending file and reason otherwise; exit 1 when there are no scripts.

`tools/verify`: gains the line `check workflows tools/check-workflows` after the `judge-fixtures` check; its summary then reads `all 4 checks passed`.

`tools/judge-milestone`: unchanged. Called as `snapshot <plan>` and `judge <plan> <snapshot-file> <start-sha>`.

Documents edited in M4: `AGENTS.md`, `docs/specs/operations.md`, `docs/capabilities/judge-milestone.md`, `docs/capabilities/index.md`, `GOALS.md`, `docs/DEBT.md`.

## Revision notes

- 2026-10-11, authored by hand in the operator's session following `skills/plan-author/SKILL.md`, from sections 2, 3, 5, 7, and 8 of `docs/superpowers/specs/2026-10-10-factory-cycle-design.md`. Four milestones. Deliberately left out: any change to `tools/judge-milestone`; a capability card for the workflow shape check; closing-stage idempotence (recorded as `D43` in M4); deletion of the stale `origin/worktree-*` branches (`D31`, an operator action); any fix for issue #110 (planned by the `cycle-plan` trial, not executed); climbing the maturity ladder.
