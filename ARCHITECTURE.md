# Architecture

## Shape

docket.pub is a Python application with three runtime processes sharing one PostgreSQL database: a Flask web app that serves citizens and an authenticated admin, an APScheduler worker that ingests, analyses, and summarises on a daily schedule, and command-line entry points an operator runs by hand. A fourth process, the transcriber, runs on a separate desktop machine and writes transcripts through a database role restricted to the transcript tables. Every city's meeting platform is reached through an adapter that implements one protocol, so the rest of the system never knows which vendor a city uses. The organising idea is that the service layer owns every transaction: web routes, worker tasks, and CLIs call services, and services call adapters, analysis, enrichment, and the AI pipeline.

## Components

### Adapters

- Lives in: `src/docket/adapters/`
- Owns: fetching meetings, agenda items, and document links from one vendor platform (Granicus, CivicClerk, CivicPlus, generic HTML archive) and returning them as the raw dataclasses in `src/docket/models/protocol.py`.
- Does not: write to the database or decide what a meeting means; `services/ingest.py` does both.

### Models

- Lives in: `src/docket/models/`
- Owns: the dataclasses for meetings, agenda items, votes, member votes, and vote-to-item links, and the `MunicipalSourceAdapter` protocol.
- Does not: touch the database or import any other layer.

### Services

- Lives in: `src/docket/services/`
- Owns: every transaction. Ingest (scrape, enrich, upsert, then sweep minutes adoptions), query (all reads for the web layer), enrichment, maintenance, minutes adoption, video OCR orchestration, badges, coverage, transcripts, the city briefing (`briefing.py`: the opener and doors of `/al/<slug>/` for a city whose metadata carries `briefing: true`, and the `city_briefing_facts` rebuild the worker's `briefing_facts` task calls; `docs/specs/city-page.md`), and the archived-meeting backfill (`archived_meetings.py`, which creates the 2023 Boutwell-era Birmingham meetings Granicus never recorded; decision `0033`).
- Does not: render HTML, schedule itself, or talk to a vendor site directly.

### Analysis

- Lives in: `src/docket/analysis/`
- Owns: turning documents into facts: the Birmingham minutes PDF parser (attendance and votes), the approval-title date parser, the N:M vote-to-agenda matcher with its provisional-to-official promotion, and the video OCR subpackage (`ocr/`: classifier, header, layout, sequence, pipeline, rosters).
- Does not: decide when to run; services and the worker call it.

### Enrichment

- Lives in: `src/docket/enrichment/`
- Owns: deterministic extraction from item text: dollar amounts and their display tiers (green under $50K, yellow to $250K, orange to $1M, red above), sponsors, keyword topics.
- Does not: call a language model.

### AI pipeline

- Lives in: `src/docket/ai/`
- Owns: the Anthropic client with its tool-use pattern and retries, prompt versions, Wave 0 non-LLM classification, Stage 1 extraction, Stage 2 Smart Brevity rewrite, Stage 2.5 reconcile, badge policy, batch submission and ingest, cost telemetry, the operator CLI, the daily budget gate, and the two 0 to 10 scores on every item (significance and consent placement), which stay NULL until the pipeline has processed the item. Its `transcripts/` subpackage holds the transcript stages the worker advances one at a time (speaker resolution, event extraction on both the transcript and the minutes side, the citation guard, the deterministic aligner, the comparison judge, alerts) and the Haiku-versus-Sonnet A/B harness; `docs/runbooks/transcripts.md` is its runbook.
- Does not: serve pages or own the cron schedule.

### Worker

- Lives in: `src/docket/worker/`
- Owns: the APScheduler process on the Railway `worker` service, the task wrappers that call services, and Healthchecks.io pings. The schedule is the code in `scheduler.py`, not any prose.
- Does not: contain business logic.

### Web

- Lives in: `src/docket/web/`
- Owns: the Flask app factory, public routes and HTMX partials, admin routes, session auth, Jinja templates and the design-system CSS.
- Does not: by rule, execute SQL; see Known rough edges.

### Blog

- Lives in: `src/docket/blog/`
- Owns: loading markdown posts with frontmatter from `content/` and rendering them under each city.
- Does not: touch meeting data.

### Migrations

- Lives in: `src/docket/migrations/`
- Owns: numbered schema migrations and the runner that applies, rolls back, and reports them.
- Does not: seed data outside a numbered migration.

### Scripts

- Lives in: `scripts/`
- Owns: one-off backfills and operator tools, including `deploy.sh`.
- Does not: get scheduled; anything recurring moves into the worker.

### Transcriber

- Lives in: `transcriber/`
- Owns: the desktop producer that transcribes council video and uploads through the `transcriber` database role, which can write only the transcript tables and its heartbeat.
- Does not: write any other table; it reads `meetings`, `municipalities`, `council_members`, and `agenda_items` to find work, and `scripts/sql/create_transcriber_role.sql` holds the grants.

## Layer map and dependency rules

From outermost to innermost: entry points (`web/`, `worker/`, `ai/cli.py`, `enrichment/cli.py`, `migrations/runner.py`, `scripts/`), then `services/`, then the domain layers (`adapters/`, `analysis/`, `enrichment/`, `ai/`, `blog/`), then `models/`, `db.py`, and `config.py`. Dependencies point inward only.

- Nothing under `src/docket/services/` may import from `src/docket/web/` or `src/docket/worker/`.
- Nothing under `src/docket/adapters/`, `src/docket/analysis/`, `src/docket/enrichment/`, or `src/docket/blog/` may import from `src/docket/services/`, `src/docket/web/`, or `src/docket/worker/`. Exception: `enrichment/cli.py` is an entry point and may import services.
- Nothing under `src/docket/models/` may import from any other `docket` package.
- Nothing under `src/docket/web/` may call `db()` or `db_cursor()` or execute SQL; it calls services.
- `src/docket/ai/` may not import from `src/docket/services/`. This rule is currently violated; see Known rough edges.

## Cross-cutting invariants

- Services own transactions; a transaction opened anywhere else is a defect.
- Every row produced from a source document stores a link to that document and the source kind (`minutes_text`, `video_ocr`, `api`).
- Configuration reaches code only through `src/docket/config.py`, which reads environment variables; no module reads `os.environ` directly for a setting that config already exposes.
- Anything that writes a shared queue row claims it with `FOR UPDATE SKIP LOCKED` so a second worker instance is safe.
- Prompt and schema versions are compared with a floor (`>=`), never equality.

## Known rough edges

- Some web modules still execute SQL directly, contrary to the web rule above. `D7` in `docs/DEBT.md` lists them.
- `src/docket/ai/` imports from `src/docket/services/` at six sites, an inward layer reaching outward: the badge-slug lookup (`D8` in `docs/DEBT.md`) and the transcript speaker helpers (`D42`).
- `src/docket/rosters/` is an empty leftover from an early layout; council rosters are stored by migration and resolved in `src/docket/analysis/ocr/rosters.py`. Deleting it is `D33` in `docs/DEBT.md`.
- A few modules read `os.environ` for settings that belong in `src/docket/config.py`, contrary to the configuration invariant above. `D34` in `docs/DEBT.md` lists them.
- `src/docket/worker/tasks.py` opens its own transactions in six task bodies, contrary to the services invariant above and the Worker rule. `D65` in `docs/DEBT.md` lists them.
