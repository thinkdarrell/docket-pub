# 0117 — The worker's schedule is stated in `scheduler.py` and printed by `--list`

## Decision

`src/docket/worker/scheduler.py` is the one place that states when a worker job runs, and `python -m docket.worker.scheduler --list` prints every job with the task it runs and its trigger, from the code. Prose names jobs and tasks, says what order they run in and why, and points at that command; it states no count of tasks or jobs and no worker clock time. A plan that adds a job changes `scheduler.py` and, where a document lists tasks by name, that list, and writes no time anywhere else.

## Rationale

The schedule used to be written out, with task counts and clock times, in more than a dozen places beside the code: the README, the cron-worker runbook, several specs and runbooks, and docstrings in `src/docket/worker/tasks.py` and two service modules. Debt row `D69` asked for the copies to be replaced, and its trigger fired four times, each time a plan added a task and raised the counts instead; row `D138` recorded a README paragraph that counted fifteen tasks when there were nineteen. `docs/PRINCIPLES.md`, One owner per fact, names "a cron schedule in prose vs. `scheduler.py`" as the violation. Plan `recordings-seen-the-day-posted` would have added three more clock times to every copy; it paid both rows.

A pointer needs something a person can run. Before the plan the only command that listed the worker's tasks was the error message of `--run-once not_a_task`, which gives names without times. `--list` builds the scheduler without starting it, opens no database connection and pings nothing, so it is safe in a checkout and inside the worker container. A test, `test_no_docstring_outside_the_scheduler_states_a_worker_clock_time` in `tests/unit/test_worker_scheduler.py`, fails when a docstring of the three modules states a time again; nothing mechanical holds the Markdown.

Left alone on purpose, and not violations of this rule: the comments inside `scheduler.py` itself (the file owns the times); the tests that pin the times; `docs/runbooks/v3-cutover.md` (a dated procedure carried out in 2026-05); the line of `docs/runbooks/analytics.md` that gives the schedule the operator types into Healthchecks for one check; `docs/runbooks/coming-up-reading-birmingham.md` (a neighborhood meeting's time, not the worker's); `docs/decisions/`, `docs/superpowers/`, `plans/completed/` and `docs/DEBT.md`, which are history or dated readings. The time of the Legion's scheduled transcriber run is not the worker's; it is stated once, in `transcriber/README.md`, "The scheduled run". The cron expressions the operator gives Healthchecks are derived from what `--list` prints (`docs/runbooks/cron-worker.md`).

## Date

2026-11-19, the authoring session of plan `recordings-seen-the-day-posted` (Claude); built by that plan's M2 and M3 and graduated by its M4 session the same day.

## Status

accepted
