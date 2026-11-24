# The admin routes ask services: no SQL left in src/docket/web/admin.py

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

docket.pub is a Flask application whose rule, written in `ARCHITECTURE.md`, is that the service layer (`src/docket/services/`) owns every database transaction and that nothing under `src/docket/web/` opens a connection or executes SQL. Five web modules break that rule and row `D7` of `docs/DEBT.md` lists them. The largest is `src/docket/web/admin.py`, the module behind the pages and buttons under `/admin/` that the one operator uses: it opens 27 transactions of its own and executes 54 statements in them. The row has been overdue for this module since 2026-11-11, because two plans changed the module and neither moved its SQL.

This plan pays `D7` for `admin.py` alone. Every statement the module executes moves, unchanged in what it reads and writes and in where its transaction begins and ends, into a function under `src/docket/services/`, and each route calls that function. The other four modules the row names (`src/docket/web/auth.py`, `admin_badge_review.py`, `admin_transcripts.py`, `create_admin.py`) are out of scope by the operator's word and stay on the row.

Nothing a person sees changes: every admin page and every admin POST answers as it does today. So the observations that stand in for a visible difference are these. First, a command that prints 82 lines today prints nothing at the end:

    grep -n 'db_cursor\|db()\|\.execute(' src/docket/web/admin.py

Second, `grep -rl 'db_cursor\|db()' src/docket/web` prints four files where today it prints five. Third, the existing admin route tests pass without one of them being edited, inside `./tools/verify`. Fourth, each moved statement is a function with its own test under `tests/services/`, which is how the Details paragraph of `D7` defines "fixed". Last, the `D7` row names four modules, no longer carries its "Overdue for `admin.py`" history, and its Details paragraph counts four.

## Progress

- [x] (2026-11-24 04:13Z) M1: the council-member, admin-profile and outlet-list statements of `src/docket/web/admin.py` are asked through `docket.services` (seven of the module's 27 transaction blocks gone), each new service function has a test under `tests/services/`, the member routes have route tests that were written and passed before the move, no existing admin test file is changed, and `./tools/verify` exits zero.
- [x] (2026-11-24 04:32Z) M2: the errors-queue, manual-badge and conflict-form statements of `src/docket/web/admin.py` are asked through `docket.services` (nine more blocks gone), an unknown item still answers 404 with nothing written, each new service function has a test under `tests/services/`, row `D25` and the calibration spec name the new homes of the two statements they cite, no existing admin test file is changed, and `./tools/verify` exits zero.
- [x] (2026-11-24 04:59Z) M3: the editorial-coverage reads and the AI dashboard reads of `src/docket/web/admin.py` are asked through `docket.services.query` (six more blocks gone), each new service function has a test under `tests/services/`, no existing admin test file is changed, and `./tools/verify` exits zero.
- [ ] M4: the meeting statements of `src/docket/web/admin.py` (the city-slug lookup, hide, unhide, the video-OCR rescan, the hidden list) are asked through `docket.services`, the module no longer imports `docket.db` and executes no statement, each new service function has a test under `tests/services/`, no existing admin test file is changed, and `./tools/verify` exits zero.
- [ ] M5: the closing documents: the `D7` row and its Details paragraph in `docs/DEBT.md` name four modules and say in writing that they are re-deferred, row `D209` no longer says `D7` names `admin.py`, a new debt row records the admin session-key mismatch this plan carried unchanged, `ARCHITECTURE.md` names the three new service modules, one decision record under `docs/decisions/` holds the durable choices, and `./tools/verify` exits zero.

## Surprises & Discoveries

As authored on 2026-11-24 (UTC), nothing has been executed, so no milestone has a discovery to record. What the authoring read and ran is written here because a later session would otherwise meet it as a surprise.

- Observation (authoring, 2026-11-24): `./tools/verify` took 348 seconds in this worktree, not the "about 150 seconds" `AGENTS.md` states. A milestone session runs it at its start and at its end, so budget about twelve minutes for the two runs.
  Evidence: at `bff4c27` (the commit this branch was cut from), `./tools/verify` printed `verify: unit+web+services ... ok (201s)`, `verify: integration ... ok (134s)`, `verify: all 6 checks passed in 348s.`; the tiers printed `3825 passed, 5 skipped, 4 xfailed` and `1164 passed`, and the producer suite `147 passed`.
- Observation (authoring, 2026-11-24): the counts this plan's acceptance rests on. `grep -c 'with db()\|with db_cursor()' src/docket/web/admin.py` printed `27`; `grep -c '\.execute(' src/docket/web/admin.py` printed `54`; `grep -n 'db_cursor\|db()\|\.execute(' src/docket/web/admin.py | wc -l` printed `82`, which is 27 and 54 and the one import line (line 23). So no comment or docstring in the module matches today, and a session that writes `db()` or `.execute(` into a comment there would break the final check.
  Evidence: the three commands, run at `bff4c27`.
- Observation (authoring, 2026-11-24): two documents the scope brief did not list state where a statement of this module lives, and both go stale in M2. `docs/specs/calibration.md` line 11 says `POST /admin/errors/<id>/escalate` "in `src/docket/web/admin.py`" merges two keys into `agenda_items.score_overrides`; and the docstring of `_audit` in `src/docket/services/conflict_resolution.py` (line 87) says it mirrors "the G2 retry/escalate pattern (admin.py:300-311)". M2 edits both to name the service.
  Evidence: `grep -rn 'admin\.py' docs/specs docs/birmingham docs/runbooks docs/capabilities` and `grep -rn 'admin\.py\|web\.admin\b' src/docket --include='*.py'`, read line by line. The other hits name `admin.py` only as where a route lives (`docs/specs/meeting-types.md` line 101, `docs/specs/calibration.md` line 21, `src/docket/web/source_security.py` line 27, `src/docket/web/__init__.py` line 246) or are history (`src/docket/migrations/018_ai_batches_ingested_at.py`, `docs/runbooks/v3-cutover.md`), and stay as they are.
- Observation (authoring, 2026-11-24): no test patches `docket.web.admin.db` or `docket.web.admin.db_cursor`, so removing the import breaks no test by name.
  Evidence: `grep -rn 'admin\.db\b\|admin\.db_cursor\|web\.admin\.db' tests` printed nothing.
- Observation (authoring, 2026-11-24): the development machine's shell is zsh and its `grep` is ugrep. An unquoted `--include=*.py` is refused by the shell (`no matches found`); quote it. Recursive `grep` prints paths without a leading `./`.
  Evidence: the unquoted form printed `(eval):1: no matches found: --include=*.py`; the quoted form ran.
- Observation (revision, 2026-11-24): a username where `admin_users.id` is expected is an error, not an empty result. `admin_users.id` is `SERIAL` (`src/docket/migrations/006_admin_users.py`), and PostgreSQL refuses the comparison. So on a real login, where `session["admin_user"]` holds the username, `/admin/profile`, `POST /admin/profile/display-name` and `POST /admin/coverage` (which stores the value as `author_id`) fail with a database error; no production request was made to see it. The fixture `authed_admin_client` holds `admin_user = "test-admin"`, so a route test of the profile routes cannot use it: such a test puts a seeded integer id under `admin_user`, as `tests/integration/test_admin_coverage.py` does.
  Evidence: against a throwaway database built by `tools/test-db`, `psql "$U" -c "SELECT username FROM admin_users WHERE id = 'test-admin'"` printed `ERROR:  invalid input syntax for type integer: "test-admin"`.
- Observation (revision, 2026-11-24): what the outside review asked to be confirmed in the module, read at `bff4c27`, each as the plan assumed. `badges.record_badge_action` executes one INSERT and reads no row, so it works on the tuple cursor `badge_add` and `badge_remove` use. `badge_remove` calls a bare `abort(404)` in both not-found cases, with no message and no log line, so one `False` loses nothing. The item lookups of `badges_manage_item` and `_render_manage_panel` have the same two inner JOINs and the same WHERE and differ only in three columns. `hide_meeting` passes `session.get("admin_user_id")`, the numeric id, so it is not part of the session-key mismatch. The Details paragraph of `D7` is the second line after its heading, inside what `grep -A3` prints. `tests/integration/test_admin_coverage.py` already posts to `/admin/profile/display-name` (`test_profile_display_name_update`); no test requests `GET /admin/profile` or clears the name. The comment at line 364 of `admin.py` holds the word `psycopg2`; it sits inside the escalate block and leaves with it in M2.
  Evidence: `sed -n` of the lines named in Context, `grep -n -A4 '^### D7' docs/DEBT.md`, and `grep -n 'psycopg2\|docket.db' src/docket/web/admin.py`, which printed lines 23 and 364.
- Observation (M1, 2026-11-24): no template prints the district names the add-member form is handed. `add_member`'s GET branch builds `districts_by_city` and passes it to `admin/member_form.html`, whose District field is a plain text input; so the route test Plan of Work asks for ("a GET of `/admin/members/add` answers 200 and lists a seeded district name") cannot read the name in the response body.
  Evidence: `grep -rn 'districts_by_city' src/docket/web/templates` printed nothing; the template was read whole. The Decision Log's M1 entry says what the test asserts instead.
- Observation (M1, 2026-11-24): every rule of the seven moved statements is pinned by a service test. Each rule was taken out of a copy of the module compiled in memory (a pytest plugin in the session scratchpad that replaces one piece of the source text and executes the result into the imported module; no committed file was edited), one at a time, and the three new service test files were run against each copy: 23 removals tried, 23 failed at least one test. No assertion was added after the commit that holds the service tests failing (`5df8dda`).
  Evidence: the 23 were, for `add_member`, the empty-name guard, the city in the district lookup, the name in the district lookup, the use of the district found, `active` TRUE, the email and the photo URL stored; for `update_member`, the `WHERE id` and each of the four SET columns; for `deactivate_member`, the `WHERE id` and the FALSE; for `set_display_name`, the `WHERE id` and a `None` stored as NULL; for `get_admin_profile`, the `WHERE id` and the `display_name` column; for `list_district_names`, the city and the `ORDER BY number`; for `list_outlets`, the `ORDER BY name`, the absence of an active filter, and the `homepage` column. The run's last line was `23 of 23 removals failed a test`.
- Observation (M1, 2026-11-24): `ruff check src/docket/web/admin.py` reports an unsorted import block (`I001`) before and after this milestone, and six other findings before (four after, the two gone being nested `with` blocks that left). Nothing in `./tools/verify` runs ruff. The findings were left as they stand; the import this milestone added is written in sorted order inside its own statement.
  Evidence: `ruff check --statistics` on the file printed `Found 7 errors` after the move and, on `git show HEAD:src/docket/web/admin.py` before it, `Found 9 errors`, each with `1 I001`. The five new test files and two new service modules printed `All checks passed!`.
- Observation (M2, 2026-11-24): of 57 rules of the moved statements, 54 are pinned by a service test and three cannot be told from their absence. Each rule was taken out of, or changed in, a copy of its module compiled in memory (a pytest plugin in the session scratchpad that replaces one piece of the source text and executes the result into the imported module; no committed file was edited), one at a time, and the three new service test files were run against each copy. No assertion was added after the commit that holds the service tests failing (`3e8b4b0`).
  Evidence: the run's last line was `54 of 57 removals failed a test; survived: ['add: status applied (left to the column default)', 'remove: item-exists guard', 'conflict form: status cast to text']`. The three, and why no test can see them. (a) `add_manual_badge` writes `status` as `'applied'` explicitly; the column's default is `'applied'` (`\d agenda_item_badges`), so leaving the column out stores the same row. The same INSERT with `'flagged'` in its place did fail a test. This is the reliance row `D25` records, and it is unchanged. (b) `remove_manual_badge` first asks whether the item exists and returns `False`; without that statement the DELETE finds nothing for an item that does not exist and the function returns the same `False`, having written the same nothing. The statement moved as it stood because the plan moves statements unchanged. (c) `get_conflict_form_item` casts `processing_status` to text; the driver hands an enum value back as a Python `str` either way, so the row is the same without the cast. The 54 that failed a test cover, for `retry_item` and `escalate_item`, the not-found guard, each column the UPDATE sets, its `WHERE id`, every value of the audit row and the returned status, and for `escalate_item` the kept keys, a NULL `score_overrides` and each of the two keys added; for `add_manual_badge`, the two not-found guards, the city, the kind, the confidence, the source, both keys of `matching_metadata`, `ON CONFLICT DO NOTHING`, the audit row and its values, that it is written only on an insert, and the returned bool; for `remove_manual_badge`, both predicates of the DELETE, the not-attached guard and the audit row and its values; for the two readers, the `WHERE` and each column.
- Observation (M2, 2026-11-24): `ruff check` reports the nested `with db() as conn:` / `with conn.cursor() as cur:` of `src/docket/services/errors_queue.py` twice (`SIM117`), the form the two blocks had in `admin.py`. Nothing in `./tools/verify` runs ruff; the blocks were left in the shape they moved in. On `src/docket/web/admin.py` ruff now prints `Found 3 errors` (`I001`, `SIM102`, `RUF019`), where M1 left 7; the four gone are nested `with` blocks that left the module.
  Evidence: `venv/bin/ruff check` on the new service module and the four new test files printed `Found 2 errors`, both `SIM117` in `errors_queue.py`; `venv/bin/ruff check --statistics src/docket/web/admin.py` printed the three lines named.
- Observation (M3, 2026-11-24): the coverage list labels a subject by the first title its id finds in `agenda_items`, then `meetings`, then `council_members`, whatever the link's type; so a link to a meeting whose id an agenda item also holds is labelled with the item's title on `/admin/coverage`. The statement moved as it stands. No debt row or issue records this; it is not this plan's to mend, and M5's session or the operator may want it filed.
  Evidence: in a transaction rolled back on the throwaway database, a meeting and an agenda item were inserted under the one id 987650777 and a note linked to the meeting; the label statement, run as it stands in the service, printed `meeting|An item title`.
- Observation (M3, 2026-11-24): of 118 removals from the moved statements, 112 fail a service test and six cannot be told from their absence. Each rule was taken out of, or changed in, a copy of `src/docket/services/query.py` compiled in memory (the pytest plugin in the session scratchpad that M1 and M2 used; no committed file was edited), one at a time, and the test file of that function was run against each copy. The first run, on the tests as commit `df565e0` holds them, printed `104 of 117 removals failed a test`: four of the thirteen were errors of the check itself (the text to remove stood more than once in the module, so nothing was removed), three were unpinned and got an assertion, and six are the six below. The three assertions added after `df565e0`: in `test_list_coverage_for_admin_labels_the_subjects_of_each_entry_in_link_order`, the first link is rewritten after the four are made, so that only the statement's `ORDER BY csl.coverage_id, csl.id` gives them back in link order; in `test_transcript_pipeline_summary_sums_a_transcript_stage_over_seven_days`, a second stage of the test's own and the assertion that the two come in stage order (a reversed `ORDER BY stage` had failed nothing while the test seeded one stage); in `test_transcript_pipeline_summary_gives_the_citation_missing_rate_of_a_prompt_version`, a third prompt version and the whole row of the second (a `total` that counted groups, and one fixed at 2, had each failed nothing).
  Evidence: the last run's final line was `112 of 118 removals failed a test; survived: ['list: no subject statement when no rows', "list: subject label '' in SQL", "list: subject label or '' in Python", 'search: the five ESCAPE clauses', 'stage costs: ORDER BY stage', 'stage costs: cost COALESCE']`. The six, and why no test can see them. (a) `list_coverage_for_admin` runs the subject statement only when it has rows; with no rows the statement is `= ANY('{}')` and returns nothing, the same empty dictionary. (b) and (c) The label has two guards against NULL, the `''` that ends the SQL `COALESCE` and the `or ""` in Python; either alone gives the empty string, so neither can be told from its absence while the other stands. (d) `ESCAPE '\'` on the five ILIKE predicates names the escape character PostgreSQL uses by default. The escaping of the needle itself is pinned: without `_escape_like`, or without any one of its three replacements, a wildcard test fails. (e) `ORDER BY stage` on the stage-cost statement: the planner groups by sorting (`EXPLAIN` printed `GroupAggregate` over `Sort  Sort Key: stage`), so the rows come in stage order without it; `ORDER BY stage DESC` in its place does fail a test. (f) `COALESCE(SUM(cost_usd), 0)` in the same statement: `ai_runs.cost_usd` is `NOT NULL` and a group holds at least one row, so the sum is never NULL. The same `COALESCE` in the seven-day statement, which has no GROUP BY, is pinned. The 112 that failed a test cover, for `list_coverage_for_admin`, each filter and their AND, each of the nine columns, both halves of the author label, the LEFT JOIN, the order, the 200, the counts and their grouping, each of the four label lookups, the restriction of subjects to the rows returned, link order and `subject_type`; for `list_active_outlets`, the filter, the order and the columns; for `get_coverage_for_edit`, the not-found guard, each `WHERE`, the columns, the three ways the outlet predicate can go wrong and the order; for `search_coverage_subjects`, the escaping, the wildcards around the needle, ILIKE, the order and the 15 of each statement, the date in a meeting's label, and the name and the slug of a badge; for `ai_pipeline_summary`, every predicate of the two pending counts, which version each placeholder gets, the debounce, the seven days, each of the three sums and its zero, and the order, the 20 and each column of the runs; for `transcript_pipeline_summary`, the grouping and order of the status counts, the `transcript_` pattern, the seven days, each aggregate of the stage costs, and for the citation rate the dismissed rows left out, the count of missing, the percentage, its one decimal, the grouping and the order.
- Observation (M3, 2026-11-24): `ruff check` reports nothing new. On `src/docket/web/admin.py` it prints the three findings M2 left (`I001`, `SIM102`, `RUF019`); on `src/docket/services/query.py` it prints `Found 6 errors` before and after this milestone; the two new test files print `All checks passed!`.
  Evidence: `venv/bin/ruff check --statistics` on each file, and on `git show HEAD:src/docket/services/query.py` saved to the scratchpad.

## Decision Log

- Decision: a plan is opened for `D7` alone, for one module, against the sentence in the row's Details paragraph ("do not open a plan for it alone").
  Rationale: the operator stated the goal in those words ("start on d7 for admin.py"). M5 rewords the sentence so it no longer forbids what the operator asked for.
  Date/Author: 2026-11-24, plan author.
- Decision: "behaviour unchanged" includes transaction boundaries. Each `with db()` or `with db_cursor()` block of the module becomes one service function that opens one transaction, with the same statements in the same order. Blocks are not merged and not split, with the two exceptions named in the next entry.
  Rationale: a route such as the errors-queue retry reads a row, updates it and writes an audit row in one transaction; splitting that would let an audit row exist without its update. Merging two blocks would change what a failure between them leaves behind.
  Date/Author: 2026-11-24, plan author.
- Decision: three tidyings are allowed because their observable result is identical, and no others. (a) `badges_manage_item` and `_render_manage_panel` run two item lookups that differ only in columns; one function returns the wider row for both, since the partial template `src/docket/web/templates/admin/_badges_manage_panel.html` reads only `item.id`. (b) The three conflict-form lookups differ only in columns; one function returns `id`, `extracted_facts` and `processing_status` for all three, since the routes read nothing else from the row. (c) The explicit `conn.commit()` in `hide_meeting` and `unhide_meeting` is dropped, since `db()` in `src/docket/db.py` commits when its block ends without an exception.
  Rationale: each removes a duplicate without changing a response or a stored row. Anything else that looks untidy stays as it stands.
  Date/Author: 2026-11-24, plan author.
- Decision: a service says "not found" by its return value (`None`, or `False` where the function otherwise returns a bool) and the route calls `abort(404)`. Services do not import Flask and do not raise a new exception class for this.
  Rationale: `ARCHITECTURE.md` says a service does not render; `docket.services.query` already returns `None` for a missing row and its callers abort. In every not-found path of this module the `abort` comes before any write (read in the module at `bff4c27`), so returning early from the service writes nothing, as the rollback did.
  Date/Author: 2026-11-24, plan author.
- Decision: homes. Reads go in `src/docket/services/query.py`, which `ARCHITECTURE.md` names as the home of all reads for the web layer, appended at the end of the file under one comment heading. Writes go to the service that already owns the table (`badges.py`, `non_meetings.py`, `video_ocr.py`) and, where none does, to three new modules: `council_members_writer.py`, `admin_users.py`, `errors_queue.py`. Interfaces and Dependencies gives every name and signature.
  Rationale: the same pattern as `outlets_writer.py` and `coverage_writer.py`. The admin hide and unhide go beside `non_meetings.py`'s own hide because that module's docstring already owns what `hidden_reason` and `keep_visible_at` mean.
  Date/Author: 2026-11-24, plan author.
- Decision: the badge audit rows of `badge_add` and `badge_remove` are written through the existing `badges.record_badge_action`, not through a second copy of its INSERT.
  Rationale: `record_badge_action` inserts the same five values plus `reason`, passed as NULL; the column `agenda_item_badges_audit.reason` is `TEXT` with no default (`src/docket/migrations/013_impact_first_refactor.py`, line 182), so the stored row is the same.
  Date/Author: 2026-11-24, plan author.
- Decision: where a route this plan moves has no route test for a path, the session writes that route test first, against the unchanged module, sees it pass, and only then moves the statement. The paths are named in each milestone.
  Rationale: a service test proves the new function; only a route test that passed before and passes after shows the route answers as it did. The four `/admin/members` routes have no test at all today.
  Date/Author: 2026-11-24, plan author.
- Decision: no existing test file is edited by any milestone. New tests go in new files.
  Rationale: "the existing admin tests pass unchanged" is the plan's main evidence, and `git diff --stat origin/main -- <those files>` printing nothing is how a reader checks it.
  Date/Author: 2026-11-24, plan author.
- Decision: debt rows this plan passes without paying, re-deferred here in writing. `D14` (no CSRF protection on the admin POST routes; trigger: a second admin user or public launch, issue #83), `D17` (the force-rescan writes no audit row; trigger: the next admin audit pass, issue #85) and `D26` (the manual vote-link correction page is not built) all sit on routes in this module. None of their triggers fires by moving a statement, and each would be a change of behaviour, which this plan does not make. `D209` (what admin and public pages do when the database does not answer) is likewise untouched: moving a statement does not change which error reaches the route. The four other modules of `D7` are re-deferred on the row itself by M5.
  Rationale: `D7` went overdue twice because plans touched the module and said nothing; this entry is the saying.
  Date/Author: 2026-11-24, plan author.
- Decision: no production data is read for this plan, and no session runs a command against production.
  Rationale: no statement's text, predicate or written value changes, so there is no new predicate to try on real rows.
  Date/Author: 2026-11-24, plan author.
- Decision (revision): `get_profile` does not go in `admin_users.py`. It is a read, so it goes in `src/docket/services/query.py` as `get_admin_profile`, and `admin_users.py` holds `set_display_name` alone. This supersedes the placement the first version of Interfaces gave.
  Rationale: the homes entry above says reads go in `query.py` and the new modules write; the first version broke its own rule, and M5's clause in `ARCHITECTURE.md` says what each new module writes. Found by the outside review.
  Date/Author: 2026-11-24, revision at the operator's request.
- Decision (revision): a session runs `./tools/verify` at its start only when the tree it starts on has not already passed it. M1 skips the opening run when `git diff --stat bff4c27 -- . ':(exclude)plans'` prints nothing, because the authoring baseline was taken at `bff4c27`. M2 to M5 skip it when the entry before theirs is ticked with a passing end-of-milestone run recorded in Artifacts and Notes, `git status --short` prints nothing, and `git log --merges --oneline bff4c27..HEAD` prints nothing. Otherwise the session runs it. The run at the end of every milestone stays. The session records which of the two it did and what the commands printed.
  Rationale: the run takes about 348 seconds, and a milestone's last act before its commit is a passing run on the tree it commits, so the next session's opening run tests the same tree; only a merge of `main` or an uncommitted change makes it a different one. Suggested by the outside review.
  Date/Author: 2026-11-24, revision at the operator's request.
- Decision (revision): M4 adds one test, `tests/unit/test_admin_module_has_no_sql.py`, that reads `src/docket/web/admin.py` with Python's `ast` module and fails when the module imports anything from `docket.db` or `psycopg2`, or calls anything named `db`, `db_cursor` or `execute`. It is written first in M4 and seen to fail on the module as M3 left it. It is a pin on this one module, not the `boundary-lint` capability, whose status stays `specced`.
  Rationale: `D7` went overdue for this module twice because plans edited it and nobody looked for SQL; a test inside `./tools/verify` keeps the module as this plan leaves it, where the plan's greps are run once. Suggested by the outside review.
  Date/Author: 2026-11-24, revision at the operator's request.
- Decision (revision): three of the outside review's suggestions are not taken. (a) A three-valued string in place of `bool | None` for `add_manual_badge`: the route is its one caller, `tests/integration/test_admin_badge_audit.py` already pins both the repeated add (`test_add_endpoint_is_idempotent`) and the two 404s, and the not-found entry above keeps one convention for every function. (b) Named tuples for the two coverage reads: each has one caller that unpacks it at once. (c) One statement for all cities' district names on the add-member form: it would merge transaction blocks, which the boundaries entry above rules out, for a page one operator opens over the few cities the migrations seed. The loop stays.
  Rationale: each is a change of shape this plan does not need to be behaviour-neutral, and (c) is a change of what runs.
  Date/Author: 2026-11-24, revision at the operator's request.
- Decision (revision): the debt row M5 writes for the session-key mismatch says it is an error on a real login today, not a hazard, and names the test that hides it.
  Rationale: the Surprises entry of the revision shows the error; a row worded as untidiness would sit behind rows that are.
  Date/Author: 2026-11-24, revision at the operator's request.
- Decision (M1): the opening `./tools/verify` was skipped, under the revision entry above.
  Rationale: at the session's start `git rev-parse HEAD` printed `0fd31a845b74de8cb4a42777e4289321e338d60f`, `git status --short` printed nothing, and `git diff --stat bff4c27 -- . ':(exclude)plans'` printed nothing, so the tree outside `plans/` is the one the authoring baseline passed on.
  Date/Author: 2026-11-24, M1 session.
- Decision (M1): the GET test of `/admin/members/add` asserts the district names in the context the route hands the template, read through Flask's `template_rendered` signal, and not in the response body. It asserts the seeded city's list equals the two seeded names in `number` order, the names being stored so that alphabetical order would reverse them.
  Rationale: the page does not print the names (Surprises, M1), and the statement M1 moves is the one that fills that context value; a test of the body could not tell the statement from its absence. Editing the template to print them would be a change of what a person sees, which this plan does not make. The alternative of dropping the test would leave the moved loop with no route test.
  Date/Author: 2026-11-24, M1 session.
- Decision (M1): the three new readers return plain dictionaries (`dict(row)`), where the routes handed the template the cursor's own rows. `update_member` and `deactivate_member` use `db_cursor()` where the routes used `db()` with a tuple cursor.
  Rationale: `query.py` returns `dict(row)` everywhere else, the templates read the rows by key either way, and neither UPDATE reads a row, so the cursor kind changes nothing stored or shown. Interfaces allows either cursor for a function that returns plain values.
  Date/Author: 2026-11-24, M1 session.
- Decision (M2): the opening `./tools/verify` was skipped, under the revision entry above.
  Rationale: at the session's start the M1 entry was ticked with its closing run recorded in Artifacts and Notes (`verify: all 6 checks passed in 335s.`), `git rev-parse HEAD` printed `e0364cca1a8db16881f26671c2f6bd564faef3c9`, `git status --short` printed nothing, and `git log --merges --oneline bff4c27..HEAD` printed nothing. The two counting greps printed `20` and `46`, as M1 left them.
  Date/Author: 2026-11-24, M2 session.
- Decision (M2): the route test of the two unknown-item POSTs reads the count and the highest id of `processing_status_audit` before the request and after it and asserts the two readings equal. It asserts no fixed size.
  Rationale: Plan of Work asks that the count stay where it was; Context forbids asserting a whole table's size, and allows the difference between two readings. Tests in a tier run one after another, so nothing else writes between the two readings.
  Date/Author: 2026-11-24, M2 session.
- Decision (M2): `errors_queue.py` and the two new functions of `badges.py` keep the tuple cursor (`db()` and `conn.cursor()`) the routes used; the two readers in `query.py` return `dict(row)`. `badge_add` now logs `inserted=<the bool the service returned>`, which is the value `inserted is not None` had.
  Rationale: the tuple-cursor blocks read their rows by position (`row[0]`, `city_id, kind = row`), so keeping the cursor kept the statements and the Python around them as they stood; `record_badge_action` reads no row and works on either cursor (Surprises, revision). The readers follow `query.py`, and both templates and the routes read the rows by key.
  Date/Author: 2026-11-24, M2 session.
- Decision (M2): comments that moved with their blocks were reworded where they named what the route did (`abort`, "reject") or the word `psycopg2`; the docstrings of the six routes were left as they were, though they still describe the transaction the service now holds.
  Rationale: a service has no `abort`, so the comment says what the service returns; the route docstrings describe what the endpoint does, which is unchanged, and rewriting them is tidying this plan does not allow itself.
  Date/Author: 2026-11-24, M2 session.
- Decision (M2): `add_manual_badge` was given three tests beyond the plan's list (over a badge the pipeline attached, that item only, the kind of a `process` template) and the two errors-queue functions one each (that item only).
  Rationale: each pins a clause of a moved statement that the plan's list left free: `ON CONFLICT` against a row the function did not write, the `WHERE id` of each UPDATE, and the `kind` read from the template. The removal check in Surprises shows them doing so.
  Date/Author: 2026-11-24, M2 session.
- Decision (M3): the opening `./tools/verify` was skipped, under the revision entry above.
  Rationale: at the session's start the M2 entry was ticked with its closing run recorded in Artifacts and Notes (`verify: all 6 checks passed in 337s.`), `git rev-parse HEAD` printed `fd0c36582da1f1587aa4677392cac2391770d536`, `git status --short` printed nothing, and `git log --merges --oneline bff4c27..HEAD` printed nothing. The two counting greps printed `11` and `29`, as M2 left them.
  Date/Author: 2026-11-24, M3 session.
- Decision (M3): a subject a coverage test links to (an agenda item, a meeting, a council member) is seeded under an explicit id in a range of its own (987650100, 987650200 and 987650300 upward), not under the id the sequence would give.
  Rationale: the label statement of the coverage list looks one `subject_id` up in `agenda_items`, then `meetings`, then `council_members`, whatever the link's type, and takes the first title it finds; on a fresh database the sequences of the three tables start together, so a meeting and an item seeded by one test can share an id and the meeting's link would be labelled with the item's title. The statement moves as it stands; the test keeps its ids apart so that what it asserts does not depend on what else the database holds.
  Date/Author: 2026-11-24, M3 session.
- Decision (M3): the six readers return plain dictionaries and lists of them (`dict(row)`), where the routes handed the templates the cursor's own rows; `get_coverage_for_edit` returns the three as one tuple, or `None`, and the route unpacks it after its 404.
  Rationale: the M1 entry on readers, applied again: `query.py` returns `dict(row)` elsewhere and the five templates read the rows by key. Interfaces gives the shapes.
  Date/Author: 2026-11-24, M3 session.
- Decision (M3): `ai_panel` keeps the order it had: the first summary is read, then `docket.services.discrepancies` is imported, then the second summary, then `approval_ratio()`. The two summaries are two calls and two transactions.
  Rationale: the boundaries entry above; the import between the two blocks stayed where it stood because moving it is tidying.
  Date/Author: 2026-11-24, M3 session.
- Decision (M3): tests beyond the plan's list were written for clauses it left free: the order and the 200 of the coverage list, both halves of the author label, the order of the outlet lists, the order and the 15 of each search statement, the case-blind match, the slug of a badge, each arm of the meetings-pending count and which version each placeholder gets, the debounce, the 20 runs, and the status counts. The wildcard needles run against all four subject types, not one.
  Rationale: each is a clause of a moved statement; the removal check in Surprises shows them pinned. The plan's list says "at least".
  Date/Author: 2026-11-24, M3 session.

## Outcomes & Retrospective

As authored on 2026-11-24 (UTC), nothing has been executed and there is no outcome to report. Each milestone's session adds its entry beneath this sentence.

M1 (2026-11-24). Seven of the 27 transaction blocks of `src/docket/web/admin.py` and 8 of its 54 statements are gone: the four member routes, the outlet list and the two profile routes call `docket.services`. The acceptance was met with no carve-out; one of its route tests reads the template context where the plan's wording expected the response body, because the page does not print district names (Surprises and Decision Log, M1). Twenty blocks and 46 statements remain, for M2 to M4. What a later session should know: the import in `admin.py` is now a parenthesised block that M2 adds `badges` and `errors_queue` to, and the reads for the admin pages sit at the end of `src/docket/services/query.py` under the comment heading `Reads behind the admin pages (docket.web.admin)`, where M2 to M4 append theirs.

M2 (2026-11-24). Nine more blocks and 17 more statements are gone from `src/docket/web/admin.py`: the two errors-queue POSTs call `docket.services.errors_queue`, the manual badge add and remove call `docket.services.badges`, and the badge-manage page, its swap panel and the three conflict forms read through `docket.services.query`. The acceptance was met with no carve-out. Eleven blocks and 29 statements remain, for M3 and M4. Row `D25`, `docs/specs/calibration.md` and the `_audit` docstring name the new homes. What a later session should know: `admin.py` still imports `json` (the conflict edit-facts POST parses with it) and `db, db_cursor` (M3 and M4 still use them); the word `psycopg2` no longer appears in the module, so M4's `grep -c 'docket\.db\|psycopg2'` has only the import line left to remove; M3 appends its reads after `get_conflict_form_item` at the end of `src/docket/services/query.py`.

M3 (2026-11-24). Six more blocks and 18 more statements are gone from `src/docket/web/admin.py`: the AI dashboard reads through `query.ai_pipeline_summary` and `query.transcript_pipeline_summary`, and the coverage list, new form, edit form and subject search read through `query.list_coverage_for_admin`, `query.list_active_outlets`, `query.get_coverage_for_edit` and `query.search_coverage_subjects`; `_escape_like` went with the search. The acceptance was met with no carve-out. Five blocks and 11 statements remain, all for M4. What a later session should know: `admin.py` still imports `db, db_cursor` (line 23), which M4 deletes with its last block; M4 appends its two reads after `transcript_pipeline_summary` at the end of `src/docket/services/query.py`, which is now 4,640 lines; the coverage list's label statement has a defect this plan carried and nothing records outside this file (Surprises, M3).

## Context and Orientation

### The rule and the helper

`src/docket/db.py` holds the only two ways to reach the database. `db()` is a context manager that yields a psycopg2 connection, commits when its block ends normally, and rolls back and re-raises on any exception. `db_cursor()` wraps it and yields a `RealDictCursor`, whose rows are dictionaries read by column name. A "transaction block" in this plan means one `with db()` or `with db_cursor()` block: everything executed inside it commits or rolls back together.

`ARCHITECTURE.md` (Layer map and dependency rules) says nothing under `src/docket/web/` may call `db()` or `db_cursor()` or execute SQL, and nothing under `src/docket/services/` may import from `src/docket/web/`. Its Known rough edges says some web modules still execute SQL and that `D7` lists them; that line names no module, stays true with four, and is not edited. The check that would enforce the rule mechanically (`boundary-lint` in `docs/capabilities/index.md`) has status `specced`, meaning it is described and not built, so this plan's greps are its evidence and building the check is not part of this plan.

### The module today

`src/docket/web/admin.py` is 1,787 lines: one Flask blueprint with the prefix `/admin`, guarded by a `before_request` hook that redirects anyone whose session has no `admin_user` key. Many of its routes already call services (`query`, `conflict_resolution`, `coverage_writer`, `outlets_writer`, `meeting_types`, `non_meetings`, `calibration`). The 27 blocks that do not are these, with the line each `with` stands on at `bff4c27` and whether its rows are tuples (`db()`) or dictionaries (`db_cursor()`):

Council members (M1). `add_member`, line 79, dictionaries: when a district name was given, `SELECT id FROM districts` by municipality and name, then `INSERT INTO council_members`; an unknown district name stores a NULL district. Line 106, dictionaries, once per municipality inside a loop: the district names of a municipality ordered by `number`. `edit_member`, line 134: one UPDATE of name, email, photo_url, active. `deactivate_member`, line 158: `UPDATE council_members SET active = FALSE`.

Outlets and profile (M1). `outlets_list`, line 1498, dictionaries handed to the template. `profile`, line 1552, one dictionary row handed to the template (or `None`). `profile_update_display_name`, line 1564, one UPDATE.

Errors queue (M2). `errors_retry`, line 284, tuples: SELECT the item's `processing_status::text`, `abort(404)` if there is no row, UPDATE the item back to `pending`, INSERT one `processing_status_audit` row. `errors_escalate`, line 348, tuples: SELECT status and `score_overrides`, `abort(404)` if no row, merge `admin_escalated` and `admin_escalated_by` into the dictionary in Python, UPDATE, INSERT one audit row. Both routes then log and flash using the status the SELECT returned.

Manual badges (M2). `badges_manage_item`, line 697, and `_render_manage_panel`, line 828, dictionaries: the item joined to its meeting and city, 404 when absent. `badge_add`, line 759, tuples: SELECT the city id and the badge template's `kind`, 404 when the item is absent or the slug is no template; INSERT into `agenda_item_badges` with `status` set to `'applied'` explicitly, `ON CONFLICT DO NOTHING RETURNING id`; an audit row only when a row was inserted. `badge_remove`, line 896, tuples: SELECT that the item exists (404), `DELETE ... RETURNING id` (404 when nothing was attached), then the audit row.

Conflict forms (M2). `conflict_form_accept_s1` (line 995), `conflict_form_re_prompt` (line 1043), `conflict_form_edit_facts` (line 1083), dictionaries: the item's `processing_status::text`, and in the third its `extracted_facts`; each route answers 404 unless the status is `cross_stage_conflict`.

AI dashboard (M3). `ai_panel`, lines 490 and 542, dictionaries, two blocks: four read-only statements (items pending, meetings pending, the seven-day cost sums, the last twenty runs), then three (transcript status counts, transcript stage costs, citation-missing rates). The second block's stage-cost statement contains `LIKE 'transcript_%%'` and is executed with no parameters, so psycopg2 sends both percent signs; two wildcards match what one does. It moves as it stands, executed with no parameters.

Coverage reads (M3). `coverage_list`, line 1175, dictionaries: the entries under a WHERE built from the optional `status` and `kind` filters (values always as placeholders), the per-status counts, and, when there are entries, the subjects attached to them. `coverage_new`, line 1237: active outlets. `coverage_edit`, line 1302: the entry (404 when absent), its subject links, and the outlets that are active or are the entry's own. `coverage_search`, line 1423: one of four ILIKE statements chosen by `subject_type`, the needle escaped by the module's `_escape_like`; any other `subject_type` runs nothing and gives an empty list.

Meetings (M4). `_meeting_page`, line 1576: the city slug of a meeting. `hide_meeting`, line 1630, and `unhide_meeting`, line 1667, tuples: SELECT that the meeting exists (404), one UPDATE, an explicit `conn.commit()`. `rescan_meeting_ocr`, line 1708, dictionaries, one transaction: the city slug (404), a COUNT of the meeting's `video_ocr` votes, DELETE their `member_votes`, DELETE the votes, UPDATE `processing_status`. `list_hidden_meetings`, line 1769: one SELECT.

### What the session keys are, and a mismatch this plan carries

`src/docket/web/auth.py` (lines 51 and 52) stores the admin's username under `session["admin_user"]` and the numeric id under `session["admin_user_id"]`. The audit routes use `session.get("admin_user", "unknown")` as an actor name, which fits. But `profile`, `profile_update_display_name` and `coverage_create` use `session["admin_user"]` as `admin_users.id`. The tests that cover them put an integer id under that key (`tests/integration/test_admin_coverage.py`, line 37), so they pass; on a real login the value is a username. This was read from the code and not observed on a running login. (The revision of 2026-11-24 ran the comparison against a throwaway database: PostgreSQL refuses a username where the integer id is expected, so on a real login the three routes fail with a database error; Surprises holds the output.) It looks like a defect, and mending it is a change of behaviour, so this plan does not: the routes go on passing whatever the session holds, the services take it as given with no conversion, and M5 records it as a debt row.

### The debt rows this plan touches

`D7` (row 8 of `docs/DEBT.md`, and a Details paragraph headed `### D7 — SQL in the web layer`): M5 rewrites the row and the paragraph. `D25` lists the files holding badge INSERT statements, among them `src/docket/web/admin.py`; after M2 that INSERT is in `src/docket/services/badges.py`, which the row already lists, so M2 drops `admin.py` from its Where cell. The badge status contract itself does not change (the INSERT keeps `status = 'applied'`), so the row's trigger does not fire. `D209` contains the sentence that a proposal "changes `src/docket/web/admin.py`, a module `D7` still names"; M5 appends a dated clause saying the row stopped naming it. `D14`, `D17` and `D26` are re-deferred in the Decision Log above and their rows are not edited.

Debt ids and decision numbers are allocated by hand (row `D70`). The rule a session applies when it needs one: fetch, then take the lowest number above every one spent on `origin/main`; an open pull request may have spent a number too, which a milestone session cannot read, so the session says in its Decision Log which reading it took. At authoring the highest row was `D211`, the highest decision `0136`, and `gh pr list --state open --json number,headRefName` printed `[]`. These are readings of 2026-11-24, not numbers to use.

### Running tests

`./tools/verify`, run from the worktree root, builds a throwaway database from the migrations, runs every test tier and four other checks, and prints one summary line per check and `verify: all 6 checks passed in <n>s.` Bare `pytest` is refused when the database is not named `docket_test_*`. To run one file:

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/services/test_query_source_hosts.py -q -p no:cacheprovider; tools/test-db --drop

Run at authoring, that printed `4 passed, 1 warning in 0.21s`. The throwaway database holds what the migrations seed (the cities, Birmingham among them) and nothing else, and the unit tier deletes agenda items and votes from it during a full run, so a service test seeds every row it reads, under a prefix of its own, and deletes them before and after each test. `tests/services/test_query_source_hosts.py` is the model: an autouse fixture that deletes by prefix, and the service's name imported inside each test so the file collects before the service exists. Route tests use the fixtures in `tests/integration/conftest.py` (`client`, and `authed_admin_client`, whose session holds `admin_user = "test-admin"`). A test never asserts the size of a whole table or the exact rows of an unfiltered list, because other tests' rows may be in the database: for a function that reads a whole table (`list_outlets`, `list_active_outlets`, `list_coverage_for_admin`, `list_hidden_meetings`, the two summary functions) it asserts that its own seeded rows are present or absent, or the difference between a reading before the seed and one after. Rows a route test makes are removed by a fixture that yields and then deletes, children before parents, so that a failed assertion leaves nothing behind; a test body does not do its own clean-up.

## Plan of Work

Every milestone follows the same order, and the order matters because it is what makes "unchanged" checkable. Run `./tools/verify` and record its summary, unless the Decision Log's entry on the opening run says this session skips it, in which case record what its commands printed. Write the route tests the milestone names for paths that have none, run that file against the unchanged module, and record that it passed. Write the service tests, run them, and record that they fail because the function does not exist. Write the service functions by moving each statement's text exactly as it stands; run the service tests and record that they pass. Replace each block in the route with the call, keeping in the route everything that is Flask (form parsing, `abort`, `flash`, logging, `redirect`, `render_template`). Run the milestone's greps and `./tools/verify`. Write the evidence into Artifacts and Notes, tick the Progress line, commit. Every commit of a milestone session changes this plan file.

### M1: council members, the admin profile, the outlet list

Route tests first, in the new file `tests/integration/test_admin_members.py`: a POST to `/admin/members/add` with a seeded city and a district name that exists stores a member with that district; with a district name that does not exist stores the member with a NULL district; a GET of `/admin/members/add` answers 200 and lists a seeded district name; a POST to `/admin/members/<id>/edit` changes the four fields; a POST to `/admin/members/<id>/deactivate` sets `active` false; a POST to `/admin/members/add` with no district field stores the member with a NULL district; a POST to `/admin/members/<id>/edit` with empty `email` and `photo_url` stores NULL in both. A fixture that yields and then deletes removes the members made. And in the new file `tests/integration/test_admin_profile.py`, with a seeded `admin_users` row whose integer id is put under `session["admin_user"]` (the shape `tests/integration/test_admin_coverage.py` uses; the file's docstring says this is the carried mismatch and not how a login fills the session): a GET of `/admin/profile` answers 200 and shows the seeded username; a POST to `/admin/profile/display-name` with an empty `display_name` stores NULL. `outlets_list` is already tested (`tests/integration/test_admin_outlets.py`, `test_outlets_list_includes_seed`).

Then the services of Interfaces and Dependencies under M1, with their tests in `tests/services/test_council_members_writer.py`, `tests/services/test_admin_users.py` and `tests/services/test_query_admin_roster.py`. The tests cover at least: each function's ordinary case read back from the table; `add_member` with an unknown district name; `list_district_names` in `number` order; `get_admin_profile` for an id with no row returning `None`; `set_display_name` with `None` storing NULL; `add_member` with an empty `district_name` storing a NULL district; `update_member` with `email` and `photo_url` of `None` storing NULL; `update_member` and `deactivate_member` for an id with no row returning without error and changing no seeded member.

Then the routes `add_member`, `edit_member`, `deactivate_member`, `outlets_list`, `profile` and `profile_update_display_name` call them. The GET branch of `add_member` keeps its loop and calls `query.list_district_names` once per municipality.

### M2: the errors queue, manual badges, the conflict forms

Route tests first, in the new file `tests/integration/test_admin_not_found_paths.py`: a POST to `/admin/errors/999999999/retry` and to `/admin/errors/999999999/escalate` each answer 404 and leave the count of `processing_status_audit` rows where it was. (The 404 paths of the badge and conflict-form routes are already tested in `tests/integration/test_admin_badge_audit.py` and `tests/integration/test_conflict_resolution.py`.)

Then the services under M2, with tests in `tests/services/test_errors_queue.py`, `tests/services/test_badges_manual.py` and `tests/services/test_query_admin_items.py`. The tests cover at least: `retry_item` returns the prior status, resets the five columns and writes one audit row with action `retry`; `escalate_item` keeps the keys already in `score_overrides`, adds the two, and writes one audit row whose from and to status are equal; `escalate_item` on an item whose `score_overrides` is NULL stores exactly the two keys; both return `None` and write nothing for an unknown item; `add_manual_badge` returns `True` and writes the badge (`status` `applied`, `source` `manual`, `confidence` 0.95) and one audit row, `False` with no second audit row when repeated, `None` for an unknown item and for an unknown slug; `remove_manual_badge` returns `True` with the row gone and one audit row, `False` with no audit row when the badge was not attached or the item does not exist; the two query functions return their columns for a seeded item and `None` for an unknown one.

Then the routes. `errors_retry` and `errors_escalate` abort on `None` and otherwise log and flash with the returned status, as now. `badge_add` aborts on `None` and logs `inserted=<the bool>`. `badge_remove` aborts on `False`. `badges_manage_item` and `_render_manage_panel` both call `query.get_item_for_badge_manage`. The three conflict-form routes call `query.get_conflict_form_item`.

Three one-line document edits belong to this milestone because the statements they cite move in it: in `docs/DEBT.md` row `D25`, drop `src/docket/web/admin.py` from the Where cell; in `docs/specs/calibration.md` line 11, say the route in `src/docket/web/admin.py` writes through `errors_queue.escalate_item` in `src/docket/services/errors_queue.py`; in `src/docket/services/conflict_resolution.py`, change the `_audit` docstring's `admin.py:300-311` to name `docket.services.errors_queue`.

### M3: coverage reads and the AI dashboard

No new route test is needed first: `tests/integration/test_admin_coverage.py` covers the list, the new form, the edit form and the search, and `tests/integration/test_admin_ai_panel_transcripts.py` renders the dashboard.

The services under M3, with tests in `tests/services/test_query_admin_coverage.py` and `tests/services/test_query_ai_summaries.py`. The tests cover at least: `list_coverage_for_admin` with no filter, with each filter, and with both, its counts by status, and the subjects of a seeded entry; `list_active_outlets` leaving out an inactive outlet; `get_coverage_for_edit` returning `None` for an unknown id and including an inactive outlet when the entry uses it; `search_coverage_subjects` for each of the four subject types, for a needle of `%` matching no row that lacks a literal percent sign, and for an unknown subject type returning an empty list; the two summary functions returning every key Interfaces names, with a seeded `ai_runs` row counted in the seven-day total; `transcript_pipeline_summary` listing a seeded `ai_runs` row whose stage is `transcript_compare` under `transcript_stage_costs` and not listing one seeded with a stage that does not begin `transcript_`, and giving, for discrepancies seeded under a `prompt_version` of the test's own (one with `citation_match` `missing`, one without; seeded the way `tests/integration/test_admin_discrepancies.py` seeds its rows), a `citation_missing` row with `total` 2, `missing` 1 and `rate` 50.0; `list_coverage_for_admin` with a `kind` filter no seeded entry of the test's status has, returning no row of the test's and no subjects for them; `search_coverage_subjects` for a needle of `_` and for one of `\`, each matching only a seeded row that holds that character.

Then `ai_panel`, `coverage_list`, `coverage_new`, `coverage_edit` and `coverage_search` call them. `_escape_like` leaves `admin.py` and goes with the search into `query.py` (no test or other module imports it; `grep -rn '_escape_like' tests src --include='*.py'` at authoring showed only `admin.py`). `ai_panel` keeps importing the two prompt versions and the two config values. It passes three of the four to `ai_pipeline_summary` (the two versions and `AI_ITEM_DEBOUNCE_MINUTES`); `AI_DAILY_BUDGET_USD` is read by no statement and goes on to the template as `budget`, as now. (The first version said all four were passed; the signature in Interfaces was right.)

### M4: meetings

First the pin, `tests/unit/test_admin_module_has_no_sql.py` (Decision Log, revision): run alone it fails on the module as M3 left it, naming the import and the calls it found; record that. Then route tests, in the new file `tests/integration/test_admin_meeting_not_found.py`: a POST to `/admin/meetings/999999999/unhide` and to `/admin/meetings/999999999/rescan-ocr` each answer 404. (The hide route's 404 is already tested.)

The services under M4, with tests in `tests/services/test_non_meetings_admin_hide.py`, `tests/services/test_video_ocr_reset.py` and `tests/services/test_query_admin_meetings.py`. The tests cover at least: `hide_by_admin` sets `is_hidden`, `hidden_at`, `hidden_by` and `hidden_reason = 'admin'` and returns `True`; `unhide_by_admin` clears the four and sets `keep_visible_at`; both return `False` for an unknown meeting; `reset_for_rescan` returns the city slug and the number of `video_ocr` votes, deletes those votes and their member votes, leaves a vote of another source and that vote's `member_votes` in place, and resets the four `processing_status` columns, and returns `None` for an unknown meeting; for a meeting with no `video_ocr` vote it returns the slug and 0 and still resets the columns; `get_meeting_city_slug` and `list_hidden_meetings` for a seeded hidden meeting.

Then the routes call them, the line `from docket.db import db, db_cursor` is deleted, the pin passes, and the closing greps of Validation print what they should.

### M5: the closing documents

In `docs/DEBT.md`, the `D7` row: the Item cell says four web modules; the Where cell lists `src/docket/web/auth.py`, `admin_badge_review.py`, `admin_transcripts.py`, `create_admin.py`; the Why cell adds that `admin.py` was paid by this plan (27 blocks, 54 statements, to the services this plan names); the Trigger cell loses everything from "Overdue for `admin.py`" through the 2026-11-23 firing, keeps the sentence about `source_security.py` being paid, keeps "The next plan touching each module moves its SQL into `services/`", and adds that this plan touched none of the four and re-defers them. The Details paragraph says four modules and replaces "do not open a plan for it alone" with wording that allows a plan the operator asks for, naming this one. Row `D209`: after the sentence about `POST /admin/source-security/refresh`, a dated clause that `D7` stopped naming `admin.py` when this plan closed. A new row, numbered by the rule in Context, for the session-key mismatch: what it is, where (`src/docket/web/admin.py` `profile`, `profile_update_display_name`, `coverage_create`; `src/docket/web/auth.py`), that this plan carried it, and a trigger (the next change to admin login or to those three routes, or the first real login that opens `/admin/profile`). The row says plainly that this is an error on a real login today and not a hazard: the database refuses a username where `admin_users.id` is expected (the output is in Surprises), so the profile page, the display-name form and the creation of a coverage entry fail for anyone who signed in through `/admin/login`; and that `tests/integration/test_admin_coverage.py` (line 37) and this plan's `tests/integration/test_admin_profile.py` hide it by putting an integer under the key. The `D7` row also gains one sentence for whoever pays the other four modules: `src/docket/services/query.py` was 4,294 lines before this plan and now also holds the admin pages' reads, so a split of the admin reads into a module of their own is worth weighing before more are added. The session records at its start what `git rev-parse HEAD` printed.

In `ARCHITECTURE.md`, Services component, Owns: one clause naming `council_members_writer.py`, `admin_users.py` and `errors_queue.py` and what each writes. Nothing else in that file changes.

One decision record under `docs/decisions/`, in the format `docs/decisions/DECISION_FORMAT.md` gives, numbered by the rule in Context: admin routes ask services; a service says not-found by its return value and the route answers 404; a transaction block moves whole. M5 does not move this plan to `plans/completed/` and does not write the closing retrospective; the stage that runs after the last milestone does both.

## Concrete Steps

All commands run from the worktree root, `.claude/worktrees/admin-routes-call-services` under the repository, with that worktree's `venv/`.

    ./tools/verify

Expected last line: `verify: all 6 checks passed in <n>s.` and exit status 0.

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest <one test file> -q -p no:cacheprovider; tools/test-db --drop

Expected: `<n> passed` once the functions exist; before they do, the service tests fail with `ImportError` or `AttributeError`.

    grep -c 'with db()\|with db_cursor()' src/docket/web/admin.py
    grep -c '\.execute(' src/docket/web/admin.py

`grep -c` counts matching lines. At authoring these printed `27` and `54`.

    git diff --stat $(git merge-base origin/main HEAD) -- tests/integration/test_admin_queues.py tests/integration/test_admin_coverage.py tests/integration/test_admin_outlets.py tests/integration/test_admin_hide_meeting.py tests/integration/test_admin_meeting_type.py tests/integration/test_admin_badge_audit.py tests/integration/test_admin_ai_panel_transcripts.py tests/integration/test_conflict_resolution.py tests/integration/test_video_ocr_rescan.py tests/web/test_hidden_meetings_admin.py

Expected at every milestone: no output. At authoring it printed nothing. The comparison is against the commit this branch left `origin/main` at, not against wherever `origin/main` now stands, so a later merge to `main` that edits one of these files does not show here (the first version compared against `origin/main` itself; the revision ran this form, which printed nothing).

## Validation and Acceptance

M1 is accepted when: `./tools/verify` exits zero; the two counting greps print `20` and `46`; the `git diff --stat` line above prints nothing; `tests/integration/test_admin_members.py` and `tests/integration/test_admin_profile.py`, each run alone, passed before the routes changed and pass after, all runs recorded; and the three new files under `tests/services/` run alone print only passes, having failed before the functions existed.

M2 is accepted when: `./tools/verify` exits zero; the two greps print `11` and `29`; the `git diff --stat` line prints nothing; `tests/integration/test_admin_not_found_paths.py` passed before and after; the three new service test files pass, having failed before; `grep '^| D25 ' docs/DEBT.md | cut -d'|' -f4` prints a cell without `src/docket/web/admin.py`; `grep -c 'admin.py:300-311' src/docket/services/conflict_resolution.py` prints `0`; and `grep -c 'errors_queue' docs/specs/calibration.md` prints `1` or more (it printed `0` at the revision).

M3 is accepted when: `./tools/verify` exits zero; the two greps print `5` and `11`; the `git diff --stat` line prints nothing; the two new service test files pass, having failed before; and `grep -c '_escape_like' src/docket/web/admin.py` prints `0`.

M4 is accepted when: `./tools/verify` exits zero; `grep -n 'db_cursor\|db()\|\.execute(' src/docket/web/admin.py` prints nothing; `grep -c 'docket\.db\|psycopg2' src/docket/web/admin.py` prints `0` (it printed `2` at the revision: the import, and a comment that leaves in M2); `tests/unit/test_admin_module_has_no_sql.py` run alone failed before the routes changed and passes after, both runs recorded; `grep -rl 'db_cursor\|db()' src/docket/web` prints exactly `src/docket/web/auth.py`, `src/docket/web/create_admin.py`, `src/docket/web/admin_badge_review.py` and `src/docket/web/admin_transcripts.py`, in any order; the `git diff --stat` line prints nothing; `tests/integration/test_admin_meeting_not_found.py` passed before and after; and the three new service test files pass, having failed before.

M5 is accepted when: `./tools/verify` exits zero; `grep '^| D7 ' docs/DEBT.md | cut -d'|' -f3,4` prints an Item cell that says four and a Where cell naming the four files and not `admin.py`; `grep '^| D7 ' docs/DEBT.md | grep -c 'Overdue'` prints `0` (it prints `1` today); `grep -A3 '^### D7' docs/DEBT.md | grep -c 'four modules'` prints `1` and the same with `five modules` prints `0`; the new debt row and the decision record exist under numbers no other row or record on `origin/main` holds; and `git diff --stat <the commit M5's session recorded at its start> -- src tests` prints nothing. (The first version compared against `origin/main`, which would have listed every file M1 to M4 changed.)

For every service function, the session records in Artifacts and Notes the names of the tests that call it. The service-tier total rises by the tests the new files collect; the session records the total before and after, and no figure is fixed here.

There is no step for the operator beyond the usual merge and deploy. A look at `/admin/members/`, `/admin/ai`, `/admin/coverage` and `/admin/meetings/hidden` after the deploy, each answering as before, is the operator's to make if wanted; no session has a browser or a production login.

## Idempotence and Recovery

Every step is an edit to source, tests or documents; nothing migrates data and nothing is run against production. A step done twice changes nothing. A milestone that goes wrong is undone with `git restore` on its files, or by reverting its commits. If a milestone will not fit in its session, the session splits its Progress line in place into what is done and what remains, records the split in the Decision Log, and stops; the block counts in Validation then apply to the sum. If a moved statement makes an existing admin test fail, the move is wrong, not the test: restore the statement's text from `git show origin/main:src/docket/web/admin.py` and compare.

## Artifacts and Notes

Authoring baseline, observed on 2026-11-24 (UTC) at `bff4c27`:

    $ ./tools/verify
    verify: unit+web+services ... ok (201s)      3825 passed, 5 skipped, 4 xfailed
    verify: integration ... ok (134s)            1164 passed
    verify: judge-fixtures ... ok (1s)
    verify: workflows ... ok (0s)
    verify: transcriber ... ok (11s)             147 passed
    verify: plans ... ok (0s)
    verify: all 6 checks passed in 348s.
    $ grep -rl 'db_cursor\|db()' src/docket/web
    src/docket/web/auth.py
    src/docket/web/create_admin.py
    src/docket/web/admin.py
    src/docket/web/admin_badge_review.py
    src/docket/web/admin_transcripts.py

Blocks and statements per milestone, counted from the `with` lines listed in Context: M1 seven blocks and 8 statements, M2 nine and 17, M3 six and 18, M4 five and 11; 27 and 54 in all.

Each milestone's session adds a heading here with what it ran and what was printed.

### M1, observed on 2026-11-24 (UTC)

The opening `./tools/verify` was skipped (Decision Log, M1). One throwaway database (`docket_test_fdb4ad9a`, built by `tools/test-db`) served every single-file run below and was dropped before the closing `./tools/verify`. Each run is `DATABASE_URL=<that database> venv/bin/python -m pytest <file> -q -p no:cacheprovider`.

Route tests, written first and run against the unchanged module (`grep -c` of the two patterns still `27` and `54`):

    tests/integration/test_admin_members.py     7 passed, 1 warning in 1.70s
    tests/integration/test_admin_profile.py     3 passed, 1 warning in 1.12s

Service tests, written next and run before any service function existed (this is the state of the commit that holds them):

    tests/services/test_council_members_writer.py   8 failed, 1 warning in 0.40s   ModuleNotFoundError: No module named 'docket.services.council_members_writer'
    tests/services/test_admin_users.py              3 failed, 1 warning in 0.07s   ModuleNotFoundError: No module named 'docket.services.admin_users'
    tests/services/test_query_admin_roster.py       7 failed, 1 warning in 0.14s   ImportError: cannot import name 'get_admin_profile' / 'list_district_names' / 'list_outlets' from 'docket.services.query'

After the service functions were written and before any route changed (the two counting greps still `27` and `54`):

    tests/services/test_council_members_writer.py   8 passed, 1 warning in 0.54s
    tests/services/test_admin_users.py              3 passed, 1 warning in 0.13s
    tests/services/test_query_admin_roster.py       7 passed, 1 warning in 0.30s

After the routes were changed to call them:

    tests/integration/test_admin_members.py         7 passed, 1 warning in 1.79s
    tests/integration/test_admin_profile.py         3 passed, 1 warning in 1.24s
    tests/services/test_council_members_writer.py   8 passed, 1 warning in 0.99s
    tests/services/test_admin_users.py              3 passed, 1 warning in 0.14s
    tests/services/test_query_admin_roster.py       7 passed, 1 warning in 0.29s
    tests/integration/test_admin_outlets.py         2 passed, 1 warning in 0.99s
    tests/integration/test_admin_coverage.py        12 passed, 1 warning in 2.80s
    $ grep -c 'with db()\|with db_cursor()' src/docket/web/admin.py
    20
    $ grep -c '\.execute(' src/docket/web/admin.py
    46
    $ git diff --stat $(git merge-base origin/main HEAD) -- <the ten existing admin test files of Concrete Steps>
    (no output)
    $ ./tools/verify          (on the tree the M1 code commit holds; exit status 0)
    verify: unit+web+services ... ok (195s)      3843 passed, 5 skipped, 4 xfailed
    verify: integration ... ok (129s)            1174 passed
    verify: judge-fixtures ... ok (0s)           12 of 12 passed
    verify: workflows ... ok (0s)
    verify: transcriber ... ok (11s)             147 passed
    verify: plans ... ok (0s)
    verify: all 6 checks passed in 335s.

Against the authoring baseline the first tier rose by 18 (3825 to 3843: the 18 tests of the three new files under `tests/services/`) and the integration tier by 10 (1164 to 1174: the two new route test files).

The tests that call each M1 service function. `council_members_writer.add_member`: `test_add_member_stores_the_row_under_the_named_district_of_that_city`, `test_add_member_with_an_unknown_district_name_stores_a_null_district`, `test_add_member_with_an_empty_district_name_looks_nothing_up`. `council_members_writer.update_member`: `test_update_member_changes_the_four_fields_of_that_member_only`, `test_update_member_with_none_email_and_photo_url_stores_null`, `test_update_member_for_an_id_with_no_row_changes_no_seeded_member`. `council_members_writer.deactivate_member`: `test_deactivate_member_sets_active_false_on_that_member_only`, `test_deactivate_member_for_an_id_with_no_row_changes_no_seeded_member` (all in `tests/services/test_council_members_writer.py`). `admin_users.set_display_name`: `test_set_display_name_stores_the_name_on_that_user_only`, `test_set_display_name_with_none_stores_null`, `test_set_display_name_for_an_id_with_no_row_changes_no_seeded_user` (`tests/services/test_admin_users.py`). `query.get_admin_profile`: `test_get_admin_profile_returns_the_username_and_display_name_of_that_id`, `test_get_admin_profile_with_no_display_name_holds_none_under_the_key`, `test_get_admin_profile_for_an_id_with_no_row_is_none`. `query.list_district_names`: `test_list_district_names_is_that_citys_names_in_number_order`, `test_list_district_names_for_a_city_with_no_district_is_an_empty_list`. `query.list_outlets`: `test_list_outlets_holds_the_five_columns_of_a_seeded_outlet_active_or_not`, `test_list_outlets_is_ordered_by_name` (all in `tests/services/test_query_admin_roster.py`). Through the routes, the ten tests of `tests/integration/test_admin_members.py` and `tests/integration/test_admin_profile.py` and the existing `test_outlets_list_includes_seed` and `test_profile_display_name_update` reach the same functions.

### M2, observed on 2026-11-24 (UTC)

The opening `./tools/verify` was skipped (Decision Log, M2). One throwaway database (`docket_test_fdb4ad9a`, built by `tools/test-db`) served every single-file run below. Each run is `DATABASE_URL=<that database> venv/bin/python -m pytest <file> -q -p no:cacheprovider`.

Route tests, written first and run against the unchanged module (`grep -c` of the two patterns still `20` and `46`):

    tests/integration/test_admin_not_found_paths.py   2 passed, 1 warning in 1.02s

Service tests, written next and run before any service function existed (this is the state of the commit that holds them):

    tests/services/test_errors_queue.py         9 failed, 1 warning in 0.33s              ModuleNotFoundError: No module named 'docket.services.errors_queue'
    tests/services/test_badges_manual.py        10 failed, 1 passed, 1 warning in 0.23s   ImportError: cannot import name 'add_manual_badge' / 'remove_manual_badge' from 'docket.services.badges'
    tests/services/test_query_admin_items.py    5 failed, 1 warning in 0.18s              ImportError: cannot import name 'get_item_for_badge_manage' / 'get_conflict_form_item' from 'docket.services.query'

The one test of `test_badges_manual.py` that passed there calls no service: `test_the_two_slugs_are_templates_of_different_kinds` reads `priority_badge_templates` to show the two slugs the file uses are seeded by the migrations, one `policy` and one `process`.

After the service functions were written and before any route changed (the two counting greps still `20` and `46`):

    tests/services/test_errors_queue.py         9 passed, 1 warning in 0.54s
    tests/services/test_badges_manual.py        11 passed, 1 warning in 0.65s
    tests/services/test_query_admin_items.py    5 passed, 1 warning in 0.29s

After the routes were changed to call them and the three documents edited:

    tests/integration/test_admin_not_found_paths.py   2 passed, 1 warning in 1.01s
    tests/services/test_errors_queue.py               9 passed, 1 warning in 0.55s
    tests/services/test_badges_manual.py              11 passed, 1 warning in 0.65s
    tests/services/test_query_admin_items.py          5 passed, 1 warning in 0.29s
    tests/integration/test_admin_queues.py            26 passed, 1 warning in 1.97s
    tests/integration/test_admin_badge_audit.py       40 passed, 1 warning in 3.14s
    tests/integration/test_conflict_resolution.py     45 passed, 1 warning in 3.01s
    $ grep -c 'with db()\|with db_cursor()' src/docket/web/admin.py
    11
    $ grep -c '\.execute(' src/docket/web/admin.py
    29
    $ git diff --stat $(git merge-base origin/main HEAD) -- <the ten existing admin test files of Concrete Steps>
    (no output)
    $ grep '^| D25 ' docs/DEBT.md | cut -d'|' -f4
     `src/docket/ai/badges_process.py`, `src/docket/ai/pipeline.py`, `src/docket/services/badges.py`, `src/docket/web/admin_badge_review.py`
    $ grep -c 'admin.py:300-311' src/docket/services/conflict_resolution.py
    0
    $ grep -c 'errors_queue' docs/specs/calibration.md
    1
    $ grep -c 'psycopg2' src/docket/web/admin.py
    0
    $ tools/test-db --drop    (the single-file database dropped; then:)
    $ ./tools/verify          (on the tree commit `03e6d8e` holds; exit status 0)
    verify: unit+web+services ... ok (196s)      3868 passed, 5 skipped, 4 xfailed
    verify: integration ... ok (130s)            1176 passed
    verify: judge-fixtures ... ok (0s)           12 of 12 passed
    verify: workflows ... ok (0s)
    verify: transcriber ... ok (11s)             147 passed
    verify: plans ... ok (0s)
    verify: all 6 checks passed in 337s.

Against M1's closing run the first tier rose by 25 (3843 to 3868: the 25 tests of the three new files under `tests/services/`) and the integration tier by 2 (1174 to 1176: the new route test file).

The tests that call each M2 service function. `errors_queue.retry_item`: `test_retry_item_returns_the_prior_status_and_resets_the_five_columns`, `test_retry_item_writes_one_audit_row_with_action_retry`, `test_retry_item_touches_that_item_only`, `test_retry_item_for_an_unknown_item_is_none_and_writes_nothing`. `errors_queue.escalate_item`: `test_escalate_item_keeps_the_keys_already_there_and_adds_the_two`, `test_escalate_item_on_null_score_overrides_stores_exactly_the_two_keys`, `test_escalate_item_writes_one_audit_row_whose_from_and_to_status_are_equal`, `test_escalate_item_touches_that_item_only`, `test_escalate_item_for_an_unknown_item_is_none_and_writes_nothing` (all in `tests/services/test_errors_queue.py`). `badges.add_manual_badge`: `test_add_manual_badge_writes_the_badge_and_one_audit_row` (once for a `policy` slug, once for a `process` one), `test_add_manual_badge_repeated_is_false_with_no_second_audit_row`, `test_add_manual_badge_over_a_pipeline_badge_is_false_and_leaves_it`, `test_add_manual_badge_touches_that_item_only`, `test_add_manual_badge_for_an_unknown_item_is_none_and_writes_nothing`, `test_add_manual_badge_for_an_unknown_slug_is_none_and_writes_nothing`. `badges.remove_manual_badge`: `test_remove_manual_badge_deletes_that_badge_and_writes_one_audit_row`, `test_remove_manual_badge_not_attached_is_false_with_no_audit_row`, `test_remove_manual_badge_for_an_unknown_item_is_false_with_no_audit_row` (all in `tests/services/test_badges_manual.py`). `query.get_item_for_badge_manage`: `test_get_item_for_badge_manage_returns_the_seven_columns_of_that_item`, `test_get_item_for_badge_manage_for_an_unknown_item_is_none`. `query.get_conflict_form_item`: `test_get_conflict_form_item_returns_id_facts_and_status_as_text`, `test_get_conflict_form_item_with_no_facts_holds_none_under_the_key`, `test_get_conflict_form_item_for_an_unknown_item_is_none` (all in `tests/services/test_query_admin_items.py`). Through the routes, the two tests of `tests/integration/test_admin_not_found_paths.py` and the existing tests of `tests/integration/test_admin_queues.py`, `tests/integration/test_admin_badge_audit.py` and `tests/integration/test_conflict_resolution.py` reach the same functions.

### M3, observed on 2026-11-24 (UTC)

The opening `./tools/verify` was skipped (Decision Log, M3). One throwaway database (`docket_test_fdb4ad9a`, built by `tools/test-db`) served every single-file run below. Each run is `DATABASE_URL=<that database> venv/bin/python -m pytest <file> -q -p no:cacheprovider`. No route test was written first: Plan of Work says the existing files cover the five routes, and run together against the unchanged module (`grep -c` of the two patterns `11` and `29`) they printed:

    tests/integration/test_admin_coverage.py tests/integration/test_admin_ai_panel_transcripts.py   13 passed, 1 warning in 3.26s

Service tests, written next and run before any service function existed (this is the state of the commit that holds them):

    tests/services/test_query_admin_coverage.py   39 failed, 1 warning in 1.39s   ImportError: cannot import name 'list_coverage_for_admin' / 'list_active_outlets' / 'get_coverage_for_edit' / 'search_coverage_subjects' from 'docket.services.query'
    tests/services/test_query_ai_summaries.py     14 failed, 1 warning in 0.61s   ImportError: cannot import name 'ai_pipeline_summary' / 'transcript_pipeline_summary' from 'docket.services.query'

After the service functions were written and before any route changed (the two counting greps still `11` and `29`):

    tests/services/test_query_admin_coverage.py   39 passed, 1 warning in 2.79s
    tests/services/test_query_ai_summaries.py     14 passed, 1 warning in 1.13s

After the routes were changed to call them, `_escape_like` had left `admin.py`, and the three assertions of the removal check were added (the counts of tests did not change):

    tests/services/test_query_admin_coverage.py            39 passed, 1 warning in 2.82s
    tests/services/test_query_ai_summaries.py              14 passed, 1 warning in 1.07s
    tests/integration/test_admin_coverage.py               12 passed, 1 warning in 2.35s
    tests/integration/test_admin_ai_panel_transcripts.py   1 passed, 1 warning in 0.87s
    $ grep -c 'with db()\|with db_cursor()' src/docket/web/admin.py
    5
    $ grep -c '\.execute(' src/docket/web/admin.py
    11
    $ grep -c '_escape_like' src/docket/web/admin.py
    0
    $ grep -rn '_escape_like' tests src --include='*.py'
    src/docket/services/query.py:4491:def _escape_like(s: str) -> str:
    src/docket/services/query.py:4511:    needle = f"%{_escape_like(q)}%"
    $ git diff --stat $(git merge-base origin/main HEAD) -- <the ten existing admin test files of Concrete Steps>
    (no output)
    $ tools/test-db --drop    (the single-file database dropped; then:)
    $ ./tools/verify          (on the tree commit `afe1fad` holds; exit status 0)
    verify: unit+web+services ... ok (204s)      3921 passed, 5 skipped, 4 xfailed
    verify: integration ... ok (132s)            1176 passed
    verify: judge-fixtures ... ok (0s)           12 of 12 passed
    verify: workflows ... ok (0s)
    verify: transcriber ... ok (11s)             147 passed
    verify: plans ... ok (0s)
    verify: all 6 checks passed in 347s.

Against M2's closing run the first tier rose by 53 (3868 to 3921: the 39 and 14 tests of the two new files under `tests/services/`) and the integration tier did not change (1176: this milestone wrote no route test).

The tests that call each M3 service function. `query.list_coverage_for_admin`: `test_list_coverage_for_admin_with_no_filter_holds_the_nine_columns_of_each_entry`, `test_list_coverage_for_admin_is_newest_update_first`, `test_list_coverage_for_admin_with_a_status_filter_holds_that_status_only`, `test_list_coverage_for_admin_with_a_kind_filter_holds_that_kind_only`, `test_list_coverage_for_admin_with_both_filters_holds_rows_that_meet_both`, `test_list_coverage_for_admin_with_a_kind_no_entry_of_that_status_has`, `test_list_coverage_for_admin_returns_at_most_two_hundred_rows`, `test_list_coverage_for_admin_counts_every_status_whatever_the_filter`, `test_list_coverage_for_admin_labels_the_subjects_of_each_entry_in_link_order`, `test_list_coverage_for_admin_holds_subjects_only_for_the_rows_it_returns`. `query.list_active_outlets`: `test_list_active_outlets_holds_three_columns_and_leaves_out_an_inactive_outlet`, `test_list_active_outlets_is_ordered_by_name`. `query.get_coverage_for_edit`: `test_get_coverage_for_edit_returns_the_entry_its_links_and_the_outlets`, `test_get_coverage_for_edit_of_a_note_lists_active_outlets_only`, `test_get_coverage_for_edit_for_an_unknown_id_is_none`. `query.search_coverage_subjects`: `test_search_coverage_subjects_finds_a_row_of_that_type_whatever_its_case` and `test_search_coverage_subjects_returns_at_most_fifteen` (each once per subject type), `test_search_coverage_subjects_takes_a_wildcard_character_literally` (once per subject type and needle, twelve in all), `test_search_coverage_subjects_for_agenda_items_is_highest_id_first`, `test_search_coverage_subjects_for_meetings_is_latest_date_first`, `test_search_coverage_subjects_for_badges_matches_the_slug_too_and_returns_it_as_id`, `test_search_coverage_subjects_for_an_unknown_subject_type_is_an_empty_list` (all in `tests/services/test_query_admin_coverage.py`). `query.ai_pipeline_summary`: `test_ai_pipeline_summary_returns_the_four_keys`, `test_ai_pipeline_summary_counts_an_item_with_no_version_or_an_older_one`, `test_ai_pipeline_summary_measures_items_against_the_item_version_it_is_given`, `test_ai_pipeline_summary_leaves_out_an_item_younger_than_the_debounce`, `test_ai_pipeline_summary_counts_an_unadopted_meeting_whose_items_are_all_done`, `test_ai_pipeline_summary_measures_meetings_against_both_versions_it_is_given`, `test_ai_pipeline_summary_counts_an_adopted_meeting_until_its_phase_is_adopted`, `test_ai_pipeline_summary_sums_cost_and_tokens_of_the_last_seven_days`, `test_ai_pipeline_summary_lists_the_last_twenty_runs_newest_id_first`. `query.transcript_pipeline_summary`: `test_transcript_pipeline_summary_returns_the_three_keys`, `test_transcript_pipeline_summary_counts_transcripts_by_status_in_status_order`, `test_transcript_pipeline_summary_sums_a_transcript_stage_over_seven_days`, `test_transcript_pipeline_summary_lists_transcript_compare_and_no_other_kind_of_stage`, `test_transcript_pipeline_summary_gives_the_citation_missing_rate_of_a_prompt_version` (all in `tests/services/test_query_ai_summaries.py`). Through the routes, the existing tests of `tests/integration/test_admin_coverage.py` and `tests/integration/test_admin_ai_panel_transcripts.py` reach the same functions.

## Interfaces and Dependencies

No new library. Services import `db` or `db_cursor` from `docket.db` and nothing from `flask` or `docket.web`. A function whose rows a template reads by key uses `db_cursor()`; one that returns plain values may use either. Every function below opens exactly one transaction.

M1. New module `src/docket/services/council_members_writer.py`:

    def add_member(*, municipality_id: int, name: str, district_name: str, email: str | None, photo_url: str | None) -> None
    def update_member(member_id: int, *, name: str, email: str | None, photo_url: str | None, active: bool) -> None
    def deactivate_member(member_id: int) -> None

`add_member` looks the district up only when `district_name` is not empty, and inserts with `active` true. New module `src/docket/services/admin_users.py`:

    def set_display_name(admin_user_id, display_name: str | None) -> None

In `src/docket/services/query.py`:

    def get_admin_profile(admin_user_id) -> dict | None            # username, display_name
    def list_district_names(municipality_id: int) -> list[str]     # ordered by districts.number
    def list_outlets() -> list[dict]                               # id, slug, name, homepage, is_active; by name

`set_display_name` and `get_admin_profile` pass `admin_user_id` to the statement as given, with no conversion, no check and no type annotation (see the session-key mismatch in Context). The first version of this section put the read in `admin_users.py` under the name `get_profile`; the Decision Log's revision entry moved it.

M2. New module `src/docket/services/errors_queue.py`:

    def retry_item(item_id: int, actor: str) -> str | None      # the status before; None when no such item
    def escalate_item(item_id: int, actor: str) -> str | None   # the status, unchanged; None when no such item

The reason strings (`Admin retry from errors queue`, `Admin escalated from errors queue (manual review needed)`) and the escalate payload stay as they are. In `src/docket/services/badges.py`:

    def add_manual_badge(item_id: int, slug: str, actor: str) -> bool | None
    def remove_manual_badge(item_id: int, slug: str, actor: str) -> bool

`add_manual_badge` returns `None` when the item does not exist or the slug is not in `priority_badge_templates`, `True` when it inserted (and wrote the audit row), `False` when the badge was already attached (no audit row). `remove_manual_badge` returns `False` when the item does not exist or the badge was not attached, having written nothing. Both write their audit row through `record_badge_action(cur, item_id, slug, 'added' or 'removed', 'admin', actor=actor)` in the same module. In `query.py`:

    def get_item_for_badge_manage(item_id: int) -> dict | None   # id, title, municipality_id, municipality_slug, municipality_name, meeting_id, meeting_date
    def get_conflict_form_item(item_id: int) -> dict | None      # id, extracted_facts, processing_status (text)

M3. In `query.py`:

    def list_coverage_for_admin(status: str | None, kind: str | None) -> tuple[list[dict], dict[str, int], dict[int, list[dict]]]
    def list_active_outlets() -> list[dict]                      # id, slug, name; by name
    def get_coverage_for_edit(coverage_id: int) -> tuple[dict, list[dict], list[dict]] | None
    def search_coverage_subjects(subject_type: str, q: str) -> list[dict]    # [{"id", "label"}], at most 15
    def ai_pipeline_summary(item_version: int, meeting_version: int, debounce_minutes: int) -> dict
    def transcript_pipeline_summary() -> dict

`list_coverage_for_admin` returns the rows, the counts by status, and the subjects keyed by coverage id, as the route builds them today. `get_coverage_for_edit` returns the entry, its subject links and the outlets, or `None` when there is no entry. `search_coverage_subjects` is called only with a non-empty `q` (the route keeps its early return), escapes it, and returns an empty list for a subject type it does not know. `ai_pipeline_summary` returns the keys `items_pending`, `meetings_pending`, `seven_day` (a dict of `total`, `cache_reads`, `regular_reads`) and `runs`; `transcript_pipeline_summary` returns `transcript_status_counts`, `transcript_stage_costs` and `citation_missing`. The two are separate functions because they are separate transactions today. The three arguments are `ITEM_PROMPT_VERSION` and `MEETING_PROMPT_VERSION` from `docket.ai.prompts` (both the integer 2 at the revision) and `AI_ITEM_DEBOUNCE_MINUTES` from `docket.config`; the session reads that constant's type in `src/docket/config.py` and annotates to match if it is not an `int`.

M4. In `src/docket/services/non_meetings.py`:

    def hide_by_admin(meeting_id: int, admin_user_id: int | None) -> bool    # False when no such meeting
    def unhide_by_admin(meeting_id: int) -> bool

In `src/docket/services/video_ocr.py`:

    def reset_for_rescan(meeting_id: int) -> tuple[str, int] | None   # (city slug, video_ocr votes deleted); None when no such meeting

In `query.py`:

    def get_meeting_city_slug(meeting_id: int) -> str | None
    def list_hidden_meetings() -> list[dict]

`_meeting_page` in `admin.py` stays as the function that turns the slug into a URL with `url_for`.

## Revision note

2026-11-24 (UTC), authoring. This is the first version of the plan. What it deliberately leaves out, from the scope brief the operator's goal was studied into: the other four modules of `D7` (`auth.py`, `admin_badge_review.py`, `admin_transcripts.py`, `create_admin.py`), which stay on the row; any edit to the Known rough edges line of `ARCHITECTURE.md`, which stays true; `docs/specs/meeting-types.md` line 101 and `docs/specs/calibration.md` line 21, which name `admin.py` only as where a route lives; a fix for the session-key mismatch, which is carried and recorded as a debt row; CSRF protection on the admin POST routes (`D14`, issue #83) and an audit row for the force-rescan (`D17`, issue #85), both changes of behaviour; any tidying beyond the three the Decision Log allows; building the `boundary-lint` check; and any sweep of what admin pages do when the database does not answer (`D209`). The brief said no spec changes; the authoring found one sentence, `docs/specs/calibration.md` line 11, that says where the escalate statement lives, and M2 edits it.

2026-11-24 (UTC), revised before any milestone ran, at the operator's request, against an outside review of the first version. Every suggestion was checked in the code at `bff4c27` before it was taken or left. Mended, because the first version was wrong: M5's last check compared against `origin/main` and would have listed M1 to M4's files (it now compares against the commit M5 starts on); the existing-tests comparison now uses the branch's merge base, so a later merge to `main` cannot fail it; Plan of Work said `ai_panel` passes four values where the signature takes three (three is right, and the signature is typed); `get_profile`, a read, was placed in a module the plan said writes (it is `query.get_admin_profile`); M2 had no check on its edit to `docs/specs/calibration.md`; M4's closing check did not look for an import of `docket.db`. Added: route tests for `GET /admin/profile` and for clearing the display name, which no test covered; service and route cases for an empty district, NULL fields, unknown ids, a NULL `score_overrides`, a transcript stage row, the citation rate, a filter that matches nothing, the needles `_` and `\`, and a rescan with no `video_ocr` vote; the rule that tests assert their own rows and clean up in a fixture; the rule for when a session skips the opening `./tools/verify`; a pin test on `admin.py` in M4; the wording of the session-key debt row, after the error was observed on a throwaway database; one sentence on the `D7` row about the size of `query.py`. Not taken, with reasons in the Decision Log: a three-valued return for `add_manual_badge`, named tuples for the coverage reads, and one statement for the add-member form's districts. Checked and found as the plan assumed, recorded in Surprises: the cursor `record_badge_action` needs, the two 404s of `badge_remove`, the JOINs of the two badge-manage lookups, the session key `hide_meeting` reads, and the reach of `grep -A3` on the `D7` paragraph. Validation clauses re-read against the changes: M1 (the new route test file), M2 (`calibration.md`), M4 (the pin and the import grep; the counts 20/46, 11/29 and 5/11 are unchanged because no statement moved between milestones), M5 (the comparison's base). No Progress entry's text was changed.
