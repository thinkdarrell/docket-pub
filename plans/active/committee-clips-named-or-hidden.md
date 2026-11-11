# Name every Birmingham committee recording, and hide the clips that are not meetings

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

docket.pub lists Birmingham's council and committee recordings at `https://docket.pub/al/birmingham/meetings/`. On 2026-11-11 that page showed two kinds of committee card: some carried the committee's name ("Public Safety Committee", "Committee of the Whole"), and ten read only "Council committee meeting". A reader cannot tell which committee met, and five of the ten are not meetings at all: they are recordings of one to eight minutes that the clerk's streaming equipment left in the city's video archive on days when no committee was scheduled.

After this work a reader sees three differences. A committee recording on a day the city's calendar lists one committee carries that committee's name, including for past days, because docket.pub reads the city's whole calendar and not only the next four events. On a day two committees met, the recording the council's YouTube channel does not name takes the name of the committee the other recording leaves over, when the evidence allows exactly one answer. And a short or speechless clip on a day the calendar shows no council or committee event is no longer listed anywhere on the site; the operator sees it, with the reason, on the admin page `/admin/meetings/hidden` and can bring it back with one click, after which it is never hidden automatically again.

The observation that stands for all of it, once the operator has run the post-merge steps in Validation and Acceptance: the meetings page shows no card dated 2026-11-05 or 2026-10-15, the 2026-10-19 committee card reads "Arts and Parks", and no meeting is listed twice. Whether the two recordings of 2026-11-09 gain their names depends on a fact production holds and the authoring checkout cannot read (why the YouTube pass has not attached that day's Budget and Finance recording to either clip); Validation and Acceptance says how the operator finds out, and this plan does not promise that day.

## Progress

As authored on 2026-11-11, nothing has been executed.

- [x] (2026-11-11 21:46Z) M1: `city_calendar` stores every City Council department event from the city's events search and from the event pages its sitemap lists, the two new sources are isolated from each other and from the council page, and the unit and integration tests for the three readers pass
- [x] (2026-11-11 22:15Z) M2: the resolver names a committee recording by elimination on a day with several committee events, a short clip no longer shares a committee's name with a full-length recording of the same day, a cancelled calendar event names nothing, a recording with agenda items and no council event that day is eligible for a committee event, `resolve_and_store` resolves every row of each affected day, and the meeting page's provenance sentence says when the name was reached by elimination
- [x] (2026-11-11 22:33Z) M3: the YouTube pass attaches a committee recording to the Granicus row the calendar already named for the same committee, choosing by length when the calendar named several, instead of creating a second row for that meeting
- [ ] M4: the daily task `non_meetings` hides a clip that meets the rule in this plan and records why, hides nothing while the calendar has not been read for 36 hours, an admin's unhide exempts the row for good, and `/admin/meetings/hidden` shows the reason and the clips the brake held back
- [ ] M5: the specs, the Birmingham guide, the decision records, and `docs/DEBT.md` describe the system as M1 to M4 left it, `D116` is deleted, and a new debt row lists the operator's post-merge steps

## Surprises & Discoveries

As authored on 2026-11-11, no milestone has run. The authoring research found the following, each observed on 2026-11-11 from the development machine with `curl` against the public pages named.

- Observation: the city's sitemap lists past event pages; the events search and the council page do not.
  Evidence: `https://www.birminghamal.gov/sitemap.xml` (700,196 bytes) held 119 `<loc>` entries containing `/events/`, 33 of them with `committee`, `council-meeting`, or `work-session` in the path, the earliest of the 2026-10 run being `/events/2026-10-05community-development-committee-meeting-october-5-2026`. By month the 119 were: 9 scattered entries from 2025-05 to 2026-06, 51 in 2026-10, 42 in 2026-11, 7 in 2026-12, and 9 later. `GET /api/search/events?page=0&search=&fromDate=2026-10-01&toDate=2026-10-31&department=&category=&district=` returned `total: 0`, so the search answers for upcoming events only.

- Observation: the events search returns every upcoming City Council department event, not four.
  Evidence: `GET https://www.birminghamal.gov/api/search/events?page=0&search=&fromDate=&toDate=&department=55&category=&district=` returned `{"graphqlEventsSearchWww": {"pageInfo": {"offset": 0, "page": 0, "pageSize": 10, "total": 5}, "results": [...]}}`, five results through 2026-11-24 including `4943 BUDGET AND FINANCE COMMITTEE MEETING, November 23, 2026`. The same hour the council page's `__NEXT_DATA__` listed four events. Department id `55` is "City Council" in the `departments` list embedded in `https://www.birminghamal.gov/events`.

- Observation: an event page carries the same fields as a search result, plus its department.
  Evidence: `https://www.birminghamal.gov/events/2026-11-09transportation-infrastructure-committee-meeting-november-9-2026` has `props.pageProps.nodeResource` with `id: "4941"`, `title: "TRANSPORTATION AND INFRASTRUCTURE COMMITTEE  MEETING, November 9, 2026"`, `path`, `department: {"name": "City Council"}`, `startDate.time: "2026-11-09T20:00:00+00:00"`, `endDate.time: "2026-11-09T21:30:00+00:00"`, `eventStatus: "active"`, `eventCategories: null`.

- Observation: a committee that is not the council's is in the sitemap too.
  Evidence: `/events/2026-10-14framework-plan-implementation-committee-public-information-meeting` has `department: {"name": "Planning, Engineering & Permits"}`. Its title contains "Committee", so without a department test `classify_event` in `src/docket/services/meeting_types.py` would name a council clip of 2026-10-14 after it.

- Observation: the ten generic committee cards, their Granicus clips, and what the calendar says. Read from the public meeting pages and from `https://bhamal.granicus.com/ViewPublisher.php?view_id=2`.
  Evidence: meetings 3192, 3193, 3194 (2026-11-05; clips 2029, 2030, 2031; 1, 8, and 4 minutes; no agenda link; no council event in the sitemap that day; the council's YouTube feed holds only `11.5.26 TEST` for that date). Meetings 2618, 2619 (2026-10-15; clips 2021, 2022; 4 and 5 minutes; no agenda link; no council event that day). Meetings 3202, 3203 (2026-11-09; clips 2032 at 37 minutes and 2033 at 1 hour 36 minutes; both link the council's 2026-11-10 agenda; the calendar lists Transportation and Infrastructure 14:00 to 15:30 and Budget and Finance 15:30 to 17:00 Central; the YouTube feed holds `11.9.26 Budget and Finance Committee Meeting` and four `TEST` streams). Meeting 2620 (2026-10-19; clip 2023, no longer in the Granicus listing; the calendar lists Arts and Parks). Meeting 2613 (2026-10-26; an agenda event with no clip; the calendar lists Budget and Finance and Transportation and Infrastructure). Meeting 2614 (2026-10-14; clip 2019, no longer in the Granicus listing; no council event that day).

- Observation: one meeting is on the site twice, and the cause is in the YouTube pass.
  Evidence: 2026-11-02 shows meeting 3188 "Arts and Parks" (Granicus clip 2027, 11 minutes, named by the calendar) and meeting 3196 "Arts and Parks Committee" (a row created from the YouTube recording, with a transcript). The calendar lists one Arts and Parks meeting that day. `_committee_candidates` in `src/docket/services/youtube_meetings.py` admits a committee row only when it has no `body_name`, so a row the calendar named first is never a candidate and the recording gets a row of its own. With the fuller calendar of M1 most committee rows will be named before the YouTube pass sees them, so without M3 this duplication becomes the common case.

- Observation: the low-speech measurement exists and hides a transcript, never a meeting.
  Evidence: `transcripts.status = 'low_speech'` is written by the producer (`transcriber/transcriber/engine.py`, `is_low_speech`, floor 180 seconds of speech) and by the worker (`mark_low_speech` in `src/docket/ai/transcripts/pipeline.py`); `public_predicate` in `src/docket/services/transcripts.py` is `uploaded_at IS NOT NULL AND status <> 'low_speech'`. The only writers of `meetings.is_hidden = TRUE` are the admin route `hide_meeting` in `src/docket/web/admin.py` and `_Run.absorb` in `src/docket/services/youtube_meetings.py`.

- Observation (M1 session, 2026-11-11): the starting state is green, and `./tools/verify` took 190 seconds against a budget of 180.
  Evidence: run before any edit, at commit `db9fb1a`: `verify: unit+web+services ... ok (83s)`, `verify: integration ... ok (98s)`, `verify: judge-fixtures ... ok (0s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (8s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 190s.` After the summary the database drop printed `ERROR:  permission denied to terminate process` (the local role is not a superuser); the exit line had already been printed and the next `tools/test-db` build succeeded.

- Observation (M1 session): the four fixtures were fetched on 2026-11-11 at about 21:35Z with the commands in Concrete Steps, each HTTP 200, and no substitution was needed.
  Evidence: sizes 5,667 bytes (search), 700,196 (sitemap), 29,069 (council event page), 31,137 (Planning event page). The sitemap held 1,839 `<loc>` entries, 119 under `/events/`, 33 of those matching the path filter, exactly the authoring counts. The committed `tests/fixtures/city_calendar/birmingham_sitemap.xml` is those 119 entries plus the home page and one news page, 121 in all, with whitespace collapsed to one `<url>` per line; the two event pages are committed as fetched. The sitemap was downloaded to the session scratchpad, not `/tmp`.

- Observation (M1 session): the search's five City Council results are four giveaways and one committee meeting, and none carries a status.
  Evidence: `pageInfo` was `{"offset": 0, "page": 0, "pageSize": 10, "total": 5}`; the ids in order are 4967 (a District 4 hams giveaway), 4969, 4965, 4943 (`BUDGET AND FINANCE COMMITTEE MEETING, November 23, 2026`), 4964. Every result has `department: {"name": "City Council"}` and no `eventStatus` key, where the council page's results and the event pages have `eventStatus: "active"`. So the department's events are not all meetings (the giveaways are stored like any other event, and what `classify_event` makes of their titles is M2's and M4's concern, since M4 counts any event `classify_event` reads as anything), and a row the search stores has a NULL `event_status`.

- Observation (M1 session): the news page kept in the sitemap fixture has `committee` in its path.
  Evidence: `https://www.birminghamal.gov/news/district-9-councilor-latonya-tate-appointed-pscp-federal-advocacy-committee`. It is the fixture's proof that the `/events/` prefix is tested and not only the three words.

- Observation (M1 session): two of the 33 filtered sitemap pages are the Planning department's, not one.
  Evidence: `/events/2026-10-08framework-plan-implementation-committee-public-information-meeting` and the `2026-10-14` page of the same name. Both are fetched on every run and stored on none.

- Observation (M1 session): the tests were committed failing before the code.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_city_calendar.py tests/integration/test_city_calendar_refresh.py tests/integration/test_043_migration.py tests/integration/test_038_migration.py -q -p no:cacheprovider` printed `52 failed, 22 passed`. The 22 are the council-page tests that existed, three of the 038 tests, and `test_043_down_removes_the_column_and_the_keys`, which passes when the migration does not exist because nothing is there to remove. One of the 52, `test_038_up_adds_columns_table_and_metadata`, failed only because this command ran the calendar tests first and they leave an active test city with a `calendar_url` in the database; `./tools/verify` runs `test_038` before them.

- Observation (M1 session): an event the search alone keeps listing can never show a changed status, and a past event's status is read once.
  Evidence: the search fixture's results have no `eventStatus` key, and the sitemap reader skips a page whose address is stored. An event stored from its page as `active` and cancelled afterwards is corrected only while the council page still lists it among its next four. M2's rule also drops an event whose title `is_cancelled_title` marks, and a changed title does arrive by the search; whether the city marks a cancellation in the title, the status, or both has not been observed. This is a limit M5's debt row for what the plan left out should name.

- Observation (M1 session): the new tests passed on the first run of the code, so each rule was removed from a copy and the tests run against it; 26 removals, 26 failed a test.
  Evidence: a pytest plugin in the session scratchpad compiled the altered source into the imported module (the committed files were not edited) and ran `tests/unit/test_city_calendar.py` and `tests/integration/test_city_calendar_refresh.py` once per removal. Adapter, 14: the department test on an event page; the sitemap's `/events/` prefix; its three words; their case-insensitivity; the newest-first sort; the normaliser's trailing slash, host case, and query; the search's stop when the total is covered, its ten-page cap, and its stop on an empty page; the one-second pause; the search's department filter; the status read from a result. Service, 12: stored pages skipped; the 60-page cap; the three-failure stop; a failed page not ending the read; `COALESCE` on the status; the status written at all; the raise when every reader failed; each of the three readers' isolation; the department handed to the search; the stored side of the address comparison normalised. No assertion had to be added after the failing-first commit `2a339c5`, and the test files are unchanged since it (`git diff 2a339c5 73296a2 -- tests` prints nothing).

- Observation (M1 session): `./tools/verify` after the change.
  Evidence: `verify: unit+web+services ... ok (81s)`, `verify: integration ... ok (97s)`, `verify: judge-fixtures ... ok (1s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (8s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 187s.` The four touched test files alone: `74 passed`.

- Observation (M2 session, 2026-11-11): the starting state is green, and `./tools/verify` took 191 seconds.
  Evidence: run before any edit, at commit `f74cf9d`: `verify: unit+web+services ... ok (82s)`, `verify: integration ... ok (102s)`, `verify: judge-fixtures ... ok (0s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (7s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 191s.`

- Observation (M2 session): the tests were committed failing before the code, and the four cases the acceptance names fail under the old rule itself, not only for want of the new keywords.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_meeting_types_resolve.py tests/integration/test_ingest_meeting_types.py tests/web/test_meeting_label.py -q -p no:cacheprovider` printed `39 failed, 75 passed`: the 31 new unit tests (every one, because the old `resolve` refuses the keywords `duration_s` and `siblings` and `same_committee` does not exist), the 7 new integration tests, and the elimination sentence's web test. The two web tests of the plain sentence pass before and after, as they should. To see which unit cases the old rule gets wrong, a plugin in the session scratchpad wrapped the old `resolve` so that it dropped the two keywords, and the 25 `TestWholeDay` tests that call `resolve` were run against it: `13 failed, 12 passed`. The 13 include cases 1, 6, 7, and 8 (and 3, 5, and 9, which build on case 1); the 12 that pass are the cases where the old rule and the new agree (2, 4, and the refusals).

- Observation (M2 session): the new tests passed on the first run of the code, so each rule was removed from a copy and the tests run against it. First round: 58 removals, 46 failed a test. Second round, after ten assertions were added and one line of code simplified: 57 removals, 57 failed a test.
  Evidence: a pytest plugin in the session scratchpad compiled the altered source of `src/docket/services/meeting_types.py` into the imported module (the committed file was not edited) and ran `tests/unit/test_meeting_types_resolve.py`, `tests/integration/test_ingest_meeting_types.py`, `tests/web/test_meeting_label.py`, and `tests/integration/test_admin_meeting_type.py` once per removal. The removals: 9 in `same_committee`, 4 in the cancelled-event test, 2 in `_before_calendar`, 2 on the 600-second floor, 4 in the test for a row without documents, 16 in the choice of event, 6 in `_changes`, 6 in the loading SQL, 1 in `clear_override`, 7 in `named_by_elimination`. Of the first round's 12 that failed nothing, one was a removal written wrongly (it changed nothing) and was replaced, and one showed a branch that could not differ from its neighbour (a row with items, no minutes, and no council event got `None` by a line of its own, where the line above already returned the one council event or `None`), so the code was simplified to the one line. The other ten were rules no test held, and each now has an assertion, all added after the failing-first commit `0e32707`: in `same_committee`, `committee_name_for` on either side, the trailing-word strip on the second name, and "work session" among the words (the prefix rule answered for every name of eight letters or more, so the new cases use a name of four); that a row with items beside a council event takes the council event on a weekday that is not the council's; that only a committee-typed sibling is a namer; that the dates widening `resolve_and_store` are this city's; and in `named_by_elimination`, the row's own type, its `type_source`, and the count being of committee events only. The new tests are `test_the_date_and_the_canonical_name_are_read_before_the_trailing_words`, `test_a_row_with_items_takes_the_council_event_on_any_weekday`, `test_only_a_committee_row_is_a_namer`, `TestNamedByElimination::test_each_condition_alone`, and `TestWholeDaysAreThisCitys`; each says in its docstring that it came after the commit.

- Observation (M2 session): `./tools/verify` after the change.
  Evidence: `verify: unit+web+services ... ok (80s)`, `verify: integration ... ok (97s)`, `verify: judge-fixtures ... ok (1s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (7s)`, `verify: plans ... ok (1s)`, `verify: all 6 checks passed in 186s.` The four touched test files alone: `127 passed`.

- Observation (M2 session): on a day with one committee event, a row already named for that committee does not stop a generic clip beside it from taking the same name.
  Evidence: the rule as this plan states it consults the namers only when the day has several committee events; with one, the row takes it unless it is short beside a long competitor, and a named row is not a competitor. So the 2026-11-02 shape (a `yt-` row titled for Arts and Parks and a Granicus clip the calendar names the same) is still two rows with one name after M2. M3's by-name attach is what joins them when the recording arrives after the calendar named the clip; where a `yt-` row already exists, the operator's hide (the Decision Log's entry on 3188) is the repair.

- Observation (M2 session): a generic-titled sibling of unknown length blocks elimination whatever else it is, and that includes an agenda row with no clip and a row whose title says cancelled.
  Evidence: `classify_title` reads "Regular City Council Meeting - Cancelled (...)" as the generic council reading (`test_cancelled_monday_is_the_council`, which predates this plan), so such a row reaches the calendar rung and, with no stored `duration_s`, counts as a competitor under "a clip of unknown length still counts". The effect is that a day stays generic, the direction the operator asked for; it is a case M5's debt row for what the plan left out can name. Not observed on any production day, since production is not readable from here.

- Observation (M2 session): `resolve_and_store` now returns more than the ids it was given can account for.
  Evidence: `TestWholeDayResolution::test_one_rows_id_resolves_the_whole_day` gives one id and reads `2` back. Its two callers (`src/docket/services/ingest.py` line 147, `src/docket/services/youtube_meetings.py` line 664) use the count only in a log line and a report.

- Observation (M3 session, 2026-11-11): the starting state is green, and `./tools/verify` took 185 seconds.
  Evidence: run before any edit, at commit `228e060`: `verify: unit+web+services ... ok (80s)`, `verify: integration ... ok (97s)`, `verify: judge-fixtures ... ok (1s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (7s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 185s.`

- Observation (M3 session): the tests were committed failing before the code, and the two the acceptance names fail with a `create` where the `attach` should be.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_youtube_sync.py -q -p no:cacheprovider` printed `6 failed, 23 passed`. The six assertion lines: `assert ['create'] == ['attach']` three times (the one named row, the two named rows of 660 and 2,700 seconds, and the dry run), `assert ['defer', 'defer'] == ['attach', 'defer']` (two recordings of one committee and one named row, both published two days before the test's today), and `assert [] == ['absorb']` twice (the two absorption tests). The six new tests that pass before the code are the refusals, which the old rule gets right because it never attaches by name at all; the removal check after the code is what shows they test anything.

- Observation (M3 session): the new tests passed on the first run of the code, so each rule was removed from a copy and the tests run against it. Against the tests of the failing-first commit `ef5702a`: 21 removals, 18 failed a test. After three tests were added and one of them corrected: 21 removals, 21 failed a test.
  Evidence: a pytest plugin in the session scratchpad compiled the altered source of `src/docket/services/youtube_meetings.py` into the imported module (the committed file was not edited) and ran `tests/integration/test_youtube_sync.py` once per removal. The removals: 5 in `_named_rows` (Granicus only, no recording held, the committee type, the calendar source, the name match), 5 in `_choose_by_name` (the single row, the several rows, the choice by length among several, each of the two notes), 5 in `_Run.day` (the step itself, the run's claimed rows, the group leaving the list, the note, the step's place ahead of the blocked rule), and 6 in `absorb_all` and `absorb` (the step, the claimed rows, the arrived-later test, the `yt-` row leaving the list, the note passed, the note printed). The three no test of `ef5702a` held: the step's place ahead of the blocked rule, the claimed rows in absorption, and the `yt-` row leaving the list. Each now has a test added after that commit, which says so in its docstring: `test_a_named_row_takes_its_recording_although_a_bodyless_clip_has_no_duration`, `test_a_clip_taken_by_name_in_this_run_absorbs_nothing_by_name`, and `test_a_yt_row_absorbed_by_name_is_not_offered_to_the_candidates_too`. The order of work is recorded as it happened: the three tests were written from reading the code before the first round was run, the first round was then run with those three deselected to measure `ef5702a`'s tests alone (18 of 21), and a round with them printed 20 of 21, because the second test as first written did not fail (next entry). Before the rounds a guard in `_named_rows` (`if not body_name: return []`) was deleted, since `same_committee` already answers false for an empty name and no input could tell the guard from its absence.

- Observation (M3 session): in a run that writes, the claimed set does nothing for absorption by name; it matters only in a dry run.
  Evidence: `absorb_all` reads the day's rows again inside the run's transaction, so a row `day` attached to already reads `has_youtube` true and `_named_rows` drops it; with the claimed test removed, `test_a_clip_taken_by_name_in_this_run_absorbs_nothing_by_name` still passed. A dry run inserts nothing, the row reads as holding no recording, and the removal then reports an `absorb` after the `attach`. The test now makes a dry run first and asserts its actions are `["attach"]`, and the removal fails it.

- Observation (M3 session): two recordings of one committee on a day with one row of that name go to the row in the listing's order, and the second falls to the old rules.
  Evidence: `test_a_row_taken_by_name_is_not_taken_twice_in_one_run` lists "Arts and Parks Committee Meeting" (2,640 seconds) and "Special Called Arts and Parks Committee Meeting" (900 seconds) for one day with one row named "Arts and Parks"; `group_videos` keeps a special-called stream apart, `same_committee` matches both, the first group in `group_videos`' order (by cleaned title) takes the row and the other is deferred, then created. Length is not consulted when one row carries the name. Not observed on any production day; a case M5's debt row for what the plan left out can name.

- Observation (M3 session): `./tools/verify` after the change.
  Evidence: `verify: unit+web+services ... ok (83s)`, `verify: integration ... ok (99s)`, `verify: judge-fixtures ... ok (1s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (7s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 191s.` It ran on the working tree that became commit `9c72212`, before that commit's edits to this file; `tools/check-plans` ran again in the pre-commit hook and printed `1 of 1 ok`. `tests/integration/test_youtube_sync.py` alone: `32 passed`.

- Observation (M4 session, 2026-11-11): the starting state is green, and `./tools/verify` took 196 seconds.
  Evidence: run before any edit, at commit `14bd0db`: `verify: unit+web+services ... ok (83s)`, `verify: integration ... ok (105s)`, `verify: judge-fixtures ... ok (0s)`, `verify: workflows ... ok (1s)`, `verify: transcriber ... ok (7s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 196s.`

- Observation (M4 session): the tests were committed failing before the code, and for the rule itself the before state says only that the module is absent.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_non_meetings.py tests/integration/test_044_migration.py tests/web/test_hidden_meetings_admin.py tests/integration/test_youtube_sync.py tests/unit/test_worker_tasks.py tests/unit/test_worker_scheduler.py tests/unit/test_worker_health.py tests/integration/test_admin_hide_meeting.py -q -p no:cacheprovider` printed `54 failed, 106 passed`. The 54: all 36 of `tests/integration/test_non_meetings.py` (each imports `docket.services.non_meetings` inside the test and fails with `ModuleNotFoundError`, so no test fails for a rule's own reason; the removal check after the code is what shows each rule is held), the 5 of `tests/integration/test_044_migration.py`, the 5 of `tests/web/test_hidden_meetings_admin.py`, `test_an_absorbed_yt_row_that_is_hidden_carries_the_reason`, 4 in `tests/unit/test_worker_tasks.py`, and 3 in `tests/unit/test_worker_scheduler.py`. The 106 that pass are the tests those files already held.

- Observation (M4 session): the new tests passed on the first run of the code but for one that could not be seeded, so each rule was removed from a copy and the tests run against it: 59 removals, 57 failed a test, and the other two are rules nothing can tell from their absence.
  Evidence: a pytest plugin in the session scratchpad compiled the altered source into the imported module (the committed files were not edited) and ran `tests/integration/test_non_meetings.py`, `tests/web/test_hidden_meetings_admin.py`, `tests/integration/test_youtube_sync.py`, `tests/unit/test_worker_tasks.py`, `tests/unit/test_worker_scheduler.py`, `tests/unit/test_worker_health.py`, and `tests/integration/test_admin_hide_meeting.py` once per removal, stopping at the first failure. The removals: 49 in `src/docket/services/non_meetings.py` (the two metadata keys; the freshness test, its 36 hours moved to 72 and to 30, its city, and its warning; the events' city, the `classify_event` filter, the Chicago date, and the day test; each of the nine conditions of the row query, the provider inside the YouTube one, and the query's city; the lower date bound and the four days moved to three and to five; the generic title and the cancelled title; the strict 600, the floor moved to 200, a NULL length read as short, each of short and low-speech alone, and the pair together; the three parts of the held-back test and the list it fills; the slug and the name put on a row; the active cities, the cities' metadata prefilter, and the per-city `try`; the three columns the `UPDATE` sets, its two conditions, the dry run, and the ids read back; and `held_back` returning the other list), 5 in `src/docket/web/admin.py` (the reason on hide, the reason cleared and the exemption set on unhide, the reason selected, the held-back rows passed), 1 in `src/docket/services/youtube_meetings.py` (`absorbed`), 2 in `src/docket/worker/tasks.py`, and 1 each in `scheduler.py` and `health.py`. The first round printed `59 removals, 55 failed a test`; two of the four that failed nothing then got an assertion (`test_another_citys_clip_is_not_this_citys_to_hide`, and `city_name` in `test_find_returns_the_facts_the_script_prints`) and failed on a second run of those two. The round was run once, on the tests as they stood after the additions below, not on the failing-first commit's tests alone; the removals whose first failing test is one added after that commit are the freshness read's city, the query's city, the name on a row, the `UPDATE`'s two conditions, and the ids read back, and the query's `is_hidden` and `keep_visible_at` conditions are held only by the dry-run assertions added to two tests of that commit (without them the `UPDATE`'s own conditions stop the write and the test cannot see the read). The template's three reason sentences and its second table are not Python and were not in the check; `tests/web/test_hidden_meetings_admin.py` asserts each sentence in the row it belongs to.

- Observation (M4 session): two clauses cannot be told from their absence.
  Evidence: `AND v.provider = 'youtube'` in the row query, because migration 040's CHECK on `meeting_videos.provider` admits only `youtube` (the first form of the test tried to seed a `granicus` row and got `psycopg2.errors.CheckViolation ... "meeting_videos_provider_check"`); the plan states the clause and it is kept for the day a second provider is admitted. And `metadata ? 'calendar_complete_from'` in the query that lists the cities, because `find` refuses a city without the key anyway; it is kept so the task reads one city and not every active one.

- Observation (M4 session): tests changed after the failing-first commit `39ee32e`.
  Evidence: `git diff --stat 39ee32e -- tests` prints `tests/integration/test_non_meetings.py | 81` and `tests/web/test_hidden_meetings_admin.py | 5`. Added, each saying so in its docstring or message: `test_another_citys_fresh_calendar_does_not_stand_for_this_one`, `test_another_citys_clip_is_not_this_citys_to_hide`, `test_a_row_an_admin_changed_between_the_read_and_the_write_is_left_as_the_admin_put_it` (two cases), the `city_name` assertion, and a dry-run assertion in `test_a_clip_with_this_column_set_is_left` and in `test_a_row_an_admin_already_hid_keeps_its_reason`. Rewritten: the YouTube-recording test lost its second half (a clip with another provider's video is still hidden), which could not be seeded. Changed without touching an assertion: both files' fixtures now delete their test cities on teardown (next entry).

- Observation (M4 session): the first `./tools/verify` after the code failed, and the cause was a test city this milestone's web test left behind.
  Evidence: `verify: integration ... FAILED (101s)`, `verify: 1 of 6 checks failed in 194s.`; a second run kept whole in the scratchpad named `tests/integration/test_038_migration.py::test_038_up_adds_columns_table_and_metadata` (`AssertionError: only Birmingham carries a calendar`) and `tests/integration/test_043_migration.py::test_043_up_adds_the_column_and_the_metadata` (`AssertionError: only Birmingham gains the keys`). The web tier runs first on the same database, and `tests/web/test_hidden_meetings_admin.py` left its city inactive with `calendar_url` and `calendar_complete_from` in its metadata; the integration tier alone, on a database the web tier had not touched, printed `1009 passed`. Both new test files now delete their cities on teardown. A later test that seeds a city with a calendar key in the web or unit tier must do the same.

- Observation (M4 session): `./tools/verify` after the change.
  Evidence: `verify: unit+web+services ... ok (81s)`, `verify: integration ... ok (100s)`, `verify: judge-fixtures ... ok (1s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (7s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 189s.` It ran on the working tree that became the code commit, before that commit's edits to this file; `tools/check-plans` ran again in the pre-commit hook. The eight touched test files alone: `164 passed`; `tests/integration/test_non_meetings.py` alone: `40 passed`.

- Observation (M4 session): `scripts/hide_non_meetings.py` run against the throwaway database with one seeded city (a 240-second clip, a 300-second clip with an uploaded `compared` transcript, a 3,600-second clip, a calendar read a moment before).
  Evidence: the dry run printed `test_script_run: 1 to hide, 1 held back`, `1  2026-11-01  Regular City Council Meeting  duration_s=240  transcript=None  hide`, `2  2026-11-02  Regular City Council Meeting  duration_s=300  transcript=compared  held: has speech`, `dry run: 0 rows written`; the write printed the same lines and `test_script_run: hidden 1 rows in one statement: [1]`; a second dry run printed `0 to hide, 1 held back`; the rows then read `('sr-a', True, 'not_a_meeting'), ('sr-b', False, None), ('sr-c', False, None)`. Birmingham, whose calendar table is empty in that database, printed `non_meetings birmingham: the calendar has no event read in the last 36 hours; nothing is hidden` and `birmingham: 0 to hide, 0 held back`. The script has no test of its own; this run is its evidence. The seeded city was deleted afterwards.

- Observation (M4 session): the city's giveaways and other non-meeting events do not keep a clip visible.
  Evidence: M1 found four of the search's five City Council events were giveaways and left what they mean for hiding to this milestone. `classify_event` reads a title with neither "CITY COUNCIL MEETING" nor "COMMITTEE" as nothing, and the rule counts only events it reads as something; `test_an_event_that_is_neither_council_nor_committee_keeps_nothing` seeds "District 4 Holiday Hams Giveaway" on the clip's day and the clip is hidden. The other side: a work session or a hearing whose calendar title holds neither phrase does not keep its day's clip either. No such title has been observed; it is a case M5's debt row for what the plan left out can name.

- Observation (M4 session): the rule's read runs on every load of `/admin/meetings/hidden`, and a stale city warns each time.
  Evidence: `list_hidden_meetings` calls `non_meetings.held_back()`, which is `find` for each city with the key: three queries for Birmingham, and the 36-hour warning in the web service's log whenever the calendar is stale. The script's write run printed the warning twice, since it reads once to print and `hide_non_meetings` reads again.

- Observation (M4 session): an unhide exempts any row, whatever hid it.
  Evidence: `unhide_meeting` sets `keep_visible_at = NOW()` for a row an admin hid by hand or the YouTube pass absorbed, as the plan words it ("`unhide_meeting` clears `hidden_reason` with the other two columns and sets `keep_visible_at = now()`"). An admin's later hide of the same row still works and does not clear the column; only the automatic rule reads it. Nothing in the admin clears `keep_visible_at`; the undo is one `UPDATE`.

## Decision Log

- Decision: the past calendar comes from the city's sitemap, the upcoming calendar from the events search, and the council page stays as a third reader.
  Rationale: the sitemap is the only public listing that still holds past events; the search holds all upcoming ones where the council page holds four (debt row `D116`); keeping the page read costs one request a day and leaves a working source if the search's address changes. Each source fails alone.
  Date/Author: 2026-11-11, plan author.

- Decision: only an event whose department is "City Council" is stored from the sitemap and the search.
  Rationale: the Framework Plan Implementation Committee's public meeting of 2026-10-14 belongs to another department and would otherwise name a council clip.
  Date/Author: 2026-11-11, plan author.

- Decision: elimination names a recording only when exactly one committee event of the day is unclaimed, no other unnamed recording competes for it, and the recording runs at least 600 seconds.
  Rationale: the operator asked that an undecidable day stay "Council committee meeting" rather than be guessed. The duration floor is the author's: a four-minute stream test left beside a named recording would otherwise take the name of a committee whose meeting the archive never recorded.
  Date/Author: 2026-11-11, operator (the stay-generic rule) and plan author (the floor).

- Decision: a clip is hidden when its title is the clerk's generic one, it has no agenda link, minutes link, agenda item, or YouTube recording, the stored calendar shows no council or committee event on its date, its date is on or after the day the calendar is complete from and at least two days past, and either it runs under 600 seconds or its transcript's status is `low_speech`.
  Rationale: the operator's instruction of 2026-11-11: hide the short clips on days with no calendar event, and hide those with a low-speech result too even when longer. Ten minutes is the author's reading of "short"; length alone hides nothing, since real committee meetings of 6 and 11 minutes exist (2026-10-05, 2026-11-02) and it is the empty calendar day that marks a test.
  Date/Author: 2026-11-11, operator and plan author.

- Decision: a clip that meets every condition but has a public transcript (uploaded, status other than `low_speech`) is not hidden; it is listed for the operator.
  Rationale: agreed with the operator on 2026-11-11 as a brake against hiding a real meeting. A transcript is not required before hiding, because a hidden or untranscribed clip never gets one (`claim_next` and `claim_meeting` in `transcriber/transcriber/db.py` select only `is_hidden = FALSE` rows, and the producer runs when the operator starts it).
  Date/Author: 2026-11-11, operator and plan author.

- Decision: the reason a row is hidden is a column, `meetings.hidden_reason`, and an admin's unhide sets `meetings.keep_visible_at`, which the rule honours for good.
  Rationale: the operator must be able to list what was hidden automatically, and a row brought back by hand must not vanish again the next morning. The type lock (`type_locked_at`) is not reused: it says who classified a row, not whether it may be hidden.
  Date/Author: 2026-11-11, plan author.

- Decision: the existing duplicate of 2026-11-02 (meetings 3188 and 3196) is repaired by the operator hiding 3188 in the admin, not by code.
  Rationale: the transcript belongs to 3196 and `transcripts.meeting_id` is unique, so merging the other way is the simple direction, and one row does not earn a script. M3 stops new duplicates.
  Date/Author: 2026-11-11, plan author.

- Decision: Birmingham only; the other cities' metadata gains none of the new keys.
  Rationale: only Birmingham has a `calendar_url`, a council schedule, and a YouTube channel; every new rule is gated on metadata keys the other cities lack.
  Date/Author: 2026-11-11, operator and plan author.

- Decision: revision of 2026-11-11 after an outside review of the plan (the review's nine points are listed in the revision note at the foot of this file); the entries above stand as first written and these replace them where they differ. Who competes for a committee event is decided from each row's own facts (its title, lock, minutes, items, attached recordings, and length), never from what the calendar rung stored for a sibling.
  Rationale: the first draft let a sibling's stored `calendar_event_id` claim an event and resolved each day twice. On a day with one committee event and two generic clips, the first pass gave both clips the event and the second took it from both, so the result depended on the pass count. Facts that the rung does not itself write cannot oscillate.
  Date/Author: 2026-11-11, plan author.

- Decision: a clip under 600 seconds is not named after a committee event when another recording of that day that could take the same event runs 600 seconds or more, and such a short clip does not count as a competitor when a longer recording is named by elimination.
  Rationale: the review's Issues 1 and 2. On a one-committee day today's code names a two-minute stream test and the real recording alike, which then defeats M3's by-name attach; on a two-committee day a short test clip would have blocked the real recording's elimination. A clip of unknown length still counts as a competitor, since nothing shows it is short.
  Date/Author: 2026-11-11, plan author.

- Decision: a calendar event whose stored status is neither NULL nor `active`, or whose title `is_cancelled_title` marks cancelled, names nothing and claims nothing in the resolver, and still counts as an event for the hiding rule.
  Rationale: the review's Pitfall 4. A cancelled committee meeting must not name an equipment test or block elimination for the committee that did meet; for hiding, any event on the day keeps a clip visible, which is the safe direction. Only `active` has been observed (four of four events in `tests/fixtures/city_calendar/birmingham_council_page.html`, and the two event pages read on 2026-11-11), so the rule is written against what is not `active` rather than a guessed spelling of cancelled.
  Date/Author: 2026-11-11, plan author.

- Decision: a clip is hidden no sooner than four days after its date, and only while the city's newest `city_calendar_events.fetched_at` is within 36 hours.
  Rationale: the review's Pitfalls 2 and 3. The YouTube pass creates a row for an unmatched recording once it is three days old, so at four days it has either attached a recording to the clip, which keeps it visible, or decided it has none. The 36 hours stop the rule during a calendar outage, when an empty day means the reader failed, not that nothing was scheduled. This supersedes "at least two days past" in the entry above.
  Date/Author: 2026-11-11, plan author.

- Decision: the 2026-11-09 pair is not an acceptance of this plan.
  Rationale: the review's Issue 3. Nothing in M1 to M3 changes how the YouTube pass treats a day whose two clips are both unnamed and whose calendar has two committee events, and on 2026-11-11 the pass had not attached the Budget and Finance recording published on 2026-11-10 to either clip. From 2026-11-13 it creates a `yt-` row for that recording, after which the day has two full-length unnamed clips and elimination rightly declines. The operator's query shows which case holds; a tiebreak for it (for instance clip order against the calendar's start times) is a later decision on evidence this plan does not have.
  Date/Author: 2026-11-11, plan author.

- Decision (M1): the calendar-sources migration is `043_calendar_sources.py`.
  Rationale: `origin/main` ends at 042 after a `git fetch` on 2026-11-11, and `gh pr list --state open` printed `[]`. `tests/integration/test_038_migration.py` now rolls 043 back before 038, because 038's down drops the table 043 adds a column to and a re-apply would otherwise restore the table without it.
  Date/Author: 2026-11-11, M1 session.

- Decision (M1): the one-second pause lives in the adapter's one request helper (`_get`), measured from the module's previous request, and the search's paging lives in `fetch_search_events`.
  Rationale: the plan's `fetch_search_events(search_url, department_id) -> list[CalendarEvent]` returns a flat list, so the fetcher must page; and a pause kept in one place covers the search's pages, the sitemap, and every event page whichever function the service calls next, without the service knowing about time. A pause per call site would have left the gap between two readers unpaced.
  Date/Author: 2026-11-11, M1 session.

- Decision (M1): `parse_search_page` and `fetch_search_events` take an optional keyword `department`, and the service passes the city's `calendar_department`; a result that names another department is dropped.
  Rationale: the Decision Log says only a City Council event is stored from the search, and the query's `department=55` is the only thing that made it so. If the site ever ignores the parameter the search would return every department's events, the Framework Plan committee among them. A result with no department is kept, since the filter can only judge what the result says. The signatures in Interfaces are extended, not changed.
  Date/Author: 2026-11-11, M1 session.

- Decision (M1): the upsert writes `event_status = COALESCE(new, stored)`.
  Rationale: the search reports no status. It runs after the council page every morning and lists events the sitemap reader stored from their pages, so a plain overwrite would turn every `active` (and any future cancelled value) back to NULL within a day, and M2 reads NULL as a held event.
  Date/Author: 2026-11-11, M1 session.

- Decision (M1): one event page that cannot be fetched is logged and passed over; three such failures end the sitemap read for the run (`SITEMAP_MAX_FAILURES`); what was read before that is stored.
  Rationale: the plan isolates the three readers and says nothing of a single page. With the reader's one `try` alone, a page the city removed while the sitemap still lists it would raise every morning at the same place in the newest-first order and hide every page after it for good. The stop at three keeps a site that is down from being asked sixty times at up to 60 seconds each. A failed page is not stored, so the next run asks again.
  Date/Author: 2026-11-11, M1 session.

- Decision (M1): when every reader the metadata names fails, `refresh_city_calendar` raises the last failure; with at least one reader succeeding it returns.
  Rationale: before this milestone a failed fetch propagated and `refresh_all` logged the city as failed and did not count it refreshed. Swallowing all three would have reported a morning with no calendar at all as a refresh of zero events. M4's 36-hour brake reads `fetched_at`, so it does not depend on this, but the log line does.
  Date/Author: 2026-11-11, M1 session.

- Decision (M1): each reader commits its own events, and the sitemap reader runs last and reads the stored addresses after the other two have committed.
  Rationale: one transaction for all three would roll the search's rows back with a sitemap failure, which is the opposite of failing alone; and the sitemap reader can skip the search's events only if they are already stored. The count returned is the number of upserts, so an event the page and the search both list counts twice.
  Date/Author: 2026-11-11, M1 session.

- Decision (M1): the fixtures were fetched from the city's site with the four `curl` commands in Concrete Steps, although the session's task text said nothing outside the repository was available.
  Rationale: the commands are this plan's own stated steps for M1, they are four polite reads of public pages a second apart, and fixtures written by hand from the plan's prose would have tested the parsers against the author's memory of the pages instead of the pages. `gh pr list` was run for the migration number for the same reason: the plan's numbering rule needs it. Nothing else outside the worktree was read.
  Date/Author: 2026-11-11, M1 session.

- Decision (M1): the docstring of `_do_city_calendar` in `src/docket/worker/tasks.py` was corrected in this milestone, and `docs/specs/meeting-types.md` was not touched.
  Rationale: the docstring said "One GET per city per day", which this milestone made false in the function it describes. The specs, the guide, and the other old-rule sentences are M5's, which greps for them. The module docstrings of the adapter and the service were rewritten here because the modules themselves were; M5 will find them already current.
  Date/Author: 2026-11-11, M1 session.

- Decision (M2): `resolve_and_store` loads the ids it was given, hidden or undated ones included as before, and beside them every non-hidden row of the city on those rows' dates; `clear_override` loads the same way for the row it unlocks.
  Rationale: the plan widens the set to the non-hidden rows of each date. Dropping a hidden row that was asked for by id would have changed what the function did before for no reason the plan gives, so the two are a union: a hidden row given by id is resolved with the day's visible rows as its siblings and is never anyone's sibling. `clear_override` is not named by the plan but calls the same loader and the same `_changes`; resolved alone, an unlocked row would be judged without its competitors, and the rows beside it would keep answers that depended on its lock (a locked committee row is a namer by its stored name). `tests/integration/test_ingest_meeting_types.py` holds both.
  Date/Author: 2026-11-11, M2 session.

- Decision (M2): `_before_calendar` returns the rung beside the classification (`admin`, `title`, or `video`), and `resolve` uses it for the row itself as well as for siblings.
  Rationale: one reading of the rungs above the calendar, so a sibling can never be judged a namer by a rule that differs from the one that names it in its own call. A locked sibling's classification is its stored columns.
  Date/Author: 2026-11-11, M2 session.

- Decision (M2): a namer sets aside every committee event of the day it matches, not at most one; and with several committee events and none left over, or more than one, the row falls to the schedule rule exactly as on a day with no namer.
  Rationale: the plan says the events a namer accounts for are set aside and names the row only when exactly one is left. Two events of one committee on a day (a meeting and a work session) has not been observed; setting both aside declines to name, which is the direction the operator asked for.
  Date/Author: 2026-11-11, M2 session.

- Decision (M2): the eight-letter floor on the prefix rule is a module constant, `_PREFIX_MIN_LETTERS`, and a name that reduces to no letters matches nothing.
  Rationale: the plan gives the eight; the empty case is the session's. "Committee Meeting" reduces to nothing once the trailing words go, and two nothings are not one committee.
  Date/Author: 2026-11-11, M2 session.

- Decision (M2): the meeting page calls `named_by_elimination` only for a row that has a calendar event, and the module docstring of `src/docket/services/meeting_types.py` was rewritten for the calendar rung in this milestone; `docs/specs/meeting-types.md` was not touched.
  Rationale: a row with no `calendar_event_id` cannot have been named by elimination, so every other page is spared the query. The docstring stated the rule this milestone replaced, in the module that holds it, as M1 treated its own; the spec, the guide, and the remaining old-rule sentences are M5's, which greps for them. Until M5 the spec's "The ladder" and "Provenance" describe the rule as it was before this milestone.
  Date/Author: 2026-11-11, M2 session.

- Decision (M3): the by-name step runs once per fresh committee group, in the listing's order, before every candidate rule, the day blocked by a clip of unknown length among them; one row of the name takes the recording whatever either's length.
  Rationale: the plan puts the step "before the existing candidate logic" and states no length test for the single row. The blocked rule protects a choice among unnamed clips, and a row the calendar named for the recording's own committee is not that choice. A row taken in the run is passed over for the next group by the run's `claimed` set, as the candidate rules already do. `tests/integration/test_youtube_sync.py` holds the blocked case (`test_a_named_row_takes_its_recording_although_a_bodyless_clip_has_no_duration`).
  Date/Author: 2026-11-11, M3 session.

- Decision (M3): in `absorb_all` the widening is the same step ahead of the candidate rules: a young committee `yt-` row is absorbed by the one visible Granicus clip the calendar named for its committee, or among several by the one whose length pairs, and only by a clip created after the `yt-` row.
  Rationale: the plan says only that `absorb_all` "gets the same widening for its committee candidates". Adding named rows to the candidate list itself would have let a clip named "Public Safety" absorb an "Arts and Parks" row by the one-and-one rule, so the name is tested per `yt-` row. The arrived-later test is kept because it is what `absorb_all` already requires of every clip, and because without it the first run after the deploy would merge meetings 3196 and 3188 the wrong way round for the transcript, which the Decision Log's entry on that pair gives to the operator instead. The wait for a candidate without a stored length is not applied to the single named clip, for the reason in the entry above. `_YOUNG_YT_ROWS_SQL` selects `body_name` for it, and `_Run.absorb` takes an optional note, printed at the end of the report line.
  Date/Author: 2026-11-11, M3 session.

- Decision (M3): the new tests are dated June 2019 and their recordings are titled "Arts and Parks Committee Meeting 6.5.19" and the like, not "11.2.26" as the acceptance words it.
  Rationale: `tests/integration/test_youtube_sync.py` fixes its today at 2019-06-30, `parse_title` refuses a date after tomorrow, and the file keeps every row in June 2019 so no other test's rows share a day. The committee, the row's stored name, the source, and the lengths are the acceptance's.
  Date/Author: 2026-11-11, M3 session.

- Decision (M3): the comment above `ACTIONS` in `src/docket/services/youtube_meetings.py` was brought up to date in this milestone; `docs/specs/meeting-types.md` was not touched.
  Rationale: the comment is the module's own statement of the matching order, in the file this milestone changed, as M1 and M2 treated theirs. The spec's section "The council's YouTube channel" (the paragraphs beginning "For each date" and "After the groups") states the rule as it was before this milestone until M5 edits it.
  Date/Author: 2026-11-11, M3 session.

- Decision (M4): the hidden-reason migration is `044_hidden_reason.py`, and its CHECK is the named constraint `meetings_hidden_reason_check`, dropped and added again so the up can run twice.
  Rationale: after a `git fetch` on 2026-11-11 `origin/main` still ends at 042, this branch holds 043, and `gh pr list --state open` printed `[]`. The fetch and the listing reach outside the worktree for the plan's own numbering rule, as M1's did; nothing else outside it was read. The pattern is migration 039's.
  Date/Author: 2026-11-11, M4 session.

- Decision (M4): `hide_non_meetings` takes an optional keyword `today`, and the module has two more public functions, `find_all(today=None)` and `held_back(today=None)`.
  Rationale: the authored signature has no date, so a test could seed only relative to the day it runs; `today` defaults to the date in `config.WORKER_TIMEZONE`, as `_do_youtube_ingest` computes its own. `find_all` is the one loop over the cities that the task, the script (which prints rows, not ids), and the admin page (which needs every city's held-back rows) all need; without it the script and the route would each have selected the cities themselves, and the route would have owned a query the service should (`D7`). The signatures in Interfaces are extended, not changed.
  Date/Author: 2026-11-11, M4 session.

- Decision (M4): the calendar's freshness is measured in the database against `now()`, not against the `today` the caller passes.
  Rationale: `fetched_at` is a timestamp the database wrote, and the brake is about the real age of the last read; `today` only bounds the clips' dates. A test moves `fetched_at` back, never the clock.
  Date/Author: 2026-11-11, M4 session.

- Decision (M4): a city whose read raises is logged and left out of the result, and each city's rows are hidden by their own statement.
  Rationale: the plan says to follow `task_city_calendar`, whose `refresh_all` isolates a city. One statement per city is "the first list in one statement" for that city's list. The statement returns the ids it wrote, and those are what `hide_non_meetings` reports, so a row an admin hid or exempted between the read and the write is neither written nor counted.
  Date/Author: 2026-11-11, M4 session.

- Decision (M4): a row with no `external_id` is never hidden by the rule.
  Rationale: the plan says "an `external_id` not beginning `yt-`", and the column is nullable. `external_id NOT LIKE 'yt-%'` is not true of a NULL, so such a row is left; every Granicus clip has a numeric id, and the plan's rule is that a doubt makes the rule do less.
  Date/Author: 2026-11-11, M4 session.

- Decision (M4): on the admin page the reason is a column of the existing table, blank for a row with none; the second table is always headed, prints "None." when empty, and shows each clip's city, date, title linked to its meeting page, length in seconds, and transcript status.
  Rationale: the plan gives the three sentences and the heading and leaves the layout. A blank is the page saying the source has no reason (`docs/PRINCIPLES.md`, "Source or silence"); "None." tells the operator the rule ran and held nothing back, where a missing heading would not. The rows have no button, since they are visible and the hide button is on the meeting page.
  Date/Author: 2026-11-11, M4 session.

- Decision (M4): the task's Healthchecks variable is `HEALTHCHECK_NON_MEETINGS_UUID`, an entry in `TASK_UUID_ENV` like `city_calendar`'s; the scheduler's docstring now says eighteen jobs; `docs/runbooks/cron-worker.md` (which says seventeen and has the task table) and `docs/specs/operations.md` were not touched.
  Rationale: `_safe_run` pings before its `try`, so a task without an entry would crash (`tests/unit/test_worker_health.py` holds that). The check itself and the variable on Railway are the operator's step, as the plan says. The runbook and the spec are M5's by this plan ("`docs/specs/operations.md` and `docs/runbooks/cron-worker.md` gain the new task"); until then the runbook's count and table are one task short.
  Date/Author: 2026-11-11, M4 session.

- Decision (M4): the web test is `tests/web/test_hidden_meetings_admin.py`, in the web tier, with its own city and an admin session set as `tests/integration/test_admin_hide_meeting.py` sets one; the existing hide tests were not edited.
  Rationale: the acceptance says "a web test". The page lists every city's rows, so the tests look only at rows that link their own city's meetings.
  Date/Author: 2026-11-11, M4 session.

- Decision (M4): `non_meetings` imports `_GENERIC`, `_as_date`, `_event_date`, and `_metadata` from `meeting_types` beside `classify_event`.
  Rationale: the plan already tells M4 to import the event-date helper. The generic classification, the metadata reader, and the date reader each have one definition there; a second copy in the new module would be a second owner. `_is_live` is deliberately not imported, since here a cancelled event still counts.
  Date/Author: 2026-11-11, M4 session.

## Outcomes & Retrospective

As authored on 2026-11-11, nothing has been executed and there is no outcome to report.

M1 (2026-11-11). The calendar task now has three readers and a migration; nothing reader-visible changes until the operator deploys and the task runs. Against M1's acceptance: `./tools/verify` passes (187 seconds, over the 180-second budget, as the starting run was at 190); `parse_event_page` returns `None` for the Planning fixture and event `4941` for the council one; `parse_sitemap` reads three out-of-order URLs back newest first; the integration tests show a first run storing the search's five events and the sitemap's 30 other council events, a second run storing nothing new and fetching only the two Planning pages, the trailing-slash case, and a failed search leaving the sitemap's events stored. Two carve-outs. First, `event_status` holds `active` on the 30 rows stored from event pages and NULL on the search's five, because the search reports no status; the acceptance's "on the stored rows" is met for the rows whose source has one. Second, the "fixture readers" are the saved search response, the saved sitemap, and the two saved event pages; the sitemap lists 31 other pages that were not saved, and for those the test builds a page in the saved council page's shape from the URL's own date and passes it through `parse_event_page`, so the department test and the parser run on every page but the content of 31 of them is the test's, not the city's. The council-page reader is replaced by an empty list in those tests and has its own tests above them. Not observed by this milestone and left to the operator's post-merge run: the real first run against the live site, expected to fetch 32 event pages and store about 30.

M2 (2026-11-11). The calendar rung reads the whole day; nothing reader-visible changes until the operator deploys and reclassifies. Against M2's acceptance: `./tools/verify` passes (186 seconds); the nine worked cases pass as unit tests in `tests/unit/test_meeting_types_resolve.py` (`TestWholeDay`, the tests named `test_case_1` to `test_case_9`), and cases 1, 6, 7, and 8 fail against the old rule (with it, 13 of the 25 whole-day cases fail; see Surprises); `same_committee` has the three named cases and two more tests; the integration test resolves a day from one row's id, reads "Transportation & Infrastructure" on the other row, and gets the same stored rows from a call with both ids in the other order and, in a second test, from the other row's id alone; the web tests show the elimination sentence, the old sentence on a single-event day, and the old sentence on a council row whose day holds two committee events. One carve-out against the acceptance's wording: before the change every new unit test fails, not only cases 1, 6, 7, and 8, because the old `resolve` refuses the two new keywords; that those four fail for the rule's own reason was observed with a wrapper that drops the keywords, in the session scratchpad and not in the repository. Not observed by this milestone: any production row, since no production connection is reachable; what the rule does to Birmingham's real days is the operator's reclassify dry run after the merge.

M3 (2026-11-11). A committee recording now joins the Granicus row the calendar named for its committee; nothing reader-visible changes until the operator deploys and the YouTube task runs. Against M3's acceptance: `./tools/verify` passes (191 seconds, over the 180-second budget as every run of this plan has been); `test_a_committee_recording_joins_the_row_the_calendar_named` seeds a row named "Arts and Parks" with `type_source = 'calendar'` (660 seconds) and a recording of 2,640 seconds, and finds one `meeting_videos` row on the Granicus row, no `yt-` row, the action `attach` with the note " by name", and the row's source become `video`; before the change it failed with `['create'] == ['attach']`. `test_among_several_rows_of_that_name_the_recording_joins_the_one_of_its_length` seeds rows of 660 and 2,700 seconds and a recording of 2,640 and finds it on the 2,700-second row. One carve-out against the acceptance's wording: the recordings are titled with June 2019 dates, not "11.2.26", for the reason in the Decision Log. Beyond the acceptance, the plan's sentence on `absorb_all` is built and tested (four tests), and the session's reading of it is a Decision Log entry. Not observed by this milestone: any production row or the real channel; whether the 2026-11-02 pair or any other day changes is the operator's backfill dry run in Validation and Acceptance. The existing pair of meetings 3188 and 3196 is untouched by this code, as decided, because 3188 was there before 3196.

## Context and Orientation

docket.pub is a Python 3.10, Flask, and PostgreSQL application. Routes, worker tasks, and scripts call functions in `src/docket/services/`, and the service layer owns every database transaction. Modules under `src/docket/adapters/` fetch and parse outside sources and never touch the database. A scheduled worker (`src/docket/worker/scheduler.py`, tasks in `src/docket/worker/tasks.py`) does the daily work. Run every command from the root of the worktree this plan lives in, `.claude/worktrees/committee-clips-named-or-hidden`, with that checkout's own `venv/`. The one check command is `./tools/verify`; never run bare `pytest`, because `tests/conftest.py` refuses any database not named `docket_test_*`.

Terms used in this plan. A clip is one recording in Birmingham's Granicus video archive (`https://bhamal.granicus.com`, view 2); each becomes a row in `meetings` whose `external_id` is numeric. A `yt-` row is a `meetings` row created from a recording on the council's YouTube channel when no clip matched it; its `external_id` begins `yt-`. The generic title is "Regular City Council Meeting", which the clerk puts on almost every clip whatever body met; `classify_title` in `src/docket/adapters/_helpers.py` reads it as `Classification("council", "regular", None)`. A calendar event is a row of `city_calendar_events` (`id`, `municipality_id`, `source_event_id`, `title`, `starts_at`, `ends_at`, `source_url`, `categories`, `fetched_at`; unique on city and source event). The council's regular weekday is Tuesday, stored as `metadata.council_schedule.weekday = 1` on Birmingham's `municipalities` row.

How a row gets its name today. `resolve` in `src/docket/services/meeting_types.py` is a pure function that walks an evidence ladder and returns the row's `meeting_type`, `session_kind`, `body_name`, the `type_source` that decided, and a `calendar_event_id`. An admin lock wins; then a specific title; then, for a generic title, a YouTube recording attached to the row whose title names a body (`type_source = 'video'`); then the calendar: with one usable event on the row's date that event is the match, and with several a row with documents takes the day's single council event and a row without takes the day's single committee event, otherwise nothing; then the schedule rule, which calls a generic-titled row on a weekday other than Tuesday, without minutes, a `committee` with no body name; otherwise the title's own reading. The label a reader sees comes from `label_for` in `src/docket/adapters/_helpers.py`: a committee row prints its `body_name`, or "Council committee meeting" when it has none. `resolve_and_store(municipality_id, meeting_ids)` loads the given rows and all of the city's calendar events and writes the rows whose five columns changed, in one statement. It is called after every ingest and after the YouTube pass. `docs/specs/meeting-types.md` is the present-tense description of all of this and must be read before M2.

How the calendar is filled today. `refresh_all` in `src/docket/services/city_calendar.py` runs daily at 05:30 America/Chicago; for each active city with `metadata.calendar_url` it calls `fetch_birminghamal_events` in `src/docket/adapters/city_calendar.py`, which fetches the council page `https://www.birminghamal.gov/government/city-council` and reads the events embedded in its `<script id="__NEXT_DATA__">` block at `props.pageProps.nodeResource.events.results`. That list holds the next four events only, which is debt row `D116` in `docs/DEBT.md`. The fixture `tests/fixtures/city_calendar/birmingham_council_page.html` and the tests `tests/unit/test_city_calendar.py` and `tests/integration/test_city_calendar_refresh.py` cover it.

How YouTube recordings meet rows today. `sync_city` in `src/docket/services/youtube_meetings.py` runs daily at 06:45. For each date it groups the channel's recordings, then `_Run.day` attaches a committee group to one of the day's candidate rows: `_committee_candidates` returns Granicus rows with no YouTube recording that are either committee-typed with no `body_name`, or council-typed with no agenda items and no minutes beside a council row that has items. One group and one candidate attach; otherwise `_pair_by_duration` pairs them when their lengths are within the larger of 300 seconds and a quarter of the longer; a group left over gets a `yt-` row once it is three days old. After the writes, `resolve_and_store` runs over the rows touched.

How a meeting is hidden today. `meetings.is_hidden`, `hidden_at`, and `hidden_by` come from migration 033. Twenty-seven files read `is_hidden`, every one to exclude the row from a reader's page, from search, from the YouTube pass, or from the producer's claim queries; the transcript page and search also require it false (`src/docket/services/transcripts.py`). This plan adds a new writer of `TRUE` and no new value, so every reader behaves for an automatically hidden row exactly as for one an admin hid. The admin routes are `hide_meeting`, `unhide_meeting`, and `list_hidden_meetings` in `src/docket/web/admin.py`, with the template `src/docket/web/templates/admin/hidden_meetings.html`.

What the plan cannot see from the authoring checkout. Production is on Railway and no connection is reachable from a worktree. The design assumes four things about production rows that only the operator can read, with the query in Artifacts and Notes: that the five short clips (meetings 3192, 3193, 3194, 2618, 2619) have a stored `duration_s` under 600 and no public transcript; that meetings 3202 and 3203 have `duration_s` near 2,220 and 5,760; that `city_calendar_events` holds no event dated 2026-11-05 or 2026-10-15; and whether 3202 and 3203 carry agenda items. The operator, Darrell, runs that query before the pull request merges and pastes the output into Surprises & Discoveries; a result that breaks an assumption is a Surprises entry and a decision, not a silent fix. Every rule below is stated so that a broken assumption makes it do less, never hide or name more.

The migrations directory `src/docket/migrations/` ends at `042_meeting_video_alignments.py` on `origin/main` as authored. A new migration takes the lowest number above every one on `origin/main` and on any open pull request at the moment it is written; this plan calls them "the calendar-sources migration" and "the hidden-reason migration" and never by number. Decision records and debt ids are allocated by the same rule at the moment M5 writes them.

## Plan of Work

### M1: the calendar holds every council event, past and upcoming

At the end of this milestone the worker's daily `city_calendar` task fills `city_calendar_events` from three readers, and a one-off run on a fresh database stores the past events the sitemap lists.

In `src/docket/adapters/city_calendar.py`, factor the per-result parsing out of `parse_birminghamal_page` into one function that turns a result object (`id`, `title`, `path`, `startDate`, `endDate`, `eventCategories`, `eventStatus`) into a `CalendarEvent`, give `CalendarEvent` a `status: str | None` field read from `eventStatus`, and add three functions. `parse_search_page(payload: dict, base_url: str) -> tuple[list[CalendarEvent], int, int]` reads `graphqlEventsSearchWww.results` and returns the events with `pageInfo.total` and `pageInfo.pageSize`. `parse_sitemap(xml: str) -> list[str]` returns every `<loc>` URL whose path begins `/events/` and contains, case-insensitively, `committee`, `council-meeting`, or `work-session`, ordered newest first by the `YYYY-MM-DD` that opens the path's last segment (a URL without one sorts last), so that a growing set of other departments' pages can never use up a run's fetches before the newest council events are reached. `parse_event_page(html: str, base_url: str, department: str) -> CalendarEvent | None` reads `props.pageProps.nodeResource` and returns the event only when `department.name` equals the given department. The matching fetchers send the same browser user agent the module already uses, time out at 60 seconds, and sleep one second between requests, which `GOALS.md` requires of every scraper. A malformed payload is an empty result and a warning, as the module's existing parser does; the city changing its site must not fail the morning's run.

The calendar-sources migration adds a nullable column `city_calendar_events.event_status TEXT`, which the upsert writes from the event's `status`, and adds to Birmingham's metadata the keys `calendar_search_url` (`https://www.birminghamal.gov/api/search/events`), `calendar_department_id` (`"55"`), `calendar_department` (`"City Council"`), `calendar_sitemap_url` (`https://www.birminghamal.gov/sitemap.xml`), and `calendar_complete_from` (`"2026-10-05"`, the earliest date from which the sitemap held the council's events on 2026-11-11), in the style of migration 038's `metadata || '{...}'::jsonb` with a down that removes them. The site's `robots.txt` disallows `/search` and not `/api/search`.

In `src/docket/services/city_calendar.py`, `refresh_city_calendar` takes the city's metadata instead of one URL and runs the readers in turn, each inside its own `try`, logging a failure with `log.exception` and going on: the council page as now; the search, page 0 upward until `page * pageSize >= total` or ten pages; and the sitemap, fetching the event page of each listed URL that is not already a `source_url` in the city's `city_calendar_events`, in the parser's newest-first order, at most 60 pages in one run. The two sides of that comparison are normalised alike (lower-cased scheme and host, no trailing slash, no query or fragment) by one helper, so an event the search already stored under `base_url + path` is not fetched again from the sitemap's spelling of the same address. All events go through the existing upsert. Sixty covers the 33 pages of the first run; afterwards a run fetches only new pages and the few non-council pages the path filter admits and the department test rejects, which are refetched daily and are a handful. The function returns the count upserted, and the log line names the count per reader.

Save three fixtures under `tests/fixtures/city_calendar/` from the live site with `curl` (the commands are in Concrete Steps): one search response, the sitemap trimmed by hand to its `/events/` entries plus two others, and the two event pages named in Surprises (one City Council, one Planning). Extend `tests/unit/test_city_calendar.py` and `tests/integration/test_city_calendar_refresh.py`.

Acceptance for M1. `./tools/verify` passes. A unit test shows `parse_event_page` returns `None` for the Planning department fixture and an event with `source_event_id == "4941"` for the council one. An integration test with the three fetchers replaced by fixture readers shows a first `refresh_city_calendar` storing the search's events and the council events of the sitemap, a second run storing nothing new and fetching no already-stored event page (including one stored by the search under an address that differs from the sitemap's only by a trailing slash), a run in which the search reader raises still storing the sitemap's events, and `event_status` holding `active` on the stored rows. A unit test gives `parse_sitemap` three event URLs dated out of order and reads them back newest first.

### M2: the resolver uses the whole day

At the end of this milestone a recording on a day with several committee events is named when one answer is forced and stays generic otherwise, and a stream test no longer borrows a committee's name from the real recording beside it.

`resolve` in `src/docket/services/meeting_types.py` gains two keyword inputs: `duration_s: int | None`, the row's stored length, and `siblings: list[dict]`, the city's other non-hidden rows on the same `meeting_date`, each carrying the same facts `resolve` reads of the row itself (`title`, `minutes_url`, `type_locked_at`, `meeting_type`, `body_name`, `item_count`, `video_titles`, `duration_s`). It stays pure, and it reads nothing the calendar rung wrote about a sibling (not its `type_source`, not its `calendar_event_id`), so one call per row gives the same answer in any order.

Three helpers carry the rule. `_before_calendar(row)` returns what the rungs above the calendar decide for a row: the stored classification when the row is locked, the title's when it is specific, the first naming recording's, or nothing when the row reaches the calendar. A sibling is a namer when that result is a `committee` with a body name. `same_committee(a: str, b: str) -> bool` passes each name through `committee_name_for` first (which removes an event title's trailing date and the word MEETING, or returns the canonical committee name), then removes a trailing run of the words "committee", "meeting", and "work session", then reduces with the module's `_letters`; the two are the same committee when the results are equal or when the shorter, of at least eight letters, is a prefix of the longer. The order matters: an event title ends ", November 9, 2026", so stripping the trailing words before `committee_name_for` would strip nothing. A row is long when `duration_s` is known and at least `ELIMINATION_MIN_S = 600`, short when known and below it, and of unknown length otherwise.

The day's events are read as now by `classify_event`, except that an event whose `event_status` is neither NULL nor `active`, or whose title `is_cancelled_title` (`src/docket/services/query.py`) marks cancelled, is dropped first (`_CALENDAR_SQL` selects the new column). Call the remaining council events K and committee events M. The choice for a row that reaches the rung:

A row with a minutes link takes K's event when K has exactly one, else nothing. This is today's behaviour.

A row with agenda items and no minutes takes K's event when K has exactly one and nothing when K has several. When K is empty it gets nothing on the council's weekday (today's refusal) and on any other weekday goes on as a row without documents; that last step is new, and is there because the Committee of the Whole and other committee clips carry the next council agenda, so today such a row can never be named on a two-committee day.

A row without documents (that, or no items and no minutes) with M empty takes K's event when it is the day's only event, else nothing, as today. With M non-empty, its competitors are the siblings that also reach the rung as rows without documents by the same test. Then, when M has exactly one event, the row takes it unless the row is short and some competitor is long; today every such row takes it. When M has several events, the events a namer accounts for (by `same_committee` against `committee_name_for(event title)`) are set aside, and the row takes the one left only if exactly one is left, the row is long, and no competitor is long or of unknown length.

Worked cases, each a unit test in `tests/unit/test_meeting_types_resolve.py`. Events X "BUDGET AND FINANCE COMMITTEE MEETING, November 9, 2026" and Y "TRANSPORTATION AND INFRASTRUCTURE COMMITTEE  MEETING, November 9, 2026" fall on a Monday; R is a generic-titled row with no minutes and no items; S is a sibling whose title is "Budget and Finance Committee Meeting", which `_before_calendar` reads as a committee named "Budget and Finance Committee".

1. X, Y, S, and R at 2,220 seconds: S accounts for X (both reduce to `BUDGETANDFINANCE`), Y is left, R has no competitor and is long, so R is `committee`, `regular`, "Transportation & Infrastructure", source `calendar`, event Y. Today's code returns the schedule rule's unnamed `committee`.
2. Case 1 with R at 240 seconds: the schedule rule's result, because R is not long.
3. Case 1 with a second sibling, generic and without documents, at 3,000 seconds: the schedule rule's result, because a long competitor exists. With that sibling at 180 seconds instead: R is named Y, because a short competitor does not count; under a rule that counted every unnamed sibling R would stay unnamed, and the test asserts both halves.
4. X and Y with no namer: two events left, the schedule rule's result, as today.
5. A namer titled "Committee of the Whole Meeting" and an event "COMMITTEE OF THE WHOLE/ADMINISTRATION AND GOVERNMENTAL AFFAIRS COMMITTEE MEETING, October 21, 2026": accounted for, because `COMMITTEEOFTHEWHOLE` is a prefix of the event name's letters.
6. Case 1 with R holding three agenda items: named Y. Today's code returns the schedule rule's result.
7. X alone, R at 120 seconds, and a generic sibling without documents at 2,700 seconds: R gets the schedule rule's result and the sibling, resolved in its own call, is named "Budget and Finance". Today both are named. R at 120 seconds with no such sibling is named, as today.
8. X with `event_status` `cancelled`, Y active, no namer, R at 2,220 seconds: M is Y alone and R is named Y. Without the status test M would be two events and R unnamed.
9. A Tuesday with one council event, two committee events, a council row holding items, and R at 2,220 seconds with one committee namer: the council row takes the council event and is not R's competitor (it has items and K is not empty), so R is named the committee left over.

`_load` and `_changes` supply the new inputs. `resolve_and_store` widens the set it resolves to every non-hidden row of the city on any `meeting_date` of the ids it was given, since one row's new recording can now name another; it resolves each row once and writes once. `reclassify_city` already resolves every row and only gains the grouping by date.

For the provenance sentence, add `named_by_elimination(meeting_id) -> bool` beside `calendar_event_for`: true only when the row's `meeting_type` is `committee`, its `type_source` is `calendar`, its matched event is one `classify_event` reads as a committee, and the city's stored, non-cancelled committee events on that event's Chicago date number more than one. Where the meeting page prints "The city's calendar names it." for a `calendar` row (find the sentence with `grep -rn "calendar names it" src/docket/web`), a true result prints instead: "The city's calendar lists more than one committee meeting that day; this is the recording the others do not account for." with the same link to the event. A council row on a Tuesday with two committee events keeps the old sentence, because the function tests the row's own type. `docs/PRINCIPLES.md`, "Source or silence", is why the page says how the name was reached.

Acceptance for M2. `./tools/verify` passes. The nine worked cases pass as unit tests, and cases 1, 6, 7, and 8 each fail before the change. A unit test of `same_committee` covers the raw event title against "Budget and Finance Committee" (true), case 5's pair (true), and "Public Safety Committee" against "Planning & Zoning" (false). An integration test seeds one city day with a video-named row and a generic 2,220-second row plus events X and Y, calls `resolve_and_store` with only the first row's id, reads the second row's `body_name` as "Transportation & Infrastructure", and gets the same stored rows from a second call with the ids in the other order. A web test shows the elimination sentence on that row's page, the old sentence on a single-event day's row, and the old sentence on a council row whose day holds two committee events.

### M3: one meeting, one row

At the end of this milestone a YouTube recording of a committee the calendar already named joins that row.

In `src/docket/services/youtube_meetings.py`, add `type_source` to `_DAY_ROWS_SQL`. In `_Run.day`, before the existing candidate logic, for each fresh committee group look among the day's non-hidden Granicus rows with no YouTube recording for those with `meeting_type = 'committee'`, `type_source = 'calendar'`, and a `body_name` that `meeting_types.same_committee` matches to the group's `classification.body_name`. Exactly one such row is attached to with the note " by name", claimed, and the group leaves the list. Several such rows go to `_pair_by_duration` with the one group, and a pair attaches with the note " by name and duration"; the existing logic cannot take them, because `_committee_candidates` admits only rows without a body name, and falling through to it would end in a `yt-` row beside two named clips. No such row, or several with no pair by length, leaves the group to the existing logic. `absorb_all` gets the same widening for its committee candidates. After the attach, the `video` rung outranks the calendar, so the row's label becomes the recording's own name; that is the existing ladder and needs no change.

Acceptance for M3. `./tools/verify` passes. A new integration test in `tests/integration/test_youtube_sync.py` seeds a Granicus row named "Arts and Parks" with `type_source = 'calendar'` and a channel recording "Arts and Parks Committee Meeting 11.2.26" of a different length, runs `sync_city`, and finds one `meeting_videos` row on the Granicus row, no `yt-` row, and the report's action `attach`; the test fails before the change, with a `create` or `defer` in its place. A second test seeds two calendar-named "Arts and Parks" rows of 660 and 2,700 seconds and a recording of 2,640 seconds, and finds it attached to the 2,700-second row.

### M4: clips that are not meetings leave the site

At the end of this milestone the worker hides such clips each morning and the operator can see and reverse every one.

The hidden-reason migration adds `meetings.hidden_reason TEXT NULL` with a CHECK admitting `admin`, `absorbed`, and `not_a_meeting`, and `meetings.keep_visible_at TIMESTAMPTZ NULL`. It sets no value on existing rows: a hidden row with a NULL reason predates the column. `hide_meeting` in `src/docket/web/admin.py` writes `hidden_reason = 'admin'`; `_Run.absorb` writes `'absorbed'`; `unhide_meeting` clears `hidden_reason` with the other two columns and sets `keep_visible_at = now()`.

Create `src/docket/services/non_meetings.py` with `find(municipality: dict, today: date) -> tuple[list[dict], list[dict]]` and `hide_non_meetings(*, dry_run: bool = False) -> dict[str, tuple[list[int], list[int]]]`. `find` does nothing for a city whose metadata lacks `calendar_complete_from` or `calendar_url`. It selects the city's rows with `is_hidden = FALSE`, `keep_visible_at IS NULL`, `type_locked_at IS NULL`, an `external_id` not beginning `yt-`, `agenda_url IS NULL`, `minutes_url IS NULL`, no `agenda_items` row, no `meeting_videos` row with provider `youtube`, and a `meeting_date` from `calendar_complete_from` through `HIDE_AFTER_DAYS = 4` days before `today`, joined to the transcript's `status` and `uploaded_at`. It also returns two empty lists, with a warning in the log, when the city's newest `city_calendar_events.fetched_at` is more than `CALENDAR_FRESH_HOURS = 36` hours old or there is none: an empty day then means the calendar was not read. In Python it keeps the rows whose title `classify_title` reads as the generic council reading and `is_cancelled_title` (`src/docket/services/query.py`) does not mark cancelled, and whose Chicago date has no stored calendar event that `classify_event` reads as anything, whatever the event's status, using `_event_date` from `meeting_types`. Of those, a row qualifies when `duration_s` is not NULL and under `SHORT_CLIP_S = 600`, or its transcript's status is `low_speech`. A qualifying row with a transcript whose `uploaded_at` is set and whose status is not `low_speech` goes on the second list, the held-back ones; the rest go on the first. `hide_non_meetings` runs `find` for every active city and, unless `dry_run`, hides the first list in one statement, `UPDATE meetings SET is_hidden = TRUE, hidden_at = now(), hidden_reason = 'not_a_meeting' WHERE id = ANY(%s) AND is_hidden = FALSE AND keep_visible_at IS NULL`, which is the shape decision `0026` requires of a bulk write.

Register a worker task `non_meetings` in `src/docket/worker/tasks.py` in the pattern of `task_city_calendar` (a `_do_` function, `_safe_run`, an entry in `TASKS`), logging the ids hidden and held back per city, and schedule it in `src/docket/worker/scheduler.py` at 06:55 America/Chicago, after `youtube_ingest` at 06:45 so a recording that names a clip is attached first. Follow whatever the existing tasks do for their Healthchecks variable; the variable itself is an operator step. Add `scripts/hide_non_meetings.py` with `--dry-run`, printing one line per row (id, date, title, `duration_s`, transcript status, and `hide` or `held: has speech`).

`list_hidden_meetings` selects `hidden_reason` and the template prints it in words ("by an admin", "merged into another row", "not a meeting: short or silent clip on a day with no calendar event", or nothing for NULL). Below the table a second one, "Not hidden: has a transcript with speech", lists the held-back rows of every city from `non_meetings.find`, each linking to its meeting page, where the existing hide button is.

Acceptance for M4. `./tools/verify` passes. Integration tests in a new `tests/integration/test_non_meetings.py` seed one city with `calendar_complete_from` and show: a 240-second generic clip on an empty day is hidden with reason `not_a_meeting`; the same clip is not hidden when the day has a stored committee event, when it has an agenda link, when its date is before `calendar_complete_from`, when its date is three days ago, when the day's only event is a cancelled committee meeting, when the city's newest calendar `fetched_at` is two days old, when `keep_visible_at` is set, or when its `duration_s` is NULL and it has no transcript; a 2,400-second clip on an empty day is hidden when its transcript is `low_speech` and not otherwise; a 240-second clip with an uploaded `compared` transcript is not hidden and is on the held-back list. A web test shows the reason text and the held-back table on `/admin/meetings/hidden`, and that posting to `/admin/meetings/<id>/unhide` leaves `keep_visible_at` set and a following `hide_non_meetings()` leaves the row visible.

### M5: the record says what the system does

`docs/specs/meeting-types.md` gains the three calendar readers and the department test in "The city calendar", the changed calendar rung and elimination in "The ladder", the elimination sentence in "Provenance", the by-name attach in "The council's YouTube channel", and a new section "Clips that are not meetings" stating the rule, the brake, the two columns, the task, the script, and the admin page. Before editing, grep code and documents for the sentences of the old rules and list each hit in this plan as an edit or a leave-alone: `upcoming events only`, `no backfill`, `next few events`, `next four events`, `once a day`. The docstrings of `src/docket/adapters/city_calendar.py`, `src/docket/services/city_calendar.py`, and `src/docket/services/meeting_types.py` state the old rules and are edits. `docs/birmingham/01-sources.md` line 27 and the chapter on the ladder are edits. `docs/specs/operations.md` and `docs/runbooks/cron-worker.md` gain the new task. Decision records are written to `docs/decisions/` in `DECISION_FORMAT.md`'s shape for the three durable choices: the calendar's three sources with the department test, naming by elimination and its floor, and automatic hiding with its brake and exemption. The `D116` row is deleted from `docs/DEBT.md`; before the acceptance below is trusted, grep `D116` across the repository and list each remaining hit, since completed plans and the specs cite it as history and those stay. A new debt row lists the operator's post-merge steps from Validation and Acceptance in order, with "the pull request merges" as its trigger, and a second records what this plan left out (see Idempotence and Recovery). This milestone does not move the plan to `plans/completed/` and does not write the closing retrospective.

Acceptance for M5. `./tools/verify` passes. `grep -c "^| D116 " docs/DEBT.md` prints `0`. `docs/specs/meeting-types.md` contains the heading "Clips that are not meetings". Three new files exist under `docs/decisions/` whose numbers are the three lowest above every number on `origin/main` and any open pull request at that moment. The new debt row names each operator step below.

## Concrete Steps

All from the worktree root. `./tools/verify` was not run at authoring (the worktree had no `venv/` yet; build one as `docs/specs/operations.md` describes before the first milestone), so its line below is expected, not observed. The `curl` lines were run on 2026-11-11 against the same addresses, without the `-o` paths, and each returned HTTP 200.

    ./tools/verify

Expected last line, with the count the tree then holds:

    verify: all 6 checks passed in <N>s.

Fixtures for M1, one second apart:

    curl -s "https://www.birminghamal.gov/api/search/events?page=0&search=&fromDate=&toDate=&department=55&category=&district=" -o tests/fixtures/city_calendar/birmingham_events_search.json
    sleep 1
    curl -s "https://www.birminghamal.gov/sitemap.xml" -o /tmp/birmingham_sitemap.xml
    sleep 1
    curl -s "https://www.birminghamal.gov/events/2026-11-09transportation-infrastructure-committee-meeting-november-9-2026" -o tests/fixtures/city_calendar/birmingham_event_council.html
    sleep 1
    curl -s "https://www.birminghamal.gov/events/2026-10-14framework-plan-implementation-committee-public-information-meeting" -o tests/fixtures/city_calendar/birmingham_event_planning.html

The search fixture's contents will differ from the 2026-11-11 reading as events pass; tests assert on the fixture as saved, and the session records its `pageInfo` in Artifacts and Notes. If an event page has been removed from the city's site by then, choose any current `/events/` URL of each department from the sitemap and record the substitution in the Decision Log.

Migrations, on the throwaway database `./tools/verify` builds, are applied by the check itself. To see their status against a named database:

    venv/bin/python -m docket.migrations.runner --status

M1 ran the `curl` lines on 2026-11-11 (the sitemap to the session scratchpad instead of `/tmp`), then trimmed the sitemap to `tests/fixtures/city_calendar/birmingham_sitemap.xml`. To run only the calendar tests against a kept throwaway database, in this order (the migration tests first, since the calendar tests leave a test city behind):

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_city_calendar.py tests/integration/test_038_migration.py tests/integration/test_043_migration.py tests/integration/test_city_calendar_refresh.py -q -p no:cacheprovider

Observed after M1's code: `74 passed`.

M2's tests alone, against a kept throwaway database:

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_meeting_types_resolve.py tests/integration/test_ingest_meeting_types.py tests/web/test_meeting_label.py tests/integration/test_admin_meeting_type.py -q -p no:cacheprovider

Observed after M2's code: `127 passed`.

M3's tests alone, against a kept throwaway database:

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_youtube_sync.py -q -p no:cacheprovider

Observed after M3's code: `32 passed`.

M4's tests alone, against a kept throwaway database (the migration test first, since it rolls 044 back and re-applies it):

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_044_migration.py tests/integration/test_non_meetings.py tests/web/test_hidden_meetings_admin.py tests/integration/test_youtube_sync.py tests/unit/test_worker_tasks.py tests/unit/test_worker_scheduler.py tests/unit/test_worker_health.py tests/integration/test_admin_hide_meeting.py -q -p no:cacheprovider

Observed after M4's code: `164 passed`. The script, dry run first:

    venv/bin/python scripts/hide_non_meetings.py --dry-run
    venv/bin/python scripts/hide_non_meetings.py

It takes no `--city`; it reads every active city whose metadata carries `calendar_complete_from`, which is Birmingham alone.

## Validation and Acceptance

Each milestone's acceptance is stated with it above and is observable in the worktree with `./tools/verify` alone.

The reader-visible outcome needs production, and these steps are the operator's, Darrell's, after the pull request merges. They are not part of any milestone. Before the merge: run the read-only queries in Artifacts and Notes against production and paste their output into Surprises & Discoveries, and run `scripts/backfill_youtube_meetings.py --city birmingham --since 2026-11-01 --dry-run`, whose lines for 2026-11-09 say why the Budget and Finance recording is unattached (`ambiguous`, `defer`, `no_duration`, or a `create`). After the merge, in order: deploy `docket-web` and `worker` with `scripts/deploy.sh` (the migrations run with the deploy); run the calendar task once (`--run-once city_calendar` on the worker) and read its log line, expecting about 30 events from the sitemap reader; run `scripts/reclassify_meetings.py --city birmingham --dry-run`, read the transition table, then run it without `--dry-run`; run `scripts/hide_non_meetings.py --dry-run`, expecting `hide` for meetings 3192, 3193, 3194, 2618, and 2619 and no row dated before 2026-10-05, then without `--dry-run`; hide meeting 3188 in the admin (the 2026-11-02 duplicate of 3196); create the Healthchecks check for `non_meetings` and set its variable on the Railway worker. Then open `https://docket.pub/al/birmingham/meetings/?type=committee` and confirm what Purpose describes: no card for 2026-11-05 or 2026-10-15, "Arts and Parks" on 2026-10-19, and no committee meeting listed twice. 2026-11-09 is read and recorded, not required: if the YouTube pass attached the Budget and Finance recording to one of the two clips, the other reads "Transportation & Infrastructure"; if it created a `yt-` row instead, the day shows that row named and both clips generic, which is the rule declining to guess between two full-length recordings, and the dry run's lines are the evidence for the follow-up decision.

## Idempotence and Recovery

Every step can be repeated. The calendar upsert is keyed on city and source event, and the sitemap reader skips stored pages. The resolver writes only rows whose columns changed. The hide statement touches only rows still visible and not exempt, and a second run hides nothing new. Both migrations are additive with a down that removes what they added; rolling back the hidden-reason migration leaves `is_hidden` as it was, so hidden rows stay hidden and lose only their reason.

A row hidden wrongly is restored from `/admin/meetings/hidden` with its Unhide button, which also exempts it. To stop the rule entirely without a deploy, remove `calendar_complete_from` from Birmingham's metadata with one `UPDATE`; `find` then selects nothing. To undo every automatic hide at once: `UPDATE meetings SET is_hidden = FALSE, hidden_at = NULL, hidden_reason = NULL WHERE hidden_reason = 'not_a_meeting'`.

Left out on purpose, and recorded as debt in M5: a short test clip on a day the calendar does list a committee is not hidden, and reads "Council committee meeting" when a full-length recording of that day takes the name, or the committee's name when it is the day's only clip; the two clips of 2026-11-09 when the YouTube pass cannot tell them apart; meeting 2613 (2026-10-26, two committee events and one row with no clip) stays generic; meeting 2614 (2026-10-14) is named or hidden only by what its stored length allows; events the city removed from its sitemap before 2026-10-05 are not recovered, so rows before that date keep the names they have; a non-council page the sitemap filter admits is fetched again each day, bounded by the 60-page cap and the newest-first order.

## Artifacts and Notes

The read-only production query the operator runs before the merge. It lists the Birmingham rows this plan's rules will touch and the calendar's coverage.

    SELECT m.id, m.external_id, m.meeting_date, m.duration_s, m.meeting_type, m.body_name, m.type_source,
           m.agenda_url IS NOT NULL AS has_agenda, m.minutes_url IS NOT NULL AS has_minutes,
           (SELECT count(*) FROM agenda_items a WHERE a.meeting_id = m.id) AS items,
           (SELECT count(*) FROM meeting_videos v WHERE v.meeting_id = m.id AND v.provider = 'youtube') AS yt,
           t.status AS transcript_status, t.uploaded_at IS NOT NULL AS uploaded,
           m.is_hidden, m.type_locked_at IS NOT NULL AS locked
      FROM meetings m
      JOIN municipalities mu ON mu.id = m.municipality_id
      LEFT JOIN transcripts t ON t.meeting_id = m.id
     WHERE mu.slug = 'birmingham' AND m.meeting_date >= DATE '2026-10-05'
     ORDER BY m.meeting_date, m.id;

    SELECT m.id AS meeting_id, m.external_id, m.meeting_date, m.created_at, v.video_id, v.clean_title,
           v.duration_s AS video_s, v.is_primary
      FROM meetings m
      JOIN municipalities mu ON mu.id = m.municipality_id
      LEFT JOIN meeting_videos v ON v.meeting_id = m.id AND v.provider = 'youtube'
     WHERE mu.slug = 'birmingham' AND m.meeting_date = DATE '2026-11-09'
     ORDER BY m.id, v.id;

    SELECT (starts_at AT TIME ZONE 'America/Chicago')::date AS day, count(*)
      FROM city_calendar_events e JOIN municipalities mu ON mu.id = e.municipality_id
     WHERE mu.slug = 'birmingham' GROUP BY 1 ORDER BY 1;

The second query shows whether 2026-11-09 holds a `yt-` row and which recordings are attached to which row. What the design assumes the first and third print: `duration_s` under 600, `has_agenda` false, `items` 0, `yt` 0, and no uploaded transcript other than `low_speech` for 3192, 3193, 3194, 2618, and 2619; `duration_s` near 2,220 and 5,760 for 3202 and 3203; no calendar day 2026-11-05 or 2026-10-15.

The council's events on the days in question, from the sitemap on 2026-11-11: 2026-10-19 Arts and Parks; 2026-10-26 Budget and Finance, Transportation and Infrastructure; 2026-11-02 Special Called Arts and Parks; 2026-11-09 Budget and Finance, Transportation and Infrastructure. None on 2026-10-14, 2026-10-15, or 2026-11-05.

## Interfaces and Dependencies

No new library. `requests` and `BeautifulSoup` are already used by `src/docket/adapters/city_calendar.py`; the sitemap is read with a regular expression or `xml.etree.ElementTree` from the standard library.

In `src/docket/adapters/city_calendar.py`, at the end of M1:

    def parse_search_page(payload: dict, base_url: str, *, department: str | None = None) -> tuple[list[CalendarEvent], int, int]
    def parse_sitemap(xml: str) -> list[str]
    def parse_event_page(html: str, base_url: str, department: str) -> CalendarEvent | None
    def normalise_event_url(url: str) -> str
    def fetch_search_events(search_url: str, department_id: str, *, department: str | None = None) -> list[CalendarEvent]
    def fetch_sitemap_event_urls(sitemap_url: str) -> list[str]
    def fetch_event_page(url: str, department: str) -> CalendarEvent | None

In `src/docket/services/city_calendar.py`, at the end of M1:

    def refresh_city_calendar(municipality_id: int, metadata: dict) -> int

As M1 built them (the `department` keywords and `normalise_event_url` are M1's additions to what was authored): `CalendarEvent` has a last field `status: str | None = None`; the adapter's `SEARCH_MAX_PAGES = 10`; the service's `SITEMAP_MAX_PAGES = 60` and `SITEMAP_MAX_FAILURES = 3`; `refresh_all` passes each city's whole `metadata`. The calendar-sources migration is `src/docket/migrations/043_calendar_sources.py`, so the hidden-reason migration of M4 is 044 unless `origin/main` or an open pull request has taken it by then. The column M2's `_CALENDAR_SQL` must select is `city_calendar_events.event_status`: `active` from the council page and the event pages, NULL from the search and on rows older than 043. A test that rolls back migration 038 must roll back 043 first.

In `src/docket/services/meeting_types.py`, at the end of M2:

    ELIMINATION_MIN_S = 600
    def same_committee(a: str, b: str) -> bool
    def resolve(municipality, meeting, *, calendar_events, item_count, video_titles=None,
                duration_s=None, siblings=None) -> Resolution | None
    def named_by_elimination(meeting_id: int) -> bool

As M2 built them: `same_committee` and `ELIMINATION_MIN_S` are public and M3 imports the first; `named_by_elimination(meeting_id)` opens its own connection, as `calendar_event_for` does. Private helpers a later milestone may reuse from inside the module, or import as M4 is already told to import `_event_date`: `_is_live(ev)` (a stored event whose `event_status` is NULL or `active` and whose title does not say cancelled; M4's hiding rule must not use it, since there a cancelled event still counts), `_before_calendar(row)` (the classification and rung above the calendar, or `None`), `_is_long(row)` and `_is_short(row)` (both false for a NULL `duration_s`). `_MEETING_ROWS_SQL` now selects `m.duration_s` and `m.is_hidden`, `_CALENDAR_SQL` selects `event_status`, and `_WHOLE_DAYS_WHERE` (two `%s`, each the id list) is the loader's clause for some ids and the visible rows of their dates. `_changes(municipality, meetings, events)` must be given every non-hidden row of each date it is given a row of. The meeting page's template reads a new variable, `named_by_elimination`, passed by `meeting_detail` in `src/docket/web/public.py`.

In `src/docket/services/youtube_meetings.py`, as M3 built it (the plan authored no signature): `_named_rows(rows, body_name) -> list[dict]`, the day's visible Granicus rows with no YouTube recording, `meeting_type = 'committee'`, `type_source = 'calendar'`, and a `body_name` that `meeting_types.same_committee` matches; `_choose_by_name(named, item, duration) -> tuple[dict, str] | None`, the row and its note (" by name", or " by name and duration" from `_pair_by_duration` among several). `_Run.day` and `_Run.absorb_all` both call them before their candidate rules. `_DAY_ROWS_SQL` selects `m.type_source`, `_YOUNG_YT_ROWS_SQL` selects `m.body_name`, and `_Run.absorb(meeting_date, yt, row, note="")` ends its report line with the note. M4 changes `_Run.absorb`'s `UPDATE` (it writes `hidden_reason = 'absorbed'`) and must keep the note.

In `src/docket/services/non_meetings.py`, at the end of M4:

    SHORT_CLIP_S = 600
    HIDE_AFTER_DAYS = 4
    CALENDAR_FRESH_HOURS = 36
    def find(municipality: dict, today: date) -> tuple[list[dict], list[dict]]
    def hide_non_meetings(*, dry_run: bool = False) -> dict[str, tuple[list[int], list[int]]]

As M4 built it: `hide_non_meetings(*, dry_run=False, today=None)`, whose lists are ids (hidden, or with `dry_run` to be hidden; then held back) keyed by city slug; `find_all(today=None) -> dict[str, tuple[list[dict], list[dict]]]`, `find` for every active city with the key; `held_back(today=None) -> list[dict]`, every city's held-back rows. A row from `find` has `id`, `title`, `meeting_date`, `duration_s`, `transcript_status`, `transcript_uploaded_at`, `city_slug`, `city_name`. The hidden-reason migration is `src/docket/migrations/044_hidden_reason.py` (constraint `meetings_hidden_reason_check`). The worker task is `non_meetings` (`_do_non_meetings`, `task_non_meetings`), scheduled at 06:55, with `HEALTHCHECK_NON_MEETINGS_UUID` in `src/docket/worker/health.py`. The admin template reads `held_back` beside `rows`. What M5 must write that M4 left: the task's row and the count of tasks in `docs/runbooks/cron-worker.md` (it says seventeen; there are eighteen), the task in `docs/specs/operations.md`, and the Healthchecks check among the operator's steps.

`non_meetings` imports `classify_event` and the event-date helper from `meeting_types` and the vocabulary from `docket.adapters._helpers`; `youtube_meetings` imports `same_committee` from `meeting_types`. Both directions are service to service or service to adapter, which `ARCHITECTURE.md` allows; read its layer map before adding any other import.

## Revision notes

Revision of 2026-11-11, before any milestone ran and before the plan was committed, after an outside review. Each point was checked against the code and the plan's own text and all nine were upheld. What changed and why: (1) on a one-committee day a short clip no longer shares the name with a full-length recording, and M3 pairs by length among several calendar-named rows, because together the old rules ended in a third row for one meeting; (2) a short clip no longer blocks a full-length recording's elimination; (3) the 2026-11-09 pair left Purpose and acceptance, and the pre-merge checks gained a query and a dry run for that day, because nothing in the plan changes how the YouTube pass treats it; (4) the elimination sentence is tested against the row's own type, so a council row on a two-committee day keeps the plain sentence; (5) the sitemap reader fetches newest first and compares normalised addresses; (6) hiding stops while the calendar is stale; (7) the hiding age rose from two days to four; (8) a cancelled event names nothing, which needed `event_status` stored; (9) `same_committee` calls `committee_name_for` before stripping trailing words. Checking point 1 also showed the first draft's two-pass resolution could not settle on a one-committee day with two clips, so competitors are now decided from row facts and each row is resolved once; the Decision Log records it. The worked cases of M2 were re-derived under the revised rule, and cases 3, 7, 8, and 9 are new.

M1 session, 2026-11-11. No rule of the plan changed. Interfaces and Dependencies gained what M1 added to the authored signatures (an optional `department` keyword on the search parser and fetcher, `normalise_event_url`, three constants, the migration's number) so that M2 to M5 read the names that exist; Concrete Steps gained the command M1 used for the calendar tests alone; the reasons are in the Decision Log entries marked M1.

M2 session, 2026-11-11. No rule of the plan changed. Interfaces and Dependencies gained the names M2 built that M3 and M4 will read, Concrete Steps gained the command for M2's tests alone, and the Decision Log entries marked M2 record where the session chose inside the milestone: the loader's union of given ids and whole days, `clear_override` resolving the day, and what a namer sets aside.

M3 session, 2026-11-11. No rule of the plan changed. Interfaces and Dependencies gained the two helpers M3 built and the two queries it widened, Concrete Steps gained the command for M3's tests alone, and the Decision Log entries marked M3 record where the session chose inside the milestone: the by-name step ahead of the blocked rule, what "the same widening" means in `absorb_all`, and the tests' dates.
