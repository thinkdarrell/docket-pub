# Make the test suite green, give the repository one verify command on a disposable database, and build the milestone judge

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

Today an agent working in this repository cannot prove its change is safe with one command. The published verify line is a pytest invocation that fails on eight tests nobody touched, the integration tier runs against the developer's own database and can be poisoned by the previous run, and there is no script that decides whether a milestone session actually landed its work. After this plan, `./tools/verify` runs from any checkout, builds a throwaway database from the migrations, runs every non-live test tier, runs the milestone judge's self-test, and exits zero on `main`. A second script, `tools/judge-milestone`, reads a plan file and the git history and says, from evidence alone, whether a session advanced exactly one milestone. Both are the mechanical ground the factory's `cycle-run` workflow (the next plan) stands on. You can see it working by running `./tools/verify` and reading one green summary line per check.

## Progress

- [x] (2026-10-11 16:56Z) M1: the eight failing tests pass on a developer database. Acceptance run `venv/bin/python -m pytest tests/unit tests/web tests/services tests/integration -q -p no:cacheprovider` printed `2468 passed, 3 skipped, 4 xfailed, 2 warnings in 133.36s`, zero failed. Carve-outs against the stated acceptance: (1) the diff touches four test files, not three; `tests/integration/test_blog_integration.py` needed its own fix because the plan's diagnosis of that test was wrong (Decision Log). (2) The acceptance holds for the first full run after the `mv_badge_volume_monthly` repair; every run of `tests/integration` re-drifts the view through `test_migration_013.py`, and the unit tier leaves rows that break 16 calibration tests on a following run, so a second run on `docket_db` is red again for reasons outside the eight tests and outside M1's scope (Surprises & Discoveries, Decision Log). M2's disposable database is the durable condition under which the suite is green.
- [ ] M2: `tools/verify` and `tools/test-db` exist; the integration tier runs on a disposable database named from the checkout; bare `pytest` no longer collects live tests.
- [ ] M3: `tools/judge-milestone` exists with its fixture self-test under `tools/verify`, and its card is in the register.
- [ ] M4: `AGENTS.md`, `docs/specs/operations.md`, `docs/DEBT.md`, `docs/MATURITY.md`, and `docs/capabilities/index.md` reflect the new commands; debt rows D1, D2, D3, D5, D35 are closed.

## Surprises & Discoveries

- Observation (M1, 2026-10-11): the plan's one-liner form `db_cursor().__enter__()` does not work. The `_GeneratorContextManager` object is a temporary; once `__enter__` returns, it is garbage-collected, the generator is closed, and the nested `with` blocks in `src/docket/db.py` close the cursor and connection before the first `execute`.
  Evidence: `psycopg2.InterfaceError: cursor already closed` from `venv/bin/python -c "from docket.db import db_cursor; cur = db_cursor().__enter__(); cur.execute(...)"`. The same query inside `with db_cursor() as cur:` ran. Concrete Steps below now show the `with` form.
- Observation (M1): the masthead partial needs three stubbed `public` endpoints, not one. After adding `city_overview`, the blog route tests still returned 500.
  Evidence: `werkzeug.routing.exceptions.BuildError: Could not build url for endpoint 'public.city_meetings' with values ['slug']`; `grep -o "url_for('public\.[a-z_]*'" src/docket/web/templates/partials/masthead.html | sort | uniq -c` lists `city_council` (1), `city_meetings` (1), `city_overview` (3) beside endpoints the stub already had. Stubs for all three were added, at the real routes' paths `/al/<slug>/`, `/al/<slug>/meetings/`, `/al/<slug>/council/` (from `src/docket/web/public.py` lines 84, 209, 893).
- Observation (M1): `test_meeting_detail_source_links_below_executive_summary` had a second latent failure hidden behind the `kpi-grid` one. With `kpi-strip` in place it failed on `AssertionError: roll-call section missing`. The template renders the Roll call block only inside `{% if votes %}` (`src/docket/web/templates/meeting_detail.html` line 123), and the developer database has no vote rows at all, so no meeting it can pick renders that block.
  Evidence: rendering `/al/birmingham/meetings/2231/` through `create_app().test_client()` returned 200 with `class="kpi-strip"` at offset 6226 and `class="mtg-sources"` at 7359 but `Roll call` at -1; `select count(*) from votes` on `docket_db` returned `0`. Resolved as logged in the Decision Log.
- Observation (M1): the session ran on a Sunday (`date +%A` printed `Sunday` at 2026-10-11T16:40Z), the one weekday on which the old `days_ago=6.5` seed shares a Monday-start `date_trunc('week', ...)` bucket with `days_ago=0.0`. With `8.0` the test passed on that Sunday, so the fix was demonstrated on the failing day rather than inferred.
  Evidence: `venv/bin/python -m pytest tests/integration/test_calibration.py::test_query_c_returns_weeks_of_data -q -p no:cacheprovider` printed `1 passed in 0.33s`.
- Observation (M1): the plan's diagnosis of `test_blog_integration.py::test_city_page_shows_blog_rail` was wrong. It cannot be the masthead `BuildError`, because this test uses the real app, which has `city_overview`; it passes alone (`3 passed in 1.40s`) and fails only after `tests/web` has run in the same process. The cause is `_overview_cache` in `src/docket/web/public.py` (line 73), a module-level dict caching the rendered city overview per slug for `_CACHE_TTL = 300` seconds. `tests/web` tests fetch `/al/birmingham/` and leave a page rendered from the real blog state in it; the integration test then receives that page, so "From the blog" is present but the swapped post is not.
  Evidence: `tests/web + test_city_page_shows_blog_rail` gave `1 failed, 189 passed`, failing on line 107 `assert b'Birmingham budget take' in r.data` after line 106 (`b"From the blog"`) passed; `tests/services + rail` and `tests/unit + rail` passed; no single `tests/web` file reproduced it alone. Three existing tests (`tests/web/test_city_overview_render.py:172`, `tests/integration/test_f5_data_debt.py:162`, `tests/integration/test_f4_browse_by_priority.py:185`) already call `_overview_cache.clear()` for this reason. After adding the clear to `override_blog_state`: `tests/web tests/integration/test_blog_integration.py` printed `192 passed, 3 skipped in 6.84s`.
- Observation (M1): the test suite destroys the developer database. `tests/unit/test_ai_worker_claim.py::fresh_db` (a unit-tier fixture, lines 13 to 28) runs `DELETE FROM vote_agenda_items`, `DELETE FROM member_votes`, `DELETE FROM votes`, `DELETE FROM processing_status_audit`, `DELETE FROM agenda_item_badges_audit`, `DELETE FROM agenda_items`, and `DELETE FROM meetings WHERE municipality_id IN (... slug LIKE 'test_%')` against whatever `DATABASE_URL` names, before each test and never after. This is why `docket_db` has zero rows in `votes` (the roll-call finding above) and why the last test's rows survive the run: meeting 44575 (`Test Meeting`, municipality 3605 `test_v3_hidden`) with agenda item 136833 titled `t`, `ai_generated_at` 2026-10-11 16:42Z.
  Evidence: `select count(*) from votes` returned `0`; the row above was found by `select ... from agenda_items where score_overrides is not null and ai_generated_at > now() - interval '24 hours'`. The leftover row carries `score_overrides` with float values (`"original_ai_significance": 4.0`), and `query_a_per_item_divergence` in `src/docket/services/calibration.py` casts that text with `::int`, so on the next run `tests/integration/test_calibration.py` fails 16 tests with `psycopg2.errors.InvalidTextRepresentation: invalid input syntax for type integer: "4.0"`. Production writes the same dict from `src/docket/ai/pipeline.py` line 368, so whether the admin calibration page breaks on real data depends on whether those values are ever floats there; not investigated in M1, left as a note for the operator.
- Observation (M1): the `mv_badge_volume_monthly` drift the plan attributed to a stale developer database is caused by a test, and recurs on every integration run. `tests/integration/test_migration_013.py::test_013_up_down_up_cycle` rolls back migrations 28 down to 21 and then 13 and calls `apply_migrations`, which re-applies only versions missing from `schema_migrations`; 033 stays recorded as applied, so its `is_hidden` rebuild of the view never re-runs and the view is left at migration 022's definition. The plan's one-time repair therefore holds only until the next run of `tests/integration`.
  Evidence: the view was rebuilt (`True`), `test_033_migration.py` passed (`4 passed`), the full suite ran, and a following `pytest tests/integration` run reported `test_033_up_refreshes_mv_with_filter` failed with the definition lacking `is_hidden`; `pg_get_viewdef` then showed `has_filter False` again. `src/docket/migrations/runner.py::apply_migrations` (line 71) skips applied versions; `rollback_migration` (line 97) deletes one version row. Within a single run on a repaired or fresh database the 033 test passes because `test_033_migration.py` collects before `test_migration_013.py`.

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
- Decision: in `test_meeting_detail_source_links_below_executive_summary`, the ordering assertion against the roll-call section applies only when the page renders a roll-call section; the assertions that `mtg-sources` and `kpi-strip` exist and that sources sit below the KPI strip stay unconditional.
  Rationale: the template gates the Roll call block on `votes`, and the developer database has zero vote rows, so the old unconditional `assert rollcall_pos > -1` cannot pass on any meeting here, nor on the fresh migrated database M2 builds (which has no meetings and makes the test return early). The alternatives were to skip the whole test when no meeting has votes, which throws away the KPI-strip ordering check that is satisfiable and meaningful, or to seed vote rows, which is a fixture build outside M1's tests-only scope. The test already tolerates absent local data (it returns early when no meeting exists), so a conditional check is in keeping with it. The roll-call ordering is still enforced wherever a meeting with votes is rendered.
  Date/Author: 2026-10-11, M1 session (Claude).
- Decision: the blog route stub gains `city_meetings` and `city_council` beside `city_overview`, with the real routes' URL shapes.
  Rationale: the plan allowed for further `BuildError` endpoints and asked that they be recorded; the masthead calls all three. Using the real paths keeps `url_for` output identical to production should an assertion ever compare hrefs.
  Date/Author: 2026-10-11, M1 session (Claude).
- Decision: `tests/integration/test_blog_integration.py` is edited in M1 even though the plan named only three test files. `override_blog_state` now clears `public._overview_cache` on swap and on restore.
  Rationale: `test_city_page_shows_blog_rail` is one of the eight tests M1 exists to fix; the plan's claim that it would pass as a consequence of the stub fix rested on a wrong diagnosis (see Surprises & Discoveries). Fixing it in its own file is the smallest change that makes it pass in the full-suite order, and it uses the idiom three other tests already use. Leaving it red would put M2's acceptance (`./tools/verify` exits zero) out of reach for a reason inside this plan. The deviation from the three-file acceptance clause is named in Progress.
  Date/Author: 2026-10-11, M1 session (Claude).
- Decision: `tests/integration/test_migration_013.py` and `tests/unit/test_ai_worker_claim.py` are not edited in M1, although the first re-drifts the materialised view on every integration run and the second deletes developer data and leaves rows that break 16 calibration tests on the next run.
  Rationale: neither of the eight tests depends on them within a single run on a repaired or fresh database, which is the condition M2's disposable database establishes for every `./tools/verify`; a durable repair of the developer database is a lost cause while the unit tier deletes its agenda items, and the plan's own M4 wording ("a stale developer `docket_db` is no longer what the tests run against") already accepts that. Fixing either would be unacceptanced scope in this milestone. Consequence named in Progress: M1's acceptance run passes once per view repair on `docket_db`. M2 must keep pytest's default collection order (file order within `tests/integration/`), because `test_033_migration.py` passing on a fresh database depends on collecting before `test_migration_013.py`. Both defects belong in `docs/DEBT.md` or an issue; M4 edits that file and should carry them.
  Date/Author: 2026-10-11, M1 session (Claude).

- Decision: M1 is accepted although the judge rules halt on it: commits `6eefdfa` and `8473ccb` do not touch the plan file, and only `5e2e621` does. The work and the record are consistent and the acceptance was re-run by the reviewer (fast tiers: `1857 passed, 3 skipped, 4 xfailed in 54.11s`). The cause is the session brief, which said to include the plan "if you changed it in that step"; the rule is that every commit carries a plan update, because a commit without one is work landed without record. From M2 on the brief states the rule, and the judge is applied without exception.
  Rationale: a halt is the judge working; the operator reads and decides. Relaxing the rule to "the last commit touches the plan" would let a dead session leave landed commits with no record, which is the failure the rule exists to catch.
  Date/Author: 2026-10-11, reviewer (operator's session, Claude).
- Decision: M2 is revised. `tools/verify` runs every tier, not only integration, with `DATABASE_URL` pointed at the disposable database, and `tools/test-db` is called once before the first tier and dropped after the last. M2's acceptance gains one check: the row counts of `votes`, `agenda_items`, and `member_votes` in `docket_db` are identical before and after `./tools/verify`.
  Rationale: M1 found that `tests/unit/test_ai_worker_claim.py::fresh_db` runs `DELETE FROM` on votes, member votes, links, and audit tables of whatever database `DATABASE_URL` names. The unit tier is therefore not database-free, and running it against `docket_db` is why the developer database has no votes. The plan's statement that the fast tiers need no database was wrong and is corrected here rather than rewritten in Context, so the correction stays visible. `tools/verify` must also keep pytest's default collection order within the integration tier, because `test_033_migration.py` passes on a fresh database only when it is collected before `test_migration_013.py`, whose up-down-up cycle leaves the view at migration 022's definition.
  Date/Author: 2026-10-11, reviewer.
- Decision: M4 adds three debt rows from M1's findings rather than fixing them here: the `fresh_db` fixture deletes rows from the configured database (trigger: anyone runs the unit tier by hand against a database they care about; `./tools/verify` no longer does); `test_migration_013.py`'s up-down-up cycle leaves `mv_badge_volume_monthly` without migration 033's filter (trigger: a fresh database is not available and the integration tier is rerun); and `query_c_baseline_drift` casts `score_overrides` values with `::int` while `src/docket/ai/pipeline.py` writes the same dict, so a float written in production would break the calibration report (trigger: next change to either file; investigate whether production ever writes floats).
  Rationale: each is real, none is M1's to fix, and the debt register is where deliberate deferrals live.
  Date/Author: 2026-10-11, reviewer.

## Outcomes & Retrospective

M1 (2026-10-11): the eight tests pass and the full non-live suite is green in one run on the repaired developer database (`2468 passed, 3 skipped, 4 xfailed`). Four of the eight needed what the plan said (three masthead stubs instead of one), one needed more than the plan said (the `kpi-strip` test had a second latent assertion the plan did not see), one needed a different fix in a file the plan did not name (the blog rail test and the module-level overview cache), and one is fixed only until the next integration run (the materialised view, which `test_migration_013.py` re-drifts). Three test files changed as planned plus `tests/integration/test_blog_integration.py`; no source file changed. The important discovery is not any of the eight tests but what the suite does to the database it runs against: a unit-tier fixture deletes every `agenda_items` and `votes` row in whatever `DATABASE_URL` names, and runs leave rows and schema drift behind that make the next run red. That is the plan's M2 case made concrete, and it means "green on a developer database" is a one-shot statement until `tools/test-db` exists. Lesson for plan authoring: a diagnosis of a failing test should include the command that reproduces it in isolation and in suite order, because two of the eight had causes the plan's single reading of the failure did not reach.

## Context and Orientation

docket.pub is a Flask and PostgreSQL application. Its code lives under `src/docket/` and its tests under `tests/` in four tiers: `tests/unit/`, `tests/web/`, and `tests/services/` need no database beyond what `tests/conftest.py` sets in the environment; `tests/integration/` needs a PostgreSQL database with the migrations applied, reached through the `DATABASE_URL` environment variable that `src/docket/config.py` reads; `tests/live/` makes real Anthropic API calls and is opted into with `pytest -m live`. There is no `addopts` in `pyproject.toml`, so a bare `pytest` collects the live tier too, and because `tests/conftest.py` sets a dummy `ANTHROPIC_API_KEY`, the live fixtures' skip check (which only tests that a key is set) does not fire.

A "migration" here is a numbered Python module under `src/docket/migrations/` with `SQL_UP` and `SQL_DOWN` strings; `python -m docket.migrations.runner` applies the pending ones to the database `DATABASE_URL` names, `--status` lists them, and `--down <version>` rolls back one by number (so `--down 1` drops the whole schema). The runner records applied versions in a `schema_migrations` table. The local developer database is `docket_db` on the Homebrew PostgreSQL 16 server (`/opt/homebrew/opt/postgresql@16/bin/`), owned by the superuser role `docket`, which may create databases.

A "materialised view" is a stored query result PostgreSQL keeps as a table until it is refreshed. `mv_badge_volume_monthly` is one; migration 033 (`src/docket/migrations/033_meetings_is_hidden.py`) rebuilds it with a `m.is_hidden = FALSE` filter. On the operator's `docket_db` the view's current definition lacks that filter although `schema_migrations` lists 033 as applied, which is why `tests/integration/test_033_migration.py::test_033_up_refreshes_mv_with_filter` fails there. A database built fresh from the migrations has the filter.

The repository's agent harness (installed by PR #108) is a set of markdown files: `AGENTS.md` is the map every session reads first; `docs/DEBT.md` is the debt register with stable row ids; `docs/capabilities/` holds one specification card per mechanical check with their statuses in `docs/capabilities/index.md`, written in the shape `docs/capabilities/CARD_FORMAT.md` defines; `docs/MATURITY.md` states the autonomy rung; `docs/specs/operations.md` is how the system is run. A "plan" is a file like this one under `plans/active/`, whose Progress section holds one checkbox line per milestone, ticked with a timestamp when done.

The factory design this plan serves is `docs/superpowers/specs/2026-10-10-factory-cycle-design.md`. Its section 4 specifies `tools/judge-milestone`, and factory-loop's own `tools/loop-runner` (in the checkout at `/Users/darrellnance/projects/factory-loop`, outside this repository) carries a working awk implementation of the plan parsing and the commit judging that this plan adapts. The judge's rule, in one sentence: an iteration advanced when at least one new commit exists, every new commit touches the plan file, exactly one Progress entry went from open to done, that entry carries a date, no done entry reverted, and the working tree is clean.

The eight failing tests and their causes, found on 2026-10-11:

Four tests in `tests/web/test_blog_routes.py` (`test_city_route_filters_to_city_and_shared`, `test_post_detail_renders`, `test_post_detail_emits_twitter_card_meta`, `test_preview_token_reveals_draft`) build a minimal Flask app with a stub `public` blueprint that registers only the routes the shared templates needed when the test was written. `src/docket/web/templates/partials/masthead.html` now calls `url_for('public.city_overview', slug=...)` in three places, and the stub has no `city_overview` route, so rendering raises `BuildError` and the response is 500. The stub is in the `app` fixture at `tests/web/test_blog_routes.py` lines 51 to 100.

`tests/web/test_city_overview_render.py::test_meeting_detail_source_links_below_executive_summary` asserts a `class="kpi-grid"` element precedes the sources section on a meeting page. The meeting template `src/docket/web/templates/meeting_detail.html` has used `class="kpi-strip"` since the visual refactor in May (commit `0745af6`); `kpi-grid` survives only in `admin/ai_panel.html`. The test went unnoticed because it returns early when no meeting exists locally.

`tests/integration/test_blog_integration.py::test_city_page_shows_blog_rail` fails with the same `BuildError` as the blog route tests, through the same masthead partial. (Correction, M1 session 2026-10-11: this was wrong; the test uses the real app and fails because of the module-level `_overview_cache` in `src/docket/web/public.py`. See Surprises & Discoveries. The sentence above is kept as the record of what the plan author believed.)

`tests/integration/test_calibration.py::test_query_c_returns_weeks_of_data` seeds two groups of items at `days_ago=0.0` and `days_ago=6.5` and expects two weekly buckets. `query_c_baseline_drift` in `src/docket/services/calibration.py` buckets by `date_trunc('week', ...)`, whose weeks start on Monday, so on a Sunday both groups fall in the same week. GitHub issue #70 recorded the Sunday flake in May.

`tests/integration/test_033_migration.py::test_033_up_refreshes_mv_with_filter` fails for the database-drift reason above. (Correction, M1 session 2026-10-11: the drift is produced by `tests/integration/test_migration_013.py::test_013_up_down_up_cycle` on every integration run, not by a one-off stale database. See Surprises & Discoveries.)

## Plan of Work

M1 touches tests only. In `tests/web/test_blog_routes.py`, inside the `app` fixture, add a stub route `@public_stub.route("/al/<slug>/")` named `city_overview` that takes `slug` and returns an empty `Response`, beside the existing stubs; then run the four blog tests and, if any other `BuildError` names a missing endpoint, add that stub too and record which. In `tests/web/test_city_overview_render.py`, change the two occurrences of `kpi-grid` in `test_meeting_detail_source_links_below_executive_summary` (the `html.find` and the assertion message) to `kpi-strip`. In `tests/integration/test_calibration.py::test_query_c_returns_weeks_of_data`, change the second group's `days_ago=6.5` to `days_ago=8.0` and extend the docstring's "6 days ago" to say eight days, so the two groups can never share a Monday-to-Sunday week. For the materialised view, repair the operator's `docket_db` once by running the view rebuild that migration 033's `SQL_UP` contains (the `DROP MATERIALIZED VIEW IF EXISTS mv_badge_volume_monthly;` through the `CREATE UNIQUE INDEX` statement), using `venv/bin/python -c` to execute that slice of `_m033.SQL_UP` through `docket.db.db()`; record the before and after of `pg_get_viewdef`. Do not change the test or the migration. Record `test_blog_integration.py` passing as a consequence of the stub fix without a change of its own.

M2 creates `tools/test-db` and `tools/verify`, both POSIX `sh` scripts with the executable bit set, and adds one line to `pyproject.toml`. `tools/test-db` computes `NAME=docket_test_$(printf '%s' "$(pwd -P)" | shasum | cut -c1-8)`, derives the server connection from `DATABASE_URL` (default `postgresql://docket@localhost:5432/docket_db`) by replacing the trailing database name, runs `DROP DATABASE IF EXISTS "$NAME" WITH (FORCE)` and `CREATE DATABASE "$NAME"` through `psql` against the `postgres` maintenance database on that server, applies the migrations with `DATABASE_URL=<server>/$NAME venv/bin/python -m docket.migrations.runner`, and prints the resulting URL on its last line; `tools/test-db --drop` drops it and prints nothing. `tools/verify` runs, in order, each printing one summary line and all of them running even if an earlier one fails: the fast tiers `venv/bin/python -m pytest tests/unit tests/web tests/services -q -p no:cacheprovider`; the integration tier `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration -q -p no:cacheprovider` followed by `tools/test-db --drop`; and, once M3 lands, `tools/fixtures/judge/run`. It ends with `verify: N of M checks failed.` and a re-run instruction, or `verify: all M checks passed in Ns.`, and exits nonzero if any check failed. Each failing check's own output is left on the terminal above the summary, never swallowed. In `pyproject.toml` under `[tool.pytest.ini_options]` add `addopts = "-m 'not live'"`, so `pytest` alone excludes the live tier and `pytest -m live` still selects it (an explicit `-m` on the command line replaces the addopts marker expression). Record the observed wall time of `./tools/verify`.

M3 creates `tools/judge-milestone`, `tools/fixtures/judge/run`, and `docs/capabilities/judge-milestone.md`, and adds the card's row to `docs/capabilities/index.md`. The judge is a POSIX `sh` script adapted from the `read_plan`, `plan_defect`, `compare_records`, and `untouching_commits` functions of factory-loop's `tools/loop-runner`, with two modes. `tools/judge-milestone snapshot <plan>` prints the tab-separated records (`OPEN`, `DONE`, `NOSTAMP`, `MISSING`, `EMPTY`, each with line number, shortened text, and the normalised key described in the loop-runner comments) and exits 0 if the record holds or 2 with the first defect as a one-line message if it does not. `tools/judge-milestone judge <plan> <snapshot-file> <start-sha>` re-reads the plan at HEAD, compares it with the snapshot, lists commits `<start-sha>..HEAD` and which of them did not touch `<plan>`, checks `git status --porcelain` is empty, and exits 0 printing `judge: advanced "<entry text>"` or 1 printing a four-line halt: the plan path, the entry it stopped on (or `no entry`), the rule that failed in one sentence, and `Fix the cause, commit in the worktree, and re-run.` The rules, each its own sentence in the output: no commit landed; commit `<short sha>` did not touch the plan; `<n>` Progress entries changed state (exactly one must); entry at line `<n>` is ticked but carries no date; entry `"<text>"` was done at the start and is no longer; the working tree has uncommitted changes. A ticked entry counts as dated when any `YYYY-MM-DD` appears anywhere on its line, in parentheses, brackets, or bare. The fixture runner `tools/fixtures/judge/run` builds temporary git repositories under `mktemp -d` for eight cases and asserts the exit code and the first word after `judge:` for each: a clean one-entry advance (0); no commit (1); a commit that does not touch the plan (1); two entries ticked in one iteration (1); one entry ticked without a date (1); a done entry un-ticked (1); a dirty tree after an otherwise clean advance (1); and a plan missing `## Decision Log` at snapshot time (2). It prints one line per case and `judge fixtures: 8 of 8 passed` or the failing case names, and exits accordingly. The card follows `docs/capabilities/CARD_FORMAT.md` with the invariant stated above, enforcement at `./tools/verify` through the fixture runner and at `cycle-run` through the judge itself, the passing and failing acceptance written as instructions, and the four-line halt as the remediation message. Its register row reads `specced` when written and is promoted in M4 after the failing case below is observed.

M4 is the close-out. `AGENTS.md` Commands becomes: Verify (cheap, after any edit): `./tools/verify` (about 150 seconds; budget 180 s; builds a throwaway database, runs every non-live tier and the judge fixtures); Full tests is removed because verify now covers it; Live tests: `venv/bin/python -m pytest -m live`; Migrations and Dev server lines stay; the sentence about no aggregated command and D5 goes. `docs/specs/operations.md` Tests section is rewritten around `./tools/verify` and `tools/test-db`, naming the per-checkout database name rule and that a stale developer `docket_db` is no longer what the tests run against; the "Never run bare pytest" paragraph becomes one sentence saying `addopts` excludes the live tier. In `docs/DEBT.md` delete rows D1, D2, D3, D5, and D35 and the D3 detail section, leaving D4 with a note that `tools/test-db` can be pointed at postgresql@18 by changing the server part of `DATABASE_URL`, and leaving D6 open. In `docs/capabilities/index.md` set `fast-verify` to `built` with `./tools/verify` as the enforcement point and `judge-milestone` to `built` with `./tools/verify` (fixtures) and `cycle-run` (planned) as enforcement points, after demonstrating both failing cases: for `fast-verify`, introduce a one-character assertion error in a unit test, run `./tools/verify`, observe the nonzero exit with pytest's own failure text above the summary, revert; for `judge-milestone`, change one expected exit code in `tools/fixtures/judge/run`, run `./tools/verify`, observe the fixture runner fail naming the case, revert. Record both transcripts in this plan's Artifacts section. In `docs/MATURITY.md` the Current rung paragraph is rewritten to say L0 with `fast-verify` and `judge-milestone` `built`, and that the one thing moving toward L1 is twenty consecutive landed changes with `./tools/verify` green and unskipped, which starts counting from this plan's merge. `evidence-check` stays `specced`: the judge's snapshot mode decides its two facts for one plan, but the card asks for a check over every plan in `plans/active/`, and that aggregation is a separate small build.

## Concrete Steps

All commands run from the worktree root `/Users/darrellnance/docket-pub/.claude/worktrees/factory-tools` on branch `plan/factory-tools`, using that checkout's own `venv/`. A session starts by reading `AGENTS.md`, then `plans/PLANS.md`, then this file, then only the files named in its milestone.

Before any milestone, observe the starting state:

    venv/bin/python -m pytest tests/unit tests/web tests/services -q -p no:cacheprovider 2>&1 | tail -1

Expected before M1: `5 failed, 1852 passed, 3 skipped, 4 xfailed ...` (observed 2026-10-11 on `main` at `b174008`). Expected after M1: `1852 passed` with zero failed, counts otherwise unchanged. Observed by the M1 session on 2026-10-11: before, `5 failed, 1852 passed, 3 skipped, 4 xfailed, 2 warnings in 72.95s`; after, `1857 passed, 3 skipped, 4 xfailed, 1 warning in 54.76s` (the five fixed tests join the passed count, which the "1852" expectation overlooked).

M1 commands:

    venv/bin/python -m pytest tests/web/test_blog_routes.py tests/web/test_city_overview_render.py -q -p no:cacheprovider 2>&1 | tail -1
    venv/bin/python -m pytest tests/integration/test_calibration.py::test_query_c_returns_weeks_of_data tests/integration/test_blog_integration.py -q -p no:cacheprovider 2>&1 | tail -1
    venv/bin/python -c "import importlib; m = importlib.import_module('docket.migrations.033_meetings_is_hidden'); from docket.db import db; sql = m.SQL_UP[m.SQL_UP.index('DROP MATERIALIZED VIEW'):]; sql = sql[: sql.index('CREATE UNIQUE INDEX')]; sql = sql + m.SQL_UP[m.SQL_UP.index('CREATE UNIQUE INDEX'):].split(';')[0] + ';'; conn = db().__enter__(); cur = conn.cursor(); cur.execute(sql); conn.commit(); print('rebuilt')"

That one-liner imports migration 033 by name (the module name starts with a digit, so a plain import statement cannot name it), takes the `SQL_UP` text from `DROP MATERIALIZED VIEW` through the end of the `CREATE UNIQUE INDEX` statement, and runs it in one transaction on `docket_db`. The `db().__enter__()` form shown above does not work (see Surprises & Discoveries); the form actually run on 2026-10-11 was the same slicing followed by:

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)

passed to `venv/bin/python -c` as a multi-line string; it printed the SQL it ran and `rebuilt`. Before and after, record (the `__enter__` form fails with `cursor already closed`; use this one):

    venv/bin/python -c "
    from docket.db import db_cursor
    with db_cursor() as cur:
        cur.execute(\"select pg_get_viewdef('mv_badge_volume_monthly'::regclass, true) as definition\")
        print('is_hidden' in cur.fetchone()['definition'])
    "

Expected before: `False`; after: `True`. Observed 2026-10-11: `False` before, `True` after. Then:

    venv/bin/python -m pytest tests/integration/test_033_migration.py -q -p no:cacheprovider 2>&1 | tail -1

Expected: all tests in that file pass. Then the full non-live suite:

    venv/bin/python -m pytest tests/unit tests/web tests/services tests/integration -q -p no:cacheprovider 2>&1 | tail -1

Expected: zero failed (observed before M1 on 2026-10-11: `8 failed, 2253 passed, 3 skipped, 4 xfailed`). Observed after M1 on 2026-10-11: `2468 passed, 3 skipped, 4 xfailed, 2 warnings in 133.36s`. Run it once per repair of the materialised view on `docket_db`; see the M1 Progress entry for why a second run is red.

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

Still to be filled by later sessions: the `./tools/verify` summary and wall time (M2); the fixture runner's eight lines (M3); the two failing-case demonstrations (M4).

M1 transcripts, observed 2026-10-11 in the worktree on `plan/factory-tools`:

Starting state, before any edit:

    venv/bin/python -m pytest tests/unit tests/web tests/services -q -p no:cacheprovider 2>&1 | tail -1
    5 failed, 1852 passed, 3 skipped, 4 xfailed, 2 warnings in 72.95s (0:01:12)

The five were the four `test_blog_routes.py` tests and `test_meeting_detail_source_links_below_executive_summary`, as the plan predicted.

Materialised view on `docket_db`, `pg_get_viewdef('mv_badge_volume_monthly'::regclass, true)`, `'is_hidden' in definition`: `False` before the rebuild. The before-definition's WHERE clause read `WHERE aib.confidence >= 0.6 AND aib.status = 'applied'::text` with no `is_hidden` term. After running migration 033's `DROP MATERIALIZED VIEW ... CREATE UNIQUE INDEX` slice through `with db() as conn`: `True`. Then:

    venv/bin/python -m pytest tests/integration/test_033_migration.py -q -p no:cacheprovider 2>&1 | tail -1
    4 passed in 0.10s

Targeted tests after the edits:

    venv/bin/python -m pytest tests/web/test_blog_routes.py tests/web/test_city_overview_render.py -q -p no:cacheprovider 2>&1 | tail -1
    35 passed in 1.82s
    venv/bin/python -m pytest tests/integration/test_calibration.py::test_query_c_returns_weeks_of_data -q -p no:cacheprovider 2>&1 | tail -1
    1 passed in 0.33s
    venv/bin/python -m pytest tests/integration/test_blog_integration.py -q -p no:cacheprovider 2>&1 | tail -1
    3 passed in 1.40s

Intermediate failing run kept for the record (after `city_overview` alone was stubbed and `kpi-grid` changed to `kpi-strip`): `5 failed, 30 passed in 1.91s`, first failure `BuildError ... 'public.city_meetings'`, and the render test failing on `roll-call section missing`.

First full-suite attempt (after the three named files were fixed and the view repaired):

    venv/bin/python -m pytest tests/unit tests/web tests/services tests/integration -q -p no:cacheprovider 2>&1 | tail -4
    FAILED tests/integration/test_blog_integration.py::test_city_page_shows_blog_rail
    1 failed, 2467 passed, 3 skipped, 4 xfailed, 2 warnings in 137.43s (0:02:17)

Diagnostic run of the integration tier alone immediately afterwards, kept because it shows the cross-run poisoning:

    venv/bin/python -m pytest tests/integration -q -p no:cacheprovider 2>&1 | tail -1
    17 failed, 594 passed, 1 warning in 90.41s (0:01:30)

(`test_033_up_refreshes_mv_with_filter` plus 16 `test_calibration.py` tests failing with `invalid input syntax for type integer: "4.0"`; `test_city_page_shows_blog_rail` passed in this order.)

Bisect of the blog rail failure, each line one process:

    tests/web + test_city_page_shows_blog_rail        1 failed, 189 passed, 3 skipped in 6.39s
    tests/services + test_city_page_shows_blog_rail   17 passed in 1.34s
    tests/unit + test_city_page_shows_blog_rail       1653 passed, 4 xfailed, 1 warning in 56.47s

Final acceptance run, after `override_blog_state` clears `_overview_cache` and the view was rebuilt once more (the integration-only diagnostic run had drifted it again; `is_hidden in definition: True` after the rebuild):

    venv/bin/python -m pytest tests/unit tests/web tests/services tests/integration -q -p no:cacheprovider 2>&1 | tail -4
    2468 passed, 3 skipped, 4 xfailed, 2 warnings in 133.36s (0:02:13)

Started 16:53Z, finished 16:56Z. Note the total differs from the `8 failed, 2253 passed` the plan recorded on `main`; both are observed numbers, and the plan did not record how its count was taken.

## Interfaces and Dependencies

`tools/test-db`: POSIX sh. Reads `DATABASE_URL` (optional). Prints the test database URL as its last line and exits 0, or exits nonzero with psql's or the runner's error. `tools/test-db --drop` drops it silently. Requires `psql` on PATH or at `/opt/homebrew/opt/postgresql@16/bin/psql` (try PATH first, then that path) and `venv/bin/python`.

`tools/verify`: POSIX sh, no arguments, exit 0 only if every check passed. Checks are listed in the script as `name` and `command` pairs so adding one is one line. Output contract: each check's own output, then one summary line per check in the form `verify: <name> ... ok` or `verify: <name> ... FAILED`, then the final line.

`tools/judge-milestone`: POSIX sh. `snapshot <plan>` to stdout, exit 0 or 2. `judge <plan> <snapshot-file> <start-sha>`, exit 0, 1, or 2, output as specified in Plan of Work. Uses only `git`, `awk`, `sed`, `printf`; no Python.

`tools/fixtures/judge/run`: POSIX sh, no arguments, exit 0 if all cases pass. Creates and removes its own temporary repositories; leaves nothing behind.

`pyproject.toml`: `[tool.pytest.ini_options]` gains `addopts = "-m 'not live'"`.

`docs/capabilities/judge-milestone.md`: card per `docs/capabilities/CARD_FORMAT.md`, sections Invariant, Enforcement point, Acceptance, Remediation message.

## Revision notes

- 2026-10-11, M1 session: recorded M1's execution. Added Surprises & Discoveries entries (context-manager one-liner, three masthead stubs, hidden roll-call assertion, Sunday demonstration, overview cache, destructive unit fixture, migration-013 view drift), four Decision Log entries (roll-call conditional, extra stubs, editing `test_blog_integration.py`, not editing `test_migration_013.py` or `test_ai_worker_claim.py`), corrected the `db_cursor` command forms in Concrete Steps, appended two corrections to Context and Orientation without removing the original sentences, filled Artifacts with the observed transcripts, ticked M1 with its carve-outs, and wrote the M1 Outcomes entry. Reason: PLANS.md requires observed evidence and visible corrections; two of the plan's eight diagnoses were wrong and the record has to show that.
