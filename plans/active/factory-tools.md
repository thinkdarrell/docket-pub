# Make the test suite green, give the repository one verify command on a disposable database, and build the milestone judge

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

Today an agent working in this repository cannot prove its change is safe with one command. The published verify line is a pytest invocation that fails on eight tests nobody touched, the integration tier runs against the developer's own database and can be poisoned by the previous run, and there is no script that decides whether a milestone session actually landed its work. After this plan, `./tools/verify` runs from any checkout, builds a throwaway database from the migrations, runs every non-live test tier, runs the milestone judge's self-test, and exits zero on `main`. A second script, `tools/judge-milestone`, reads a plan file and the git history and says, from evidence alone, whether a session advanced exactly one milestone. Both are the mechanical ground the factory's `cycle-run` workflow (the next plan) stands on. You can see it working by running `./tools/verify` and reading one green summary line per check.

## Progress

- [ ] M1: the eight failing tests pass on a developer database.
- [ ] M2: `tools/verify` and `tools/test-db` exist; the integration tier runs on a disposable database named from the checkout; bare `pytest` no longer collects live tests.
- [ ] M3: `tools/judge-milestone` exists with its fixture self-test under `tools/verify`, and its card is in the register.
- [ ] M4: `AGENTS.md`, `docs/specs/operations.md`, `docs/DEBT.md`, `docs/MATURITY.md`, and `docs/capabilities/index.md` reflect the new commands; debt rows D1, D2, D3, D5, D35 are closed.

## Surprises & Discoveries

None yet. Nothing has been executed.

## Decision Log

- Decision: milestones are ordered tests first, then the verify command and disposable database, then the judge, then the documentation close-out.
  Rationale: a verify command that is red at its own acceptance is hard to accept; fixing the eight tests first makes M2's acceptance a plain "exits zero". The judge needs the verify command to exist so its self-test has a home. The close-out is last because it states what the earlier milestones made true.
  Date/Author: 2026-10-11, plan author (Claude, for the operator).
- Decision: the judge decides from git and the plan file only. It does not run the test suite. The caller (a person now, `cycle-run` later) runs `./tools/verify` as a separate step after the judge says the record advanced.
  Rationale: one check per concern. A judge that also ran tests would take two minutes per fixture and could not have a self-test inside the verify budget. factory-loop's `loop-runner` makes the same split.
  Date/Author: 2026-10-11, plan author.
- Decision: the disposable test database is named `docket_test_<hash>`, where the hash is the first eight hex characters of the SHA-1 of the checkout's absolute path.
  Rationale: two worktrees running `./tools/verify` at the same time would otherwise drop each other's database mid-run. The `isolated-env` card asks for exactly this property. The name is printed so an operator can find and drop it.
  Date/Author: 2026-10-11, plan author.
- Decision: the test database lives on the same PostgreSQL 16 server as `docket_db`, not on the installed postgresql@18.
  Rationale: the postgresql@18 server is installed but not running as a service (`brew services list` shows it as none), and starting a second server is a machine change this plan does not own. Debt row D4 stays open with that option recorded.
  Date/Author: 2026-10-11, plan author.
- Decision: `isolated-env` stays `specced` after this plan even though per-checkout venvs and per-checkout test databases now exist.
  Rationale: the card's promotion bar is a demonstrated failing case under two concurrent environments. This plan does not run that demonstration; a later plan or the first `cycle-plan` worktree build can.
  Date/Author: 2026-10-11, plan author.
- Decision: the verify time budget published in `AGENTS.md` is 180 seconds.
  Rationale: the three fast tiers take about 67 seconds on the operator's machine, the integration tier about 50 seconds plus the database build, and the judge fixtures a few seconds. factory-loop's default of 60 seconds is for repositories of markdown; this one runs 2,250 tests.
  Date/Author: 2026-10-11, plan author.
- Decision: this plan is executed by fresh agent sessions one milestone at a time, with the operator's session judging between them by the loop-runner rules until M3 lands and by `tools/judge-milestone` itself afterwards.
  Rationale: the `cycle-run` workflow does not exist yet (it is the next plan). Executing this plan the way the factory will execute later plans is the live trial the design document asks for, and judging M4 with the judge built in M3 exercises it on a real plan before any workflow depends on it.
  Date/Author: 2026-10-11, plan author.

## Outcomes & Retrospective

Not yet written. Nothing has been executed.

## Context and Orientation

docket.pub is a Flask and PostgreSQL application. Its code lives under `src/docket/` and its tests under `tests/` in four tiers: `tests/unit/`, `tests/web/`, and `tests/services/` need no database beyond what `tests/conftest.py` sets in the environment; `tests/integration/` needs a PostgreSQL database with the migrations applied, reached through the `DATABASE_URL` environment variable that `src/docket/config.py` reads; `tests/live/` makes real Anthropic API calls and is opted into with `pytest -m live`. There is no `addopts` in `pyproject.toml`, so a bare `pytest` collects the live tier too, and because `tests/conftest.py` sets a dummy `ANTHROPIC_API_KEY`, the live fixtures' skip check (which only tests that a key is set) does not fire.

A "migration" here is a numbered Python module under `src/docket/migrations/` with `SQL_UP` and `SQL_DOWN` strings; `python -m docket.migrations.runner` applies the pending ones to the database `DATABASE_URL` names, `--status` lists them, and `--down <version>` rolls back one by number (so `--down 1` drops the whole schema). The runner records applied versions in a `schema_migrations` table. The local developer database is `docket_db` on the Homebrew PostgreSQL 16 server (`/opt/homebrew/opt/postgresql@16/bin/`), owned by the superuser role `docket`, which may create databases.

A "materialised view" is a stored query result PostgreSQL keeps as a table until it is refreshed. `mv_badge_volume_monthly` is one; migration 033 (`src/docket/migrations/033_meetings_is_hidden.py`) rebuilds it with a `m.is_hidden = FALSE` filter. On the operator's `docket_db` the view's current definition lacks that filter although `schema_migrations` lists 033 as applied, which is why `tests/integration/test_033_migration.py::test_033_up_refreshes_mv_with_filter` fails there. A database built fresh from the migrations has the filter.

The repository's agent harness (installed by PR #108) is a set of markdown files: `AGENTS.md` is the map every session reads first; `docs/DEBT.md` is the debt register with stable row ids; `docs/capabilities/` holds one specification card per mechanical check with their statuses in `docs/capabilities/index.md`, written in the shape `docs/capabilities/CARD_FORMAT.md` defines; `docs/MATURITY.md` states the autonomy rung; `docs/specs/operations.md` is how the system is run. A "plan" is a file like this one under `plans/active/`, whose Progress section holds one checkbox line per milestone, ticked with a timestamp when done.

The factory design this plan serves is `docs/superpowers/specs/2026-10-10-factory-cycle-design.md`. Its section 4 specifies `tools/judge-milestone`, and factory-loop's own `tools/loop-runner` (in the checkout at `/Users/darrellnance/projects/factory-loop`, outside this repository) carries a working awk implementation of the plan parsing and the commit judging that this plan adapts. The judge's rule, in one sentence: an iteration advanced when at least one new commit exists, every new commit touches the plan file, exactly one Progress entry went from open to done, that entry carries a date, no done entry reverted, and the working tree is clean.

The eight failing tests and their causes, found on 2026-10-11:

Four tests in `tests/web/test_blog_routes.py` (`test_city_route_filters_to_city_and_shared`, `test_post_detail_renders`, `test_post_detail_emits_twitter_card_meta`, `test_preview_token_reveals_draft`) build a minimal Flask app with a stub `public` blueprint that registers only the routes the shared templates needed when the test was written. `src/docket/web/templates/partials/masthead.html` now calls `url_for('public.city_overview', slug=...)` in three places, and the stub has no `city_overview` route, so rendering raises `BuildError` and the response is 500. The stub is in the `app` fixture at `tests/web/test_blog_routes.py` lines 51 to 100.

`tests/web/test_city_overview_render.py::test_meeting_detail_source_links_below_executive_summary` asserts a `class="kpi-grid"` element precedes the sources section on a meeting page. The meeting template `src/docket/web/templates/meeting_detail.html` has used `class="kpi-strip"` since the visual refactor in May (commit `0745af6`); `kpi-grid` survives only in `admin/ai_panel.html`. The test went unnoticed because it returns early when no meeting exists locally.

`tests/integration/test_blog_integration.py::test_city_page_shows_blog_rail` fails with the same `BuildError` as the blog route tests, through the same masthead partial.

`tests/integration/test_calibration.py::test_query_c_returns_weeks_of_data` seeds two groups of items at `days_ago=0.0` and `days_ago=6.5` and expects two weekly buckets. `query_c_baseline_drift` in `src/docket/services/calibration.py` buckets by `date_trunc('week', ...)`, whose weeks start on Monday, so on a Sunday both groups fall in the same week. GitHub issue #70 recorded the Sunday flake in May.

`tests/integration/test_033_migration.py::test_033_up_refreshes_mv_with_filter` fails for the database-drift reason above.

## Plan of Work

M1 touches tests only. In `tests/web/test_blog_routes.py`, inside the `app` fixture, add a stub route `@public_stub.route("/al/<slug>/")` named `city_overview` that takes `slug` and returns an empty `Response`, beside the existing stubs; then run the four blog tests and, if any other `BuildError` names a missing endpoint, add that stub too and record which. In `tests/web/test_city_overview_render.py`, change the two occurrences of `kpi-grid` in `test_meeting_detail_source_links_below_executive_summary` (the `html.find` and the assertion message) to `kpi-strip`. In `tests/integration/test_calibration.py::test_query_c_returns_weeks_of_data`, change the second group's `days_ago=6.5` to `days_ago=8.0` and extend the docstring's "6 days ago" to say eight days, so the two groups can never share a Monday-to-Sunday week. For the materialised view, repair the operator's `docket_db` once by running the view rebuild that migration 033's `SQL_UP` contains (the `DROP MATERIALIZED VIEW IF EXISTS mv_badge_volume_monthly;` through the `CREATE UNIQUE INDEX` statement), using `venv/bin/python -c` to execute that slice of `_m033.SQL_UP` through `docket.db.db()`; record the before and after of `pg_get_viewdef`. Do not change the test or the migration. Record `test_blog_integration.py` passing as a consequence of the stub fix without a change of its own.

M2 creates `tools/test-db` and `tools/verify`, both POSIX `sh` scripts with the executable bit set, and adds one line to `pyproject.toml`. `tools/test-db` computes `NAME=docket_test_$(printf '%s' "$(pwd -P)" | shasum | cut -c1-8)`, derives the server connection from `DATABASE_URL` (default `postgresql://docket@localhost:5432/docket_db`) by replacing the trailing database name, runs `DROP DATABASE IF EXISTS "$NAME" WITH (FORCE)` and `CREATE DATABASE "$NAME"` through `psql` against the `postgres` maintenance database on that server, applies the migrations with `DATABASE_URL=<server>/$NAME venv/bin/python -m docket.migrations.runner`, and prints the resulting URL on its last line; `tools/test-db --drop` drops it and prints nothing. `tools/verify` runs, in order, each printing one summary line and all of them running even if an earlier one fails: the fast tiers `venv/bin/python -m pytest tests/unit tests/web tests/services -q -p no:cacheprovider`; the integration tier `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration -q -p no:cacheprovider` followed by `tools/test-db --drop`; and, once M3 lands, `tools/fixtures/judge/run`. It ends with `verify: N of M checks failed.` and a re-run instruction, or `verify: all M checks passed in Ns.`, and exits nonzero if any check failed. Each failing check's own output is left on the terminal above the summary, never swallowed. In `pyproject.toml` under `[tool.pytest.ini_options]` add `addopts = "-m 'not live'"`, so `pytest` alone excludes the live tier and `pytest -m live` still selects it (an explicit `-m` on the command line replaces the addopts marker expression). Record the observed wall time of `./tools/verify`.

M3 creates `tools/judge-milestone`, `tools/fixtures/judge/run`, and `docs/capabilities/judge-milestone.md`, and adds the card's row to `docs/capabilities/index.md`. The judge is a POSIX `sh` script adapted from the `read_plan`, `plan_defect`, `compare_records`, and `untouching_commits` functions of factory-loop's `tools/loop-runner`, with two modes. `tools/judge-milestone snapshot <plan>` prints the tab-separated records (`OPEN`, `DONE`, `NOSTAMP`, `MISSING`, `EMPTY`, each with line number, shortened text, and the normalised key described in the loop-runner comments) and exits 0 if the record holds or 2 with the first defect as a one-line message if it does not. `tools/judge-milestone judge <plan> <snapshot-file> <start-sha>` re-reads the plan at HEAD, compares it with the snapshot, lists commits `<start-sha>..HEAD` and which of them did not touch `<plan>`, checks `git status --porcelain` is empty, and exits 0 printing `judge: advanced "<entry text>"` or 1 printing a four-line halt: the plan path, the entry it stopped on (or `no entry`), the rule that failed in one sentence, and `Fix the cause, commit in the worktree, and re-run.` The rules, each its own sentence in the output: no commit landed; commit `<short sha>` did not touch the plan; `<n>` Progress entries changed state (exactly one must); entry at line `<n>` is ticked but carries no date; entry `"<text>"` was done at the start and is no longer; the working tree has uncommitted changes. A ticked entry counts as dated when any `YYYY-MM-DD` appears anywhere on its line, in parentheses, brackets, or bare. The fixture runner `tools/fixtures/judge/run` builds temporary git repositories under `mktemp -d` for eight cases and asserts the exit code and the first word after `judge:` for each: a clean one-entry advance (0); no commit (1); a commit that does not touch the plan (1); two entries ticked in one iteration (1); one entry ticked without a date (1); a done entry un-ticked (1); a dirty tree after an otherwise clean advance (1); and a plan missing `## Decision Log` at snapshot time (2). It prints one line per case and `judge fixtures: 8 of 8 passed` or the failing case names, and exits accordingly. The card follows `docs/capabilities/CARD_FORMAT.md` with the invariant stated above, enforcement at `./tools/verify` through the fixture runner and at `cycle-run` through the judge itself, the passing and failing acceptance written as instructions, and the four-line halt as the remediation message. Its register row reads `specced` when written and is promoted in M4 after the failing case below is observed.

M4 is the close-out. `AGENTS.md` Commands becomes: Verify (cheap, after any edit): `./tools/verify` (about 150 seconds; budget 180 s; builds a throwaway database, runs every non-live tier and the judge fixtures); Full tests is removed because verify now covers it; Live tests: `venv/bin/python -m pytest -m live`; Migrations and Dev server lines stay; the sentence about no aggregated command and D5 goes. `docs/specs/operations.md` Tests section is rewritten around `./tools/verify` and `tools/test-db`, naming the per-checkout database name rule and that a stale developer `docket_db` is no longer what the tests run against; the "Never run bare pytest" paragraph becomes one sentence saying `addopts` excludes the live tier. In `docs/DEBT.md` delete rows D1, D2, D3, D5, and D35 and the D3 detail section, leaving D4 with a note that `tools/test-db` can be pointed at postgresql@18 by changing the server part of `DATABASE_URL`, and leaving D6 open. In `docs/capabilities/index.md` set `fast-verify` to `built` with `./tools/verify` as the enforcement point and `judge-milestone` to `built` with `./tools/verify` (fixtures) and `cycle-run` (planned) as enforcement points, after demonstrating both failing cases: for `fast-verify`, introduce a one-character assertion error in a unit test, run `./tools/verify`, observe the nonzero exit with pytest's own failure text above the summary, revert; for `judge-milestone`, change one expected exit code in `tools/fixtures/judge/run`, run `./tools/verify`, observe the fixture runner fail naming the case, revert. Record both transcripts in this plan's Artifacts section. In `docs/MATURITY.md` the Current rung paragraph is rewritten to say L0 with `fast-verify` and `judge-milestone` `built`, and that the one thing moving toward L1 is twenty consecutive landed changes with `./tools/verify` green and unskipped, which starts counting from this plan's merge. `evidence-check` stays `specced`: the judge's snapshot mode decides its two facts for one plan, but the card asks for a check over every plan in `plans/active/`, and that aggregation is a separate small build.

## Concrete Steps

All commands run from the worktree root `/Users/darrellnance/docket-pub/.claude/worktrees/factory-tools` on branch `plan/factory-tools`, using that checkout's own `venv/`. A session starts by reading `AGENTS.md`, then `plans/PLANS.md`, then this file, then only the files named in its milestone.

Before any milestone, observe the starting state:

    venv/bin/python -m pytest tests/unit tests/web tests/services -q -p no:cacheprovider 2>&1 | tail -1

Expected before M1: `5 failed, 1852 passed, 3 skipped, 4 xfailed ...` (observed 2026-10-11 on `main` at `b174008`). Expected after M1: `1852 passed` with zero failed, counts otherwise unchanged.

M1 commands:

    venv/bin/python -m pytest tests/web/test_blog_routes.py tests/web/test_city_overview_render.py -q -p no:cacheprovider 2>&1 | tail -1
    venv/bin/python -m pytest tests/integration/test_calibration.py::test_query_c_returns_weeks_of_data tests/integration/test_blog_integration.py -q -p no:cacheprovider 2>&1 | tail -1
    venv/bin/python -c "import importlib; m = importlib.import_module('docket.migrations.033_meetings_is_hidden'); from docket.db import db; sql = m.SQL_UP[m.SQL_UP.index('DROP MATERIALIZED VIEW'):]; sql = sql[: sql.index('CREATE UNIQUE INDEX')]; sql = sql + m.SQL_UP[m.SQL_UP.index('CREATE UNIQUE INDEX'):].split(';')[0] + ';'; conn = db().__enter__(); cur = conn.cursor(); cur.execute(sql); conn.commit(); print('rebuilt')"

That one-liner imports migration 033 by name (the module name starts with a digit, so a plain import statement cannot name it), takes the `SQL_UP` text from `DROP MATERIALIZED VIEW` through the end of the `CREATE UNIQUE INDEX` statement, and runs it in one transaction on `docket_db`. If `db()` is not usable as shown, open the connection the way `src/docket/db.py` documents and record the form used. Before and after, record:

    venv/bin/python -c "from docket.db import db_cursor; cur = db_cursor().__enter__(); cur.execute(\"select pg_get_viewdef('mv_badge_volume_monthly'::regclass, true)\"); print('is_hidden' in cur.fetchone()['definition' if 'definition' in cur.description[0].name else 0])"

Expected before: `False`; after: `True`. Then:

    venv/bin/python -m pytest tests/integration/test_033_migration.py -q -p no:cacheprovider 2>&1 | tail -1

Expected: all tests in that file pass. Then the full non-live suite:

    venv/bin/python -m pytest tests/unit tests/web tests/services tests/integration -q -p no:cacheprovider 2>&1 | tail -1

Expected: zero failed (observed before M1 on 2026-10-11: `8 failed, 2253 passed, 3 skipped, 4 xfailed`).

M2 commands:

    chmod +x tools/test-db tools/verify
    tools/test-db
    tools/test-db --drop
    ./tools/verify; echo "exit=$?"
    venv/bin/python -m pytest --collect-only -q 2>&1 | grep -c 'tests/live/'

Expected: `tools/test-db` prints the migration runner's output and ends with a line `postgresql://docket@localhost:5432/docket_test_<8 hex>`; the drop prints nothing; verify prints one line per check and `verify: all 2 checks passed in <N>s.` with `exit=0`; the collect-only count of live tests is `0` after the `addopts` change and nonzero before it (record both).

M3 commands:

    chmod +x tools/judge-milestone tools/fixtures/judge/run
    tools/judge-milestone snapshot plans/active/factory-tools.md | head -5; echo "exit=$?"
    tools/fixtures/judge/run
    ./tools/verify; echo "exit=$?"

Expected: the snapshot prints records beginning `OPEN`/`DONE` for this plan's four milestones (M1 and M2 `DONE` by then) and exits 0; the fixture runner prints eight case lines and `judge fixtures: 8 of 8 passed`; verify reports `all 3 checks passed`.

M4 commands are the two failing-case demonstrations described in Plan of Work, each followed by `git checkout -- <file>` to revert, then `./tools/verify` once more, then `wc -l AGENTS.md` (must stay under 100), then the reference walk from the bootstrap plan's Task 10 over the edited artifacts.

## Validation and Acceptance

M1 is accepted when `venv/bin/python -m pytest tests/unit tests/web tests/services tests/integration -q -p no:cacheprovider` prints a summary with `0 failed` or no `failed` count at all, and the diff touches only the three test files named (plus this plan). The `docket_db` repair is recorded as a command transcript, not a code change.

M2 is accepted when `./tools/verify` exits 0 on this branch and prints a per-check summary; when running it from a second checkout at the same time would build a differently named database (observed by printing the computed name in both checkouts, which is acceptance a person can read without running two at once); when `venv/bin/python -m pytest --collect-only -q | grep -c tests/live/` prints `0`; and when `venv/bin/python -m pytest -m live --collect-only -q | grep -c tests/live/` prints a number above 0.

M3 is accepted when `tools/fixtures/judge/run` prints `judge fixtures: 8 of 8 passed` and exits 0, when `./tools/verify` includes it and still exits 0, when `tools/judge-milestone snapshot plans/active/factory-tools.md` exits 0, and when `docs/capabilities/judge-milestone.md` exists with the four mandatory sections and a `specced` row in the index.

M4 is accepted when both failing-case transcripts are in this plan's Artifacts section and each shows a nonzero exit with the underlying check's own message; when `./tools/verify` exits 0 afterwards; when `AGENTS.md` names `./tools/verify` with its budget and is under 100 lines; when `grep -c '^| D[0-9]' docs/DEBT.md` prints `31`; and when `docs/capabilities/index.md` shows `fast-verify` and `judge-milestone` as `built`.

## Idempotence and Recovery

Every step can be rerun. `tools/test-db` drops before it creates, so a half-built test database is replaced on the next run; `tools/test-db --drop` removes it by hand. The one-time `docket_db` view rebuild in M1 is a `DROP ... IF EXISTS` followed by `CREATE`, safe to repeat, and reversible by applying migration 033's `SQL_DOWN` view portion, which nobody should need. Editing `pyproject.toml` `addopts` is reversible by deleting the line. If a session dies mid-milestone, commit what landed, split the Progress entry into completed and remaining parts, log the split in the Decision Log, and stop; the next session reads the record. If `./tools/verify` is red for a reason outside this plan (a new failing test from a merge of `main`), that is a finding for Surprises & Discoveries, not something this plan absorbs.

## Artifacts and Notes

To be filled by executing sessions with observed transcripts: the before and after `pg_get_viewdef` of the materialised view; the `./tools/verify` summary and wall time; the fixture runner's eight lines; the two failing-case demonstrations.

## Interfaces and Dependencies

`tools/test-db`: POSIX sh. Reads `DATABASE_URL` (optional). Prints the test database URL as its last line and exits 0, or exits nonzero with psql's or the runner's error. `tools/test-db --drop` drops it silently. Requires `psql` on PATH or at `/opt/homebrew/opt/postgresql@16/bin/psql` (try PATH first, then that path) and `venv/bin/python`.

`tools/verify`: POSIX sh, no arguments, exit 0 only if every check passed. Checks are listed in the script as `name` and `command` pairs so adding one is one line. Output contract: each check's own output, then one summary line per check in the form `verify: <name> ... ok` or `verify: <name> ... FAILED`, then the final line.

`tools/judge-milestone`: POSIX sh. `snapshot <plan>` to stdout, exit 0 or 2. `judge <plan> <snapshot-file> <start-sha>`, exit 0, 1, or 2, output as specified in Plan of Work. Uses only `git`, `awk`, `sed`, `printf`; no Python.

`tools/fixtures/judge/run`: POSIX sh, no arguments, exit 0 if all cases pass. Creates and removes its own temporary repositories; leaves nothing behind.

`pyproject.toml`: `[tool.pytest.ini_options]` gains `addopts = "-m 'not live'"`.

`docs/capabilities/judge-milestone.md`: card per `docs/capabilities/CARD_FORMAT.md`, sections Invariant, Enforcement point, Acceptance, Remediation message.
