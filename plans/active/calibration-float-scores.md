# Make the calibration queries read float-valued scores so the daily calibration report runs and the admin calibration page loads

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

docket.pub scores every substantive agenda item twice with a language model (a significance score and a consent-placement score, each 0 to 10) and then applies deterministic floors and ceilings to those scores. The "before" and "after" numbers are stored together on the row in a JSON column, `agenda_items.score_overrides`, and two readers compare them to catch a model that is drifting: a daily worker task named `calibration_report`, and an admin web page at `/admin/calibration`. Both readers are broken today. The pipeline writes the scores as JSON floats such as `9.0`, and both readers cast them to PostgreSQL integers with `::int`, which PostgreSQL refuses for the text `"9.0"`. The worker's reader has a second, older fault: it filters on a column, `agenda_items.updated_at`, that has never existed, so it has crashed every day since 2026-05-11. The worker swallows the exception and nothing alerts (GitHub issue #110 and runbook item #56 in `docs/runbooks/v3-cutover.md`).

After this plan, an operator who opens `/admin/calibration` while a scored item sits in the last 24 hours sees the page (HTTP 200) with that item in the per-item divergence panel instead of a 500 error; the worker's `calibration_report` task logs one `calibration_report: divergence=N underscoring=N overscoring=N drift_alerts=N cache_cleanup=N` line and no `task=calibration_report failed` traceback; and a new set of integration tests seeds a row shaped exactly as production writes it, with float scores, and runs every calibration query against a real database, so the regression cannot return silently. Nothing about the writer changes: the 39,236 production rows that already hold floats are read correctly as they are.

## Progress

- [ ] M1: both calibration query files read `score_overrides` scores through `::numeric::int` and filter on `ai.ai_generated_at`; `tests/integration/test_calibration.py` seeds float-valued scores and runs every calibration query on a real database; the `calibration_report` task completes against a database holding a float-valued row.
- [ ] M2: `docs/specs/calibration.md` describes the calibration report and dashboard in the present tense, `docs/specs/index.md` lists it, and `docs/runbooks/v3-cutover.md` item #56 says the task is fixed and by which change.

## Surprises & Discoveries

Nothing has been executed yet. The entries below were observed while authoring the plan, on 2026-10-11, in this worktree against the local PostgreSQL 16 server; they are recorded here because they correct the scope brief the plan was written from.

- Observation (authoring): the brief said seven `::int` casts in the two files operate on non-`score_overrides` values and must be left alone. There are none. Every `::int` in both files is a cast of a `score_overrides->>` value: eighteen per file, thirty-six in all. The only other casts are `::float` on integer counts (two per file) and `::date` on `DATE_TRUNC` (one per file), which are unaffected.
  Evidence: `grep -c "score_overrides->>'[a-z_]*')::int" src/docket/ai/calibration.py src/docket/services/calibration.py` printed `18` for each file; `grep -n "::int" <file> | grep -v score_overrides` printed nothing for either file.
- Observation (authoring): the brief said `ai.updated_at` appears in four queries; it appears five times, because `QUERY_C_DRIFT` uses it twice (in `DATE_TRUNC('week', ai.updated_at)` and in its `WHERE`).
  Evidence: `grep -n "updated_at" src/docket/ai/calibration.py` printed lines 21, 47, 76, 91, 96.
- Observation (authoring): the worker's task fails today on the missing column before it ever reaches a float cast, so the first error an executing session sees from the worker path is `UndefinedColumn`, not `InvalidTextRepresentation`. The service path, which already uses `ai_generated_at`, fails on the float.
  Evidence: `DATABASE_URL=postgresql://docket@localhost:5432/docket_db venv/bin/python -m docket.worker.scheduler --run-once calibration_report` logged a traceback ending `psycopg2.errors.UndefinedColumn: column ai.updated_at does not exist` / `LINE 13:   AND ai.updated_at > NOW() - INTERVAL '24 hours'` / `HINT:  Perhaps you meant to reference the column "m.updated_at".`, inside `task=calibration_report failed`. A Python snippet executing `select ('{"a": 9.0}'::jsonb->>'a')::int` through `docket.db.db_cursor` raised `psycopg2.errors.InvalidTextRepresentation: invalid input syntax for type integer: "9.0"`; the same with `::numeric::int` returned `{'v': 9, 'd': 7}` for value and a 9-minus-2 difference.
- Observation (authoring): the fixed cast shape works on a row shaped exactly as production writes it. Inside one `BEGIN ... ROLLBACK` on the local `docket_db`, a meeting and an agenda item with `score_overrides` `{"final_significance": 9.0, "original_ai_significance": 2.0, "final_consent": 3.0, "original_ai_consent": 9.0, "triggers": [], "conflicts": [], "admin_override_used": false}` and `ai_generated_at = NOW()` were inserted; today's Query A text failed with `invalid input syntax for type integer: "9.0"`; the same query with `::numeric::int` returned `float demo item | 2 | 9 | 7`. Nothing persisted (`select count(*) from agenda_items where title = 'float demo item'` printed `0` afterwards).
- Observation (authoring): `tools/verify`, `tools/test-db`, and `tools/judge-milestone` do not exist on `origin/main` at `fc63c75`, which this branch was cut from. They are on `origin/plan/factory-tools`, pull request #111, which was still open when this plan was written. The acceptance commands below assume that pull request has merged into the branch the executing session works on; the Context section says what to do if it has not.
  Evidence: `ls tools` in this worktree printed `ls: tools/: No such file or directory`; `gh pr view 111` printed state `OPEN` and listed `tools/verify`, `tools/test-db`, `tools/judge-milestone` among its files.
- Observation (authoring): the local `docket_db` has no rows with `score_overrides` at all, so a test database built from migrations will hold no float-valued rows unless a test or the demonstration below seeds one. The integration tests must seed their own.
  Evidence: `select count(*) filter (where score_overrides::text ~ '[0-9]\.[0-9]'), count(*) filter (where score_overrides is not null) from agenda_items` printed `0 | 0`.

## Decision Log

- Decision: fix the readers, not the writer. Every `(ai.score_overrides->>'<key>')::int` in `src/docket/ai/calibration.py` and `src/docket/services/calibration.py` becomes `(ai.score_overrides->>'<key>')::numeric::int`; `src/docket/ai/rewrite_schema.py` keeps `float | None` for both scores and `src/docket/ai/pipeline.py` keeps writing `json.dumps` of the floats.
  Rationale: the goal as the operator stated it chose the cast fix. The 39,236 production rows already hold floats and would stay floats under any writer change, so the readers must cope regardless. Retyping the pydantic schema changes what the model's tool-use output must validate against, which decision `0027` in `docs/decisions/` says needs a live smoke test against Anthropic; a bug fix should not carry that. `::numeric::int` accepts both `"9.0"` and `"9"`, so it is also correct for any future integer-valued rows. PostgreSQL rounds numeric to integer half away from zero; the stored scores are whole numbers written as `x.0`, so rounding never changes a value.
  Date/Author: 2026-10-11, plan author (Claude, for the operator).
- Decision: also replace every `ai.updated_at` in `src/docket/ai/calibration.py` (five tokens across the four queries) with `ai.ai_generated_at`, and change nothing else in that file's SQL.
  Rationale: the goal names only the cast, but the task cannot succeed without this: `agenda_items` has no `updated_at` column (migration 001 added one only to `meetings` and `municipalities`), the worker task has crashed on it daily since 2026-05-11, and runbook item #56 has recorded that since then. `src/docket/services/calibration.py` already uses `ai_generated_at` for the same purpose and its module docstring explains why: it is written on every successful Stage 2 / 2.5 run, the moment `score_overrides` is populated. Using the same column in both files makes the worker's log line and the admin page agree on which rows are "recent".
  Date/Author: 2026-10-11, plan author.
- Decision: do not consolidate the two files (having the worker call the service functions) and do not touch `src/docket/worker/tasks.py` or `tests/unit/test_worker_tasks_calibration_report.py`.
  Rationale: the duplication is real and the two `QUERY_C` texts even differ in where the `n >= 10` filter is applied (the service applies `HAVING COUNT(*) >= 10` inside the CTE so `LAG` skips low-volume weeks; the worker applies `WHERE n >= 10` after `LAG`), but consolidating changes `tasks.py`, which trips `D34`'s trigger for that module, and rewrites eight mock-cursor unit tests. The one-token column fix keeps both files correct without it. The `QUERY_C` difference is left as it is and named in Outcomes for a future consolidation; it does not affect this bug.
  Date/Author: 2026-10-11, plan author.
- Decision: the new tests live in `tests/integration/test_calibration.py` (not a new file) and seed through the existing `_Bag` helper, extended with one keyword argument `raw_overrides` that writes a dictionary into `score_overrides` verbatim.
  Rationale: the file already owns the `bag`, `app`, `client`, and `admin_client` fixtures, the cleanup discipline, and the Birmingham lookup; a second file would duplicate them. The existing `add_item` keyword arguments are typed `int | None` and `json.dumps` would write `9` not `9.0`, so a verbatim path is required to reproduce production's shape. One new keyword is the smallest change that gives it.
  Date/Author: 2026-10-11, plan author.
- Decision: the test for the worker's four SQL constants calls `docket.ai.calibration.run_calibration_queries(cur)` with a real `db_cursor()` cursor rather than executing the four constants one by one.
  Rationale: that is the exact code path `_do_calibration_report` in `src/docket/worker/tasks.py` runs, it executes all four constants in order, and it also exercises the Python drift-counting over real `RealDictCursor` rows. Runbook item #56 asked for precisely this: "a test that exercises the query against a real cursor (the existing `test_run_calibration_queries_*` tests use a mock cursor so they didn't catch this)".
  Date/Author: 2026-10-11, plan author.
- Decision: two milestones. M1 is the code change plus the tests plus the worker demonstration; M2 is the documentation (a short present-tense spec, the specs index row, the runbook item).
  Rationale: a milestone that lands red tests without the fix leaves `./tools/verify` failing, so tests and fix are one milestone. The documentation is separable, is verifiable on its own by inspection, and keeps M1 inside one session: read the plan and two SQL files, make thirty-six plus five token edits, write five tests, run verify twice (about 150 seconds each), write the evidence back.
  Date/Author: 2026-10-11, plan author.
- Decision: reflect the calibration behaviour into a new short file `docs/specs/calibration.md` and list it in `docs/specs/index.md`, rather than invoking the "purely internal" exemption of the reflection rule, and leave `D9` in `docs/DEBT.md` open.
  Rationale: `docs/specs/index.md` requires every plan to reflect what a caller can now observe or state why not. An operator can now observe the admin page and the worker's log line, which no present-tense document describes anywhere. `D9`'s trigger says the first plan touching an area reflects its behaviour into `docs/specs/`; `src/docket/ai/calibration.py` is in the AI pipeline area. A full AI-pipeline spec is far outside a bug fix, so this plan writes the calibration sliver only and says so; `D9` stays open for the rest of the pipeline.
  Date/Author: 2026-10-11, plan author.
- Decision: the runbook item names the change by issue and branch, and by pull request number only if one exists when M2 runs.
  Rationale: the pull request is opened after the plan completes, so its number is unknowable while M2 runs unless the factory has already opened one. M2 checks with `gh pr list --repo thinkdarrell/docket-pub --head plan/calibration-float-scores --json number`; if it prints a number the item says `pull request #N`, otherwise it says `the pull request from branch plan/calibration-float-scores, which closes issue #110`. The authoring-time check printed `[]`.
  Date/Author: 2026-10-11, plan author.
- Decision: do not backfill production rows to integers, do not set `HEALTHCHECK_CALIBRATION_UUID`, and do not change any `::float` cast.
  Rationale: a backfill is unnecessary once every reader casts through numeric, and a 39k-row rewrite on the 1 GB Railway volume is an operator step under decision `0026`, not part of a bug fix. The Healthchecks variable is a Railway setting, not code, and `docs/runbooks/cron-worker.md` records the task as silent-by-design; Outcomes will recommend setting it. The `::float` casts divide integer counts and are unaffected by the JSON values.
  Date/Author: 2026-10-11, plan author.

## Outcomes & Retrospective

Nothing has been executed yet. When the plan completes, this section states, against the Purpose above: whether `/admin/calibration` returns 200 with a float-scored item visible, whether the worker task logs its summary line against a float-valued row, the before-and-after test counts, that the writer and the production rows were left unchanged, that `D9` remains open for the rest of the AI pipeline, and that the `QUERY_C` low-volume-filter difference between the two files is known and unresolved. It also carries the recommendation that the operator set `HEALTHCHECK_CALIBRATION_UUID` on the Railway `worker` service so the next silent failure of this task alerts.

## Context and Orientation

docket.pub is a Python 3.10 application: a Flask web app in `src/docket/web/`, an APScheduler worker in `src/docket/worker/`, services in `src/docket/services/` that own every database transaction, and an AI pipeline in `src/docket/ai/`. One PostgreSQL database holds everything. `AGENTS.md` at the repository root is the map and names the commands. Run every command from the worktree root with that checkout's own `venv/` (`venv/bin/python`); `venv/bin/python -c "import docket; print(docket.__file__)"` must print a path inside this worktree.

Terms used below. An "agenda item" is one row of the `agenda_items` table, one piece of business at a council meeting. "Stage 2" is the language-model step that writes a headline and two scores for an item; "Stage 2.5" is the deterministic step in `src/docket/ai/floors.py` that may raise the significance score or lower the consent-placement score when a rule fires (a "floor" or "ceiling"). "`score_overrides`" is a JSONB column on `agenda_items`, added by migration 013, that records what Stage 2.5 did: the keys are `original_ai_significance`, `final_significance`, `original_ai_consent`, `final_consent`, `triggers` (a list), `conflicts` (a list), and `admin_override_used` (a boolean). `src/docket/ai/pipeline.py` writes it, around line 367, as `json.dumps` of the fields of the `ScoreOverrides` dataclass in `floors.py`. Those fields are typed `int | None` in the dataclass, but their values come from `ItemRewrite.significance_score` and `consent_placement_score` in `src/docket/ai/rewrite_schema.py` (lines 23 and 25), which pydantic types as `float | None`, so the model's integer scores arrive as Python floats and `json.dumps` writes `9.0`. "`ai_generated_at`" is a TIMESTAMPTZ column on `agenda_items` (migration 012) written on every successful Stage 2 / 2.5 run; it is the only freshness column the table has. `agenda_items` has no `updated_at` column: migration 001 gave one, with an auto-update trigger, to `meetings` and `municipalities` only.

"JSONB arrow operators": `col->'key'` returns the value as JSONB; `col->>'key'` returns it as text. The text of a JSON number `9.0` is `9.0`, and PostgreSQL's integer input routine rejects a decimal point, so `('9.0')::int` fails with `invalid input syntax for type integer: "9.0"`. Casting the text to `numeric` first accepts it, and `numeric` to `int` then rounds; `(... ->> 'key')::numeric::int` is therefore the fix, and `NULL` passes through both casts as `NULL`, which the queries' `COALESCE` and `NULL > NULL` semantics already rely on.

The two readers. `src/docket/services/calibration.py` holds six functions, each opening `docket.db.db_cursor()` (a `RealDictCursor`, rows as dicts) and returning `list[dict]`: `query_a_per_item_divergence` (items whose final significance differs from the model's by more than 3, in the last 24 hours, by `ai_generated_at`), `query_b1_under_scoring_impact` and `query_b2_over_scoring_consent` (per action type and prompt version over 7 days, at least 30 items, more than 20 percent boosted or reduced), `query_c_baseline_drift` (12-week averages per action type with week-over-week deltas), `query_badge_volume_calibration`, and `query_top_false_positives`. The last two read badge tables, not `score_overrides`, and need no change; the test runs them anyway because the admin route calls all six. The `::int` casts to change are at lines 78 to 81 and 90 to 92 (Query A), 138 to 145 (B1), and 204 to 211 (B2). The route `calibration()` in `src/docket/web/admin.py` (line 443 onward) calls all six and renders `src/docket/web/templates/admin/calibration.html`, whose per-item panel prints `#{{ row.id }}`, `{{ row.title }}`, and `{{ row.sig_delta }}` per row. Authentication is a blueprint-level `before_request`; the integration tests log in by setting `session["admin_user"]`.

`src/docket/ai/calibration.py` holds four SQL string constants, `QUERY_A_DIVERGENCE`, `QUERY_B1_UNDERSCORING`, `QUERY_B2_OVERSCORING`, `QUERY_C_DRIFT`, which are the same four queries written independently (the service's Query C drops weeks with fewer than ten items inside its CTE with `HAVING`; the worker's drops them after the window function with `WHERE n >= 10`; both are left as they are), and `run_calibration_queries(cur)`, which executes the four on the cursor it is given and returns a dict of four counts: `divergence_count`, `underscoring_categories`, `overscoring_categories`, `drift_alerts`. The `::int` casts are at lines 12 to 15 and 23 to 24, 36 to 43, and 65 to 72; `ai.updated_at` is at lines 21, 47, 76, 91, 96. `_do_calibration_report` in `src/docket/worker/tasks.py` (line 226) opens `db_cursor()`, calls `run_calibration_queries`, calls `docket.ai.cache.cache_cleanup(max_age_days=90)` (deletes `ai_response_cache` rows not accessed in 90 days), and logs `calibration_report: divergence=%d underscoring=%d overscoring=%d drift_alerts=%d cache_cleanup=%d`. `task_calibration_report` wraps it in `_safe_run`, which pings Healthchecks (a no-op when `HEALTHCHECK_CALIBRATION_UUID` is unset, which it is in production) and on exception logs `task=calibration_report failed` with the traceback and does not re-raise. `src/docket/worker/scheduler.py` schedules it daily at 11:00 America/Chicago and offers `--run-once calibration_report` to run it once in the foreground; `venv/bin/python -m docket.worker.scheduler --help` prints `usage: scheduler.py [-h] [--run-once TASK]`.

Tests. `tests/integration/test_calibration.py` (28 tests collected today, `--collect-only` printed `28 tests collected`) has a `_Bag` class whose `add_meeting`, `add_item`, `add_badge`, `add_audit` insert rows through `docket.db.db()` and whose `cleanup` deletes them; the `bag` fixture looks up Birmingham's `municipalities.id` and yields a `_Bag`. `add_item` takes the four scores as `int | None` keywords and `json.dumps` them, so every existing seed writes integers, which is why no existing test sees the float bug. `tests/unit/test_worker_tasks_calibration_report.py` tests `run_calibration_queries` with a `MagicMock` cursor and asserts the four constants are passed to `execute` by identity; it passes before and after and is not edited. `tests/conftest.py` sets a dummy `ANTHROPIC_API_KEY`, `PGTZ=UTC`, and `TZ=UTC`.

Verification tooling. On the branch the executing session should have, `./tools/verify` builds a disposable database named `docket_test_<hash>` from the migrations with `tools/test-db` (which prints the database URL as its only stdout line), exports it as `DATABASE_URL`, runs the unit, web, services, and integration tiers and the judge fixtures, prints one `verify: <name> ... ok (Ns)` line per check and a final `verify: all N checks passed in Ns.`, drops the database, and exits 0 only if everything passed; about 150 seconds. `DATABASE_URL=$(tools/test-db) <command>; tools/test-db --drop` runs one command against such a database. `psql` is not on `PATH` on the development machine; `tools/test-db` falls back to `/opt/homebrew/opt/postgresql@16/bin/psql`, and the commands below use that path. If `tools/` is absent in the worktree (pull request #111 not merged into this branch), record that in Surprises & Discoveries and use the fallbacks published in the worktree's own `AGENTS.md`: the integration file alone can run against the developer database with `DATABASE_URL=postgresql://docket@localhost:5432/docket_db venv/bin/python -m pytest tests/integration/test_calibration.py -q -p no:cacheprovider` because every test in it cleans up its own rows, but the unit tier deletes rows from whatever database it is given (`D37` on that branch), so do not run the unit tier against `docket_db`.

Debt and specs. No row of `docs/DEBT.md` is paid by this plan (the earlier `D39` row for this bug was replaced by issue #110 on the `plan/factory-tools` branch and does not exist on `main`). `D9` is tripped and handled as the Decision Log says: the new `docs/specs/calibration.md` reflects this sliver and `D9` stays open. The design document the queries were built from is `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md` section 3.5; it is history, not current behaviour, and nothing in it is edited. `plans/active/` is empty on `main`; no plan in flight touches these files.

What is deliberately out of scope, so no session adds it: changing the writer (`rewrite_schema.py`, `pipeline.py`, `floors.py`); backfilling production rows; consolidating the two query files or touching `tasks.py` and its unit tests; setting Railway variables; touching the `::float` casts.

## Plan of Work

M1, in `src/docket/ai/calibration.py`: replace all eighteen `::int` casts of `score_overrides->>` values with `::numeric::int`, and all five `ai.updated_at` with `ai.ai_generated_at`. The mechanical way: `sed -i '' "s/')::int/')::numeric::int/g; s/ai\.updated_at/ai.ai_generated_at/g" src/docket/ai/calibration.py`, then read the file and confirm with `grep -c "::numeric::int" src/docket/ai/calibration.py` (expected `18`), `grep -c "updated_at" src/docket/ai/calibration.py` (expected `0` for the bare name; `ai_generated_at` does not match `updated_at`), and `grep -c "::int" src/docket/ai/calibration.py` (expected `18`, all now preceded by `::numeric`). Update the module docstring's spec line to add one sentence: scores in `score_overrides` are JSON floats and are read through `::numeric::int`; freshness is `ai_generated_at` because `agenda_items` has no `updated_at`.

M1, in `src/docket/services/calibration.py`: the same `sed` for the cast only (`s/')::int/')::numeric::int/g`); this file already uses `ai_generated_at`. Confirm `grep -c "::numeric::int"` prints `18`. Add one sentence to the module docstring's existing "Spec/code drift note" paragraph saying the scores are floats in the JSON and the casts go through `numeric` (issue #110).

M1, in `tests/integration/test_calibration.py`: extend `_Bag.add_item` with `raw_overrides: dict | None = None` placed after `triggers`; when it is not `None`, `score_overrides = json.dumps(raw_overrides)` and the four scalar keywords and `with_overrides` are ignored. Add a module-level constant near the top of the test section:

    FLOAT_OVERRIDES = {
        "final_significance": 9.0,
        "original_ai_significance": 2.0,
        "final_consent": 3.0,
        "original_ai_consent": 9.0,
        "triggers": [],
        "conflicts": [],
        "admin_override_used": False,
    }

and a new section headed `# Float-valued score_overrides (issue #110)` before the `# G1.2 — /admin/calibration route` section, with these five tests:

`test_query_a_reads_float_valued_score_overrides(bag)`: one meeting, one item with `title="G1-float-divergence"`, `action_type="contract_award"`, `raw_overrides=FLOAT_OVERRIDES`; call `cal.query_a_per_item_divergence()`; find the row by id; assert `ai_sig == 2`, `final_sig == 9`, `sig_delta == 7`.

`test_query_b1_counts_float_valued_boosts(bag)`: one meeting; nine items with `action_type="float_b1"`, `ai_rewrite_version=98`, `raw_overrides=FLOAT_OVERRIDES` (final 9.0 above original 2.0 is a boost); twenty-one items with `action_type="float_b1"`, `ai_rewrite_version=98`, `processing_status="completed"` and no overrides; call `cal.query_b1_under_scoring_impact()`; the row with `action_type == "float_b1"` exists with `total_items == 30`, `items_with_sig_boost == 9`, and `float(avg_boost_magnitude) == 7.0`.

`test_all_service_queries_run_with_float_valued_score_overrides(bag)`: seed one float item as in the first test; call all six service functions in turn and assert each returns a `list` (this is the "no exception" test for B2, C, badge volume, and false positives on a database that holds a float row).

`test_worker_calibration_queries_run_on_real_cursor_with_float_scores(bag)`: seed one float item; `from docket.ai.calibration import run_calibration_queries` and `from docket.db import db_cursor`; `with db_cursor() as cur: counts = run_calibration_queries(cur)`; assert the four keys are present and `counts["divergence_count"] >= 1`.

`test_calibration_dashboard_renders_float_valued_item(bag, admin_client)`: seed one float item with `title="G1-float-render"`; `rv = admin_client.get("/admin/calibration")`; assert `rv.status_code == 200`, `"G1-float-render"` in the body, `f"#{iid}"` in the body, and `'<td class="t-tnum">7</td>'` in the body (the per-item panel's `sig_delta` cell as `src/docket/web/templates/admin/calibration.html` line 69 renders it today).

Write the tests first and run the file once before editing the SQL, so the session observes them fail; record the failure lines. Then edit the SQL and run again.

M1, demonstration: build a test database, seed one float-valued row with the SQL in Concrete Steps, run the worker task once, and record the log line; drop the database.

M2, new file `docs/specs/calibration.md`, present tense, about twenty-five lines, no code fences (indented text where needed): what calibration is (comparing the model's scores to the floored scores), where the data lives (`agenda_items.score_overrides`, keys, written as JSON floats by `src/docket/ai/pipeline.py`), the two readers and what each shows (the daily `calibration_report` task's one log line with its five counters; the six panels of `/admin/calibration` with their windows and thresholds: 24 hours and more than 3 for Query A; 7 days, at least 30 items, more than 20 percent for B1 and B2; 12 weeks and at least 10 items per week for C; 12 weeks for badge volume; 7 days and at least 5 admin removals for false positives), the two reading rules every query follows (scores read through `::numeric::int`; freshness by `ai_generated_at`, since `agenda_items` has no `updated_at`), the fact that the task is silent on Healthchecks unless `HEALTHCHECK_CALIBRATION_UUID` is set (`docs/runbooks/cron-worker.md`), and the one known difference between the two readers' Query C low-volume filters. The schedule is not restated; it points at `src/docket/worker/scheduler.py`.

M2, `docs/specs/index.md`: add one table row directly after the `operations.md` row, in the same two-column shape. Its first cell is the file name `calibration.md` in backticks; its second cell reads: The daily calibration report and the `/admin/calibration` dashboard: what they compare, their windows and thresholds, how scores are read. Leave the closing paragraph about `D9` as it is.

M2, `docs/runbooks/v3-cutover.md` line 178: change the leading `- **#56** —` to `- **#56 (FIXED)** —` and append, at the end of the same bullet, one sentence: `Fixed 2026-10 by <reference>: the four queries in src/docket/ai/calibration.py filter on ai.ai_generated_at, every score_overrides score in both calibration files is read through ::numeric::int (issue #110, which also broke /admin/calibration), and tests/integration/test_calibration.py runs the queries on a real cursor against float-valued scores.` where `<reference>` is as the Decision Log says. Keep every other character of the line.

## Milestones

### Milestone 1: the queries read float scores, the tests prove it, the worker task runs

Scope: the two SQL files, the integration test file, and a worker demonstration. At the end of M1, a database that holds a production-shaped float-valued `score_overrides` row no longer breaks either reader, and the test file carries five tests that fail on the old SQL and pass on the new. The writer is untouched.

Work, in order. Run `./tools/verify` first and record its final line (the starting state; on a clean branch it should pass). Add the `raw_overrides` keyword, the `FLOAT_OVERRIDES` constant, and the five tests to `tests/integration/test_calibration.py`. Run the file once against a disposable database and record the observed failures: the expectation, from the authoring probes, is `5 failed, 28 passed`, with the service-path tests failing on `psycopg2.errors.InvalidTextRepresentation: invalid input syntax for type integer: "9.0"` and the worker-path test failing on `psycopg2.errors.UndefinedColumn: column ai.updated_at does not exist`. Make the SQL edits in both files and the two docstring sentences. Run the file again. Run the worker demonstration. Run `./tools/verify`. Commit as you go; every commit must also change this plan file (the milestone judge requires it).

Acceptance, all run from the worktree root:

`DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_calibration.py -q -p no:cacheprovider; tools/test-db --drop` prints a line ending `33 passed in <n>s` (28 existing plus 5 new) with no `failed`.

The worker demonstration in Concrete Steps prints exactly one line containing `calibration_report: divergence=1 underscoring=0 overscoring=0 drift_alerts=0 cache_cleanup=0` and no line containing `task=calibration_report failed`. (`divergence=1` because the seeded row's delta is 7; the other counters are 0 because one row cannot reach B1's or C's sample floors and the fresh database has no cache rows.)

`./tools/verify; echo "exit=$?"` prints a final `verify: all <N> checks passed in <n>s.` and `exit=0`.

`grep -c "::numeric::int" src/docket/ai/calibration.py src/docket/services/calibration.py` prints `18` for each file; `grep -n "ai\.updated_at" src/docket/ai/calibration.py` prints nothing; `git diff --stat origin/main -- src/` lists only the two calibration files.

### Milestone 2: the behaviour is written down where the next reader looks

Scope: documentation only. At the end of M2, a reader of `docs/specs/` finds a present-tense description of the calibration report and dashboard, and a reader of the cutover runbook sees that item #56 is closed and how.

Work: write `docs/specs/calibration.md` as the Plan of Work describes; add the index row; edit runbook line 178; run `./tools/verify`; commit with the plan.

Acceptance, from the worktree root:

`grep -n 'calibration.md' docs/specs/index.md` prints one table row naming the file. `grep -c 'numeric::int' docs/specs/calibration.md` prints a number of at least `1`, and `grep -c 'ai_generated_at' docs/specs/calibration.md` likewise. `test -f docs/specs/calibration.md && head -1 docs/specs/calibration.md` prints a level-one heading beginning `# `.

`grep -c '^- \*\*#56 (FIXED)\*\* —' docs/runbooks/v3-cutover.md` prints `1`, and `sed -n 178p docs/runbooks/v3-cutover.md | grep -c 'numeric::int'` prints `1`.

`./tools/verify; echo "exit=$?"` prints `verify: all <N> checks passed in <n>s.` and `exit=0`; `git status --porcelain` prints nothing.

## Concrete Steps

All commands run from `/Users/darrellnance/docket-pub/.claude/worktrees/calibration-float-scores` (or whichever worktree holds branch `plan/calibration-float-scores`). Replace `PSQL` with `/opt/homebrew/opt/postgresql@16/bin/psql` if `psql` is not on `PATH`.

Starting state (M1 and M2 both begin here):

    ./tools/verify; echo "exit=$?"

Expected (not yet observed in this worktree; the form is from `tools/verify` on `origin/plan/factory-tools`): several `verify: <name> ... ok (<n>s)` lines, then `verify: all <N> checks passed in <n>s.`, then `exit=0`.

M1, run the test file before and after the SQL edit:

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_calibration.py -q -p no:cacheprovider; tools/test-db --drop

Expected before the SQL edit (with the five new tests present): `5 failed, 28 passed in <n>s`. Expected after: `33 passed in <n>s`.

M1, the SQL edits (then read both files to confirm):

    sed -i '' "s/')::int/')::numeric::int/g; s/ai\.updated_at/ai.ai_generated_at/g" src/docket/ai/calibration.py
    sed -i '' "s/')::int/')::numeric::int/g" src/docket/services/calibration.py
    grep -c "::numeric::int" src/docket/ai/calibration.py src/docket/services/calibration.py
    grep -n "updated_at" src/docket/ai/calibration.py

Expected: `18` for each file, then nothing from the last grep. (`sed -i ''` is the macOS form; on GNU sed use `sed -i`.)

M1, the worker demonstration. Build a database, seed one float-valued row, run the task once, drop the database:

    URL=$(tools/test-db)
    PSQL=/opt/homebrew/opt/postgresql@16/bin/psql
    $PSQL "$URL" -X -v ON_ERROR_STOP=1 -c "
    WITH m AS (
      INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
      SELECT id, 'float demo', CURRENT_DATE, 'council' FROM municipalities WHERE slug = 'birmingham'
      RETURNING id
    )
    INSERT INTO agenda_items (meeting_id, title, processing_status, extracted_facts, score_overrides, ai_rewrite_version, ai_generated_at)
    SELECT m.id, 'float demo item', 'completed', '{\"action_type\": \"contract_award\"}',
           '{\"final_significance\": 9.0, \"original_ai_significance\": 2.0, \"final_consent\": 3.0, \"original_ai_consent\": 9.0, \"triggers\": [], \"conflicts\": [], \"admin_override_used\": false}',
           3, NOW()
    FROM m;"
    DATABASE_URL="$URL" venv/bin/python -m docket.worker.scheduler --run-once calibration_report 2>&1 | grep -E "calibration_report"
    tools/test-db --drop

Expected: `INSERT 0 1`, then one line of the form `<timestamp> INFO docket.worker.tasks: calibration_report: divergence=1 underscoring=0 overscoring=0 drift_alerts=0 cache_cleanup=0`, and no `task=calibration_report failed` line. The INSERT statement itself was run at authoring time inside a rolled-back transaction on `docket_db` and printed `INSERT 0 1`; the `--run-once` against a seeded database has not been run yet. On today's code the same `--run-once` printed the `UndefinedColumn` traceback quoted in Surprises & Discoveries.

M2, the runbook check, after editing:

    grep -c '^- \*\*#56 (FIXED)\*\* —' docs/runbooks/v3-cutover.md
    gh pr list --repo thinkdarrell/docket-pub --head plan/calibration-float-scores --json number

Expected: `1`; and either `[]` (write the branch-and-issue form) or a JSON list with a number (write `pull request #N`). At authoring time the `gh` line printed `[]`.

Committing: the judge (`tools/judge-milestone`) requires every commit in a milestone session to change this plan file, exactly one Progress line to go from `- [ ]` to `- [x] (YYYY-MM-DD HH:MMZ)` with nothing else on that line changed, and a clean tree at the end. Commit identity is `hello@docket.pub` (already configured in this worktree).

## Validation and Acceptance

The change is proven by three observations, all stated per milestone above and repeated here as the plan's overall acceptance. First, the five new tests in `tests/integration/test_calibration.py` fail on the unmodified SQL and pass after it, and the whole file prints `33 passed`. Second, with a float-valued row present and fresh, `GET /admin/calibration` as an authenticated admin returns 200 and lists the item (the test `test_calibration_dashboard_renders_float_valued_item` is this observation run through Flask's test client; the item's `#<id>` and title appear in the body, and the per-item panel's `sig_delta` cell holds `7`). Third, `venv/bin/python -m docket.worker.scheduler --run-once calibration_report` against a database holding that row logs the single `calibration_report: divergence=1 ...` line and no failure traceback. `./tools/verify` passing at the end of each milestone shows nothing else regressed, including the eight mock-cursor unit tests that compare the SQL constants by identity.

## Idempotence and Recovery

Every step can be repeated. The `sed` substitutions can be re-run safely: the pattern `')::int` does not occur inside `')::numeric::int` (the characters before that `::int` are `numeric`, not `')`), and `ai.updated_at` does not occur inside `ai.ai_generated_at`, so a second run changes nothing. If a run of the test file leaves rows behind (a test killed before its `finally`), the database it ran on was disposable; `tools/test-db --drop` removes it and the next `tools/test-db` rebuilds it from migrations. If the worker demonstration is interrupted, run `tools/test-db --drop`. Nothing in this plan touches `docket_db` or production; the only production effect arrives when a human deploys `main` after the pull request merges, at which point the next 11:00 America/Chicago run of the task should log its summary line (check with `railway logs --service worker`), and `/admin/calibration` should load. Rollback is `git revert` of the milestone commits; the writer and the data are unchanged either way.

## Artifacts and Notes

Authoring-time evidence (2026-10-11, local PostgreSQL 16.14, worktree venv Python 3.10.21):

    $ /opt/homebrew/opt/postgresql@16/bin/psql postgresql://docket@localhost:5432/docket_db -X -c "select ('{\"a\": 7.0}'::jsonb->>'a')::int;"
    ERROR:  invalid input syntax for type integer: "7.0"

    $ ... -c "select ('{\"a\": 7.0}'::jsonb->>'a')::numeric::int AS via_numeric, ('{\"a\": 7}'::jsonb->>'a')::numeric::int AS int_via_numeric, (NULL::text)::numeric::int AS null_case;"
     via_numeric | int_via_numeric | null_case
    -------------+-----------------+-----------
               7 |               7 |

    $ ... -c "select column_name, data_type from information_schema.columns where table_name='agenda_items' and column_name in ('updated_at','ai_generated_at','score_overrides',...);"
     significance_score      | real
     consent_placement_score | real
     ai_generated_at         | timestamp with time zone
     processing_status       | USER-DEFINED
     score_overrides         | jsonb
     ai_rewrite_version      | integer
    (6 rows)            -- no updated_at row

    $ DATABASE_URL=postgresql://docket@localhost:5432/docket_db venv/bin/python -m docket.worker.scheduler --run-once calibration_report
    ...
      File ".../src/docket/ai/calibration.py", line 124, in run_calibration_queries
        cur.execute(QUERY_A_DIVERGENCE)
    psycopg2.errors.UndefinedColumn: column ai.updated_at does not exist
    LINE 13:   AND ai.updated_at > NOW() - INTERVAL '24 hours'
    HINT:  Perhaps you meant to reference the column "m.updated_at".

    (inside BEGIN ... ROLLBACK on docket_db, after seeding the float row)
    SELECT ... ::int ...                      ->  ERROR:  invalid input syntax for type integer: "9.0"
    SELECT ... ::numeric::int ...             ->  float demo item |      2 |         9 |         7

    $ DATABASE_URL=... venv/bin/python -m pytest tests/integration/test_calibration.py -q -p no:cacheprovider --collect-only | tail -1
    28 tests collected in 0.44s

Milestone sessions append their observed transcripts below this line.

## Interfaces and Dependencies

No new module, function, or dependency. The interfaces that must hold at the end:

In `src/docket/ai/calibration.py`, the four module constants `QUERY_A_DIVERGENCE`, `QUERY_B1_UNDERSCORING`, `QUERY_B2_OVERSCORING`, `QUERY_C_DRIFT` remain `str` and `run_calibration_queries(cur) -> dict` keeps returning exactly the keys `divergence_count`, `underscoring_categories`, `overscoring_categories`, `drift_alerts`; the unit tests in `tests/unit/test_worker_tasks_calibration_report.py` import these names and must keep passing unedited. Every read of a `score_overrides` score in those constants has the shape `(ai.score_overrides->>'<key>')::numeric::int`, and every freshness filter and `DATE_TRUNC` uses `ai.ai_generated_at`.

In `src/docket/services/calibration.py`, the six functions keep their names, zero-argument signatures, and `list[dict[str, Any]]` return type, and the row keys the template reads (`id`, `title`, `action_type`, `ai_sig`, `final_sig`, `sig_delta`, `triggers_fired` for Query A) are unchanged; `ai_sig`, `final_sig`, and `sig_delta` are Python `int`.

In `tests/integration/test_calibration.py`, `_Bag.add_item(..., raw_overrides: dict | None = None)` writes `json.dumps(raw_overrides)` into `score_overrides` when given; `FLOAT_OVERRIDES` is the module-level dict quoted in Plan of Work.

In `docs/specs/`, `calibration.md` exists and is listed in `index.md`. In `docs/runbooks/v3-cutover.md`, line 178 begins `- **#56 (FIXED)** —`.

Libraries: psycopg2 (already pinned in `requirements.lock`) for the cursor; pytest for the tests; nothing new.

## Revision notes

- 2026-10-11, authored. The plan folds in the read-only scope brief for issue #110 and corrects two of its counts from observation (zero non-`score_overrides` `::int` casts, not seven; five `ai.updated_at` tokens, not four). Deliberately left out, as the brief's out-of-scope list and the Decision Log record: changing the writer so `score_overrides` stores integers; backfilling the 39,236 float-valued production rows; consolidating `src/docket/ai/calibration.py` onto the service functions (which would touch `src/docket/worker/tasks.py` and its mock-cursor tests, and is where the two files' differing `QUERY_C` low-volume filters would be reconciled); setting `HEALTHCHECK_CALIBRATION_UUID` on Railway; and the `::float` casts, which divide integer counts. Also left out: a full AI-pipeline spec for `D9`; this plan reflects only the calibration sliver.
