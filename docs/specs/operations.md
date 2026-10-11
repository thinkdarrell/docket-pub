# Operations

How docket.pub is run today: environments, tests, deploys, Railway, the domain, and the transcriber. Present tense. The cron schedule itself is the code in `src/docket/worker/scheduler.py`; this file does not restate it.

## Local environment

Python 3.10 is required; `requirements.lock` is compiled for it and the Dockerfile and Railway use it.

    python3.10 -m venv venv
    venv/bin/pip install -e ".[dev]"       # reads requirements.lock via pyproject, deterministic
    cp .env.example .env

Each git worktree needs its own `venv/`. The editable install pins the `docket` package to the checkout it was installed from, so a worktree that borrows the main checkout's venv tests the main checkout's code.

`requirements.txt` holds the top-level dependencies with loose ranges; `requirements.lock` is the pinned tree. The Dockerfile and `pyproject.toml` both read the lock, so local, CI, and Railway resolve the same versions. When a dependency changes, edit `requirements.txt` and regenerate the lock in the same commit:

    uv pip compile requirements.txt --python-version 3.10 -o requirements.lock

Migrations and the dev server:

    venv/bin/python -m docket.migrations.runner            # apply pending
    venv/bin/python -m docket.migrations.runner --status
    venv/bin/python -m docket.migrations.runner --down <version>   # rolls back migration number <version>

`--down` takes a migration number, not a count: `--down 35` rolls back 035, and `--down 1` runs 001's down SQL, which drops the whole schema.
    venv/bin/flask run

Docker is an alternative for the database and app together: `docker-compose up -d`.

Local PostgreSQL without Docker is version 16 from Homebrew:

    /opt/homebrew/opt/postgresql@16/bin/pg_ctl -D /opt/homebrew/var/postgresql@16 start
    /opt/homebrew/opt/postgresql@16/bin/pg_ctl -D /opt/homebrew/var/postgresql@16 stop
    /opt/homebrew/opt/postgresql@16/bin/createuser -s docket      # first time only
    /opt/homebrew/opt/postgresql@16/bin/createdb -O docket docket_db

Then `DATABASE_URL=postgresql://docket@localhost:5432/docket_db` in `.env`.

## Tests

One command runs everything that does not call Anthropic:

    ./tools/verify

Its wall time and budget are stated once, in `AGENTS.md` Commands; it exits zero only when every check passed. It first runs `tools/test-db`, which builds a disposable database on the server that `DATABASE_URL` names (the `.env` value when the variable is unset in the shell) by applying every migration, in under a second. The database is named `docket_test_<hash>`, where `<hash>` is the first eight hex characters of the SHA-1 of the checkout's absolute path, so two checkouts never share one and the name is the same from any directory inside a checkout; `tools/test-db --drop` removes it. With `DATABASE_URL` exported at that database, verify runs the fast tiers (`tests/unit`, `tests/web`, `tests/services`), the integration tier (`tests/integration`), and the milestone judge's fixture self-test (`tools/fixtures/judge/run`), prints one `verify: <name> ... ok (Ns)` or `verify: <name> ... FAILED (Ns)` line per check with each failing check's own output above the summary, ends with `verify: all M checks passed in Ss.` or `verify: N of M checks failed in Ss.` followed by one indented command per failing check that re-runs it alone on a disposable database, and drops the database on every exit path. Every check runs even when an earlier one fails; the one exception is a failed database build, after which no tier runs and verify exits 1, because without the exported URL the unit tier would delete rows from `docket_db` (`D37`).

A stale developer `docket_db` is no longer what the tests run against: `./tools/verify` neither reads nor changes it, so drift in it cannot make the suite red, and the suite's own leftovers (the rows and the materialised-view drift that `D37` and `D38` describe) vanish with the disposable database. Expected on a fresh database: the fast tiers report `5 skipped`, four in `tests/web/test_p5_translation.py`, whose data-dependent cases skip when no meetings, tagged items, search hits, or coverage rows exist, and one in `tests/web/test_city_overview_render.py`, which skips when there is no Birmingham meeting to render; that is expected, not a failure (`D41`). Tests that insert rows own their cleanup, the migration tests apply and roll back real migrations against the disposable database, and the integration tier keeps pytest's default file order (`D38` says why).

To run one tier by hand on a disposable database: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration -q -p no:cacheprovider`, then `tools/test-db --drop`. `tools/test-db` writes its progress and the migration runner's output to stderr and the URL alone to stdout, which is what makes the `$(...)` form work. It refuses, with exit 2 and one line on stderr before it touches the server, a `DATABASE_URL` that names no database after the host and any argument other than `--drop`; if the migration run fails it drops the database it was building.

Live tests make real Anthropic calls and need a real `ANTHROPIC_API_KEY`: `venv/bin/python -m pytest -m live`. Bare `pytest` no longer collects them, because `pyproject.toml` sets `addopts = "-m 'not live'"` and an explicit `-m live` replaces that expression.

The milestone judge, `tools/judge-milestone`, decides from a plan file and the git history alone whether a session advanced exactly one milestone; `AGENTS.md` Commands says how it is run, its contract is `docs/capabilities/judge-milestone.md`, and its twelve-case self-test is verify's third check.

## Deploying

A human deploys, from a clean `main` after the pull request has merged:

    git checkout main && git pull
    scripts/deploy.sh --service docket-web
    scripts/deploy.sh --service worker

The wrapper writes the current HEAD SHA to `./COMMIT_SHA` (gitignored) before invoking `railway up --detach`, and the Dockerfile moves it to `/app/COMMIT_SHA`. To see which commit a service is running:

    railway ssh --service docket-web "cat /app/COMMIT_SHA"
    railway ssh --service worker     "cat /app/COMMIT_SHA"

A bare `railway up` still works but records the literal string `unknown`, because the Railway CLI strips `.git` from uploads. Deploying only from a clean `main` is a constraint in `GOALS.md`, and decision `0022` records why. Never use `railway redeploy`; it restarts the old build without new code.

The `web:` process runs the migrations and then gunicorn serving `docket.web:create_app()` (see `Procfile`). The worker is a separate Railway service with a custom start command; decision `0023` says why, and `scripts/deploy.sh --service worker` redeploys it.

## Railway specifics

`railway run <cmd>` executes locally with Railway's variables injected, and the injected `DATABASE_URL` points at `postgres.railway.internal`, which resolves only inside Railway's network. `railway ssh --service <name> "<cmd>"` executes inside the container. For anything that touches the production database from a laptop, use `DATABASE_PUBLIC_URL`:

    DATABASE_URL=$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-) \
    ANTHROPIC_API_KEY=$(railway variables --service docket-web --kv | grep '^ANTHROPIC_API_KEY=' | cut -d= -f2-) \
    venv/bin/python -m docket.ai.cli --status

Manual worker tasks run inside the container: `railway ssh --service worker` then `python -m docket.worker.scheduler --run-once <task>`. A long `railway ssh "<cmd>"` can return before the remote command finishes; poll the relevant table rather than chaining commands.

Dumps and restores from a laptop use the postgresql@18 binaries (`/opt/homebrew/opt/postgresql@18/bin/pg_dump`, `psql`); the version 16 binaries refuse with a server version mismatch. The version gap is a constraint in `GOALS.md`.

The worker's memory ceiling and the ban on a second heavy Python process are constraints in `GOALS.md`; `railway ssh --run-once <heavy task>` starts exactly such a process and has caused out-of-memory kills. If headroom shrinks, the options are a larger tier, `LIMIT 1` per OCR tick, or a separate OCR service.

Feature flags in production: `IMPACT_FIRST_ENABLED=true` on `worker` (the v3 pipeline writes) and `SMART_BREVITY_UI=true` on `docket-web` (citizen rendering of v3 cards) are on. `MINUTES_VS_VIDEO_UI` on `docket-web` stays unset until the transcript ship gate on `/admin/ai` reads "met" (decision `0032`). `TRANSCRIPT_PER_TICK` (default 5) bounds the worker's transcript stage advances per tick. Flags are read in `src/docket/config.py` and `src/docket/web/__init__.py`; Railway holds the values.

Backfills run from a laptop against `DATABASE_PUBLIC_URL`. The archived 2023 Birmingham meetings come from `scripts/backfill_archived_meetings.py --manifest scripts/manifests/birmingham_2023_archived.json`, which caches agenda PDFs on disk and paces Wayback requests; no minutes exist online for those meetings, so they carry agendas and video only.

Bulk changes on production are one targeted SQL statement. The volume size is a constraint in `GOALS.md`; the incident behind the rule is decision `0026`.

A second Postgres service named `Postgres-pKpA` exists in the Railway project with no known use; it is `D32` in `docs/DEBT.md`.

## Domain and headers

The apex `docket.pub` is on Railway with a Let's Encrypt certificate it provisions itself. DNS at Namecheap: `CNAME @` to `zu815cqb.up.railway.app` plus a `TXT _railway-verify` record. `www.docket.pub` is a Namecheap URL redirect over HTTP only; moving it to Railway is `D10`.

`src/docket/web/__init__.py` sends `Strict-Transport-Security: max-age=31536000` in an `after_request` hook when `FLASK_ENV` is not `development`, without `includeSubDomains`; decision `0025` says why and `D10` tracks the change.

## Transcriber

The desktop producer on the Legion is the Transcriber component in `ARCHITECTURE.md`; it connects as the `transcriber` database role, created once by `scripts/sql/create_transcriber_role.sql` (decision `0030`). Rotate it with `ALTER ROLE transcriber PASSWORD '...'` and update the transcriber's .env file on the Legion (not in this repository). Uploads are public on arrival. Operating notes, expected oddities (stray Monday Granicus clips, over-split speakers), and the bring-up log are in `transcriber/README.md`; the runbook is `docs/runbooks/transcripts.md`.

## Runbooks

- `docs/runbooks/cron-worker.md`: Healthchecks.io setup, `--run-once` verification, alert response, the backfill.
- `docs/runbooks/analytics.md` and `docs/analytics-queries.md`: Umami views and common queries. Query only the `v_*` views; see decision `0024`.
- `docs/runbooks/transcripts.md`: the transcript pipeline end to end, the Legion producer, worker environment, review queue, ship gate, A/B. `docs/runbooks/transcripts-pipeline-map.md`: the stage map for review.
- `docs/runbooks/v3-cutover.md` and `docs/runbooks/smart-brevity-ui-flip.md`: the Impact-First cutover procedures.
- `docs/SECURITY_CHECKLIST.md`: pre-launch requirements.
