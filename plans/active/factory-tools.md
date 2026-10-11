# Make the test suite green, give the repository one verify command on a disposable database, and build the milestone judge

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

Today an agent working in this repository cannot prove its change is safe with one command. The published verify line is a pytest invocation that fails on eight tests nobody touched, the integration tier runs against the developer's own database and can be poisoned by the previous run, and there is no script that decides whether a milestone session actually landed its work. After this plan, `./tools/verify` runs from any checkout, builds a throwaway database from the migrations, runs every non-live test tier, runs the milestone judge's self-test, and exits zero on `main`. A second script, `tools/judge-milestone`, reads a plan file and the git history and says, from evidence alone, whether a session advanced exactly one milestone. Both are the mechanical ground the factory's `cycle-run` workflow (the next plan) stands on. You can see it working by running `./tools/verify` and reading one green summary line per check.

## Progress

- [x] (2026-10-11 16:56Z) M1: the eight failing tests pass on a developer database. Acceptance run `venv/bin/python -m pytest tests/unit tests/web tests/services tests/integration -q -p no:cacheprovider` printed `2468 passed, 3 skipped, 4 xfailed, 2 warnings in 133.36s`, zero failed. Carve-outs against the stated acceptance: (1) the diff touches four test files, not three; `tests/integration/test_blog_integration.py` needed its own fix because the plan's diagnosis of that test was wrong (Decision Log). (2) The acceptance holds for the first full run after the `mv_badge_volume_monthly` repair; every run of `tests/integration` re-drifts the view through `test_migration_013.py`, and the unit tier leaves rows that break 16 calibration tests on a following run, so a second run on `docket_db` is red again for reasons outside the eight tests and outside M1's scope (Surprises & Discoveries, Decision Log). M2's disposable database is the durable condition under which the suite is green.
- [x] (2026-10-11 17:14Z) M2: `tools/verify` and `tools/test-db` exist; every tier runs on a disposable database named from the checkout; bare `pytest` no longer collects live tests. Acceptance run `./tools/verify; echo "exit=$?"` printed `verify: all 2 checks passed in 144s.` and `exit=0` (fast tiers `1856 passed, 4 skipped, 4 xfailed` in 61 s, integration `611 passed` in 83 s); `docket_db` row counts were `votes 0`, `agenda_items 1`, `member_votes 0` immediately before and immediately after, as the reviewer's revised acceptance requires; collect-only live count `0` bare and `12` with `-m live`; the disposable database `docket_test_692415bc` was gone after the run. Carve-outs against the stated acceptance: (1) the "second checkout builds a differently named database" clause was shown by hashing the main checkout's path string (`docket_test_0a1dedec` versus this worktree's `docket_test_692415bc`), not by running `tools/test-db` in a second checkout, because this session may not touch any other directory. (2) The fast tiers report `4 skipped` on the fresh database where M1 saw `3 skipped` on `docket_db`: four data-dependent `tests/web/test_p5_translation.py` tests skip when no meetings, tagged items, search hits, or coverage rows exist (Surprises & Discoveries); nothing fails, but the fresh database tests one case fewer than the developer database did.
- [x] (2026-10-11 17:31Z) M3: `tools/judge-milestone` exists with its fixture self-test under `tools/verify`, and its card is in the register. Acceptance: `tools/fixtures/judge/run` printed eight `ok` case lines and `judge fixtures: 8 of 8 passed`, exit 0; `./tools/verify; echo "exit=$?"` printed `verify: judge-fixtures ... ok (2s)` as its third check and `verify: all 3 checks passed in 147s.`, `exit=0` (fast tiers `1856 passed, 4 skipped, 4 xfailed` in 61 s, integration `611 passed` in 83 s, fixtures 2 s); `tools/judge-milestone snapshot plans/active/factory-tools.md` exited 0 with `DONE` for M1 and M2 and `OPEN` for M3 and M4 (measured without the plan's `| head -5` pipe, which masks the exit status; Surprises & Discoveries); `docs/capabilities/judge-milestone.md` exists with the four mandatory sections and `docs/capabilities/index.md` carries its `specced` row. No carve-out against the stated acceptance. Details the plan left open were resolved and logged (Decision Log): verdict words `advanced`/`halt`/`defect`, the plan read from `HEAD:`, rule order, key normalisation for bracketed and bare dates, hermetic git configuration in the fixture repositories.
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
- Observation (M2, 2026-10-11): the `DATABASE_URL` the tests actually use does not come from the shell or from `src/docket/config.py`'s built-in default. The shell has no `DATABASE_URL`; `config.py` calls `load_dotenv()`, which walks up from the file's directory and finds `/Users/darrellnance/docket-pub/.env` above the worktree, giving `postgresql://docket@localhost:5432/docket_db` (no password), while the code default is `postgresql://docket:docket_dev@localhost:5432/docket_db`. The plan's stated `tools/test-db` default matches the `.env` value by coincidence. `tools/test-db` therefore asks `docket.config` for the URL when the environment has none, so it builds on the server the tests would otherwise reach.
  Evidence: `echo ${DATABASE_URL:-<unset>}` printed `<unset>`; `venv/bin/python -c "from docket.config import DATABASE_URL; print(DATABASE_URL)"` printed `postgresql://docket@localhost:5432/docket_db`; `venv/bin/python -c "from dotenv import find_dotenv; print(find_dotenv(usecwd=True))"` printed `/Users/darrellnance/docket-pub/.env`. Because `load_dotenv` does not override variables already set, exporting `DATABASE_URL` from `tools/verify` wins over the `.env`.
- Observation (M2): the plan's `DATABASE_URL=$(tools/test-db)` idiom and its "prints the migration runner's output and ends with the URL" description conflict unless the runner's output leaves stdout; `$(...)` captures every stdout line, not the last one. Resolved by sending progress and the runner's output to stderr (Decision Log); a terminal still shows both.
  Evidence: with stderr redirected to a file, `URL=$(tools/test-db)` gave `URL=postgresql://docket@localhost:5432/docket_test_692415bc` exactly, and the file held 68 lines (`test-db: building ...`, 33 `Applying`/`Applied` pairs, `All migrations applied.`).
- Observation (M2): on the fresh database the fast tiers pass `1856` and skip `4`, against M1's `1857` passed and `3` skipped on `docket_db`. All four skips are `tests/web/test_p5_translation.py` tests that call `pytest.skip` when the database has no rows to render; `docket_db` evidently satisfied one of them. A fresh database is cleaner but also emptier, so the suite's data-dependent assertions run only where someone has seeded data; a seeding step for `tools/test-db` is a candidate for the debt register, not for this milestone.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_query_hidden_meetings.py tests/web/test_p5_translation.py -q -rs -p no:cacheprovider` printed `SKIPPED [1] tests/web/test_p5_translation.py:38: No Birmingham meetings seeded in this env`, `:64: No tagged items seeded in this env`, `:123: No search hits for 'council' in this env`, `:212: No coverage entries in DB to permalink-test`, then `34 passed, 4 skipped in 2.19s`.
- Observation (M2): building the disposable database is effectively free; all 33 migrations applied in under one second of wall time (`verify: test-db ... ok (0s)`), so the verify budget is spent entirely in pytest: 61 s fast tiers, 83 s integration, 144 s total, within the 180 s budget the Decision Log sets.
  Evidence: the `./tools/verify` summary lines in Artifacts.
- Observation (M3, 2026-10-11): the plan's M3 command `tools/judge-milestone snapshot plans/active/factory-tools.md | head -5; echo "exit=$?"` reports `head`'s exit status, not the judge's, so it would print `exit=0` even on a defective plan. The judge's exit was measured separately, without the pipe.
  Evidence: `tools/judge-milestone snapshot plans/active/factory-tools.md >/dev/null; echo "snapshot exit=$?"` printed `snapshot exit=0`; the piped form also printed `exit=0`, but for the wrong reason.
- Observation (M3): judged against the real M2 history before any M3 commit, the judge passed rules one to five and halted on the sixth. With the snapshot taken from `git show 0bc385c:plans/active/factory-tools.md` and `0bc385c` as the start, the four commits to `d6f2466` all touch the plan, exactly one entry (M2) became done and dated, and nothing reverted; the halt was `the working tree has uncommitted changes.`, caused by the untracked `tools/judge-milestone` itself. This also shows the reviewer's `d6f2466` edits to the plan did not alter the M1 or M2 entry text, since an edited done entry would have read as a revert (Decision Log).
  Evidence: `judge: halt plans/active/factory-tools.md`, `judge: entry "(2026-10-11 17:14Z) M2: ..."`, `judge: the working tree has uncommitted changes.`, `judge: Fix the cause, commit in the worktree, and re-run.`, exit 1.
- Observation (M3): the local git configuration points `core.hooksPath` at the main checkout's `.git/hooks`, which holds only `*.sample` files, so no hook runs on commits from this worktree; nothing was bypassed and nothing needed to be.
  Evidence: `git config --local --list | grep -i hooks` printed `core.hookspath=/Users/darrellnance/docket-pub/.git/hooks`; `ls` of that directory listed only `.sample` files.

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
- Decision: the M2 session did not run the `AGENTS.md` cheap verify (`venv/bin/python -m pytest tests/unit tests/web tests/services -q -p no:cacheprovider`) against `docket_db` as its starting-state observation. The row counts of `votes`, `agenda_items`, and `member_votes` were recorded instead, before any edit, and the fast tiers are first observed in this session inside `./tools/verify` on the disposable database.
  Rationale: M1 established that `tests/unit/test_ai_worker_claim.py::fresh_db` runs `DELETE FROM agenda_items` (and votes, member votes, audit rows) against whatever `DATABASE_URL` names, so the published cheap verify would have changed the very counts M2's revised acceptance compares. The reviewer's re-run at `0bc385c` (`1857 passed, 3 skipped, 4 xfailed in 54.11s`, a reported claim, not observed in this session) stands as the pre-M2 fast-tier state.
  Date/Author: 2026-10-11, M2 session (Claude).
- Decision: `tools/test-db` resolves the base `DATABASE_URL` by asking `docket.config` when the variable is not set in the environment, falling back to `postgresql://docket@localhost:5432/docket_db` only if that import fails; it `cd`s to the repository root before computing `pwd -P`, so the database name is the same from any working directory inside the checkout; and it writes its progress line and the migration runner's output to stderr, leaving the URL as the only stdout line.
  Rationale: the tests reach the server through `docket.config`, `.env` included (Surprises & Discoveries), so the disposable database must be created on that same server; a name that varied with the caller's subdirectory would defeat the drop-before-create idempotence; and `DATABASE_URL=$(tools/test-db)`, the idiom the plan writes for `tools/verify`, needs a single-line stdout.
  Date/Author: 2026-10-11, M2 session (Claude).
- Decision: when `tools/test-db` fails inside `tools/verify`, no test tier runs; each check is reported as `FAILED (not run: no test database)` and verify exits 1. The plan's "all checks run even if an earlier one fails" rule applies to the checks, not to the database build they depend on.
  Rationale: without the exported `DATABASE_URL`, pytest would fall back to `docket_db` through `.env`, and the unit tier would delete its rows; the revised acceptance (row counts unchanged) forbids exactly that, and it is the one failure mode where running on is worse than stopping.
  Date/Author: 2026-10-11, M2 session (Claude).
- Decision: `tools/verify` drops the disposable database through a `trap ... EXIT`, so the drop runs on every exit path including a failed check or an interrupt; the build is not counted among the checks (the final line says `2 checks` in M2 and will say `3` after M3) but gets its own `verify: test-db ... ok <url>` summary line; and each check's summary line carries its wall time in parentheses, `verify: <name> ... ok (61s)`, a suffix on the contract the Interfaces section states rather than a change to its prefix.
  Rationale: a leaked database after a red run would make the next run's drop-before-create do the cleanup anyway, but an operator reading `pg_database` should not find strays; counting the build as a check would make the plan's expected `all 2 checks passed` wrong; and the per-check seconds are the evidence the 180 s budget decision needs on every run.
  Date/Author: 2026-10-11, M2 session (Claude).

- Decision: M2 is accepted. The judge rules pass (three commits, each touching the plan, one entry ticked and dated, none reverted, clean tree). The reviewer re-ran `./tools/verify` independently: `test-db ok (1s)`, `unit+web+services ok (58s)`, `integration ok (80s)`, `all 2 checks passed in 139s`, exit 0. Two leftover databases named `docket_test_umami_*` exist on the local server; they come from the analytics test fixtures in the existing suite, not from `tools/test-db`, and M4 records them as a debt row (trigger: next change to the analytics tests). The M2 session committed once with `-c core.hooksPath=/dev/null`; no hooks exist, so nothing was bypassed, but sessions should not disable hooks, and the brief for later milestones says so.
  Rationale: evidence re-observed by the reviewer, not taken from the session's report.
  Date/Author: 2026-10-11, reviewer (operator's session, Claude).

- Decision: every line the judge prints begins `judge: `, and the first word after it is one of three verdicts: `advanced` (exit 0), `halt` (exit 1, the first of the four halt lines, followed by the plan path), or `defect` (exit 2). In `snapshot` mode the records go to stdout and the defect line to stderr, so `snapshot <plan> > file` leaves a usable record file even when it exits 2.
  Rationale: the plan says the fixture runner asserts "the exit code and the first word after `judge:`", which needs one word per verdict on the first line; it does not say what the snapshot's one-line defect message looks like or where it goes, and a defect mixed into the record file would corrupt the next `judge` comparison.
  Date/Author: 2026-10-11, M3 session (Claude).
- Decision: `judge` reads the plan from `git show HEAD:<path>`, not from the working file; `snapshot` reads the working file it is given. The judge halts on a plan that is absent at HEAD with `judge: defect <plan> is not in the tree at HEAD`, exit 2.
  Rationale: the plan says the judge "re-reads the plan at HEAD", and the thing being judged is landed work; an uncommitted edit to the plan is caught by the clean-tree rule rather than silently counted as progress. When the tree is clean the two readings are the same file.
  Date/Author: 2026-10-11, M3 session (Claude).
- Decision: the rules are checked in this order, and the first failure halts: no commit landed; a commit did not touch the plan; the plan at HEAD has a structural defect (a required living section missing or empty, which is exit 2 rather than a halt); not exactly one entry changed state; a ticked entry has no date; a done entry reverted; the tree is dirty. In `snapshot` mode a ticked entry without a date is a defect (exit 2), as it is in factory-loop; in `judge` mode any undated ticked entry at HEAD is the halt rule the plan names ("entry at line n is ticked but carries no date"), whether or not it was ticked in this session. The second line of a halt names the entry that became done when exactly one did, the offending entry for the no-date and reverted rules, and `no entry` otherwise.
  Rationale: the plan lists six rules but not their order or what "the entry it stopped on" is for rules that have no single entry; this is the order in which each later rule's message is meaningful (counting entries on a plan missing its Progress section is not). Treating a stamp removed from an old entry as a halt costs nothing and catches a session that edited history.
  Date/Author: 2026-10-11, M3 session (Claude).
- Decision: an entry's key is its text lowercased with every date removed, whether in parentheses, in square brackets, or bare (`YYYY-MM-DD` with an optional `HH:MM` or `HH:MMZ` after it), and non-alphanumeric runs collapsed. A consequence carried over from factory-loop: rewriting the text of an already-done entry changes its key, which the judge reads as that entry reverting and a new one becoming done, so the count rule or the revert rule halts. Corrections to a done milestone therefore belong in Surprises & Discoveries, the Decision Log, or an appended sentence in a later entry, never in the done entry's own line.
  Rationale: the plan's date tolerance (any `YYYY-MM-DD` anywhere on the line) has to be mirrored in the key, or ticking an entry with a bracketed or bare date would make it a new entry rather than the same one done. The revert-on-edit behaviour is the conservative reading PLANS.md already asks for ("corrections are appended, not rewritten").
  Date/Author: 2026-10-11, M3 session (Claude).
- Decision: the shortened text in a record is the first 72 characters followed by ASCII `...`, not the `…` factory-loop uses.
  Rationale: the macOS `awk` (version 20200816) counts bytes, not characters, so a multibyte ellipsis would make the 72-character rule a 72-byte rule with an odd suffix; the plan says only "shortened text".
  Date/Author: 2026-10-11, M3 session (Claude).
- Decision: the fixture runner's temporary repositories run git with `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1` and an identity from `GIT_AUTHOR_*`/`GIT_COMMITTER_*` environment variables; the snapshot file lives inside each fixture repository and is listed in its `.git/info/exclude`. Cases three (commit not touching the plan) and six (done entry reverted) pair the condition under test with an otherwise clean one-entry advance.
  Rationale: a signing key, hook path, or commit template in the operator's global configuration must not change a verdict, and the repositories are the fixture's own, not this checkout's (this checkout's hooks are untouched). Without the exclusion the snapshot would dirty every tree and every case would halt on the last rule. Without the pairing, case three would halt on "no entry changed state" rather than on the untouched commit, and case six on the count rule rather than the revert rule, so the cases would pass without exercising the rules they are named for; the per-case output line prints the halt rule so a reader can see which rule fired.
  Date/Author: 2026-10-11, M3 session (Claude).
- Decision: `judge-fixtures` is wired into `tools/verify` as one `check` line after the integration tier, and so sits behind the same database gate as the test tiers: when `tools/test-db` fails, the fixtures are reported `FAILED (not run: no test database)` although they need no database.
  Rationale: the plan says adding a check is one line, and the M2 decision that nothing runs without a database belongs to `tools/verify`'s design, not to this milestone; verify exits 1 in that case regardless, so no verdict is lost, only two seconds of information. Making the gate per-check is a small later change if a session ever wants the fixtures' result on a machine without PostgreSQL.
  Date/Author: 2026-10-11, M3 session (Claude).

- Decision: M3 is accepted. Judged twice by the reviewer: the manual loop-runner rules and `tools/judge-milestone judge plans/active/factory-tools.md <snapshot at d6f2466> d6f2466` both print advanced for the M3 entry; `tools/fixtures/judge/run` prints `8 of 8 passed`; `./tools/verify` prints `test-db ok`, `unit+web+services ok (59s)`, `integration ok (78s)`, `judge-fixtures ok (2s)`. From M4 on, `tools/judge-milestone` is the judge of this plan.
  Rationale: the judge judging the plan that built it is the trial the design asked for, and it agreed with the hand rules on every point.
  Date/Author: 2026-10-11, reviewer (operator's session, Claude).
- Decision: M4's debt-row acceptance changes from 31 to 35 rows. Five rows close (D1, D2, D3, D5, D35) and four open from findings during this plan: the `fresh_db` fixture deletes rows from the configured database; `test_migration_013.py`'s up-down-up cycle leaves the badge view without migration 033's filter; `query_c_baseline_drift` casts `score_overrides` with `::int` while `src/docket/ai/pipeline.py` writes the same dict; and the analytics test fixtures leave `docket_test_umami_*` databases on the local server. The four `tests/web/test_p5_translation.py` skips on a fresh database are noted in `docs/specs/operations.md` Tests as expected, not as debt. M4 must not reword the Progress lines of M1 to M3: the judge keys entries by their text with dates stripped, so a reworded done line reads as one entry reverted and one newly done.
  Rationale: the register must match what this plan actually learned; the judge's keying rule is a property of the tool M3 built and binds every later edit of a plan in flight.
  Date/Author: 2026-10-11, reviewer.

## Outcomes & Retrospective

M1 (2026-10-11): the eight tests pass and the full non-live suite is green in one run on the repaired developer database (`2468 passed, 3 skipped, 4 xfailed`). Four of the eight needed what the plan said (three masthead stubs instead of one), one needed more than the plan said (the `kpi-strip` test had a second latent assertion the plan did not see), one needed a different fix in a file the plan did not name (the blog rail test and the module-level overview cache), and one is fixed only until the next integration run (the materialised view, which `test_migration_013.py` re-drifts). Three test files changed as planned plus `tests/integration/test_blog_integration.py`; no source file changed. The important discovery is not any of the eight tests but what the suite does to the database it runs against: a unit-tier fixture deletes every `agenda_items` and `votes` row in whatever `DATABASE_URL` names, and runs leave rows and schema drift behind that make the next run red. That is the plan's M2 case made concrete, and it means "green on a developer database" is a one-shot statement until `tools/test-db` exists. Lesson for plan authoring: a diagnosis of a failing test should include the command that reproduces it in isolation and in suite order, because two of the eight had causes the plan's single reading of the failure did not reach.

M3 (2026-10-11): `tools/judge-milestone`, `tools/fixtures/judge/run`, and `docs/capabilities/judge-milestone.md` exist, the register has the card as `specced`, and `./tools/verify` runs three checks in 147 s. The judge is about 200 lines of POSIX sh around four awk programs adapted from factory-loop; its first real use was on this plan's own M2 history, where it passed five rules and halted correctly on the sixth because the new script was untracked. The plan's specification was complete enough that no acceptance clause had to be carved out, but it left seven details open (verdict words, where the plan is read from, rule order, what "the entry" means for rules without one, the key for bracketed and bare dates, the ellipsis, the fixtures' git environment), each resolved in the Decision Log. Two things to carry forward: the plan's own `| head -5; echo "exit=$?"` acceptance command measures the wrong exit status, a trap worth remembering when writing acceptance commands; and the judge's key makes editing a done entry's text read as a revert, which is the convention PLANS.md already states and which the M4 session must respect when it ticks its entry. Lesson: a halt on the first real run is the judge working, not failing; the fixture that proves it can say `advanced` (case one) is as important as the seven that prove it can say `halt`.

M2 (2026-10-11): `tools/test-db` and `tools/verify` exist and `pyproject.toml` excludes the live tier by default. One command now runs every non-live tier on a database built from the migrations in under a second and dropped on exit, in 144 s, leaving `docket_db` untouched (`0 / 1 / 0` rows before and after). Two of the plan's details did not survive contact: the `DATABASE_URL` the tests use comes from a `.env` above the worktree rather than from the shell or the code default, and the plan's `$(tools/test-db)` idiom needed the runner's output moved to stderr. One thing is slightly worse on a fresh database: four data-dependent web tests skip instead of running. Nothing in `src/` changed. Lesson: a plan that says "the fast tiers need no database" should name the command that proves it; here the proof would have found `fresh_db` in M1's planning rather than in M1's execution.

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

Expected: `tools/test-db` prints the migration runner's output and ends with a line `postgresql://docket@localhost:5432/docket_test_<8 hex>`; the drop prints nothing; verify prints one line per check and `verify: all 2 checks passed in <N>s.` with `exit=0`; the collect-only count of live tests is `0` after the `addopts` change and nonzero before it (record both). Observed by the M2 session on 2026-10-11: `tools/test-db` wrote the runner's output to stderr and `postgresql://docket@localhost:5432/docket_test_692415bc` to stdout; `--drop` printed nothing; `./tools/verify` printed `verify: all 2 checks passed in 144s.` and `exit=0`; live collect-only counts were `12` before and `0` after (`12` with `-m live` both times). Transcripts in Artifacts.

M3 commands:

    chmod +x tools/judge-milestone tools/fixtures/judge/run
    tools/judge-milestone snapshot plans/active/factory-tools.md | head -5; echo "exit=$?"
    tools/fixtures/judge/run
    ./tools/verify; echo "exit=$?"

Expected: the snapshot prints records beginning `OPEN`/`DONE` for this plan's four milestones (M1 and M2 `DONE` by then) and exits 0; the fixture runner prints eight case lines and `judge fixtures: 8 of 8 passed`; verify reports `all 3 checks passed`. Observed by the M3 session on 2026-10-11: the snapshot printed `DONE` for lines 13 and 14 (M1, M2) and `OPEN` for lines 15 and 16 (M3, M4) and exited 0 (measured without the `| head` pipe, which masks the exit; Surprises & Discoveries); the fixture runner printed the eight lines in Artifacts and `judge fixtures: 8 of 8 passed`, exit 0; the verify result is recorded in the M3 Progress entry and Artifacts.

M4 commands are the two failing-case demonstrations described in Plan of Work, each followed by `git checkout -- <file>` to revert, then `./tools/verify` once more, then `wc -l AGENTS.md` (must stay under 100), then the reference walk from the bootstrap plan's Task 10 over the edited artifacts.

## Validation and Acceptance

M1 is accepted when `venv/bin/python -m pytest tests/unit tests/web tests/services tests/integration -q -p no:cacheprovider` prints a summary with `0 failed` or no `failed` count at all, and the diff touches only the three test files named (plus this plan). The `docket_db` repair is recorded as a command transcript, not a code change.

M2 is accepted when `./tools/verify` exits 0 on this branch and prints a per-check summary; when running it from a second checkout at the same time would build a differently named database (observed by printing the computed name in both checkouts, which is acceptance a person can read without running two at once); when `venv/bin/python -m pytest --collect-only -q | grep -c tests/live/` prints `0`; and when `venv/bin/python -m pytest -m live --collect-only -q | grep -c tests/live/` prints a number above 0.

M3 is accepted when `tools/fixtures/judge/run` prints `judge fixtures: 8 of 8 passed` and exits 0, when `./tools/verify` includes it and still exits 0, when `tools/judge-milestone snapshot plans/active/factory-tools.md` exits 0, and when `docs/capabilities/judge-milestone.md` exists with the four mandatory sections and a `specced` row in the index.

M4 is accepted when both failing-case transcripts are in this plan's Artifacts section and each shows a nonzero exit with the underlying check's own message; when `./tools/verify` exits 0 afterwards; when `AGENTS.md` names `./tools/verify` with its budget and is under 100 lines; when `grep -c '^| D[0-9]' docs/DEBT.md` prints `31`; and when `docs/capabilities/index.md` shows `fast-verify` and `judge-milestone` as `built`.

## Idempotence and Recovery

Every step can be rerun. `tools/test-db` drops before it creates, so a half-built test database is replaced on the next run; `tools/test-db --drop` removes it by hand. The one-time `docket_db` view rebuild in M1 is a `DROP ... IF EXISTS` followed by `CREATE`, safe to repeat, and reversible by applying migration 033's `SQL_DOWN` view portion, which nobody should need. Editing `pyproject.toml` `addopts` is reversible by deleting the line. If a session dies mid-milestone, commit what landed, split the Progress entry into completed and remaining parts, log the split in the Decision Log, and stop; the next session reads the record. If `./tools/verify` is red for a reason outside this plan (a new failing test from a merge of `main`), that is a finding for Surprises & Discoveries, not something this plan absorbs.

## Artifacts and Notes

Still to be filled by later sessions: the two failing-case demonstrations (M4). (The `./tools/verify` summary and wall time from M2, and the M3 transcripts, are below.)

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

M2 transcripts, observed 2026-10-11 in the worktree on `plan/factory-tools` at `0bc385c`:

Row counts in `docket_db` before any M2 edit (17:02Z), through `with db_cursor() as cur: cur.execute('select count(*) from <table>')`:

    votes 0
    agenda_items 1
    member_votes 0

Live-tier collection before the `addopts` change:

    venv/bin/python -m pytest --collect-only -q 2>&1 | grep -c 'tests/live/'
    12
    venv/bin/python -m pytest -m live --collect-only -q 2>&1 | grep -c 'tests/live/'
    12

`tools/test-db` (17:06Z), stdout captured, stderr to a file:

    URL=$(tools/test-db 2>stderr.txt); echo "exit=$? URL=$URL"
    exit=0 URL=postgresql://docket@localhost:5432/docket_test_692415bc
    head -2 stderr.txt
    test-db: building docket_test_692415bc on postgresql://docket@localhost:5432
    Applying migration 1: docket.migrations.001_initial
    tail -1 stderr.txt
    All migrations applied.

`printf '%s' "$(pwd -P)" | shasum | cut -c1-8` in this checkout printed `692415bc`, matching the name. `--status` on the new database counted 33 `applied`, 0 `pending`; `select count(*) from municipalities` gave `4`, `meetings` gave `0`; `pg_get_viewdef('mv_badge_volume_monthly')` contained `is_hidden` (`t`). Run from `tests/` as `../tools/test-db`, the URL printed was identical. `tools/test-db --drop` printed nothing and exited 0; `select count(*) from pg_database where datname like 'docket_test_6%'` then gave `0`; a second `--drop` also printed nothing and exited 0.

Live-tier collection after adding `addopts = "-m 'not live'"` to `pyproject.toml` (17:10Z):

    venv/bin/python -m pytest --collect-only -q 2>&1 | grep -c 'tests/live/'
    0
    venv/bin/python -m pytest --collect-only -q 2>&1 | tail -1
    2475/2487 tests collected (12 deselected) in 1.40s
    venv/bin/python -m pytest -m live --collect-only -q 2>&1 | grep -c 'tests/live/'
    12
    venv/bin/python -m pytest -m live --collect-only -q 2>&1 | tail -1
    12/2487 tests collected (2475 deselected) in 1.33s
    venv/bin/python -m pytest tests/unit tests/web tests/services tests/integration --collect-only -q -p no:cacheprovider 2>&1 | tail -1
    2475 tests collected in 1.35s

The last line shows the `addopts` expression deselects nothing inside the four non-live tiers, so `tools/verify`'s counts are unaffected by it.

`./tools/verify` acceptance run, started 17:08Z, finished 17:10Z, output 128 lines (the runner's 67 lines, two pytest runs, the summary); row counts taken through `docket.db.db_cursor` against `docket_db` immediately before and after:

    before:  votes 0   agenda_items 1   member_votes 0
    ./tools/verify >verify-run1.txt 2>&1; echo "exit=$?"
    exit=0
    tail -4 verify-run1.txt
    verify: test-db ... ok (0s) postgresql://docket@localhost:5432/docket_test_692415bc
    verify: unit+web+services ... ok (61s)
    verify: integration ... ok (83s)
    verify: all 2 checks passed in 144s.
    grep -E 'passed|failed' verify-run1.txt | grep -v '^verify'
    1856 passed, 4 skipped, 4 xfailed, 1 warning in 59.38s
    611 passed, 1 warning in 82.55s (0:01:22)
    after:   votes 0   agenda_items 1   member_votes 0
    select count(*) from pg_database where datname = 'docket_test_692415bc'
    0

Name divergence between checkouts, computed from the path strings (this session may not run anything in the main checkout):

    /Users/darrellnance/docket-pub -> docket_test_0a1dedec
    /Users/darrellnance/docket-pub/.claude/worktrees/factory-tools -> docket_test_692415bc

POSIX check: `dash -n tools/test-db && dash -n tools/verify` passed; `dash tools/test-db` built the database and printed the same URL, `dash tools/test-db --drop` exited 0 and left no `docket_test_692415bc` row in `pg_database`. `shellcheck` is not installed on this machine.

M3 transcripts, observed 2026-10-11 in the worktree on `plan/factory-tools` at `d6f2466`:

Starting state, before any edit (17:19Z to 17:22Z), `./tools/verify`:

    verify: test-db ... ok (1s) postgresql://docket@localhost:5432/docket_test_692415bc
    verify: unit+web+services ... ok (60s)
    verify: integration ... ok (82s)
    verify: all 2 checks passed in 143s.
    exit=0

(fast tiers `1856 passed, 4 skipped, 4 xfailed, 1 warning in 59.66s`; integration `611 passed, 1 warning in 81.29s`.)

Snapshot of this plan (17:25Z), `tools/judge-milestone snapshot plans/active/factory-tools.md`, exit 0, four records (keys elided):

    DONE	13	(2026-10-11 16:56Z) M1: the eight failing tests pass on a developer data...
    DONE	14	(2026-10-11 17:14Z) M2: `tools/verify` and `tools/test-db` exist; every ...
    OPEN	15	M3: `tools/judge-milestone` exists with its fixture self-test under `too...
    OPEN	16	M4: `AGENTS.md`, `docs/specs/operations.md`, `docs/DEBT.md`, `docs/MATUR...

The fixture runner (17:27Z), `tools/fixtures/judge/run; echo "exit=$?"`:

    judge fixture: clean-advance            ok (exit 0, advanced "(2026-10-02 11:00Z) M2: the second thing.")
    judge fixture: no-commit                ok (exit 1, halt: no commit landed since c7f4b29.)
    judge fixture: untouched-commit         ok (exit 1, halt: commit da4766f did not touch the plan.)
    judge fixture: two-ticked               ok (exit 1, halt: 2 Progress entries changed state (exactly one must).)
    judge fixture: ticked-undated           ok (exit 1, halt: entry at line 6 is ticked but carries no date.)
    judge fixture: done-reverted            ok (exit 1, halt: entry "(2026-10-01 10:00Z) M1: the first thing." was done at the start and is no longer.)
    judge fixture: dirty-tree               ok (exit 1, halt: the working tree has uncommitted changes.)
    judge fixture: missing-section          ok (exit 2, defect plan.md is missing the required section `## Decision Log`)
    judge fixtures: 8 of 8 passed
    exit=0

(Correction, same session: the `17:25Z` and `17:27Z` above were estimates written before the clock was re-read; `date -u` printed `17:26Z` immediately after the card commit `6675289`, which followed both runs, so the snapshot and the fixture run happened between 17:22Z and 17:25Z. The Progress entry's `17:27Z` for the fixture run carries the same error.) The count of `tmp.*` directories under `$TMPDIR` was 5 before and 5 after the run. A scratch copy of the runner with case one's expected exit changed from `0` to `1` (the M4 demonstration, rehearsed here on a copy outside the tree and not counted as it) printed `judge fixture: clean-advance            FAILED (want exit 1 word advanced; got exit 0: advanced "(2026-10-02 11:00Z) M2: the second thing.")`, seven `ok` lines, `judge fixtures: 1 of 8 failed: clean-advance`, exit 1. `dash -n tools/judge-milestone && dash -n tools/fixtures/judge/run` passed.

`./tools/verify` acceptance run with the fixture runner wired in as the third check, started 17:27Z, finished 17:30Z, output 140 lines:

    ./tools/verify >verify-m3.txt 2>&1; echo "exit=$?"
    exit=0
    tail -5 verify-m3.txt
    verify: test-db ... ok (1s) postgresql://docket@localhost:5432/docket_test_692415bc
    verify: unit+web+services ... ok (61s)
    verify: integration ... ok (83s)
    verify: judge-fixtures ... ok (2s)
    verify: all 3 checks passed in 147s.
    grep -E 'passed|failed' verify-m3.txt | grep -v '^verify'
    1856 passed, 4 skipped, 4 xfailed, 1 warning in 60.65s (0:01:00)
    611 passed, 1 warning in 82.17s (0:01:22)
    judge fixtures: 8 of 8 passed
    select count(*) from pg_database where datname = 'docket_test_692415bc'
    0

`dash -n tools/verify` passed after the edit.

## Interfaces and Dependencies

`tools/test-db`: POSIX sh. Reads `DATABASE_URL` (optional). Prints the test database URL as its last line and exits 0, or exits nonzero with psql's or the runner's error. `tools/test-db --drop` drops it silently. Requires `psql` on PATH or at `/opt/homebrew/opt/postgresql@16/bin/psql` (try PATH first, then that path) and `venv/bin/python`.

`tools/verify`: POSIX sh, no arguments, exit 0 only if every check passed. Checks are listed in the script as `name` and `command` pairs so adding one is one line. Output contract: each check's own output, then one summary line per check in the form `verify: <name> ... ok` or `verify: <name> ... FAILED`, then the final line. (As built in M2: the `ok`/`FAILED` word is followed by the check's wall time in parentheses, a `verify: test-db ... ok <url>` line precedes the checks, a check that could not run because the database failed to build reads `FAILED (not run: no test database)`, and the final failing line is `verify: N of M checks failed in Ss. Each failing check's output is above its summary line; re-run one with:` followed by one indented command per failing check. `DATABASE_URL` is exported to every check.)

`tools/judge-milestone`: POSIX sh. `snapshot <plan>` to stdout, exit 0 or 2. `judge <plan> <snapshot-file> <start-sha>`, exit 0, 1, or 2, output as specified in Plan of Work. Uses only `git`, `awk`, `sed`, `printf`; no Python. (As built in M3: records are `KIND<TAB>line<TAB>shortened text<TAB>key`, where KIND is `OPEN`, `DONE`, `NOSTAMP`, `MISSING`, or `EMPTY`, line is `0` for the last two, the shortened text is the first 72 characters plus `...`, and the key is the lowercased text with dates and non-alphanumerics normalised away. Every message line begins `judge: ` and its first word is the verdict: `advanced "<shortened entry>"` on exit 0; `halt <plan>` as the first of four lines on exit 1, followed by `entry "<shortened entry>"` or `no entry`, the rule sentence, and `Fix the cause, commit in the worktree, and re-run.`; `defect <plan> <phrase>` on exit 2, written to stderr in both modes. `judge` resolves the plan's path relative to the repository root with `git rev-parse --show-prefix`, reads it with `git show HEAD:<path>`, and runs `git status --porcelain` for the whole repository. The judge may be invoked from any directory; the plan path is taken relative to the current directory.)

`tools/fixtures/judge/run`: POSIX sh, no arguments, exit 0 if all cases pass. Creates and removes its own temporary repositories; leaves nothing behind. (As built in M3: one line per case, `judge fixture: <case> ... ok (exit N, <verdict or halt rule>)` or `... FAILED (want exit N word W; got exit M: <first line>)`, then `judge fixtures: 8 of 8 passed` or `judge fixtures: N of 8 failed: <names>`. The cases are named `clean-advance`, `no-commit`, `untouched-commit`, `two-ticked`, `ticked-undated`, `done-reverted`, `dirty-tree`, `missing-section`. Git runs with `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1`.)

`pyproject.toml`: `[tool.pytest.ini_options]` gains `addopts = "-m 'not live'"`.

`docs/capabilities/judge-milestone.md`: card per `docs/capabilities/CARD_FORMAT.md`, sections Invariant, Enforcement point, Acceptance, Remediation message.

## Revision notes

- 2026-10-11, M1 session: recorded M1's execution. Added Surprises & Discoveries entries (context-manager one-liner, three masthead stubs, hidden roll-call assertion, Sunday demonstration, overview cache, destructive unit fixture, migration-013 view drift), four Decision Log entries (roll-call conditional, extra stubs, editing `test_blog_integration.py`, not editing `test_migration_013.py` or `test_ai_worker_claim.py`), corrected the `db_cursor` command forms in Concrete Steps, appended two corrections to Context and Orientation without removing the original sentences, filled Artifacts with the observed transcripts, ticked M1 with its carve-outs, and wrote the M1 Outcomes entry. Reason: PLANS.md requires observed evidence and visible corrections; two of the plan's eight diagnoses were wrong and the record has to show that.
- 2026-10-11, M2 session: recorded M2's execution. Added Surprises & Discoveries entries (`.env` resolution of `DATABASE_URL`, the `$(tools/test-db)` stdout conflict, four data-dependent skips on a fresh database, sub-second database build), four Decision Log entries (no destructive starting-state run against `docket_db`, `tools/test-db` resolution and stderr contract, no tiers without a database, drop-on-exit and summary-line shape), the observed M2 results in Concrete Steps, the M2 transcripts in Artifacts, the as-built output contract in Interfaces, ticked M2 with two carve-outs, and wrote the M2 Outcomes entry. Reason: PLANS.md requires observed evidence and visible corrections; the reviewer's revision of M2 (every tier on the disposable database, row counts unchanged) is the acceptance recorded here.
- 2026-10-11, M3 session: recorded M3's execution across three commits. Added Surprises & Discoveries entries (the `| head` exit-status trap in the plan's own M3 command, the real-history smoke of the judge on M2's commits, the inert hooks path), seven Decision Log entries (verdict words and stderr for defects, reading the plan at `HEAD:`, rule order and the meaning of "the entry", key normalisation and the revert-on-edit consequence, ASCII ellipsis, hermetic fixture repositories and paired cases, the fixture check behind the database gate), the observed M3 results in Concrete Steps, the M3 transcripts in Artifacts with an appended time correction, the as-built record and message shapes in Interfaces, ticked M3 with no carve-out, and wrote the M3 Outcomes entry. Reason: PLANS.md requires observed evidence and visible corrections, and the next session (M4) needs the judge's exact output shapes to demonstrate its failing case and promote the card.
