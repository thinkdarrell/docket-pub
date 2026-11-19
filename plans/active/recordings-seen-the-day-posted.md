# Give the worker an afternoon pass so a Birmingham recording is seen the day it is posted

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

docket.pub publishes a machine transcript of each Birmingham council meeting. The transcript is made on the operator's desktop machine (the Legion) by a program called the transcriber, which can only transcribe a meeting whose row in the database already carries the address of its recording (`meetings.video_url`). That address is written by the worker, the scheduled process on Railway, when it reads Birmingham's Granicus archive. Today the worker reads the archive once a day, early in the morning. A meeting held on a Tuesday morning has its recording posted later that day, the worker first sees it on Wednesday morning, and the transcript is public on Wednesday evening at the earliest.

Since 2026-11-19 the Legion runs the transcriber on its own every day at 17:30 Central. After this plan the worker makes a second, shorter pass in the afternoon, before that run: at 16:30 it reads Birmingham's Granicus archive again, at 16:45 it matches the council's YouTube channel again, and at 16:55 it runs the rule that hides clips that are not meetings again, all in America/Chicago time. A recording the city posts between the morning pass and 16:30 then has its meeting row and its `video_url` before 17:30, the Legion's run claims it, and the transcript page is public that evening instead of the next day. The morning pass does not change, and the other three cities are still visited once a day.

A reader can see the change three ways. The first is a check that fails today and passes afterwards: `tests/unit/test_worker_scheduler.py` asserts that the scheduler registers the three afternoon jobs at those times beside the unchanged morning jobs, and `./tools/verify` passes with it. The second is a test that the 16:30 job ingests Birmingham and no other city. The third is the operator's, after a human deploys the worker, and no session of this plan can make it: the worker's startup log lists the afternoon jobs with their next run times, and on a day Birmingham posts a recording between the passes the meeting row carries its `video_url` before 17:30 and its transcript is public that evening.

The plan also pays a long-overdue debt the change would otherwise deepen. The worker's schedule is written out in prose, with task counts and clock times, in more than a dozen places beside the code that owns it, and each plan that added a task has patched the copies. This plan adds a command that prints the schedule from the code, `python -m docket.worker.scheduler --list`, and replaces the copies with pointers to it.

## Progress

As authored on 2026-11-19, nothing has been executed.

- [ ] M1: the worker registers an afternoon pass, `ingest_afternoon` at 16:30 for the cities `AFTERNOON_INGEST_SLUGS` names (Birmingham), `youtube_ingest_afternoon` at 16:45 and `non_meetings_afternoon` at 16:55 America/Chicago, beside the unchanged morning jobs, with the scheduler, task, health, and service tests passing
- [ ] M2: `python -m docket.worker.scheduler --list` prints every job with the task it runs and its trigger in time-of-day order, and the docstrings of `src/docket/worker/tasks.py`, `src/docket/services/non_meetings.py` and `src/docket/services/city_calendar.py` state no clock time
- [ ] M3: `README.md`, `docs/runbooks/cron-worker.md` and the other runbooks and specs that stated a worker task count or clock time point at `scheduler.py` and `--list` in its place, the runbook lists the afternoon jobs and the `docket-ingest-afternoon` check, and debt rows `D69` and `D138` are deleted
- [ ] M4: the specs, the transcriber README, the transcripts runbook, and the Birmingham tour describe the afternoon pass and the Legion's scheduled `docket-transcriber` run, the durable decisions are records under `docs/decisions/`, and `docs/DEBT.md` carries the CivicClerk delay row, the operator's post-merge steps, and the written re-deferrals

## Surprises & Discoveries

As authored on 2026-11-19, nothing has been executed; the entries below are what the authoring session observed in the worktree before any edit.

- Observation: `./tools/verify` takes 295 seconds on this machine before any change, five seconds inside the 300-second default timeout a factory agent's command runs under.
  Evidence: run at authoring on `a484523` (the branch's base): `verify: unit+web+services ... ok (171s)`, `verify: integration ... ok (112s)`, `verify: transcriber ... ok (11s)`, `verify: all 6 checks passed in 295s.`; the tiers printed `3480 passed, 5 skipped, 4 xfailed`, `1049 passed`, and `147 passed`. Debt row `D93` in `docs/DEBT.md` records the same level for the two plans before this one.

- Observation: the worktree has no `.env` file and `./tools/verify` passed all six checks under the default database URL (`postgresql://docket:docket_dev@localhost:5432/...`).
  Evidence: `ls -a` at the worktree root printed `.env.example` and no `.env`; the verify line `verify: test-db ... ok (0s) postgresql://docket:docket_dev@localhost:5432/docket_test_7eed746c`. Debt row `D57` says every new worktree on this machine needs a hand-written `.env` before verify can pass; that was not so on 2026-11-19.

- Observation: editing `README.md` fires the trigger of debt row `D149`, and editing the docstrings of `src/docket/services/non_meetings.py` and `src/docket/services/city_calendar.py` fires the triggers of `D121` and `D119`, none of which the scope brief named.
  Evidence: `D149`'s trigger reads "or the next change to `README.md` (`D138`)"; `D121`'s reads "The next touch of `non_meetings.py`, the admin template, or either calendar module"; `D119`'s reads "the next plan that touches the calendar rung, the hiding rule, or the calendar readers". The Decision Log says what the plan does with each.

- Observation (M1): the comment above `WORKER_TIMEZONE` in `src/docket/config.py` says "Every task time in docs/runbooks/cron-worker.md is in this zone", and M3 removes the runbook's column of times, so that sentence goes stale when M3 lands. The plan's M3 does not name `config.py`.
  Evidence: `src/docket/config.py` lines 16 and 17, read while adding `AFTERNOON_INGEST_SLUGS` below them. M1 left the comment alone, because it is true until M3; the M3 session should reword it to name `--list`.

- Observation (M1): `src/docket/worker/scheduler.py` still holds two citations of a plan by its `plans/completed/` path and clock times in the comments of other jobs. M1 changed neither: the file owns the times (Decision Log, the `D69` entry), and the citations are older plans' and outside this milestone.
  Evidence: `grep -n "plans/completed" src/docket/worker/scheduler.py` printed two lines when the file was read for M1.

## Decision Log

- Decision: The afternoon Birmingham-only ingest is a new worker task, `ingest_afternoon`, with its own entry in `TASKS` and its own Healthchecks variable; the afternoon runs of `youtube_ingest` and `non_meetings` are second scheduler jobs (`youtube_ingest_afternoon`, `non_meetings_afternoon`) that call the existing task functions and so ping the existing checks.
  Rationale: `_do_ingest_all` visits every active city and the operator's answer (3) keeps the other cities at one visit a day, so the ingest needs a body of its own; a `TASKS` key also gives the operator `--run-once ingest_afternoon`. `_do_youtube_ingest` and `_do_non_meetings` already read only the cities whose metadata names a YouTube channel or a complete calendar, which is Birmingham alone, so a second trigger on the same function is the whole change and a second task key would duplicate a body for nothing.
  Date/Author: 2026-11-19, the authoring session (Claude).

- Decision: Healthchecks. `ingest_afternoon` gets a new check, `docket-ingest-afternoon`, through the new variable `HEALTHCHECK_INGEST_AFTERNOON_UUID`. The checks `docket-youtube-ingest` and `docket-non-meetings` each hear from two jobs and the operator changes each one's schedule to a cron expression naming both hours.
  Rationale: `GOALS.md` requires every scheduled task to ping and a missed ping to page. A check's schedule is one cron expression. The two YouTube runs share a minute (45) and the two non-meetings runs share a minute (55), so one expression with two hours covers both and a missed afternoon run pages. The ingest runs are at minute 0 and minute 30, which no single expression covers without also naming two times nothing runs, so the afternoon ingest pinging `docket-ingest` could be missed silently; it gets its own check. Creating a check and setting a Railway variable are the operator's (the pattern of debt rows `D18`, `D48`, `D64`), so until then the worker's startup WARNING names `ingest_afternoon` as unmonitored, and a debt row written by M4 lists the steps.
  Date/Author: 2026-11-19, the authoring session (Claude).

- Decision: Which cities the afternoon ingest visits is a setting, `AFTERNOON_INGEST_SLUGS` in `src/docket/config.py`, a comma-separated list whose default is `birmingham`; the task ingests each named city that is also active.
  Rationale: The alternatives were a city name written into `src/docket/worker/tasks.py` (the worker holds no business logic, and a setting belongs in `config.py`), a new key in `municipalities.metadata` (a migration and a production statement for what is a scheduling choice), and reusing the `youtube_channel_id` key (it would tie the ingest to an unrelated fact). A setting also gives the operator an off switch without a code change: an empty value makes the task do nothing, which matters because debt row `D102` names "Granicus slows or refuses the worker" as a trigger and this plan doubles Birmingham's requests.
  Date/Author: 2026-11-19, the authoring session (Claude).

- Decision: The list of active cities moves out of `_do_ingest_all` into a service function, `active_slugs()` in `src/docket/services/ingest.py`, which both ingest tasks call. This pays the `_do_ingest_all` part of debt row `D65`; the other six task bodies that row names are re-deferred in writing by M4.
  Rationale: The afternoon task must honour `municipalities.active`, or deactivating a city would no longer stop the worker from scraping it. Reading that column needs a statement, and `ARCHITECTURE.md` says services own every transaction; `D65`'s trigger asks the next plan touching each task to move its SQL into a service. The move is three lines and two existing tests. The other six bodies are unrelated to the outcome.
  Date/Author: 2026-11-19, the authoring session (Claude).

- Decision: No afternoon or evening run of `transcript_pipeline` is added. A transcript uploaded by the Legion's evening run is public on arrival and shows "Speaker N" labels until the worker's next daily `transcript_pipeline` tick resolves its speakers.
  Rationale: The decision is the operator's (answer 2 of 2026-11-19). The reasons recorded here are the author's reading of the code and were not stated by the operator. The Legion's run had not fired once when the plan was written, so its finishing time is unknown and is bounded only by its three-hour cap (20:30); there is no time at which an evening tick is known to follow the upload. A tick advances each transcript by one stage, so an evening tick would buy speaker names a few hours early and nothing else, would spend from the daily AI budget in a second window, and would add a second window in which the runbook forbids starting a re-transcription (`docs/runbooks/transcripts.md`, "Re-transcribing one meeting").
  Date/Author: 2026-11-19, the operator's answer; recorded by the authoring session (Claude).

- Decision: Only three tasks get an afternoon run. `city_calendar`, `video_ocr`, `committee_documents`, `ai_items`, `vote_matching`, `briefing_facts` and the rest stay once a day.
  Rationale: The goal names three tasks. A same-day clip's OCR votes, AI text and committee documents still arrive the next morning. No second calendar read is needed: `non_meetings` refuses to hide anything unless the calendar's sitemap read is at most 36 hours old (`CALENDAR_FRESH_HOURS` in `src/docket/services/non_meetings.py`), and the morning read is about eleven and a half hours old at the afternoon run.
  Date/Author: 2026-11-19, the authoring session (Claude).

- Decision: Debt rows `D69` and `D138` are paid, not re-deferred: M2 adds `--list` to the scheduler and M2 and M3 replace every prose task count and worker clock time with a pointer to `src/docket/worker/scheduler.py` and that command. Left alone on purpose: the comments inside `scheduler.py` itself (the file owns the times), the tests (they pin the times), `docs/runbooks/v3-cutover.md` (a dated procedure that was carried out in 2026-05), `docs/runbooks/analytics.md` line 130 (the schedule the operator types into Healthchecks for one check), `docs/runbooks/coming-up-reading-birmingham.md` (a neighborhood meeting's time, not the worker's), `docs/decisions/`, `docs/superpowers/`, `plans/completed/`, and `docs/DEBT.md`.
  Rationale: `D69`'s trigger has fired four times, each time a plan added a task and raised the counts instead of replacing them. This plan would add three more clock times to every copy. A pointer needs something to point at that a person can run, and the only existing one, the error message of `--run-once not_a_task`, lists task names without times; `--list` prints the job, the task and the trigger from the code. `docs/PRINCIPLES.md`, One owner per fact, names "a cron schedule in prose vs. `scheduler.py`" as the violation.
  Date/Author: 2026-11-19, the authoring session (Claude).

- Decision: The facts about the Legion's scheduled run (the task's name, its 17:30 trigger, its settings, the script it runs, the log path) are stated once, in `transcriber/README.md` under a new heading "The scheduled run"; every other document points there. The afternoon jobs' comments in `scheduler.py` say they run before that scheduled run and name the README section, without the time.
  Rationale: The script and the Task Scheduler task live on the Legion, outside the repository, so the repository needs one written copy, and one only (`docs/PRINCIPLES.md`, One owner per fact). The transcriber's README already holds the Legion's operating notes and the stale "At log on" paragraph this replaces.
  Date/Author: 2026-11-19, the authoring session (Claude).

- Decision: The two 0.5-second CivicClerk delays (Vestavia Hills and Mobile) are recorded as a new debt row by M4 and not fixed.
  Rationale: The operator's answer (4). They are below the one second `GOALS.md` requires, were true before this plan, and are untouched by it: the afternoon pass visits neither city.
  Date/Author: 2026-11-19, the operator's answer; recorded by the authoring session (Claude).

- Decision: Debt rows `D34`, `D46`, the rest of `D65`, `D102`, `D119` and `D121` are re-deferred in writing by M4, and the README half of `D149` is paid by M3.
  Rationale: Each row's trigger fires on a file this plan edits. `D34`: the plan's one new setting goes through `config.py`, and the two remaining direct reads (`ANALYTICS_DATABASE_URL` in `tasks.py`, pinned by a test of the `KeyError`; the per-task lookup in `health.py`) are unrelated to the outcome. `D46`: the calibration queries are unrelated. `D102`: the needless player-page fetch now happens twice a day for Birmingham; the fix is a change to ingest's precheck with its own tests, and the off switch above bounds the cost. `D119` and `D121`: the plan changes one docstring sentence in each of `non_meetings.py` and `city_calendar.py` and no behaviour. `D149`: its trigger is the next change to `README.md`, and the stale roadmap bullet is one line that decision `0091` and debt row `D10` already answer. Writing each re-deferral down keeps the triggers from going overdue silently, which the register shows has happened four times to `D34` and twice to `D46`.
  Date/Author: 2026-11-19, the authoring session (Claude).

- Decision: The work is cut into four milestones: the code of the afternoon pass; `--list` and the docstrings; the prose that stated the schedule; the closing documents.
  Rationale: Each leaves the repository coherent and has acceptance a session can run. M1 alone delivers the outcome. M2 comes before M3 because M3's pointers name a command that must exist. No milestone moves the plan to `plans/completed/` or writes the closing retrospective; the retro stage of `cycle-run` does both.
  Date/Author: 2026-11-19, the authoring session (Claude).

- Decision: No decision number or debt id is fixed in this plan. The session that needs one takes the lowest number above every one spent on `origin/main` and on any open pull request at that moment.
  Rationale: Debt row `D70`: numbers are allocated by hand and a figure written at authoring goes stale while the plan waits. Context and Orientation gives the procedure.
  Date/Author: 2026-11-19, the authoring session (Claude).

- Decision (M1): Two tests beyond the ones the plan names were added to `tests/unit/test_worker_tasks.py`: `test_ingest_afternoon_visits_the_configured_cities_in_the_configured_order` and `test_config_afternoon_ingest_slugs_defaults_to_birmingham`. The second reads the setting in a fresh interpreter (a subprocess), with the variable unset, empty, and set to two cities.
  Rationale: The plan states two rules no named test could tell from their absence: that the cities are visited "in the configured order", and that the default is `birmingham` while an empty value turns the task off. `config.py` reads the variable once, at import, so only a new interpreter can show the default; reloading `docket.config` inside the test process would replace the module object other tests have patched. The removal check in Artifacts and Notes shows both tests failing when their rule is taken out.
  Date/Author: 2026-11-19, the M1 session (Claude).

- Decision (M1): The tests of `config._csv` live in `tests/unit/test_worker_tasks.py`, under their own heading.
  Rationale: The plan says "in the same file or the existing config test file if one exists"; `ls tests/unit | grep -i config` printed nothing.
  Date/Author: 2026-11-19, the M1 session (Claude).

- Decision (M1): `test_build_scheduler_afternoon_pass` and `test_build_scheduler_morning_pass_is_unchanged` are each one parametrized test of three cases, under the names the plan gives.
  Rationale: The file's existing `test_build_scheduler_job_hours` is written that way, and a failing case then names its job in the test id. Each case asserts everything the plan lists for its job.
  Date/Author: 2026-11-19, the M1 session (Claude).

- Decision (M1): The afternoon tests assert more of the log than the plan asks: the exact WARNING text for the inactive city, the exact INFO text for the empty setting, that `log.exception` carries the exception, and the result line with six distinct counts (`errors=2` from a two-item list).
  Rationale: The plan fixes these strings, the M3 runbook will quote the result line to the operator, and a fixture with equal counts could not tell one count from another.
  Date/Author: 2026-11-19, the M1 session (Claude).

- Decision (M1): `active_slugs()` is placed immediately above `ingest_municipality` in `src/docket/services/ingest.py`, and its integration test seeds three cities (active, inactive, active) inserted in reverse slug order.
  Rationale: The plan asks for two cities and "sorted". With two rows inserted in slug order, a query without `ORDER BY` returns them sorted by accident; three rows inserted last-first make the removal of `ORDER BY slug` fail the test, which the removal check observed.
  Date/Author: 2026-11-19, the M1 session (Claude).

## Outcomes & Retrospective

As authored on 2026-11-19, nothing has been executed and there is no outcome to report.

## Context and Orientation

Work in the git worktree this plan lives in; every command below is run from its root with its own `venv/`. The branch is `plan/recordings-seen-the-day-posted`, cut from `origin/main` at `a484523`.

### The parts

The worker is the process `python -m docket.worker.scheduler` on the Railway service named `worker`. `src/docket/worker/scheduler.py` holds `build_scheduler(timezone)`, which registers jobs on an APScheduler `BlockingScheduler`; a job is a function, a `CronTrigger` (the time of day it fires, in America/Chicago), and an id. Every job is registered with `coalesce=True, max_instances=1`, meaning a missed firing is run once and a job never overlaps itself. Today there are nineteen jobs and each job's id is the name of the task it runs. `src/docket/worker/tasks.py` holds the tasks: for each, a body `_do_<name>` and a public function `task_<name>` that runs the body through `_safe_run(<name>, body)`, and the dictionary `TASKS` from name to public function. `_safe_run` pings Healthchecks.io (an outside service that alerts the operator when an expected ping does not arrive) at start, success, and failure, and never re-raises. `src/docket/worker/health.py` holds `TASK_UUID_ENV`, from task name to the environment variable that carries that task's check id; `ping()` does nothing when the variable is unset, and `unmonitored_tasks()` lists the tasks whose variable is unset so the worker can warn at startup. `--run-once <task>` runs one task in the foreground; an unknown name exits 1 and prints the known names.

The three tasks this plan schedules a second time:

`ingest_all` (morning, 06:00). Its body `_do_ingest_all` selects every active city (`SELECT slug FROM municipalities WHERE active = TRUE ORDER BY slug`, a statement in `tasks.py` that debt row `D65` says belongs in a service) and calls `ingest_municipality(slug)` from `src/docket/services/ingest.py` for each, logging and passing over a city that raises. `ingest_municipality` loads the city's adapter (the class that reads one vendor's site; Birmingham's is `GranicusAdapter` in `src/docket/adapters/granicus.py`), lists the city's meetings, inserts or updates their rows, reads agenda items, resolves meeting types, refreshes scheduled hearings, reads votes from minutes, and sweeps minutes adoptions. It returns an `IngestResult` (`meetings_found`, `meetings_inserted`, `meetings_updated`, `agenda_items_inserted`, `votes_inserted`, `errors`) and for an unknown slug returns one with an error and does not raise; it does not look at `municipalities.active`. For Birmingham, one run requests the Granicus publisher page once and then, with the adapter's delay after each request, a player page or document for each meeting that still lacks something. There are four active cities: Birmingham, Vestavia Hills, Mobile, Homewood.

`youtube_ingest` (morning, 06:45). Its body reads every active city whose metadata names `youtube_channel_id`, which is Birmingham alone, and calls `youtube_meetings.sync_city`, which attaches the council's YouTube recordings of the last 30 days to Granicus meeting rows and creates a row (`external_id` beginning `yt-`) for a recording Granicus never had once the video is three days old. A run costs about three units of a daily quota of 10,000. Run twice in a day with the same date, it creates no row the morning run did not; what the afternoon run adds is attaching a recording uploaded during the day to a clip the afternoon ingest has just listed.

`non_meetings` (morning, 06:55). Its body calls `non_meetings.hide_non_meetings()` in `src/docket/services/non_meetings.py`, which reads every active city whose metadata carries `calendar_complete_from`, again Birmingham alone, and hides short or speechless clips on days the city's stored calendar shows no meeting. It hides nothing dated within the last four days (`HIDE_AFTER_DAYS`) and nothing at all unless the calendar's sitemap read is at most 36 hours old. A second run in a day applies the same rules to the same rows; it cannot hide a clip of the same day.

The transcriber is the program under `transcriber/`. It runs in Docker on the Legion (the operator's Windows desktop), connects through a restricted database role, and claims work with the query in `transcriber/transcriber/db.py`: a Birmingham meeting with `video_url IS NOT NULL`, not hidden, on or after the run's `--since` date, newest first. Its uploads are public on arrival. The worker task `transcript_pipeline` (once a day) then resolves speakers, extracts events, and compares them with the minutes, one stage per transcript per run. An ordinary transcriber run begins by measuring where each attached YouTube recording sits on its Granicus clip's clock, so a recording the afternoon `youtube_ingest` attaches is measured the same evening.

### What the operator reported on 2026-11-19

None of this was observed by a session of the repository; it is the operator's report.

A Windows Task Scheduler task named `docket-transcriber` was registered on the Legion on 2026-11-19: daily at 17:30 Central, run only when the operator is logged on, catching up a missed start, not starting on battery. It runs `C:\docket-archive\run-transcriber.cmd`, a script that lives on the Legion and not in the repository, which runs

    docker compose -f C:\docket-pub\transcriber\docker-compose.yml run --rm -T transcriber --since 2025-10-28 --limit 10 --max-hours 3

and appends to `C:\docket-archive\logs\transcriber-scheduled.log`. When the plan was written the task had not fired once, so how long a run takes is unobserved; `--max-hours 3` puts its end at 20:30 at the latest. `transcriber/README.md` still describes only an optional task "At log on" with `--max-hours 4`.

A read-only query of production `municipalities` on 2026-11-19 printed these `adapter_config` delay values: `birmingham`, `GranicusAdapter`, no delay key (so the adapter's default of 1.0 second applies, `self.delay = config.get("delay", 1.0)`); `vestavia_hills`, `CivicClerkAdapter`, `delay=0.5`; `mobile`, `CivicClerkAdapter`, `delay=0.5`; `homewood`, `GenericCMSAdapter`, `delay=1.0`. `GOALS.md` requires polite delays of at least one second between requests. Birmingham, the only city the afternoon pass visits, meets it. The two 0.5-second values do not, were so before this plan, and are recorded as debt, not fixed.

### What is not known

When, on a meeting day, Birmingham posts a recording to Granicus, and so how often it lands before 16:30. How long Birmingham's ingest takes, and so whether it has finished when `youtube_ingest_afternoon` starts fifteen minutes later; the morning pass has the same forty-five minutes for four cities and no record in the repository says how much of it is used. Whether the Healthchecks checks `docket-youtube-ingest` and `docket-non-meetings` exist (`health.py` calls the first optional). When the Legion's scheduled run finishes. Each is an operator observation after the deploy and is listed under Validation and Acceptance.

### What the afternoon pass does not change

A meeting recorded only on YouTube still gets its row when its video is three days old, so it is not transcribed the day it is posted; the same-day outcome holds for Granicus clips and the recordings attached to them. A same-day clip's votes read from the video, its AI summaries, and its committee documents arrive the next morning as now. The city page's freshness chip reads the newest `meetings.created_at` (`query.most_recent_ingest_at`), so it moves in the afternoon only when the afternoon ingest creates a row, which is true to what happened. At 16:30 the half-hourly `process_batches` job also fires, as it does beside `ingest_all` at 06:00; both are light, both run as threads of the one worker process, and no second heavy process is started (`GOALS.md`, Constraints).

### Debt rows this plan accounts for

`docs/DEBT.md` is the register of deliberate deferrals; each row has an id `Dn`, and a closed row is deleted. Paid: `D69` (the schedule and task count in prose in several places) and `D138` (the README's worker paragraph counts fifteen tasks), both by M2 and M3; the `_do_ingest_all` part of `D65` by M1; the README half of `D149` by M3. Re-deferred in writing by M4, each with the reason in the Decision Log: `D34` (direct `os.environ` reads in `tasks.py` and `health.py`), `D46` (the calibration queries written twice), the other six task bodies of `D65`, `D102` (a needless Granicus player-page fetch per ingest run, now twice a day for Birmingham), `D119` and `D121` (rows about the hiding rule and the calendar readers, tripped by a docstring edit). `D93` (verify runs past its budget) is not changed by the plan; each session records its own verify time and M4 adds the readings to the row. `D70` governs numbering, below.

### Numbering decisions and debt rows

Decision records are files `docs/decisions/NNNN-<slug>.md` in the format `docs/decisions/DECISION_FORMAT.md` describes (the sections Decision, Rationale, Date, Status; read one recent record as a model). Debt rows are table rows in `docs/DEBT.md`. Neither number is fixed in this plan. The session that needs one runs `git fetch origin`, reads the highest decision number and the highest debt id on `origin/main` (`git ls-tree --name-only origin/main docs/decisions/ | tail -3` and `git show origin/main:docs/DEBT.md | grep -o '^| D[0-9]*' | tail -1`), runs `gh pr list --state open --json number,headRefName` and, for any pull request it lists, reads which numbers that branch spends, and takes the lowest numbers above all of them. A list that fails prints an error and no rows, which is not an empty list: run it again. If the remote cannot be reached, take the numbers from the fetched refs, say so in the Decision Log, and add the pull-request check to the operator's steps row. As observed at authoring on 2026-11-19 the highest on this branch were `0114` and `D174`, and the scope brief reported that `gh pr list --state open` printed `[]` that day; both are readings, not numbers to spend.

### Running the checks

`./tools/verify` is the one check command. It builds a throwaway database, runs every test tier that does not call Anthropic, and prints one `verify: <name> ... ok (Ns)` line per check and a last line `verify: all 6 checks passed in Ns.` It took 295 seconds at authoring. Run it with a command timeout of 600 seconds, or in the background and wait for it; under a 300-second timeout it can be cut off a few seconds before it finishes. Never run bare `pytest`: `tests/conftest.py` refuses any database not named `docket_test_*`. To run one test file while working, build the throwaway database yourself:

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_worker_scheduler.py -q -p no:cacheprovider
    tools/test-db --drop

Git hooks live in `tools/hooks/` and are never disabled or bypassed. In a milestone session every commit changes this plan file, and the text of a Progress entry is never reworded: a session ticks its entry by changing `- [ ]` to `- [x] (YYYY-MM-DD HH:MMZ)` and nothing else on the line.

Before changing `src/docket/services/ingest.py` (M1), read `docs/PRINCIPLES.md`.

## Plan of Work

### M1: the afternoon pass

At the end of M1 the scheduler registers twenty-two jobs: the nineteen it has, unchanged, and three afternoon jobs. Nothing else about the worker changes.

In `src/docket/config.py` add a helper and a setting near `WORKER_TIMEZONE`:

    def _csv(value: str) -> tuple[str, ...]:
        """The comma-separated parts of a setting, stripped, empty parts dropped."""
        return tuple(part.strip() for part in value.split(",") if part.strip())

    # The cities the worker's afternoon ingest visits (task ingest_afternoon).
    # An empty value turns the afternoon ingest off.
    AFTERNOON_INGEST_SLUGS: tuple[str, ...] = _csv(os.environ.get("AFTERNOON_INGEST_SLUGS", "birmingham"))

If the file already has a helper that does the same, use it and do not add a second.

In `src/docket/services/ingest.py` add a public function `active_slugs() -> list[str]` that runs `SELECT slug FROM municipalities WHERE active = TRUE ORDER BY slug` through `db_cursor()` and returns the slugs in that order. Its docstring says it is the one list of cities the worker's ingest tasks visit.

In `src/docket/worker/tasks.py`: import `active_slugs` beside `ingest_municipality`. Rewrite `_do_ingest_all` to loop over `active_slugs()` in place of its own statement; its behaviour (each city in slug order, a city that raises is logged with `log.exception("ingest failed for %s", slug)` and the next one runs) does not change. Add `_do_ingest_afternoon()`: read `config.AFTERNOON_INGEST_SLUGS`; if it is empty, log at INFO `ingest_afternoon: no cities configured (AFTERNOON_INGEST_SLUGS is empty)` and return; otherwise take `active = set(active_slugs())` and for each configured slug in the configured order: a slug not in `active` is logged at WARNING as `ingest_afternoon: <slug> is not an active municipality; skipped` and passed over; otherwise call `ingest_municipality(slug)`, and on an exception log `log.exception("ingest failed for %s", slug)` and continue; on a result log at INFO one line

    ingest_afternoon <slug>: found=<meetings_found> inserted=<meetings_inserted> updated=<meetings_updated> items=<agenda_items_inserted> votes=<votes_inserted> errors=<len(errors)>

The docstring of `_do_ingest_afternoon` says what it is for (a recording posted during the day has its row before the Legion's scheduled transcriber run; `transcriber/README.md`, "The scheduled run"), that the cities come from `AFTERNOON_INGEST_SLUGS`, and that the other cities keep one visit a day; it states no clock time. Add `task_ingest_afternoon()` calling `_safe_run("ingest_afternoon", _do_ingest_afternoon)` and the entry `"ingest_afternoon": task_ingest_afternoon` in `TASKS`. The module still imports `db_cursor`; other bodies use it.

In `src/docket/worker/health.py` add to `TASK_UUID_ENV` the entry `"ingest_afternoon": "HEALTHCHECK_INGEST_AFTERNOON_UUID"` with a comment: the check is `docket-ingest-afternoon`; the operator creates it and sets the variable on the worker service after the first deploy of the task; `ping()` short-circuits until then.

In `src/docket/worker/scheduler.py`, immediately after the `non_meetings` job and before `ai_items`, register three jobs, each `coalesce=True, max_instances=1` like every other:

    id="ingest_afternoon"           TASKS["ingest_afternoon"]   CronTrigger(hour=16, minute=30, timezone=timezone)
    id="youtube_ingest_afternoon"   TASKS["youtube_ingest"]     CronTrigger(hour=16, minute=45, timezone=timezone)
    id="non_meetings_afternoon"     TASKS["non_meetings"]       CronTrigger(hour=16, minute=55, timezone=timezone)

Above them one comment: the afternoon pass, Birmingham only, repeats the morning's three source tasks so a recording posted during the day has its row and its attached YouTube recording before the Legion's scheduled transcriber run (`transcriber/README.md`, "The scheduled run"); the second and third are second jobs on the morning's tasks and ping the same checks. The module docstring says "all nineteen jobs" and the `build_scheduler` docstring says "all nineteen jobs registered"; this milestone makes both false, so change them to "every job" with no number.

Tests. In `tests/unit/test_worker_scheduler.py`: `test_build_scheduler_registers_all_jobs` gains the three new ids and expects 22 jobs (it fails before the scheduler edit). Add `test_build_scheduler_afternoon_pass`, which for each of the three jobs asserts the hour, minute, and `day_of_week` fields (`("16", "30", "*")`, `("16", "45", "*")`, `("16", "55", "*")`), `coalesce is True`, `max_instances == 1`, and that `job.func` is `scheduler.TASKS["ingest_afternoon"]`, `scheduler.TASKS["youtube_ingest"]`, and `scheduler.TASKS["non_meetings"]` in turn; and `test_build_scheduler_morning_pass_is_unchanged`, which asserts `ingest_all` at `("6", "0")`, `youtube_ingest` at `("6", "45")`, `non_meetings` at `("6", "55")`. In `tests/unit/test_worker_tasks.py`: the two `ingest_all` tests patch `docket.worker.tasks.active_slugs` in place of `db_cursor` and keep their assertions; `test_tasks_registry_has_all_jobs` gains `"ingest_afternoon"`; add `test_ingest_afternoon_ingests_only_the_configured_active_cities` (with `docket.worker.tasks.config.AFTERNOON_INGEST_SLUGS` patched to `("birmingham",)` and `active_slugs` returning `["birmingham", "homewood", "mobile", "vestavia_hills"]`, `ingest_municipality` is called exactly once, with `("birmingham",)`, and the INFO line for Birmingham is logged), `test_ingest_afternoon_skips_a_configured_city_that_is_not_active` (configured `("birmingham", "hoover")`: one call, and a WARNING naming `hoover`), `test_ingest_afternoon_continues_on_per_city_failure`, `test_ingest_afternoon_does_nothing_when_no_city_is_configured` (configured `()`: `ingest_municipality` and `active_slugs` are not called), and `test_ingest_afternoon_is_registered_and_safe_run_wrapped` (the pings are `("ingest_afternoon", "start")` then `("ingest_afternoon", "success")`). Patch `ingest_municipality` to return a `MagicMock` with integer counts and `errors=[]` where the log line is asserted. Add tests of `config._csv` (`"birmingham, mobile,,"` gives `("birmingham", "mobile")`; `""` gives `()`) in the same file or the existing config test file if one exists. In `tests/unit/test_worker_health.py` add an assertion that `health.TASK_UUID_ENV["ingest_afternoon"] == "HEALTHCHECK_INGEST_AFTERNOON_UUID"`. Add `tests/integration/test_ingest_active_slugs.py`: insert two cities with slugs that cannot collide with real ones, one active and one not (model the insert and its cleanup on `tests/integration/test_ingest_preserves_is_hidden.py`), and assert that `active_slugs()` contains the active one, omits the other, and is sorted; delete both rows afterwards.

For each new test that passes on its first run, follow `skills/plan-execute/SKILL.md` on proving it can fail.

### M2: `--list`, and the docstrings

At the end of M2 a person can print the schedule from the code, and no docstring outside `scheduler.py` states a worker clock time.

In `src/docket/worker/scheduler.py` add

    def list_jobs(timezone: str = "America/Chicago") -> list[str]:

which builds the scheduler and returns one line per job, `<job id> <task name> <trigger>`, separated by single spaces. The task name is the key of `TASKS` whose function the job runs, found by identity (`f is job.func`). The trigger is `str(job.trigger)`. The lines are sorted by a key of three parts: the trigger's hour as an integer when its `hour` field is a single number, else 24; its minute as an integer when its `minute` field is a single number, else 60; then the job id. (Read the fields as the existing tests do: `{f.name: str(f) for f in job.trigger.fields}`.) Add the flag `--list` to `main()`, mutually exclusive with `--run-once`: it prints `timezone=<tz> jobs=<n>` and then the lines, with the timezone from `config.WORKER_TIMEZONE`, starts nothing, pings nothing, opens no database connection, and returns. Extend the module docstring's list of modes with it.

Tests in `tests/unit/test_worker_scheduler.py`: `test_list_jobs_prints_every_job_in_time_of_day_order` (the list has one line per job of `build_scheduler()`, the first line is `prune_analytics prune_analytics cron[day='1', hour='4', minute='0']`, the last is `process_batches process_batches cron[minute='0,30']`, and `ingest_all` comes before `ingest_afternoon`), `test_list_jobs_names_the_task_a_second_job_runs` (the list contains `youtube_ingest_afternoon youtube_ingest cron[hour='16', minute='45']` and `non_meetings_afternoon non_meetings cron[hour='16', minute='55']`), and `test_main_with_list_prints_the_schedule_and_starts_nothing` (with `sys.argv` set to `["scheduler", "--list"]` and `build_scheduler` left real, `capsys` shows the header line and the scheduler's `start` is never called; patch `BlockingScheduler.start` to fail the test if called).

Then the docstrings. Each of these states a clock time that `scheduler.py` owns; reword each to keep the order and the reason and drop the time. In `src/docket/worker/tasks.py`: `_do_briefing_facts` ("runs at 09:45 after vote_matching (09:00) and process_badges (09:30)" becomes "runs after vote_matching and process_badges"), `_do_city_calendar` ("runs at 05:30 so the rows exist before ingest_all (06:00)" becomes "runs before ingest_all so the rows exist when it"), `_do_non_meetings` ("Runs at 06:55, after ``youtube_ingest`` (06:45)" becomes "Runs after each ``youtube_ingest`` run, morning and afternoon,"), `_do_committee_documents` ("Runs at 07:15, after ``youtube_ingest`` (06:45)" becomes "Runs after the morning ``youtube_ingest``"). Add to the `_do_youtube_ingest` docstring that it runs after each ingest pass, morning and afternoon. In `src/docket/services/non_meetings.py` the module docstring's "(06:55 America/Chicago, after ``youtube_ingest``)" becomes "(after each ``youtube_ingest`` run; ``docket.worker.scheduler`` owns the times)", and "The daily worker task" becomes "The worker task". In `src/docket/services/city_calendar.py` the module docstring's "(05:30 America/Chicago, before ``ingest_all`` at 06:00)" becomes "(before ``ingest_all``; ``docket.worker.scheduler`` owns the times)". Change no code in those two service modules.

### M3: the prose that stated the schedule

At the end of M3 no document outside the leave-alone list states a worker task count or clock time; each says where the schedule is and how to print it. The command to name is `venv/bin/python -m docket.worker.scheduler --list` (in a checkout) and `python -m docket.worker.scheduler --list` (inside the worker container).

`docs/runbooks/cron-worker.md`. The opening sentence loses "nineteen scheduled tasks" and says the service runs the jobs registered in `src/docket/worker/scheduler.py`, which `--list` prints with the task each runs and its trigger. The Task inventory table loses its "Cron (America/Chicago)" column and keeps its rows in the order `--list` prints the jobs; add a row for `ingest_afternoon` (variable `HEALTHCHECK_INGEST_AFTERNOON_UUID`; notes: ingests the cities `AFTERNOON_INGEST_SLUGS` names, Birmingham by default, so a recording posted during the day has its row before the Legion's scheduled transcriber run, `transcriber/README.md`, "The scheduled run"; an empty value turns it off; logs one `ingest_afternoon <slug>: found=... errors=...` line per city), and say in the `youtube_ingest` and `non_meetings` rows that each runs twice a day under two job ids (`youtube_ingest` and `youtube_ingest_afternoon`; `non_meetings` and `non_meetings_afternoon`) and pings one check. Remove "Daily" clock times from the notes where a note repeats one. In the block of `railway variables` lines add `HEALTHCHECK_INGEST_AFTERNOON_UUID` and `HEALTHCHECK_YOUTUBE_INGEST_UUID`. The "Suggested schedule + grace per check" table loses its Schedule column and gains a column naming the job or jobs each check hears from, a row `docket-ingest-afternoon` (job `ingest_afternoon`, grace 2h), and this rule above it: give each check the schedule of its job as `--list` prints it, in America/Chicago; a check that hears from two jobs (`docket-youtube-ingest`, `docket-non-meetings`) takes one cron expression naming both hours, `<minute> <morning hour>,<afternoon hour> * * *`, so a missed afternoon run pages as a missed morning run does. Add `--run-once ingest_afternoon` to the run-once list after `ingest_all`. In "Member vote resolution", "(daily 08:45)" becomes "(daily)". In the note under "When a Healthchecks alert fires" say that `docket-ingest-afternoon`, like `docket-ingest`, is green when a city's ingest returned errors without raising; the log line's `errors=` count says so.

`README.md`. In the "Cron worker" paragraph (line 25 at authoring) replace "with fifteen scheduled tasks in `America/Chicago`" and the whole list of task names with times by: the schedule is `src/docket/worker/scheduler.py`, in `America/Chicago`; `venv/bin/python -m docket.worker.scheduler --list` prints every job, and `docs/runbooks/cron-worker.md` says what each task does; keep the sentences about Healthchecks, the manual trigger, the spec and the runbook, the one naming the two silent-by-design tasks included (it matches `SILENT_BY_DESIGN` in `health.py` at authoring: `prune_analytics`, `calibration_report`). In the "Meeting transcripts" paragraph (line 27) drop "10:00 CT: " from the parenthesis. In the numbered item "Cron Worker (T27)" (line 68) drop "15 daily/weekly/monthly tasks (...)" and the parenthesis counting monitored checks; say it runs the scheduled tasks `--list` prints, with a Healthchecks.io heartbeat per task, and that the runbook says which tasks have a check. In the file tree (line 612) the comment on `tasks.py` loses "11" and its list of names: "task wrappers; `_safe_run` handles the Healthchecks ping and swallows exceptions". In the roadmap, the bullet "Move `www.docket.pub` to Railway" describes a Namecheap redirect that no longer exists; replace it with one bullet saying that `www.docket.pub` redirects to the apex at Cloudflare's edge (decision `0091`) and what remains is `includeSubDomains` on the HSTS header (`D10` in `docs/DEBT.md`).

The other sites, each one phrase: `docs/runbooks/transcripts.md` at four places ("the `transcript_pipeline` cron (10:00 CT)"; "`transcript_pipeline` runs at 10:00 America/Chicago (after vote matching)"; "(10:00 America/Chicago, `src/docket/worker/scheduler.py`)" in "Re-transcribing one meeting"; "The worker's 10:00 CT tick"): say "daily", "after vote matching", or "the `transcript_pipeline` job, whose time `--list` prints", as fits each sentence; the third keeps its pointer to `scheduler.py` and gains the command, because the operator needs the time there. `docs/runbooks/transcripts-pipeline-map.md` line 19 ("cron transcript_pipeline, 10:00 America/Chicago") becomes "cron transcript_pipeline, daily". `docs/specs/transcripts.md` line 23 ("the worker's daily 10:00 Central window") loses "10:00 Central". `docs/specs/committee-documents.md` line 96 ("so it is run before 04:00 or after 11:15 America/Chicago") becomes: so it is run while no worker job is due; `venv/bin/python -m docket.worker.scheduler --list` prints the schedule, which apart from the half-hourly `process_batches` is a morning block and a short afternoon pass. `docs/specs/city-page.md` ("`CronTrigger(hour=9, minute=45)` America/Chicago in `scheduler.py`") becomes "scheduled in `src/docket/worker/scheduler.py`".

`docs/DEBT.md`: delete the rows `D69` and `D138`. Two citations of them remain and are right to remain: decision `0111` cites `D69` as history, and the `D149` row cites `D138` in its trigger, which M4 rewords.

### M4: the closing documents

At the end of M4 the documents that describe behaviour say what M1 built, the Legion's scheduled run is written down, the durable decisions are records, and the register is true. No clock time of the worker's is written into any of these documents; they name jobs and point at `--list`. The Legion's 17:30 is written in `transcriber/README.md` and nowhere else.

`transcriber/README.md`. Delete the paragraph that begins "Task Scheduler (optional): a basic task "At log on"" and add, after the "Running" section and before "YouTube recordings", a section headed `## The scheduled run` that states: on the Legion a Windows Task Scheduler task named `docket-transcriber` runs the producer every day at 17:30 Central; it was registered on 2026-11-19 with these settings as the operator reported them (no session of the repository has seen the machine): run only when the operator is logged on, start a missed run when the machine is next available, do not start on battery; the task runs `C:\docket-archive\run-transcriber.cmd`, a script kept on the Legion and not in this repository, which runs the `docker compose ... run --rm -T transcriber --since 2025-10-28 --limit 10 --max-hours 3` line given in Context above (as an indented block) and appends its output to `C:\docket-archive\logs\transcriber-scheduled.log`; `--max-hours 3` ends a run three hours after it starts at the latest; the time is chosen to follow the worker's afternoon pass (the jobs `ingest_afternoon`, `youtube_ingest_afternoon` and `non_meetings_afternoon`, whose times `python -m docket.worker.scheduler --list` prints), so a recording Birmingham posts during the day is claimed that evening; a run by hand is still the command under "Running"; and a last paragraph: when this was written the task had not fired once, so how long a scheduled run takes is not known; the operator records the first run's start and end, read from the log, here. Not yet recorded.

`docs/runbooks/transcripts.md`, "Running the producer (on the Legion)": one bullet saying the Legion also runs this command on a schedule and pointing to `transcriber/README.md`, "The scheduled run", and one saying a transcript uploaded by an evening run shows "Speaker N" until the worker's next daily `transcript_pipeline` tick (no afternoon or evening tick exists; name the decision record written below).

`docs/specs/operations.md`. In the paragraph on Birmingham's YouTube recordings, "(daily, after `ingest_all`; ..." becomes "(after each ingest pass, morning and afternoon; ...". In the paragraph on clips that are not meetings, "(daily, after `youtube_ingest`; ..." becomes "(after each `youtube_ingest` run; ...". After that paragraph add one on the afternoon pass: what the three jobs are and why (the purpose in one sentence), that `ingest_afternoon` visits the cities `AFTERNOON_INGEST_SLUGS` names (default `birmingham`; read in `src/docket/config.py`; set on the `worker` service; an empty value turns the afternoon ingest off at the worker's next start), that the other cities are visited once a day, that its Healthchecks variable is `HEALTHCHECK_INGEST_AFTERNOON_UUID`, and that the other two afternoon jobs ping the morning tasks' checks. In the Transcriber section add one sentence: the Legion runs the producer on a schedule through Windows Task Scheduler, and `transcriber/README.md`, "The scheduled run", is the one place that says how.

`docs/specs/meeting-types.md`. In "The council's YouTube channel", "the daily worker task `youtube_ingest`" becomes "the worker task `youtube_ingest`, which runs after each ingest pass, morning and afternoon"; say in one sentence that a second run in a day creates no row the first did not (the three-day rule reads the date) and attaches a recording uploaded since. In "Clips that are not meetings", "(daily, scheduled in `src/docket/worker/scheduler.py` after `youtube_ingest`, ..." becomes "(scheduled in `src/docket/worker/scheduler.py` after each `youtube_ingest` run, ..."; say in one sentence that the afternoon run applies the same rule to the same rows, and that the calendar read it relies on is the morning's, inside the 36-hour limit.

`docs/birmingham/02-ingest.md`, the paragraph that begins "The worker (`src/docket/worker/scheduler.py` owns the times": after the morning order add that in the afternoon a second, shorter pass runs for Birmingham alone, `ingest_afternoon`, then `youtube_ingest` and `non_meetings` again, so that a recording posted during the day has its row before the Legion's scheduled transcriber run (chapter 7). `docs/birmingham/07-operations.md`, "The daily rhythm": "Every morning, Chicago time:" stays for the list, and the list gains an item after "Reporting": **Afternoon**, the second pass in the same words; the paragraph "The transcriber is **not** on this schedule..." is rewritten: the transcriber is not a worker job; on the Legion, Windows Task Scheduler starts it once a day after the worker's afternoon pass (`transcriber/README.md`, "The scheduled run"), the operator can still start it by hand, and its uploads are picked up by the worker's next `transcript_pipeline` tick, so a same-day transcript shows "Speaker N" until the next morning.

`docs/decisions/`: three records, numbered by the rule in Context, each from the Decision Log entry named and in the directory's format. `NNNN-the-afternoon-pass-is-one-birmingham-only-ingest-task-and-second-jobs-on-two-existing-tasks.md` (the first three Decision Log entries: the task and the two second jobs, the checks, the setting). `NNNN-no-afternoon-or-evening-transcript-pipeline-tick.md` (the operator's decision, with the sentence that the reasons are the author's reading). `NNNN-the-worker-schedule-is-stated-in-scheduler-py-and-printed-by-list.md` (the `D69` payment: prose names jobs and their order and points at `--list`; it states no count and no clock time; the leave-alone list).

`docs/DEBT.md`, in one commit or several, each changing this plan file too. Two new rows, numbered by the rule. The first: the `adapter_config` of `vestavia_hills` and `mobile` (both `CivicClerkAdapter`) holds `delay=0.5`, half the one second `GOALS.md` requires between requests to a city's site, as a read-only production query printed on 2026-11-19 (give all four cities' values from Context); where: production `municipalities.adapter_config`; why deferred: true before plan `recordings-seen-the-day-posted`, whose afternoon pass visits neither city, and the operator chose to record and not fix it; trigger: the next change to either city's row or to `src/docket/adapters/civicclerk.py`, or a refusal from either site: one targeted `UPDATE` setting `delay` to 1.0 for the two slugs. The second: the operator's steps after the pull request of this plan merges, in the order Validation and Acceptance gives them, with "the pull request merges" as its trigger; it names `HEALTHCHECK_INGEST_AFTERNOON_UUID`, the three cron expressions, and the two places an observation is recorded. Then the edits to existing rows, each an appended sentence dated 2026-11 and naming this plan, never a rewrite of what is there: `D34` (touched `tasks.py` and `health.py`; added no `os.environ` read, the new setting being read through `config.py`; re-deferred for the reasons the row already gives for each file); `D46` (added a task to `tasks.py`; re-deferred as unrelated); `D65` (the `_do_ingest_all` statement moved to `ingest.active_slugs` by M1, so six bodies remain; the others re-deferred as unrelated to the outcome); `D102` (since this plan the fetch and the WARNING lines happen twice a day for Birmingham; `AFTERNOON_INGEST_SLUGS` set empty stops the afternoon half); `D119` and `D121` (one docstring sentence changed in each of `non_meetings.py` and `city_calendar.py`, no behaviour; re-deferred); `D149` (the README half paid by M3: reword the row to the analytics runbook alone and drop the README from its Where and its trigger); `D93` (the verify times this plan's sessions recorded, read from this file, and the count of tests the plan added).

## Concrete Steps

Every session starts and ends with `./tools/verify` from the worktree root, under a 600-second timeout or in the background, and records the last line of each run in this plan. The transcripts below are expected, not observed, except where a line says it was run at authoring.

M1. After the edits:

    venv/bin/python - <<'EOF'
    from docket.worker import scheduler
    for j in scheduler.build_scheduler().get_jobs():
        if j.id.endswith("afternoon") or j.id in ("ingest_all", "youtube_ingest", "non_meetings"):
            print(j.id, str(j.trigger), j.coalesce, j.max_instances)
    EOF

Run at authoring on the unchanged tree, this printed the first three lines below and nothing more. Expected after M1:

    ingest_all cron[hour='6', minute='0'] True 1
    youtube_ingest cron[hour='6', minute='45'] True 1
    non_meetings cron[hour='6', minute='55'] True 1
    ingest_afternoon cron[hour='16', minute='30'] True 1
    youtube_ingest_afternoon cron[hour='16', minute='45'] True 1
    non_meetings_afternoon cron[hour='16', minute='55'] True 1

    venv/bin/python -m docket.worker.scheduler --run-once not_a_task

Run at authoring, this exited 1 and printed `unknown task: 'not_a_task' (known: [...])` with nineteen names. Expected after M1: the same with twenty names, `'ingest_afternoon'` among them, exit 1.

M2. After the edits:

    venv/bin/python -m docket.worker.scheduler --list

Run at authoring, this exited 2 with `scheduler.py: error: unrecognized arguments: --list`. Expected after M2, exit 0 and exactly these twenty-three lines (the triggers are `str()` of the triggers, which the authoring session printed for the nineteen existing jobs):

    timezone=America/Chicago jobs=22
    prune_analytics prune_analytics cron[day='1', hour='4', minute='0']
    refresh_backfill_ratio_mv refresh_backfill_ratio_mv cron[hour='4', minute='30']
    recast_post_meeting_ai recast_post_meeting_ai cron[hour='4', minute='45']
    repair_empty_agendas repair_empty_agendas cron[day_of_week='0', hour='5', minute='0']
    city_calendar city_calendar cron[hour='5', minute='30']
    ingest_all ingest_all cron[hour='6', minute='0']
    video_ocr video_ocr cron[hour='6', minute='30']
    youtube_ingest youtube_ingest cron[hour='6', minute='45']
    non_meetings non_meetings cron[hour='6', minute='55']
    ai_items ai_items cron[hour='7', minute='0']
    committee_documents committee_documents cron[hour='7', minute='15']
    ai_meetings ai_meetings cron[hour='8', minute='0']
    resolve_member_votes resolve_member_votes cron[hour='8', minute='45']
    vote_matching vote_matching cron[hour='9', minute='0']
    process_badges process_badges cron[hour='9', minute='30']
    briefing_facts briefing_facts cron[hour='9', minute='45']
    transcript_pipeline transcript_pipeline cron[hour='10', minute='0']
    calibration_report calibration_report cron[hour='11', minute='0']
    ingest_afternoon ingest_afternoon cron[hour='16', minute='30']
    youtube_ingest_afternoon youtube_ingest cron[hour='16', minute='45']
    non_meetings_afternoon non_meetings cron[hour='16', minute='55']
    process_batches process_batches cron[minute='0,30']

If the worker's environment sets `WORKER_TIMEZONE`, the header names that zone. Then:

    grep -rnE "\b(0[4-9]|1[01]|16):[0-5][0-9]\b" src/docket/worker/tasks.py src/docket/services/non_meetings.py src/docket/services/city_calendar.py

Run at authoring this printed nine lines (seven in `tasks.py`, one in each service module). Expected after M2: no output.

M3. After the edits:

    grep -rnE "\b(0[4-9]|1[01]):(00|15|30|45|55)\b|\b16:(30|45|55)\b" README.md docs/specs docs/runbooks docs/birmingham transcriber/README.md | cut -d: -f1 | sort | uniq -c

Run at authoring this printed nine files: `README.md` 2, `docs/runbooks/analytics.md` 1, `docs/runbooks/coming-up-reading-birmingham.md` 1, `docs/runbooks/cron-worker.md` 33, `docs/runbooks/transcripts-pipeline-map.md` 1, `docs/runbooks/transcripts.md` 4, `docs/runbooks/v3-cutover.md` 4, `docs/specs/committee-documents.md` 1, `docs/specs/transcripts.md` 1. Expected after M3, the three leave-alone files only:

          1 docs/runbooks/analytics.md
          1 docs/runbooks/coming-up-reading-birmingham.md
          4 docs/runbooks/v3-cutover.md

    grep -nE "nineteen|fifteen scheduled|15 daily/weekly/monthly|11 task wrappers" README.md docs/runbooks/cron-worker.md src/docket/worker/scheduler.py

Run at authoring this printed six lines. Expected after M3: no output.

    grep -c "^| D69 \|^| D138 " docs/DEBT.md

Run at authoring this printed `2`. Expected after M3: `0`.

    grep -c "ingest_afternoon" docs/runbooks/cron-worker.md

Expected after M3: 3 or more (the inventory row, the check row, the run-once line); it printed nothing matching at authoring (`grep -rn "ingest_afternoon" src docs README.md transcriber tests` printed nothing).

M4. After the edits:

    grep -n "^## The scheduled run\|At log on" transcriber/README.md

Run at authoring this printed one line, `88:Task Scheduler (optional): a basic task "At log on" running`. Expected after M4: one line, the new heading.

    grep -c "docket-transcriber" transcriber/README.md docs/specs/operations.md docs/runbooks/transcripts.md docs/birmingham/07-operations.md

Run at authoring this printed `0` for all four. Expected after M4: `transcriber/README.md` 1 or more; the other three may stay 0, because they point to the README section by its name and need not repeat the task's name.

    grep -n "daily, after" docs/specs/operations.md

Run at authoring this printed two lines (106 and 108). Expected after M4: no output.

    ls docs/decisions | grep -E "afternoon-pass|transcript-pipeline-tick|printed-by-list"

Run at authoring this printed nothing. Expected after M4: three file names.

    grep -c "vestavia_hills" docs/DEBT.md
    grep -c "HEALTHCHECK_INGEST_AFTERNOON_UUID" docs/DEBT.md

Run at authoring each printed `0`. Expected after M4: each 1 or more. And the M3 time grep again, with the same three-file output, to show M4 wrote no worker clock time into those documents.

## Validation and Acceptance

M1 is accepted when `./tools/verify` ends `verify: all 6 checks passed`, the M1 snippet prints the six expected lines, `--run-once not_a_task` names `ingest_afternoon`, and the session has seen `test_build_scheduler_registers_all_jobs` fail before the scheduler edit and pass after it. The test named `test_ingest_afternoon_ingests_only_the_configured_active_cities` is the proof that the afternoon ingest visits Birmingham and no other city. The fast tiers' total rises from the `3480 passed` of authoring by the tests the new functions collect, and the integration tier's from `1049 passed`; the session records both totals as it reads them.

M2 is accepted when `./tools/verify` passes, `--list` prints the twenty-three expected lines and exits 0, and the docstring grep prints nothing.

M3 is accepted when `./tools/verify` passes, the time grep prints the three leave-alone files only, the count grep prints nothing, the debt-row count is `0`, and `docs/runbooks/cron-worker.md` names `ingest_afternoon`.

M4 is accepted when `./tools/verify` passes and the M4 greps print what Concrete Steps expects.

The operator's steps, after the pull request merges. None is part of a milestone; M4 copies them into a debt row. In order:

1. Deploy the worker from a clean `main`: `scripts/deploy.sh --service worker`.
2. Read the startup log, `railway logs --service worker`: it should show `jobs=22`, the lines `job=ingest_afternoon next_run=...`, `job=youtube_ingest_afternoon next_run=...` and `job=non_meetings_afternoon next_run=...` with times of 16:30, 16:45 and 16:55 Central, and a WARNING that names `ingest_afternoon (HEALTHCHECK_INGEST_AFTERNOON_UUID)` among the tasks with no check.
3. At healthchecks.io create the check `docket-ingest-afternoon` with the cron schedule `30 16 * * *`, time zone America/Chicago, grace 2 hours; set it with `railway variables --service worker --set HEALTHCHECK_INGEST_AFTERNOON_UUID=<uuid>` and redeploy the worker as `docs/runbooks/cron-worker.md` says; the startup WARNING then no longer names the task.
4. Change the schedule of `docket-youtube-ingest` to `45 6,16 * * *` and of `docket-non-meetings` to `55 6,16 * * *`, America/Chicago, grace 2 hours; if either check does not exist yet, create it with that schedule and set its variable (`HEALTHCHECK_YOUTUBE_INGEST_UUID`, `HEALTHCHECK_NON_MEETINGS_UUID`).
5. After the first afternoon, read the log for the lines `ingest_afternoon birmingham: found=... errors=0`, `youtube_ingest birmingham: ...` and `non_meetings: 1 cities read`, and note when the ingest line was written: if it is later than the YouTube line's start, the afternoon ingest takes more than fifteen minutes and the times need another look.
6. After the Legion's first scheduled run, read `C:\docket-archive\logs\transcriber-scheduled.log` and write the run's start and end into `transcriber/README.md`, "The scheduled run", in place of "Not yet recorded."
7. On the first day Birmingham posts a recording between the morning pass and the afternoon one, confirm the outcome: before 17:30 the meeting's row has its `video_url` (`SELECT id, external_id, video_url IS NOT NULL AS has_video, updated_at FROM meetings WHERE municipality_id = (SELECT id FROM municipalities WHERE slug = 'birmingham') AND meeting_date = current_date`, read-only), and that evening `https://docket.pub/al/birmingham/meetings/<id>/transcript/` answers 200.
8. If a session could not list the open pull requests when it took a decision number or a debt id, check that no open pull request spends the same number.

## Idempotence and Recovery

Every step of every milestone can be repeated. The tests seed and remove their own rows and run only against the throwaway database. `--list` reads nothing but the code. The documentation edits are replacements of named phrases; a session that finds a phrase already replaced leaves it.

The afternoon pass itself is safe to repeat by design: ingest upserts, the YouTube pass and the hiding rule decide from stored rows and the date, and each job is `coalesce=True, max_instances=1`. In production the afternoon ingest is turned off without a code change by setting `AFTERNOON_INGEST_SLUGS` to an empty value on the `worker` service and redeploying it (the task then logs that no city is configured and succeeds); the two second jobs are harmless without it. Removing the pass altogether is a revert of the pull request and a deploy. Nothing in this plan writes to production, changes the schema, or calls Anthropic.

If a session cannot finish its milestone, it splits the Progress entry in place (completed and remaining), records the split in the Decision Log, and stops, as `plans/PLANS.md` requires.

## Artifacts and Notes

The verify run at authoring, on `a484523`, before any edit:

    verify: test-db ... ok (0s) postgresql://docket:docket_dev@localhost:5432/docket_test_7eed746c
    verify: unit+web+services ... ok (171s)
    verify: integration ... ok (112s)
    verify: judge-fixtures ... ok (0s)
    verify: workflows ... ok (1s)
    verify: transcriber ... ok (11s)
    verify: plans ... ok (0s)
    verify: all 6 checks passed in 295s.

The nineteen jobs as `build_scheduler()` held them at authoring, printed as id, trigger, and function name, are the first eighteen and the last of the expected `--list` lines above without the three afternoon ones; `recast_post_meeting_ai` is registered in `TASKS` as a lambda, which is why `list_jobs` finds a job's task by identity and not by function name.

M1, session of 2026-11-19 (observed). The verify run before any edit, on `3919b44`:

    verify: unit+web+services ... ok (170s)
    verify: integration ... ok (110s)
    verify: judge-fixtures ... ok (1s)
    verify: workflows ... ok (0s)
    verify: transcriber ... ok (10s)
    verify: plans ... ok (0s)
    verify: all 6 checks passed in 291s.

with the tier totals `3480 passed, 5 skipped, 4 xfailed`, `1049 passed`, `judge fixtures: 12 of 12 passed`, and `147 passed`.

M1, the tests before the code. With the test edits made and `src/` untouched, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_worker_scheduler.py tests/unit/test_worker_tasks.py tests/unit/test_worker_health.py tests/integration/test_ingest_active_slugs.py -q -p no:cacheprovider` printed `17 failed, 64 passed, 1 warning in 1.20s`. The seventeen: `test_build_scheduler_registers_all_jobs`; the three cases of `test_build_scheduler_afternoon_pass`; the two `ingest_all` tests (they now patch `docket.worker.tasks.active_slugs`, which does not exist yet); the six `test_ingest_afternoon_*` tests; the two config tests; `test_tasks_registry_has_all_jobs`; `test_ingest_afternoon_has_its_healthcheck_variable`; and the integration test `test_active_slugs_lists_the_active_cities_in_slug_order` (`ImportError`). The three cases of `test_build_scheduler_morning_pass_is_unchanged` passed, as they must on the unchanged scheduler. The commit that holds this paragraph holds the tests in that failing state.

M1, the tests after the code. With the edits to `src/docket/config.py`, `src/docket/services/ingest.py`, `src/docket/worker/tasks.py`, `src/docket/worker/health.py` and `src/docket/worker/scheduler.py` made, the same command printed `81 passed, 1 warning in 0.94s`.

M1, the acceptance snippet of Concrete Steps, run after the edits, printed the six expected lines:

    ingest_all cron[hour='6', minute='0'] True 1
    youtube_ingest cron[hour='6', minute='45'] True 1
    non_meetings cron[hour='6', minute='55'] True 1
    ingest_afternoon cron[hour='16', minute='30'] True 1
    youtube_ingest_afternoon cron[hour='16', minute='45'] True 1
    non_meetings_afternoon cron[hour='16', minute='55'] True 1

and `len(scheduler.build_scheduler().get_jobs())` printed `22`. `venv/bin/python -m docket.worker.scheduler --run-once not_a_task` exited 1 and printed `unknown task: 'not_a_task' (known: [...])` with twenty names, `'ingest_afternoon'` between `'committee_documents'` and `'ingest_all'`.

M1, proving the new tests can fail. Thirty-seven rules were taken out of the code one at a time, each in a copy of the source altered in memory at import (a `sitecustomize.py` in the session scratchpad that replaces one string of one file as Python loads it, so the subprocess the config test starts sees the same alteration; no committed file was edited), and the four test files were run against each copy. All thirty-seven failed at least one test; none survived. By file: sixteen in `tasks.py` (the empty-setting guard and its INFO line; the inactive-city skip and its WARNING; the per-city `try` and its `log.exception`; the result line, each of its counts, and the order of the cities; the name `_safe_run` pings; and for `_do_ingest_all` the per-city `try` and the call of `active_slugs`), four in `config.py` (strip, drop empty parts, the default `birmingham`, the variable's name), two in `ingest.py` (`WHERE active = TRUE`, `ORDER BY slug`), one in `health.py`, and fourteen in `scheduler.py` (each afternoon job's hour, minute, day of week, `coalesce`, `max_instances` and task, and each of the three morning times). Two of the thirty-seven patterns matched two places in `tasks.py` on the first run and failed collection instead of a test; they were narrowed and rerun, and each then failed a test. No assertion was added after the commit that holds the tests failing (`09ee1d4`); the only change to a test file after it is the removal of an unused `monkeypatch` argument and a reworded docstring on `test_config_afternoon_ingest_slugs_defaults_to_birmingham`.

## Interfaces and Dependencies

No new library. APScheduler's `BlockingScheduler` and `CronTrigger` are already used; `str()` of a `CronTrigger` prints as in the transcripts above on the installed version.

At the end of M1 these exist:

    src/docket/config.py
        def _csv(value: str) -> tuple[str, ...]
        AFTERNOON_INGEST_SLUGS: tuple[str, ...]        # env AFTERNOON_INGEST_SLUGS, default "birmingham"

    src/docket/services/ingest.py
        def active_slugs() -> list[str]

    src/docket/worker/tasks.py
        def _do_ingest_afternoon() -> None
        def task_ingest_afternoon() -> None
        TASKS["ingest_afternoon"] is task_ingest_afternoon

    src/docket/worker/health.py
        TASK_UUID_ENV["ingest_afternoon"] == "HEALTHCHECK_INGEST_AFTERNOON_UUID"

    src/docket/worker/scheduler.py, job ids
        "ingest_afternoon", "youtube_ingest_afternoon", "non_meetings_afternoon"

At the end of M2:

    src/docket/worker/scheduler.py
        def list_jobs(timezone: str = "America/Chicago") -> list[str]
        the command-line flag --list

Names spent by this plan and not to be reused for anything else: the task name `ingest_afternoon`, the three job ids, the setting and environment variable `AFTERNOON_INGEST_SLUGS`, the variable `HEALTHCHECK_INGEST_AFTERNOON_UUID`, the check name `docket-ingest-afternoon`, and the README heading "The scheduled run". The dependency directions are the existing ones: `worker/` calls `services/` and reads `config`; `services/ingest.py` gains no import.

## Revision notes

2026-11-19, authoring (Claude, from the operator's goal and a scope brief). The plan was written from the goal as the operator stated it and the operator's four answers of 2026-11-19, with the scope brief folded into Purpose and Context. Deliberately left out, as the brief set out: fixing the 0.5-second CivicClerk delays for Vestavia Hills and Mobile (recorded as a debt row only); any afternoon or evening `transcript_pipeline` run (a recorded decision); afternoon visits to Vestavia Hills, Mobile and Homewood; afternoon runs of `city_calendar`, `video_ocr`, `committee_documents`, `ai_items`, `vote_matching` or `briefing_facts`; any change to `HIDE_AFTER_DAYS` or to the three-day rule for `yt-` rows, so a meeting recorded only on YouTube is still not transcribed the day it is posted; checking the Legion's script, its Task Scheduler settings, or its first run, which are outside the repository and are documented as reported; deploying the worker and creating or changing Healthchecks checks, which are the operator's steps; paying `D34`, `D46`, the rest of `D65`, `D102`, `D119` and `D121`, each re-deferred in writing; and issues #174, #62 and #63, Granicus neighbours the goal does not name. Two things the brief left to the author were decided toward doing more: `D69` and `D138` are paid, with a `--list` command for the pointers to name, and the `_do_ingest_all` part of `D65` is paid because the afternoon task needs the same list of active cities. The brief's live check of remote branches did not complete and was not repeated; the plan fixes no decision number or debt id for that reason among others.
