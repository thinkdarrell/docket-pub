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
    venv/bin/python -m docket.migrations.runner --down 1   # roll back the latest one
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
- Integration: `venv/bin/python -m pytest tests/integration -q`. About 50 seconds. Needs local Postgres with `docket_db` migrated. There is no global rollback; tests that insert rows own their cleanup, and the migration tests apply and roll back real migrations against that database. One test fails on `main`; it is `D2`. The shared-database shape is `D3`.
- Live: `venv/bin/python -m pytest -m live`. Opt in only. Makes real Anthropic calls and needs a real `ANTHROPIC_API_KEY`.

## Deploying

A human deploys, from a clean `main` after the pull request has merged:

    git checkout main && git pull
    scripts/deploy.sh --service docket-web
    scripts/deploy.sh --service worker

The wrapper writes the current HEAD SHA to `./COMMIT_SHA` (gitignored) before invoking `railway up --detach`, and the Dockerfile moves it to `/app/COMMIT_SHA`. To see which commit a service is running:

    railway ssh --service docket-web "cat /app/COMMIT_SHA"
    railway ssh --service worker     "cat /app/COMMIT_SHA"

A bare `railway up` still works but records the literal string `unknown`, because the Railway CLI strips `.git` from uploads. `railway up` deploys whatever is in the local working tree regardless of branch, which is why deploys happen only from `main`. Never use `railway redeploy`; it restarts the old build without new code.

Railway runs only the `web:` line of the Procfile. The worker is a separate Railway service whose custom start command runs `python -m docket.worker.scheduler`; the `worker:` Procfile line is informational. It was created once in the dashboard as an empty service with the web service's environment variables copied over.

## Railway specifics

`railway run <cmd>` executes locally with Railway's variables injected, and the injected `DATABASE_URL` points at `postgres.railway.internal`, which resolves only inside Railway's network. `railway ssh --service <name> "<cmd>"` executes inside the container. For anything that touches the production database from a laptop, use `DATABASE_PUBLIC_URL`:

    DATABASE_URL=$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-) \
    ANTHROPIC_API_KEY=$(railway variables --service docket-web --kv | grep '^ANTHROPIC_API_KEY=' | cut -d= -f2-) \
    venv/bin/python -m docket.ai.cli --status

Manual worker tasks run inside the container: `railway ssh --service worker` then `python -m docket.worker.scheduler --run-once <task>`. A long `railway ssh "<cmd>"` can return before the remote command finishes; poll the relevant table rather than chaining commands.

Production Postgres is version 18.3. Dumps and restores from a laptop use the postgresql@18 binaries (`/opt/homebrew/opt/postgresql@18/bin/pg_dump`, `psql`); the version 16 binaries refuse with a server version mismatch.

The worker idles near 954 MB. An OCR scan adds roughly 600 MB of Python and 150 MB of ffmpeg, so an active scan runs near 1.7 GB. Never start a second heavy Python process on the worker (`railway ssh --run-once <heavy task>` has caused out-of-memory kills). If headroom shrinks, the options are a larger tier, `LIMIT 1` per OCR tick, or a separate OCR service.

The production database volume is 1 GB. A per-row sweep over tens of thousands of rows overflows the write-ahead log; on 2026-05-12 a Wave 0 sweep wrote about 360 MB of WAL into a 500 MB volume and crash-looped Postgres. Bulk changes are one targeted SQL statement; see decision `0026` in `docs/decisions/`.

A second Postgres service named `Postgres-pKpA` exists in the Railway project with no known use; it is `D32` in `docs/DEBT.md`.

## Domain and headers

The apex `docket.pub` is on Railway with a Let's Encrypt certificate it provisions itself. DNS at Namecheap: `CNAME @` to `zu815cqb.up.railway.app` plus a `TXT _railway-verify` record. `www.docket.pub` is a Namecheap URL redirect over HTTP only; moving it to Railway is `D10`.

`src/docket/web/__init__.py` sends `Strict-Transport-Security: max-age=31536000` in an `after_request` hook when `FLASK_ENV` is not `development`. `includeSubDomains` is omitted on purpose until `www` is served by Railway; see decision `0025`.

## Transcriber

The desktop producer on the Legion transcribes council video and uploads through the `transcriber` database role, created once by `scripts/sql/create_transcriber_role.sql`. The role can write only `transcripts`, `transcript_segments`, `transcript_speakers`, and `producer_heartbeats`. Rotate it with `ALTER ROLE transcriber PASSWORD '...'` and update the transcriber's .env file on the Legion (not in this repository). Uploads are public on arrival. Operating notes, expected oddities (stray Monday Granicus clips, over-split speakers), and the bring-up log are in `transcriber/README.md`; the runbook is `docs/runbooks/transcripts.md`.

## Runbooks

- `docs/runbooks/cron-worker.md`: Healthchecks.io setup, `--run-once` verification, alert response, the backfill.
- `docs/runbooks/analytics.md` and `docs/analytics-queries.md`: Umami views and common queries. Query only the `v_*` views; see decision `0024`.
- `docs/runbooks/transcripts.md`: the Legion producer.
- `docs/runbooks/v3-cutover.md` and `docs/runbooks/smart-brevity-ui-flip.md`: the Impact-First cutover procedures.
- `docs/SECURITY_CHECKLIST.md`: pre-launch requirements.
