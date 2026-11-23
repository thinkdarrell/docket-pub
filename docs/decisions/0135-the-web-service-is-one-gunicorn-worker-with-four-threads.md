# 0135 — The web service is one gunicorn worker with four threads

## Decision

The web service's start line asks gunicorn for one worker and four threads (`--workers 1 --threads 4`), in `Dockerfile` and `Procfile` alike, and `tests/unit/test_web_start_line.py` holds both lines to it. Concurrency is added as threads; a second worker process is not added without first deciding what becomes of the minutes page viewer's in-memory state.

## Rationale

The minutes page viewer (decision `0134`) put a fetch of a city's file inside the web process: a request that has to fetch can last about 13 seconds. The service was then one synchronous worker, which answers one request and only then takes the next, so one slow city file held every reader on every page; `D197` in `docs/DEBT.md` recorded it and named threads as the remedy to weigh.

Threads and not more workers, because everything the viewer keeps is in the process's memory and is correct only while there is one process: one cache of city files of up to 40 MB (`CACHE_BYTES`), one host gap that keeps docket.pub's requests to a city at least a second apart as `GOALS.md` requires, one memory of a host that just failed, and one resident size (about 214 MB before the viewer). Each extra process would have its own of each, and two processes could ask one city twice within a second. Four is the operator's figure. Before choosing it the request path was read for state that threads would share: the viewer and `pdf_page` were written and tested for threads, every older in-process cache on the request path takes a lock, and the three that take none (`neighborhood_schedule._cache`, `briefing._provenance_cache`, `_static_versions` in `create_app`) are each one dictionary read and one assignment of a value any thread computes identically, so the worst case is a duplicated load and no lock was added on assumption. `docket.db.db()` opens a connection per call and shares none.

`--workers 1` is written out because gunicorn otherwise takes its worker count from a `WEB_CONCURRENCY` variable when one is set; writing it makes the one process a property of the line that a test can read. With `--threads` above one gunicorn uses its threaded worker (`gthread`), and under it the timeout stops being a limit on one request: the worker's main loop reports to gunicorn's parent whatever its threads are doing, so the parent restarts a worker whose loop stops and does not end a slow request. The site's database calls had no bound of their own (`src/docket/db.py` connects with the address and nothing else), so the line gives the web process two through gunicorn's `--env`: `PGOPTIONS=-c statement_timeout=30000`, the 30 seconds gunicorn's timeout used to give every request, and `PGCONNECT_TIMEOUT=10`. They are on gunicorn's own command, and not a `connect` argument in `src/docket/db.py` or an `ENV` line in the `Dockerfile`, because the worker service shares the image and the module and runs long statements, and the migrations run before gunicorn on the same line; `--env` limits the web process alone. `exec` is there so that gunicorn replaces the shell as the container's first process and Railway's stop signal reaches it. `MALLOC_ARENA_MAX=2`, which an outside review proposed for memory, was measured and not set: four threads each drawing 60 pages, three rounds, read 146, 146 and 147 MB resident as is and 124, 175 and 155 MB with the variable.

What was observed when this was written: on the old lines the test failed four of its five cases and on the new it passes five, one of them starting a real gunicorn with the `Dockerfile`'s options and seeing a second request answered while a first is held; each of 22 single changes to the two lines failed a test; and the docket application under the committed options, against a throwaway database, answered 80 of 80 requests with five threads in its one worker and `Using worker: gthread` in its log. Production under threads had not been read: the deploy and the readings in the container are the operator's (`D206`), and what is still open under threads, that one visitor can hold all four with viewer requests, is `D197`.

## Date

2026-11-23, plan `site-answers-while-a-page-loads`, at the operator's stated goal.

## Status

accepted
