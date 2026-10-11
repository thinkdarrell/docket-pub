# docket.pub — agent guide

docket.pub ingests, parses, and indexes Alabama municipal meeting records and publishes them at https://docket.pub with every fact linked to the city's own source document. Python 3.10, Flask and HTMX, PostgreSQL, deployed on Railway; a cron worker does the daily work. The one thing to understand before editing: the service layer owns every transaction, and nothing shown to a reader may lose its link to the source. Read `docs/PRINCIPLES.md` before touching anything that produces or renders data.

## Map

- `GOALS.md`: purpose, outcomes, scope, non-goals, constraints, known unknowns. Read first.
- `ARCHITECTURE.md`: components, layer map, dependency rules, known rough edges.
- `docs/PRINCIPLES.md`: six rules that override convenience.
- `docs/MATURITY.md`: the autonomy ladder; this project is at L0.
- `docs/DEBT.md`: deliberate deferrals with triggers, `D1` onward.
- `docs/decisions/`: one file per durable decision, `0001` onward.
- `docs/specs/`: present-tense behaviour. `operations.md` is how the system is run.
- `docs/capabilities/`: spec cards for mechanical checks, with status in `index.md`.
- `plans/PLANS.md`: the plan convention. `plans/active/` in flight, `plans/completed/` done.
- `skills/`: the six procedures (`plan-author`, `plan-execute`, `doc-garden`, `retro`, `capability-build`, `harness-init`). Also reachable as `.claude/skills/`.
- `docs/superpowers/`: design specs, plans, and reviews written before this harness. History, not current behaviour.
- `docs/runbooks/`: operator procedures, indexed from `docs/specs/operations.md`.
- GitHub issues on `thinkdarrell/docket-pub`: bugs nobody chose. Deliberate deferrals go in `docs/DEBT.md`.

## Commands

Run from the repository root (or the worktree root) with that checkout's own `venv/`.

- Verify (cheap): `venv/bin/python -m pytest tests/unit tests/web tests/services -q` (about 70 s; five known failures, `D1`). There is no aggregated verify command yet; `D5` and the `fast-verify` card track it.
- Full tests: `venv/bin/python -m pytest tests/unit tests/web tests/services tests/integration -q` (about 105 s; needs local Postgres with `docket_db` migrated; three more known failures, `D2`). Never bare `pytest`, which also collects live tests (`D35`). Live tests: `-m live`.
- Migrations: `venv/bin/python -m docket.migrations.runner` (`--status`; `--down <version>` rolls back that migration number, and `--down 1` drops the schema).
- Dev server: `venv/bin/flask run`.
- Deploy: humans only, from a clean `main`, `scripts/deploy.sh --service docket-web` or `--service worker`.

## Working rules

- Multi-file or multi-session work requires an ExecPlan per `plans/PLANS.md`.
- Execute one milestone per session. Update every living section `plans/PLANS.md` requires, with observed evidence. Stop.
- Never report a planned command as passing evidence. Run it, record what you observed.
- Decisions with lasting effect go in the plan's Decision Log; durable ones graduate to `docs/decisions/`.
- Nothing material lives outside the repo. If it was decided, it is written here.
- This file is a map, not an encyclopedia. Keep it under about 100 lines; content that wants to grow moves into `docs/` and leaves a one-line map entry.
- Before changing anything under `src/docket/adapters/`, `src/docket/analysis/`, `src/docket/services/ingest.py`, or a template that renders data, read `docs/PRINCIPLES.md`.
- Routes, worker tasks, and CLIs call `docket.services.*`; services own transactions. Known violations are `D7`.
- The Constraints in `GOALS.md` bind every change: production volume and worker memory, polite scraping, deploy from `main` only, commit identity.
- Feature branches (`feat/*` by hand, `plan/<slug>` from the factory) merge to `main` by pull request.
- Each worktree needs its own `venv/`; `docs/specs/operations.md` says why and how.
