# Show how each Mobile council member voted, read from the city's minutes, each vote linked to its minutes page

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.


## Purpose / Big Picture

docket.pub publishes Alabama cities' council records with every fact linked to the city's own document. For Birmingham a meeting page shows how each member voted. For Mobile it shows nothing: the adapter for Mobile's vendor system (CivicClerk) returns no votes, the `votes` table has no page column, and the meeting page prints no per-vote source link.

After this plan is merged, deployed, and the operator's written-out steps are run, a reader who opens a Mobile City Council meeting under https://docket.pub/al/mobile/ dated 2021-11-02 or later, whose minutes the city has published, sees a Votes section sourced "official minutes": one block per motion the minutes record, headed by what the presiding officer declared in the minutes' own words ("the resolution adopted", "the waiver tabled"), with the count and each member by name as yea, nay, abstain or absent. Each block carries a link to the city's own Minutes PDF with `#page=N`, N being the page the vote is printed on, and the link's text names that page.

Meetings from 2024-06-25 on have structured agenda items; there a vote is attached to its item by the code the item's title starts with (`40-948`) against the code the minutes print (`RESOLUTION: 40-948-2026`), and the item's page shows the vote. Meetings from 2021-11-02 to 2024-06-18 have no agenda items and the city's system holds none; their votes are shown on the meeting page under the code and caption the minutes themselves print, each linked to its page, and no agenda item row is made. That reads "each item" in the goal as the item the minutes name.

Three things the reader of this plan should know before going further, each measured by the author on 2026-11-21 by reading all 254 Minutes files the city lists for these meetings.

First, not every meeting gets votes. Of the 135 meetings before 2024-06-25, the city's files hold minutes for 106; 29 (most of them from November 2023 to April 2024) have no minutes among the files and so get no link and no votes, which is the rule `docs/PRINCIPLES.md` calls Source or silence. Of the meetings from 2024-06-25 on, 119 have minutes today and one more has a file labelled Minutes that is in fact another meeting's agenda; that one loses its wrong link.

Second, the city serves its files with `content-disposition: attachment`, so a browser downloads the PDF instead of opening it at the page. The link is still the city's own address with `#page=N`, and because the fragment may do nothing, the link's words carry the page number ("Minutes, page 5"). Whether that is enough is the operator's look, written out in Validation and Acceptance.

Third, the reader is built to take its city from settings and only Mobile is switched on and checked.

What stands in for "it works" before the operator's steps: a parser test over saved Mobile minutes text that cannot pass today (no reader exists) and passes afterwards; a service test that pairs a file to the meeting its first page names and stores its votes with their pages; a web test that a Mobile vote renders a link ending `#page=N`; and `./tools/verify` passing. After the operator's steps: a read-only production count of `votes` rows with `minutes_reader = 'mobile'`, zero today by construction, compared with the per-meeting figures in Artifacts and Notes.


## Progress

- [x] (2026-11-22 02:43Z) M1: `docket.analysis.mobile_minutes.read_minutes` reads the page texts of a Mobile minutes file into the date its first page prints and one record per vote (page, ayes, nays, abstentions, absent members, the motion, what the presiding officer declared, a result, and the item's code and caption where the minutes print them), opening no transaction; the tests built from the saved minutes text under `tests/fixtures/mobile_minutes/` pass and `./tools/verify` passes
- [x] (2026-11-22 03:35Z) M2: a new numbered migration adds the page, caption, motion, declaration and reader columns to `votes`, the `minutes_files` table, and name aliases on `council_members`, and corrects Scott Jones's row from the roll calls read; the resolver answers to an alias, and the vote matcher's text rules pass over a vote a minutes reader wrote; their tests pass and `./tools/verify` passes
- [x] (2026-11-22 04:15Z) M3: `docket.services.minutes_votes` reads a city's listed Minutes files up to a cap, pairs each to the one meeting its first page dates, stores that meeting's minutes link and its votes with their member votes in one transaction per file, records every file it read in `minutes_files`, and attaches votes to agenda items by code in one statement; its tests on seeded rows pass and `./tools/verify` passes
- [x] (2026-11-22 04:50Z) M4: `CivicClerkAdapter` lists the Minutes files of the events it listed and fetches one with its delay and retries, `ingest_municipality` keeps a paired minutes link and runs the reader as a stage for a city whose `adapter_config` names one, its two early returns that raised `TypeError` return their error, and `scripts/read_minutes_votes.py` runs the same read for one city as a dry run or with `--apply`; their tests pass and `./tools/verify` passes
- [x] (2026-11-22 05:26Z) M5: the meeting page prints a minutes-reader vote with the declaration, the code and caption, the motion, and a link to its minutes page; the item page's vote link names the page; the member page prints the declaration and the caption; a vote from any other writer renders as before; the web tests pass and `./tools/verify` passes
- [ ] M6: the close: `docs/specs/votes.md`, `docs/specs/civicclerk-ingest.md`, `docs/specs/operations.md`, `docs/specs/index.md`, `ARCHITECTURE.md`, `GOALS.md`, `docs/birmingham/03-votes-and-facts.md` and `docs/runbooks/cron-worker.md` describe what M1 to M5 built, the durable decisions are graduated to `docs/decisions/`, and `docs/DEBT.md` has `D180`, `D181` and `D184` deleted, `D179`, `D183`, `D131`, `D93`, `D111` and `D9` edited, and new rows for the operator's steps after merge and for what this plan left open; `./tools/verify` passes


## Surprises & Discoveries

As authored on 2026-11-21, no milestone has been executed, so nothing below this paragraph comes from a milestone session. What the author found while reading the city's files is recorded here because each finding changed the design.

- Observation (authoring, 2026-11-21): the city serves a Minutes file as a download, not a page.
  Evidence: `curl -s -D - -o /dev/null 'https://mobileal.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=3854,plainText=false)'` printed `HTTP/2 200`, `content-type: application/pdf`, `content-disposition: attachment; filename=3854.pdf; filename*=UTF-8''3854.pdf`. A browser that obeys the header saves the file and ignores `#page=N`.

- Observation (authoring): 29 of the 135 imported meetings have no minutes among the city's files, two files are not minutes, and 26 meeting dates are named by two files each.
  Evidence: the author's read of all 254 Minutes files (the requests and counts are in Context and Orientation, "What the city's files hold").

- Observation (authoring): the roll calls settle both open questions of debt row `D181`. "Scott" and "Jones" are one member, and the last roll call that lists him is that of 2023-04-04.
  Evidence: Context and Orientation, "The roster".

- Observation (authoring): what the minutes declare is about the thing voted on, not about the motion. "declared the waiver denied" follows a 7 to 0 vote on a motion to deny; "declared the ordinance failed" follows 4 ayes and 2 nays.
  Evidence: Context and Orientation, "What the minutes declare"; it is why the result rule reads the motion as well.

The entries below are from the M1 session of 2026-11-22 (UTC).

- Observation (M1, starting state): `./tools/verify`, run before any edit, passed.
  Evidence: it printed `verify: unit+web+services ... ok (173s)`, `verify: integration ... ok (119s)`, `verify: judge-fixtures ... ok (1s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (11s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 305s.` and exited 0 at 02:32Z.

- Observation (M1, the before state): with the thirteen fixture files and `tests/unit/test_mobile_minutes.py` in place and `src/` untouched, every one of the file's 29 tests fails on the import of the module, and the file collects.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_mobile_minutes.py -q -p no:cacheprovider` printed 29 lines `FAILED tests/unit/test_mobile_minutes.py::<test> - ModuleNotFoundError: No module named 'docket.analysis.mobile_minutes'` (the short summary cuts the message to `ModuleNotF...`) and `29 failed, 1 warning in 0.16s`. The tests import the module inside each test function, as `skills/plan-execute/SKILL.md` asks, so the failure is 29 failed tests and not one collection error; M1's acceptance words it as "fails on import of `docket.analysis.mobile_minutes`", which is what each of the 29 does. The commit that holds this state is the one whose subject begins `M1: the saved Mobile minutes text and the reader's tests, failing`.

- Observation (M1): the fixture files were not typed by hand. A scratch script cut them out of this file's section "The saved minutes text" (each block of lines indented four spaces under a backquoted file name, the indent removed), so each file is this plan's text byte for byte.
  Evidence: the script printed the line count of each file it wrote: `mobile_2026-11-03.txt 152`, `mobile_2021-11-23.txt 33`, `mobile_2024-06-18.txt 22`, `mobile_2022-02-22.txt 12`, `mobile_2022-03-15.txt 20`, `mobile_2022-07-12.txt 8`, `mobile_2024-07-16.txt 9`, `mobile_2025-11-18.txt 14`, `mobile_2026-11-10.txt 9`, `not_minutes_agenda.txt 9`, `not_minutes_letter.txt 5`, `invented_chain.txt 28`, `invented_closing.txt 31`.

- Correction (M1) to the before-state entry above, which says all 29 failures print `ModuleNotFoundError`: 28 do and one prints another import error. The entry stands as written; this is what was observed when the run was repeated with the module set aside (moved to the session scratchpad and moved back, `git stash` not used).
  Evidence: `... pytest tests/unit/test_mobile_minutes.py -q -p no:cacheprovider 2>&1 | grep "^E  .*Error" | sort | uniq -c` printed `28 E       ModuleNotFoundError: No module named 'docket.analysis.mobile_minutes'` and `1 E       ImportError: cannot import name 'mobile_minutes' from 'docket.analysis' (.../src/docket/analysis/__init__.py)`; the one is `test_pages_from_pdf_keeps_an_empty_page`, which imports the module by `from docket.analysis import mobile_minutes` so that it can patch `pdfplumber.open` on it. The summary line was `29 failed, 1 warning in 0.16s` both times.

- Observation (M1, the after state): with `src/docket/analysis/mobile_minutes.py` written, the same command passes, and the purity check prints nothing.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_mobile_minutes.py -q -p no:cacheprovider` printed `29 passed, 1 warning in 0.10s` (the warning is `PytestRemovedIn10Warning` from `anyio`'s plugin, there before this plan). `git grep -n "db_cursor\|db()\|import requests" -- src/docket/analysis/mobile_minutes.py`, run with the file staged (`git grep` does not read an untracked file, and its first run here, before `git add`, proved nothing), printed nothing and exited 1; `git grep -c "" -- src/docket/analysis/mobile_minutes.py` printed `src/docket/analysis/mobile_minutes.py:439`, so the file was read.

- Observation (M1): the rules as this plan words them gave every reading of "Expected readings" on the first run of the first draft; no rule and no expected line disagreed, so nothing was bent.
  Evidence: a scratch script printed each vote of each fixture from the draft before any test ran against it, and the 13 per-fixture tests, written from "Expected readings" and not from that print, passed on their first run (`29 passed`).

- Observation (M1, the removal check `skills/plan-execute/SKILL.md` asks for): 96 single alterations of the module were tried, each on a copy of the source held in memory (a pytest plugin in the session scratchpad compiles the altered text and installs it as `docket.analysis.mobile_minutes`; the committed file was not edited). Against the tests as committed failing, 76 failed a test and 20 failed none. Assertions were then added, each inside a test this plan names, and all 96 fail a test.
  Evidence: first run `tried 96 failed-a-test 76 survived 20`; after the additions `tried 96 failed-a-test 96 survived 0`. The 20 that failed nothing, and the test that now holds each: a line is read without the spaces around it (`test_running_line_and_page_number_are_not_content`); a heading whose date is no date agrees with no other heading (`test_a_letter_and_an_agenda_have_no_header_date`); `Absent:` on the fifth line after the roll call's first is still read (`test_absent_members_come_from_the_attendance_block_in_force`, by one line added to its third roll call); `Aye:` opens a vote, a second `Abstain:` line is not part of the block, and the first other line ends the block (`test_abstain_before_nays_is_read`); a declaration is never read past the next `Ayes:` line (`test_a_vote_with_no_declaration_is_unknown_and_flagged`); six clauses of Rule 7, the motion (eight lines back and not nine, not into the vote before, `called for the vote`, the fall-back to `motion`, the nearest line, and a lowercase line directly after the vote before; all in `test_a_procedural_motion_takes_no_code_and_the_item_keeps_it`, the one named test that is about motions); `called up` keeps an item that `was held over`, `and held over` without `was` does not close one, and the opening sentence ends at its period (`test_an_item_held_over_without_a_vote_gives_no_code_to_the_next_vote`); the opening sentence is not looked for before the vote that precedes the code line (`test_a_pending_item_carries_across_an_amendment_and_ends_at_a_heading`); the caption takes at most ten lines above, stops at a code line, and is None when empty (`test_code_without_a_colon_and_with_a_space_is_normalised`). Every assertion added uses text written in the test, in the invented style of `invented_chain.txt`, not the city's words; the fixture files are as this plan gives them. All of them were added after the commit that holds the tests failing, in the commit that adds the module.

- Observation (M1): the fixtures alone leave Rule 9's "a new item has begun" clause indistinguishable from its absence in the one place the plan names for it. In `invented_closing.txt` the item before the malformed line `RESOLUTION: 1-101-2029` is `01-100-2029`, which its own opening sentence closes ("was held over until"), so nothing is pending for the clause to clear and `test_a_malformed_code_line_is_not_read_and_the_item_before_it_does_not_leak` would pass without it.
  Evidence: the test as committed failing already carried a second case written in the test (an item introduced and coded, then an item with a malformed code line, then a vote), in both the one-line and the two-line spelling of `The following`; the two alterations `9 a new item clears` and `9 new item across two lines` failed that test in the first run of 96. The fixture file is unchanged.

- Observation (M1): `ruff` is installed in the venv and is not one of verify's checks. On the two new files it prints seven style findings and no error of substance; two (`ISC004`, two strings side by side inside a tuple of test cases) were fixed by parentheses, and five are left (`FURB188` in the module; `C408`, `FLY002` twice and `SIM905` in the test).
  Evidence: `venv/bin/ruff check src/docket/analysis/mobile_minutes.py tests/unit/test_mobile_minutes.py --output-format concise` printed `Found 7 errors.` before and no `ISC004` line after.

- Observation (M1, the finished state): `./tools/verify`, run on a clean tree at commit `58f5f1f` (the module and its tests committed, nothing edited while it ran), passed.
  Evidence: it printed `verify: unit+web+services ... ok (176s)`, `verify: integration ... ok (120s)`, `verify: judge-fixtures ... ok (0s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (11s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 307s.` and exited 0 at 02:43Z on 2026-11-22. That is 2 seconds over this session's starting run (305s) and 127 seconds over the 180-second budget `AGENTS.md` states, which it was already over before this plan (`D93`; M6 records the times).

- Observation (M1): the check that the fall-back test of the "new item" clause was in the failing-first commit was made, not assumed.
  Evidence: the test file as committed at `76e494a`, copied beside the others under a scratch name and removed after, run against the module with each of the two alterations of that clause: both printed `FAILED ...::test_a_malformed_code_line_is_not_read_and_the_item_before_it_does_not_leak` and `1 failed, 28 passed`.

The entries below are from the M2 session of 2026-11-22 (UTC).

- Observation (M2, starting state): `./tools/verify`, run before any edit on a clean tree at `3dd67ca`, passed.
  Evidence: it printed `verify: unit+web+services ... ok (170s)`, `verify: integration ... ok (120s)`, `verify: judge-fixtures ... ok (1s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (11s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 302s.` and exited 0 at 02:54Z.

- Observation (M2): the new migration's number is `050`, taken after looking for a taker.
  Evidence: `git fetch origin` then `git ls-tree --name-only origin/main src/docket/migrations/` ended at `049_mobile_council_terms.py`; `gh pr list --state open` with each pull request's files filtered to paths holding `migrations`, `decisions` or `DEBT` printed one line, `192 civicclerk: store an unpublished agenda that holds items once its meeting is held (issue #190)`, with no such path after it. The file is `src/docket/migrations/050_minutes_votes.py`.

- Observation (M2, the before state): with the tests written and `src/` untouched, 21 tests of the six test files fail and the 57 that were there, with one new one, pass; every file collects.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_050_migration.py tests/integration/test_049_migration.py tests/unit/test_member_votes.py tests/unit/test_vote_matcher.py tests/unit/test_vote_dataclass.py tests/unit/test_query_list_votes.py -q -p no:cacheprovider` printed `21 failed, 57 passed, 1 warning in 3.25s`. The 21: all six of `test_050_migration.py`; all five of `test_049_migration.py` (its expectations now name the row the new migration writes, and one test is new, `test_049_scott_is_scott_jones`); in `test_member_votes.py`, `test_an_alias_resolves_within_the_members_term`, `test_an_alias_two_seated_members_share_is_unresolved` and `test_the_roster_read_carries_each_members_aliases`; in `test_vote_matcher.py`, `test_text_rules_pass_over_a_minutes_reader_vote` and `test_match_all_unmatched_does_not_list_a_meeting_whose_only_unlinked_votes_are_reader_votes`; in `test_vote_dataclass.py`, the four new tests of the `Vote` fields, `vote_label`, `vote_tone` and `page_link`; in `test_query_list_votes.py`, `test_list_votes_carries_what_a_minutes_reader_stored`. The one new test that passes before the code is `test_a_four_part_row_has_no_alias`, which is what M2 says of it ("A row of four parts behaves as today"). The commit that holds this state is the one whose subject begins `M2: the tests of the schema, the roster and the matcher's gate, failing`.

- Observation (M2, the session was cut off): the M2 session that wrote the failing tests at `f257511` stopped at a usage limit before it finished, and the operator's session committed what it left in the tree, unfinished and unverified, so the next M2 session starts on a clean tree.
  Evidence: at 2026-11-22 03:07Z `git status --short` printed five modified files (`src/docket/analysis/vote_matcher.py`, `src/docket/migrations/runner.py`, `src/docket/models/vote.py`, `src/docket/services/member_votes.py`, `src/docket/services/query.py`) and one untracked (`src/docket/migrations/050_minutes_votes.py`, 117 lines). No test and no `./tools/verify` was run on them after the cut-off. The next M2 session treats that commit as a draft: it reads each of those files against M2 in Plan of Work, runs the six test files named above, and finishes or corrects the work.

The entries below are from the second M2 session of 2026-11-22 (UTC), the one that took up the draft commit `b2678b0`.

- Observation (M2, second session, starting state): `./tools/verify`, run before any edit on a clean tree at `b2678b0` (the draft), passed.
  Evidence: it printed `verify: unit+web+services ... ok (167s)`, `verify: integration ... ok (119s)`, `verify: judge-fixtures ... ok (1s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (10s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 297s.` and exited 0 at 03:13Z. So the draft, which its own commit calls not tested, was green on every tier before this session touched anything.

- Observation (M2, the after state): with the draft's `src/` as committed at `b2678b0`, the command of the before state passes.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_050_migration.py tests/integration/test_049_migration.py tests/unit/test_member_votes.py tests/unit/test_vote_matcher.py tests/unit/test_vote_dataclass.py tests/unit/test_query_list_votes.py -q -p no:cacheprovider` printed `78 passed, 1 warning in 5.31s` (the 21 that failed at `f257511` and the 57 that passed there; the warning is the `anyio` one M1 names). After this session's added assertions the same command printed `78 passed, 1 warning in 4.67s`: the assertions went into tests that were already there, so the count did not move.

- Observation (M2, the draft read against M2 in Plan of Work): the six files of `src/` the draft changed were read line by line against the milestone, and this session changed none of them. The migration's SQL is that of Interfaces and Dependencies, statement for statement, with `ROSTER_SQL` exported and placed at the end of `SQL_UP`; the runner's list ends with `docket.migrations.050_minutes_votes`; `_ROSTER_SQL` selects `aliases`, `_roster_rows` returns five parts and `index_from_rows` takes four or five; the three SELECTs of `vote_matcher.py` named by M2 each gain `AND v.minutes_reader IS NULL` and nothing else in that module differs; `Vote` has the six fields and `vote.py` the three functions; `list_votes` passes the five columns.
  Evidence: `git show b2678b0 -- src`, read whole; `git diff b2678b0 -- src` printed nothing at the end of this session's work.

- Observation (M2, the removal check `skills/plan-execute/SKILL.md` asks for): 124 single alterations of the code were tried, each on a copy of one module's source held in memory (a pytest plugin in the session scratchpad puts a finder first on `sys.meta_path` that compiles the altered text for the one module, the migration and the runner's list among them; no committed file was edited, and each run printed that the altered copy was the one loaded). For an alteration of the migration or of the runner's list the disposable database was built again first, so no run saw what another left. Against the tests as committed failing at `f257511`, 112 failed a test and 12 failed none. Assertions were then added, each inside a test of the files M2 names, and 123 fail a test; the one left is told from its absence by nothing (next entry).
  Evidence: first run `tried 124 failed-a-test 112 survived 12 errors 0`; after the additions `tried 124 failed-a-test 123 survived 1 errors 0`. What was altered: the three gates of the matcher, one at a time; in `member_votes.py` the `aliases` in the SELECT, the fifth part of a row, the alias loop, its tolerance of None, `normalize_name` on an alias, and the alias's member and each end of its term; in `vote.py` the two clauses of `vote_label`, every clause, word, word boundary and case flag of `vote_tone` and the order of its tests, the clauses of `page_link`, and each new field's default; each of the five columns `list_votes` passes; the runner's entry; and in the migration every `ADD COLUMN` and its `IF NOT EXISTS`, the type of `source_page`, the array type, `NOT NULL` and presence of `aliases`, the table, each `NOT NULL`, default, the CHECK and each of its five values, both foreign keys' `ON DELETE`, the UNIQUE and its city part, the index, its uniqueness, its `WHERE` and its `IF NOT EXISTS`, each part of `ROSTER_SQL` (the alias, the date and its value, the Mobile scope, each of the three surname clauses and their whole-word spaces, its place in the up), and each statement of the down with its `IF EXISTS`, its date and its two scopes. The 12 that failed nothing, and the test that now holds each: the left word boundary of `tabled`, `held over`, `laid over`, `withdrawn` and more than one space inside `held over` (`test_vote_tone_reads_the_result_and_the_declaration`, three phrases added: `the item upheld over objection`, `the untabled item adopted`, `the resolution Held  Over`); `minutes_files.municipality_id` cascading on the city's delete and its `NOT NULL`, and `NOT NULL` on `file_id`, `votes_stored`, `attempts` and `read_at` (`test_050_a_file_row_takes_its_defaults_and_is_one_per_city_and_file`: the NULL loop names nine columns where it named four, and a city built by the test under the slug `m050-city` is deleted and its file row is gone); the surname clauses `name = 'Jones'` and `'% Jones %'` (`test_050_roster_sql_alone_puts_the_row_right`: the row is respelled `Jones` and then `Scott Jones Jr.`, `ROSTER_SQL` finds it each time, and a `finally` puts the name, alias and date back); the Mobile scope of the down's date (`test_050_down_removes_all_of_it_and_the_up_applies_again`: the other city's `M050 Jones` is given an end of 2024-01-01, which the down must leave). All of these were added after the commit that holds the tests failing, in this session's commit of the tests.

- Observation (M2): the down's `DROP INDEX IF EXISTS minutes_files_one_paired_per_meeting` cannot be told from its absence by any test, because the next statement drops the table and PostgreSQL drops a table's indexes with it.
  Evidence: the alteration `down drops index` failed no test in either run of the 124. The statement stays, since the plan words the down as reversing each statement of the up; nothing was added for it.

- Observation (M2): `tools/test-db` failed once, with exit status 1, when the removal check's driver called it for the first alteration that rebuilds the database, straight after 65 test runs on the same database; the driver did not keep its stderr. It did not fail again in the 250 or so builds that followed, by hand or from the driver.
  Evidence: the driver's first run ended `subprocess.CalledProcessError: Command '['tools/test-db']' returned non-zero exit status 1.`; the same call from a Python subprocess a minute later returned 0 with `Applied migration 50` and `All migrations applied.` The cause was not found and is not this milestone's.

- Observation (M2): `ruff`, which is not one of verify's checks, prints five style findings on the files this milestone touched and nothing of substance; they are left, as M1 left its five.
  Evidence: `venv/bin/ruff check src/docket/migrations/050_minutes_votes.py src/docket/models/vote.py src/docket/services/member_votes.py tests/integration/test_050_migration.py tests/unit/test_vote_dataclass.py --output-format concise` printed one `I001` and two `C408` on `test_050_migration.py`, two `C408` on `test_vote_dataclass.py` (both in lines that were there before this plan), and `Found 5 errors.`

- Correction (M2) to the entry above on `tools/test-db`, which says it did not fail again "in the 250 or so builds that followed": the figure was not counted and is too high. The two full runs of the removal check each rebuilt the database once per alteration of the migration or of the runner's list, which is more than a hundred builds together and fewer than 250; none of them failed (a failed build prints `TEST-DB FAILED` in the driver's log, and neither log holds the words).

- Observation (M2, the finished state): `./tools/verify`, run on a clean tree at commit `9568e72` (the draft's code, the tests with the added assertions; nothing edited while it ran), passed.
  Evidence: it printed `verify: unit+web+services ... ok (177s)`, `verify: integration ... ok (122s)`, `verify: judge-fixtures ... ok (1s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (11s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 311s.` and exited 0 at 03:35Z on 2026-11-22; `git status --short` printed nothing before and after. That is 14 seconds over this session's starting run (297s) and 131 over the 180-second budget of `AGENTS.md` (`D93`; M6 records the times).

The entries below are from the M3 session of 2026-11-22 (UTC).

- Observation (M3, starting state): `./tools/verify`, run before any edit on a clean tree at `929cc03`, passed.
  Evidence: it printed `verify: unit+web+services ... ok (174s)`, `verify: integration ... ok (120s)`, `verify: judge-fixtures ... ok (1s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (11s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 306s.` and exited 0 at 03:46Z; `git status --short` printed nothing after it.

- Observation (M3, the before state): with `tests/integration/test_minutes_votes.py` written and `src/` untouched, every one of its 39 tests fails on an import and the file collects.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_minutes_votes.py -q -p no:cacheprovider` printed `39 failed, 1 warning in 2.86s`; the same run piped through `grep "^E  .*Error" | sort | uniq -c` printed `23 E       ImportError: cannot import name 'RawMinutesFile' from 'docket.models.protocol'`, `1 E       ImportError: cannot import name 'minutes_votes' from 'docket.services'` and `15 E       ModuleNotFoundError: No module named 'docket.services.minutes_votes'`. The 23 are the tests that build a listed file before they call the service (the helper `_file` imports `RawMinutesFile` inside itself); the rest reach the service's import first. The commit that holds this state is the one whose subject begins `M3: the tests of the service that reads, pairs and stores, failing`.

- Observation (M3, the after state): with `src/docket/services/minutes_votes.py` written and `RawMinutesFile` added to `src/docket/models/protocol.py`, the same command passes, after one expectation of one test was corrected.
  Evidence: the first run against the service printed `1 failed, 1 passed` under `-x`: `test_every_position_is_stored_and_a_flagged_vote_is_medium_and_marked` wrote a vote of 2 ayes to 3 nays under a declaration of `the thing adopted` and expected it unflagged, where Rule 10 flags it `declaration_contradicts_count` (the service stored `medium` and `needs_review` true, which is the rule). The test's own text was wrong, not the service: its vote became 3 ayes to 2 nays with one abstaining, and the run then printed `39 passed, 1 warning in 4.96s` (the warning is the `anyio` one M1 names). That edit to the test was made after the commit that holds the tests failing, in the commit that adds the service.

- Observation (M3, the removal check `skills/plan-execute/SKILL.md` asks for): single alterations of `src/docket/services/minutes_votes.py` were tried, each on a copy of the source held in memory (a pytest plugin in the session scratchpad compiles the altered text, installs it as `docket.services.minutes_votes` and prints that it did; the committed file was not edited by it), each against the whole of `tests/integration/test_minutes_votes.py`. The first run was made after the service's commit `2f8497c` and after three tests and some assertions had already been added to the file as committed failing (listed below), so it is not a run against the failing-first commit: 138 tried, 128 failed a test, 10 failed none. After more assertions, 137 tried, 133 fail a test, and 4 fail none because nothing can tell each from its absence (next entry).
  Evidence: first run `tried 138 failed-a-test 128 survived 10 errors 0`; second run `tried 137 failed-a-test 133 survived 4 errors 0` (137 because one condition was shortened and its two alterations became one). What was altered: every clause of `reader_settings` and the key each error names; in `with_paired_links` the paired rows, the city scope, the three cases of a listed link and the order of the two rules; in `read_listed` the order, the cap, the count of waiting files, each clause of which file is waiting, the limit of three, the error text, the per-file catch, the dry run's rollback, the transaction per file, the floor, the page count, the roster, the version, the refusal, the default fetch, and a write placed before the fetches; in the store each part of the attempts rule, each column of the file row on insert and on update, the failed read's kept columns, the votes and the link of a meeting a file no longer holds, the supersede statement and its two conditions, the meeting's link, the clearing statement and its two conditions; each clause of the pairing rule; every column of a stored vote, each of the four positions, the resolving and its date, the two deletes; and every clause and value of the code join. The 10 that failed nothing in the first run, and what now holds each: a meeting's votes going with any row that names it and not only with the file that holds it (new test `test_a_superseded_file_that_no_longer_names_the_meeting_leaves_the_paired_files_votes`); `header_date` and `page_count` not rewritten on a re-read (`test_a_file_that_now_names_another_meeting_moves_its_votes_and_its_link`, which now reads the row); one statement a row for votes and for member votes (new test `test_a_files_votes_and_its_member_votes_are_two_insert_statements`, which counts the calls of `execute_values` and their page sizes: 7 and 49 rows); the join's `\y` (`test_link_votes_by_code_attaches_a_coded_vote_to_the_one_item_that_opens_with_its_code`: a reader vote coded `40-9482-2026` and an item titled `40-94821 ...`, which must not join); one of the ten was a clause that proved redundant and was taken out of the code (`status != "paired" or` beside `held != row["meeting_id"]`: a file that is not paired never names the meeting it held); four are the next entry.
  Added to the test file after the commit that holds the tests failing (`3766928`), all in this session's later commits: the corrected vote of `test_every_position_is_stored_and_a_flagged_vote_is_medium_and_marked`; the tests `test_a_file_that_now_names_another_meeting_moves_its_votes_and_its_link`, `test_a_minutes_file_with_no_vote_is_paired_and_gives_its_meeting_the_link`, `test_only_a_paired_row_holds_a_meeting`, `test_a_superseded_file_that_no_longer_names_the_meeting_leaves_the_paired_files_votes` and `test_a_files_votes_and_its_member_votes_are_two_insert_statements`; in `test_a_file_on_the_meetings_own_event_replaces_the_first_files_votes` a `video_ocr` vote on the meeting that must survive the replacement; in `test_a_file_that_failed_and_then_reads_is_stored_with_its_attempts` the file listed at a new address and event on its second read, and the row's `url`, `event_external_id` and `read_at` read back; and the `40-9482` case of the join. The file has 44 tests where it had 39.

- Observation (M3): four clauses cannot be told from their absence by any test, and stay.
  Evidence: the four alterations that failed no test in the second run. `prior["status"] == "error"` in the attempts rule: a row that is not `error` and is at the current version is never offered to a run, so the store never sees one. `held != row["meeting_id"]`: without it a file that pairs again to the meeting it holds deletes that meeting's reader votes and clears its link one statement before both are written again. `AND v.resolution_number IS NOT NULL` in the code join: `substring` of NULL is NULL and never equals a title's code. `ON CONFLICT (vote_id, agenda_item_id) DO NOTHING`: the statement only takes votes with no link at all, one item each. The last two are in the statement as Interfaces and Dependencies gives it, and are kept as given.

- Observation (M3): one case is left as the plan words it and is not what a reader would want, and it cannot happen until `READER_VERSION` is raised. A file whose row was `paired` under an older version and whose re-read fails becomes an `error` row (so its tries are counted and stop at three); the meeting keeps its votes and its stored `minutes_url`, but `with_paired_links` no longer finds a `paired` row for the meeting and gives it the listing's own link, which for an imported event is none. The next ingest would then write NULL over the stored link while the votes stay, until a later try reads the file.
  Evidence: `test_a_failed_reread_leaves_what_the_file_stored` shows the row (`error`, `attempts` 1, the meeting and date kept) and the votes kept; `test_with_paired_links_lets_the_table_decide_a_meetings_minutes_link` shows a meeting with an `error` row and no listed link getting none. No test joins the two, and no code was written for it: it belongs to whoever first raises `READER_VERSION`, and M6's debt row for what this plan left open should name it.

- Observation (M3): `ruff`, which is not one of verify's checks, prints two style findings on the files this milestone wrote and nothing of substance; they are left.
  Evidence: `venv/bin/ruff check src/docket/services/minutes_votes.py src/docket/models/protocol.py tests/integration/test_minutes_votes.py --output-format concise` printed `BLE001 Do not catch blind exception` on the per-file catch of `read_listed` (the catch M3 asks for) and `FLY002` on one line of the test.

- Observation (M3, the finished state): `./tools/verify`, run on a clean tree at commit `e80310f` (the service, `RawMinutesFile`, and the 44 tests; nothing edited while it ran), passed.
  Evidence: it printed `verify: unit+web+services ... ok (171s)`, `verify: integration ... ok (123s)`, `verify: judge-fixtures ... ok (1s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (11s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 306s.` and exited 0 at 04:15Z on 2026-11-22; `git status --short` printed nothing before and after. That is the same 306 seconds as this session's starting run and 126 over the 180-second budget of `AGENTS.md` (`D93`; M6 records the times). Just before it, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_minutes_votes.py -q -p no:cacheprovider` printed `44 passed, 1 warning in 6.59s`.

The entries below are from the M4 session of 2026-11-22 (UTC).

- Observation (M4, starting state): `./tools/verify`, run before any edit on a clean tree at `4f92515`, passed.
  Evidence: it printed `verify: unit+web+services ... ok (172s)`, `verify: integration ... ok (126s)`, `verify: judge-fixtures ... ok (0s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (11s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 310s.` and exited 0 at 04:27Z; `git status --short` printed nothing after it.

- Observation (M4, work in flight): pull request #192 is not in this checkout's `origin/main`, so nothing was merged or rebased before `civicclerk.py` and `test_civicclerk.py` were edited. This session was told to use nothing outside the repository, so it ran no `git fetch` and no `gh`: the statement is about the ref as this checkout holds it, not about GitHub at this hour.
  Evidence: `git log --oneline -1 origin/main` printed `432c21a Merge pull request #191 from thinkdarrell/docs/d170-step-6-read-back`, and `git merge-base --is-ancestor origin/main HEAD` exited 0 (the branch already holds all of it).

- Observation (M4, the before state): with the tests written and `src/` and `scripts/` untouched, 41 of the 90 tests of the two files fail and every file collects.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_ingest_minutes_stage.py tests/unit/test_civicclerk.py -q -p no:cacheprovider` printed `41 failed, 49 passed, 1 warning in 2.97s`. The 41: in `tests/unit/test_civicclerk.py`, 17 of the 19 cases of the new class `TestMinutesFiles` (3 on `'CivicClerkAdapter' object has no attribute 'listed_minutes_files'`, 14 on `... no attribute 'fetch_file'`); in the new `tests/integration/test_ingest_minutes_stage.py`, 24 of its 25 cases: 9 on `ModuleNotFoundError: No module named 'scripts.read_minutes_votes'`, 1 on `ImportError: cannot import name 'read_city' from 'docket.services.minutes_votes'`, 2 on `TypeError: IngestResult.__init__() missing 1 required positional argument: 'errors'` (`test_an_unknown_slug_returns_its_error` and `test_a_failed_listing_returns_its_error`, which is `D184` as it stands today), and 12 on an assertion (a reader city gets no `minutes_files` row and no vote from an ingest run, and a bad `minutes_reader` or `minutes_read_cap` is not reported). The 49 that pass: the 46 tests the adapter's file had, and three new ones that say something stays as it is and so pass before the code, `test_a_city_without_the_key_ingests_exactly_as_before`, `test_a_json_request_is_still_refused_an_empty_or_unparsable_body` and `test_a_next_page_link_is_still_refused_in_its_own_words`. The script and `read_city` are imported inside each test, as `skills/plan-execute/SKILL.md` asks. The commit that holds this state is the one whose subject begins `M4: the tests of the adapter's files, the ingest stage and the script, failing`.

- Observation (M4, the after state): with the adapter, the ingest stage, `read_city` and the script written, the same command passes, after the invented minutes of two tests were corrected.
  Evidence: the first run against the code printed `2 failed, 88 passed`: `test_a_reader_city_gets_its_votes_from_one_ingest_run_a_scanned_meeting_included` and `test_a_file_that_cannot_be_fetched_is_one_error_and_the_run_goes_on` expected `Minutes votes linked by code: 1` and saw `2`. The tests' own text was wrong, not the code: their file printed a coded item's vote and then a vote with no code line, and Rule 9 gives the second vote the item still pending, so both carried `40-948-2029` and both joined the item. The uncoded vote now comes first in that text (and in the script tests' text, which had the same order), and `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_ingest_minutes_stage.py tests/unit/test_civicclerk.py tests/integration/test_minutes_votes.py tests/integration/test_ingest_backlog_settings.py -q -p no:cacheprovider` printed `144 passed, 1 warning in 11.24s` (the two files of this milestone, 90 tests, with M3's 44 and the 10 of the ingest settings file, which share the code changed). That edit to the tests was made after the commit that holds them failing, in the commit that adds the code.

- Observation (M4, the script run as Concrete Steps gives it): on the disposable database, where Mobile's seeded `adapter_config` names no reader, the script refuses before it builds an adapter, so the session sent the city nothing.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python scripts/read_minutes_votes.py --city mobile --limit 2` printed `database: localhost/docket_test_5e7545f1` on stdout and `adapter_config of mobile names no minutes_reader` on stderr and exited 2; without `--limit` it printed argparse's `error: the following arguments are required: --limit` and exited 2. The lines Concrete Steps calls expected (`file 3861 on event 500 names 2026-11-10 -> paired, 48 votes`) need the city's files, which a session does not fetch; lines of that form are what `test_the_script_dry_run_prints_each_file_and_changes_nothing` asserts over a patched adapter, which is how M4's acceptance words it.

- Observation (M4, the removal check `skills/plan-execute/SKILL.md` asks for): single alterations of the four files of code were tried, each on a copy of one module's source held in memory (a pytest plugin in the session scratchpad puts a finder first on `sys.meta_path` that compiles the altered text for the one module and prints that it did; no committed file was edited by it). An alteration of `src/docket/adapters/civicclerk.py` was run against `tests/unit/test_civicclerk.py`; one of `src/docket/services/ingest.py`, of `read_city` in `src/docket/services/minutes_votes.py` or of `scripts/read_minutes_votes.py` against `tests/integration/test_ingest_minutes_stage.py`. Both runs were made after the code's commit `326a5bb`, so after the two tests' invented minutes had been corrected; neither is a run against the failing-first commit. In the end 126 were tried and all 126 fail a test.
  Evidence: first run `tried 127 failed-a-test 89 survived 3 errors 35`; second run `tried 126 failed-a-test 126 survived 0 errors 0`. The 35 errors of the first run were the harness's and measured nothing: every alteration of the script printed `NOTLOADED`, because the plugin wrote its "loaded" line to `sys.stderr`, which the script's tests capture with `capsys`; it now writes to `sys.__stderr__`. One of the 89 was a bad alteration (it named a class that does not exist, so it failed on `NameError`) and was rewritten. The 3 that failed nothing: an event listed again with no Minutes file keeping its old record (a clause that proved redundant and was taken out of the code, next entry; hence 126); `_get` accepting an empty body (the clause was there before this milestone and moved with the loop: an empty body is refused by the JSON parse as well, so only the reason logged differs, and `test_a_json_request_is_still_refused_an_empty_or_unparsable_body` now reads the two logged reasons); and the code join placed before the read, which was the harness's again (the alteration added a join and left the real one in place; rewritten as a move, it fails `test_a_reader_city_gets_its_votes_from_one_ingest_run_a_scanned_meeting_included`). What was altered: in the adapter, where a file is recorded and under which key, each of its four fields, the emptying at the start of a listing, the drop of an event before `since`, which events get the link, the copy `listed_minutes_files` returns, the address check of `fetch_file` and each of its three parts and its message, the `%PDF-` check (absent, four bytes, anywhere in the body, its message, bytes or text), which reading `_get` and `fetch_file` each use, the wait before a later request, the mark that a request was sent, the scaling of the retry wait, two and four attempts, the status check, the timeout, the params, the two parts of the final error, the two clauses of the JSON reading, and the next-link check; in ingest, each of the two seven-value returns, the settings not read, read leniently, and read after the listing, the paired links not applied, applied for every city, and for another city, stage 4b for every city and for none, the cap, a dry run, each part of a file's error line, the votes added to the result, each of the eight numbers of the log line and the line itself, the code join absent, for another city, unlogged, and before the read, the three parts of the stage's `except`, and stage 4 skipped for a reader city; in `read_city`, both refusals and their words, the settings read after the adapter is built, the floor, the listing and its `since`, each argument of `get_adapter`, the limit, `dry_run` both ways, the join both ways, and the report returned; in the script, the database line and both halves of its label, each argument's `required`, the negative limit, each argument passed on, the refusal's exit code, stream and `except`, every clause of a file's line, the counts, each of the eight totals, the last line, and the exit code. The one assertion added after the commit that holds the tests failing is the logged reasons in `test_a_json_request_is_still_refused_an_empty_or_unparsable_body`; the other edit to the tests after that commit is the order of the invented votes (the after-state entry above).

- Observation (M4): one clause written first was redundant and was removed. `_event_to_meeting` dropped the stored record of an event that has no Minutes file; `list_meetings` empties the record before it reads any event, so within a listing there is never an old record to drop.
  Evidence: the alteration that removed the clause failed no test, while `test_listed_minutes_files_are_those_of_the_last_listing` (an event listed again without its file lists none) passes with and without it; the emptying itself is pinned (its removal fails that test).

- Observation (M4): the log line of stage 4b and `IngestResult.votes_inserted` count what each file stored when it was read, not what stands at the end of the run. A file read first and paired, then superseded in the same run by the file on the meeting's own event, is counted `paired` with its votes, and so is the file that took the meeting.
  Evidence: `test_the_statuses_are_each_counted_in_the_log_line` reads four files and logs `read=4 paired=2 superseded=0 not_minutes=1 no_meeting=1 errors=0 votes=4 waiting=0` while `minutes_files` afterwards holds one `paired` and one `superseded` row and the meeting holds 2 votes. The script's totals count the same way, which is what "The reference figures" already says of a dry run ("reports that one `paired` and the listed one `superseded`, unless the listed one is read later in the same run, when it takes over"). For the operator's step 4 this means the dry run's `paired` total can be above 225 and `superseded` below 26 by the number of doubled dates whose other file is read first; query Q7, which reads the table, is the one that gives 225 and 26.

- Observation (M4): `ruff`, which is not one of verify's checks, prints nothing of substance on what this milestone wrote; the findings are left.
  Evidence: `venv/bin/ruff check` over the four files of code and the two test files printed `Found 21 errors.`: 17 in `ingest.py`, of which one is this milestone's (`BLE001` on stage 4b's `except Exception`, the catch M4 asks for) and 16 are on lines that were there before; `BLE001` on M3's per-file catch in `minutes_votes.py`; `BLE001` on the test helper that hands an exception back; `I001` on the new test file's import block; and one more on `test_civicclerk.py`.

- Correction (M4) to the entry above on `ruff`, whose last clause ("one more on `test_civicclerk.py`") was written from the tail of the output and is wrong. The entry stands as written; this is the count per file, read whole.
  Evidence: the same command piped through `cut -d: -f1 | sort | uniq -c` printed 1 for `src/docket/adapters/civicclerk.py`, 17 for `src/docket/services/ingest.py`, 1 for `src/docket/services/minutes_votes.py`, 1 for `tests/integration/test_ingest_minutes_stage.py` and 1 for `tests/unit/test_civicclerk.py`. The one on the adapter is `I001`, this milestone's: the import of five names from `docket.models.protocol` is one line longer than the formatter allows. `git show 4f92515:<file> | venv/bin/ruff check --stdin-filename <file> -` printed `All checks passed!` for the adapter and for its test file and `Found 16 errors.` for `ingest.py`, so of the 21, 16 were there before and 5 are this milestone's: the import line, stage 4b's `except Exception`, the test helper's `except Exception`, the new test file's import block, and none in `minutes_votes.py` (its one is M3's). All are style and are left.

- Observation (M4, the finished state): `./tools/verify`, run on a clean tree at commit `5002b1d` (the code, the script and the tests; nothing edited while it ran), passed.
  Evidence: it printed `verify: unit+web+services ... ok (166s)`, `verify: integration ... ok (128s)`, `verify: judge-fixtures ... ok (1s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (11s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 306s.` and exited 0 at 04:49Z on 2026-11-22; `git status --short` printed nothing before and after. That is 4 seconds under this session's starting run (310s) and 126 over the 180-second budget of `AGENTS.md` (`D93`; M6 records the times). Just before it, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_ingest_minutes_stage.py tests/unit/test_civicclerk.py -q -p no:cacheprovider` printed `90 passed, 1 warning in 4.53s`.

- Observation (M5, the starting state): `./tools/verify`, run at commit `815c14d` on a clean tree before any edit, passed.
  Evidence: it printed `verify: unit+web+services ... ok (174s)`, `verify: integration ... ok (130s)`, `verify: judge-fixtures ... ok (0s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (11s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 315s.` and exited 0. No file was written in the worktree until it had.

- Observation (M5, the before state): with `tests/web/test_mobile_minutes_votes.py` written and `src/` untouched, 20 of its 23 tests fail and the file collects; the three routes answer 200 over the seeded rows, so each failure is of what a page prints and none is of the seeding.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/web/test_mobile_minutes_votes.py -q -p no:cacheprovider` printed `20 failed, 3 passed, 1 warning in 2.74s`. The three that pass are the three that say another writer's vote renders as before: `test_a_birmingham_minutes_vote_and_a_video_vote_render_as_before`, `test_a_minutes_vote_no_reader_wrote_renders_as_before_in_a_reader_city` and `test_the_member_page_prints_any_other_vote_as_before`. Of the 20: the head prints `passed` where `the resolution adopted` is asserted; the block of a reader vote prints `No agenda item linked.` and no code, caption, motion or `#page=`; a carried motion to deny has `is-pass`; the item page's link reads `Read minutes` where `Read minutes, page 5` is asserted; the member row reads `7–0 · passed` under the meeting's title; `layout.css` has no `.vote-block-result--declared`; and `app.jinja_env.globals["vote_label"]` raises `KeyError`.

- Observation (M5, the after state): with the three queries, the two template globals, the three templates and the stylesheet rule written, the same file passes on its first run against the code, no test or expected line changed, and the files that pin how any other vote renders pass unedited.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/web/test_mobile_minutes_votes.py tests/web/test_vote_result_block.py tests/web/test_new_routes_p4.py tests/unit/test_query_list_votes.py tests/unit/test_query_get_vote_for_item.py tests/unit/test_query_member_history.py -q -p no:cacheprovider` printed `90 passed, 1 warning in 6.83s`. `git diff efe0a0f --stat -- tests` is empty at the commit that holds the code. Printed from the route over the seeded rows, the block of the code-joined vote reads, in order: the head `<span class="vote-block-result vote-block-result--declared">the resolution adopted</span>`, the `official minutes · high` chip, `Re:` and the item's link with `minutes code · 100%`, the line `40-948-2026` and the caption, the motion, `7–0`, the names, and `<a class="link t-meta" href="https://mobileal.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=3854,plainText=false)#page=5" target="_blank" rel="noreferrer">Minutes, page 5 ↗</a>`. Tests that pass on the first run have not yet shown they test the code; the removal check is the next entry.

- Observation (M5, the removal check `skills/plan-execute/SKILL.md` asks for): 74 single alterations of what this milestone wrote were tried, each on a copy of one source held in memory (a pytest plugin in the session scratchpad: a finder first on `sys.meta_path` compiles the altered text of `docket.services.query` or `docket.web`; `jinja2.FileSystemLoader.get_source` is wrapped to hand back the altered text of one template; `pathlib.Path.read_text` is wrapped for `layout.css`; each writes a line to a marker file when its alteration was applied, and a run with no line counts as an error; no committed file was edited by it). Each was run against `tests/web/test_mobile_minutes_votes.py`, `tests/web/test_vote_result_block.py` and `tests/web/test_new_routes_p4.py` together. Against the test file as first committed with the code (`0abc435`), 14 failed nothing; assertions and seeded rows were added, and against the file as it stands all 74 fail a test.
  Evidence: with the tests of `0abc435` (written to an untracked file for the run and deleted after) `tried 74 failed-a-test 60 survived 14 errors 0`; with the tests as committed after it `tried 74 failed-a-test 74 survived 0 errors 0`. What was altered: in `query.py`, 13 (the join that reads the meeting's link, each of the three places the page link is built and what it is built from, each new column of the two SELECTs, each new argument to `VoteEntry`); in `docket/web/__init__.py`, 3 (each global dropped, the two exchanged); in `layout.css`, 5 (the rule gone, each of its two declarations gone, the rule moved above each rule it overrides); in `meeting_detail.html`, 27; in `partials/_vote_result_block.html`, 20; in `member_detail.html`, 6 (in the templates: the tone given no declaration, each of `is-pass` and `is-fail` dropped, the class always, never, and for an empty string, the label replaced by the stored result, each gate of the no-item sentence, of the code line, of the code, of the caption and of the motion made always or never, the safety check dropped, the link dropped, the link's address, words, `target` and `rel`, the plain minutes link's new condition, and the member row's title and line). The 14 of the first run: on the meeting page, the class on a declaration that is the empty string, the code line for a vote no reader wrote, the code line for a reader vote with neither code nor caption, the code line only with a caption, the caption and the motion printed where there is none; on the item page, the tone of the banner and of a history row read without the declaration, the history row's `is-pass` and `is-fail`, and the class printed on every banner and every history row; on the member page, the line's class always and never. Added after `0abc435` to pin them: the rows `empty` (a declaration that is the empty string), a Birmingham minutes vote that carries a resolution number, `held` with a code and no caption, and the item's older vote declared `the amendment tabled`; the tests `test_a_reader_vote_with_a_code_and_no_caption_prints_the_code_alone`, `test_a_declaration_that_is_the_empty_string_is_no_declaration`, `test_the_item_page_is_coloured_by_what_was_declared`, `test_the_item_page_prints_the_stored_result_of_a_vote_with_no_declaration` and `test_the_member_pages_declared_line_has_the_class_and_no_other_line_does`; and one assertion each in the tests of the bare vote (no `vote-block-minutes-item`), the flagged vote (no `None`) and the Birmingham votes (the resolution number is not printed). One of the 74, the plain minutes link never printed, is failed by `tests/web/test_vote_result_block.py` (`test_source_link_without_a_video_link_falls_through_to_minutes`) and by nothing in the new file, which is the existing file doing what Validation says it is for.

- Observation (M5): two clauses written first told nothing apart and were taken out of the templates before the check was run; both were found by reading, not by a surviving alteration. The motion was printed for `vote.minutes_reader and vote.motion_text`, and only a minutes reader writes `motion_text`. The page link was printed for `vote.minutes_page_url and is_source_url_safe(vote.minutes_page_url)` on the meeting page and the same on the item page, and `is_url_safe` in `src/docket/web/source_security.py` answers False for anything that is not a string, which its docstring says it does ("Defensive against non-string input (None, int, list)").
  Evidence: the templates as committed read `{% if vote.motion_text %}`, `{% if is_source_url_safe(vote.minutes_page_url) %}` and `{%- elif is_source_url_safe(v.minutes_page_url) -%}`; the tests of a meeting with no minutes link, of a vote from another writer and of `tests/web/test_vote_result_block.py`, whose stand-in vote has no `minutes_page_url` attribute at all, pass on them (`95 passed` for the six files named in the after-state entry, run again on the finished code).

- Observation (M5): `get_member_vote_summary` in `src/docket/services/query.py` selects a member's last 20 votes with their `result` and was not given the two new columns. No route and no template reads it.
  Evidence: `grep -rn 'get_member_vote_summary\|recent_votes' src/docket/web/*.py src/docket/web/templates -l` printed nothing. Context and Orientation names it among the functions that count `passed` and `failed`, which it still does unchanged.

- Observation (M5): `ruff`, which is not one of verify's checks, found three things in the new test file, all the same (`re.S` where it wants `re.DOTALL`), and they were changed.
  Evidence: `venv/bin/ruff check tests/web/test_mobile_minutes_votes.py` printed `Found 3 errors.` and, after the change, `All checks passed!`. The files under `src/` were not put through it by this session.

- Observation (M5, the finished state): `./tools/verify`, run on a clean tree at commit `16af795` (the code, the templates, the stylesheet and the tests; nothing edited while it ran), passed.
  Evidence: it printed `verify: unit+web+services ... ok (177s)`, `verify: integration ... ok (124s)`, `verify: judge-fixtures ... ok (0s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (11s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 312s.` and exited 0 at 05:26Z on 2026-11-22; `git status --short` printed nothing before and after. That is 3 seconds under this session's starting run (315s) and 132 over the 180-second budget of `AGENTS.md` (`D93`; M6 records the times). Just before the commit, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/web/test_mobile_minutes_votes.py tests/web/test_vote_result_block.py tests/web/test_new_routes_p4.py tests/unit/test_query_list_votes.py tests/unit/test_query_get_vote_for_item.py tests/unit/test_query_member_history.py -q -p no:cacheprovider` printed `95 passed, 1 warning in 6.97s`, 28 of them the new file's, and `git diff 0abc435 --stat -- tests/web/test_vote_result_block.py tests/web/test_new_routes_p4.py` printed nothing: the two files Validation names as the proof that other votes render as before were not edited.

The entries below are from the M6 session of 2026-11-22 (UTC).

- Observation (M6, starting state): `./tools/verify`, run before any edit on a clean tree at `cce0fc6`, passed.
  Evidence: it printed `verify: unit+web+services ... ok (172s)`, `verify: integration ... ok (128s)`, `verify: judge-fixtures ... ok (0s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (11s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 312s.` and exited 0 at 05:38Z; `git status --short` printed nothing before it and after it. No file of the worktree was written until it had.

- Observation (M6, identifiers): the numbers this session takes are decisions `0123` to `0130` and debt rows `D187` to `D192`, read from the refs this checkout holds and from nothing else. The session was told that nothing outside the repository is available, so it ran no `git fetch` and no `gh`; whether an open pull request or a newer `main` has spent any of them was not read and is the operator's look before merging (the first lines of `D187`).
  Evidence: `git ls-tree --name-only origin/main docs/decisions/ | tail -2` ended at `0122-backlog-floor-and-per-run-agenda-cap-are-adapter-config-settings-read-by-ingest.md`; `git show origin/main:docs/DEBT.md | grep -o "^| D[0-9]* " | tail -2` printed `D184` and `D186`, and the same two are the last rows of this branch's `docs/DEBT.md` (`D185` is in neither; ids are never reused, so the next is `D187`); `git log --oneline -1 origin/main` printed `432c21a Merge pull request #191 from thinkdarrell/docs/d170-step-6-read-back`, as it did for M4.

- Observation (M6): three sentences of the specs that M6's work list does not name stated a rule M1 to M5 changed, and were edited with the paragraphs it does name. In `docs/specs/civicclerk-ingest.md`, "Requests and failures" said the request helper `_get` is the only place the adapter pauses (the loop is `_request` since M4, under `_get` and `fetch_file`). In `docs/specs/votes.md`, "When resolution runs" said every `minutes_text` row is resolved at insert by `_ingest_votes` (the reader's rows are resolved by `minutes_votes.py`), and "How a video vote is attached" said `match_all_unmatched` runs over every meeting with a vote that has no active attachment (since M2 it passes over a reader's votes).
  Evidence: `src/docket/adapters/civicclerk.py` lines 127 to 180, read in this session (`_get` and `fetch_file` both end `return self._request(...)`, whose docstring says "This is the only place the adapter pauses"); the two sentences of `votes.md` as they stood at `cce0fc6`.


## Decision Log

- Decision: votes for meetings before 2024-06-25 are shown under the code and caption the minutes print, with no `agenda_items` row; reading agenda items out of the 68 to 153 MB agenda packets stays deferred (`D179`).
  Rationale: the goal says "read from the city's minutes", the minutes name every item they vote on, and the packets are a parser of their own. The reader loses the item page, the search card and the AI summary for those items, and keeps the vote, the names and the source page.
  Date/Author: 2026-11-21, plan author (from the scope brief).

- Decision: a Minutes file is paired to a meeting by the date printed in its heading line (`MUNICIPAL BUILDING, MOBILE, ALABAMA, <date>`), not by the roll call, and only when the city has exactly one meeting row on that date. The pairing is stored in a new table, `minutes_files`, and that table, not the adapter's listing, decides a meeting's minutes link once a file has been read.
  Rationale: the scope brief said "date and roll call"; the date alone decides in every file read (252 of 254 print one date, the other two are not minutes), and where two files name one date they hold the same votes (26 of 26). A stored pairing is needed because ingest's upsert writes the listed links over the stored ones every run and the listing gives an imported event no minutes link.
  Date/Author: 2026-11-21, plan author.

- Decision: a file attached to a meeting's own event wins over a file attached to another event; otherwise the first file read for a date keeps the meeting, and a later one is recorded `superseded`.
  Rationale: a deterministic rule for the 26 doubled dates, in each of which one of the two files sits on the event of that date; and when the city replaces a meeting's minutes with a corrected file on the same event, the new file takes over.
  Date/Author: 2026-11-21, plan author.

- Decision: the reading runs as a stage of `ingest_municipality`, not as a worker task of its own, bounded by `minutes_read_cap` files a run.
  Rationale: ingest already holds the adapter that listed the events, so no second listing is sent to the city (decision `0111` made the same choice for hearings); no task in `src/docket/worker/tasks.py` is touched, so `D65` is not tripped.
  Date/Author: 2026-11-21, plan author.

- Decision: `votes.result` for a row the Mobile reader writes says whether the motion carried (`passed`, `failed`, or `unknown`), decided from the presiding officer's declaration and, for the one ambiguous word, the motion; the declaration itself is stored in a new column and is what a page prints. The values `tabled` and `held over` are never written to `result`.
  Rationale: the member page counts a yea on a `passed` vote as voting with the outcome and a yea on a `failed` one as voting against it (`query.AGAINST_OUTCOME_PREDICATE`). A 7 to 0 motion to deny a waiver, stored as `failed` because the minutes say "denied", would list seven members as dissenting on a unanimous vote. Birmingham's minutes rows already mean "the motion carried", from the count; Mobile's mean the same, from the declaration, which honours the scope brief's default that Mobile's result comes from what the minutes say and not from a count.
  Date/Author: 2026-11-21, plan author.

- Decision: a vote whose declaration was not read, or says "denied" where neither the motion nor the count settles which side prevailed, or says the motion carried with fewer ayes than nays, is stored with `needs_review` true and a `review_reason` (`declaration_not_read`, `declaration_ambiguous`, `declaration_contradicts_count`).
  Rationale: the existing rule that a flagged vote is shown with a callout and not counted fits; 14 of 8,354 votes are of these kinds (7, 5 and 2).
  Date/Author: 2026-11-21, plan author.

- Decision: a vote written by a minutes reader carries `minutes_reader` (`'mobile'`), and `_match_substantive`, `_match_consent_block` and `match_all_unmatched` in `src/docket/analysis/vote_matcher.py` pass over such votes. This is a change to which votes the matcher's rules apply to; the module's shape is left alone and `D111` is re-deferred in writing by M6.
  Rationale: the daily `vote_matching` task visits every meeting with a `minutes_text` vote that has no active attachment and applies keyword and consent-block rules written for Birmingham's minutes. Mobile's motion to suspend the rules for "consent resolutions" would be read as a consent block and attached to every consent item of its meeting. A marker on the row holds even if the city's setting is later removed.
  Date/Author: 2026-11-21, plan author.

- Decision: "Scott" resolves to Scott Jones through a new `council_members.aliases` column read by `RosterIndex`, not by adding first names to every member's variants. Jones's `term_end` moves to 2023-04-11.
  Rationale: the alias is evidence about one member in one city (Context, "The roster"); a first-name variant for everyone would change what Birmingham's stored names resolve to. The seat was vacant from April to August 2023, so the date of the first roll call that does not list him is the end of his term under decision `0004`'s half-open window.
  Date/Author: 2026-11-21, plan author.

- Decision: the vote's link is the city's file address with `#page=N` and its text names the page; no copy of the file is served from docket.pub.
  Rationale: Source or silence asks for the city's own document. A viewer or proxy that opens at the page is new surface and is left as a debt row for the operator to judge after the look.
  Date/Author: 2026-11-21, plan author.

- Decision: `D184` is paid in M4, and `D131` (the test-removal runner under `tools/`) and `D93` (verify past its budget) are re-deferred.
  Rationale: M4 adds a setting whose bad value must be an early return of `ingest_municipality`, which is `D184`'s trigger, and the fix is two lines and a test. The runner is a capability of its own, outside a goal stated as a reader's outcome; this plan adds tests and lengthens verify, which M6 records on `D93` with the times its sessions observed.
  Date/Author: 2026-11-21, plan author.

- Decision: a file whose heading dates it before the city's `backlog_floor` is recorded `no_meeting` and stores nothing.
  Rationale: one imported event carries the minutes of 2021-09-14, the council before this one; production holds 83 Mobile meetings before the floor that the operator chose on 2026-11-20 to leave as they are (`D186`).
  Date/Author: 2026-11-21, plan author.

The seven entries below were added on 2026-11-21 by a revision made before any milestone ran. The operator supplied an outside review of this plan (a file on the operator's machine, not committed); each of its points was checked against this file and the code, and the Revision note at the bottom lists the points that changed nothing.

- Decision: `read_listed` holds no transaction while a file is fetched or parsed. It first fetches and reads every candidate it took, keeping each reading (or the exception's text) in memory and dropping the PDF's bytes once read; then it stores the outcomes in the order the files were taken, one transaction per file. A dry run fetches and reads the same way with no connection open, then opens its one connection, stores every outcome on it, builds its report, and rolls back. This supersedes M3's sentence "In a dry run the whole run uses one connection that is rolled back at the end", which stays in M3 marked as superseded.
  Rationale: the operator's step 4 is about seven minutes of requests to the city. Under the first text the update of `meetings.minutes_url` on 225 rows and every insert sat uncommitted for those minutes, and any writer of those meeting rows (the worker's tasks) waited; decision `0103` records that trap as observed on 2026-11-15. The dry run still runs the real statements, which is what `0103` keeps a dry run for; they now take as long as the statements take. The cost that remains: a full dry run inserts and rolls back about 8,354 votes and 57,607 member votes, dead rows that autovacuum reclaims for reuse, so step 4 is run once and not repeated for comfort.
  Date/Author: 2026-11-21, Claude in the operator's session, from the outside review.

- Decision: the transaction that records a file as `not_minutes`, `no_meeting` or `superseded` also sets `minutes_url` to NULL on every meeting of that city whose `minutes_url` is that file's address.
  Rationale: `with_paired_links` already gives such a meeting no link, but only on the run after the file is read, so a wrong link stood for a day; and the operator's look (step 6) opens the meeting of 2024-10-22 straight after the backfill and expects "no minutes link where there was a wrong one", which the first text could not show until the next morning's ingest. A paired meeting is never touched by this: a `superseded` file's address equals a meeting's link only when that file sat on the meeting's own event, and such a file wins the pairing.
  Date/Author: 2026-11-21, Claude in the operator's session, from the outside review.

- Decision: before any file's row becomes `paired` for meeting M, the same transaction sets to `superseded` every other `paired` row that names M, every time and not only when the pairing rule found one. And a file re-read because its row's `reader_version` is below `READER_VERSION` starts again: `attempts` is 1 and `error` is NULL on that read, whatever the row held.
  Rationale: the first statement is a no-op when the pairing rule is right and keeps the partial unique index from refusing a pairing when it is not. Without the second, a file that failed three times under one version would be offered once under the next and never again after one failed request.
  Date/Author: 2026-11-21, Claude in the operator's session, from the outside review.

- Decision: `vote_tone` is neutral (the empty string) for a declaration that says `tabled`, `held over`, `laid over` or `withdrawn`, each matched as whole words ignoring case.
  Rationale: Rule 9 already reads `held over` and `laid over` as the clerks' two spellings of one thing in an item's opening sentence, and a declaration in either says the item was not decided; a withdrawn item was not decided either. The author's script counted declarations holding `failed` or `denied` and no others, so whether a declaration says `laid over` or `withdrawn` in the 254 files is not measured; the two words cost nothing where they do not occur.
  Date/Author: 2026-11-21, Claude in the operator's session, from the outside review.

- Decision: a reader vote's head carries the class `vote-block-result--declared` beside `vote-block-result`, and `src/docket/web/static/layout.css` gains `.vote-block-result--declared { text-transform: none; letter-spacing: normal; }`. The minutes page link carries `target="_blank" rel="noreferrer"`, as the existing "Read minutes" link in `src/docket/web/templates/partials/_vote_result_block.html` does. This settles what M5's first text left to its session to find.
  Rationale: `layout.css` line 510 reads `.vote-block-result { text-transform: uppercase; letter-spacing: 0.1em; font-size: 11px; color: var(--ink); }` (read on 2026-11-21), so a declaration would print as `THE RESOLUTION ADOPTED`, which is not the minutes' own words. A link that opens a new tab leaves the meeting page, with the page number in the link's text, on screen when the browser downloads the file instead of showing it.
  Date/Author: 2026-11-21, Claude in the operator's session, from the outside review.

- Decision: `tests/integration/test_049_migration.py` executes `ROSTER_SQL` inside the `finally` of `test_049_down_restores_the_seeded_roster_and_the_up_applies_again`, after that block's `runner.apply_migrations(conn)`, not as a step after the block.
  Rationale: the `finally` is where that test puts the roster back (it rolls 049 back and applies again, which leaves Scott Jones as 049 writes him); a failed assertion above it would otherwise leave the disposable database's roster without the new migration's row for every test that runs after.
  Date/Author: 2026-11-21, Claude in the operator's session, from the outside review.

- Decision: the debt row M6 writes for the seven malformed code lines says that whether any of the seven is a real code with a digit dropped (`1-101-2026` for `01-101-2026`) was not checked against an agenda.
  Rationale: the review asked; the author's scratch copies of the files are deleted and a revision sends no request to the city, so the question is recorded as open where the lines already are.
  Date/Author: 2026-11-21, Claude in the operator's session, from the outside review.

The entries below were made by the M1 session of 2026-11-22 (UTC). Each resolves a point the rules of M1 leave open; none changes a reading of "Expected readings", and the author's count over the 254 files (8,354 votes) was made by a script this session does not have, so whether any of them moves that count is for the operator's dry run (step 4) to show.

- Decision: `^Ayes?:`, `^Nays?:` and `^Absent:` are matched as printed, case and all; only the abstain line and the patterns Rule 1, Rule 2, Rule 6, Rule 9's procedural motion and Rule 10 say "ignoring case" for ignore it.
  Rationale: Rule 5 puts "(ignoring case)" after the abstain pattern alone. Reading it as covering the whole sentence would make `AYES:` open a vote, which the author's count of lines "beginning `Ayes:`" does not include.
  Date/Author: 2026-11-22, M1 session.

- Decision: in Rule 6, when four lines have been joined and the text still does not end with a period, those four lines are the text that is tested; a match is a declaration of four lines.
  Rationale: the rule says "taking at most four lines" and then "if the joined text matches". The other reading (no period within four lines, so no declaration) would drop a declaration whose last line the PDF cut differently; the test of a fifth-line `declared` holds either way.
  Date/Author: 2026-11-22, M1 session.

- Decision: `declared_text` is the text after the first `declared` in the sentence, the word matched whole and ignoring case.
  Rationale: Rule 6 says "the text after the word `declared`" and does not say which when there are two; the first keeps the whole of what was declared.
  Date/Author: 2026-11-22, M1 session.

- Decision: a heading line whose date is no date (`FEBRUARY 30`) counts as a heading that agrees with no other, so `header_date` is None for a file that has one.
  Rationale: Rule 2 gives a date only when all heading lines name the same one. Dropping the bad line and pairing on the others would pair a file on less than the rule asks; None makes it `not_minutes` in M3, which stores nothing (Source or silence).
  Date/Author: 2026-11-22, M1 session.

- Decision: in Rule 9, `The following` and `(resolution|ordinance)`, `was held over`, `called up`, the code line and the section headings are matched in the case the rule prints; a line's test against "no lowercase letter" for the caption uses `str.islower` on each character.
  Rationale: the rule says "ignoring case" only for the procedural-motion pattern; captions and headings are capitals in every fixture and sentences are not, which is the distinction the rule relies on.
  Date/Author: 2026-11-22, M1 session.

- Decision: in Rule 9 the lines walked for a vote are those after the previous vote's last line (its block, or its declaration when it has one), and Rule 3's attendance blocks are looked for in the same lines; a line inside a vote's block or declaration is neither.
  Rationale: Rule 9 says "between the previous vote's end and this vote's `Ayes:` line"; Rule 3 says "the latest one opened before it", and no attendance block is printed inside a vote.
  Date/Author: 2026-11-22, M1 session.

- Decision: the tests import `docket.analysis.mobile_minutes` inside each test function, not at the top of the file.
  Rationale: `skills/plan-execute/SKILL.md` asks for it, so the before state reads as 29 failed tests in a file that collects; M1's acceptance ("fails on import of `docket.analysis.mobile_minutes`") is met by each test failing on that import.
  Date/Author: 2026-11-22, M1 session.

- Decision: `READER_VERSION` stays 1, and the five `ruff` findings left on the new files are left.
  Rationale: nothing has been stored under the reader yet. The findings are style; `ruff` is not a check of `./tools/verify`, and changing the module for one after the removal check would mean running the 96 again for no reader's benefit.
  Date/Author: 2026-11-22, M1 session.

The entries below were made by the M2 sessions of 2026-11-22 (UTC): the first wrote the tests and the draft of the code and was cut off, the second read the draft, checked it and wrote these down. Each resolves a point M2 leaves open.

- Decision: the draft commit `b2678b0` is kept as the code of M2, unchanged; the second session added assertions to tests and nothing to `src/`.
  Rationale: read against M2 it does what the milestone says and no more, verify passed on it before any edit, the six test files pass on it, and 123 of 124 single alterations of it fail a test. Rewriting code that meets its acceptance would be work with no reader.
  Date/Author: 2026-11-22, second M2 session.

- Decision: an alias is compared as any stored name is (`normalize_name` on the alias when the index is built), and an alias that two seated members answer to resolves to nobody.
  Rationale: `RosterIndex.resolve` normalises the name it is asked for, so an alias stored `Scott` must answer to `SCOTT`; and the resolver's existing rule for a name two seated members share is to leave it unresolved, which an alias gets by being one more variant (`test_an_alias_two_seated_members_share_is_unresolved`).
  Date/Author: 2026-11-22, M2 sessions.

- Decision: `index_from_rows` reads a fifth part that is None or empty as no alias, and `_roster_rows` always returns five parts.
  Rationale: M2 says a row of four parts behaves as today; a caller that builds rows by hand with None in the fifth place (a test, a later service) should not need to know the column's default.
  Date/Author: 2026-11-22, M2 sessions.

- Decision: `vote_label` gives the stored result for a declaration that is the empty string as well as for None; in `vote_tone`, `held over` and `laid over` are matched with any run of white space between the two words, and the test for failed (the result, or `failed` or `denied` in the declaration) comes before the test for not decided.
  Rationale: an empty head would print nothing where every other vote prints a word. A declaration is joined from lines of a PDF, where two spaces can stand between words. The order is the one Interfaces and Dependencies gives ("a failed result is tested first" in Expected readings), and it makes `the tabled item denied` read as failed, the thing voted on having been denied.
  Date/Author: 2026-11-22, M2 sessions.

- Decision: `match_all_unmatched` gains the gate although its SELECT, unlike the other two, does not name `minutes_text`; a meeting whose only unlinked votes are a reader's is not visited at all.
  Rationale: M2 names the three SELECTs. Without the third the daily task would call `match_votes_for_meeting` for every Mobile meeting every day, to attach nothing: 225 meetings of wasted statements (Production is not a sandbox).
  Date/Author: 2026-11-22, M2 sessions.

- Decision: the migration's test file is `tests/integration/test_050_migration.py` and its test rows are meetings whose external id begins `m050-`, file rows whose `file_id` begins `m050-`, members whose name begins `M050 `, and one city under the slug `m050-city` that exists only inside one test.
  Rationale: the pattern of `test_048_migration.py` and `test_049_migration.py`; a prefix per migration lets a test delete its own rows and no others.
  Date/Author: 2026-11-22, M2 sessions.

The entries below were made by the M3 session of 2026-11-22 (UTC). Each resolves a point M3 leaves open; none changes a sentence of M3's acceptance.

- Decision: `RawMinutesFile` is added to `src/docket/models/protocol.py` in M3, with the four fields of Interfaces and Dependencies, although M4's work is where the plan says to add it. M4 finds it there and adds nothing to that file.
  Rationale: `read_listed`'s signature names the type and M3's tests build listed files; a service annotated with a type that does not exist, or tests built on a stand-in class, would leave M4 to discover that the two agree. It is six lines and no behaviour.
  Date/Author: 2026-11-22, M3 session.

- Decision: `reader_settings` is written and tested in M3; `read_city` is left to M4. `read_listed` raises `ValueError` for a city whose `adapter_config` names no reader, before it asks the adapter for anything. With no reader named, `minutes_read_cap` is not looked at: the answer is `(None, 0)` whatever the cap holds.
  Rationale: `read_listed` takes no reader argument, so it must learn the reader from the city's row, and `reader_settings` is the one rule for that key; M4 calls the same function from ingest. `read_city` builds an adapter and lists meetings, which is the adapter work M4 does and tests. The docstring in Interfaces and Dependencies says "absent or null: (None, 0)" and gives the cap's rule after it.
  Date/Author: 2026-11-22, M3 session.

- Decision: a reader is looked up by name in `_READERS` in `src/docket/services/minutes_votes.py` (`{"mobile": docket.analysis.mobile_minutes}`), a module that gives `READER_VERSION`, `read_minutes` and `pages_from_pdf`; the version is read from the module on every run. The city's floor is read with `docket.services.ingest._backlog_settings`, imported inside `read_listed`.
  Rationale: a second city's reader is one entry, and the name stored in `votes.minutes_reader` is the key. One rule reads `backlog_floor`, and M4 makes `ingest.py` import this module, so an import at the top of this module would be a cycle.
  Date/Author: 2026-11-22, M3 session.

- Decision: a `superseded` row keeps the id of the meeting it lost, in `minutes_files.meeting_id` and in `FileOutcome.meeting_id`; a `not_minutes` or `no_meeting` row has none.
  Rationale: the plan's own statement that supersedes a paired row (`UPDATE minutes_files SET status = 'superseded' WHERE meeting_id = %s ...`) leaves `meeting_id` on it, so a superseded row written directly says the same thing; the partial unique index looks only at `paired` rows. `with_paired_links` reads the meeting only from `paired` rows.
  Date/Author: 2026-11-22, M3 session.

- Decision: `attempts` on a file that failed under the current version and then reads is the row's count plus one (a file that failed once and then pairs has `attempts` 2 and `error` NULL). The stored error is the exception's text, or the name of its type when the text is empty.
  Rationale: the revision's sentence is "only a retry of an `error` row at the current version adds to `attempts`", and a retry that succeeds is a retry. An `error` row with an empty `error` would read as no error.
  Date/Author: 2026-11-22, M3 session.

- Decision: a file that held a meeting (its row was `paired`) and, read again, no longer holds it (it now names another meeting, or is `no_meeting`, `not_minutes` or `superseded`) takes with it the reader votes of the meeting it held and that meeting's `minutes_url` where it is the file's stored address. A read that fails is different: it says nothing about the file, so an `error` written over a row that had a pairing keeps the row's `header_date`, `meeting_id`, `page_count` and `votes_stored`, and no vote and no link is touched.
  Rationale: Source or silence: a vote stays only while the file it was read from is its meeting's minutes. The plan does not say this, because the only way to it is a re-read under a raised `READER_VERSION`. A failed request is no evidence against the pairing, and deleting a meeting's votes because the city's server was down for a minute would be a loss with no source behind it.
  Date/Author: 2026-11-22, M3 session.

- Decision: `with_paired_links` finds "the file the listing's link names" by the address: the link is kept when no `minutes_files` row of the city has that `url`, or the row with it is `error`.
  Rationale: a `RawMeeting` carries the address and no file id; the adapter builds both from the same file id (`_file_url`), so the address identifies the file.
  Date/Author: 2026-11-22, M3 session.

- Decision: an exception while a file is stored (the second pass) is not caught per file. In a real run it leaves the earlier files committed and that file rolled back, and is raised to the caller; in a dry run everything is rolled back.
  Rationale: M3 says an exception from `fetch_pages` is caught per file. A statement that fails is a fault of the database or of this code, not of one file, and M4's stage 4b already wraps the call in a `try` that reports it.
  Date/Author: 2026-11-22, M3 session.

- Decision: the pairing counts every meeting row of the city on the date, hidden rows included.
  Rationale: M3 says "read the city's meetings on that date; zero or more than one: `no_meeting`". A hidden duplicate of a meeting therefore keeps its date from pairing; whether Mobile has any is not known to a session, and the operator's query Q3 lists every date with two rows before the backfill.
  Date/Author: 2026-11-22, M3 session.

- Decision: the stored votes are matched to the reading's votes by the `external_id` that `RETURNING id, external_id` gives back, and each of the two inserts is sent with `page_size` equal to its row count.
  Rationale: PostgreSQL does not promise the order of `RETURNING` rows; `execute_values` cuts its rows into statements of 100 by default, and the plan asks for one statement for a file's votes and one for its member votes.
  Date/Author: 2026-11-22, M3 session.

The entries below were made by the M4 session of 2026-11-22 (UTC). Each resolves a point M4 leaves open; none changes a sentence of M4's acceptance.

- Decision: `list_meetings` empties the adapter's record of Minutes files before it reads an event, and an event its own `since` test drops takes its file with it, so `listed_minutes_files()` gives the files of exactly the meetings the last listing returned. `event_date` is the date the event's meeting was given. An event read outside a listing (`_look_up_agenda_id`, one request for a meeting the instance did not list) adds its file to the record; neither ingest nor `read_city` reaches that path before it asks for the files.
  Rationale: the interface says "every event the last list_meetings listed". Without the emptying an adapter listed twice would keep the file of an event the second listing did not have, and a file on an event below the floor would be offered for a meeting ingest never stored. The file's `event_external_id` has to equal the `external_id` of the meeting made from the event (M3's "own event" rule), and both are `str(event_id)`.
  Date/Author: 2026-11-22, M4 session.

- Decision: the rule "an address of this adapter" is one private function, `_is_own_address`, read by `_check_next_link` and by `fetch_file`; `fetch_file` raises its own `ValueError` (`CivicClerk file address is not under <base>: <address>`) and the next-link message is unchanged. The shared loop is `_request(url, params, read)`; `_json_body` and `_pdf_body` are the two readings. A body that does not begin `%PDF-` is a failure of the try like any other, so the file is asked for three times before the error is raised.
  Rationale: M4 says "a URL that `_check_next_link`'s rule would refuse" and one loop with "a function turning a response into a value"; a refusal that says "next-page link" about a file would mislead. `_get` already tries three times on a body that is not JSON, and a city's server that answers a file request with an error page once is the case a retry is for; the interface's sentence ("after three failures or when the body does not begin b'%PDF-'") is met either way.
  Date/Author: 2026-11-22, M4 session.

- Decision: in stage 4b the code join runs after the read inside the same `try`. A file that could not be read is one line of the run's errors (`Minutes file <file id>: <error>`) and does not stop the join; an exception from the read itself (a database error, the adapter's listing of files) is the one error `Minutes files: <error>`, and the join waits for the next run. `with_paired_links`, before the upsert, is not wrapped: a database failure there raises as one in `_upsert_meetings` beside it does.
  Rationale: M4 words the stage as one `try` holding the read, the file errors, the log line and the join. Storing meetings with links the pairing table was not asked about would write the listing's link over a pairing, which is the thing the call exists to prevent, so there is no safe way to go on without it.
  Date/Author: 2026-11-22, M4 session.

- Decision: with `minutes_read_cap` 0 the stage still runs: the links are decided by the table, the adapter is asked for its listed files (no request; they are in memory), nothing is fetched, the log line says `read=0` with the number waiting, and the code join runs.
  Rationale: Idempotence and Recovery says "set `minutes_read_cap` to 0; the listing and the link rule go on", and the operator's step 3 sets 0 so the daily ingest reads nothing while the backfill is run by hand; the join costs one statement and is what attaches a vote to an item ingest stored that morning.
  Date/Author: 2026-11-22, M4 session.

- Decision: `read_city` reads the city's row, refuses an unknown slug, a city with no reader and a setting that cannot be read (all `ValueError`), and only then builds the adapter with `docket.adapters.get_adapter`, imported at the top of `minutes_votes.py`, and lists from the floor. The number of links the join made is logged at INFO and is not in the script's output.
  Rationale: a refusal should cost the city no request, and the script's tests put their adapter in by replacing `docket.services.minutes_votes.get_adapter`. `ReadReport` has the two fields Interfaces and Dependencies gives and no place for a link count; the expected output there has no line for it; the operator's Q6 reads it from the table.
  Date/Author: 2026-11-22, M4 session.

- Decision: the script's line for a file is `file <id> on event <event>`, then ` names <date>` when the file's heading printed one date, then ` -> paired, <n> votes`, ` -> error: <reason>`, or ` -> ` and the status. `--limit` is a whole number of 0 or more, refused by argparse otherwise, before the database line is printed. Every `ValueError` from `read_city` is printed on stderr with exit 2; an exception from the city's listing is not caught.
  Rationale: Interfaces and Dependencies shows the paired line alone and says "the words after the arrow are a `FileOutcome`'s status; a paired file names its meeting's date and vote count". A file that is not minutes has no date to name. A listing that fails after three tries is a fault to see whole, as `scripts/reset_agenda_items.py` leaves any exception that is not its refusal.
  Date/Author: 2026-11-22, M4 session.

- Decision: the tests of the ingest stage, of `read_city` and of the script are one file, `tests/integration/test_ingest_minutes_stage.py`; their rows are meetings and files whose ids begin `ims-test-`, on dates in March 2029, and the reader's `pages_from_pdf` is replaced for the file by one that cuts the fake adapter's bytes back into the pages the test wrote.
  Rationale: the three share the fake adapter and the seeding. Dates no other test uses keep the pairing rule (one meeting of the city on the date) from meeting another file's rows. No PDF is built: `pages_from_pdf` has its own test from M1, and what M4 adds is the path from `fetch_file`'s bytes to the reader, which the stand-in still walks.
  Date/Author: 2026-11-22, M4 session.

- Decision: a vote a minutes reader wrote never prints "No agenda item linked.", whether or not it has a caption. Where it has a code or a caption the block prints one line with them (the code from `votes.resolution_number`, then the caption), and prints it as well as the "Re:" line of the agenda item when the vote is joined to one. The line is printed only for a reader's vote.
  Rationale: M5's acceptance names the case with no item and no caption; the same sentence on a vote that prints its caption would say on every vote of the 106 meetings before 2024-06-25 that something is missing which the city's system does not hold. The acceptance asks for "a line with the code `40-948-2026` and the caption" and the operator's look for "a line to its agenda item" on the same vote, so both stand. Birmingham's minutes votes carry a `resolution_number` too, and they are to render as before, so the reader gate on this line is not redundant (an alteration that drops it fails `test_a_birmingham_minutes_vote_and_a_video_vote_render_as_before`).
  Date/Author: 2026-11-22, M5 session.

- Decision: "a vote whose `declared_text` is not null" is read as "a vote that has a declaration": the class `vote-block-result--declared` is printed where `declared_text` is neither null nor the empty string.
  Rationale: `vote_label`, by M2's decision, prints the stored result for the empty string as for None, and a stored result is printed in capitals like every other. The reader stores None, never the empty string, so no stored row is affected; the case is pinned on the meeting page by `test_a_declaration_that_is_the_empty_string_is_no_declaration` and not on the item or member page.
  Date/Author: 2026-11-22, M5 session.

- Decision: the address is checked in the template, with the `is_source_url_safe` global, on the page address itself, on the meeting page and on the item page. On the item page a reader vote whose address fails the check prints "Vote in meeting context" and no minutes link at all: the plain "Read minutes" link is now printed only for a vote with no page address. The plain link of every other vote is printed unchecked, as before.
  Rationale: the acceptance names the global. Without the second condition a reader vote refused its page link would fall through to the plain link to the same address, which is the link the check had just refused. Checking the existing plain link would change how other votes render, which this milestone must not; it is named in Outcomes for M6.
  Date/Author: 2026-11-22, M5 session.

- Decision: on the item page the history rows are treated as the banner is: `vote_label`, `vote_tone`, the class beside `vote-history-result`, and the page link from the same macro. The stylesheet rule is written after `.vote-history-result`, so it is later than both rules it overrides.
  Rationale: M5 says "in the three templates the printed result becomes `vote_label(result, declared_text)`" and the partial prints the result in two places; `.vote-history-result` (line 548) upper-cases as `.vote-block-result` does, the three selectors have one class each, and the later rule wins. The test reads the file and asserts the order.
  Date/Author: 2026-11-22, M5 session.

- Decision: on the member page the class goes on the line that prints the count and the label (`<div class="t-meta vote-block-result--declared">7–0 · the resolution adopted</div>`); the caption stands in the meeting's title's place only where the vote has no agenda link, cut at 120 characters as the title is; a vote joined to an item is titled by the item.
  Rationale: the revision of 2026-11-21 says the element that prints `vote_label` carries the class wherever the vote has a declaration and leaves the session no choice; on that line nothing upper-cases the text (`.t-meta` sets colour and size), so the class changes nothing there today and keeps the rule one rule. The acceptance words the caption's place as "where the vote has no agenda link".
  Date/Author: 2026-11-22, M5 session.

- Decision: `list_votes` reads the meeting's minutes link by joining `meetings` in its first statement (`SELECT v.*, m.minutes_url AS meeting_minutes_url`), so the page still costs three statements; `minutes_page_url` is `page_link` of that link and the vote's `source_page` for every row, with no test of who wrote it. The link is the last line of the block before the review callout, its words end with the arrow the page's other outside links end with (`Minutes, page 5 ↗`), and the motion is printed under the code and caption in the small grey text of the page.
  Rationale: only a reader writes `source_page`, so `page_link` already gives None for every other row; a fourth statement would be a query per page for one column. The acceptance fixes the link's words as `Minutes, page 5`, and the test strips the arrow before comparing, as the item page's `Read minutes ↗` already carries one.
  Date/Author: 2026-11-22, M5 session.

- Decision: the tests seed Mobile's and Birmingham's own rows of the disposable database (meetings whose external ids begin `m5-test-`, one council member named `M5TEST Member`, both removed after each test) and ask the three routes through the test client; nothing is rendered from a stand-in object.
  Rationale: the acceptance says "rendering the three routes over seeded rows", and the address check passes for Mobile's file address because `civicclerk.com` is in the static allowlist, so the test needs no allowlist of its own. A new member row for each test keeps the member page's in-process cache (keyed by member id) from serving one test's page to the next.
  Date/Author: 2026-11-22, M5 session.


## Outcomes & Retrospective

As authored on 2026-11-21, nothing has been executed and there is no outcome to report. Each milestone session appends its own entry beneath this paragraph.

- M1, 2026-11-22 (UTC). Done, with no carve-out against its acceptance. What exists now that did not: `src/docket/analysis/mobile_minutes.py` (`READER_VERSION` 1, `MinutesVote`, `MinutesReading`, `read_minutes`, `pages_from_pdf`, with the names and fields of Interfaces and Dependencies), the thirteen fixture files under `tests/fixtures/mobile_minutes/`, and `tests/unit/test_mobile_minutes.py` (29 tests: one per fixture file and the sixteen this plan names). The three observations of the acceptance, each made: the commit `76e494a` holds the fixtures and the tests with `src/` untouched and every test failing on the import of the module (28 with `ModuleNotFoundError`, one with `ImportError`, as the correction in Surprises says); with the module (`58f5f1f`) the same command printed `29 passed`, and the readings the tests assert are those of "Expected readings", which the rules gave without any rule or expected line being changed; the purity check printed nothing. `./tools/verify` passed before the first edit (305s) and on the finished tree (307s). Nothing outside the reader was touched: no migration, no service, no adapter, no template, no document; the module is called by nothing yet, so no page or stored row has changed.
  What a later session needs from this one. The test helper that turns a fixture file into pages is `load_pages(name)` in `tests/unit/test_mobile_minutes.py` (index 0 is page 1, a missing page is the empty string); M3's fake adapter "serves the fixture pages" and can import it from there. A `MinutesVote`'s `absent` holds only names from the attendance block, in the block's order; its `code` is already written `NN-NNN-YYYY`; `kind` is carried on the record and, as M5 says, not stored. The eight Decision Log entries of this session say how the points the rules leave open were read; a session that changes one of them changes what a file reads as and raises `READER_VERSION`.
  What was not done and is nobody's yet: the reader has been run on the thirteen fixture files and on text written in tests, and on no whole minutes file. The plan's figures for the 254 files (8,354 votes, 6,435 coded, 14 flagged) are the author's, from a script that is not in the repository, and this session neither reproduced nor contradicted them; the first comparison is the operator's dry run (step 4).
  Next: M2, the schema, the roster, and the matcher's gate.

- M2, 2026-11-22 (UTC). Done, with no carve-out against its acceptance, over two sessions: the first wrote the tests failing (`f257511`) and a draft of the code and was cut off by a usage limit (the draft is `b2678b0`, committed by the operator's session untested); the second ran verify on the draft, read it against the milestone, ran the tests and the removal check, added assertions (`9568e72`) and changed nothing under `src/`. What exists now that did not: migration `050_minutes_votes` (the five `votes` columns, `minutes_files` with its partial unique index, `council_members.aliases`, and Scott Jones's row with the alias `Scott` and `term_end` 2023-04-11; `ROSTER_SQL` exported), registered in the runner; `RosterIndex` answering to an alias inside the member's term; the gate `AND v.minutes_reader IS NULL` on the three SELECTs of `vote_matcher.py`; the six fields on `Vote` with `vote_label`, `vote_tone` and `page_link` in `src/docket/models/vote.py`; and `list_votes` passing the five columns. The acceptance, clause by clause, each observed: `tests/integration/test_050_migration.py` passes on a disposable database (the columns, the table and the alias column exist; Jones's row has `{Scott}` and 2023-04-11; the down removes all of it and puts 2023-08-08 back; a second up changes nothing); `tests/unit/test_member_votes.py` shows `Scott` resolving on 2021-11-02 and 2023-04-10 and to nobody on 2023-04-11; `tests/unit/test_vote_matcher.py` shows a reader vote getting no attachment from `match_votes_for_meeting` and the same vote, the marker cleared, getting one; the six files together printed `78 passed`, where the same command printed `21 failed, 57 passed` at `f257511`; `./tools/verify` passed before the second session's first edit (297s, on the draft) and on the finished tree (311s).
  What a later session needs from this one. No row has `minutes_reader` set yet and nothing writes one; M3 is the first writer, and a row it writes is invisible to the matcher's text rules and to `match_all_unmatched` from the moment it is stored. `load_roster_index(municipality_id)` already answers `Scott` for Mobile on the disposable database, so M3's test that `Scott` and `Jones` resolve to one member needs no seeding. `minutes_files` refuses a second `paired` row for a meeting (`UniqueViolation` from `minutes_files_one_paired_per_meeting`), so M3 sets the old row `superseded` first, in the same transaction, as the plan already says. `page_link(url, page)` and the `Vote` field `minutes_page_url` exist and nothing fills the field; M5 does. `vote_label` and `vote_tone` are not yet registered as Jinja globals; M5 does that. A test that rolls migration 049 back and applies it again must run `ROSTER_SQL` of `docket.migrations.050_minutes_votes` afterwards, as `test_049_migration.py` now does in its `finally`.
  What was not done and is nobody's yet: the one failure of `tools/test-db` recorded in Surprises has no cause found and no issue filed; a milestone session files nothing outside the repository, so the closing session or the operator decides whether it is worth one. Production's Scott Jones row still ends 2023-08-08 until the operator runs the migration (step 2 of the operator's steps).
  Next: M3, the service that reads, pairs and stores.

- M3, 2026-11-22 (UTC). Done, with no carve-out against its acceptance. What exists now that did not: `src/docket/services/minutes_votes.py` (`FileOutcome`, `ReadReport`, `reader_settings`, `with_paired_links`, `read_listed`, `link_votes_by_code`, with the signatures of Interfaces and Dependencies), `RawMinutesFile` in `src/docket/models/protocol.py`, and `tests/integration/test_minutes_votes.py` (44 tests). Nothing calls the service yet: no route, task, script or stage of ingest, so no stored row and no page has changed. The acceptance, clause by clause, each observed in a test that passes: a file is paired to the one meeting of its city on the date its first page prints, the meeting's `minutes_url` becomes the file's address, and its votes are stored as `minutes_text` votes of reader `mobile` with page, caption, motion and declaration, the member votes resolved on the meeting date with `Scott` and `Jones` one member; a file with no heading date is `not_minutes` and stores nothing; a file before the floor, or on a date with no meeting or two, is `no_meeting`; a second file is `superseded` unless it sits on the meeting's own event, when it replaces the first file's votes; a fetch that raises is `error`, counted, and tried by later runs until three; a second run with nothing new reads and writes nothing; at most `cap` files are read, newest event first; a dry run leaves every table as it was; no transaction is open while a file is fetched, in a dry run and a real one; an unpaired file clears the link that named it; a pairing supersedes any other paired row of its meeting; a re-read under a newer version starts its attempts again; `link_votes_by_code` attaches a coded vote to the one item that opens with its code, nothing where none or two match, and nothing on a second run; the adoption sweep attaches nothing to a reader vote. The before state is commit `3766928` (39 failed, every one on an import); `./tools/verify` passed before the first edit and on the finished tree, 306 seconds each time.
  What a later session needs from this one. M4 adds nothing to `protocol.py`: `RawMinutesFile(file_id, url, event_external_id, event_date)` is there, and `event_external_id` must be the `external_id` of the meeting made from that event (for CivicClerk, `str(event_id)`), because that equality is the "own event" rule. `read_listed(municipality_id, adapter, *, cap, dry_run=False, fetch_pages=None)` asks the adapter only for `listed_minutes_files()` and, when `fetch_pages` is not given, `fetch_file(url)` returning the PDF's bytes; it raises `ValueError` for a city that names no reader, and lets a database error from the store through, so stage 4b's `try` is needed as M4 words it. A `FileOutcome` of status `error` carries the text in `.error`; `ReadReport.waiting` is the candidates the cap left. `reader_settings(adapter_config)` exists with the rule of Interfaces and Dependencies and raises `ValueError` naming the key; M4 calls it and writes `read_city`, which M3 did not. `with_paired_links` and `link_votes_by_code` open their own short connections and are safe to call for a city with no `minutes_files` row. The test helpers M4 can copy are in `tests/integration/test_minutes_votes.py`: `_text(heading, *votes)` writes a page of minutes in an invented style, `_Pages` is a `fetch_pages` that serves pages or raises, and the `mobile` fixture names the reader in Mobile's `adapter_config` and puts the row back. The Decision Log's ten entries of this session say how the open points were read.
  What was not done and is nobody's yet: the case of a failed re-read of a paired file under a raised `READER_VERSION` (Surprises), for M6's debt row; and, as after M1, the service has been run on the saved excerpts and on text written in tests, never on a whole minutes file, so the plan's figures for the 254 files are still the author's until the operator's dry run.
  Next: M4, the adapter, ingest, and the operator's script.

- M4, 2026-11-22 (UTC). Done, with no carve-out against its acceptance. What exists now that did not: on `CivicClerkAdapter`, `listed_minutes_files()` and `fetch_file(url)`, with the request loop shared as `_request` and the docstrings of `fetch_votes` and `_is_imported` corrected; in `ingest_municipality`, the reader settings read beside the backlog settings, the paired links applied before the upsert, stage 4b, and both early returns passing seven values (`D184`); `minutes_votes.read_city`; `scripts/read_minutes_votes.py`; the class `TestMinutesFiles` in `tests/unit/test_civicclerk.py` (19 cases) and `tests/integration/test_ingest_minutes_stage.py` (25 cases). Nothing in `src/docket/models/protocol.py` changed (M3 had added `RawMinutesFile`). No city's `adapter_config` names a reader in the migrations or in production, so no ingest run does anything new until the operator's step 3. The acceptance, clause by clause, each observed in a test that passes: `listed_minutes_files()` returns one record per listed event that has a Minutes file, imported (event 297, file 549) or not (event 500, file 3861), with the file id, address, event id and date; `fetch_file` waits the delay, retries twice, refuses an address outside the base, and raises when the body does not begin `%PDF-`; a city with `minutes_reader` `mobile` gets its votes from one ingest run, a meeting already marked `votes_scanned` included; the paired link survives a second run whose listing gives that meeting none; a city without the key ingests as before, with no `minutes_files` row and no call to `listed_minutes_files`; a bad `minutes_reader` or `minutes_read_cap` returns `Bad adapter_config for mobile: <reason naming the key>` before any request; an unknown slug and a failed listing each return their error (at `ca6fb67` both raise `TypeError`); the script over a patched adapter prints the lines of Interfaces and Dependencies and changes nothing, stores with `--apply`, and for a city that names no reader prints the refusal and exits 2, which is also what it did when run by hand on the disposable database. The before state is commit `ca6fb67` (41 failed, 49 passed); `./tools/verify` passed before the first edit (310s) and on the finished tree (the Surprises entry below this session's others gives its lines).
  What a later session needs from this one. M5 touches none of this. For M6's documents: the two settings are `minutes_reader` (absent: nothing of this runs) and `minutes_read_cap` (absent: 10; 0: nothing is fetched, the link rule and the join go on); the log lines are `Minutes files: read=%d paired=%d superseded=%d not_minutes=%d no_meeting=%d errors=%d votes=%d waiting=%d` and `Minutes votes linked by code: %d`, and the run's errors gain `Minutes file <file id>: <error>` per file and `Minutes files: <error>` for the stage; the counts are per file as read, so a file paired and then superseded in one run counts as paired (Surprises), and the operator's steps should point at Q7 for 225 and 26, not at the dry run's totals. The script's docstring is the text for `docs/specs/operations.md`. Stage 4 still marks a reader city's meeting `votes_scanned` once the meeting has a link, and nothing reads the mark for such a city. The docstrings M4 was to correct are corrected, so M6's list of sentences to edit no longer includes them. `D184` is paid in code and its row is still in `docs/DEBT.md` for M6 to delete, with `D180` and `D181`.
  What was not done and is nobody's yet: whether pull request #192 has merged was read only from this checkout's `origin/main` (it has not, there); the session that closes the plan, or the operator, looks again before the pull request of this branch is opened, since both change `civicclerk.py` and its tests. And as after M1 and M3, no whole minutes file has been fetched or read by a session: `fetch_file` has been run on bytes written in tests, never on the city's server.
  Next: M5, what the reader sees.

- M5, 2026-11-22 (UTC). Done, with no carve-out against its acceptance. What exists now that did not: `query.list_votes` sets `Vote.minutes_page_url` from the meeting's minutes link and the vote's page; `VoteEntry` and `get_vote_for_item` carry `declared_text`, `source_page` and `minutes_page_url`; `list_member_voting_history` selects `declared_text` and `caption`; `vote_label` and `vote_tone` are Jinja globals; `meeting_detail.html`, `partials/_vote_result_block.html` and `member_detail.html` print the label and take their colour from the tone; `layout.css` has `.vote-block-result--declared { text-transform: none; letter-spacing: normal; }`; and `tests/web/test_mobile_minutes_votes.py` (28 tests). The acceptance, clause by clause, each observed in a test that passes over seeded rows and the three routes: on the meeting page a reader vote's block prints `the resolution adopted` in a head that carries the class, a line with `40-948-2026` and the caption, the motion, the names, and one link with `href` the meeting's `minutes_url` followed by `#page=5`, text `Minutes, page 5`, `target="_blank"` and `rel="noreferrer"`; a reader vote on a meeting with no `minutes_url`, or with one on a host outside the allowlist, prints no link; a reader vote with no item and no caption does not print "No agenda item linked."; a flagged reader vote prints the review callout; a Birmingham minutes vote and a video vote print `passed` and `failed` in a head without the class, "No agenda item linked.", and no page link. On the item page the code-joined vote prints its declaration and a link `Read minutes, page 5` to the same address, and its older vote's history row prints its own declaration and page. On the member page a reader vote's row prints `7–0 · the resolution adopted`, and where the vote has no agenda link its caption in the place of the meeting's title. `layout.css`, read as a file, holds the rule after the two it overrides. The before state is commit `efe0a0f` (20 failed, 3 passed, the 3 being the tests of other writers' votes); `tests/web/test_vote_result_block.py` and `tests/web/test_new_routes_p4.py` pass unedited; `./tools/verify` passed before the first edit (315s) and on the finished tree (312s, on `16af795`).
  What a later session needs from this one. For `docs/specs/votes.md` (M6), what the pages print for a reader vote: the head and the member row print `declared_text` where there is one and the stored result otherwise (a flagged vote with no declaration prints `unknown`); the colour is `vote_tone`'s, so a carried motion to deny is red and an item tabled or held over is neither; the meeting page prints the code and caption line for a reader vote that has either, beside the item's "Re:" line when it is joined, then the motion; "No agenda item linked." is never printed for a reader vote; the page link is printed where `is_source_url_safe` passes the address, and on the item page a reader vote whose address fails it prints "Vote in meeting context". The tests that pin each are named in the Surprises entry on the removal check. The review callout prints the stored `review_reason` as it is (`declaration_not_read`), as it does for every other vote. The seven Decision Log entries of this session say how the points M5 left open were read.
  What was not done and is nobody's yet. No browser has shown any of this: the session saw the HTML the routes return, not a rendered page, so how the declaration, the code line and the motion look, at a desk and at a phone width, and what the browser does with `#page=N` on a file the city serves as a download, are the operator's look (step 6). The plain "Read minutes" link of the item page and the "View full minutes" link beside it are still printed without the address check, as they were before this plan; M5 could not change how other votes render, and whether that is a debt row is M6's to say. The class is pinned for an empty-string declaration on the meeting page only. `get_member_vote_summary` was not given the new columns; nothing renders it (Surprises). As after M1, M3 and M4, nothing has been run on a whole minutes file or on production.
  Next: M6, the close.


## Context and Orientation

### The repository, for a reader new to it

docket.pub is a Python 3.10 application: a Flask web app (`src/docket/web/`), a scheduled worker (`src/docket/worker/`), and operator scripts (`scripts/`), sharing one PostgreSQL database. Each city's vendor system is reached through an adapter under `src/docket/adapters/`; Mobile's is `CivicClerkAdapter` in `src/docket/adapters/civicclerk.py`. Adapters fetch and return dataclasses defined in `src/docket/models/protocol.py`; they never write to the database. Code under `src/docket/analysis/` turns documents into facts and, by the rule this plan keeps, opens no transaction. Everything that writes is a service under `src/docket/services/`; the daily ingest is `ingest_municipality` in `src/docket/services/ingest.py`, called once per active city by the worker's `ingest_all` task. Web routes call `src/docket/services/query.py` and render Jinja templates under `src/docket/web/templates/`.

Read `AGENTS.md` and `docs/PRINCIPLES.md` before editing. Two principles bind this work: Source or silence (a fact shown to a reader links to the city's own document, and a value the source does not supply is shown as missing) and Production is not a sandbox (bulk changes are bounded; no per-row sweep).

The check command is `./tools/verify`, run from the worktree root with the worktree's own `venv/`. On the authoring machine on 2026-11-21, at the commit this plan was cut from, it printed `verify: unit+web+services ... ok (175s)`, `verify: integration ... ok (118s)` and `verify: all 6 checks passed in 306s.` Never run bare `pytest`: `tests/conftest.py` refuses any database not named `docket_test_*`. One file is run on a disposable database like this, which the author ran on 2026-11-21 (`tests/unit/test_civicclerk.py` printed `46 passed, 1 warning`; the not-yet-written `tests/unit/test_mobile_minutes.py` collected nothing):

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_civicclerk.py -q -p no:cacheprovider
    tools/test-db --drop

### What exists today

`CivicClerkAdapter.fetch_votes` returns an empty list and `fetch_minutes_text` returns None. `_event_to_meeting` gives a meeting the city's Minutes file as `minutes_url` only when the event was created on or before its own date; an event created after its date is called imported (the city loaded 135 of them on 2024-07-25 for the meetings of 2021-11-02 to 2024-06-18), and an imported event gets no minutes link, because the file attached to one is often another meeting's (decision `0119`). `_latest_file(event, "Minutes")` picks an event's one Minutes file; `_file_url(file_id)` builds its address, `https://mobileal.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=N,plainText=false)`. `_get` is the adapter's one request helper: it waits `self.delay` (never under one second) before every request after the first, tries three times, and parses JSON, so it cannot fetch a PDF as written.

`ingest_municipality` lists meetings (stage 1), upserts them (stage 2: `_upsert_meetings` writes `agenda_url`, `minutes_url` and `video_url` from the listing over the stored values, every run), fetches agendas (stage 3), resolves meeting types (3b), refreshes hearings (3c), then stage 4: for each listed meeting with a `minutes_url` it calls `_ingest_votes`, which skips a meeting whose `processing_status.votes_scanned` is true, calls `adapter.fetch_votes`, inserts `votes` and `member_votes` rows one at a time, and marks `votes_scanned`. For a CivicClerk meeting that call returns nothing and the meeting is marked scanned (`D181` c). Two of the function's early returns pass six values to `IngestResult`, which has seven fields, and raise `TypeError` (`D184`): the one for an unknown slug and the one after `adapter.list_meetings` raises.

The `votes` table (read from the disposable database on 2026-11-21) has the columns `id, meeting_id, external_id, result, yeas, nays, abstentions, source, confidence, header_result, needs_review, review_reason, video_timestamp, raw_text, created_at, resolution_number, match_context`. `result` has no CHECK constraint; its writers produce `passed` and `failed` from Birmingham's minutes (by count) and `passed`, `failed`, `tabled` and `unknown` from video OCR. `member_votes` holds `vote_id, council_member_id, member_name, position`. `vote_agenda_items` attaches a vote to an agenda item (`association_type` one of `explicit`, `consent_named`, `consent_implicit`, `positional`; `UNIQUE (vote_id, agenda_item_id)`; both foreign keys cascade on delete). `council_members` has `id, municipality_id, district_id, name, term_start, term_end, email, photo_url, active, created_at`.

`RosterIndex.resolve` in `src/docket/services/member_votes.py` is the one owner of "which member a stored name means": a name resolves when it equals a variant of a member's name (the surname, or an initial with the surname) and the member is seated on the meeting date under `term_start <= date < term_end`. `index_from_rows` builds the index from `(id, name, term_start, term_end)` tuples; `load_roster_index(municipality_id)` reads them with `_ROSTER_SQL`.

Mobile's roster in the migrations (migration `049_mobile_council_terms`, read back from the disposable database): Cory Penn, C.J. Small, Ben Reynolds, Gina Gregory from 2021-11-02; William Carroll and Joel Daves 2021-11-02 to 2025-11-04; Scott Jones 2021-11-02 to 2023-08-08; Josh Woods from 2023-08-08; Samantha Ingram and Beau Fleming from 2025-11-04. Mobile's seeded `adapter_config` is `{"delay": 0.5, "tenant": "mobileal", "category_id": 26}` and its `metadata` holds only county and population keys; production's row is set by the operator steps of debt row `D178` (`backlog_floor` `2021-11-01`, `agenda_fetch_cap` 10), which no session has confirmed were run.

### What the city's files hold

The author read the city's public system on 2026-11-21, one request at a time with more than a second between them. `GET https://mobileal.api.civicclerk.com/v1/Events?$orderby=eventDate desc&$count=true&$filter=eventCategoryId eq 26 and eventDate ge 2021-11-01T00:00:00Z`, followed through 21 pages of `@odata.nextLink`, listed 301 events: 135 imported (2021-11-02 to 2024-06-18), 134 of them with a Minutes file, and 166 not imported (2024-06-25 to 2027-08-31), 120 of them with one. No event has two Minutes files and no file id is on two events: 254 files. Each was fetched from its file address (all answered 200 with a PDF of 0.4 to 1.2 MB, 242 MB together) and its text taken page by page with `pdfplumber` (`page.extract_text()`), the library the Birmingham parser already uses; every file has a text layer.

252 files print one date in heading lines of the form `MUNICIPAL BUILDING, MOBILE, ALABAMA, NOVEMBER 3, 2026`. Two print none and are not minutes: file 449 (on the imported event of 2023-06-13) is a one-page letter from the City Clerk, and file 869 (on event 50, 2024-10-22, not imported, so linked as that meeting's minutes today) is the agenda of October 29, 2024.

Of the 120 files on events that are not imported, 119 name their own event's date. Of the 134 on imported events, 69 name their own event's date and 64 name another's: the 133 dated files name 107 dates, 26 of them twice. In all 26 pairs both files hold the same votes (same pages, names and codes), and one of the two sits on the event of that date. 106 of the 107 dates are dates of imported events; the other is 2021-09-14 (file 433), the council before this one, with no event in the listing. 29 imported events have no file naming their date: 2022-05-31, 2022-06-21, 2022-10-25, 2023-05-16, 2023-06-06, 2023-07-24, and the 23 from 2023-11-21 to 2024-04-30. One date in the listing has two events (2026-12-22, events 506 and 537), in the future.

So when every file is read, 225 meetings have paired minutes: 106 before 2024-06-25 and 119 from it on. Those 225 files hold 8,354 votes and 57,607 member positions (the author's count with the rules below; the per-meeting list is in Artifacts and Notes). The author's estimate of what that adds to the database is 15 to 20 MB; production's volume is 1 GB (`GOALS.md` Constraints).

### How the minutes print a vote

One file holds the minutes of the pre-council conference and then of the regular meeting, each under the heading line. Pages after the first begin with a running line `MINUTES OF NOVEMBER 3, 2026` and most end with the page number alone on a line. A vote is always printed as a line beginning `Ayes:` (9,308 such lines in the 254 files), followed by `Nays:` (missing on 3), sometimes `Abstain:` or `Abstained:` (55 votes, before or after `Nays:`), and then, in all but 7, a sentence in which the presiding officer declares the outcome: most often `The vote was then announced by the City Clerk, whereupon the Presiding Officer declared the resolution adopted.`, with many small variants (`Assistant City Clerk`, `This vote was then read`, `Presiding Office`, `The Presiding Officer declared unanimous consent granted for the items.`, `... set the date for the public hearing as December 8, 2026.`, `The motion passed.`). The sentence can sit on the page after the `Ayes:` line. Before the `Ayes:` line comes the motion: `Councilmember Ingram moved to adopt the waiver, which was seconded by Councilmember Gregory and the vote was as follows:`, or `The Presiding Officer then called for the vote on the original motion as amended and the vote was as follows:`.

An item of business opens with a caption in capital letters, then a sentence beginning `The following resolution` or `The following ordinance` (the words can break across lines after `The`), then a line `RESOLUTION: 40-948-2026` or `ORDINANCE: 64-042-2022` (30 lines print it without the colon, 6 with a space after a hyphen, and 7 are malformed in other ways and are not read), then the text, then the motion and the vote. An item that is only introduced says so in its opening sentence (`The following resolution was held over until the regular meeting of November 10, 2026.`) and has no vote; an item called up from an earlier meeting says `... and held over until the regular meeting of November 3, 2026, was called up by the Presiding Officer.` and is voted. Sections are headed by lines such as `CONSENT RESOLUTIONS HELD OVER`, `RESOLUTIONS BEING INTRODUCED`, `APPEALS`, `ANNOUNCEMENTS`. With the rules of M1, 6,435 of the 8,354 votes carry a code and 41 of those have no caption read. Votes without a code are the adoption of the agenda, noise waivers under APPEALS, motions to suspend the rules, to enter executive session and to adjourn.

Attendance is printed twice: `Councilmembers:` / `Present: ...` / `Absent: ...` for the conference (in 2021, `Present:` / `Councilmembers: ...` / `Absent: ...`), and `Present on Roll Call:` / `Chairman: ...` / `Vice-Chairman: ...` / `Councilmembers: ...` / `Absent: ...` for the meeting; some roll calls print no `Absent:` line.

### What the minutes declare

Read over one file per date (226 dates, 2021-09-14 among them): the declaration says "failed" or "denied" on 47 votes and neither on the rest; 7 votes have no declaration. "failed" always follows a motion that lost, including with more ayes than nays (4 to 2 and 5 to 2 on ordinances, which need more votes than a majority of those voting). "denied" follows either a motion to deny that carried (`Councilmember Gregory moved to deny the ordinance`, 7 to 0, `declared the ordinance denied`) or a motion to adopt that lost (`moved that the resolution be adopted`, 3 ayes, 0 nays, 2 abstaining, `declared the resolution denied`). On 2025-11-18 two votes of 1 aye to 5 nays are declared `the amendment passed` and `the ordinance adopted as amended`, which reads as the clerk's two lines exchanged. The rule in M1 gives, over the 225 paired meetings, `passed` 8,313, `failed` 29, `unknown` 12, with 14 votes flagged for review (`declaration_not_read` 7, `declaration_ambiguous` 5, `declaration_contradicts_count` 2).

### The roster

Names printed in the 9,308 votes: Gregory, Penn, Reynolds, Small, Carroll, Daves, Woods, Jones, Fleming, Ingram, Scott (472 times), and, as what the page prints and nobody on the roster: Richardson, Williams and Rich (the earlier council, in the 2021-09-14 file and on two votes of the 2022-01-04 minutes), and five misprints (`William`, `Woodds`, `Carroll Small` twice, `Reynolds Daves`, `Carroll Reynolds`). A name stored as printed that matches no seated member stays unresolved and is shown by name, as `docs/specs/votes.md` already says.

"Scott" (debt row `D181` a): every roll call from 2021-11-02 to 2022-07-19 lists `Scott` in the seventh place, and the same minutes list `Jones` in some of their votes: on 2021-11-09 (file 185) the roll call reads `Councilmembers: Penn, Carroll, Reynolds, Daves, Scott and Gregory`, 19 votes list `Scott`, 4 list `Jones`, and a waiver is `seconded by Councilmember Jones`; on 2021-11-23 (file 160) the conference lists `Scott` and a motion is `seconded by Councilmember Jones` with `Ayes: Penn, Carroll, Small, Reynolds, Jones and Gregory`. Across the 1,275 votes of November 2021 to July 2022 none lists both names. They are one member, Scott Jones, and his `term_start` of 2021-11-02 stands.

Jones's last roll call (`D181` b): the roll call of 2023-04-04 (file 213) lists `Councilmembers: Penn, Carroll, Reynolds, Daves, and Jones`; that of 2023-04-11 (file 253) lists `Penn, Carroll, Reynolds, and Daves` and every roll call after it until 2023-08-08 lists six members without him. Two votes in the minutes of 2023-04-25 print `Jones` among seven ayes while that meeting's roll call lists six; under the new end date those two names stay unresolved, shown as printed.

### Who reads what this plan changes

Every statement on `votes` under `src/` and `scripts/` was listed with `git grep -nE "(FROM|JOIN|INTO|UPDATE) votes\b"`, and each reader that tells one kind of vote from another, or would act on a Mobile vote, was opened.

`_match_substantive` and `_match_consent_block` in `src/docket/analysis/vote_matcher.py` select `minutes_text` votes with no active attachment and apply text rules; `match_all_unmatched` lists every meeting with such a vote, daily. They are edited in M2 to pass over a vote with `minutes_reader` set. `match_votes_by_timestamp` reads only `video_ocr` votes and is left alone. `strict_reparse_meeting` acts only where a link is provisional; a code-joined link is not, so it is left alone.

`sweep_adoptions` in `src/docket/services/minutes_adoption.py` runs at the end of every city's ingest over agenda items of meetings that have a `passed` vote, and for a title that reads as an approval of minutes sets `minutes_adopted_at` on the meeting named and calls `match_votes_for_meeting` for it. For Mobile it will now find such meetings; what it sets feeds only the "provisional" and "adopted" chips of consent-block links, which Mobile has none of, and the matcher it calls passes over reader votes. Left alone; M3's test seeds a Mobile adoption-titled item and asserts that the sweep attaches nothing to a reader vote.

`SPLIT_VOTE_AND_CONTESTED_SQL` in `src/docket/ai/badges_process.py` gives an item the `split_vote` badge when a vote attached to it has a nay or an abstention. A Mobile item with a code-joined vote and a dissent gets the badge, which is what the badge means. Left alone.

`get_member_stats`, `get_member_vote_summary`, `list_member_voting_history` and `AGAINST_OUTCOME_PREDICATE` in `src/docket/services/query.py` count `passed` and `failed` against yea and nay through `briefing.chosen_source_cte`, which picks `minutes_text` for a meeting with any unflagged minutes vote. Mobile's rows fit as they are because `result` keeps the meaning "the motion carried"; the history query gains two columns in M5.

`list_votes` (the meeting page), `get_vote_for_item` (the item page) and the member history are the three builders of a vote for a page; their callers are `meeting_detail`, `item_detail` and `member_detail` in `src/docket/web/public.py`, and the three templates that print `result` are `meeting_detail.html` (lines 181 to 183), `partials/_vote_result_block.html` (lines 50 to 52 and 77 to 78) and `member_detail.html` (line 122). All three are edited in M5. `src/docket/services/how_it_works.py` prints a meeting's `minutes_url` and no vote; left alone.

`src/docket/services/briefing.py` writes sentences from `votes.result`, for a city whose metadata carries `"briefing": true`; migration 037 sets that for Birmingham alone. `src/docket/ai/transcripts/compare.py` reads votes of meetings that have a transcript, which Mobile has none of. Both left alone; the operator's first query below confirms the metadata.

`reset_agenda_items` in `src/docket/services/ingest.py` refuses a city whose items carry vote links. Once Mobile's votes are joined to items it refuses Mobile, which is the guard working; the reset of `D178` is run before this plan's steps. Left alone, and `tests/integration/test_reset_agenda_items.py` with it.

A meeting that gains a minutes link is read by `src/docket/services/meeting_types.py` (its schedule rung asks for "no minutes link" on a city whose metadata names `council_schedule`), `non_meetings.py` and `youtube_meetings.py` (both need `calendar_url` or a YouTube channel in the metadata). Mobile's seeded metadata has none of those keys, so a Mobile row's type does not move. Left alone.

`council_members` gains a column. `git grep -n "council_members" -- src | grep "SELECT \*\|cm\.\*"` printed nothing on 2026-11-21, so no reader maps every column.

The sentences that state a rule this work changes were listed with `git grep -n -i` for "only city with votes", "doesn't provide structured vote", "no minutes link", "imported event", "Birmingham minutes PDF parser", "a minutes row never", and the ids `D180`, `D181`, `D184`, `0119`. To edit: `GOALS.md` line 25 ("the only city with votes"); `docs/birmingham/03-votes-and-facts.md` line 7 (the same words); `docs/specs/civicclerk-ingest.md` (the minutes-link paragraph, "What is not read", and the Known limits lines citing `D180` and `D184`); `docs/specs/votes.md` ("Two sources", which says a minutes row's result is counted from the names); `docs/specs/index.md` (two rows); `ARCHITECTURE.md` line 30 (Analysis owns "the Birmingham minutes PDF parser"); the docstrings of `CivicClerkAdapter.fetch_votes` and `_is_imported` in `src/docket/adapters/civicclerk.py`; and the docstring of `test_049_names_that_must_not_resolve`. To leave alone: decision `0119` (a dated record; the new decision M6 graduates says what replaces it), the docstring of migration `049` (a migration is not edited), `skills/plan-author/SKILL.md` line 319 and the `D70` and `D186` rows (each cites `D181` or `0119` as history), `src/docket/adapters/civicplus.py` (another vendor), and `docs/birmingham/01-sources.md` line 65 ("A meeting with no minutes link has no votes", still true). So after M6 the ids `D180`, `D181` and `D184` still print in `skills/plan-author/SKILL.md`, in the `D70` row's history if it lists them, in the new decision records, and in this plan.

### Debt rows this plan accounts for

Paid: `D180` (imported events get their minutes link by pairing; M3 and M4), `D181` (a and b by the migration of M2, c by a reader that does not consult `votes_scanned`, pinned by a test in M4), `D184` (M4).

Tripped and re-deferred in writing by M6: `D179` (items before 2024-06-25 stay unread; votes there show under the minutes' captions); `D183` (in the author's sample of 11 meetings from 2024-06-25 to 2026-11-10, 258 distinct codes carry a vote and 4 of them have no item in the agenda the city's system returned on 2026-11-21: `60-983` on 2024-10-15, `40-1405` and `40-1407` on 2025-11-04, `19-1577` on 2026-01-06; such a vote shows under the minutes' caption, and the production count is the operator's query Q6); `D131`; `D93`; `D111`. Named and not tripped: `D92` (the reader opens no transaction; M1's acceptance checks it), `D65` (no worker task is touched), `D7`. `D9` is edited to say the specs now cover Mobile's votes. `D178` is still open: this plan's operator steps come after its steps and say so. `D182` (Vestavia Hills' roster) is untouched: the reader is not switched on there. `D28` and GitHub issue #162 do not apply: Mobile has one vote source.

### Work in flight

`plans/active/` was empty when this plan was authored. Pull request #192 (`fix/civicclerk-held-meeting-unpublished-agenda`) is open and changes `src/docket/adapters/civicclerk.py`, `tests/unit/test_civicclerk.py` and `docs/specs/civicclerk-ingest.md`, the first two of which M4 edits and the third M6. It spends no decision number, debt id or migration number (its file list holds none). If it merges while this plan is in flight, the session that next touches those files rebases or merges `origin/main` first and records it.

### Identifiers

A decision number, a debt id and a migration number are not spent by this plan. The session that needs one takes the lowest number above every one on `origin/main` and on any open pull request at that moment (`D70`); a milestone session can read only the refs it has, so M6 says in its debt row that the operator re-reads the open pull requests before merging. As authored, the highest migration is `049`, the highest decision `0122`, the highest debt row `D186`, and this plan writes "the new migration" for the file M2 creates (its number is `050` unless another has taken it).


## Plan of Work

The work is six milestones, one session each. A session starts and ends with `./tools/verify`, makes a failing-first commit of its tests where the milestone says so, changes the plan file in every commit, and ticks its one Progress line with the time observed.

### M1. The reader

Acceptance, stated first. Three observations. The commit that adds `tests/fixtures/mobile_minutes/` and `tests/unit/test_mobile_minutes.py` with `src/` untouched fails on import of `docket.analysis.mobile_minutes` when the file is run on a disposable database. With the module written, the same command passes, and the readings it asserts are exactly those of "Expected readings" in Artifacts and Notes. `git grep -n "db_cursor\|db()\|import requests" -- src/docket/analysis/mobile_minutes.py` prints nothing.

The work. Create the fixture files exactly as given in Artifacts and Notes ("The saved minutes text"). Create `src/docket/analysis/mobile_minutes.py` with the names in Interfaces and Dependencies and these rules. They were run by the author, as a throwaway script that is not in the repository, over the 254 files and over the fixtures; the expected readings were printed by that script.

Rule 1, kept lines. For each page, 1-based, split its text on newlines and strip each line. Drop empty lines, lines that match `^MINUTES OF <MONTH> <D>, <YYYY>$` ignoring case (the running line), and lines of one to three digits (the page number). Every kept line remembers its page.

Rule 2, the heading date. A kept line matching `^MUNICIPAL BUILDING, MOBILE, ALABAMA,?\s+(<MONTH>\s+\d{1,2},\s*\d{4})\s*$`, ignoring case, is a heading line. `header_date` is the date of the heading lines when there is at least one and all name the same date, and None otherwise.

Rule 3, attendance. Walking the kept lines in order, a line that starts with `Present on Roll Call`, or equals `Present:`, or starts with `Councilmembers:` while the next kept line starts with `Present:`, opens an attendance block: the absent list becomes the names of the first line matching `^Absent:\s*(.*)$` among that line and the five kept lines after it, or empty when there is none. The absent list in force at a vote is the latest one opened before it.

Rule 4, names. A list of names is its text with a trailing period removed, split on commas and on the word `and`, each part stripped, empty parts dropped; `None` or nothing is the empty list. Names are kept exactly as printed.

Rule 5, a vote block. A kept line matching `^Ayes?:\s*(.*)$` opens a vote; its page is the vote's page. Up to three following kept lines are consumed while each is the first `^Nays?:`, the first `^Abstain(ed|ing|s)?:` (ignoring case), or an `^Absent:` line; the first other line ends the block.

Rule 6, the declaration. Starting at the kept line after the block, join lines with single spaces until the joined text ends with a period, taking at most four lines and never a line that opens another vote. If the joined text matches `\b(declared|set the date)\b` or `^The motion (passed|carried|failed)` (ignoring case) it is the declaration and its lines are consumed; otherwise the vote has none and no line is consumed. `declared_text` is the text after the word `declared`; or, with no `declared`, the text from `set the date` on; or the whole sentence; stripped, with one final period removed unless the text ends `a.m.` or `p.m.`.

Rule 7, the motion. Look back from the `Ayes:` line over at most eight kept lines, not past the end of the previous vote's block and declaration. The motion starts at the nearest line matching `\bmoved\b|called for the vote`; failing that, the nearest matching `\b(motion|move)\b`; failing that there is none. When the starting line begins with a lowercase letter and the line before it lies after the previous vote, the motion starts one line earlier. `motion_text` is those lines through the line before `Ayes:`, joined with spaces.

Rule 8, absent members. A vote's absent list is the names of the attendance block in force that are not among its ayes, nays or abstentions.

Rule 9, the item. Keep one pending item (code, kind, caption) while walking, across votes. Over the kept lines between the previous vote's end and this vote's `Ayes:` line, in order: a section heading clears the pending item; so does a line which, joined to the kept line before it by one space, matches `The\s+following\s+(resolution|ordinance)\b` while the line before it alone does not (a new item has begun; the two words can sit on two lines); a code line, `^(RESOLUTION|ORDINANCE):?\s*(\d{2})\s*-\s*(\d{3,4})\s*-\s*(\d{4})\s*$`, sets the pending item to the code written `NN-NNN-YYYY` and the kind, unless its opening sentence closes it. The opening sentence is found in the up to twelve kept lines before the code line (not past the previous vote), joined with spaces: the last match of `The\s+following` to the next period. It closes the item when it matches `\bwas\s+(held|laid)\s+over\b` and does not contain `called up`; then the pending item is cleared. The caption is the text of the line holding the start of the opening sentence, before that start, preceded by the kept lines above it (up to ten, and only among those twelve) for as long as each has no lowercase letter and is neither a heading nor a code line; joined with spaces, a final period removed; None when empty or when no opening sentence was found. A section heading is a line that, with a trailing colon or period removed, is one of `ANNOUNCEMENTS`, `APPEALS`, `PUBLIC HEARINGS`, `ADOPTION OF THE AGENDA`, `APPROVAL OF MINUTES`, `COMMUNICATIONS FROM THE MAYOR`, `STATEMENT OF RULES BY PRESIDING OFFICER`, `NON-AGENDA ITEMS`, `AGENDA ITEMS`, `CALL FOR PUBLIC HEARINGS`, `MONTHLY FINANCE REPORT`, `PRESENTATIONS TO THE COUNCIL`, `PRESENTATIONS BY THE COUNCIL`, or matches `^(CONSENT |CIP )?(RESOLUTIONS|ORDINANCES) (HELD OVER|BEING INTRODUCED)( FOR THE FIRST TIME)?$`. The vote takes the pending item unless its motion matches `\b(adjourn\w*|executive session|adopt the agenda|suspen\w+ (of )?the rules|recess\w*)\b` ignoring case; the pending item stays for the votes after it.

Rule 10, the result. With no declaration: `unknown`, flagged `declaration_not_read`. Else if `declared_text` holds the word `failed`: `failed`. Else if it holds the word `denied`: `passed` when the motion matches `\bden(y|ied)\b`; otherwise `failed` when the ayes are no more than the nays; otherwise `unknown`, flagged `declaration_ambiguous`. Else `passed`, flagged `declaration_contradicts_count` when the ayes are fewer than the nays. A flagged vote has `needs_review` true and the code as `review_reason`.

`raw_text` is the kept lines from the motion's first line (or the `Ayes:` line when there is no motion) through the last line of the declaration (or of the block), joined with newlines. `pages_from_pdf` opens the bytes with `pdfplumber` and returns `page.extract_text() or ""` for every page in order, so a page with no text keeps its number.

Result and proof. `tests/unit/test_mobile_minutes.py` holds one test per row of "Expected readings" and the tests named in Validation and Acceptance. Record in the plan the import error of the failing-first commit, the summary line of the passing run, and the verify line.

### M2. The schema, the roster, and the matcher's gate

Acceptance, stated first. On a disposable database the new migration's test passes: the five `votes` columns, `minutes_files` and `council_members.aliases` exist; Scott Jones's row has `aliases` `{Scott}` and `term_end` 2023-04-11; the down removes all of it and puts `term_end` back to 2023-08-08; a second up changes nothing. `tests/unit/test_member_votes.py` shows `Scott` resolving to the member whose row carries that alias on a date in his term and to nobody the day it ends. `tests/unit/test_vote_matcher.py` shows a seeded `minutes_text` vote with `minutes_reader` set getting no attachment from `match_votes_for_meeting` while the same vote without it does. `./tools/verify` passes.

The work. Add the new migration under `src/docket/migrations/`, registered the way `049_mobile_council_terms.py` is, with the SQL in Interfaces and Dependencies. Its roster statements are also exported as a module constant, `ROSTER_SQL`, because `tests/integration/test_049_migration.py` runs migration 049's down and up inside a test and must leave the roster as the migrations leave it: that test's last step executes `ROSTER_SQL` (revision of 2026-11-21: inside the `finally` of `test_049_down_restores_the_seeded_roster_and_the_up_applies_again`, straight after its `runner.apply_migrations(conn)`, so a failed assertion still leaves the roster right), and its expectations change where the new migration changes the row (the `EXPECTED` tuple for Scott Jones, the roll call of 2023-08-08 cases, and `test_049_names_that_must_not_resolve`, where `("Scott", date(2021, 11, 2))` now resolves and moves to the resolving cases, `index.resolve("Jones", date(2023, 8, 7))` becomes unresolved, and `("Jones", date(2023, 4, 11))` is added as unresolved). The docstring of the new migration gives the roll calls of "The roster" above with their file ids.

In `src/docket/services/member_votes.py`: `_ROSTER_SQL` also selects `aliases`; `_roster_rows` returns five-part tuples; `index_from_rows` accepts tuples of four or five parts and, for a fifth part, adds `RosterVariant(normalize_name(alias), ...)` for each alias, under the member's own term. A row of four parts behaves as today, so the existing tests stand unedited.

In `src/docket/analysis/vote_matcher.py`: the vote SELECTs of `_match_substantive` and `_match_consent_block` and the meeting SELECT of `match_all_unmatched` each gain `AND v.minutes_reader IS NULL`. Nothing else in the module changes.

In `src/docket/models/vote.py`: `Vote` gains the fields and the two functions given in Interfaces and Dependencies. `list_votes` in `src/docket/services/query.py` passes the five new columns into `Vote` (it selects `*`), so later milestones can assert on them.

### M3. The service that reads, pairs and stores

Acceptance, stated first. `tests/integration/test_minutes_votes.py`, on seeded rows and a fake adapter that serves the fixture pages, shows each sentence of the Progress line: a file is paired to the one meeting of its city on the date its first page prints, that meeting's `minutes_url` becomes the file's address, and its votes are stored with `source` `minutes_text`, `minutes_reader` `mobile`, the page, caption, motion and declaration, and member votes resolved against the roster on the meeting date (`Scott` and `Jones` to the same member); a file with no heading date is `not_minutes` and stores nothing; a file dated before `backlog_floor`, or on a date with no meeting or two, is `no_meeting`; a second file for a paired meeting is `superseded` unless it sits on the meeting's own event, in which case it replaces the first file's votes; a fetch that raises is `error` with `attempts` counted and is tried again by the next run until three; a second run with nothing new reads nothing and writes nothing; at most `cap` files are read; a dry run leaves every table as it was; `link_votes_by_code` attaches a coded vote to the one item of its meeting whose title starts with that code, attaches nothing where no item or two items match, and does nothing on a second run. `./tools/verify` passes.

The work. Create `src/docket/services/minutes_votes.py` with the functions in Interfaces and Dependencies.

`read_listed` takes the municipality id, an adapter, the cap, and `dry_run`; it reads the city's `backlog_floor` from its `adapter_config` row itself. It asks the adapter for `listed_minutes_files()`, orders them newest event first, and keeps as candidates the files with no `minutes_files` row, those whose row has `reader_version` below `READER_VERSION`, and those whose row is `error` with `attempts` under 3; it takes the first `cap`. For each it fetches the bytes (`adapter.fetch_file(url)`), turns them into pages (`pages_from_pdf`), reads them (`read_minutes`), and stores the outcome in one transaction: the `minutes_files` row is inserted or updated (`ON CONFLICT (municipality_id, file_id)`), and for a pairing the meeting's reader votes are replaced and its `minutes_url` set. The two steps that touch the network or the PDF are injected for tests through a keyword argument, `fetch_pages`, a callable from file to pages whose default composes the two. An exception from it is caught per file and stored as `error` with its text; the run goes on. In a dry run the whole run uses one connection that is rolled back at the end, the precedent of decision `0103`. (Superseded by the revision of 2026-11-21; the next paragraph is the rule.)

Revision of 2026-11-21, the order of work. No transaction is open while a file is fetched or parsed. `read_listed` works in two passes. The first calls `fetch_pages` and `read_minutes` for each candidate it took and keeps the reading, or the exception's text, in a list; nothing is written. The second walks that list in order and stores each outcome in its own transaction, exactly as the paragraph above describes. In a dry run the first pass is the same and opens no connection; the second pass runs on one connection that is rolled back after the report is built. The acceptance gains two clauses, each with a test: while `fetch_pages` runs for the second of two files, in a dry run and in a real run alike, a separate connection (`psycopg2.connect` on `DATABASE_URL`, made by the test) takes `SELECT 1 FROM meetings WHERE id = %s FOR UPDATE NOWAIT` on the first file's meeting without an error; and a file recorded `not_minutes`, `no_meeting` or `superseded` leaves no meeting of its city holding that file's address as `minutes_url`, a meeting that held it having NULL afterwards.

Revision of 2026-11-21, three rules of the store. The transaction that records a file as `not_minutes`, `no_meeting` or `superseded` also runs `UPDATE meetings SET minutes_url = NULL WHERE municipality_id = %s AND minutes_url = %s` with the file's address. Before a row becomes `paired` for M, the same transaction runs `UPDATE minutes_files SET status = 'superseded' WHERE meeting_id = %s AND status = 'paired' AND file_id <> %s`, every time. A file read again because its `reader_version` is below `READER_VERSION` is written with `attempts` 1 and `error` NULL; only a retry of an `error` row at the current version adds to `attempts`. Each has a test: `test_a_file_that_is_not_minutes_clears_the_link_that_named_it`, `test_a_pairing_supersedes_any_other_paired_row_of_its_meeting`, `test_a_reread_under_a_newer_version_starts_its_attempts_again`.

Pairing. With no `header_date`: `not_minutes`. With a `header_date` before the city's `backlog_floor` (when its `adapter_config` has one): `no_meeting`. Otherwise read the city's meetings on that date; zero or more than one: `no_meeting`. With one meeting M: if no `minutes_files` row of status `paired` names M, pair. If one does and it is this same file (a re-read under a newer `READER_VERSION`), pair again. If one does and it is another file, this file pairs only when its `event_external_id` equals M's `external_id`; the other row becomes `superseded`. Otherwise this file is `superseded`.

Storing a pairing. Delete M's votes whose `minutes_reader` is not null (their member votes and links go by cascade). Insert the reading's votes with one multi-row statement (`psycopg2.extras.execute_values` with `RETURNING id`), in document order, `external_id` `<M's external id>-mv-<n>` from 1, `yeas`, `nays` and `abstentions` the lengths of the three lists, `confidence` `high` or, when flagged, `medium`, `resolution_number` the code. Insert their member votes with one multi-row statement: `yea`, `nay`, `abstain`, `absent`, each name resolved through one `RosterIndex` loaded once per run. Set `meetings.minutes_url` to the file's address. Write the `minutes_files` row: `paired`, `meeting_id`, `header_date`, `page_count`, `votes_stored`, `reader_version`. Two statements per file, not one per vote, is what keeps the operator's backfill within Production is not a sandbox.

`with_paired_links(municipality_id, raw_meetings)` returns the meetings with `minutes_url` decided by the table: the paired file's address when a `paired` row names the meeting; else the listing's own link when the file it names has no row or an `error` row; else None. It uses `dataclasses.replace`, since `RawMeeting` is frozen.

`link_votes_by_code(municipality_id)` is the one statement given in Interfaces and Dependencies. It never touches a vote that has any `vote_agenda_items` row, active or not, so a link an admin removed is not put back.

### M4. The adapter, ingest, and the operator's script

Acceptance, stated first. `tests/unit/test_civicclerk.py` shows `listed_minutes_files()` returning one record per listed event that has a Minutes file, imported or not, with the file id, the file address, the event's id and date, and `fetch_file` waiting the delay, retrying twice, refusing an address outside the adapter's base, and raising when the body does not begin `%PDF-`. `tests/integration/test_ingest_minutes_stage.py` shows a city whose `adapter_config` has `minutes_reader` `mobile` getting its votes from one `ingest_municipality` run with a fake adapter, a meeting already marked `votes_scanned` included; the paired `minutes_url` surviving a second run whose listing gives that meeting no minutes link; a city without the key ingesting exactly as before (no `minutes_files` row, no call to `listed_minutes_files`); a bad `minutes_reader` or `minutes_read_cap` returning `Bad adapter_config for <slug>: <reason naming the key>` before any request; and an unknown slug and a failed listing each returning their error where today they raise `TypeError`. `scripts/read_minutes_votes.py --city mobile --limit 2` against the disposable database with a patched adapter prints lines of the form given at the end of Interfaces and Dependencies and changes nothing; with `--apply` it stores; for a city whose `adapter_config` names no reader it prints the refusal and exits 2. `./tools/verify` passes.

The work. In `src/docket/models/protocol.py` add `RawMinutesFile`. In `src/docket/adapters/civicclerk.py`: `_event_to_meeting` records, for an event with a Minutes file (`_latest_file(event, "Minutes")`, whatever `_is_imported` says), a `RawMinutesFile` in `self._minutes_files`, keyed by event id; `listed_minutes_files()` returns them. `fetch_file(url)` refuses, with `ValueError`, a URL that `_check_next_link`'s rule would refuse, then requests it under the same pause and three-attempt rule as `_get`; move the shared loop into one private helper that takes a function turning a response into a value, so `_get` keeps its JSON parsing and `fetch_file` returns `resp.content` after checking the first five bytes. The docstrings of `fetch_votes` and `_is_imported` are corrected: votes are read by `docket.services.minutes_votes`, and an imported event's link comes from the pairing.

In `src/docket/services/ingest.py`: both six-value `IngestResult` returns pass seven. After `_backlog_settings`, read the reader settings with `minutes_votes.reader_settings(adapter_config)` inside the same `try`, so a bad value is the same early return. After stage 1 and before `_upsert_meetings`, for a city with a reader: `raw_meetings = minutes_votes.with_paired_links(municipality_id, raw_meetings)`. After stage 4, stage 4b for such a city, inside its own `try` that appends `Minutes files: <error>` to the run's errors: `read_listed(municipality_id, adapter, cap=cap)`, each file's error appended as `Minutes file <file id>: <error>`, one INFO line `Minutes files: read=%d paired=%d superseded=%d not_minutes=%d no_meeting=%d errors=%d votes=%d waiting=%d`, then `link_votes_by_code(municipality_id)` with `Minutes votes linked by code: %d`. `IngestResult.votes_inserted` adds the votes stored. Stage 4 itself is not changed: for a CivicClerk meeting it still marks `votes_scanned`, and nothing reads that mark for a reader city.

`minutes_votes.read_city(slug, *, limit, apply)` loads the city, refuses one with no `minutes_reader`, builds its adapter, lists its meetings from its `backlog_floor`, and calls `read_listed` with `dry_run=not apply`, then `link_votes_by_code` when applying. `scripts/read_minutes_votes.py --city <slug> --limit <n> [--apply]` follows `scripts/reset_agenda_items.py`: it prints `database: <host>/<name>` first, one line per file read, the totals, and `dry run: nothing changed` or `applied`; `--limit` is required.

### M5. What the reader sees

Acceptance, stated first. `tests/web/test_mobile_minutes_votes.py`, rendering the three routes over seeded rows, shows: on the meeting page a reader vote's block prints its `declared_text` in the head, a line with the code `40-948-2026` and the caption, the motion, the names, and one link whose `href` is the meeting's `minutes_url` followed by `#page=5` and whose text is `Minutes, page 5`; a reader vote on a meeting whose `minutes_url` is null, or whose URL fails `is_source_url_safe`, prints no link; a reader vote with no item and no caption does not print "No agenda item linked."; a flagged reader vote prints the review callout; a Birmingham minutes vote and a video vote render exactly as before (the head prints `passed`, the "No agenda item linked." sentence stands). On the item page a code-joined vote prints its declaration and a link `Read minutes, page 5` to the same address. On the member page a history row for a reader vote prints the declaration after the count and, where the vote has no agenda link, its caption in place of the meeting's title. `./tools/verify` passes.

The work. `query.list_votes` also reads the meeting's `minutes_url` and sets `Vote.minutes_page_url` with `page_link`. `VoteEntry` and `get_vote_for_item` gain `declared_text`, `source_page` and `minutes_page_url`. `list_member_voting_history` selects `v.declared_text` and `v.caption`. `docket.web.create_app` registers `vote_label` and `vote_tone` as Jinja globals. In the three templates the printed result becomes `vote_label(result, declared_text)` and the `is-pass` and `is-fail` classes come from `vote_tone(result, declared_text)`; read the stylesheet's `.vote-block-result` rule first: if it changes the case of the text, a reader vote's head gets a class that prints the declaration as the minutes have it, and the Decision Log says which was found and done. The reader's `kind` (`RESOLUTION` or `ORDINANCE`) is not stored; the page prints the code and the caption. What a browser does with the link is not a session's to see; Validation names it as the operator's look.

Revision of 2026-11-21. The stylesheet has been read: `src/docket/web/static/layout.css` line 510 upper-cases `.vote-block-result`. So the session does not choose: wherever a template prints `vote_label` for a vote whose `declared_text` is not null, the element carries `vote-block-result--declared` as well, and `layout.css` gains `.vote-block-result--declared { text-transform: none; letter-spacing: normal; }`. The minutes page link, on the meeting page and on the item page, carries `target="_blank" rel="noreferrer"`. `tests/web/test_mobile_minutes_votes.py` asserts three more things: the reader vote's head has the class and a Birmingham minutes vote's head does not; the link has both attributes; and `layout.css` holds the rule (read as a file).

### M6. The close

Acceptance, stated first. The eight documents named in the Progress line state the behaviour M1 to M5 built in the present tense, each fact in one owner. `docs/DEBT.md` has no row `D180`, `D181` or `D184`; rows `D179`, `D183`, `D131`, `D93`, `D111` and `D9` each carry a dated sentence from this plan; there is a new row listing the operator's steps in order with "the pull request merges" as its trigger, and one new row each for the download behaviour of the city's links, the 29 meetings with no minutes and the two files that are not minutes, and the seven malformed code lines (that row says, by the revision of 2026-11-21, that whether any of the seven is a real code with a digit dropped was not checked). The Decision Log's entries on the pairing and the stored link (its record says what it replaces in decision `0119`), on which file wins a meeting, on the result rule with its review reasons, on the matcher's gate, on aliases, on the page link, and on the ingest stage with its cap each have a record under `docs/decisions/` in the format of `docs/decisions/DECISION_FORMAT.md`; the re-deferrals and the floor rule stay in this plan and the debt rows, and a decision a milestone session logged is graduated when it binds later work. `./tools/verify` passes. This milestone does not move the plan to `plans/completed/` and does not write the closing retrospective; the factory's retro stage does both.

The work. `docs/specs/votes.md` gains the Mobile reader under "Two sources": what a reader row holds, the result rule, the three review reasons, the code join, what the pages print, and the tests that pin each. `docs/specs/civicclerk-ingest.md`: the minutes-link rule (the pairing table decides once a file is read), the two settings `minutes_reader` and `minutes_read_cap` (absent reader: stage off; absent cap: 10; 0 reads none), stage 4b and its log lines, the statuses of `minutes_files`, what is still not read, and the Known limits. `docs/specs/operations.md`, Railway specifics: the script, its order and its counts. `docs/specs/index.md`: the two rows. `ARCHITECTURE.md`: Analysis owns the Mobile minutes reader beside Birmingham's parser; Services owns `minutes_votes.py`. `GOALS.md` Scope: Mobile has votes from its minutes. `docs/birmingham/03-votes-and-facts.md` line 7: Birmingham is no longer the only city with votes. `docs/runbooks/cron-worker.md`: what `ingest_all` now does for Mobile and how to stop it (cap 0).


## Concrete Steps

Every command is run from the worktree root, `/home/thinkdarrell/docket-pub/.claude/worktrees/mobile-votes-from-minutes`, with that checkout's `venv/`.

At the start and the end of every milestone:

    ./tools/verify

Expected last line (the time varies; 306 s at authoring): `verify: all 6 checks passed in <n>s.`

One test file on a disposable database (the form the author ran):

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_mobile_minutes.py -q -p no:cacheprovider
    tools/test-db --drop

M1's purity check, expected to print nothing:

    git grep -n "db_cursor\|db()\|import requests" -- src/docket/analysis/mobile_minutes.py

M4's script against the disposable database (expected; the script does not exist until M4):

    DATABASE_URL=$(tools/test-db) venv/bin/python scripts/read_minutes_votes.py --city mobile --limit 2
    tools/test-db --drop

A milestone session sends no request to the city's site or to production. Everything it needs from either is in this file.


## Validation and Acceptance

### What each milestone's tests assert

M1, `tests/unit/test_mobile_minutes.py`: one test per fixture asserting the header date, the number of votes, and for each vote the fields of "Expected readings"; and by name `test_running_line_and_page_number_are_not_content`, `test_a_vote_is_paged_where_its_ayes_line_is_printed` (the vote on page 37 whose declaration is on page 38), `test_abstain_before_nays_is_read`, `test_a_vote_with_no_declaration_is_unknown_and_flagged`, `test_denied_on_a_motion_to_deny_is_passed`, `test_denied_on_a_motion_to_adopt_with_more_ayes_is_flagged_ambiguous`, `test_failed_is_failed_whatever_the_count`, `test_passed_with_fewer_ayes_than_nays_is_flagged`, `test_absent_members_come_from_the_attendance_block_in_force`, `test_an_item_held_over_without_a_vote_gives_no_code_to_the_next_vote`, `test_a_pending_item_carries_across_an_amendment_and_ends_at_a_heading`, `test_a_malformed_code_line_is_not_read_and_the_item_before_it_does_not_leak`, `test_a_procedural_motion_takes_no_code_and_the_item_keeps_it`, `test_code_without_a_colon_and_with_a_space_is_normalised`, `test_a_letter_and_an_agenda_have_no_header_date`, and `test_pages_from_pdf_keeps_an_empty_page` (with `pdfplumber.open` patched). Each is expected to fail before the module exists and pass after.

M2: `tests/integration/test_<number>_migration.py` after the pattern of `test_049_migration.py`; in `tests/unit/test_member_votes.py`, `test_an_alias_resolves_within_the_members_term` and `test_a_four_part_row_has_no_alias`; in `tests/unit/test_vote_matcher.py`, `test_text_rules_pass_over_a_minutes_reader_vote` and `test_match_all_unmatched_does_not_list_a_meeting_whose_only_unlinked_votes_are_reader_votes`; `tests/integration/test_049_migration.py` passes with the edits named in M2.

M3, `tests/integration/test_minutes_votes.py`: one test per clause of M3's acceptance, and `test_the_adoption_sweep_attaches_nothing_to_a_reader_vote`. The roster is the one the migrations seed for Mobile; meetings are seeded by the test under external ids that begin `mv-test-` and removed after.

M4: the tests named in M4's acceptance; `test_a_failed_listing_returns_its_error` and `test_an_unknown_slug_returns_its_error` pin `D184`.

M5: `tests/web/test_mobile_minutes_votes.py` as in M5's acceptance; the existing `tests/web/test_vote_result_block.py` and `tests/web/test_new_routes_p4.py` pass unedited, which is the proof that other votes render as before.

### The operator's steps

None of these is a milestone's, and no Progress line says one was done. M6 writes them into `docs/DEBT.md` as one row whose trigger is "the pull request merges". They are for the operator, on the Legion, in the WSL checkout of docket-pub at `/home/thinkdarrell/docket-pub`, in a terminal there unless a step names the Windows browser.

Before merging, read-only against production (`default_transaction_read_only=on`), pasting the output on the pull request. The design assumes the results stated; a different result is a Surprises entry and a decision, not a quiet fix.

    Q1  SELECT adapter_config, metadata FROM municipalities WHERE slug = 'mobile';
        assumed: adapter_config holds "backlog_floor": "2021-11-01" (D178 step 1 was run);
        metadata has no "briefing", "council_schedule" or "calendar_url" key.

    Q2  SELECT v.source, count(*) FROM votes v JOIN meetings m ON m.id = v.meeting_id
          JOIN municipalities mu ON mu.id = m.municipality_id
         WHERE mu.slug = 'mobile' GROUP BY 1;
        assumed: (0 rows).

    Q3  SELECT m.meeting_date, count(*) FROM meetings m JOIN municipalities mu ON mu.id = m.municipality_id
         WHERE mu.slug = 'mobile' AND m.meeting_date >= DATE '2021-11-01'
         GROUP BY 1 HAVING count(*) > 1 ORDER BY 1;
        assumed: no date before 2026-12-22 (a date with two rows gets no pairing).

    Q4  SELECT cm.name, cm.term_start, cm.term_end, cm.active FROM council_members cm
          JOIN municipalities mu ON mu.id = cm.municipality_id WHERE mu.slug = 'mobile' ORDER BY 1;
        assumed: the ten rows of migration 049, Scott Jones ending 2023-08-08 (D178 step 3 was run).

    Q5  SELECT pg_size_pretty(pg_database_size(current_database()));
        assumed: under 800 MB with 20 MB to spare.

Also before merging: `gh pr list --state open` and a look at `docs/decisions/` and `docs/DEBT.md` on `origin/main`, to see that the numbers M2 and M6 took are still free.

After merging, in one sitting, after the morning's `ingest_all` has finished: (1) deploy `docket-web` and `worker` from a clean `main` with `scripts/deploy.sh`; (2) run the migrations inside the web container and read `--status`; (3) name the reader with a cap of 0, so the script can run and the daily ingest reads nothing yet, one statement, expecting `UPDATE 1`:

    UPDATE municipalities
       SET adapter_config = adapter_config || '{"minutes_reader": "mobile", "minutes_read_cap": 0}'::jsonb
     WHERE slug = 'mobile';

(4) from the laptop against the public address, `venv/bin/python scripts/read_minutes_votes.py --city mobile --limit 300` as a dry run (about seven minutes: one request a second to the city, and one transaction on production that is rolled back; by the revision of 2026-11-21 that transaction opens only after the last file is read and lasts as long as its statements, and since it inserts and rolls back every vote, the full dry run is run once): read that its first line names the production host, and compare its per-file lines with "The reference figures" in Artifacts and Notes (254 files; 225 paired; the dates and vote counts listed there; file 449 and file 869 `not_minutes`; file 433 `no_meeting`; 26 `superseded`); a file whose count differs is opened and looked at before going on; (5) run it again with `--apply` in batches of `--limit 60` (five runs; two insert statements a file), then Q6 and Q7, and set `minutes_read_cap` to 10 with the same statement so the daily ingest keeps up;

(6) in the Windows browser open, written out in full:

    https://docket.pub/al/mobile/

then the meeting of 2026-11-03: its Votes section shows 40 votes sourced "official minutes"; the vote on resolution 40-948-2026 reads "the resolution adopted", 7–0, with Penn, Ingram, Small, Reynolds, Fleming, Woods and Gregory as yea, a line to its agenda item, and a link "Minutes, page 5". Click it and write down what the browser did: opened the PDF at page 5, opened it at page 1, or downloaded it. Open that item's page and see the same vote. Open the meeting of 2021-11-23: 23 votes, the first with Daves absent and "Jones" as yea, no agenda items, each vote under the minutes' caption where it has one. Open a meeting from the 29 with no minutes (2024-01-30): no Votes section and no minutes link. Open the meeting of 2024-10-22: no minutes link where there was a wrong one. Open Scott Jones's member page and Josh Woods's: counts above zero. Look at each at a phone width as well.

    Q6  SELECT count(*) AS votes, count(*) FILTER (WHERE v.resolution_number IS NOT NULL) AS coded,
               count(*) FILTER (WHERE v.resolution_number IS NOT NULL AND m.meeting_date >= DATE '2024-06-25'
                                AND NOT EXISTS (SELECT 1 FROM vote_agenda_items x WHERE x.vote_id = v.id)) AS coded_without_item,
               count(*) FILTER (WHERE v.needs_review) AS flagged
          FROM votes v JOIN meetings m ON m.id = v.meeting_id JOIN municipalities mu ON mu.id = m.municipality_id
         WHERE mu.slug = 'mobile' AND v.minutes_reader = 'mobile';
        expected after step 5: votes 8354, coded 6435, flagged 14 (more if the city has published minutes since
        2026-11-21); coded_without_item is the figure D183 asks for, to be written on that row.

    Q7  SELECT mf.status, count(*) FROM minutes_files mf JOIN municipalities mu ON mu.id = mf.municipality_id
         WHERE mu.slug = 'mobile' GROUP BY 1 ORDER BY 1;
        expected: no_meeting 1, not_minutes 2, paired 225, superseded 26.

Mobile's agenda items arrive at ten meetings a day after the reset of `D178`; a vote is joined to its item by the daily ingest on the first run after the item is stored, so `coded_without_item` falls for some days.


## Idempotence and Recovery

The migration is additive; its down drops what it added and restores the one changed date. Every reader write is keyed: a file is one `minutes_files` row, a meeting's reader votes are replaced whole, and the code join inserts only where a vote has no link. A second run with nothing new writes nothing. A run that stops halfway has committed whole files only.

To stop the reading without a deploy, set `minutes_read_cap` to 0; the listing and the link rule go on. To take the reader's work out of production entirely: delete the city's votes where `minutes_reader = 'mobile'` (their member votes and links go by cascade), delete the city's `minutes_files` rows, and remove the `minutes_reader` key, each one statement scoped to the city. The next ingest then writes every listed meeting's minutes link from the listing alone, as before this plan.

A wrong reading is corrected by changing the rule in `mobile_minutes.py` and raising `READER_VERSION`; every file whose row is below it is read again, `minutes_read_cap` a run, and each meeting's votes are replaced. Vote ids change on a re-read, so a link to `#vote-<id>` on a Mobile meeting page does not survive one; M6 records that in the spec.

A milestone that cannot finish splits its Progress line in place, as `plans/PLANS.md` says, and stops.


## Artifacts and Notes

### The saved minutes text

These are the fixture files M1 creates under `tests/fixtures/mobile_minutes/`, each line exactly as given with the four-space indent of this plan removed. A line `=====PAGE N=====` starts page N; the pages between are empty. The text is the city's, as `pdfplumber` extracted it on 2026-11-21 from the file named, cut down to the lines the tests need; curly apostrophes and dashes are the city's. The two `invented_` files are not the city's words: the author wrote them to pin rules the cut-down excerpts cannot. The test helper `load_pages(name)` returns a list in which index 0 is page 1 and a missing page is the empty string.

`mobile_2026-11-03.txt` (file 3854, the minutes of event 499):

    =====PAGE 1=====
    MUNICIPAL BUILDING, MOBILE, ALABAMA, NOVEMBER 3, 2026
    The Council of the City of Mobile, Alabama, met in the City Council’s Conference Room
    on the ninth floor of the Mobile Government Plaza on Tuesday November 3, 2026, at 9:00
    a.m.
    Councilmembers:
    Present: Penn, Ingram, Small, Reynolds, Fleming, Woods, and Gregory
    Absent: None
    The meeting was called to order. The Council reviewed and discussed the agenda for
    their meeting to be held today at 10:30 a.m.
    Approved:
    COUNCIL PRESIDENT
    CITY CLERK
    MUNICIPAL BUILDING, MOBILE, ALABAMA, NOVEMBER 3, 2026
    The City Council of the City of Mobile, Alabama, met in the Auditorium of the Government
    Plaza on Tuesday, November 3, 2026, at 10:30 a.m., for the regular meeting.
    The meeting was called to order by the City Clerk.
    The Presiding Officer led the Pledge of Allegiance.
    Present on Roll Call:
    Chairman: Small
    Vice-Chairman: Gregory
    Councilmembers: Penn, Ingram, Reynolds, Fleming, and Woods
    Absent: None
    STATEMENT OF RULES BY PRESIDING OFFICER
    The Presiding Officer provided an overview of the City Council’s Rules of Procedure.
    APPROVAL OF MINUTES
    The minutes from the meeting of October 27, 2026 were approved as submitted.
    =====PAGE 2=====
    MINUTES OF NOVEMBER 3, 2026
    ADOPTION OF THE AGENDA
    Councilmember Penn moved to adopt the agenda, which was seconded by
    Councilmember Woods
    Ayes: Penn, Ingram, Small, Reynolds, Fleming, Woods, and Gregory
    Nays: None
    The vote was then announced by the City Clerk whereupon the Presiding Officer declared
    the agenda adopted.
    APPEALS
    Request of Kendrick Wells for a waiver of the Noise Ordinance at 650 St. Francis Street
    on November 6, 2026, from 7:00 p.m. – 10:00 p.m. (District 2).
    Councilmember Ingram moved to adopt the waiver, which was seconded by
    Councilmember Gregory and the vote was as follows:
    Ayes: Small, Penn, Ingram, Reynolds, Fleming, Woods, and Gregory
    Nays: None
    The vote was then announced by the City Clerk whereupon the Presiding Officer declared
    the waiver adopted.
    =====PAGE 4=====
    MINUTES OF NOVEMBER 3, 2026
    CONSENT RESOLUTIONS HELD OVER
    DECLARE THE STRUCTURE AT 906 S. BROAD STREET A PUBLIC NUISANCE AND
    ORDER IT DEMOLISHED. The following resolution which was introduced and read at the
    regular meeting of September 1, 2026, and held over until the regular meeting of
    November 3, 2026, was called up by the Presiding Officer.
    RESOLUTION: 40-948-2026
    Sponsored by: Councilmember Small
    4
    =====PAGE 5=====
    MINUTES OF NOVEMBER 3, 2026
    filed in the Office of the Judge of Probate of Mobile County, Alabama.
    The resolution was read by the City Clerk, whereupon Councilmember Small moved to
    adopt the resolution, which was seconded by Councilmember Ingram and the vote was as
    follows:
    Ayes: Penn, Ingram, Small, Reynolds, Fleming, Woods, and Gregory
    Nays: None
    The vote was then announced by the City Clerk, whereupon the Presiding Officer declared
    the resolution adopted.
    RESOLUTIONS HELD OVER
    AUTHORIZE PROFESSIONAL SERVICES CONTRACT WITH THE BLOOM GROUP,
    INC.; NTE $156,000.00. The following resolution which was introduced and read at the
    regular meeting of October 20, 2026 and was held over until the regular meetings of
    October 27, 2026, and November 3, 2026 was called up by the Presiding Officer.
    RESOLUTION: 21-1141-2026
    Sponsored by: Mayor Cheriogotis
    =====PAGE 19=====
    MINUTES OF NOVEMBER 3, 2026
    SUSPENSION OF RULES FOR IMMEDIATE CONSIDERATION OF CONSENT
    RESOLUTIONS BEING INTRODUCED FOR THE FIRST TIME. Councilmember
    Reynolds moved for the suspension of the rules to consider resolutions 03-1171 through
    60-1178 being introduced for the first time. The motion was seconded by Councilmember
    Penn and the vote was as follows:
    Ayes: Penn, Ingram, Small, Reynolds, Fleming, Woods, and Gregory
    Nays: None
    The Presiding Officer declared unanimous consent granted for the items.
    CONSENT RESOLUTIONS BEING INTRODUCED
    APPOINT SPENCER RUGGS, JR. TO THE BOARD OF ADJUSTMENT. The following
    resolution was introduced by Councilmember Reynolds.
    RESOLUTION: 03-1171-2026
    Sponsored by: Councilmember Ingram
    19
    =====PAGE 24=====
    MINUTES OF NOVEMBER 3, 2026
    RESOLUTIONS BEING INTRODUCED
    AUTHORIZE AGREEMENT WITH A-1 MCDUFFIE SANITATION, LLC, AND
    ECOSOUTH SERVICES OF MOBILE, LLC FOR RESIDENTIAL GARBAGE AND
    24
    =====PAGE 25=====
    MINUTES OF NOVEMBER 3, 2026
    TRASH SERVICES. The following resolution was held over until the regular meeting of
    November 10, 2026.
    RESOLUTION: 01-1179-2026
    Sponsored by: Mayor Cheriogotis
    BE IT RESOLVED BY THE CITY COUNCIL OF THE CITY OF MOBILE, ALABAMA, that
    the Mayor and the City Clerk be, and they hereby are authorized to execute and attest,
    of said Agreement is on file in the office of the City Clerk.
    APPROVE PURCHASE ORDER TO SOUTHERN REALTY MANAGEMENT GROUP,
    LLC FOR STORM DRAINAGE VEGETATION AND DEBRIS REMOVAL – 3153
    HEATHER STREET TO DAUPHIN STREET; $25,000.00. The following resolution was
    introduced by Councilmember Reynolds.
    RESOLUTION: 08-1180-2026
    Sponsored by: Mayor Cheriogotis
    BE IT RESOLVED BY THE CITY COUNCIL OF MOBILE, ALABAMA, that the Purchasing
    Agent is authorized to execute, for and on behalf of the City of Mobile, a purchase order
    The resolution was read by the City Clerk, whereupon Councilmember Reynolds moved
    to adopt the resolution which was seconded by Councilmember Ingram and the vote was
    as follows:
    Ayes: Penn, Ingram, Small, Reynolds, Fleming, Woods, and Gregory
    Nays: None
    The vote was then announced by the City Clerk, whereupon the Presiding Officer declared
    the resolution adopted.
    =====PAGE 36=====
    MINUTES OF NOVEMBER 3, 2026
    CALL FOR PUBLIC HEARING TO CONSIDER AMENDING THE DOWNTOWN
    DEVELOPMENT DISTRICT REGULATING PLAN TO UPDATE THE ZONING MAP TO
    REZONE PROPERTY LOCATED AT 255 CHURCH STREET FROM T-5.2 TO T-6
    (SCHEDULED FOR DECEMBER 8, 2026) (DISTRICT 2). The following resolution was
    introduced by Councilmember Ingram.
    RESOLUTION: 41-1198-2026
    36
    =====PAGE 37=====
    MINUTES OF NOVEMBER 3, 2026
    Section Two: This Ordinance shall be in force and effect from and after its adoption and
    publication.
    Councilmember Ingram moved to call for the public hearing, which was seconded by
    Councilmember Reynolds and the vote was as follows:
    Ayes: Penn, Ingram, Small, Reynolds, Fleming, Woods, and Gregory
    Nays: None
    37
    =====PAGE 38=====
    MINUTES OF NOVEMBER 3, 2026
    The vote was then announced by the City Clerk, whereupon the Presiding Officer set the
    date for the public hearing as December 8, 2026.
    ANNOUNCEMENTS
    Councilmembers Ingram, Penn, Gregory, and Small encouraged all citizens to vote today.
    Councilmember Reynolds moved to adjourn the meeting, which was seconded by
    Councilmember Ingram and the vote was as follows:
    Ayes: Penn, Ingram, Small, Reynolds, Fleming, Woods, and Gregory
    Nays: None
    The vote was then announced by the City Clerk, whereupon the Presiding Officer declared
    the regular meeting adjourned at approximately 11:40 a.m.
    Adopted:
    COUNCIL PRESIDENT
    CITY CLERK
    38

`mobile_2021-11-23.txt` (file 160):

    =====PAGE 1=====
    MUNICIPAL BUILDING, MOBILE, ALABAMA, NOVEMBER 23, 2021
    The Council of the City of Mobile, Alabama, met in the City Council’s Conference Room
    on the ninth floor of the Mobile Government Plaza on Tuesday, November 23, 2021, at
    9:00 a.m.
    Present:
    Councilmembers: Penn, Carroll, Small, Reynolds, Scott and Gregory
    Absent: Daves
    The meeting was called to order. The Council reviewed and discussed the agenda for
    their meeting to be held today at 10:30 a.m.
    Approved:
    COUNCIL PRESIDENT
    CITY CLERK
    Councilmember Gregory moved for the Council to enter into executive session and
    reconvene into the regular meeting at 10:30 a.m., which move was seconded by
    Councilmember Jones.
    =====PAGE 2=====
    MINUTES OF NOVEMBER 23, 2021
    Following a roll call, the vote was as follows:
    Ayes: Penn, Carroll, Small, Reynolds, Jones and Gregory
    Nays: None
    The vote was then announced by the City Clerk whereupon the Presiding Officer declared
    the meeting moved into executive session at approximately 9:26 a.m.
    MUNICIPAL BUILDING, MOBILE, ALABAMA, NOVEMBER 23, 2021
    The City Council of the City of Mobile, Alabama, met in the Auditorium of the Mobile
    Government Plaza on Tuesday, November 23, 2021, at 10:30 a.m., in regular meeting.
    The meeting was called to order by City Clerk Lisa C. Lambert.
    The Presiding Officer led the Pledge of Allegiance.
    Present on Roll Call:
    Chairman: Small
    Councilmembers: Penn, Carroll, Reynolds, Scott and Gregory
    Absent: Daves
    2

`mobile_2024-06-18.txt` (file 811):

    =====PAGE 2=====
    MINUTES OF JUNE 18, 2024
    ADOPTION OF THE AGENDA
    Councilmember Penn moved to adopt the agenda, which was seconded by
    Councilmember Woods and the vote was as follows:
    Ayes: Penn, Carroll, Small, Reynolds, Daves, Woods, and Gregory
    Nays: None
    2
    =====PAGE 3=====
    MINUTES OF JUNE 18, 2024
    The vote was then announced by the Assistant City Clerk whereupon the Presiding Officer
    declared the motion to adopt the agenda adopted.
    APPEALS
    Request of Forress Rayford for a waiver of the Noise Ordinance at 911 Dauphin Street on
    March 3, 2025, from 5:00 p.m. – 1:00 a.m. (District 2).
    Councilmember Carroll moved to table the waiver, which move was seconded by
    Councilmember Woods and the vote was as follows:
    Ayes: Penn, Carroll, Small, Reynolds, Woods, and Gregory
    Nays: None
    Abstain: Daves
    The vote was then announced by the Assistant City Clerk whereupon the Presiding Officer
    declared the waiver tabled.

`mobile_2022-02-22.txt` (file 663):

    =====PAGE 15=====
    MINUTES OF FEBRUARY 22, 2022
    The Presiding Officer called for the vote on Councilmember Carroll’s motion to amend/hold
    over the ordinance for four (4) months and the vote was as follows:
    Ayes: Penn, Carroll, Small, Daves, and Gregory
    Abstain: Reynolds and Jones
    Nays: None
    The Presiding Officer called for the vote on Councilmember Jones’ original motion, and
    the vote was as follows:
    Ayes: Penn, Carroll, Small, Daves, and Gregory
    Abstain: Reynolds and Jones
    Nays: None

`mobile_2022-03-15.txt` (file 625):

    =====PAGE 9=====
    MINUTES OF MARCH 15, 2022
    AUTHORIZE THE COUNCIL TO HIRE A CONSULTANT TO PERFORM AND PROVIDE
    A RACIAL POLARIZATION STUDY. The following resolution, which was introduced and
    read at the regular meeting of February 22, 2022, and held over until the regular meeting
    of March 15, 2022, was called up by the Presiding Officer.
    RESOLUTION: 60-197-2022
    Sponsored by: Councilmembers Daves and Gregory
    BE IT RESOLVED by the City Council of the City of Mobile that the Council shall hire a
    consultant to perform and provide a racial polarization study of City of Mobile municipal
    election voting patterns, provided, however, that the consultant to be hired to provide such
    study must be approved by a super majority of the Council.
    The resolution was read by the City Clerk; whereupon Councilmember Daves moved that
    the resolution be adopted, which was seconded by Councilmember Gregory and the vote
    was as follows:
    Ayes: Carroll, Daves and Gregory
    Nays: None
    Abstain: Reynolds and Jones
    The vote was then announced by the City Clerk, whereupon the Presiding Officer declared
    the resolution denied.

`mobile_2022-07-12.txt` (file 393):

    =====PAGE 3=====
    MINUTES OF JULY 12, 2022
    NOTE: Councilmember Reynolds moved to waive the rules regarding four speakers on
    either side of the issue for this public hearing, the move was seconded by Councilmember
    Daves and the vote was as follows:
    Ayes: Penn, Carroll, Small, Reynolds, Daves, Jones, and Gregory
    Nays: None
    The motion passed.

`mobile_2024-07-16.txt` (file 105):

    =====PAGE 6=====
    MINUTES OF JULY 16, 2024
    The ordinance was read by the Assistant City Clerk, whereupon Councilmember Penn
    moved to adopt the ordinance which was seconded by Councilmember Woods and the
    vote was as follows:
    Ayes: Penn and Daves
    Nays: Carroll, Small, Reynolds, Woods, and Gregory
    The vote was then announced by the Assistant City Clerk, whereupon the Presiding Officer
    declared the ordinance failed.

`mobile_2025-11-18.txt` (file 1375):

    =====PAGE 30=====
    MINUTES OF NOVEMBER 18, 2025
    and recommend whether to (i) continue, (ii) modify, or (iii) expand the program citywide.
    and the vote was as follows:
    and the vote was as follows:
    Ayes: Reynolds
    Nays: Penn, Ingram, Small, Fleming, and Woods
    The Presiding Officer declared the amendment passed.
    The Presiding Officer called for the vote on the original motion as amended and the
    vote was as follows:
    Ayes: Reynolds
    Nays: Penn, Ingram, Small, Fleming, and Woods
    The vote was then announced by the City Clerk, whereupon the Presiding Officer
    declared the ordinance adopted as amended.

`mobile_2026-11-10.txt` (file 3861):

    =====PAGE 28=====
    MINUTES OF NOVEMBER 10, 2026
    Following comments from Councilmembers Gregory and Woods, Councilmember
    Gregory moved to deny the ordinance, which was seconded by Councilmember
    Reynolds and the vote was as follows:
    Ayes: Penn, Ingram, Small, Reynolds, Fleming, Woods, and Gregory
    Nays: None
    The vote was then announced by the Assistant City Clerk, whereupon the Presiding
    Officer declared the ordinance denied.

`not_minutes_agenda.txt` (file 869, the agenda filed as the minutes of 2024-10-22):

    =====PAGE 1=====
    AGENDA
    Mobile City Council
    Auditorium
    Government Plaza
    205 Government Street
    Mobile, AL 36644
    Tuesday, October 29, 2024, 10:30 AM
    1. CALL TO ORDER

`not_minutes_letter.txt` (file 449, the head of a one-page letter):

    =====PAGE 1=====
    CITY CLERK
    THE CITY OF MOBILE, ALABAMA
    OFFICE OF THE CITY CLERK
    October 25, 2022

`invented_chain.txt` (the author's words, not the city's):

    =====PAGE 1=====
    WIDGET ORDINANCE HELD OVER FROM LAST WEEK. The following ordinance which was introduced and read at the
    regular meeting of May 1, 2029, and held over until the regular meeting of May 8, 2029, was called up by
    the Presiding Officer.
    ORDINANCE 12- 345-2029
    Section One. Widgets are regulated.
    Councilmember Alpha moved to amend the ordinance, which was seconded by Councilmember Beta and the
    vote was as follows:
    Ayes: Alpha, Beta, and Gamma
    Nays: Delta
    The vote was then announced by the City Clerk, whereupon the Presiding Office declared
    the amendment adopted.
    1
    =====PAGE 2=====
    MINUTES OF MAY 8, 2029
    The Presiding Officer then called for the vote on the original motion as amended and the
    vote was as follows:
    Ayes: Alpha, Beta, Gamma, and Delta
    Nays: None
    The vote was then announced by the City Clerk, whereupon the Presiding Officer declared the
    ordinance adopted as amended.
    ANNOUNCEMENTS
    Councilmember Alpha moved to recognize a guest, which was seconded by Councilmember Beta and the
    vote was as follows:
    Ayes: Alpha, Beta, Gamma, and Delta
    Nays: None
    The motion carried.
    2

`invented_closing.txt` (the author's words, not the city's):

    =====PAGE 1=====
    RESOLUTIONS BEING INTRODUCED
    FIRST THING. The following resolution was held over until the regular meeting of May 15, 2029.
    RESOLUTION: 01-100-2029
    BE IT RESOLVED that the first thing is done.
    SECOND THING. The following resolution was introduced by Councilmember Alpha.
    RESOLUTION: 1-101-2029
    BE IT RESOLVED that the second thing is done.
    The resolution was read by the City Clerk, whereupon Councilmember Alpha moved to adopt the
    resolution, which was seconded by Councilmember Beta and the vote was as follows:
    Ayes: Alpha, Beta, Gamma, and Delta
    Nays: None
    The vote was then announced by the City Clerk, whereupon the Presiding Officer declared
    the resolution adopted.
    THIRD THING FOR THE PARKS; $1,000.00. The
    following resolution was introduced by Councilmember Alpha.
    RESOLUTION: 01-102-2029
    BE IT RESOLVED that the third thing is done.
    Councilmember Beta moved to recess the meeting for five minutes, which was seconded by
    Councilmember Gamma and the vote was as follows:
    Ayes: Alpha, Beta, Gamma, and Delta
    Nays: None
    The vote was then announced by the City Clerk, whereupon the Presiding Officer declared
    the meeting in recess.
    The resolution was read by the City Clerk, whereupon Councilmember Alpha moved to adopt the
    resolution, which was seconded by Councilmember Beta and the vote was as follows:
    Ayes: Alpha and Beta
    Nays: Gamma and Delta
    Abstained: Epsilon
    The vote was then announced by the City Clerk, whereupon the Presiding Officer declared
    the resolution failed.

### Expected readings

What the rules of M1 give for each fixture, obtained by running the author's script on the files as they are printed above (the script was re-run on the text of this section's fixtures before the plan was committed; where a rule and a line here disagree, the session logs it as a Surprise and a Decision, and does not bend either quietly). "Seven" stands for `Penn, Ingram, Small, Reynolds, Fleming, Woods, Gregory` in that order. Every vote not said to be flagged has `needs_review` false; every list not given is empty; code, kind and caption not given are None.

`mobile_2026-11-03.txt`: header date 2026-11-03; seven votes.
1. page 2; ayes Seven; `passed`; declared `the agenda adopted`; motion `Councilmember Penn moved to adopt the agenda, which was seconded by Councilmember Woods`.
2. page 2; ayes `Small, Penn, Ingram, Reynolds, Fleming, Woods, Gregory`; `passed`; declared `the waiver adopted`; motion `Councilmember Ingram moved to adopt the waiver, which was seconded by Councilmember Gregory and the vote was as follows:`.
3. page 5; ayes Seven; `passed`; declared `the resolution adopted`; code `40-948-2026`, kind `RESOLUTION`, caption `DECLARE THE STRUCTURE AT 906 S. BROAD STREET A PUBLIC NUISANCE AND ORDER IT DEMOLISHED`; motion `The resolution was read by the City Clerk, whereupon Councilmember Small moved to adopt the resolution, which was seconded by Councilmember Ingram and the vote was as follows:`.
4. page 19; ayes Seven; `passed`; declared `unanimous consent granted for the items`; no code (the pending item `21-1141-2026` is not taken: the motion is to suspend the rules); motion `Reynolds moved for the suspension of the rules to consider resolutions 03-1171 through 60-1178 being introduced for the first time. The motion was seconded by Councilmember Penn and the vote was as follows:`.
5. page 25; ayes Seven; `passed`; declared `the resolution adopted`; code `08-1180-2026`, kind `RESOLUTION`, caption `APPROVE PURCHASE ORDER TO SOUTHERN REALTY MANAGEMENT GROUP, LLC FOR STORM DRAINAGE VEGETATION AND DEBRIS REMOVAL – 3153 HEATHER STREET TO DAUPHIN STREET; $25,000.00` (not `03-1171-2026`, cleared by the heading on page 24, nor `01-1179-2026`, held over).
6. page 37; ayes Seven; `passed`; declared `set the date for the public hearing as December 8, 2026`; code `41-1198-2026`, kind `RESOLUTION`, caption `CALL FOR PUBLIC HEARING TO CONSIDER AMENDING THE DOWNTOWN DEVELOPMENT DISTRICT REGULATING PLAN TO UPDATE THE ZONING MAP TO REZONE PROPERTY LOCATED AT 255 CHURCH STREET FROM T-5.2 TO T-6 (SCHEDULED FOR DECEMBER 8, 2026) (DISTRICT 2)`; motion `Councilmember Ingram moved to call for the public hearing, which was seconded by Councilmember Reynolds and the vote was as follows:`.
7. page 38; ayes Seven; `passed`; declared `the regular meeting adjourned at approximately 11:40 a.m.`; no code (cleared by `ANNOUNCEMENTS`, and the motion is to adjourn).

`mobile_2021-11-23.txt`: header date 2021-11-23; one vote: page 2; ayes `Penn, Carroll, Small, Reynolds, Jones, Gregory`; absent `Daves`; `passed`; declared `the meeting moved into executive session at approximately 9:26 a.m.`; motion `Councilmember Gregory moved for the Council to enter into executive session and reconvene into the regular meeting at 10:30 a.m., which move was seconded by Councilmember Jones. Following a roll call, the vote was as follows:`.

`mobile_2024-06-18.txt`: no header date (page 1 is not in the excerpt); two votes. 1: page 2; ayes `Penn, Carroll, Small, Reynolds, Daves, Woods, Gregory`; `passed`; declared `the motion to adopt the agenda adopted`. 2: page 3; ayes `Penn, Carroll, Small, Reynolds, Woods, Gregory`; abstain `Daves`; `passed`; declared `the waiver tabled`; motion `Councilmember Carroll moved to table the waiver, which move was seconded by Councilmember Woods and the vote was as follows:`.

`mobile_2022-02-22.txt`: two votes, both page 15; ayes `Penn, Carroll, Small, Daves, Gregory`; abstain `Reynolds, Jones`; no declaration; `unknown`, flagged `declaration_not_read`. The first's motion is `The Presiding Officer called for the vote on Councilmember Carroll’s motion to amend/hold over the ordinance for four (4) months and the vote was as follows:`.

`mobile_2022-03-15.txt`: one vote: page 9; ayes `Carroll, Daves, Gregory`; abstain `Reynolds, Jones`; declared `the resolution denied`; `unknown`, flagged `declaration_ambiguous`; code `60-197-2022`, kind `RESOLUTION`, caption `AUTHORIZE THE COUNCIL TO HIRE A CONSULTANT TO PERFORM AND PROVIDE A RACIAL POLARIZATION STUDY`.

`mobile_2022-07-12.txt`: one vote: page 3; seven ayes `Penn, Carroll, Small, Reynolds, Daves, Jones, Gregory`; `passed`; declared `The motion passed`.

`mobile_2024-07-16.txt`: one vote: page 6; ayes `Penn, Daves`; nays `Carroll, Small, Reynolds, Woods, Gregory`; `failed`; declared `the ordinance failed`; motion `The ordinance was read by the Assistant City Clerk, whereupon Councilmember Penn moved to adopt the ordinance which was seconded by Councilmember Woods and the vote was as follows:` (the line before `moved` is taken because that line begins with a lowercase letter).

`mobile_2025-11-18.txt`: two votes, both page 30; ayes `Reynolds`; nays `Penn, Ingram, Small, Fleming, Woods`; both `passed` and flagged `declaration_contradicts_count`. 1: declared `the amendment passed`; no motion. 2: declared `the ordinance adopted as amended`; motion `The Presiding Officer called for the vote on the original motion as amended and the vote was as follows:`.

`mobile_2026-11-10.txt`: one vote: page 28; ayes Seven; `passed`, not flagged; declared `the ordinance denied`; motion `Gregory moved to deny the ordinance, which was seconded by Councilmember Reynolds and the vote was as follows:`.

`not_minutes_agenda.txt` and `not_minutes_letter.txt`: no header date, no votes.

`invented_chain.txt`: three votes. 1: page 1; ayes `Alpha, Beta, Gamma`; nays `Delta`; `passed`; declared `the amendment adopted`; code `12-345-2029`, kind `ORDINANCE`, caption `WIDGET ORDINANCE HELD OVER FROM LAST WEEK`. 2: page 2; four ayes; `passed`; declared `the ordinance adopted as amended`; the same code, kind and caption. 3: page 2; four ayes; `passed`; declared `The motion carried`; no code.

`invented_closing.txt`: three votes, all page 1. 1: four ayes; `passed`; declared `the resolution adopted`; no code (`01-100-2029` was held over, and `1-101-2029` is malformed and not read). 2: four ayes; `passed`; declared `the meeting in recess`; no code. 3: ayes `Alpha, Beta`; nays `Gamma, Delta`; abstain `Epsilon`; `failed`; declared `the resolution failed`; code `01-102-2029`, kind `RESOLUTION`, caption `THIRD THING FOR THE PARKS; $1,000.00`.

For `vote_label` and `vote_tone` (M2): `("passed", None)` gives `passed` and `pass`; `("failed", None)` gives `failed` and `fail`; `("tabled", None)` gives `tabled` and the empty string; `("passed", "the resolution adopted")` gives `the resolution adopted` and `pass`; `("passed", "the waiver tabled")` and `("passed", "the resolution held over for sixty days")` give the declaration and the empty string; `("passed", "the ordinance denied")` and `("failed", "the ordinance failed")` give the declaration and `fail`; `("unknown", "the resolution denied")` gives the declaration and `fail`; `("unknown", None)` gives `unknown` and the empty string. Added by the revision of 2026-11-21: `("passed", "the ordinance laid over until the next meeting")` and `("passed", "the resolution withdrawn")` give the declaration and the empty string; `("failed", "the resolution withdrawn")` gives the declaration and `fail`, because a failed result is tested first.

### The reference figures

What the author's script read on 2026-11-21 for the 225 meetings that pair, as `date:file:votes`, for the operator's dry run to be compared with. A vote is one line beginning `Ayes:`, so the count does not depend on any other rule. Totals: 8,354 votes, 6,435 with a code, 57,607 member positions; `passed` 8,313, `failed` 29, `unknown` 12; 14 flagged.

    2021-11-02:197:28 2021-11-09:185:23 2021-11-17:171:27 2021-11-23:160:23 2021-11-30:148:22 2021-12-07:135:20
    2021-12-14:123:45 2021-12-21:111:26 2022-01-04:746:28 2022-01-11:734:42 2022-01-18:721:32 2022-01-25:709:35
    2022-02-01:697:32 2022-02-08:685:43 2022-02-15:673:32 2022-02-22:663:44 2022-03-02:647:14 2022-03-08:637:27
    2022-03-15:625:37 2022-03-22:613:34 2022-03-29:601:38 2022-04-05:587:29 2022-04-12:575:24 2022-04-19:561:40
    2022-04-26:547:29 2022-05-03:532:24 2022-05-10:518:44 2022-05-17:504:56 2022-05-24:488:29 2022-06-07:461:25
    2022-06-14:447:34 2022-06-28:420:28 2022-07-05:407:19 2022-07-12:393:38 2022-07-19:381:31 2022-07-26:369:23
    2022-08-02:357:25 2022-08-09:661:48 2022-08-16:333:28 2022-08-23:321:26 2022-08-30:310:39 2022-09-06:298:32
    2022-09-13:286:44 2022-09-20:275:40 2022-09-27:263:48 2022-10-04:251:27 2022-10-11:237:38 2022-10-19:221:36
    2022-11-01:199:29 2022-11-08:189:48 2022-11-15:175:29 2022-11-22:162:28 2022-11-29:150:27 2022-12-06:137:36
    2022-12-13:125:29 2022-12-20:113:27 2023-01-03:748:41 2023-01-10:736:35 2023-01-17:383:43 2023-01-24:371:27
    2023-01-31:699:42 2023-02-07:687:47 2023-02-14:677:55 2023-02-22:335:34 2023-02-28:323:25 2023-03-07:265:34
    2023-03-14:300:40 2023-03-21:288:56 2023-03-28:603:46 2023-04-04:213:42 2023-04-11:253:27 2023-04-18:239:41
    2023-04-25:225:38 2023-05-02:201:64 2023-05-09:177:42 2023-05-23:164:44 2023-05-30:152:43 2023-06-13:187:34
    2023-06-20:115:29 2023-06-27:422:38 2023-07-05:738:2 2023-07-11:139:35 2023-07-18:752:34 2023-08-01:713:23
    2023-08-08:701:43 2023-08-15:725:47 2023-08-22:689:48 2023-08-29:675:60 2023-09-05:665:28 2023-09-12:653:44
    2023-09-19:643:54 2023-09-26:631:37 2023-10-03:617:28 2023-10-10:605:34 2023-10-17:591:43 2023-10-24:579:44
    2023-10-31:567:35 2023-11-08:553:35 2023-11-14:539:26 2024-05-07:806:28 2024-05-14:807:28 2024-05-21:808:48
    2024-05-28:809:39 2024-06-04:812:33 2024-06-11:453:28 2024-06-18:811:31 2024-06-25:77:30 2024-07-02:94:33
    2024-07-09:95:40 2024-07-16:105:35 2024-07-23:762:42 2024-07-30:780:41 2024-08-06:769:46 2024-08-13:779:29
    2024-08-20:785:47 2024-08-27:786:38 2024-09-03:797:39 2024-09-10:829:41 2024-09-17:831:28 2024-09-24:835:32
    2024-10-01:862:28 2024-10-09:863:28 2024-10-15:864:33 2024-10-29:887:29 2024-11-05:898:30 2024-11-12:899:58
    2024-11-19:912:39 2024-11-26:913:37 2024-12-03:914:30 2024-12-10:925:46 2024-12-17:932:42 2025-01-02:939:30
    2025-01-07:950:18 2025-01-14:979:45 2025-01-28:1001:39 2025-02-04:992:54 2025-02-11:1002:38 2025-02-25:1027:40
    2025-03-05:1028:37 2025-03-11:1038:38 2025-03-18:1047:43 2025-03-25:1055:38 2025-04-01:1065:46 2025-04-08:1074:36
    2025-04-15:1081:42 2025-04-22:1091:39 2025-04-29:1096:35 2025-05-06:1101:37 2025-05-13:1126:42 2025-05-20:1147:49
    2025-05-27:1151:44 2025-06-03:1150:44 2025-06-10:1146:42 2025-06-17:1172:66 2025-06-24:1173:32 2025-07-01:1171:28
    2025-07-08:1183:35 2025-07-15:1199:40 2025-07-22:1198:40 2025-07-29:1216:53 2025-08-05:1217:41 2025-08-12:1231:24
    2025-08-19:1337:31 2025-08-27:1338:36 2025-09-02:1339:32 2025-09-09:1340:34 2025-09-16:1341:46 2025-09-24:1342:26
    2025-09-30:1347:44 2025-10-14:1348:75 2025-10-21:1349:63 2025-10-28:1350:37 2025-11-04:1351:29 2025-11-12:1363:34
    2025-11-18:1375:49 2025-11-25:1394:41 2025-12-02:1395:18 2025-12-09:1408:34 2025-12-16:1409:29 2025-12-30:1432:45
    2026-01-06:1433:30 2026-01-13:1439:42 2026-01-20:1449:44 2026-01-27:1450:46 2026-02-03:1467:41 2026-02-10:2483:42
    2026-02-18:2482:36 2026-02-24:2509:35 2026-03-03:2507:32 2026-03-10:2508:53 2026-03-17:2535:40 2026-03-24:2559:37
    2026-03-31:2560:44 2026-04-07:2579:51 2026-04-14:2580:47 2026-04-21:2588:45 2026-04-28:2589:41 2026-05-05:2597:50
    2026-05-12:2605:41 2026-05-19:2631:39 2026-05-26:2642:46 2026-06-02:2644:30 2026-06-09:2650:43 2026-06-16:2654:48
    2026-06-23:2669:36 2026-06-30:2670:26 2026-07-07:2676:28 2026-07-14:3683:26 2026-07-21:3687:33 2026-07-28:3694:32
    2026-08-04:3702:43 2026-08-11:3709:37 2026-08-18:3721:35 2026-08-25:3728:57 2026-09-01:3743:40 2026-09-08:3748:22
    2026-09-15:3757:38 2026-09-22:3774:41 2026-09-29:3801:41 2026-10-06:3802:48 2026-10-14:3813:42 2026-10-20:3822:28
    2026-10-27:3833:40 2026-11-03:3854:40 2026-11-10:3861:48

The file listed for a date named by two files is the one on that date's own event. The 26 doubled dates and both files of each: 2021-11-30 (148, 345), 2022-03-15 (211, 625), 2022-05-24 (488, 723), 2022-06-14 (447, 711), 2022-06-28 (420, 589), 2022-08-02 (357, 627), 2022-08-23 (321, 651), 2022-08-30 (310, 615), 2022-09-06 (298, 639), 2022-09-13 (286, 534), 2022-09-20 (275, 563), 2022-09-27 (263, 549), 2022-10-04 (251, 490), 2022-10-11 (237, 577), 2022-11-01 (199, 520), 2022-11-29 (150, 506), 2022-12-06 (137, 476), 2022-12-13 (125, 463), 2022-12-20 (113, 435), 2023-01-03 (405, 748), 2023-01-10 (395, 736), 2023-01-31 (312, 699), 2023-02-07 (359, 687), 2023-02-14 (347, 677), 2023-03-28 (277, 603), 2023-06-27 (127, 422). A dry run that reads the other file of a pair first reports that one `paired` and the listed one `superseded`, unless the listed one is read later in the same run, when it takes over; the vote counts are the same either way.

### The code join, measured

For 11 meetings the author fetched the agenda (`GET https://mobileal.api.civicclerk.com/v1/Meetings/<agendaId>`) and compared the codes that open item names (`^(\d{2}-\d{3,4})\b`) with the codes of the votes read: 2024-06-25 22 of 22 vote codes have an item, 2024-07-02 22 of 22, 2024-08-13 22 of 22, 2024-10-15 27 of 28, 2025-01-07 14 of 14, 2025-07-01 17 of 17, 2025-11-04 19 of 21, 2026-01-06 23 of 24, 2026-06-02 20 of 20, 2026-11-03 35 of 35, 2026-11-10 37 of 37. No agenda had two items with one code. In Postgres (run on the disposable database on 2026-11-21) `substring('40-948 Declare the structure' from '^(\d{2}-\d{3,4})\y')` and `substring('40-948-2026' from '^(\d{2}-\d{3,4})-\d{4}$')` both give `40-948`, and `substring('Roll Call' from ...)` and `substring('40-94811 x' from ...)` give NULL.


## Interfaces and Dependencies

No new library. `pdfplumber` (already in `requirements.txt`) reads the PDFs; `psycopg2.extras.execute_values` writes the multi-row inserts.

In `src/docket/analysis/mobile_minutes.py`:

    READER_VERSION = 1

    @dataclass(frozen=True)
    class MinutesVote:
        page: int
        ayes: tuple[str, ...]
        nays: tuple[str, ...]
        abstain: tuple[str, ...]
        absent: tuple[str, ...]
        motion_text: str | None
        declared_text: str | None
        result: str                 # 'passed' | 'failed' | 'unknown'
        needs_review: bool
        review_reason: str | None   # 'declaration_not_read' | 'declaration_ambiguous' | 'declaration_contradicts_count'
        code: str | None            # '40-948-2026'
        kind: str | None            # 'RESOLUTION' | 'ORDINANCE'
        caption: str | None
        raw_text: str

    @dataclass(frozen=True)
    class MinutesReading:
        header_date: date | None
        votes: tuple[MinutesVote, ...]

    def read_minutes(pages: list[str]) -> MinutesReading: ...
    def pages_from_pdf(pdf_bytes: bytes) -> list[str]: ...

In `src/docket/models/protocol.py`:

    @dataclass(frozen=True)
    class RawMinutesFile:
        file_id: str
        url: str
        event_external_id: str
        event_date: date

In `src/docket/models/vote.py`, on `Vote` (all defaulting to None): `minutes_reader`, `source_page`, `caption`, `motion_text`, `declared_text`, `minutes_page_url`; and the module functions, the one owner of what a page prints for a result:

    def vote_label(result: str, declared_text: str | None) -> str:
        """The declaration when the row has one, else the stored result."""

    def vote_tone(result: str, declared_text: str | None) -> str:
        """'fail' when the result is failed or the declaration says failed or denied;
        '' when the declaration says tabled, held over, laid over or withdrawn (whole
        words, ignoring case; the last two added by the revision of 2026-11-21), or the
        result is neither passed nor failed; 'pass' when the result is passed otherwise."""

    def page_link(url: str | None, page: int | None) -> str | None:
        """url with any fragment removed and '#page=<page>' added; None unless both are given."""

The new migration, up (the down reverses each statement and sets the date back to 2023-08-08):

    ALTER TABLE votes ADD COLUMN IF NOT EXISTS minutes_reader TEXT;
    ALTER TABLE votes ADD COLUMN IF NOT EXISTS source_page INTEGER;
    ALTER TABLE votes ADD COLUMN IF NOT EXISTS caption TEXT;
    ALTER TABLE votes ADD COLUMN IF NOT EXISTS motion_text TEXT;
    ALTER TABLE votes ADD COLUMN IF NOT EXISTS declared_text TEXT;
    ALTER TABLE council_members ADD COLUMN IF NOT EXISTS aliases TEXT[] NOT NULL DEFAULT '{}';

    CREATE TABLE IF NOT EXISTS minutes_files (
        id                SERIAL PRIMARY KEY,
        municipality_id   INTEGER NOT NULL REFERENCES municipalities(id) ON DELETE CASCADE,
        file_id           TEXT NOT NULL,
        url               TEXT NOT NULL,
        event_external_id TEXT NOT NULL,
        status            TEXT NOT NULL CHECK (status IN ('paired', 'superseded', 'not_minutes', 'no_meeting', 'error')),
        header_date       DATE,
        meeting_id        INTEGER REFERENCES meetings(id) ON DELETE SET NULL,
        page_count        INTEGER,
        votes_stored      INTEGER NOT NULL DEFAULT 0,
        reader_version    INTEGER NOT NULL,
        attempts          INTEGER NOT NULL DEFAULT 1,
        error             TEXT,
        read_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (municipality_id, file_id)
    );
    CREATE UNIQUE INDEX IF NOT EXISTS minutes_files_one_paired_per_meeting
        ON minutes_files (meeting_id) WHERE status = 'paired';

    -- ROSTER_SQL: scoped to Mobile, found by whole-word surname as migration 049 does
    UPDATE council_members SET aliases = ARRAY['Scott'], term_end = DATE '2023-04-11'
     WHERE municipality_id = (SELECT id FROM municipalities WHERE slug = 'mobile')
       AND (name = 'Jones' OR name ILIKE '% Jones' OR name ILIKE '% Jones %');

Because of the partial unique index, a replacement sets the old row `superseded` before the new row becomes `paired`, in the same transaction.

In `src/docket/services/minutes_votes.py`:

    @dataclass
    class FileOutcome:
        file_id: str
        event_external_id: str
        header_date: date | None
        status: str
        meeting_id: int | None
        votes: int
        error: str | None

    @dataclass
    class ReadReport:
        files: list[FileOutcome]
        waiting: int                 # candidates left unread by the cap

    def reader_settings(adapter_config: dict) -> tuple[str | None, int]:
        """(reader, cap). 'minutes_reader' absent or null: (None, 0). Its only value is 'mobile'.
        'minutes_read_cap' absent or null: 10; a whole number of 0 or more otherwise.
        Raises ValueError naming the key; true and false are not whole numbers here."""

    def with_paired_links(municipality_id: int, raw_meetings: list[RawMeeting]) -> list[RawMeeting]: ...
    def read_listed(municipality_id: int, adapter, *, cap: int, dry_run: bool = False,
                    fetch_pages: Callable[[RawMinutesFile], list[str]] | None = None) -> ReadReport: ...
    def link_votes_by_code(municipality_id: int) -> int: ...
    def read_city(slug: str, *, limit: int, apply: bool) -> ReadReport:
        """The script's entry. ValueError for an unknown slug and for a city whose adapter_config names no reader."""

`link_votes_by_code` runs this one statement and returns its row count:

    INSERT INTO vote_agenda_items
        (vote_id, agenda_item_id, association_type, match_method, match_confidence, provisional, is_manual, is_active)
    SELECT v.id, min(ai.id), 'explicit', 'minutes_code', 1.0, FALSE, FALSE, TRUE
      FROM votes v
      JOIN meetings m ON m.id = v.meeting_id
      JOIN agenda_items ai ON ai.meeting_id = v.meeting_id
       AND substring(ai.title from '^(\d{2}-\d{3,4})\y') = substring(v.resolution_number from '^(\d{2}-\d{3,4})-\d{4}$')
     WHERE m.municipality_id = %s
       AND v.minutes_reader IS NOT NULL
       AND v.resolution_number IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM vote_agenda_items x WHERE x.vote_id = v.id)
     GROUP BY v.id
    HAVING count(*) = 1
    ON CONFLICT (vote_id, agenda_item_id) DO NOTHING

On `CivicClerkAdapter`:

    def listed_minutes_files(self) -> list[RawMinutesFile]:
        """The Minutes file of every event the last list_meetings listed, imported or not."""

    def fetch_file(self, url: str) -> bytes:
        """One of the city's files. Waits and retries as _get does; ValueError for an address
        outside this adapter's base; requests.RequestException after three failures or when
        the body does not begin b'%PDF-'."""

The script's output, expected, for a dry run over two files (the words after the arrow are a `FileOutcome`'s status; a paired file names its meeting's date and vote count):

    database: localhost/docket_test_5e7545f1
    file 3861 on event 500 names 2026-11-10 -> paired, 48 votes
    file 3854 on event 499 names 2026-11-03 -> paired, 40 votes
    read: 2  paired: 2  superseded: 0  not_minutes: 0  no_meeting: 0  errors: 0  votes: 88  waiting: 252
    dry run: nothing changed


Revision note, 2026-11-21 (authoring): this is the first version of the plan, written from the operator's goal and a scope brief that the plan folds into Purpose and Context instead of committing it as a file. Deliberately left out, as the brief's out-of-scope list has it: agenda items for Mobile meetings before 2024-06-25 (`D179`; votes there show under the minutes' captions with no agenda item row, item page, search card or AI summary); Vestavia Hills' votes and roster (`D182`; the reader is city-neutral in build and switched on for Mobile only, and no Vestavia Hills minutes were read); Mobile's video, YouTube, transcripts, video OCR and coming-up page, which are later stages of the operator's Mobile work; how the 83 Mobile meetings before the 2021-11-01 floor are shown (`D186`); minutes-against-video reconciliation (`D28`) and issue #162, since Mobile has one vote source; issue #190 and pull request #192, a separate fix that edits files M4 and M6 also edit; per-vote page links for Birmingham's minutes votes, whose new page column stays NULL; Birmingham's minutes parser and `D12` and `D67`; moving web or worker SQL the plan does not touch (`D7`, `D65`); and the deploy, the production migration, the backfill and the look, which are the operator's and are written out in Validation and Acceptance. Three things the brief did not have were added by the author's read of the city's files and are recorded in the Decision Log: the result rule reads the motion as well as the declaration; `D184` is paid; and 29 meetings, two mislabelled files and the download behaviour of the city's links limit what the reader will see.

Revision note, 2026-11-21 (after an outside review, before any milestone ran): the operator supplied a review of this plan and Claude, in the operator's session, checked each point against this file and the code. Seven Decision Log entries record what changed and why: no transaction is open while a file is fetched (M3, and the operator's step 4); a file that is not paired clears the meeting link that named it (M3); a pairing supersedes any other paired row every time, and a re-read under a newer version starts its attempts again (M3); `vote_tone` is neutral for `laid over` and `withdrawn` (M2, Interfaces, Expected readings); the declared head's class and the link's attributes are settled from the stylesheet (M5); `ROSTER_SQL` runs inside the `finally` of the 049 test (M2); and the debt row for the malformed code lines says what was not checked (M6). No Progress entry's text was changed. Validation clauses re-read against the changed rules: M3's "a dry run leaves every table as it was" holds (the one connection is still rolled back); "a second run with nothing new reads nothing and writes nothing" holds (no candidate, so neither pass has work); "a fetch that raises is `error` with `attempts` counted and is tried again by the next run until three" holds for a row at the current version, which is the case it seeds; the vote counts and statuses of "The reference figures" do not depend on any changed rule; the operator's look at 2024-10-22 now holds straight after step 5. Points of the review that changed nothing, with what was read: `ingest_municipality` already passes `backlog_floor` as `since` when the caller gave none (`src/docket/services/ingest.py` lines 137 to 143) and `read_city` lists from the floor, so the backlog is listed every run; `list_member_voting_history` is paged, 20 rows a page (`src/docket/services/query.py` line 864); the code join's `\y` behaves as the plan measured; code normalisation is already pinned by `test_code_without_a_colon_and_with_a_space_is_normalised`; and serving the city's PDF from docket.pub stays out, as the Decision Log's entry on the page link has it.
