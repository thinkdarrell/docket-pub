# docket.pub — agent guide

docket.pub ingests, parses, and indexes Alabama municipal meeting records and publishes them at https://docket.pub with every fact linked to the city's own source document. Python 3.10, Flask and HTMX, PostgreSQL, deployed on Railway; a cron worker does the daily work. The one thing to understand before editing: the service layer owns every transaction, and nothing shown to a reader may lose its link to the source. Read `docs/PRINCIPLES.md` before touching anything that produces or renders data.

## Map

- `GOALS.md`: purpose, outcomes, scope, non-goals, constraints, known unknowns. Read first.
- `ARCHITECTURE.md`: components, layer map, dependency rules, known rough edges.
- `docs/PRINCIPLES.md`: six rules that override convenience.
- `docs/MATURITY.md`: the autonomy ladder; this project is at L0.
- `docs/DEBT.md`: deliberate deferrals with triggers; stable ids `Dn`, closed rows are deleted and numbers are never reused.
- `docs/decisions/`: one file per durable decision, `0001` onward.
- `docs/specs/`: present-tense behaviour. `operations.md` is how the system is run.
- `docs/capabilities/`: spec cards for mechanical checks, with status in `index.md`.
- `plans/PLANS.md`: the plan convention. `plans/active/` in flight, `plans/completed/` done.
- `tools/`: `verify` (the one check command), `test-db` (the disposable database it builds), `judge-milestone` (did a session advance exactly one milestone), `fixtures/judge/run` (the judge's self-test), `check-workflows` (every saved workflow parses and its meta names its file), `check-plans` (every active plan carries its living sections and dated ticks), `hooks/pre-commit` (the same check on a staged plan; installed with `git config core.hooksPath tools/hooks`).
- `.claude/workflows/`: the factory's two commands, `cycle-plan` (a stated goal becomes a committed plan on its own branch, worktree, and venv) and `cycle-run` (a plan becomes a pull request, one fresh agent per milestone, judged from git). `docs/specs/operations.md` Running the factory says how they are run.
- `skills/`: the six procedures (`plan-author`, `plan-execute`, `doc-garden`, `retro`, `capability-build`, `harness-init`). Also reachable as `.claude/skills/`.
- `docs/superpowers/`: design specs, plans, and reviews written before this harness. History, not current behaviour.
- `docs/runbooks/`: operator procedures, indexed from `docs/specs/operations.md`.
- GitHub issues on `thinkdarrell/docket-pub`: bugs nobody chose. Deliberate deferrals go in `docs/DEBT.md`.

## Commands

Run from the repository root (or the worktree root) with that checkout's own `venv/`.

- Verify (cheap, after any edit): `./tools/verify` (about 150 seconds; budget 180 s). Builds a throwaway database from the migrations, runs every non-live tier (unit, web, services, integration) and the judge fixtures against it, then the saved-workflow shape check (`tools/check-workflows`), then the producer suite (`transcriber/tests`, whose database tests then run against the throwaway database), then, sixth, the active-plan check (`tools/check-plans`), prints one summary line per check, drops the database, and exits zero only when every check passed. Never bare `pytest` against a database you care about: `pyproject.toml` excludes the live tier, but the unit tier deletes rows from whatever `DATABASE_URL` names (`D37`), so `tests/conftest.py` refuses, with exit 2 before collection, any database not named `docket_test_*` outside the live tier.
- Live tests: `venv/bin/python -m pytest -m live` (real Anthropic calls; needs a real `ANTHROPIC_API_KEY`).
- Milestone judge: `tools/judge-milestone snapshot <plan>` before a session, `tools/judge-milestone judge <plan> <snapshot-file> <start-sha>` after it; the contract is `docs/capabilities/judge-milestone.md`.
- Migrations: `venv/bin/python -m docket.migrations.runner` (`--status`; `--down <version>` rolls back that migration number, and `--down 1` drops the schema).
- Dev server: `venv/bin/flask run`.
- Deploy: humans only, from a clean `main`, `scripts/deploy.sh --service docket-web` or `--service worker`.
- Factory: `/cycle-plan <goal>` from any checkout; `/cycle-run plans/active/<slug>.md` from a session started in `.claude/worktrees/<slug>`. One run at a time.

## Working rules

- Multi-file or multi-session work requires an ExecPlan per `plans/PLANS.md`.
- Execute one milestone per session. Update every living section `plans/PLANS.md` requires, with observed evidence. Stop.
- In a milestone session, every commit changes the plan file (decision `0037`); a Progress entry's text is never reworded once written, because the judge identifies entries by their text (`docs/capabilities/judge-milestone.md`); git hooks are never disabled or bypassed (they live in `tools/hooks/`, activated by `core.hooksPath`); the committed `.claude/settings.json` denies the hook-bypass and deploy commands, and those deny rules are listed there and nowhere else.
- Never report a planned command as passing evidence. Run it, record what you observed.
- Decisions with lasting effect go in the plan's Decision Log; durable ones graduate to `docs/decisions/`.
- Nothing material lives outside the repo. If it was decided, it is written here.
- This file is a map, not an encyclopedia. Keep it under about 100 lines; content that wants to grow moves into `docs/` and leaves a one-line map entry.
- Before changing anything under `src/docket/adapters/`, `src/docket/analysis/`, `src/docket/services/ingest.py`, or a template that renders data, read `docs/PRINCIPLES.md`.
- Routes, worker tasks, and CLIs call `docket.services.*`; services own transactions. Known violations are `D7`.
- The Constraints in `GOALS.md` bind every change: production volume and worker memory, polite scraping, deploy from `main` only, commit identity.
- Feature branches (`feat/*` by hand, `plan/<slug>` from the factory) merge to `main` by pull request.
- Each worktree needs its own `venv/`; `docs/specs/operations.md` says why and how.
