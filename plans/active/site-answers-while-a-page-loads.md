# Run the web service with four gunicorn threads, so the site answers while a page loads

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

docket.pub's web service answers one request at a time. That did not matter while every page was a few database reads, but pull request 197 (plan `minutes-open-at-the-vote-page`, merged to `main` on 2026-11-23 as `97765fe`, not yet deployed) adds the minutes page viewer, a page that fetches a city's PDF while the reader waits. With one request at a time, a city file that is slow to arrive holds the whole site for up to about 13 seconds: every other reader, on every other page, waits behind it.

After this plan the web service is started as one gunicorn worker process with four threads, so four requests are answered at once and a viewer fetch holds one thread, not the site. gunicorn is the web server program that runs the Flask application; a worker is a process it starts to answer requests; a thread is one of several lines of work inside that one process, sharing its memory. The operator asked for this to be authored against `origin/main` as it stands with the viewer merged, so that one deploy ships the viewer and the threads together.

How someone sees it. In the repository, the line that starts the web service (in `Dockerfile`, which production runs, and in `Procfile`, which a reader would take for it) carries `--workers 1 --threads 4`, and a test that does not exist today, `tests/unit/test_web_start_line.py`, passes under `./tools/verify`: it reads both lines, and it starts a real gunicorn on the test machine with the `Dockerfile`'s options and shows a second request answered while a first is still held. On today's lines that test fails. After the operator's one deploy of `docket-web`, the running gunicorn's command line read inside the container shows `--workers 1 --threads 4`, the worker process shows more than one thread, and a request to another page answers while a minutes viewer page whose city file is not yet cached is loading. The deploy and those readings are the operator's (deploys are humans only, `AGENTS.md`); no milestone claims them.

## Progress

- [ ] M1: the web service's start line in `Dockerfile` and in `Procfile` asks gunicorn for one worker and four threads, and `tests/unit/test_web_start_line.py` pins both lines and shows, on a gunicorn started on the test machine with the `Dockerfile`'s options, a second request answered while a first is held.
- [ ] M2: the documents say it: `docs/specs/operations.md` and `docs/specs/votes.md` state one worker with four threads and what a viewer fetch now holds, a decision record under `docs/decisions/` says why threads and not more workers, `D197` in `docs/DEBT.md` is rewritten to its open half, and `D188` gains the operator's readings after the one deploy.

## Surprises & Discoveries

As authored on 2026-11-23, nothing has been executed, so no milestone has a surprise to report. What the authoring itself found is in Context and Orientation, under What was observed at authoring, and each line there says what was run.

## Decision Log

- Decision: "four gunicorn threads" is `--workers 1 --threads 4`, with the worker count written out and not left to gunicorn's default.
  Rationale: gunicorn 26.0.0 takes its default worker count from the environment variable `WEB_CONCURRENCY` when one is set (`default = int(os.environ.get("WEB_CONCURRENCY", 1))` in the installed `gunicorn/config.py`). `docs/specs/votes.md` says there is one cache of city files, one host gap and one failure memory because there is one web process; a second process would double all three and the roughly 214 MB resident size. Writing `--workers 1` makes the one process a property of the line a test can read and not of an environment nobody in a factory session can read. Production showed one worker on 2026-11-23, so the flag changes nothing there. The alternative, `--threads 4` alone, was the brief's literal reading and leaves the test's "one worker" true only by accident of the environment.
  Date/Author: 2026-11-23, plan author.

- Decision: both start lines are changed, `Dockerfile` and `Procfile`, and a test holds them to the same worker and thread counts.
  Rationale: production runs the `Dockerfile`'s line (`docs/specs/operations.md`, Railway specifics). The `Procfile`'s `web:` line is what `docs/birmingham/07-operations.md` names and what a reader would take for the start line; leaving it without the flag would be two files stating one fact differently (`docs/PRINCIPLES.md`, One owner per fact). Removing the `Procfile` line, or deciding which file Railway should read, is not asked and stays out.
  Date/Author: 2026-11-23, plan author.

- Decision: the timeout numbers are left as they are (none on the `Dockerfile`'s line, so gunicorn's 30 seconds; `--timeout 120` on the `Procfile`'s), and the documents say what the timeout means under threads.
  Rationale: the goal names threads only. Under the threaded worker the timeout stops being a limit on one request: the worker's main loop reports to gunicorn's parent process once a second whatever its threads are doing (`self.notify()` at the top of the loop in `ThreadWorker.run`, `gunicorn/workers/gthread.py`), so the parent restarts a worker whose loop stops and does not end one slow request. What bounds a viewer request is the viewer's own limits, as it already was in practice. Unifying the two numbers would be a second change with no observation behind it.
  Date/Author: 2026-11-23, plan author.

- Decision: the check has two halves, and the behavioural half starts a real gunicorn with a stub application, not the docket application.
  Rationale: a test that only reads the text of two files proves the text. `skills/plan-author/SKILL.md` asks that a claim about what code does be tested against the thing itself, so one test starts gunicorn as a subprocess with every option of the `Dockerfile`'s line except the application and the address, serving a ten-line application whose `/slow` path sleeps, and asserts a request to `/fast` finishes while `/slow` is held. That fails on today's options and passes with four threads (both observed at authoring with the options typed by hand). The stub keeps the test free of the database and of city sites and costs about four seconds. The real application under four threads is run once by hand in M1, as recorded evidence, because a permanent test of it would have nothing slow to hold a thread with.
  Date/Author: 2026-11-23, plan author.

- Decision: no lock is added to the two request-path caches that have none (`_cache` in `src/docket/services/neighborhood_schedule.py`, `_provenance_cache` in `src/docket/services/briefing.py`).
  Rationale: both were read at authoring. Each is one dictionary read and one assignment of a value that any thread would compute identically from the same file or the same rows; two threads that miss at once each compute it and each store it, and every reader gets a whole value either way. The worst case is a duplicated load, not a wrong page. A lock added on assumption would be code with no failing test behind it.
  Date/Author: 2026-11-23, plan author.

- Decision: the operator's after-deploy readings are appended to the existing `D188` row as steps 8 and 9, and `D197` is rewritten in place, keeping its id; no new debt id is spent.
  Rationale: `D188` already lists, in order, what the operator does after pull request 197's deploy, and its step 1 is the deploy this plan rides on. One deploy, one list. Its existing words are not reworded because the operator already has them; the additions say so. `D197`'s first half (a slow file holds the whole site because one worker answers one request at a time) is paid by four threads; its second half (nothing limits how fast one visitor may ask for viewer pages) stays open and is sharper under threads, since one crawler can now hold four threads at once.
  Date/Author: 2026-11-23, plan author.

- Decision: the plan is two milestones, code and its proof first, documents second.
  Rationale: after M1 the repository is coherent (the lines and their test agree, and the specs still describe production truthfully, because production runs the old build until the operator deploys). M2 then writes the documents about a start line that exists. One milestone would put the test, a hand run of the site, two specs, a decision record and two debt rows in one session with no room to record them.
  Date/Author: 2026-11-23, plan author.

## Outcomes & Retrospective

As authored on 2026-11-23, nothing has been executed and there is no outcome to report.

## Context and Orientation

### The repository, for a reader new to it

docket.pub publishes Alabama municipal meeting records at https://docket.pub. It is a Python 3.10 Flask application on PostgreSQL, deployed on Railway (a hosting service) as two services: `docket-web`, the site, and `worker`, a scheduled process this plan does not touch. `AGENTS.md` at the repository root is the map. All commands in this plan are run from the root of the worktree the session was started in, with that worktree's own `venv/`.

`./tools/verify` is the one check command. It builds a throwaway database, runs the test tiers, and prints one summary line per check and a final line. `AGENTS.md` gives it as about 150 seconds; at authoring it took 336 seconds in this worktree (below). Never run bare `pytest`: `tests/conftest.py` refuses any database not named `docket_test_*`. To run one test file, use the form `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest <file> -q -p no:cacheprovider; tools/test-db --drop`.

### What starts the web service today

`Dockerfile` ends with

    CMD ["sh", "-c", "python -m docket.migrations.runner && gunicorn 'docket.web:create_app()' --bind 0.0.0.0:${PORT:-5000}"]

and `Procfile` holds

    web: python -m docket.migrations.runner && gunicorn "docket.web:create_app()" --bind 0.0.0.0:${PORT:-5000} --timeout 120
    worker: python -m docket.worker.scheduler

Production runs the `Dockerfile`'s line, not the `Procfile`'s (`docs/specs/operations.md`, Railway specifics, a reading of 2026-11-23 taken from `/proc` inside the container). Neither line has `--workers`, `--threads` or `--worker-class`, which gunicorn reads as one worker of its `sync` class: one process that answers one request and only then takes the next. `requirements.lock` pins `gunicorn==26.0.0`, and `pyproject.toml` takes its dependencies from that file, so the developer's venv, CI and the container run the same gunicorn. No test, tool or CI file reads `Dockerfile` or `Procfile` today (a search of `tests`, `tools`, `scripts`, `.github` and `transcriber/tests` finds only comments in `scripts/deploy.sh`), so nothing mechanical pins the start line.

When gunicorn is given `--threads` above one and its worker class is the default, it uses its threaded worker class, `gthread` (`gunicorn.workers.gthread.ThreadWorker`): one process whose main loop accepts connections and hands each request to a pool of that many threads. Its start-up log then says `Using worker: gthread` where today's says `Using worker: sync`. The pool starts a thread when it first needs one, so the process's thread count grows with use, to five at most (the main loop and four).

### Why the viewer makes this matter

The minutes page viewer is the page at `/al/<slug>/meetings/<id>/minutes/page/<n>/` (`minutes_page` in `src/docket/web/public.py`; `docs/specs/votes.md`, The minutes page viewer; decision `0134`). When a reader opens it, `src/docket/services/minutes_viewer.py` fetches the city's PDF (`fetch_pdf` in `src/docket/adapters/source_file.py`, which ends within 12 seconds), keeps it in the web process's memory for an hour, and `src/docket/analysis/pdf_page.py` draws the one page as a picture. Requests to one host are kept a second apart. So a request that has to fetch can last about 13 seconds, and one that first waits behind another fetch on the same host can last about 26 (up to `WAIT_S`, 13 seconds, for the host's lock, then its own gap and fetch). Under one `sync` worker the whole site waits that long. `D197` in `docs/DEBT.md` records exactly this and names threads as the remedy to weigh.

### Is the code safe under threads

The viewer was written for threads. `minutes_viewer.py` guards its four dictionaries with `_state_lock`, which is never held across a sleep, a fetch or a draw, and keeps one lock per host; `pdf_page.py` makes every call into the PDF library `pypdfium2` under one module lock, because that library is not safe from two threads, and encodes the picture outside it; `tests/unit/test_minutes_viewer.py` has tests that use a real second thread. The older in-process caches on the request path take locks: `_overview_lock`, `_rss_lock` and `_member_lock` in `src/docket/web/public.py`, `_lock` in `src/docket/web/crawlers.py`, `_CACHE_LOCK` in `src/docket/web/source_security.py`. The two `lru_cache` functions in `src/docket/services/badges.py` are thread-safe by the standard library's contract. `src/docket/db.py` opens a new `psycopg2` connection in every `db()` call and shares none, so four threads mean at most a few more connections at once and there is no pool to resize. `src/docket/blog/render.py` builds its Markdown converter inside the function that uses it. `_dry_run_conn` in `src/docket/services/committee_documents.py` is set only inside `_rolled_back()`, which only a dry run asks for (line 646), and no web route runs a dry run.

Two caches have no lock, and the Decision Log says why none is added: `get_schedule` in `src/docket/services/neighborhood_schedule.py` (`if slug in _cache: return _cache[slug]`, then load the file and `_cache[slug] = schedule`) and the provenance function in `src/docket/services/briefing.py` (`_provenance_cache.get(municipality_id)`, then two reads and `_provenance_cache[municipality_id] = (now, result)`). M1 reads both again and records that they are as described; if either is not, that is a Surprises entry and a Decision Log entry before anything else is done.

### What was observed at authoring

Each of these was run on 2026-11-23 in the authoring worktree, cut from `origin/main` at `97765fe`.

`./tools/verify` exited 0: `verify: all 6 checks passed in 336s.`, with `3787 passed, 5 skipped, 4 xfailed` in the unit, web and services tiers (194 s), `1164 passed` in integration (130 s), `judge fixtures: 12 of 12 passed`, `147 passed` in the transcriber suite. The 336 seconds is more than twice the figure in `AGENTS.md`; other work was running on the machine, and no cause was looked for.

`venv/bin/gunicorn --version` printed `gunicorn (version 26.0.0)`.

A gunicorn started on this machine with a stub application whose `/slow` path sleeps two seconds, on `--bind 127.0.0.1:0`: with no other option it logged `Using worker: sync`, a request to `/fast` sent 0.3 seconds after one to `/slow` took 1.71 seconds, and the worker's `/proc/<pid>/status` read `Threads: 1`; with `--workers 1 --threads 4` it logged `Using worker: gthread`, the same `/fast` request took 0.00 seconds, and the worker read `Threads: 3`. gunicorn logs the real port of a `:0` address (`Listening at: http://127.0.0.1:33339`).

The docket application itself, started with `venv/bin/gunicorn 'docket.web:create_app()' --bind 127.0.0.1:5097 --workers 1 --threads 4` against a throwaway database (`tools/test-db`, which holds the migrations' rows and no meetings): 40 requests, eight at a time, to `/al/birmingham/` printed `40 200`, 40 to `/al/mobile/` printed `40 200`, the log held `Using worker: gthread` and no `ERROR` or `Traceback`, and the worker's status read `Threads: 5`. The options were typed by hand; the files were not changed.

Both start lines read with gunicorn's own option parser (`gunicorn.config.Config().parser()`): as they stand, `threads 1 workers 1 SyncWorker`, with `timeout 30` for the `Dockerfile` and `120` for the `Procfile`; with `--workers 1 --threads 4` appended, `threads 4 workers 1 ThreadWorker`. One trap: `gunicorn ... --threads 4 --print-config` prints `worker_class = sync`, the setting as typed, although the class it then loads is the threaded one, so that output is not used as evidence anywhere in this plan.

gunicorn 26 opens a control socket by default (its log says `Control socket listening at /run/user/1000/gunicorn.ctl`); `--no-control-socket` turns it off and the test uses it so that two gunicorns on one machine do not share a path.

`DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_web_start_line.py -q -p no:cacheprovider` was run before the file existed: the database guard did not refuse it and it ended `1 warning in 0.00s` with no test run, so the form of the line is right for this worktree.

A loop that lists gunicorn processes from `/proc` without `ps` (it is given under Validation, the operator's steps) was run on this machine against a local gunicorn and printed each process's command line, `PPid`, `VmRSS` and `Threads`. It has not been run in the production container; no production command was run at authoring.

`gh pr list --state open` printed `[]`: no pull request was open.

### Prose that states the old rule

A search of the tree for `synchronous`, `one request at a time`, `holds that worker`, `--threads` and `--workers` (outside `venv/`) found these, and each is an edit or a leave-alone. `docs/specs/operations.md` line 96 ("one synchronous gunicorn worker ... One request is answered at a time"): edited in M2. `docs/specs/votes.md` line 65 ("Production runs one synchronous gunicorn worker ... a fetch holds that worker while it lasts"): edited in M2. `docs/DEBT.md`, rows `D188` and `D197`: `D197` rewritten and `D188` appended to in M2. `docs/birmingham/07-operations.md` line 9 ("the Procfile runs the migrations, then the server"): that one cell is corrected in M2, since production uses the `Dockerfile`'s line. `docs/specs/operations.md` line 86 (the `Procfile`'s `--timeout 120`): still true, left. `docs/decisions/0134-...md` line 15 ("a web worker that answers one request at a time under gunicorn's 30-second limit"): a dated record, left as written; the new record names it. `plans/completed/minutes-open-at-the-vote-page.md` and three files under `docs/superpowers/reviews/`: history, left. `src/docket/web/source_security.py` line 213 ("a single worker still serves multiple threads") and the module docstring of `src/docket/services/minutes_viewer.py` ("two web processes each have their own"): both already true under threads, left. `src/docket/ai/batch_ingest.py`, `scripts/read_minutes_votes.py` and `docs/runbooks/v3-cutover.md` use the words about other things, left. `ARCHITECTURE.md`, `GOALS.md` and `AGENTS.md` do not mention gunicorn's worker or threads.

### Debt rows and identifiers

`D197` and `D188` are accounted for as the Decision Log says. `D34` (modules that read `os.environ`) and `D7` (web modules that execute SQL) have triggers worded as "the next plan touching each module": this plan reads `src/docket/web/__init__.py` and `src/docket/web/source_security.py` and changes neither, so neither trigger fires, and a session that finds itself editing either file has left this plan. `D205` (no log line for a viewer page past the end of the file; it notes gunicorn has no access log) has the trigger "the next change to the `minutes_page` route", which this plan does not make.

The decision record M2 writes takes the lowest number above every one spent under `docs/decisions/` on `origin/main` and on any open pull request at the moment M2 runs (`D70` in `docs/DEBT.md` says why the rule and not a figure). This plan writes `<NNNN>` for it. No debt id is spent.

No other plan is in flight: `plans/active/` held no file at authoring.

## Plan of Work

### M1. The start lines and their test

Read `Dockerfile`, `Procfile`, and the two unlocked cache functions named in Context, and record in Surprises & Discoveries that the two functions are as Context describes (or that they are not).

Write `tests/unit/test_web_start_line.py` first and run it against the unchanged lines, so the failures are seen. Its module docstring says what it pins and names this plan. It has three helpers and three test functions that collect four tests.

The helpers. `ROOT` is `Path(__file__).resolve().parents[2]`. `start_line(name)` returns the web start line as one string: for `"Dockerfile"`, the last line that begins `CMD `, whose remainder is a JSON array, of which the last element is the line; for `"Procfile"`, the line that begins `web:`, with that prefix removed. `gunicorn_tokens(name)` splits the start line on `&&`, strips each part, takes the one part that begins `gunicorn `, and returns `shlex.split` of it, so that the `Dockerfile`'s single quotes and the `Procfile`'s double quotes around the application both come out as the bare token `docket.web:create_app()`.

`test_start_line_asks_for_one_worker_and_four_threads`, parametrized over `"Dockerfile"` and `"Procfile"` (two tests): in the tokens, `--workers` is followed by `1` and `--threads` by `4`, each flag occurring once and `--worker-class` and `-k` not at all; and gunicorn's own reading agrees, which the test gets by building `gunicorn.config.Config()`, parsing the tokens after the first with `cfg.parser().parse_args(...)`, setting every parsed value that is not `None` (other than `args`) on the config with `cfg.set(name.lower(), value)`, and asserting `cfg.threads == 4`, `cfg.workers == 1` and `cfg.worker_class is gunicorn.workers.gthread.ThreadWorker`. Fails today on both files.

`test_both_start_lines_run_the_migrations_then_the_same_application` (one test): for each file, the part of the start line before the first `&&` is `python -m docket.migrations.runner`; the tokens begin `gunicorn`, `docket.web:create_app()`; and `--bind` is followed by `0.0.0.0:${PORT:-5000}`. Passes today; it is there so that a change to either file that breaks the helpers' reading fails by name.

`test_the_dockerfile_options_answer_a_second_request_while_one_is_held` (one test): writes `stubapp.py` into `tmp_path`, a WSGI callable `app` that sleeps 3 seconds when `PATH_INFO` is `/slow` and answers `200` with body `ok` for every path. Takes the `Dockerfile`'s tokens, removes `gunicorn`, the application token and `--bind` with its value, and runs `[sys.executable, "-m", "gunicorn", "stubapp:app", *the remaining options, "--bind", "127.0.0.1:0", "--chdir", str(tmp_path), "--no-control-socket", "--error-logfile", str(tmp_path / "gunicorn.log")]` as a subprocess whose environment is the test's with `WEB_CONCURRENCY` and `GUNICORN_CMD_ARGS` removed. It polls the log file, for at most 20 seconds, for `Listening at: http://127.0.0.1:<port>` and `Booting worker with pid`, and fails with the log's text if they do not come. It then starts a thread that requests `/slow` with `urllib.request` and notes when it finished, waits half a second, requests `/fast` with a 10-second timeout and notes when that finished, joins the thread, and asserts that `/fast` finished at least one second before `/slow` did. The comparison is of two finishing times and not of one duration against a threshold, so a loaded machine does not make it flaky: under the `sync` worker `/fast` cannot finish before `/slow`, and under threads it finishes about two and a half seconds before. In a `finally`, the subprocess is terminated, waited for 10 seconds, and killed if still alive. No request leaves the machine. Fails today.

Run the file and record the result (expected: 3 failed, 1 passed). Commit the test with the plan (every commit in a milestone session changes the plan file).

Then change the two lines, and nothing else in either file. In `Dockerfile`, the `CMD` line ends `--bind 0.0.0.0:${PORT:-5000} --workers 1 --threads 4"]`. In `Procfile`, the `web:` line ends `--bind 0.0.0.0:${PORT:-5000} --workers 1 --threads 4 --timeout 120`. The comment above the `Dockerfile`'s `CMD` (`# Run migrations then start gunicorn`) may gain the words "one worker, four threads (docs/specs/operations.md)"; nothing else moves.

Run the file again (expected: 4 passed). Then run the docket application once under the changed line, by hand, as Concrete Steps gives it, and record what printed. Then `./tools/verify`.

### M2. The documents

All of M2 is prose; no file under `src/`, `tests/`, `Dockerfile` or `Procfile` changes. The texts below are what to write; a session may mend a word but not a claim, and a claim it finds untrue against the tree is a Surprises entry.

`docs/specs/operations.md`, Railway specifics: replace the paragraph that begins "The web service in production is one synchronous gunicorn worker" with this, the loop as an indented block the way the file's other commands are:

    The web service is started by the `Dockerfile`'s line (`python -m docket.migrations.runner && gunicorn 'docket.web:create_app()' --bind ... --workers 1 --threads 4`) and not the `Procfile`'s, which asks for the same worker and threads and adds `--timeout 120`; `tests/unit/test_web_start_line.py` pins both. That is one gunicorn worker process whose four threads answer up to four requests at once: with `--threads` above one gunicorn uses its threaded worker, and its start-up log says `Using worker: gthread`. `--workers 1` is written out because gunicorn otherwise takes the count from a `WEB_CONCURRENCY` variable, and a second process would keep its own copy of everything the minutes page viewer holds in memory (decision `<NNNN>`). The `Dockerfile`'s line has no `--timeout`, so gunicorn's 30 seconds applies, and under the threaded worker it is not a limit on one request: gunicorn restarts a worker whose main loop stops reporting, and a request that is slow inside a thread is ended only by the code's own bounds (the minutes page viewer's are in `docs/specs/votes.md`).

    To read it in the container, which has no `ps`: `railway ssh --service docket-web`, then

        for f in $(grep -l gunicorn /proc/[0-9]*/cmdline 2>/dev/null); do d=${f%/cmdline}; echo "$d: $(tr '\0' ' ' < $f 2>/dev/null)"; grep -E '^(PPid|Threads|VmRSS)' $d/status 2>/dev/null; done

    The worker is the gunicorn process whose `PPid` is the other gunicorn process. Its command line ends `--workers 1 --threads 4`, and its `Threads:` is 2 or more once it has answered a request and 5 at most (the pool starts a thread when it first needs one). The one reading taken so far, on 2026-11-23, is of the build before this line: one worker with one thread, about 214 MB resident. The reading of the four-thread build after its first deploy is step 8 of `D188` in `docs/DEBT.md`.

The Deploy paragraph above it ("The web service runs the migrations and then gunicorn serving `docket.web:create_app()`; in production the line that starts it is the `Dockerfile`'s, not the `Procfile`'s `web:` line with its `--timeout 120`") stays true and is left.

`docs/specs/votes.md`, The minutes page viewer: replace the paragraph "The cache, the host gap and the failure memory are each web process's own. Production runs one synchronous gunicorn worker ..." with:

    The cache, the host gap and the failure memory are each web process's own. The web service is started as one gunicorn worker with four threads (`docs/specs/operations.md`, Railway specifics; decision `<NNNN>`), so there is one of each, shared by the threads, and a fetch holds one of the four threads while it lasts and not the site: a request for another page is answered by another thread. The start line's timeout does not end a slow request under threads, so the bounds above are what end one: a request that fetches lasts at most about 13 seconds (the host gap and the fetch), and one that first waits for the host behind another file's fetch at most about 26 (`WAIT_S`, then its own). Four such requests at once hold all four threads, and nothing limits how fast one visitor may ask (`D197`).

`docs/decisions/<NNNN>-the-web-service-is-one-gunicorn-worker-with-four-threads.md`, in the four-field format of `docs/decisions/DECISION_FORMAT.md` (`# <NNNN> — The web service is one gunicorn worker with four threads`, then `## Decision`, `## Rationale`, `## Date`, `## Status`). Decision: the web service's start line asks gunicorn for one worker and four threads, in `Dockerfile` and `Procfile` alike; concurrency is added as threads, and a second worker process is not added without first deciding what becomes of the minutes page viewer's in-memory state. Rationale, in a few paragraphs drawn from this plan: the stall `D197` recorded once the viewer (decision `0134`) put a fetch of up to about 13 seconds inside the one worker; why threads and not workers (one cache of up to 40 MB, one host gap that keeps requests to a city a second apart as `GOALS.md` requires, one failure memory, one resident size, where each extra process would have its own of each and two processes could ask one city twice in a second); why four (the operator's figure; the request path was read for state shared between threads and the viewer and every older cache but two take locks, the two being idempotent single assignments); why `--workers 1` is written out (`WEB_CONCURRENCY`); and what the timeout now means. It says what was observed (the test, and M1's hand run of the site under the line) and that production under threads had not been read when the record was written. Date: the day M2 runs, "plan `site-answers-while-a-page-loads`, at the operator's stated goal". Status: accepted.

`docs/DEBT.md`, row `D197`: rewrite in place, same id, one line, five cells. Item: nothing limits how fast one visitor may ask for minutes viewer pages; `robots.txt` and the `noindex` header are advisory; the web service is one gunicorn worker with four threads (decision `<NNNN>`), each viewer request that has to fetch holds a thread for up to about 13 seconds, or about 26 behind another fetch on the same host, so a crawler that ignores `robots.txt` can hold all four threads at once and the site then waits as it did under one worker, and makes docket.pub ask a city for file after file (a second apart for one host); the row's first half, that one slow file held the whole site, was paid by plan `site-answers-while-a-page-loads` on the day M2 runs; four threads may also raise the web service's memory, since up to four fetches of up to 25 MB and four pictures being encoded can be in memory at once beside the 40 MB cache, and nobody has measured it (step 8 of `D188` reads the resident size). Where: `src/docket/services/minutes_viewer.py`; `Dockerfile`, `Procfile`; Cloudflare's dashboard. Why deferred: a rate-limiting rule is the operator's choice in Cloudflare's dashboard, not a factory session's. Trigger: the operator sees the site stall while viewer pages load, or the logs show a crawler on `/al/*/meetings/*/minutes/page/*` despite `robots.txt`, or the reading of step 8 of `D188` shows the resident size well above the 214 MB read before threads; what to weigh then is the rule the second outside review of plan `minutes-open-at-the-vote-page` recommended, 20 to 30 requests a minute from one address on `/al/*/meetings/*/minutes/*` (step 6 of `D188`), and for memory a smaller `CACHE_BYTES`. The word "synchronous" does not appear in the rewritten row.

`docs/DEBT.md`, row `D188`: every cell keeps its present text, whole and first; text is only added at the end of a cell. At the end of the Item cell add: "Plan `site-answers-while-a-page-loads` (2026-11-23) then changed the start line to one worker with four threads before the deploy of step 1 was made, so that one deploy ships the viewer and the threads; the reading above, one synchronous worker, is of the build before it." At the end of the Trigger cell add steps 8 and 9 and the sentence after them, worded as Validation and Acceptance gives them under The operator's steps, ending: "Steps 8 and 9 were added by plan `site-answers-while-a-page-loads`; the row is deleted when steps 2 to 4, 8 and 9 are as expected, and what step 8 printed is written into `docs/specs/operations.md`, Railway specifics, in place of the reading of 2026-11-23."

`docs/birmingham/07-operations.md`, the table's first row, third cell: "the Procfile runs the migrations, then the server" becomes "the `Dockerfile`'s start line runs the migrations, then the server (`docs/specs/operations.md`, Railway specifics)". Nothing else in that file changes.

Then `./tools/verify`. M2 does not move this plan to `plans/completed/` and does not write the closing retrospective; the factory's retro stage does both.

## Concrete Steps

Every session: from the worktree root, `./tools/verify` first and last, and record the final line and the tier totals each time.

M1, the test file alone:

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_web_start_line.py -q -p no:cacheprovider; tools/test-db --drop

Expected before the two lines change: `3 failed, 1 passed`. Expected after: `4 passed`.

M1, the docket application under the changed line, by hand. The options are read from the file, not typed, so the run is of the line as committed:

    T=$(mktemp -d)
    export DATABASE_URL=$(tools/test-db)
    OPTS=$(venv/bin/python -c "import json,shlex;l=[x for x in open('Dockerfile').read().splitlines() if x.startswith('CMD ')][-1];t=shlex.split(json.loads(l[4:])[-1].split('&&')[1]);i=t.index('--bind');print(' '.join(t[2:i]+t[i+2:]))")
    echo "$OPTS"
    venv/bin/gunicorn 'docket.web:create_app()' --bind 127.0.0.1:5097 $OPTS --pid $T/gunicorn.pid --daemon --error-logfile $T/gunicorn.log
    sleep 4
    seq 1 40 | xargs -P 8 -I{} curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5097/al/birmingham/ | sort | uniq -c
    seq 1 40 | xargs -P 8 -I{} curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5097/al/mobile/ | sort | uniq -c
    W=$(pgrep -P $(cat $T/gunicorn.pid)); grep Threads /proc/$W/status; tr '\0' ' ' < /proc/$W/cmdline; echo
    kill $(cat $T/gunicorn.pid); sleep 2
    grep -E "Using worker|ERROR|Traceback" $T/gunicorn.log
    tools/test-db --drop; rm -rf $T

Expected: `echo "$OPTS"` prints `--workers 1 --threads 4`; each `uniq -c` prints `40 200`; `Threads:` is between 2 and 5; the command line shows `--workers 1 --threads 4`; the last `grep` prints one line, `Using worker: gthread`. At authoring the same sequence, with the options typed by hand in place of `$OPTS`, printed `40 200` twice, `Threads: 5` and that one log line; the `OPTS` line was run by itself and printed an empty line on today's `Dockerfile` and `--workers 1 --threads 4` on a copy of it with the two flags added. Do not stop the server with `pkill -f`: it matches the shell that runs it. If port 5097 is taken, use another.

M2, the checks under Validation and Acceptance, then `./tools/verify`.

## Validation and Acceptance

### M1

One: with the test file committed and the two lines unchanged, the test-file command above prints `3 failed, 1 passed`, the failures being the two parametrized cases of `test_start_line_asks_for_one_worker_and_four_threads` and `test_the_dockerfile_options_answer_a_second_request_while_one_is_held`. After the two lines change it prints `4 passed`.

Two: `git diff --numstat $(git merge-base HEAD origin/main) -- Dockerfile Procfile` prints `1 1 Procfile` and either `1 1 Dockerfile` or, if the comment above `CMD` was also reworded, `2 2 Dockerfile`.

Three: the hand run of the docket application in Concrete Steps prints what is expected there, and the session records the lines it printed.

Four: `./tools/verify` exits 0 with every check `ok`, and the unit, web and services line reads four more passed than the session's opening run of it did, with the same skipped and xfailed (at authoring the opening figure was `3787 passed, 5 skipped, 4 xfailed`, so `3791 passed`; if `origin/main` has moved, the opening run's own figure is the baseline).

### M2

One: `grep -n "synchronous" docs/specs/operations.md docs/specs/votes.md` prints nothing (at authoring it printed one line from each), and `grep -c -e "--workers 1 --threads 4" docs/specs/operations.md` prints at least `1`.

Two: `ls docs/decisions | grep -c "the-web-service-is-one-gunicorn-worker-with-four-threads"` prints `1`; the file has the four fields of `docs/decisions/DECISION_FORMAT.md`; its number is used by no other file under `docs/decisions/`; and `grep -c "<NNNN>" docs/specs/operations.md docs/specs/votes.md docs/DEBT.md` prints `0` for each, the placeholder having been replaced by the number everywhere.

Three: `git diff --numstat $(git merge-base HEAD origin/main) -- docs/DEBT.md` prints `2 2 docs/DEBT.md` (two rows, each one line, changed in place); `grep -c '^| D197 ' docs/DEBT.md` prints `1` and `grep '^| D197 ' docs/DEBT.md | grep -c synchronous` prints `0`; and this prints `5 5 True`, which says every cell of the `D188` row begins with the whole of its text on the base:

    venv/bin/python - <<'EOF'
    import subprocess
    run = lambda *a: subprocess.run(a, capture_output=True, text=True).stdout
    base = run("git", "merge-base", "HEAD", "origin/main").strip()
    row = lambda text: [l for l in text.splitlines() if l.startswith("| D188 ")][0].strip().strip("|").split(" | ")
    old, new = row(run("git", "show", f"{base}:docs/DEBT.md")), row(open("docs/DEBT.md").read())
    print(len(old), len(new), all(b.strip().startswith(a.strip()) for a, b in zip(old, new)))
    EOF

At authoring, on the unchanged row, it printed `5 5 True`, and each of the two rows held six `|` characters, so neither has a `|` inside a cell; the text M2 adds to either row must not contain the character `|`, which is why step 8 on the row points to the loop in `docs/specs/operations.md` and does not quote it. The `D188` row also holds the words `(8)` and `(9)`.

Four: `git diff --stat $(git merge-base HEAD origin/main) -- docs/birmingham/07-operations.md` shows one line changed, and `git diff --name-only $(git merge-base HEAD origin/main)` lists nothing under `src/` and, under `tests/`, only `tests/unit/test_web_start_line.py`.

Five: `./tools/verify` exits 0 with every check `ok` and the same test totals as the session's opening run.

### The operator's steps, after the pull request merges

These are not a clause of any milestone. They are steps 8 and 9 that M2 appends to `D188`, after that row's own steps 1 to 7, which stand as written; step 1 there is the one deploy (`scripts/deploy.sh --service docket-web`, on the Legion, in the WSL terminal, in the main checkout of docket-pub and not a worktree, on a clean `main` that holds both merges). None of the commands below was run against production at authoring; the loop of step 8 was run on the authoring machine against a local gunicorn.

Step 8. On the Legion, in the WSL terminal, in the main checkout: `railway ssh --service docket-web`, and in the shell that opens, paste the loop that `docs/specs/operations.md`, Railway specifics, gives (it is quoted in M2's text above). Expected: two gunicorn processes; the one whose `PPid` is the other is the worker; both command lines end `--workers 1 --threads 4`; the worker's `Threads:` is 2 or more after the site has answered a few requests, 5 at most. Note the worker's `VmRSS` beside the 214 MB read before threads. Write what printed into `docs/specs/operations.md` in place of the reading of 2026-11-23. If the command line lacks the flags, the deploy was not of the merged `main`; `railway ssh --service docket-web "cat /app/COMMIT_SHA"` says which commit is running.

Step 9. On the Legion, in the WSL terminal, in any folder, as soon after the deploy as steps 1 and 8 allow and before step 2's click (a deploy empties the viewer's cache, and the first open of a meeting's minutes is the only one that fetches):

    curl -s -o /dev/null -w 'viewer %{http_code} %{time_total}\n' https://docket.pub/al/mobile/meetings/1071/minutes/page/5/ & sleep 0.2; curl -s -o /dev/null -w 'city %{http_code} %{time_total}\n' https://docket.pub/al/mobile/; wait

Expected: two lines, both `200`, and the `city` line's time is what `/al/mobile/` takes alone (run the second `curl` by itself to compare), not that time plus the rest of the viewer's. Mobile answered the viewer's fetch in 0.63 seconds from inside the container on 2026-11-23, so the difference is small when the city is quick; the thread count of step 8 is the firm evidence and this is the look at it working. If Cloudflare answers `curl` with a challenge and not the page, do the same with two tabs of the Windows browser and say so on the row.

## Idempotence and Recovery

Every step can be repeated. The test starts its gunicorn on a port the system picks and stops it in a `finally`; a run killed midway can leave a `gunicorn` process serving `stubapp:app`, which `pgrep -af stubapp` finds and `kill` ends. The hand run uses a pid file under a temporary directory; if the session loses it, `pgrep -af "127.0.0.1:5097"` finds the server (kill the pid it prints, not with `pkill -f`). `tools/test-db --drop` is safe to run when no database exists. If `./tools/verify` is running, do not start the hand run until it ends: both use the one throwaway database named for the worktree.

Rollback of the change is the two lines without the two flags. In production it is a deploy of a `main` with that revert, by the operator; there is no migration and no stored state to undo, and the viewer works under either line.

If the behavioural test proves flaky under `./tools/verify` (a `/fast` that does not answer within its 10 seconds on a loaded machine), record the failure text in Surprises & Discoveries and raise the sleep of `/slow` and the timeout together; do not weaken the comparison to a duration threshold and do not mark the test skipped.

## Artifacts and Notes

The lines as they should read when M1 is done:

    CMD ["sh", "-c", "python -m docket.migrations.runner && gunicorn 'docket.web:create_app()' --bind 0.0.0.0:${PORT:-5000} --workers 1 --threads 4"]

    web: python -m docket.migrations.runner && gunicorn "docket.web:create_app()" --bind 0.0.0.0:${PORT:-5000} --workers 1 --threads 4 --timeout 120

The prototype at authoring, a stub application under a local gunicorn (options typed by hand):

    []                            Using worker: sync     /fast took 1.71s  Threads: 1
    --workers 1 --threads 4       Using worker: gthread  /fast took 0.00s  Threads: 3

## Interfaces and Dependencies

No library is added or changed: gunicorn 26.0.0 is already pinned in `requirements.lock`, and its threaded worker needs nothing further. No application code changes. The test uses only the standard library (`json`, `shlex`, `subprocess`, `sys`, `threading`, `time`, `urllib.request`, `pathlib`), `pytest`, and `gunicorn.config.Config` and `gunicorn.workers.gthread.ThreadWorker` from the installed gunicorn.

At the end of M1 these exist: in `tests/unit/test_web_start_line.py`, the helpers `start_line(name: str) -> str` and `gunicorn_tokens(name: str) -> list[str]` and the three test functions named in Plan of Work; in `Dockerfile` and `Procfile`, the two lines under Artifacts and Notes. At the end of M2 these exist: the two spec paragraphs, the decision record `docs/decisions/<NNNN>-the-web-service-is-one-gunicorn-worker-with-four-threads.md` with its number in place of every `<NNNN>` written into the tree, the rewritten `D197` row, the `D188` row with its additions, and the corrected cell of `docs/birmingham/07-operations.md`.

## Revision note

2026-11-23, authored. Written from the operator's goal (run the web service with four gunicorn threads, against `origin/main` at `97765fe` with pull request 197 merged and not deployed, so one deploy ships the viewer and the threads) and a scope brief by a read-only agent, folded into Purpose and Context above. Deliberately left out: the deploy itself and the readings in the container and browser, which are the operator's and are written as steps 8 and 9 of `D188`; a Cloudflare rate-limiting rule on `/al/*/meetings/*/minutes/*`, the operator's choice and the open half of `D197`; more worker processes; changing or unifying the timeout (`--timeout 120` in the `Procfile`, none in the `Dockerfile`); removing the `Procfile`'s web line or settling which file Railway reads beyond what `docs/specs/operations.md` already says; a gunicorn access log (`D205`); locks on `neighborhood_schedule._cache` and `briefing._provenance_cache`; `D34` and `D7`, whose files are read and not changed; any rewording of decision `0134` or of `plans/completed/minutes-open-at-the-vote-page.md`; anything in `docs/birmingham/07-operations.md` beyond the one stale cell; and a measurement of the web service's memory under four threads, which only production can give and which step 8 reads. The brief's reading that "four threads" leaves the worker count unstated was changed to an explicit `--workers 1`, for the reason the first Decision Log entry gives. No open GitHub issue concerns the web server's concurrency (the brief's reading with the `gh` CLI; the GitHub MCP server did not connect in the authoring session either).
