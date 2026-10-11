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

Three tiers.

- Unit, web, and services: `venv/bin/python -m pytest tests/unit tests/web tests/services -q`. About 70 seconds. Needs no database beyond what `tests/conftest.py` sets (a dummy `ANTHROPIC_API_KEY`, `PGTZ=UTC`, `TZ=UTC`). Five tests fail on `main` as of 2026-10-11; they are `D1` in `docs/DEBT.md`.
- Full (unit, web, services, integration): `venv/bin/python -m pytest tests/unit tests/web tests/services tests/integration -q`. About 105 seconds. Needs local Postgres with `docket_db` migrated. There is no global rollback; tests that insert rows own their cleanup, and the migration tests apply and roll back real migrations against that database. Three integration tests fail on `main` as of 2026-10-11; they are `D2`. The shared-database shape is `D3`.
- Live: `venv/bin/python -m pytest -m live`. Opt in only. Makes real Anthropic calls and needs a real `ANTHROPIC_API_KEY`.

Never run bare `pytest`: `pyproject.toml` sets no `addopts`, so it also collects `tests/live/`, whose fixtures skip only when no key is set, and `tests/conftest.py` sets a dummy key. Tracked as `D35`.

## Deploying

A human deploys, from a clean `main` after the pull request has merged:

    git checkout main && git pull
    scripts/deploy.sh --service docket-web
    scripts/deploy.sh --service worker

The wrapper writes the current HEAD SHA to `./COMMIT_SHA` (gitignored) before invoking `railway up --detach`, and the Dockerfile moves it to `/app/COMMIT_SHA`. To see which commit a service is running:

    railway ssh --service docket-web "cat /app/COMMIT_SHA"
    railway ssh --service worker     "cat /app/COMMIT_SHA"

A bare `railway up` still works but records the literal string `unknown`, because the Railway CLI strips `.git` from uploads. `railway up` deploys whatever is in the local working tree regardless of branch, which is why deploys happen only from `main`. Never use `railway redeploy`; it restarts the old build without new code.

The `web:` process runs the migrations and then gunicorn serving `docket.web:create_app()` (see `Procfile`). The worker is a separate Railway service with a custom start command; decision `0023` says why, and `scripts/deploy.sh --service worker` redeploys it.

## Railway specifics

`railway run <cmd>` executes locally with Railway's variables injected, and the injected `DATABASE_URL` points at `postgres.railway.internal`, which resolves only inside Railway's network. `railway ssh --service <name> "<cmd>"` executes inside the container. For anything that touches the production database from a laptop, use `DATABASE_PUBLIC_URL`:

    DATABASE_URL=$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-) \
    ANTHROPIC_API_KEY=$(railway variables --service docket-web --kv | grep '^ANTHROPIC_API_KEY=' | cut -d= -f2-) \
    venv/bin/python -m docket.ai.cli --status

Manual worker tasks run inside the container: `railway ssh --service worker` then `python -m docket.worker.scheduler --run-once <task>`. A long `railway ssh "<cmd>"` can return before the remote command finishes; poll the relevant table rather than chaining commands.

Dumps and restores from a laptop use the postgresql@18 binaries (`/opt/homebrew/opt/postgresql@18/bin/pg_dump`, `psql`); the version 16 binaries refuse with a server version mismatch. The version gap is a constraint in `GOALS.md`.

The worker's memory ceiling is a constraint in `GOALS.md`. Never start a second heavy Python process on the worker (`railway ssh --run-once <heavy task>` has caused out-of-memory kills). If headroom shrinks, the options are a larger tier, `LIMIT 1` per OCR tick, or a separate OCR service.

Feature flags in production: `IMPACT_FIRST_ENABLED=true` on `worker` (the v3 pipeline writes) and `SMART_BREVITY_UI=true` on `docket-web` (citizen rendering of v3 cards) are on. `MINUTES_VS_VIDEO_UI` on `docket-web` stays unset until the transcript ship gate on `/admin/ai` reads "met" (decision `0032`). `TRANSCRIPT_PER_TICK` (default 5) bounds the worker's transcript stage advances per tick. Flags are read in `src/docket/config.py` and `src/docket/web/__init__.py`; Railway holds the values.

Backfills run from a laptop against `DATABASE_PUBLIC_URL`. The archived 2023 Birmingham meetings come from `scripts/backfill_archived_meetings.py --manifest scripts/manifests/birmingham_2023_archived.json`, which caches agenda PDFs on disk and paces Wayback requests; no minutes exist online for those meetings, so they carry agendas and video only.

Bulk changes on production are one targeted SQL statement. The volume size is a constraint in `GOALS.md`; the incident behind the rule is decision `0026`.

A second Postgres service named `Postgres-pKpA` exists in the Railway project with no known use; it is `D32` in `docs/DEBT.md`.

## Domain and headers

The apex `docket.pub` is on Railway with a Let's Encrypt certificate it provisions itself. DNS at Namecheap: `CNAME @` to `zu815cqb.up.railway.app` plus a `TXT _railway-verify` record. `www.docket.pub` is a Namecheap URL redirect over HTTP only; moving it to Railway is `D10`.

`src/docket/web/__init__.py` sends `Strict-Transport-Security: max-age=31536000` in an `after_request` hook when `FLASK_ENV` is not `development`, without `includeSubDomains`; decision `0025` says why and `D10` tracks the change.

## Transcriber

The desktop producer on the Legion transcribes council video and uploads through the `transcriber` database role, created once by `scripts/sql/create_transcriber_role.sql` and limited to the transcript tables and its heartbeat (decision `0030`). Rotate it with `ALTER ROLE transcriber PASSWORD '...'` and update the transcriber's .env file on the Legion (not in this repository). Uploads are public on arrival. Operating notes, expected oddities (stray Monday Granicus clips, over-split speakers), and the bring-up log are in `transcriber/README.md`; the runbook is `docs/runbooks/transcripts.md`.

## Runbooks

- `docs/runbooks/cron-worker.md`: Healthchecks.io setup, `--run-once` verification, alert response, the backfill.
- `docs/runbooks/analytics.md` and `docs/analytics-queries.md`: Umami views and common queries. Query only the `v_*` views; see decision `0024`.
- `docs/runbooks/transcripts.md`: the transcript pipeline end to end, the Legion producer, worker environment, review queue, ship gate, A/B. `docs/runbooks/transcripts-pipeline-map.md`: the stage map for review.
- `docs/runbooks/v3-cutover.md` and `docs/runbooks/smart-brevity-ui-flip.md`: the Impact-First cutover procedures.
- `docs/SECURITY_CHECKLIST.md`: pre-launch requirements.
