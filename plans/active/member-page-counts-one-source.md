# Member page counts one source per meeting: the counting readers take the city page's rule, the history shows each row's source, and the Dissent view uses the against-the-outcome predicate with or without a date

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

docket.pub records every Birmingham City Council vote twice when it can: once from the city's minutes PDF (`votes.source = 'minutes_text'`) and once from the council video, read off the vote board by OCR (`votes.source = 'video_ocr'`). Each member's position on each motion is a `member_votes` row under its vote, and since plan `member-votes-name-their-member` a daily sweep gives every such row its `council_member_id`. The member page at `/al/<slug>/council/<id>/` (the route `member_detail` in `src/docket/web/public.py`, the template `src/docket/web/templates/member_detail.html`) prints a stat strip of attendance, alignment with the majority, and the roll-call total, and below it the member's voting history. Today its counting readers in `src/docket/services/query.py`, `get_member_stats` and `get_member_vote_summary`, select every row carrying the member's id with no condition on the source, so a meeting that holds both a minutes vote and a video vote on one motion counts that member's one position as two roll calls: on the throwaway database one such meeting printed `votes_total: 2, attendance_pct: 100` for Clinton P. Woods (`D68` in `docs/DEBT.md`). The city page's council card for the same member, built by plan `birmingham-city-briefing`, counts one source per meeting (minutes when the meeting has them, otherwise manual, then api, then video OCR; decision `0056`), so the card and the page disagree about the same person over the same meetings.

After this plan a reader notices three things. The member page without `since` prints the same roll-call count as the city page's council card over the same meetings: for one meeting that holds a `minutes_text` vote and a `video_ocr` vote on the same motion for one member, `get_member_stats` returns `votes_total 1, attendance_pct 100` (today 2), `get_member_vote_summary` returns `total 1`, and the one rule that decides this lives in one place, `briefing.chosen_source_cte` in `src/docket/services/briefing.py`, reached from `query.py` by a function-local import and written nowhere a second time. The history still lists every row, one per source, and each row shows its source in its own column in the words the meeting page already uses ("official minutes", "video OCR"), under a one-line note beneath the stat strip saying that minutes are counted where a meeting has them and video OCR otherwise; a vote flagged `needs_review` is listed and counted nowhere. And the undated Dissent filter (`?filter=dissent` with no `since`) lists what the dated view and the council card call a vote against the outcome, a no on a motion that passed or a yes on one that failed, so an abstention and a vote on a tabled motion are no longer listed as dissent (`D58` paid). The rule's reach is stated in `docs/specs/votes.md`, `docs/specs/city-page.md`, and `docs/specs/index.md`, and recorded as decision `0066`. The proof is `./tools/verify` passing with four new unit tests that fail on today's code, and the member smoke test seeing the source column and the note.

## Progress

- [x] (2026-10-21 00:13Z) M1: `get_member_stats` and the counts of `get_member_vote_summary` in `src/docket/services/query.py` take one source per meeting through `briefing.chosen_source_cte` by a function-local import, the undated Dissent filter of `list_member_voting_history` is `AGAINST_OUTCOME_PREDICATE`, four new unit tests in `tests/unit/test_query_member_history.py` fail before the change and pass after, the three assertions that pinned the old behaviour are updated, decision `0066` is written, `D58` is deleted, and decisions `0056` and `0057` cite the paid row
- [x] (2026-10-21 00:24Z) M2: `member_detail.html` shows each history row's source in its own column ("official minutes" or "video OCR") sized in `layout.css` and wrapped on phones in `mobile.css`, one line under the stat strip says minutes are counted where a meeting has them and video OCR otherwise, and the member smoke test in `tests/web/test_new_routes_p4.py` seeds one meeting with one vote and sees the column and the note
- [ ] M3: `docs/specs/votes.md` states the member page's counting rule in Two sources and corrects the sentence in When resolution runs, `docs/specs/city-page.md` line 53 and the `votes.md` row of `docs/specs/index.md` follow, `D68` is deleted, and `D66` notes that its one-time sweep may now run

## Surprises & Discoveries

- Observation: nothing has been executed yet; this section holds what the authoring research found that the goal and the brief did not say.
  Evidence: authoring session, 2026-10-20, in the worktree `.claude/worktrees/member-page-counts-one-source` cut from `origin/main` at `2a322fd` (the merge of pull request #128).
- Observation: the worktree was cut without the gitignored `.env` that `D57` says every worktree on this machine needs, so `tools/test-db` failed with `permission denied to create database` under the default URL in `src/docket/config.py` (the local `docket` role has no CREATEDB: `pg_roles` printed `docket|f|f`). The author wrote `.env` with the one line `DATABASE_URL=postgresql://thinkdarrell@/docket_db`, after which the build succeeded; `git status --porcelain` printed nothing, because `.gitignore` line 8 is `.env`. Every milestone session depends on that file; Concrete Steps says how to recreate it.
  Evidence: `tools/test-db` printed `ERROR:  permission denied to create database` and exited 1 before the file existed; with it, `test-db exit 0` and `All migrations applied.`
- Observation: the throwaway database holds no votes at all (`SELECT count(*) FROM votes` and `FROM member_votes` both printed `0`), so the rule cannot be measured on local rows; the production distribution it will run on is the operator's to read (Concrete Steps, Operator step), and the plan's tests seed the shapes by hand, which proves the seed, not the writer.
  Evidence: `psql "$URL" -Atc ...` on `docket_test_b3b359fd` after `tools/test-db`, 2026-10-20; the first municipality is `1|birmingham` and its first members are `1|Clinton P. Woods|t`, `2|Hunter Williams|t`, `3|Josh Vasa|t`.
- Observation: the baseline the acceptance counts from. `venv/bin/python -m pytest tests/unit/test_query_member_history.py tests/web/test_new_routes_p4.py tests/unit/test_query_hidden_meetings.py -q -p no:cacheprovider` with `DATABASE_URL` exported at the throwaway database printed `38 passed in 1.57s` (ten, ten, and eighteen tests); `tests/web/test_city_briefing.py tests/services/test_briefing_facts.py` printed `79 passed in 9.14s`, and each file alone `58 passed` and `21 passed`.
  Evidence: the two runs above, 2026-10-20, then `tools/test-db --drop`.
- Observation: `tests/integration/test_transcript_pipeline.py` line 194 opens a docstring with `D58:` meaning a transcript row state, not the member page's Dissent filter; it is a leftover from before the register was renumbered and is not touched by this plan, so a grep for `D58` across `tests/` still prints that line after M1.
  Evidence: `grep -rn 'D58' ...` at authoring printed that line among the six real citations.
- Observation (M1 session, 2026-10-21): the M1 acceptance check `grep -n 'D58' src/docket/services/query.py tests/unit/test_query_member_history.py tests/web/test_city_briefing.py docs/DEBT.md` does not print nothing after the `D58` row is deleted: it prints one line, the `D70` row of `docs/DEBT.md`, whose text says pull request #128 "spends rows D58 to D65". That is a true historical statement about a numbering collision, not a citation of the paid debt, and `D70` is outside this milestone, so it was left alone. The stricter check `grep -n '^| D58 ' docs/DEBT.md` prints nothing; the other three files print nothing under the original grep. Recorded as a carve-out against the M1 acceptance clause in Validation and Acceptance.
  Evidence: the two greps, run in the worktree after the `docs/DEBT.md` edit, 2026-10-21, shortly before the 00:13Z tick.
- Observation (M1 session): the fixture `member_with_both_sources_one_meeting` needs a second vote on the meeting `_add_vote_meeting` created, and the plan's helper signature inserts one meeting with one vote; a second small helper, `_add_vote_to_meeting(meeting_id, member_id, *, source, result, position) -> int`, was added to the test file for the video row. Decision Log has the entry.
  Evidence: `tests/unit/test_query_member_history.py`, the two helpers above the fixture.
- Observation (M1 session): the first run of the unit file against the finished code printed `14 passed, 1 warning in 0.39s` under `-q`; the rerun without `-q`, piped through `grep -i -A8 'warnings summary'`, printed nothing, and `./tools/verify` passed, so the warning's text was not captured. Noted, not chased: it did not recur and no test failed.
  Evidence: the two runs on `docket_test_b3b359fd`, 2026-10-21.
- Observation (M2 session, 2026-10-21): the failing-before run was obtained without a stash: `git diff -- src` was saved to a patch file in the session scratchpad, `git checkout -- src` reverted the page, the test file (already edited) ran, and `git apply` restored the three `src/` files; `git diff --stat` afterwards listed the same four files with the same line counts as before the revert. The new test failed on its first assertion, the source column, which is the expected shape: the unchanged page has neither the column nor the note.
  Evidence: `1 failed, 10 passed in 0.72s`, with `FAILED tests/web/test_new_routes_p4.py::test_member_detail_shows_source_column_and_count_note` and `E       assert 'class="member-history-source t-meta">official minutes<' in '<!DOCTYPE html>...'`.
- Observation (M2 session): the stat strip's sub-line reads `1 roll calls` for one roll call, the plural the existing `partials/num_stat.html` call in the template has always printed (`sub=(stats.votes_total ~ ' roll calls')`), and the plan's acceptance asserts that exact text. Left as it is: the wording predates this plan and changing it is outside the milestone.
  Evidence: the body assertion `"1 roll calls" in body` passed in the `11 passed` run.
- Observation (M2 session): the `1 warning` the first verify tier prints (M1 saw it too and did not capture it) is `PytestRemovedIn10Warning: Class-scoped fixture defined as instance method is deprecated.` from `tests/unit/test_engagement_strip.py::TestCardPartialCityAlias::test_engagement_strip_without_city_silently_degrades`, a file this plan does not touch; the integration tier separately prints `PytestUnknownMarkWarning: Unknown pytest.mark.integration` from `tests/integration/test_vote_matcher_v2_integration.py:19`. Both predate this plan and are left alone.
  Evidence: the closing `./tools/verify` log of the M2 session, its two `warnings summary` blocks.
- Observation (M2 session): the M2 tick was stamped `00:24Z` while the clock read `2026-10-21 00:23Z` when the tick commit was made (`date -u` printed in the same command); the stamp is one minute ahead and is left as written because a Progress line's text is not reworded once written.
  Evidence: the output of the tick command, 2026-10-21.
- Observation (M3 session, 2026-10-21): after the `D68` row is deleted, one citation of `D68` remains outside this plan, in the Rationale of decision `0066` ("(`D68` in `docs/DEBT.md`, observed on the throwaway database as ...)"), the record M1 wrote verbatim from Artifacts and Notes; M3's named edits do not include `0066`. A check of every `docs/decisions/0*.md` against the live rows of `docs/DEBT.md` found the same shape already in the register before this plan: `0049` cites `D55` and `0052` cites `D15`, both rows deleted and never repaired, so a paid row cited from the rationale that paid it is the register's existing state, not a reference this plan broke. Left as written; Decision Log has the entry.
  Evidence: `grep -rn 'D68' docs src tests plans/active` minus this plan printed the one `0066` line; the per-record check against `grep -o '^| D[0-9]*' docs/DEBT.md` (56 live rows) listed `0049`/`D55`, `0052`/`D15`, `0050`/`D58`, `0056`/`D58`, `0057`/`D58`, `0066`/`D58`, `0066`/`D68`.
- Observation (M3 session): all eight M3 acceptance greps printed what Validation and Acceptance asks on the first run, and `git diff --stat HEAD -- src` printed nothing, so M3 changed no file under `src/`; `git diff --stat origin/main -- src` lists only the four files M1 and M2 changed (`query.py`, `layout.css`, `mobile.css`, `member_detail.html`).
  Evidence: the grep transcript under Artifacts and Notes, 2026-10-21 00:28Z.

## Decision Log

- Decision: the counting readers reach the per-meeting rule through `briefing.chosen_source_cte` (decision `0056`) by a function-local import inside one private helper in `query.py`, `_member_source_with`, which the dated branch of `list_member_voting_history` also uses; the rule's `CASE` is not written in `query.py`.
  Rationale: the operator asked for one owner of the rule and for the fragment to be reached the way pull request #128 already does (`query.py` line 809 today), because `briefing` imports `query` at module level and a module-level import the other way would be circular. The helper exists so the scope condition (the member's non-hidden meetings, optionally on or after a date) is written once instead of three times; it is not a second owner of the rule, since it only passes a scope to the fragment.
  Date/Author: 2026-10-20, plan author (Claude, under `cycle-plan`), from the operator's goal.
- Decision: `D58` is paid, not left: the undated Dissent filter routes through `AGAINST_OUTCOME_PREDICATE` exactly as the dated filter does (one predicate swap at `query.py` lines 793 to 801 today), and the three assertions that pinned the old behaviour change (`tests/unit/test_query_member_history.py` last line `== 6` becomes `== 4`; `tests/web/test_city_briefing.py` line 812 `== 2` becomes `== 0`; the comment at `query.py` line 757 and the two docstrings follow).
  Rationale: the operator preferred paying it when it is one predicate swap covered by one test, which it is. After M1 the stat strip counts under the city page's rule; leaving the list under a second, broader definition of dissent would put two definitions of one word on one page, with the strip and the list disagreeing about the same member. The only cost is that an abstention and a vote on a tabled motion leave the undated Dissent view, which is what decision `0057` already says they are: roll calls attended, not votes against an outcome.
  Date/Author: 2026-10-20, plan author.
- Decision: the rule is applied to the counts only. `list_member_voting_history` without `since` and the `recent` list of `get_member_vote_summary` keep listing every row carrying the member's id, flagged rows included, and the page distinguishes them by a source column instead of hiding one.
  Rationale: the operator said so, and `docs/PRINCIPLES.md` (Keep the sources apart) wants a disagreement shown, not resolved by code; a history that hid the video row on a meeting the minutes cover would silently drop what the video recorded. The dated history (`since` given) stays under the rule as plan `birmingham-city-briefing` M4 built it, because it exists so the council card's number and the door it opens agree.
  Date/Author: 2026-10-20, plan author.
- Decision: the rule is per meeting, not per motion, and `D28` (source reconciliation) is cited from `docs/specs/votes.md` as the reconciliation that stays unbuilt; nothing in this plan decides which of two readings of one motion is right.
  Rationale: choosing per motion would need the reconciliation `D28` defers and would mix the two sources inside one number; per meeting, minutes first, is the smallest rule that yields one number without adjudicating, and it is the rule the card already counts under.
  Date/Author: 2026-10-20, plan author, from the operator's goal.
- Decision: decision `0066` is written in M1, the milestone that lands both halves of the rule it records, and `D58` is deleted in that same milestone with the citations in `0056` and `0057` repaired in place to name the plan and the record; `D68` is deleted in M3, when the spec its trigger asks for exists.
  Rationale: a citation that dangles for two sessions protects nothing (`docs/decisions/DECISION_FORMAT.md`, Superseding), so the row, the record that replaces it, and the repair land together; `D68`'s trigger names the spec statement as part of paying it, so its row outlives M1 and M2 on this branch, and the plan says so here rather than letting a reader think the row was forgotten. `0066` is unspent on `origin/main` (whose last record is `0065`) and `gh pr list --state open` printed nothing on 2026-10-20, the check `D70` asks for.
  Date/Author: 2026-10-20, plan author.
- Decision: the production distribution the rule will run on is not measured by this plan beyond the counts the operator supplied in the goal and `D68` (the twelve months to 2026-10-20 hold 2680 minutes member votes and 1814 video ones); the exact read-only queries are under Concrete Steps, Operator step, for the operator to run before merge.
  Rationale: the factory worktree has no production connection and the local throwaway database holds no votes (Surprises). The design assumes `votes.source` holds only `minutes_text` and `video_ocr` on production, which the fragment's `CASE` tolerates either way, and that a non-empty set of meetings holds both sources, which is why the double count matters. A result that breaks either assumption is a Surprises entry and a decision, not a silent fix.
  Date/Author: 2026-10-20, plan author.
- Decision: the source column's wording is the meeting page's binary mapping (`video_ocr` is "video OCR", everything else "official minutes", `meeting_detail.html` lines 157 to 160), and no "needs review" marker is added to the history rows.
  Rationale: the operator asked for the meeting page's wording; a `manual` or `api` vote has no producer today (migration 001 allows the values, nothing writes them), and inventing a third label would be a word no page uses. A review marker is an extension the goal does not ask for; the meeting page, which the row links to, shows the "Needs review" callout.
  Date/Author: 2026-10-20, plan author.
- Decision: on phones (the `max-width: 768px` layer in `mobile.css`) the source column drops under the row's body by `order: 1; grid-column: 2 / -1` instead of staying a fourth column.
  Rationale: the desktop grid `110px 1fr auto auto` leaves about 13 px for the title on a 375 px screen once the date, the source, and the position chip take theirs; the `order` property moves the source last in auto-placement so the position chip keeps its place beside the title and the source wraps beneath, with no change to the markup.
  Date/Author: 2026-10-20, plan author.
- Decision: the M1 test file gains a second helper, `_add_vote_to_meeting`, beside the planned `_add_vote_meeting`, to put the `video_ocr` row on meeting X; the planned helper's signature is kept as written.
  Rationale: the plan's `_add_vote_meeting` inserts one meeting with one vote, and the fixture needs two votes on one meeting; widening the planned helper to take an optional existing meeting id would change the signature the plan spent, while inlining the second insert in the fixture would repeat the insert the helper exists to own. A second helper is the smallest resolution inside the milestone's boundary.
  Date/Author: 2026-10-21, M1 session (Claude, under `cycle-run`).
- Decision: the `D70` row is not edited to make the M1 grep for `D58` print nothing; the carve-out is recorded instead (Surprises & Discoveries, Progress).
  Rationale: `D70` records that pull request #128 spent rows `D58` to `D65`, which stays true after `D58` is paid, and rewording a debt row this plan does not name would be scope the milestone does not have (`skills/plan-execute/SKILL.md`, Never). The acceptance's intent, that nothing cites the paid row as live debt, is met: the `D58` row is gone and the three code and test files print nothing.
  Date/Author: 2026-10-21, M1 session.
- Decision: decision `0066` keeps its citation of `D68` unrepaired after M3 deletes the row.
  Rationale: `0066` is the record that pays `D68`, and its Rationale cites the row as the problem it describes in the past tense; `docs/decisions/DECISION_FORMAT.md` allows repairing a reference in place, but M3's work names four documents and two debt edits and not `0066`, and the register already holds two records (`0049` on `D55`, `0052` on `D15`) that cite deleted rows the same way, so the citation follows the repository's existing convention for paid debt and widening the milestone to repair it would be scope the session does not have. A reader who follows the citation finds the row's text in the `D68` description that `0066` itself summarises and in this plan's Context and Orientation.
  Date/Author: 2026-10-21, M3 session (Claude, under `cycle-run`).
- Decision: the sentence M3 adds to Tests that pin this in `docs/specs/votes.md` is appended to the section's one existing paragraph, after the sentence about `tests/integration/test_video_ocr_persistence.py`, not as a paragraph of its own.
  Rationale: Plan of Work says "add to Tests that pin this the sentence given there" without placing it; the section is one paragraph listing the tests that pin the spec, and a second paragraph for two files would separate the member-page tests from the list they belong to.
  Date/Author: 2026-10-21, M3 session.

## Outcomes & Retrospective

Written at the end of M3, 2026-10-21, the last milestone; the entries before this paragraph were the authoring placeholder and are kept as history.

Against the purpose: the member page's counting readers (`get_member_stats`, the counts of `get_member_vote_summary`) and the dated history reach the per-meeting rule through `briefing.chosen_source_cte` by one function-local import in one helper, and `grep -n 'CASE WHEN bool_or' src/docket/services/query.py` prints nothing, so the rule has one owner (M1). A meeting holding a minutes vote and a video vote on one motion counts one roll call and lists two rows, pinned by `tests/unit/test_query_member_history.py` (M1). The page shows each row's source in its own column in the meeting page's words and says under the stat strip what is counted, pinned by `tests/web/test_new_routes_p4.py` (M2). The undated Dissent view is `AGAINST_OUTCOME_PREDICATE`, so an abstention and a vote on a tabled motion leave it (M1). `D58` and `D68` are deleted, `D66` says its sweep may now run, decision `0066` records the rule, and `docs/specs/votes.md`, `docs/specs/city-page.md`, and `docs/specs/index.md` state its reach (M1, M3). Every `./tools/verify` in the three sessions passed all six checks.

What remains is outside any milestone session: the operator's two read-only production queries under Concrete Steps, Operator step, whose results are owed to Surprises & Discoveries on this branch before merge; the post-deploy comparison of one member's roll-call total with the council card's; and the close of the plan (move to `plans/completed/`), which the factory's close step does. The dangling `D68` citation in `0066` is recorded in the Decision Log and left under the register's existing convention.

Lessons: the three carve-outs the plan met (`D70`'s historical mention of `D58`, the `1 roll calls` plural, `0066`'s citation of `D68`) were all cases where a grep-shaped acceptance met text whose meaning the author had not read against the grep; a plan that deletes a debt row should list, at authoring, every file that cites it and say for each whether it is repaired or left. Reverting `src/` by patch for one run (M2) gave a failing-before result without a shared stash and is worth reusing.

## Context and Orientation

The repository is a Flask application over PostgreSQL. Web routes under `src/docket/web/` call read functions in `src/docket/services/query.py` and render Jinja templates under `src/docket/web/templates/`; the stylesheet is `src/docket/web/static/layout.css` with a phone layer in `src/docket/web/static/mobile.css` (one breakpoint, `@media (max-width: 768px)`, the block that starts at line 609 holds the KPI strip rule at lines 628 to 641). Nothing in `src/docket/web/` executes SQL. `./tools/verify` is the one check command: it builds a throwaway database `docket_test_<hash>` from the migrations, runs every non-live test tier against it, then four more checks, prints one summary line per check, and drops the database; it takes about 150 seconds and ends `verify: all 6 checks passed in <N>s.` A single test file is run the same way, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest <file> -q -p no:cacheprovider; tools/test-db --drop`, because `tests/conftest.py` refuses any database not named `docket_test_*` before collection (a bare `pytest` in this worktree exits 2 with `tests: refusing to run against database ''`, observed at authoring).

The tables. A `votes` row is one motion of one meeting: `meeting_id`, `source` (`minutes_text`, `video_ocr`, `api`, or `manual`; migration 001 line 124), `result` (`passed`, `failed`, `tabled`, or `unknown`), the counts `yeas`, `nays`, `abstentions`, `confidence`, and `needs_review`, true when the OCR pipeline could not trust what it read ("flagged", below). A `member_votes` row is one member's position on one vote: `vote_id`, `member_name` as the source printed it, `position` (`yea`, `nay`, `abstain`, `absent` from the minutes; `yes`, `no`, `abstain`, `absent` from the video), and `council_member_id`, NULL until resolved. A `meetings` row carries `is_hidden`, and every public reader excludes hidden meetings. A meeting that both the minutes parser and the video OCR covered holds two sets of `votes` rows, one per source, and the two are never merged (decision `0005`, `docs/specs/votes.md` Two sources).

The rule and its owner. `chosen_source_cte(scope)` in `src/docket/services/briefing.py` (lines 136 to 158) returns the body of a CTE, a named subquery introduced by `WITH`, called `meeting_vote_source`, with one row per meeting naming its `chosen_source`: `minutes_text` when the meeting has any vote from the minutes with `needs_review` false, otherwise `manual`, then `api`, then `video_ocr`. `scope` is a SQL condition on `v.meeting_id` the caller supplies so the aggregate never groups votes outside the meetings the query is about (decision `0056` says why); its parameters come first in the caller's parameter list. A caller writes `"WITH " + chosen_source_cte(scope)` and then joins `meeting_vote_source s ON s.meeting_id = v.meeting_id AND s.chosen_source = v.source AND v.needs_review = FALSE`, which keeps only the votes of each meeting's chosen source and drops flagged votes. `briefing.py` imports `AGAINST_OUTCOME_PREDICATE`, `CANCELLED_PREDICATE_MT`, and `_UPCOMING_PREDICATE_MT` from `query.py` at module level (lines 34 to 38), so `query.py` cannot import `briefing` at module level; the dated branch of `list_member_voting_history` imports `chosen_source_cte` inside the function (line 809, with the comment "Imported here: briefing imports this module at import time"), and that is the pattern this plan reuses. The city page's council card gets its numbers from `_MEMBER_COUNTS_SQL` (`briefing.py` lines 231 to 250), which joins through that CTE and counts `against` with `AGAINST_OUTCOME_PREDICATE`.

The readers this plan changes, all in `src/docket/services/query.py`. `get_member_stats(member_id)` (line 662) runs one `SELECT` over `member_votes mv JOIN votes v JOIN meetings m WHERE mv.council_member_id = %s AND m.is_hidden = FALSE` and returns `{votes_total, attendance_pct, alignment_pct}`, where attendance is the share of rows with a position other than `absent` and alignment the share of present rows whose position agrees with the result (yea on passed, nay on failed); both percentages are `None` when nothing was counted. `AGAINST_OUTCOME_PREDICATE` (line 758) is the string `((mv.position IN ('yea','yes') AND v.result = 'failed') OR (mv.position IN ('nay','no') AND v.result = 'passed'))`, "voted against the outcome" (decision `0057`); the comment above it, line 757, says the undated Dissent view keeps its older filter. `list_member_voting_history(member_id, *, cursor, limit, filter_mode, since)` (line 764) is the cursor-paginated history: with `filter_mode == "dissent"` and `since` it adds `AND <AGAINST_OUTCOME_PREDICATE>` (line 793); with `filter_mode == "dissent"` and no `since` it adds the older filter at lines 794 to 801, every present position not aligned with the result, which lists an abstention and any present vote on a tabled motion as dissent (`D58`); with `since` it builds the CTE scoped to the member's non-hidden meetings on or after the date (lines 809 to 822) and joins through it. Its rows carry `vote_id, result, source, yeas, nays, position` (folded to `yea`, `nay`, or the stored word), `meeting_id, meeting_date, meeting_title`, and `agenda_links`. `get_member_vote_summary(member_id)` (line 946) runs a `GROUP BY` of positions over the same unscoped predicate, then a `recent` list of the twenty newest rows, and returns `{total, yea, nay, abstain, absent, recent}`; it has no caller in `src/` today (`grep -rn get_member_vote_summary src` prints only its definition) and the operator said to keep it, so its counts get the rule and it gains a direct test.

The page. `member_detail` in `src/docket/web/public.py` (line 897) reads `filter` (`all`, `dissent`, `sponsored`; anything else is `all`) and `since` (ISO date; malformed ignored), calls `get_member_stats`, `count_sponsored_items_for_member`, and either `list_sponsored_items_for_member` or `list_member_voting_history`, and renders `member_detail.html`, caching the first page per `(slug, member_id, filter_mode, since)` for `_CACHE_TTL`. In the template, the hero section (lines 15 to 52) ends with `<div class="kpi-strip">` of three `partials/num_stat.html` cards (Attendance with sub `<n> roll calls`, Alignment with majority, Items sponsored); the filter chips follow (lines 56 to 68) with the sentence "Showing votes since <date>, one source per meeting." when `since` is set; the history section (lines 71 to 140) renders vote rows as `<a class="member-history-row vote-row">` with three children, `.member-history-date`, `.member-history-body` (title and the `<yeas>–<nays> · <result>` line), and the position chip `<span class="chip chip-<position>">`, and sponsored rows as `<a class="member-history-row">` with two or three children. `layout.css` line 172 sets `.member-history-row { display: grid; grid-template-columns: 110px 1fr auto; gap: 16px; ... }`; `.member-since` is at line 1418 among the `brf-` rules. The meeting page, `src/docket/web/templates/meeting_detail.html` lines 157 to 160, labels a vote `video OCR · <confidence>` when `vote.source == 'video_ocr'` and `official minutes · <confidence>` otherwise; this plan borrows the two phrases without the confidence.

The tests. `tests/unit/test_query_member_history.py` (ten tests) has two fixtures that seed under the prefix `TEST_MH_` on the first municipality (`SELECT id FROM municipalities ORDER BY id LIMIT 1`, which is Birmingham, id 1, on the throwaway database) and clean up by that prefix: `member_with_history` (three meetings, three minutes votes) and `member_with_two_sources` (meetings A, B, C with the mix its docstring at lines 135 to 143 describes). Its last test, `test_voting_history_since_dissent_excludes_abstentions_and_tabled`, adds meeting D with a tabled yea and an abstention and ends `assert len(page["rows"]) == 6` for the undated Dissent view; line 191 asserts `== 4` for the same view before D exists, and that number does not change under the new predicate (A's yea on failed, B's video yea on failed, C's video yea on failed, and C's flagged minutes yea on failed are each a yes on a motion that failed; B's minutes yea on passed is not). `tests/web/test_new_routes_p4.py` (ten tests) seeds two cities `p4test_alpha` and `p4test_beta` with one member each (`TEST_P4_Alpha Member`, `TEST_P4_Beta Member`) and no meetings or votes; its `_cleanup` deletes members by name and cities by slug, and because `meetings.municipality_id` references `municipalities` without `ON DELETE CASCADE` (migration 001 line 32) while `votes` and `member_votes` cascade from `meetings`, a seeded meeting must be deleted before its city. `tests/web/test_city_briefing.py` line 446 onward renders the real Birmingham seed of `tests/support/briefing_seed.py`: the past meeting holds a split minutes vote (Hunter Williams nay), a unanimous one (Clinton P. Woods absent), and a review-flagged `video_ocr` vote that passed 6 to 3 on which the roster's third, fourth, and fifth members (`names[2:5]`) voted no; `test_council_card_links_dissent_since_and_member_page_matches_count` asserts at its end that `names[3]`'s undated Dissent view has one row (that flagged no on a motion that passed, which the new predicate also matches because the history lists flagged rows), and `test_council_card_count_matches_dated_dissent_view_with_abstention_and_tabled` asserts at line 812 that the abstainer's undated view has two rows, the abstention and the tabled yea, which the new predicate excludes. `tests/unit/test_query_hidden_meetings.py` line 394 seeds a vote with `source = 'test'` on a hidden meeting and compares `get_member_stats` before and after; hidden meetings are outside the scope either way, so it needs no edit. `tests/services/test_briefing_facts.py` is read for its `_add_tabled_and_abstention_votes` twin and not changed.

The documents. `docs/specs/votes.md` describes the two sources, the resolution rule, and the OCR review reasons; its Two sources section ends with the sentence that the two sources are never merged, and its When resolution runs section ends with the sentence "The member pages at `/al/birmingham/members/<id>/` (attendance, alignment, voting history) count only rows that carry that member's id, so a row joins a member's page the moment it resolves.", wrong in its path (the route is `/al/<slug>/council/<id>/`) and, after M1, in its claim. `docs/specs/city-page.md` line 53 describes the `since` parameter and ends "Without `since` the page behaves as before, its undated Dissent filter included (`D58` in `docs/DEBT.md`)." `docs/specs/index.md` lists each spec in a table whose `votes.md` row names what it covers. `docs/DEBT.md` is a register table with rows `D58` (line 53), `D66` (line 60), `D68` (line 62), and `D70` (line 64); `D28` (line 27) is source reconciliation, not built. `docs/decisions/0056-...md` says in its Rationale "The undated member page predates the rule and keeps its own filter (`D58` in `docs/DEBT.md`)." and `docs/decisions/0057-...md` says "The undated Dissent view keeps its older, broader filter (`D58`) because the design excludes the member page beyond `since`, and the dated view exists so the card's number and the door it opens agree."; `docs/decisions/DECISION_FORMAT.md` allows a reference that stopped resolving to be repaired in place without changing a word of the argument. The last record is `0065`; `0066` is free.

Terms. "Chosen source": the one `votes.source` the rule names for a meeting. "Flagged": a `votes` row with `needs_review` true. "Roll call": one `member_votes` row that counts. "The stat strip": the `kpi-strip` block of three cards at the top of the member page. "Function-local import": an `import` statement inside a function body, run when the function is called, used to break the import cycle between `briefing.py` and `query.py`.

## Plan of Work

M1, the readers. In `src/docket/services/query.py`, immediately above `def get_member_stats`, add a private helper and a private constant (exact text in Interfaces and Dependencies): `_member_source_with(where_since: str = "") -> str` does the function-local import of `chosen_source_cte` and returns `"WITH " + chosen_source_cte(<scope>)` where the scope is the member's non-hidden meetings, `v.meeting_id IN (SELECT m2.id FROM meetings m2 JOIN votes v2 ON v2.meeting_id = m2.id JOIN member_votes mv2 ON mv2.vote_id = v2.id WHERE mv2.council_member_id = %s<where_since> AND m2.is_hidden = FALSE)`; `_CHOSEN_SOURCE_JOIN` is the join through `meeting_vote_source` with `v.needs_review = FALSE`. Rewrite the `SELECT` of `get_member_stats` to start with `{_member_source_with()}` and to place `{_CHOSEN_SOURCE_JOIN}` between `JOIN votes v` and `JOIN meetings m`, passing `(member_id, member_id)`; the three `COUNT` expressions and the returned dict do not change. Do the same to the first query of `get_member_vote_summary` (the `GROUP BY pos` one), passing `(member_id, member_id)`; leave its `recent` query and the links query as they are. In `list_member_voting_history`, collapse the two `dissent` branches into one, `where_filter = f"AND {AGAINST_OUTCOME_PREDICATE}"` whenever `filter_mode == "dissent"`, and in the `since` branch replace the inline `with_clause` and `source_join` with `_member_source_with(" AND m2.meeting_date >= %s")` and `_CHOSEN_SOURCE_JOIN` (the parameter order, member id then date, is unchanged). Reword the comment block above `AGAINST_OUTCOME_PREDICATE` so it names the member page's Dissent view "with or without `since`" and drops the sentence about `D58`; reword the `since` paragraph of the history docstring so it says that without `since` the history lists every row of every source and the Dissent filter is the same predicate; add one sentence to the `get_member_stats` docstring and one to `get_member_vote_summary`'s saying the counts take one source per meeting through `briefing.chosen_source_cte` with flagged votes excluded, and that `recent` lists every row. `grep -n 'CASE WHEN bool_or' src/docket/services/query.py` must print nothing afterwards: the rule is not copied.

M1, the tests. In `tests/unit/test_query_member_history.py`, import `get_member_vote_summary` beside the others; add a helper `_add_vote_meeting(muni_id, member_id, label, mdate, *, source, result, position, needs_review=False) -> int` that inserts one `TEST_MH_<label>` council meeting, one vote of that source with `yeas 5, nays 0, abstentions 0, confidence 'high'`, and one member vote, committing, and a fixture `member_with_both_sources_one_meeting` that creates member `TEST_MH_Lee` and meeting `X` (2099-05-01) holding a `minutes_text` vote `passed` with position `yea` and a `video_ocr` vote `passed` with position `yes`, yielding `{"member_id", "muni_id"}`; then the four tests in Validation and Acceptance. Change the last assertion of `test_voting_history_since_dissent_excludes_abstentions_and_tabled` from `== 6` to `== 4` and its docstring and the comment above the assertion to say both views exclude them; reword the comment at line 189 ("every vote, as the page always behaved") to say the history lists every row and four are against an outcome. In `tests/web/test_city_briefing.py`, change line 812 from `== 2` to `== 0` and reword the comment on line 811 to say the undated view, under the same predicate, counts none; reword the comment at line 471 ("behaves as it always did: every vote") to say the history lists every row, the flagged video vote included, so the predicate finds that no on a motion that passed. Leave `_add_tabled_and_abstention_votes` in both that file and `tests/services/test_briefing_facts.py` alone: their constraint on which member abstains is still needed, because the flagged video vote is still listed.

M1, the records. Write `docs/decisions/0066-the-member-page-counts-one-vote-source-per-meeting-through-the-city-pages-fragment.md` with the text in Artifacts and Notes. In `docs/DEBT.md`, delete the `D58` row (the whole table line). In `docs/decisions/0056-...md`, change the parenthetical `(`D58` in `docs/DEBT.md`)` to `(`D58` in `docs/DEBT.md`, paid by plan `member-page-counts-one-source`; decision `0066`)` and nothing else; in `docs/decisions/0057-...md`, change `(`D58`)` to `(`D58`, paid by plan `member-page-counts-one-source`; decision `0066`)` and nothing else.

M2, the page. In `member_detail.html`, inside the vote-row branch (the `<a class="member-history-row vote-row">`), insert between the closing `</div>` of `.member-history-body` and the position chip one element, `<span class="member-history-source t-meta">{{ 'video OCR' if row.source == 'video_ocr' else 'official minutes' }}</span>`; the sponsored branch is untouched. After the closing `</div>` of `.kpi-strip` and before the hero's `</section>`, add `<p class="t-meta member-count-note">Counted from the official minutes where a meeting has them and from video OCR otherwise; a vote flagged for review is listed below but not counted.</p>`, rendered always (it states the rule, not a count). In `layout.css`, directly after the `.member-history-row` rule (line 178's closing brace), add `.member-history-row.vote-row { grid-template-columns: 110px 1fr auto auto; }` and `.member-history-source { color: var(--ink-3); font-size: 11px; white-space: nowrap; }`; next to `.member-since` (line 1418) add `.member-count-note { margin: 0; max-width: 68ch; }`. In `mobile.css`, inside the `@media (max-width: 768px)` block that holds the KPI strip rule (after line 641's closing brace), add `.member-history-row.vote-row { grid-template-columns: 110px 1fr auto; }` and `.member-history-source { order: 1; grid-column: 2 / -1; white-space: normal; }`.

M2, the test. In `tests/web/test_new_routes_p4.py`, make `_cleanup` first run `DELETE FROM meetings WHERE title LIKE 'TEST_P4_%'` (votes and member votes cascade), then the two existing deletes. Add a helper `_seed_one_vote(fx) -> int` that inserts into the alpha city one council meeting `TEST_P4_meeting` dated 2099-01-01, one `minutes_text` vote `passed` 1 to 0 (`abstentions 0, confidence 'high', needs_review FALSE`), and one member vote for `alpha_member_id` with position `yea`, committing and returning the meeting id; and the test `test_member_detail_shows_source_column_and_count_note` in Validation and Acceptance. The existing tests are unchanged.

M3, the documents. In `docs/specs/votes.md`, append to Two sources the paragraph in Artifacts and Notes (the rule's reach, per meeting not per motion, `D28` cited, the history's two rows and the source column, the note, the Dissent predicate), replace the last sentence of When resolution runs with the one given there, and add to Tests that pin this the sentence given there. In `docs/specs/city-page.md`, replace the last sentence of line 53 with the one given there. In `docs/specs/index.md`, extend the `votes.md` row's second cell with the clause given there. In `docs/DEBT.md`, delete the `D68` row, and append to the Item cell of `D66` the clause given there. Nothing in `src/` changes in M3.

## Concrete Steps

Every command runs from the worktree root, `/home/thinkdarrell/docket-pub/.claude/worktrees/member-page-counts-one-source`, on branch `plan/member-page-counts-one-source`, with this checkout's own `venv/`. The milestone session's first and last commands are `./tools/verify`; its last line is recorded in the plan. Every commit in a milestone session changes this plan file (decision `0037`), and the pre-commit hook in `tools/hooks/` (active: `git config core.hooksPath` prints `tools/hooks`) checks the staged plan.

Before anything: `ls .env` must print `.env`. If it does not (a fresh clone, or the file was removed), write it with one line, `DATABASE_URL=postgresql://thinkdarrell@/docket_db`, the peer-authenticated superuser URL `D57` describes for this machine; it is gitignored. Without it `tools/test-db` exits 1 with `permission denied to create database` and `./tools/verify` runs no tier.

Run one test file:

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_query_member_history.py -q -p no:cacheprovider; tools/test-db --drop

At authoring, the three files `tests/unit/test_query_member_history.py tests/web/test_new_routes_p4.py tests/unit/test_query_hidden_meetings.py` run this way printed `38 passed in 1.57s`.

M1 order: run `./tools/verify` (expect `verify: all 6 checks passed`); write the new tests and the assertion changes first and run the unit file, recording the failing summary (expected: the four new tests and the `== 4` assertion fail, `5 failed, 9 passed`); make the `query.py` changes; run the unit file again (expected `14 passed`); run `tests/web/test_city_briefing.py` (expected `58 passed` after its one assertion change; the file alone printed `58 passed in 8.27s` at authoring, and `tests/services/test_briefing_facts.py` alone `21 passed in 0.36s`); write `0066`, delete `D58`, repair `0056` and `0057`; run `./tools/verify`; tick M1 with the observed time; commit.

M1 as run (2026-10-21, one session): `./tools/verify` before any edit printed `verify: all 6 checks passed in 102s.`; the unit file with the new tests against the unchanged `query.py` printed `5 failed, 9 passed in 0.35s` (the four new tests and `test_voting_history_since_dissent_excludes_abstentions_and_tabled`); after the `query.py` edit the unit file printed `14 passed, 1 warning in 0.39s`, `tests/web/test_city_briefing.py` printed `58 passed in 8.71s`, and `tests/services/test_briefing_facts.py tests/unit/test_query_hidden_meetings.py tests/web/test_new_routes_p4.py` together printed `49 passed in 1.45s`; after the records, `./tools/verify` printed `verify: all 6 checks passed in 104s.` The greps are under Artifacts and Notes.

M2 order: `./tools/verify`; the template, the two stylesheets, the test; run `tests/web/test_new_routes_p4.py` (expected `11 passed`); `./tools/verify`; tick; commit.

M2 as run (2026-10-21, one session): `./tools/verify` before any edit printed `verify: all 6 checks passed in 102s.`; the template, `layout.css`, and `mobile.css` were edited, then the test file; `tests/web/test_new_routes_p4.py` against the edited page printed `11 passed in 0.68s`; the same test file against the page as committed in M1 (the `src/` edits reverted by patch for one run, Surprises) printed `1 failed, 10 passed in 0.72s`; the five greps each printed `1`. The closing `./tools/verify`, run after the work was committed and before the tick, printed `verify: all 6 checks passed in 102s.` (its first tier `1986 passed, 5 skipped, 4 xfailed, 1 warning in 53.55s`).

M3 order: `./tools/verify`; the four documents and the two debt edits; the grep checks in Validation; `./tools/verify` (its sixth check reads this plan); tick; commit.

M3 as run (2026-10-21, one session): `./tools/verify` before any edit printed `verify: all 6 checks passed in 103s.`; the six edits (three to `docs/specs/votes.md`, one each to `docs/specs/city-page.md` and `docs/specs/index.md`, the `D68` deletion and the `D66` clause in `docs/DEBT.md`) were applied by one script of anchored replacements, each anchor asserted to occur once, and `git diff --stat` listed those four files with 7 insertions and 6 deletions; the eight acceptance greps and the `src` diff check printed as Validation asks (transcript under Artifacts and Notes). The closing `./tools/verify` line is recorded there when observed.

Operator step. None of this runs in a milestone session. Before merge, read-only, from the WSL checkout with `psql` against the `DATABASE_PUBLIC_URL` of the `docket-web` Railway service (the way `plans/completed/member-votes-name-their-member.md` had its queries run), the two queries below; the results go into this plan's Surprises & Discoveries as a dated operator entry committed on this branch before merge, and a shape the design does not assume (a `source` value other than `minutes_text` and `video_ocr`, or no meeting holding both) is a Decision Log entry too.

    -- A. non-hidden meetings of the twelve-month window by which unflagged sources they hold,
    --    with the resolved member-vote rows the member pages read on them
    SELECT has_minutes, has_video, count(*) AS meetings, sum(member_rows) AS member_rows
      FROM (SELECT v.meeting_id,
                   bool_or(v.source = 'minutes_text' AND NOT v.needs_review) AS has_minutes,
                   bool_or(v.source = 'video_ocr' AND NOT v.needs_review) AS has_video,
                   (SELECT count(*) FROM member_votes mv JOIN votes v3 ON v3.id = mv.vote_id
                     WHERE v3.meeting_id = v.meeting_id AND mv.council_member_id IS NOT NULL) AS member_rows
              FROM votes v JOIN meetings m ON m.id = v.meeting_id
             WHERE m.is_hidden = FALSE AND m.meeting_date >= current_date - interval '12 months'
             GROUP BY v.meeting_id) t
     GROUP BY 1, 2 ORDER BY 1, 2;
    -- expected: a non-zero row for has_minutes = true, has_video = true (the meetings the double count hits)
    -- B. every source value and flag the rule will meet
    SELECT source, needs_review, count(*) FROM votes GROUP BY 1, 2 ORDER BY 1, 2;
    -- expected: only minutes_text and video_ocr

After the deploy the operator can compare, for one member, the roll-call total on `/al/birmingham/council/<id>/` with the "Attended <a> of <r> roll calls in the last 12 months" line of the council card on `/al/birmingham/` after passing `since=<the card's date>`; the two `r` values agree.

## Validation and Acceptance

M1. `./tools/verify` prints `verify: all 6 checks passed in <N>s.` as its last line. The unit file, run as above, prints `14 passed`, and the four new tests, run against the code as it stood before the `query.py` edit, fail; the session records both summaries. The four tests, in `tests/unit/test_query_member_history.py`: `test_get_member_stats_counts_one_source_per_meeting` asserts on the fixture that `get_member_stats(member_id) == {"votes_total": 1, "attendance_pct": 100, "alignment_pct": 100}` and that `list_member_voting_history(member_id, limit=10)["rows"]` has two rows whose `source` values sorted are `["minutes_text", "video_ocr"]` and whose positions are both `yea`; `test_get_member_stats_counts_ocr_only_meeting` adds meeting `Y` (2099-06-01, `video_ocr`, `passed`, position `no`) and asserts `votes_total == 2`, `attendance_pct == 100`, `alignment_pct == 50`; `test_get_member_stats_excludes_flagged_vote_and_history_lists_it` adds meeting `Z` (2099-07-01, `minutes_text`, `failed`, position `yea`, `needs_review=True`) and asserts `votes_total == 1` and `attendance_pct == 100`, that the undated history has three rows titled `["TEST_MH_Z", "TEST_MH_X", "TEST_MH_X"]`, and that the undated Dissent view lists exactly the `Z` row (a yes on a motion that failed, listed though never counted); `test_get_member_vote_summary_counts_under_rule` asserts on the fixture `summary["total"] == 1`, `summary["yea"] == 1`, `summary["nay"] == 0`, and `len(summary["recent"]) == 2` with both sources present. The changed assertions hold: the last line of the file is `== 4`, and `tests/web/test_city_briefing.py` line 812 is `== 0`. `grep -n 'CASE WHEN bool_or' src/docket/services/query.py` prints nothing; `grep -c 'from docket.services.briefing import chosen_source_cte' src/docket/services/query.py` prints `1`; `grep -n 'D58' src/docket/services/query.py tests/unit/test_query_member_history.py tests/web/test_city_briefing.py docs/DEBT.md` prints nothing; `ls docs/decisions/0066-*.md` prints one file; `grep -c 'member-page-counts-one-source' docs/decisions/0056-the-city-page-counts-one-vote-source-per-meeting-minutes-first.md docs/decisions/0057-a-tabled-motion-has-no-outcome-on-the-city-page.md` prints `1` for each.

M2. `./tools/verify` prints `verify: all 6 checks passed in <N>s.` `tests/web/test_new_routes_p4.py` prints `11 passed`. The new test `test_member_detail_shows_source_column_and_count_note` seeds through `_seed_one_vote`, requests `/al/p4test_alpha/council/<alpha_member_id>/`, and asserts status 200, that the body contains `class="member-history-source t-meta">official minutes<`, the sentence `Counted from the official minutes where a meeting has them and from video OCR otherwise`, and `1 roll calls` (the stat strip's sub-line for one counted roll call); the existing `test_member_detail_200`, whose fixture seeds no votes, still passes with the note rendered. `grep -c 'member-history-source' src/docket/web/templates/member_detail.html src/docket/web/static/layout.css src/docket/web/static/mobile.css` prints `1` for each file; `grep -c 'member-count-note' src/docket/web/templates/member_detail.html src/docket/web/static/layout.css` prints `1` for each.

M3. `./tools/verify` prints `verify: all 6 checks passed in <N>s.` `grep -n 'members/<id>' docs/specs/votes.md` prints nothing; `grep -c 'chosen_source_cte' docs/specs/votes.md` prints at least `1`; `grep -c 'D28' docs/specs/votes.md` prints at least `1`; `grep -n 'behaves as before' docs/specs/city-page.md` prints nothing; `grep -c '0066' docs/specs/city-page.md` prints `1`; `grep -c 'counting rule' docs/specs/index.md` prints `1`; `grep -n '^| D68 ' docs/DEBT.md` prints nothing; `grep -c 'member-page-counts-one-source' docs/DEBT.md` prints `1` (the `D66` note). `git diff --stat origin/main -- src` shows no file changed by M3 beyond M1 and M2's.

## Idempotence and Recovery

Every edit is to a tracked file and is re-runnable: a second application of a `sed`-style change is detected by the greps above printing the wrong count, and `git diff` shows the state. The test fixtures clean by prefix (`TEST_MH_`, `TEST_P4_`) before and after, so a failed run leaves nothing that a rerun does not remove, and `tools/test-db --drop` removes the throwaway database on every `./tools/verify` exit path; if a single-file run was interrupted, run `tools/test-db --drop` by hand. A milestone that does not fit its session is split in place in Progress (completed: X; remaining: Y) with a Decision Log entry, never carried through compaction. No migration, no production write, and no deploy is part of this plan; the operator's read-only queries change nothing.

## Artifacts and Notes

Observed at authoring, 2026-10-20, in the worktree:

    $ tools/test-db            (before .env existed)
    ERROR:  permission denied to create database
    $ printf 'DATABASE_URL=postgresql://thinkdarrell@/docket_db\n' > .env; tools/test-db
    All migrations applied.
    $ venv/bin/python -m pytest tests/unit/test_query_member_history.py tests/web/test_new_routes_p4.py tests/unit/test_query_hidden_meetings.py -q -p no:cacheprovider
    38 passed in 1.57s
    $ venv/bin/python -m pytest tests/web/test_city_briefing.py tests/services/test_briefing_facts.py -q -p no:cacheprovider
    79 passed in 9.14s
    $ ./tools/verify
    verify: unit+web+services ... ok (55s)   [1981 passed, 5 skipped, 4 xfailed]
    verify: integration ... ok (47s)          [631 passed]
    verify: all 6 checks passed in 105s.

Observed in the M1 session, 2026-10-21, in the worktree:

    $ ./tools/verify                                  (before any edit)
    verify: all 6 checks passed in 102s.
    $ DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_query_member_history.py -q -p no:cacheprovider
    5 failed, 9 passed in 0.35s                       (tests written, query.py unchanged)
    ... after the query.py edit:
    14 passed, 1 warning in 0.39s
    $ ... tests/web/test_city_briefing.py
    58 passed in 8.71s
    $ grep -n 'CASE WHEN bool_or' src/docket/services/query.py
    (nothing)
    $ grep -c 'from docket.services.briefing import chosen_source_cte' src/docket/services/query.py
    1
    $ grep -n 'D58' src/docket/services/query.py tests/unit/test_query_member_history.py tests/web/test_city_briefing.py docs/DEBT.md
    docs/DEBT.md:63:| D70 | ... (which spends rows D58 to D65 ...)    (the carve-out; see Surprises)
    $ grep -n '^| D58 ' docs/DEBT.md
    (nothing)
    $ ls docs/decisions/0066-*.md
    docs/decisions/0066-the-member-page-counts-one-vote-source-per-meeting-through-the-city-pages-fragment.md
    $ grep -c 'member-page-counts-one-source' docs/decisions/0056-*.md docs/decisions/0057-*.md
    1 and 1
    $ ./tools/verify                                  (after every M1 edit)
    verify: all 6 checks passed in 104s.

Observed in the M2 session, 2026-10-21, in the worktree:

    $ ./tools/verify                                  (before any edit)
    verify: all 6 checks passed in 102s.
    $ DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/web/test_new_routes_p4.py -q -p no:cacheprovider
    11 passed in 0.68s                                (template, stylesheets, test edited)
    ... the same, with src/ reverted to the M1 commit for one run:
    1 failed, 10 passed in 0.72s                      (test_member_detail_shows_source_column_and_count_note)
    $ grep -c 'member-history-source' src/docket/web/templates/member_detail.html src/docket/web/static/layout.css src/docket/web/static/mobile.css
    1, 1, 1
    $ grep -c 'member-count-note' src/docket/web/templates/member_detail.html src/docket/web/static/layout.css
    1, 1
    $ ./tools/verify                                  (after every M2 edit)
    verify: unit+web+services ... ok (54s)   [1986 passed, 5 skipped, 4 xfailed, 1 warning]
    verify: integration ... ok (46s)
    verify: all 6 checks passed in 102s.

Observed in the M3 session, 2026-10-21, in the worktree:

    $ ./tools/verify                                  (before any edit)
    verify: all 6 checks passed in 103s.
    $ git diff --stat                                 (after the six edits)
     docs/DEBT.md            | 3 +--
     docs/specs/city-page.md | 2 +-
     docs/specs/index.md     | 2 +-
     docs/specs/votes.md     | 6 ++++--
    $ grep -n 'members/<id>' docs/specs/votes.md
    (nothing)
    $ grep -c 'chosen_source_cte' docs/specs/votes.md; grep -c 'D28' docs/specs/votes.md
    1, 1
    $ grep -n 'behaves as before' docs/specs/city-page.md
    (nothing)
    $ grep -c '0066' docs/specs/city-page.md; grep -c 'counting rule' docs/specs/index.md
    1, 1
    $ grep -n '^| D68 ' docs/DEBT.md
    (nothing)
    $ grep -c 'member-page-counts-one-source' docs/DEBT.md
    1
    $ git diff --stat origin/main -- src
     src/docket/services/query.py                | 94 ++++++++++++++++++-----------
     src/docket/web/static/layout.css            |  3 +
     src/docket/web/static/mobile.css            | 11 ++++
     src/docket/web/templates/member_detail.html |  2 +
    $ git diff --stat HEAD -- src
    (nothing)

The decision record M1 writes, `docs/decisions/0066-the-member-page-counts-one-vote-source-per-meeting-through-the-city-pages-fragment.md`, verbatim:

    # 0066 — The member page counts one vote source per meeting through the city page's fragment, lists every row with its source, and its Dissent view is the against-the-outcome predicate with or without a date

    ## Decision

    `get_member_stats` and the counts of `get_member_vote_summary` in `src/docket/services/query.py` join each member vote through `briefing.chosen_source_cte` (decision `0056`), scoped to the member's non-hidden meetings and reached by a function-local import, so a member's attendance, alignment, and roll-call total count one source per meeting with flagged votes excluded, and the rule is written in one place. The history lists every row carrying the member's id, each with its source shown. `list_member_voting_history` applies `AGAINST_OUTCOME_PREDICATE` to the Dissent filter whether or not `since` is given (decision `0057`).

    ## Rationale

    A meeting that holds both a minutes vote and a video vote on one motion gave the member page two roll calls for one position (`D68` in `docs/DEBT.md`, observed on the throwaway database as `votes_total: 2, attendance_pct: 100` for one meeting and one member), and the daily resolver (decision `0062`) makes that visible on every meeting of the window that has both sources once its one-time sweep runs (`D66`). Three ways to count were open. Counting every row is the double count. Choosing per motion would need the reconciliation `D28` defers and would mix the two sources inside one number. Choosing per meeting, minutes first, is the rule the city page's council card already counts under, so the member page prints the same roll-call total as the card over the same meetings and the rule has one owner; writing it a second time in `query.py` would let the two drift, and the function-local import is the price of `briefing` importing `query` at module level. The history is not a count: it lists both rows so the reader sees what each source recorded (`docs/PRINCIPLES.md`, Keep the sources apart), the source column tells the two rows apart, and a flagged vote is listed for the same reason and counted nowhere.

    The undated Dissent view had kept an older filter that listed an abstention and any present vote on a tabled motion as dissent (`D58`, carried by decisions `0056` and `0057` because the city page design excluded the member page beyond `since`). With the stat strip counting under the card's rule, two definitions of dissent on one page would leave the strip and the list disagreeing about the same member; the swap is one predicate and one test, so it is paid here rather than left.

    ## Date

    2026-10-20, the plan author (Claude, cycle-plan) from the operator's goal, in `plans/active/member-page-counts-one-source.md`, written in its M1.

    ## Status

    accepted

The paragraph M3 appends to the Two sources section of `docs/specs/votes.md`, after the sentence ending "(decision `0005`).":

    Where a count is printed per member, one source counts per meeting. The member page at `/al/<slug>/council/<id>/` (`member_detail` in `src/docket/web/public.py`) prints attendance, alignment with the majority, and the roll-call total from `get_member_stats` in `src/docket/services/query.py`, and `get_member_vote_summary` counts positions the same way: both join each member vote through `briefing.chosen_source_cte` (`src/docket/services/briefing.py`, decision `0056`), the one owner of the rule the city page's counts use, reached by a function-local import because `briefing` imports `query` at module level. For each meeting the chosen source is `minutes_text` when the meeting has any vote from the minutes with `needs_review` false, otherwise `manual`, then `api`, then `video_ocr`; a vote with `needs_review` true is never counted. The rule is per meeting, not per motion: on a meeting the minutes cover, a motion only the video recorded is not counted, and which of two readings of one motion is right is not decided anywhere; `D28` in `docs/DEBT.md` is the reconciliation that stays unbuilt, and the meeting page shows both readings. The page's history (`list_member_voting_history` without `since`, and the `recent` list of `get_member_vote_summary`) is not a count: it lists every row carrying the member's id, flagged rows included, each with its source in its own column ("official minutes" or "video OCR", the meeting page's words), so a motion both sources recorded appears twice, once per source, under a line beneath the stat strip saying that the official minutes are counted where a meeting has them and video OCR otherwise. With `since` the history too is restricted to the chosen source (`docs/specs/city-page.md`, Parameters on existing routes). The Dissent filter, dated or not, is `query.AGAINST_OUTCOME_PREDICATE`, a no on a motion that passed or a yes on one that failed (decisions `0057` and `0066`).

The sentence that replaces the last sentence of When resolution runs in `docs/specs/votes.md`:

    The member page at `/al/<slug>/council/<id>/` counts only rows that carry that member's id, and of those only the rows of each meeting's chosen source with `needs_review` false (Two sources above); its history lists every row carrying the id, so a row joins a member's page the moment it resolves and is counted when its source is the meeting's chosen one.

The sentence M3 adds to Tests that pin this in `docs/specs/votes.md`:

    `tests/unit/test_query_member_history.py` pins the member page's counting rule (a meeting holding both sources counts once and lists twice, an OCR-only meeting counts, a flagged vote is listed and not counted, `get_member_vote_summary` counts the same way) and that the Dissent view, dated or not, excludes an abstention and a vote on a tabled motion; `tests/web/test_new_routes_p4.py` pins the source column and the note on the page.

The sentence that replaces the last sentence of `docs/specs/city-page.md` line 53:

    Without `since` the page's counts take the same rule over every meeting of the member, its history lists every row with its source, and the Dissent filter is the same predicate (`docs/specs/votes.md`, Two sources; decision `0066`).

The clause M3 appends to the second cell of the `votes.md` row in `docs/specs/index.md`, before the closing ` |`:

    , and the member page's counting rule (one source per meeting through the city page's fragment, flagged votes listed and not counted, the source column, and the Dissent predicate with or without a date)

The clause M3 appends to the Item cell of `D66` in `docs/DEBT.md`, before that cell's closing ` |`:

    ; since plan `member-page-counts-one-source` the member page counts one source per meeting, so the sweep may run without making a double count visible there

## Interfaces and Dependencies

In `src/docket/services/query.py`, immediately above `def get_member_stats`, define:

    # The member page's counting readers (``get_member_stats``, the counts of
    # ``get_member_vote_summary``) and the dated history take one vote source per
    # meeting: the city page's rule, owned by ``briefing.chosen_source_cte``
    # (decision 0056) and written nowhere else. ``_member_source_with`` returns
    # the WITH clause scoped to the non-hidden meetings holding a vote of one
    # member; its parameters are the member id, then ``since`` when
    # ``where_since`` is given. ``_CHOSEN_SOURCE_JOIN`` keeps the votes of each
    # meeting's chosen source and drops flagged ones.
    def _member_source_with(where_since: str = "") -> str:
        # Imported here: briefing imports this module at import time.
        from docket.services.briefing import chosen_source_cte

        return "WITH " + chosen_source_cte(
            "v.meeting_id IN (SELECT m2.id FROM meetings m2"
            " JOIN votes v2 ON v2.meeting_id = m2.id"
            " JOIN member_votes mv2 ON mv2.vote_id = v2.id"
            f" WHERE mv2.council_member_id = %s{where_since} AND m2.is_hidden = FALSE)"
        )


    _CHOSEN_SOURCE_JOIN = """
            JOIN meeting_vote_source s
              ON s.meeting_id = v.meeting_id
             AND s.chosen_source = v.source
             AND v.needs_review = FALSE
    """

`get_member_stats(member_id: int) -> dict`, `list_member_voting_history(member_id: int, *, cursor: str | None = None, limit: int = 20, filter_mode: str = "all", since: date | None = None) -> dict`, and `get_member_vote_summary(member_id: int) -> dict` keep their signatures and return shapes; `AGAINST_OUTCOME_PREDICATE` keeps its text. `briefing.chosen_source_cte(scope: str) -> str` is read and not changed; nothing else in `briefing.py` is touched, so `D60`, `D61`, and `D62` do not fire. `member_detail` in `public.py` is not changed. The CSS classes this plan introduces are `member-history-source` and `member-count-note`; the Jinja expression for the source is `{{ 'video OCR' if row.source == 'video_ocr' else 'official minutes' }}`.

Identifiers spent by this plan: decision `0066`; test names `test_get_member_stats_counts_one_source_per_meeting`, `test_get_member_stats_counts_ocr_only_meeting`, `test_get_member_stats_excludes_flagged_vote_and_history_lists_it`, `test_get_member_vote_summary_counts_under_rule`, `test_member_detail_shows_source_column_and_count_note`; fixture `member_with_both_sources_one_meeting`; helpers `_add_vote_meeting`, `_add_vote_to_meeting` (added in M1, Decision Log), and `_seed_one_vote`; seed names `TEST_MH_Lee`, `TEST_MH_X`, `TEST_MH_Y`, `TEST_MH_Z`, `TEST_P4_meeting`. Debt rows deleted: `D58` (M1), `D68` (M3). Debt rows edited: `D66` (M3). Debt rows cited and left: `D28`, `D57`, `D70`.

## Milestones

### Milestone 1: the readers count one source per meeting and both Dissent views use one predicate

Today `get_member_stats` and the counts of `get_member_vote_summary` count every row carrying the member's id, and the undated Dissent view uses a broader filter than the dated one. At the end of this milestone both counting readers join through `briefing.chosen_source_cte` by the helper in Interfaces and Dependencies, the dated branch of `list_member_voting_history` uses the same helper, the Dissent filter is `AGAINST_OUTCOME_PREDICATE` with or without `since`, the four new unit tests pass where they failed before, the three assertions that pinned the old behaviour are updated, decision `0066` exists, `D58` is gone, and `0056` and `0057` cite the paid row. The work is the first three paragraphs of Plan of Work; the proof is the M1 paragraph of Validation and Acceptance. The page itself still shows two indistinguishable rows for a doubly recorded motion until M2, and that is expected.

### Milestone 2: the page shows each row's source and says what is counted

At the end of this milestone a vote row on the member page shows "official minutes" or "video OCR" in its own column between the title and the position chip, sized `110px 1fr auto auto` on desktop and wrapped under the title on phones, and a one-line note under the stat strip reads "Counted from the official minutes where a meeting has them and from video OCR otherwise; a vote flagged for review is listed below but not counted." The smoke test seeds one meeting with one minutes vote for the alpha member and sees the column text, the note, and `1 roll calls`. The work is the M2 paragraphs of Plan of Work; the proof is the M2 paragraph of Validation and Acceptance.

### Milestone 3: the specs, the index, the debt register

At the end of this milestone `docs/specs/votes.md` states the rule's reach in Two sources and no longer claims the member pages count every row carrying the id, `docs/specs/city-page.md` line 53 no longer says the undated page behaves as before, the `votes.md` row of `docs/specs/index.md` names the counting rule, the `D68` row is deleted, and `D66` says its sweep may now run without making a double count visible. The texts are given verbatim in Artifacts and Notes; the proof is the M3 paragraph of Validation and Acceptance and `./tools/verify`, whose sixth check reads this plan.

## Revision notes

- 2026-10-20, authored by the plan author (Claude, under `cycle-plan`) from the operator's goal and the scope brief, in the worktree cut from `origin/main` at `2a322fd`. Left out on purpose, as the brief's out-of-scope list and the Decision Log say: deleting `get_member_vote_summary` (no caller in `src/`, the operator said keep it; it gets the rule and a direct test); a needs-review marker on the history rows (the meeting page the row links to shows the callout); putting the undated history list itself under the rule (the operator wants every row listed, one per source, with the source column telling them apart); repairing the wrong path in the `D68` row (the row is deleted); any change to `briefing.py`, so `D60`, `D61`, and `D62` do not fire; and any edit to `tests/unit/test_query_hidden_meetings.py`, whose `source = 'test'` vote sits on a hidden meeting outside every scope. The slugs `member-page-one-source-per-meeting` and `member-counts-one-source-per-meeting` were also free; the shortest was taken.
- 2026-10-21, M1 session (Claude, under `cycle-run`): M1 ticked; Surprises & Discoveries, Decision Log, Concrete Steps, Artifacts and Notes, and the spent-identifier list carry the observed evidence, the `_add_vote_to_meeting` helper, and the carve-out that the M1 grep for `D58` prints the `D70` row. No other section changed.
- 2026-10-21, M2 session (Claude, under `cycle-run`): M2 executed; Surprises & Discoveries, Concrete Steps, and Artifacts and Notes carry the observed evidence (the failing-before and passing-after runs of `tests/web/test_new_routes_p4.py`, the greps, both `./tools/verify` lines). No carve-out against the M2 acceptance. No other section changed beyond the M2 tick.
- 2026-10-21, M3 session (Claude, under `cycle-run`): M3 executed, the last milestone; Surprises & Discoveries, Decision Log, Outcomes & Retrospective, Concrete Steps, and Artifacts and Notes carry the observed evidence, the placement of the Tests sentence, and the `0066`/`D68` citation left under the register's convention. No carve-out against the M3 acceptance. The plan stays under `plans/active/` for the factory's close step.
