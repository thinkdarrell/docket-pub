# Read the Birmingham council committees' agendas and minutes, and show what each committee took up and what it did

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

docket.pub can say that a Birmingham City Council committee met and can show the recording. It cannot say what the committee took up or what it did, because it reads no committee document. Almost every ordinance and resolution passes through a committee before the council votes, so this is the largest hole in the site's account of how a decision is made.

After this plan, a reader who opens a committee meeting's page, for example the Budget and Finance Committee meeting of 2026-10-12, sees links to the city's own agenda and minutes PDFs and, beneath them, the list of what the committee took up: each item's name, the text the minutes give for it, who moved and seconded, and the action the committee took in the minutes' own words ("Item Recommended to the City Council Consent Agenda."). A committee that met with no recording, such as the Economic and Workforce Development / Tourism Committee, appears as a meeting for the first time, because its minutes prove it met.

To see it working after the last milestone and the operator's backfill: open the page of the Transportation and Infrastructure Committee meeting of 2026-05-11 on the live site. It lists six items; the fifth is "Parking Reform Update", moved by O'Quinn, seconded by Smith, "Item Recommended to the City Council Agenda." The words can be found in the minutes PDF the page links.

This is the second of four phases of the design in `docs/superpowers/specs/2026-11-12-how-it-works-design.md` (section 8), which is on branch `plan/how-it-works-explainer` until that branch merges. This plan does not depend on that branch and repeats here everything it needs from the design.

## Progress

- [x] (2026-11-15 01:53Z) M1: A committee page's listing and a document's own header can be read: which committee, which date, agenda or minutes, proved on the saved fixtures.
- [x] (2026-11-15 02:15Z) M2: A minutes document's text is read into items, each with its name, text, action, action category, mover and seconder, proved on the saved fixtures.
- [x] (2026-11-15 02:43Z) M3: Two new tables hold documents and their items; a service lists, fetches, reads and stores them, and running it twice changes nothing the second time.
- [x] (2026-11-15 03:05Z) M4: Stored documents are attached to the committee meeting rows that already exist, and minutes for a meeting with no row create one; nothing is attached twice and no meeting is created twice.
- [ ] M5: A committee meeting's page shows its documents and what the committee took up.
- [ ] M6: A daily worker task keeps the documents current, and a script the operator runs from a laptop fills production and prints the per-committee counts.
- [ ] M7: The behaviour is written into `docs/specs/` and the Birmingham guide, the durable decisions are graduated, and the deferred work is recorded in `docs/DEBT.md`.

## Surprises & Discoveries

As authored on 2026-11-13, nothing has been executed and there are no discoveries from execution. What the authoring research found, which differs from what the design assumed, is in Context and Orientation under "What the documents are really like".

- Observation (M1, 2026-11-15): the starting state is green, and `./tools/verify` runs past its 180 second budget on this machine.
  Evidence: run before any edit, at commit `348d8aa`: `verify: all 6 checks passed in 207s.` (unit+web+services 91s, integration 108s). The budget in `AGENTS.md` is 180 s; nothing in this milestone touches either tier's running time.

- Observation (M1, 2026-11-15): the tests of M1 fail before the module exists, each on its own import, and the file collects.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_committee_documents_read.py -q -p no:cacheprovider` printed `17 failed, 1 warning in 0.49s` with `src/docket/adapters/committee_documents.py` absent. The commit that adds the test file holds this state.

- Observation (M1, 2026-11-15): the plan's year rule could not read the plan's own example. The rule said the year is `19` or `20` followed by two characters that are digits or the letter O; the test value "TUESDAY, May 26, 2O26" has its O in the second place, so the year does not begin `20` until the O is read as zero.
  Evidence: under the rule as first written, `re.search(r"(?:19|20)[0-9O]{2}", "2O26")` is None, and the stated result `(2026, 5, 26)` cannot be produced. The rule text in M1 is mended (see the Decision Log and the revision note at the foot of this file); the test asserts the stated result and passes.

- Observation (M1, 2026-11-15): the Planning and Zoning page fixture holds 25 `<h4>` headings, not 15. Ten have no document under them: nine read "... - MEETING CANCELLED" (one of them printed "0CT0BER 27, 2026", with zeros for the letter O) and one is a single non-breaking space. The 27 listings sit under the other 15, each of which `read_date` reads to a full date, "MAY12, 2026" among them.
  Evidence: a scratch script over the fixture with the new module printed `25` and the ten headings with no listing; the 15 listed headings read to 2025-12-09 through 2026-10-13. An `<h4>` with no text sets the heading to None for the documents after it; no document in the fixture follows the blank one.

- Observation (M1, 2026-11-15): the plan's pattern for Arts and Parks, the bare letters `ARTS`, is found inside other words. `committees_named("COUNCILOR STARTS THE MEETING")` returned `('Arts and Parks',)`. No fixture header is affected: the eight readable fixtures each gave exactly the committees the plan states (the two not asserted in M1, `ps_minutes_2026-09-22.pdf` and `ti_minutes_2026-05-11.pdf`, gave `('Public Safety',)` and `('Transportation & Infrastructure',)`). The pattern is left as the plan states it, because the survey that validated it on 199 documents cannot be rerun from a milestone session (no fetching); the operator's dry run in Validation and Acceptance is where a document wrongly given Arts and Parks would show, as a document with two committees or with `listing_disagrees`.
  Evidence: the call above, run in this session against the committed module.

- Observation (M1, 2026-11-15): the 17 tests passed on the first run of the module, so each stated rule was taken out of an in-memory copy of the module, one at a time, and the tests run against each copy (a pytest plugin and a script in the session scratchpad; the committed file was not edited). First pass: 48 removals, 33 failed a test, 15 failed none. Assertions were added to the existing tests for 14 of the 15, and the final pass read `48 removals, 1 survived`.
  Evidence: the 14 rules that nothing pinned at the commit holding the failing tests (`bedbe0f`), each now pinned by an assertion added after that commit: in `test_read_date_spellings`, a word that is not a month is passed over and the search goes on ("ROOM 21, MARCH 3, 2026"), an ordinal day does not hide the year ("November 18th, 2025"), four digits not beginning 19 or 20 are not a year ("JUNE 2 1130 AM"), the day is 1 to 31 ("MAY 45"), the day is not the start of a longer number ("MAY 2026"), and the month word is not the tail of a longer word; in `test_header_stops_at_the_first_heading_line_and_at_twenty_lines`, a date is read within one line and never across two, MINUTES must be a whole line, MINUTES is matched in any case, and a text with no header line gives None; in `test_no_text_kind_comes_from_the_listed_name`, the listed name is matched in any case; in `test_resolve_falls_back_to_the_listing_fact_by_fact`, a header date with no year under a heading with no year gives no date, another committee's page alone is a disagreement, and a heading with no year cannot disagree about the date. The one removal that fails no test is the filter that parses only the `__NEXT_DATA__` strings containing `media--type-document`: without it every string is parsed and the same listings result, because a string without that class holds no such article. Nothing can tell that clause from its absence but the time taken; it stays because the plan states it.

- Observation (M2, 2026-11-15): the starting state is green, and `./tools/verify` again runs past its 180 second budget.
  Evidence: run before any edit, at commit `1c6521f`: `verify: all 6 checks passed in 207s.` (unit+web+services 93s, printing `2743 passed, 5 skipped, 4 xfailed, 2 warnings in 91.41s`; integration 106s, `1015 passed`; transcriber `127 passed`).

- Observation (M2, 2026-11-15): the tests of M2 fail before `parse_minutes_items` exists, each on its own import, and the file collects.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_committee_documents_minutes.py -q -p no:cacheprovider` printed `17 failed, 1 warning in 0.48s` with the function absent from `src/docket/adapters/committee_documents.py`. The commit that adds the test file holds this state. Five of the 17 read the five minutes fixtures; twelve read short texts written out in the test file, for the rules no fixture exercises.

- Observation (M2, 2026-11-15): every value the plan states for the five minutes fixtures was produced by the rules as the plan words them, on the first run of the function; no rule text and no expected value was changed.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_committee_documents_minutes.py tests/unit/test_committee_documents_read.py -q -p no:cacheprovider` printed `1 failed, 33 passed` on the first run and `34 passed, 1 warning in 2.28s` after the one failing test was mended. The failure was the session's own test and not the plan's: `test_an_item_before_any_heading_is_named_by_its_first_line` gave a five-line header and then lines with no heading line, and read `ValueError: not enough values to unpack (expected 1, got 0)`, because with no heading line the header runs on to its twentieth line and took the item's lines with it. The test now gives a twenty-line header. The five fixture tests passed on that first run.

- Observation (M2, 2026-11-15): what the rules give that a later milestone will show. The body of the first item of every fixture begins with the call to order ("The Meeting was called to order by the Committee Chair, Councilor Tate"), because an item is every line since the header and the call to order has no action of its own. The body of an item named by its first line (a licence application) contains that line, so its name is printed again as the body's first line. A heading with sub-headings leaves no trace in its items: the Planning and Zoning items "a." and "b." under "IV. UPDATE ON APPOINTMENTS/ REAPPOINTMENTS" each own their lettered heading, have no group, and nowhere carry the words of heading IV. `trailing_lines` counts heading lines as well as other lines: 4 for `ps_minutes_2026-09-22.pdf` and 6 for `pz_minutes_2026-09-08.pdf`.
  Evidence: the assertions of `tests/unit/test_committee_documents_minutes.py` on those fixtures, which pass; M5 decides what the page does with the first two.

- Observation (M2, 2026-11-15): the rule for an ending wrapped onto later lines, as the plan first worded it, takes the next item's first two lines into an action whenever the second of them happens to end like an outcome. No fixture has such lines; a text written for the purpose showed it.
  Evidence: with the stretch "Item Delayed" / "Third Shop" / "The earlier item withdrawn" before the next "Action Taken", the function as first committed (`2369a6f`) gave the action "Item Delayed Third Shop The earlier item withdrawn", where `test_an_action_ends_at_the_first_ending_and_at_the_longest_reading_of_it` expects "Item Delayed": `1 failed, 18 passed`. Two lines further the joined text does end with an outcome ending ("item withdrawn"), but a different one from the "Item Delayed" that ended the action. The rule and the function now ask that the ending two lines on begin at the same word (Decision Log); the five fixtures give the same items either way, and the test passes.

- Observation (M2, 2026-11-15): the session's first test of the outcome endings could not tell any ending from its absence, and the rule-removal check is what showed it. Each ending was printed as one line with a full stop before another action, where the rule for an action with no ending (through the first line ending with a full stop) gives the same action.
  Evidence: each stated rule was taken out of, or loosened in, an in-memory copy of the module, one at a time, and the M2 tests run against each copy (a pytest plugin and a script in the session scratchpad; the committed file was not edited). First pass, against the tests as committed in `2369a6f`: 125 alterations, 52 failed a test, 73 did not; 38 of the 73 were the script's own mistakes (37 whose text to replace was not found in the source and one that left the copy unable to compile), one changed nothing (reading the header lines again, which are then dropped as repeats of themselves), and 34 were rules nothing pinned: 28 of the outcome endings and their optional parts, the three limits on the page-number line (any case, and a whole line at each end), the first "Present" line winning, the longest extension being taken, and the action ending at the first ending and not a later one. Second pass, with the script mended and assertions added: `124 removals, 113 failed a test, 11 did not`; the 11 were "Action Taken" only at a line's start, six orderings of two neighbouring categories, the misspelled "Recommeded" in the consent and no-quorum categories, and the whole-word limit on `withdrawn` and `adjourned`. Final pass: `124 removals, 124 failed a test, 0 did not`. The assertions added after the commit that holds the tests failing (`b4a15a9`) are: `test_each_outcome_ending_ends_an_action` rewritten so each of 28 endings is printed with no full stop after a line with none; the new `test_an_action_ends_at_the_first_ending_and_at_the_longest_reading_of_it` and `test_an_action_with_no_words_is_still_an_item`; in `test_category_order`, the six texts that fit two categories, the two misspelled ones and the two words that contain a category's word; in `test_page_lines_and_the_repeated_header_are_dropped_only_when_they_are_whole_lines`, the four lines "No Action Taken: at the last meeting", "See Page 2 of 6", "Page 2 of 6 follows" and "PAGE 3 OF 6"; and in `test_present_spellings`, the three lines after "The first such line is the one".

- Observation (M3, 2026-11-15): the starting state is green, and `./tools/verify` again runs past its 180 second budget.
  Evidence: run before any edit, at commit `a1a1a05`: `verify: all 6 checks passed in 206s.` (unit+web+services 93s, printing `2762 passed, 5 skipped, 4 xfailed, 2 warnings in 90.99s`; integration 105s, `1015 passed`; transcriber `127 passed`).

- Observation (M3, 2026-11-15): the tests of M3 do not pass before the migration, the fetch functions and the service exist, and all three files collect. Most read as errors and not failures, because what is missing is what their fixtures set up.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/services/test_committee_documents_store.py tests/unit/test_committee_documents_fetch.py tests/integration/test_045_migration.py -q -p no:cacheprovider` printed `6 failed, 1 warning, 35 errors in 1.37s`. The 6 failures and 5 of the errors are the six tests of `test_045_migration.py` (no migration 45 is registered; five of the six also error in their fixture's teardown, which deletes from a table that does not exist). The 22 store tests error in their autouse fixture, which deletes from `committee_documents` before each test. The 8 fetch tests error in their fixture, which replaces `requests.get` and `time.sleep` on a module that imports neither yet. The commit that adds the three test files holds this state. The plan names two test files for M3; the third, `tests/unit/test_committee_documents_fetch.py`, is this session's, for the rules M3 states for `fetch_page` and `fetch_pdf` (the one-second gap shared by both, the 60 second timeout, the 40 MB stop, the `%PDF-` mark).

- Observation (M3, 2026-11-15): the 36 new tests passed on the first run of the migration, the two fetches and the service; no test and no expected value was changed to make them pass.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/services/test_committee_documents_store.py tests/unit/test_committee_documents_fetch.py tests/integration/test_045_migration.py tests/unit/test_committee_documents_read.py tests/unit/test_committee_documents_minutes.py -q -p no:cacheprovider` printed `72 passed, 1 warning in 8.47s`: 22 store, 8 fetch and 6 migration tests, and the 36 of M1 and M2 unchanged. Because they passed at once, the rule-removal check follows in the next commit.

- Observation (M3, 2026-11-15): the rule-removal check found 18 rules that the tests committed as not passing (`ec6db42`) left free, and one line of the service that no input reaches.
  Evidence: each stated rule of the two fetches, the service and the migration was taken out of, or loosened in, an in-memory copy of its module, one at a time, and that module's test file run against each copy (a pytest plugin and a script in the session scratchpad; no committed file was edited, and the throwaway database was dropped and rebuilt after every alteration of the migration). First pass, against the tests as committed in `ec6db42`: `149 alterations: 131 failed a test, 18 failed none, 0 broken`. The 18: the 40 MB limit read as 41 MB; a PDF whose body breaks off part-way; documents first seen at the same moment taken lowest id first; None from `fetch_pdf` handed on to `_read` (which then raises, is caught, and leaves the same row); `work_session` stored; the line `text = text or ""` in `_store_reading`; and in the migration, the address unique per city and not across cities, `meeting_id` set to NULL when its meeting is deleted, `municipality_id` a reference, and nine `NOT NULL` columns. The line `text = text or ""` was deleted, not pinned: `extract_text_from_pdf` returns a string and `reparse` selects only rows whose text is not NULL, so nothing could reach it. Second pass, with the assertions below added: `148 alterations: 148 failed a test, 0 failed none, 0 broken`. The assertions added after `ec6db42`: in `tests/unit/test_committee_documents_fetch.py`, `test_fetch_pdf_stops_past_forty_megabytes` now asserts exactly 40 one-megabyte chunks were taken (it asserted at most 41), and the new `test_fetch_pdf_is_none_when_the_body_breaks_off_part_way`; in `tests/services/test_committee_documents_store.py`, the new `test_a_work_session_is_stored_as_one`, the assertion in `test_a_fetch_that_fails_three_times_is_not_tried_a_fourth` that a fetch giving None logs no error, and in `test_read_pending_takes_the_oldest_first_up_to_its_limit_and_only_this_city` two documents first seen at the same moment; in `tests/integration/test_045_migration.py`, the new `test_045_what_must_be_given_cannot_be_null` and `test_045_a_document_outlives_its_meeting`, and the assertion that the same address under another city is another row.

- Observation (M4, 2026-11-15): the starting state is green, and `./tools/verify` again runs past its 180 second budget.
  Evidence: run before any edit, at commit `3666b2a`: `verify: all 6 checks passed in 214s.` (unit+web+services 99s, integration 107s, transcriber 8s, printing `127 passed`). The session kept only the last lines of that run, so the pass counts of the first two tiers at the start were not read; M3's record of the same commit's tree gives them as 2794 and 1023.

- Observation (M4, 2026-11-15): the tests of M4 fail before `committee_of`, `attach` and `primary_documents` exist, each on its own import, and the file collects.
  Evidence: `DATABASE_URL=<the docket_test_61bde166 address tools/test-db prints> venv/bin/python -m pytest tests/services/test_committee_documents_attach.py -q -p no:cacheprovider` printed `30 failed, 1 warning in 1.70s` with none of the three names in `src/docket/services/committee_documents.py`. The commit that adds the test file holds this state. The throwaway database holds four cities (birmingham, homewood, mobile, vestavia_hills) and no meeting, so every meeting a test sees is one it inserted; the tests date everything in 2031.

- Observation (M4, 2026-11-15): the 30 new tests passed on the first run of `committee_of`, `attach` and `primary_documents`; no test and no expected value was changed to make them pass.
  Evidence: `DATABASE_URL=<the docket_test_61bde166 address> venv/bin/python -m pytest tests/services/test_committee_documents_attach.py tests/services/test_committee_documents_store.py -q -p no:cacheprovider` printed `53 passed, 1 warning in 9.50s`: the 30 attach tests and the 23 store tests of M3 unchanged. `venv/bin/ruff check` on the service and the test file printed `All checks passed!`. Because they passed at once, the rule-removal check follows in the next commit.

- Observation (M4, 2026-11-15): every title a created meeting can have classifies as a committee meeting whose `body_name` names its own committee and no other, so a created row is a candidate for the next document of the same committee and date.
  Evidence: a scratch call of `classify_title` on the 32 titles (eight canonical names, each as " Committee Meeting" and " Committee Work Session", with and without "Special Called ") gave `meeting_type='committee'` for all 32, `session_kind` `regular`, `special`, `work_session` and `work_session` in that order for each name, and a `body_name` that `committees_named` reads to exactly that one committee. A title that says both "Special Called" and "Work Session" is stored with `session_kind = 'work_session'`; the word "Special" survives in the title only. The same call gave `('Budget and Finance',)` for "Budget & Finance Committee" and `('Economic and Workforce Development / Tourism',)` for "Economic Development & Tourism Committee Work Session", the two spellings M4's tests name.

- Observation (M4, 2026-11-15): the rule-removal check found six rules that the tests committed as failing (`05a5355`) left free, one clause of the service that no input reaches, and one clause nothing in a test can tell from its absence.
  Evidence: each stated rule of `committee_of`, `attach`, the creation of a meeting and `primary_documents` was taken out of, or loosened in, an in-memory copy of `src/docket/services/committee_documents.py`, one at a time, and `tests/services/test_committee_documents_attach.py` run against each copy (a pytest plugin and a script in the session scratchpad; no committed file was edited by the check). First pass, against the tests as committed in `05a5355`: `61 alterations: 54 failed a test, 7 failed none, 0 broken`. The seven: `body_name or ""` in `committee_of`; the crowded-day count limited to this city, limited to meetings typed `council`, and returned in date order; the held `external_id` looked up in this city only; `primary_documents` leaving out the text; and the condition `AND meeting_id IS NULL` on the update that attaches. The first was deleted, not pinned: `committees_named` already reads None as no text, so the clause did nothing. Second pass, with the assertions below added: `60 alterations: 59 failed a test, 1 failed none, 0 broken`. The one left is the update's `AND meeting_id IS NULL`: the documents are selected with the same condition a moment before, so only another process attaching the same document between the select and the update could show the difference, and no test here runs two at once. It stays because Idempotence and Recovery states it. The assertions added after `05a5355`: in `test_a_created_meetings_day_with_a_second_granicus_council_meeting_is_crowded`, a day with two Granicus council meetings in Mobile, a day with two Granicus meetings typed `planning`, and a second crowded day earlier than the first and created after it (the report lists the two in date order); in `test_a_meeting_that_already_has_the_created_address_is_attached_to_and_not_made_twice`, a Mobile meeting holding the same `external_id`, inserted later; and in `test_the_primary_document_of_each_kind_is_the_lowest_id_and_a_meeting_with_none_has_none`, that neither primary row has a `text` key.

- Observation (M5, 2026-11-15): the starting state is green, and `./tools/verify` again runs past its 180 second budget.
  Evidence: run before any edit, at commit `e87b8c7`: `verify: all 6 checks passed in 224s.` (unit+web+services 106s, printing `2824 passed, 5 skipped, 4 xfailed, 2 warnings in 104.15s`; integration 110s, `1023 passed`; transcriber `127 passed`).

- Observation (M5, 2026-11-15): the tests of M5 fail before `for_meeting` and the partial exist, and the file collects. Two of the 26 pass already, and are meant to: they assert what must not change (a meeting with no document shows no record and its strip reads "Agenda items"; a council meeting's strip is as it was).
  Evidence: `DATABASE_URL=<the docket_test_61bde166 address tools/test-db prints> venv/bin/python -m pytest tests/web/test_committee_record_page.py -q -p no:cacheprovider` printed `24 failed, 2 passed, 1 warning in 3.84s` with no `for_meeting` in `src/docket/services/committee_documents.py` and no `partials/committee_record.html`; the two that passed are `test_a_meeting_with_no_document_shows_no_record_and_its_strip_is_unchanged` and `test_a_council_meetings_strip_is_unchanged`. The three tests of `for_meeting` fail on their own import; the page tests fail where they look for the record's section or, for the strip, its new words. The commit that adds the test file holds this state.

- Observation (M5, 2026-11-15): the 26 new tests passed on the first run of `for_meeting`, the partial, the route's call and the strip's edit; no test and no expected value was changed to make them pass.
  Evidence: `DATABASE_URL=<the docket_test_61bde166 address> venv/bin/python -m pytest tests/web/test_committee_record_page.py -q -p no:cacheprovider` printed `26 passed, 1 warning in 4.02s`. After the partial's two headings were given classes the stylesheet has (the first draft named `t-h2` and `t-h3`, which no stylesheet defines), the whole web tier with the M4 attach tests printed `454 passed, 5 skipped, 1 warning in 43.34s`. `venv/bin/ruff check` on the service and the test file is clean; on `src/docket/web/public.py` it reports one finding (`C408`, a `dict()` call in `meeting_transcript`) that was there before this milestone and is not touched. Because the tests passed at once, the rule-removal check follows in the next commit.

## Decision Log

- Decision: Committee documents and committee items live in two new tables, `committee_documents` and `committee_items`. Nothing is written to `agenda_items`, `votes`, `meetings.agenda_url` or `meetings.minutes_url`.
  Rationale: Every existing reader of `agenda_items` treats a row as council business. A new row there defaults to `processing_status = 'pending'` and is claimed by the daily AI stage, which has no meeting-type filter; the city page's money list, search, the sitemap and the member pages have none either, so a committee item would appear beside the council item for the same resolution and be counted twice. `meetings.minutes_url` is worse: the meeting-type resolver never gives a row with a minutes link a committee event, the minutes-adoption sweep selects on it, and the daily Granicus ingest overwrites both address columns from its own feed. New tables change no existing reader. The cost is that committee items are not in search and have no page of their own; that is recorded as debt.
  Date/Author: 2026-11-13, plan author.

- Decision: What a document is (which committee, which date, agenda or minutes) is read from the document's own first lines. The committee page it is listed on, the date heading it is listed under, and its listed name are the fallback, used only for a fact the document's own lines do not give.
  Rationale: Measured on all 199 listed documents on 2026-11-13. Fourteen documents sit under a heading for a different meeting than the one they record, several file names carry the wrong year, one committee's minutes are posted on another committee's page, and one document is a full council agenda. The document's own heading was right in every case read by hand. The design said the date comes from the page's heading; this supersedes it.
  Date/Author: 2026-11-13, plan author.

- Decision: Items come from minutes only. An agenda is stored and linked, and its items are not read.
  Rationale: The design said items come from the agenda until minutes exist. The eight committees print agendas in eight layouts with dot leaders, sub-items and presenter names; thirteen of the 106 agendas are scanned images with no text; and an agenda does not say what the committee did, which is the fact this plan exists to show. Minutes share one layout across all eight committees. A meeting whose minutes are not yet posted shows its agenda link and the sentence that minutes are not yet posted. Reading agenda items is recorded as debt.
  Date/Author: 2026-11-13, plan author.

- Decision: Minutes for a committee and date with no meeting row create a meeting row. An agenda alone never does.
  Rationale: Minutes prove a meeting was held; a posted agenda does not (meetings are cancelled and rescheduled). The Economic and Workforce Development / Tourism Committee has 13 sets of minutes and one meeting row, so without creation the committee would stay invisible.
  Date/Author: 2026-11-13, plan author.

- Decision: A committee's action is stored as its own words plus one of a closed list of categories, and is never stored or shown as a vote.
  Rationale: Committee minutes record a motion and a second, not a roll call. A tally the record does not contain must not appear (`docs/PRINCIPLES.md`, "Source or silence"). An action that fits no category keeps its words and the category `other`.
  Date/Author: 2026-11-13, plan author.

- Decision: Reading is by fixed rules and patterns; no language model reads a committee document.
  Rationale: The outcome wordings are few and regular (753 of 768 actions in the survey fall into a category by pattern), and a model's reading could not be traced to the page.
  Date/Author: 2026-11-13, plan author.

- Decision: Which committee a name refers to is decided by one keyword per committee, in a function this plan adds, not by the existing `same_committee`.
  Rationale: `same_committee` in `src/docket/services/meeting_types.py` was run on 2026-11-13 against the fifteen committee `body_name` spellings in production. It matches thirteen and fails "Economic Development & Tourism Committee" and "Economic Development & Tourism Committee Work Session" against the canonical "Economic and Workforce Development / Tourism", because neither is a prefix of the other. A keyword per committee matches all fifteen and every document title in the survey.
  Date/Author: 2026-11-13, plan author.

- Decision: A year is four characters, each a digit or the letter O, that read with O as zero begin `19` or `20`. The M1 rule text is changed to say so.
  Rationale: The rule as first written put the O only in the last two places and could not read "2O26", the example the plan gives for it. The plan's stated result `(2026, 5, 26)` is the reading a person makes of that header, so the result stands and the rule's wording was the defect. Reading O as zero in any of the four places admits nothing new that is plausible in a header: the four characters must still begin 19 or 20 once read.
  Date/Author: 2026-11-15, M1 session.

- Decision: Three limits on `read_date` that the plan does not state, each pinned by a test: the day is 1 to 31; the day's digits are not the start of a longer number; and the month word starts at a word's beginning.
  Rationale: Without the second, "MAY 2026" reads as the 20th of May with no year, and a heading or header printing a month and year would date a document to a day it does not name. Without the first, "MAY 45" is a date that `resolve` would then have to discard. Without the third, a word longer than twelve letters can lend its tail as a month. Each makes the reader say nothing where the page says nothing (`docs/PRINCIPLES.md`, "Source or silence"). The alternative, the rule exactly as worded, loses on "MAY 2026" alone.
  Date/Author: 2026-11-15, M1 session.

- Decision: In `resolve`, a header that names no committee does not make `listing_disagrees` true, and a date that is no day of the calendar (30 February) is no date, with `date_source` None.
  Rationale: The plan's clause reads "the header's committees do not include the page's committee". Read literally, the seven agendas whose header is logo noise and names no committee would all disagree with their listing, when the listing is the only thing that says which committee they are and `resolve` has just taken the committee from it. A disagreement needs two statements. The calendar check is needed because `DocumentFacts.meeting_date` is a `date` and cannot hold an impossible one.
  Date/Author: 2026-11-15, M1 session.

- Decision: `read_header` returns None for a text with no header line (no line at all, or a heading line first), as well as for a full council meeting. `parse_committee_page` returns an empty list, with a logged warning, for a page with no `__NEXT_DATA__` block or one that is not JSON.
  Rationale: The plan gives None one meaning, "not a committee document", and M3's `_read` tests for too little text before it calls `read_header`, so a scanned document never reaches this case there. A caller that does reach it is told there is no header to read, which is what `resolve` takes None to mean. The alternative, a `Header` with no lines, would make `resolve` call a document with no readable header an agenda. The empty list follows `src/docket/adapters/city_calendar.py`, whose parsers do the same so that the city changing one page does not fail a run; M3's `sync_listings` decides what a page with no listing means.
  Date/Author: 2026-11-15, M1 session.

- Decision: Four readings of M2's rule text where it does not say, each pinned by a test. The "Councilor(s) Present" pattern is matched from the start of a header line in any case, the first such line wins, and a line with nothing after it gives None. The page-number pattern, like the transcription line, is matched in any case. An item under a heading that several actions share, or under no heading at all, that has no line of its own is named by the heading's text, and by the empty string when there is no heading. An "Action Taken" line with nothing after it before the next heading line or action is an item whose `action_text` is empty and whose category is `other`.
  Rationale: The Transportation fixture prints "COUNCILOR(S) PRESENT:" in capitals, so the pattern as written, read case-sensitively, would give None for a line that plainly says who was present. The other three are cases no fixture holds; each keeps what the minutes print and adds nothing, and M3's `name text not null` and `action_text text not null` accept the empty string. The alternative for the last, dropping an action with no words, would lose the fact that the minutes recorded an action there.
  Date/Author: 2026-11-15, M2 session.

- Decision: The mover and seconder patterns are matched in the case the plan writes them ("Councilor", "Motioned", "Seconded", a capital to start the surname), unlike the outcome endings and categories, which the plan says are case-insensitive.
  Rationale: The plan marks the other patterns case-insensitive and not these, and every motion line in the five fixtures is in that case. A surname is given to a reader as a fact, so the stricter reading is the one that says nothing where the minutes print something unexpected (`docs/PRINCIPLES.md`, "Source or silence"). The operator's dry run shows how many items have no mover.
  Date/Author: 2026-11-15, M2 session.

- Decision: `read_header`'s loop that finds the header lines moved, unchanged, into a private function `_header_lines`, which `read_header` and `parse_minutes_items` both call.
  Rationale: M2 says "the header lines are those M1 identified"; two copies of the rule could drift apart. `Header.lines` could not be used because `read_header` returns None for a full council meeting and `parse_minutes_items` takes text, not a `Header`. M1's 17 tests pass unchanged.
  Date/Author: 2026-11-15, M2 session.

- Decision: An ending found one or two lines further extends an action only when it begins at the same word as the ending first found. The M2 rule text is changed to say so.
  Rationale: The plan's sentence says the joined lines "still" end with an outcome ending and explains the look-ahead as keeping a wrapped ending whole. Read loosely, any ending within two lines counts, and a licence application whose second line ends "... item withdrawn" would be swallowed into the action before it, losing that item's name and putting another item's words in the committee's mouth (`docs/PRINCIPLES.md`, "Source or silence"). The same-word test is what "still" means, and it keeps every case the plan gives: "… Lack of" / "Quorum.", and "Minutes were Approved" / "as Recorded." in the budget fixture. The alternative, the loose reading, changes no fixture result and loses only on the constructed text in Surprises & Discoveries; it was rejected because the failure it allows is silent.
  Date/Author: 2026-11-15, M2 session.

- Decision: The migration is number 045, `src/docket/migrations/045_committee_documents.py`. Its tables and index are created `IF NOT EXISTS`, and the index is named `committee_documents_meeting_id_idx`.
  Rationale: 044 is the highest on `origin/main` as this worktree holds it (`git ls-tree origin/main src/docket/migrations/`), and a milestone session fetches nothing, so no later number could be looked for. `IF NOT EXISTS` is what makes "up twice is harmless" true of a `CREATE TABLE`, and the operator's dry run in Validation and Acceptance creates the tables itself when they are absent.
  Date/Author: 2026-11-15, M3 session.

- Decision: In `sync_listings`, a page that fetches and yields no listing is a failed page, like one that cannot be fetched; the call raises `RuntimeError` when every configured page failed, and returns 0 without raising when no page is configured.
  Rationale: M1 left this to M3 (`parse_committee_page` returns an empty list for a page it cannot parse). All eight pages listed documents on 2026-11-13, so a page with none is far likelier the city's error page or a changed layout than a committee with nothing posted, and M7's debt row for the term's address names exactly this as its trigger ("a `sync_listings` run finds no listing on any page"). The alternative, treating an empty page as read, would let a site change pass silently every morning. One empty page among eight costs a log line and nothing else.
  Date/Author: 2026-11-15, M3 session.

- Decision: `fetch_pdf` returns None when the request fails (an HTTP error, no connection, a timeout), as it does for a body past 40 MB or not beginning `%PDF-`; `fetch_page` raises. In `read_pending`, any exception raised while one document is fetched or read (a PDF `pdfplumber` cannot open, text the database refuses) is logged and counted as a failed attempt: status `fetch_failed`, one more `fetch_attempts`, and the documents after it are still read.
  Rationale: The plan gives `fetch_pdf` the type `bytes | None` and tells `read_pending` what to do "on failure", so None is the one way a PDF fails to arrive. `read_pending` takes the oldest first: a document that raised and was left `listed` would be the first one tried, and would stop the run, every day. Counting it against the three attempts bounds that. The status's name says "fetch" where the failure may be the read; no reader shows the status, and the log line carries the exception. The alternative, a sixth status, would change the plan's table for a case no fixture has.
  Date/Author: 2026-11-15, M3 session.

- Decision: `read_pending`'s limit is on documents tried, not on documents read. `fetch_attempts` counts failures and is not set back to zero when a later fetch succeeds. `fetched_at` and `pdf_sha256` are written by `_read`, in the same transaction as the reading.
  Rationale: M6 justifies `read_limit = 25` by the requests a run makes ("at most 33 requests"), which holds only if a failed fetch counts. The attempts are a record of what happened and nothing selects on them once a row is read. Writing the hash inside `_read` keeps "one transaction per document" and lets a caller with the bytes in hand (M5's acceptance loads a fixture "through `_read`") store a whole document with one call: `_read(row, pdf_bytes)`, where `row` is a mapping with `id`, `url`, `page_url`, `page_committee`, `listed_name` and `listed_heading`.
  Date/Author: 2026-11-15, M3 session.

- Decision: The reading from text is one private function, `_store_reading(cur, row, text)`, which `_read` and `reparse` both call. Every reading writes every fact column and replaces the document's items, so a document that is not minutes, or not a committee's, has no items and NULL `present` and `trailing_lines` whatever an earlier reading left.
  Rationale: `reparse` must run "the same reading" as `_read`; two copies would drift. Writing every column each time is what makes a rule change take effect on a row whose kind or committee the new rule reads differently, and a `not_committee` row is given the columns' defaults (no kind, no committees, no date), which is what "no facts" means. `reparse` does not select a `no_text` row, whose text is NULL: there is nothing stored to read again.
  Date/Author: 2026-11-15, M3 session.

- Decision: `attach` takes minutes before agendas, and within each kind the lowest id first.
  Rationale: An agenda with no meeting row waits for one. Taken in id order, an agenda listed before its own minutes would be left unattached in the call whose later step creates its meeting, and would attach only on the next call; the operator's second dry run in Validation and Acceptance must report "nothing new to read, attach or create", which holds only if one call settles everything it can. The alternative, a second pass over the unattached agendas, does the same with more code.
  Date/Author: 2026-11-15, M4 session.

- Decision: What `AttachReport` counts. `matched` and `created` count documents attached in this call, so `created` is also the number of meetings made (each is made by exactly one document). `ambiguous` counts, among the matched, the documents that had more than one candidate, whatever committee each candidate was for. `unattached_agendas` and `unattached_minutes` count the documents the call considered (read or `no_text`, with a kind, a date and a committee, and no meeting) and left with no meeting; a document with no date or no committee is in neither. `crowded_days` is a sorted list of distinct dates, of meetings created in this call only, so a second call reports none.
  Rationale: The plan names the counts and does not define them. Each is what the operator's dry run needs to compare with the survey ("at least 140 documents attach to an existing meeting; at most 25 meetings would be created"), and "a second `attach` reports nothing new" requires every count to be of this call's own work. Documents that can never attach (no date, no committee) are already visible in M6's table of documents by status and date source; counting them here on every call would bury the ones that are waiting for a meeting.
  Date/Author: 2026-11-15, M4 session.

- Decision: When the insert of a created meeting does nothing because a row already holds that `external_id`, the document is attached to that row with `attached_by = 'matched'` and counted as matched, whatever that row's state.
  Rationale: The plan says to select the existing row and attach to it. Such a row was no candidate, so it is hidden or has been typed otherwise since it was made (an admin hid a `cdoc-` meeting, or retyped it); nothing was created, and `created` must stay the number of meetings made. Attaching to a hidden row shows nothing to a reader, which is what hiding it asked for, and it stops the document from making a second meeting for the day on every later call. The alternative, leaving the document unattached, would try the insert again daily for ever.
  Date/Author: 2026-11-15, M4 session.

- Decision: A document that has a meeting is never moved or detached by `attach`, whatever a later reading (`reparse`) makes of its committee, date or kind. One transaction per document, as in M3.
  Rationale: M3 left this to M4. Idempotence and Recovery already says "attachment only where `meeting_id` is NULL", and the update carries that condition itself. A rule change that re-dates a document is rare and is the operator's to see (M6's script prints documents by date source); moving a document silently between meetings, or deleting a created meeting that a reader may have linked, is the worse failure. To re-attach on purpose, set `meeting_id` to NULL on the rows concerned and run `attach`. One transaction per document keeps a failure on one document from undoing the others; M6's `--dry-run` inherits the same shape it already has to deal with for M3's functions.
  Date/Author: 2026-11-15, M4 session.

- Decision: `primary_documents(meeting_id)` returns a dict with a key only for each kind the meeting has (`agenda`, `minutes`); each value is that document's row as a dict with `id`, `kind`, `url`, `page_url`, `listed_name`, `status`, `meeting_date`, `committees`, `listing_disagrees`, `present`, `trailing_lines` and `attached_by`, and never the text. A meeting with no document gives `{}`.
  Rationale: The plan gives the return type as `dict` and no more. M5's `for_meeting` needs the primary minutes' id (for its items) and `present`, and each document's address and status; the text is up to hundreds of kilobytes and no page shows it.
  Date/Author: 2026-11-15, M4 session.

## Outcomes & Retrospective

As authored on 2026-11-13, nothing has been executed and there are no outcomes.

M1, 2026-11-15. `src/docket/adapters/committee_documents.py` exists with the committee table, `Listing`, `Header`, `DocumentFacts`, `committees_named`, `parse_committee_page`, `read_date`, `read_header` and `resolve`, as Interfaces and Dependencies names them; `MinutesItem`, `MinutesFacts`, `parse_minutes_items`, `fetch_page` and `fetch_pdf` are M2's and M3's and are not there yet. Every expected value the plan states for M1 was observed as stated; the one rule that could not produce its stated value (the year "2O26") was mended in the plan. Both acceptance checks were run and are recorded in Artifacts and Notes; there is no carve-out against M1's acceptance. Left for later milestones to notice: the bare `ARTS` pattern (Surprises & Discoveries), and `./tools/verify` taking 207 seconds against a 180 second budget before and after this milestone. Next is M2.

M2, 2026-11-15. `parse_minutes_items`, `MinutesItem` and `MinutesFacts` exist in `src/docket/adapters/committee_documents.py` as Interfaces and Dependencies names them; `fetch_page` and `fetch_pdf` are M3's and are not there yet. Every value the plan states for the five minutes fixtures was observed as stated, the eleven Public Safety items and their categories among them, with no expected value changed. One sentence of the rule text was mended (a wrapped ending must be the same ending read further), on a constructed text and not on a fixture. The acceptance check was run and is recorded in Artifacts and Notes; there is no carve-out against M2's acceptance. What M3 inherits: an item's `name` and `action_text` can be the empty string (an item with no heading and no line, an "Action Taken" with no words), which M3's `not null` columns accept; `group` is the string M3 stores as `group_text`. What M5 inherits: the first item's body begins with the call to order, and an item named by its first line repeats that line as the first line of its body (Surprises & Discoveries). Lesson: a test that prints each case in the shape the fallback rule also handles proves nothing about the rule; the removal check found 34 unpinned rules that the fixtures and a plausible-looking table of endings had left free. `./tools/verify` took 207 seconds before and after, against a 180 second budget. Next is M3.

M3, 2026-11-15. Migration 045 creates `committee_documents` and `committee_items` and sets Birmingham's `committee_document_pages`; `fetch_page` and `fetch_pdf` exist in the adapter; `src/docket/services/committee_documents.py` exists with `PARSER_VERSION`, `sync_listings`, `read_pending`, `_read` and `reparse`, as Interfaces and Dependencies names them. `committee_of`, `attach`, `primary_documents`, `for_meeting`, `refresh_city` and `refresh_all` are M4's, M5's and M6's and are not there yet. Every value the plan states for M3's tests was observed as stated (27 listings and none the second time, the budget minutes read to 2026-10-12 with 12 items, the scanned agenda `no_text` with its date from the heading, three failed attempts and no fourth, the same 12 items after `reparse`), and no plan text was changed. The acceptance was run and is recorded in Artifacts and Notes; there is no carve-out against M3's acceptance. Nothing was fetched from the city's site and nothing touched production: the migration has run only on the throwaway database. What M4 inherits: `meeting_id` and `attached_by` are NULL on every row this milestone writes, and a reading (`_store_reading`, which `reparse` also runs) rewrites a row's kind, committees and date and does not touch `meeting_id`, so M4 decides what a document already attached does when a later reading changes its facts. What M5 inherits: `_read(row, pdf_bytes)` stores a whole document from bytes in hand, where `row` needs `id`, `url`, `page_url`, `page_committee`, `listed_name` and `listed_heading`. What M6 inherits: each service function opens and commits its own transactions through `docket.db.db_cursor` (one per page in `sync_listings`, one per document in `read_pending` and `reparse`), so the script's `--dry-run`, which must roll everything back, cannot simply wrap the calls in a transaction of its own; and `sync_listings` raises `RuntimeError` when every page failed, which `refresh_city` must let through or catch on purpose. Lesson: a test of a size limit that asserts "at most 41 chunks" passes for a limit of 41 MB as well as 40; the removal check found that and 17 other free rules, nine of them `NOT NULL` columns the plan's migration test list never mentions. `./tools/verify` took 206 seconds before and 217 after, against a 180 second budget. Next is M4.
M4, 2026-11-15. `committee_of`, `attach`, `AttachReport` and `primary_documents` exist in `src/docket/services/committee_documents.py` as Interfaces and Dependencies names them; `for_meeting`, `refresh_city` and `refresh_all` are M5's and M6's and are not there yet. Every case M4's test list states was observed as stated (the two spellings of a `body_name` matched, the `cdoc-economic-workforce-development-tourism-<date>` row typed `committee` and nothing made by a second call, the agenda that waits and then attaches, minutes after `today` making nothing, the hidden and the council rows passed over, the joint minutes on the Public Safety row and counted ambiguous, the agreeing minutes primary whichever came first, a deleted meeting leaving `meeting_id` NULL), and no plan text was changed. The acceptance was run and is recorded in Artifacts and Notes; there is no carve-out against M4's acceptance. Nothing was fetched and nothing touched production; every meeting and document was a row a test inserted in the throwaway database. What M5 inherits: `primary_documents(meeting_id)` gives a dict keyed by the kinds the meeting has, each value a row with `id`, `kind`, `url`, `page_url`, `listed_name`, `status`, `meeting_date`, `committees`, `listing_disagrees`, `present`, `trailing_lines`, `attached_by`; a created meeting has `source_url` set to the committee's page, so the meeting page's source rail will show "Original source" for it; and M5's acceptance can call `attach(municipality_id, today)` after `_read` with no further setup. What M6 inherits: `attach` commits one transaction per document, like M3's functions, so `--dry-run` cannot wrap it in a transaction of its own; `AttachReport`'s counts are of that call's own work and are defined in the Decision Log; the script's "list of meetings it would create" is not in the report (it holds counts and `crowded_days`) and must be read from `meetings` rows whose `external_id` begins `cdoc-`. Not decided here and left as the plan has it: a `cdoc-` meeting and a later `yt-` meeting for the same day are two rows (M7's debt row), since a YouTube recording arriving after the minutes does not look for a `cdoc-` row. Lesson: the removal check again found what the plan's test list did not ask for, here that every count in a report about one city was free to count another city's rows. `./tools/verify` took 214 seconds before and 223 after, against a 180 second budget. Next is M5.

## Context and Orientation

docket.pub is a Python 3.10 Flask application with HTMX, backed by PostgreSQL. `AGENTS.md` at the repository root is the map. The rules from it that govern this plan: routes in `src/docket/web/public.py` never run SQL and call functions in `src/docket/services/`; adapters in `src/docket/adapters/` fetch and parse and never touch the database; services own every database read and write; nothing shown to a reader may lose its link to the city's source; requests to a city's website are at least one second apart (`GOALS.md`); and a session never writes to production. `./tools/verify` is the only test command; it builds its own throwaway database.

Terms used below. A **committee page** is one of the eight pages the city publishes, one per standing committee, each listing that committee's agenda and minutes PDFs. A **listing** is one PDF link on such a page, with the date heading it sits under and the name the page shows for it. A **document** is one PDF. Its **header** is its first few lines, which print the committee's name, the meeting's date and, for minutes, the single word MINUTES. A **heading line** inside a document is a line that begins with a number, Roman numeral or letter followed by a full stop or a closing bracket, such as `VI.` or `4)` or `a.`. An **action** is the text that follows a line beginning "Action Taken:". An **item** is one thing the committee took up: the lines before an action, and the action.

### What exists today

- `src/docket/adapters/city_calendar.py` already reads `www.birminghamal.gov`. Its private function `_get(url, **kwargs)` waits until one second has passed since the module's last request, then calls `requests.get` with a browser user agent (`_BROWSER_UA`) and a 60 second timeout, and raises on an HTTP error. City pages are Next.js pages: their data is JSON inside `<script id="__NEXT_DATA__">`, and the module parses it with `json` and `BeautifulSoup`. Tests in `tests/unit/test_city_calendar.py` stub the network with `unittest.mock.patch("docket.adapters.city_calendar.requests.get", ...)` and an autouse fixture that replaces `time.sleep`.
- PDF text is extracted with `pdfplumber` (already in `requirements.txt`). `src/docket/analysis/minutes_parser.py` has `extract_text_from_pdf(pdf_bytes: bytes) -> str`, which joins each page's `extract_text()` with a newline. This plan uses that function unchanged; every number and example below was produced with it, not with any other extractor.
- `src/docket/services/meeting_types.py` has `BIRMINGHAM_COMMITTEES`, the eight canonical committee names: "Arts and Parks", "Budget and Finance", "Committee of the Whole / Administration & Governmental Affairs", "Community Development", "Economic and Workforce Development / Tourism", "Planning & Zoning", "Public Safety", "Transportation & Infrastructure".
- `src/docket/adapters/_helpers.py` has `classify_title(title) -> Classification(meeting_type, session_kind, body_name)`. Run on 2026-11-13: "Budget and Finance Committee Meeting" gives `('committee', 'regular', 'Budget and Finance Committee')`; "Special Called Budget and Finance Committee Meeting" gives `session_kind='special'`; "Economic and Workforce Development / Tourism Committee Work Session" gives `session_kind='work_session'`. All eight canonical names followed by " Committee Meeting" classify as `committee`.
- The `meetings` table has, among others, `municipality_id`, `external_id` (unique with `municipality_id`, the only uniqueness on the table), `title`, `meeting_date`, `meeting_type`, `session_kind`, `body_name`, `type_source`, `video_url`, `source_url`, `is_hidden`. There is no uniqueness on committee and date; two sources can each create a row for the same meeting unless code prevents it.
- `src/docket/services/youtube_meetings.py` creates a committee meeting row from the council's YouTube channel, with `external_id` beginning `yt-`, three days after a recording appears if nothing else has claimed it (`CREATE_AFTER_DAYS = 3`). Its insert ends `ON CONFLICT (municipality_id, external_id) DO NOTHING RETURNING id`, which is the model for the insert in M4.
- Migrations are Python modules in `src/docket/migrations/`, each with a docstring, `SQL_UP` and `SQL_DOWN`, registered by hand in `runner.MIGRATIONS`. The highest on `origin/main` at authoring is `044_hidden_reason.py`. Migration tests are in `tests/integration/test_0NN_migration.py`; `test_044_migration.py` is the model (registered in order, up adds the objects, a CHECK rejects a bad value, up twice is harmless, down removes them).
- The worker registers daily tasks in `src/docket/worker/scheduler.py` (`build_scheduler`), defines them in `src/docket/worker/tasks.py` (a `_do_<name>` function, a `task_<name>` wrapper calling `_safe_run`, an entry in `TASKS`), and maps each to a health-check variable in `src/docket/worker/health.py` (`TASK_UUID_ENV`). `city_calendar` runs at 05:30, `ingest_all` at 06:00, `youtube_ingest` at 06:45. `tests/unit/test_worker_scheduler.py` pins the exact set of eighteen job ids and their hours, and `tests/unit/test_worker_health.py` requires every task to have a variable. `docs/runbooks/cron-worker.md`, `README.md` and the `scheduler.py` docstring state the count "eighteen" in prose.
- The meeting page is `meeting_detail` in `src/docket/web/public.py`, template `src/docket/web/templates/meeting_detail.html`. Its `kpi-strip` prints "Agenda items", "Votes" and "Total dollars" from `agenda_items` and `votes`; a committee meeting with none prints "0", "none recorded" and "$0". The source rail further down lists "Agenda", "Official minutes", "Watch video" and "Original source", each only when the meeting row has that address.

### What the documents are really like

All eight committee pages and all 199 PDFs they list were downloaded on 2026-11-13, one request a second, and read with `extract_text_from_pdf`. The pages are at `https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/<slug>`, with the slugs `arts-parks-committee`, `budget-finance-committee`, `committee-whole-administration-governmental-affairs`, `community-development-committee`, `economic-workforce-development-tourism-committee`, `planning-zoning-committee`, `public-safety-committee`, `transportation-infrastructure-committee`. The documents run from November 2025 to November 2026.

A committee page holds its listings inside `__NEXT_DATA__` as a string of HTML. In that HTML each meeting date is an `<h4>` ("SEPTEMBER 8, 2026") and each document under it is an `<article class="media media--type-document ...">` with a `name` attribute (the listed name) and a `file` attribute (the PDF's address). The Planning and Zoning page lists 27 documents under 15 headings. Of the 199 listings, 195 sit under a heading with a full date, 2 under one with no year, and 2 under one that does not parse ("MAY12, 2026").

Of the 199 documents: 13 have no text layer (they are scanned images; 11 are Public Safety agendas and 2 Planning and Zoning agendas), and 1 is a full council agenda posted on the Public Safety page (its header reads "REGULAR MEETING OF THE COUNCIL"). Of the 185 others, the header names one committee in 169, two committees in 9 (joint meetings such as "JOINT PUBLIC SAFETY AND SPECIAL CALLED COMMITTEE OF THE WHOLE MEETING"), and none in 7 (agendas whose first lines are a logo read as noise). The header gives a full date in 165, a month and day with no year in 11 ("Tuesday, June 2"), and no date in 9. Eighty-nine are minutes and 96 are agendas by the rule in M1.

Minutes share one shape across all eight committees. After the header comes "Councilor(s) Present:" and a list of surnames, then items. Each item ends with a line "Action Taken:" followed by the action. Heading lines use `I.`, `1)`, `1.` or `A.` depending on the committee. Public Safety lists licence applications under one heading with no number of their own. Every page after the first repeats the first header lines, and every page ends with "Page N of M" and "FULL TRANSCRIPTION AVAILABLE UPON REQUEST".

The 89 minutes hold 768 actions. By the category rules in M2: `recommended` 347, `recommended_consent` 244, `minutes_approved` 71, `information_only` 31, `recommended_no_quorum` 20, `delayed` 15, `withdrawn` 10, `adjourned` 6, `no_recommendation` 5, `tabled` 2, `recommended_deny` 2, and `other` 15. These counts came from a prototype whose rule for where an action ends was looser than M2's, so M2's counts may differ by a few; the operator's dry run in M6 records the real ones.

Matching against production, read-only, on 2026-11-13: Birmingham has 109 non-council meeting rows dated 2025-10-01 or later; 92 came from YouTube (`external_id` beginning `yt-`). Of the 198 committee documents, 154 name a committee and date for which a committee meeting row exists. The rest: 28 Economic and Workforce Development / Tourism documents (one meeting row exists for that committee, dated 2026-11-03); Public Safety minutes for 2026-03-10, 2026-06-09 and 2026-10-13; Budget and Finance documents for 2025-12-08 and an agenda for 2026-10-26; Arts and Parks documents for 2026-01-20; and a few agendas. On 2026-10-13 production holds a second Granicus clip (meeting 2612) typed `council`, which is probably the Public Safety meeting mislabelled; this plan does not retype it and reports such days. About 17 meeting rows are expected to be created from minutes.

Fifty-five `agenda_items` rows sit under three meetings typed `committee` today (meetings 2374, 2541 and 2613, all `type_source = 'schedule_rule'`, none with a committee named). They are council agenda items attached to mislabelled rows. This plan leaves them alone and records them as debt.

### Fixtures

`tests/fixtures/committee_documents/` holds nine of those PDFs and one committee page, committed with this plan, with a `README.md` naming where each was listed and why it was chosen. Every expected value in M1 and M2 was obtained by reading these files with `extract_text_from_pdf` and applying the stated rule by hand or by prototype.

### Readers that this plan changes, and readers it must not

The only page that changes is the meeting page. The created meeting rows are ordinary `committee` rows with `type_source = 'title'` and no recording, and reach every list of meetings the way a YouTube-created committee row does today: the city's meeting list, the sitemap, and search over meeting titles. The city page's "last meeting" and "next meeting" select `meeting_type = 'council'` and are unaffected. Because no `agenda_items` or `votes` row is written, the AI stages, the money list, item search, member pages and vote counts are unaffected; M3's test asserts that the row counts of `agenda_items` and `votes` do not change.

## Plan of Work

### M1: Read a committee page's listing and a document's header

Scope: two pure functions and their tests. Nothing is fetched and nothing is stored.

Create `src/docket/adapters/committee_documents.py`. Add the canonical committee table: for each of the eight names in `BIRMINGHAM_COMMITTEES`, one case-insensitive pattern, tested against upper-cased text: Arts and Parks `ARTS`; Budget and Finance `BUDGET`; Committee of the Whole / Administration & Governmental Affairs `COMMITTEE\s+OF\s+THE\s+WHOLE|GOVERNMENTAL\s+AFFAIRS`; Community Development `COMMUNITY\s+DEVELOPMENT`; Economic and Workforce Development / Tourism `ECONOMIC`; Planning & Zoning `PLANNING`; Public Safety `PUBLIC\s+SAFETY`; Transportation & Infrastructure `TRANSPORTATION`. `committees_named(text) -> tuple[str, ...]` returns the canonical names whose pattern is found, ordered by where each is first found in the text. An adapter may not import a service (`ARCHITECTURE.md`), so the module holds its own tuple of the eight names and a unit test asserts it equals `meeting_types.BIRMINGHAM_COMMITTEES`.

`parse_committee_page(html, page_url) -> list[Listing]`: load `__NEXT_DATA__` as JSON, walk it for every string value containing `media--type-document`, parse each with `BeautifulSoup`, and walk its `<h4>` and `<article class="media--type-document">` elements in document order. Each article yields a `Listing` with the `file` attribute as `url`, the `name` attribute (HTML entities decoded) as `listed_name`, the text of the nearest preceding `<h4>` as `listed_heading` (or None), and `page_url`. A `url` seen twice on the page is kept once. Keep only addresses beginning `https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/` or `https://www.birminghamal.gov/` and ending `.pdf` (case-insensitive).

`read_date(text) -> tuple[int | None, int, int] | None`: the first match in the text of a month word, a day, and an optional year. The month word is 3 to 12 letters and is identified by its first three letters alone (so "SEPTEBMBER" is September); the day may carry `st`, `nd`, `rd` or `th`; the year is four characters, each a digit or the letter O, which with O read as zero begin `19` or `20` (one scanned-looking header prints "2O26"). A word whose first three letters are not a month's is skipped and the search continues. The day is 1 to 31 and is not the start of a longer number ("MAY 2026" is not a date), and the month word starts at a word's beginning.

`read_header(text) -> Header | None`. Take the non-empty lines of the text, stripped. The header is the lines before the first heading line, and at most the first 20. If the header, joined and upper-cased, contains `REGULAR MEETING OF THE COUNCIL`, return None: it is not a committee document. Return None also when there is no header line at all. Otherwise return a `Header` with `committees = committees_named(joined header)`, `date = read_date` applied line by line to the header (first line that yields one), `is_minutes = True` when some header line, upper-cased, is exactly `MINUTES`, and `special` / `work_session` true when the joined header contains `SPECIAL CALLED` / `WORK SESSION`.

`resolve(listing, page_committee, header) -> DocumentFacts` combines the two, the document first. `committees`: the header's when it names any, else `(page_committee,)`. `kind`: `minutes` when `header.is_minutes`; else, when there is a header, `agenda`; when there is no text at all, `minutes` if the listed name contains `MINUTES`, `agenda` if it contains `AGENDA`, else None. `meeting_date`: the header's date when it has a year; when the header has month and day without a year, the heading's year if the heading's month and day are the same, else None; when the header has no date, the heading's date if it has a year, else None. `date_source` is `header` or `heading` accordingly. `listing_disagrees` is true when both the header and the heading give a full date and they differ, or the header names at least one committee and none of them is the page's committee. A date that is no day of the calendar is None, and `date_source` is None whenever `meeting_date` is.

Tests in `tests/unit/test_committee_documents_read.py`, each reading a fixture with `extract_text_from_pdf`:

- `page_planning_zoning.html` yields 27 listings under 15 distinct headings; the first is under "OCTOBER 13, 2026" with listed name "PLANNING AND ZONING COMMITTEE MEETING AGENDA, October 13, 2026.pdf"; the listing whose address ends `PLANNING%20AND%20ZONING%20COMMITTEE%20MEETING%2C%20September%208%2C%202026.pdf` is under "SEPTEMBER 8, 2026".
- `bf_minutes_2026-10-12.pdf`: committees `("Budget and Finance",)`, date `(2026, 10, 12)`, minutes.
- `pz_minutes_2026-09-08.pdf`: committees `("Planning & Zoning",)`, date `(2026, 9, 8)` although the header prints "SEPTEBMBER", minutes.
- `ps_cow_joint_minutes_2025-11-25.pdf`: committees `("Public Safety", "Committee of the Whole / Administration & Governmental Affairs")` in that order, date `(2025, 11, 25)`, minutes.
- `cd_minutes_2026-05-04_posted_under_bf.pdf` resolved with page committee "Budget and Finance" and heading "JUNE 22, 2026": committees `("Community Development",)`, date 2026-05-04, `date_source` header, `listing_disagrees` true.
- `ed_agenda_june_2_no_year.pdf`: header date `(None, 6, 2)`, agenda; resolved with heading "JUNE 2, 2026" the date is 2026-06-02 with `date_source` heading; resolved with heading "JUNE 16, 2026" the date is None.
- `pz_agenda_2026-01-27_with_minutes_appended.pdf`: agenda, date `(2026, 1, 27)`, although the text contains "Action Taken".
- `ps_agenda_2026-09-22_scanned.pdf`: `extract_text_from_pdf` returns fewer than 200 non-space characters; `resolve` with no header, page committee "Public Safety", heading "SEPTEMBER 22, 2026" and listed name containing "AGENDA" gives an agenda dated 2026-09-22 with `date_source` heading.
- A text whose header contains "REGULAR MEETING OF THE COUNCIL" gives None.
- `read_date` on "MAY12, 2026" gives `(2026, 5, 12)` (no space is required between the month and the day). On "Tuesday, November 18th" it gives `(None, 11, 18)`; on "TUESDAY, May 26, 2O26" it gives `(2026, 5, 26)`; on "MONDAY" alone it gives None.
- The module's committee tuple equals `meeting_types.BIRMINGHAM_COMMITTEES`.

### M2: Read minutes into items

Scope: one pure function, `parse_minutes_items(text) -> MinutesFacts`, in the same module, and its tests.

Prepare the lines. Take the text's lines, stripped, and drop empty ones. The header lines are those M1 identified. From the lines after the header, drop every line that matches `^Page \d+ of \d+$` or equals "FULL TRANSCRIPTION AVAILABLE UPON REQUEST" (case-insensitive), and every line that is identical to one of the header lines (the repeated page header). `present` is the text after the colon on the header line matching `Councilor\(s\):?\s*Present\s*:?`, or None.

Find the actions. An action begins at a line matching `^Action Taken\s*:?\s*(.*)$` (case-insensitive); any text after the colon is its first line. Its **stretch** is the following lines up to, and not including, the next heading line or the next "Action Taken" line, whichever comes first, or the end. A heading line matches `^(?:[IVXLivxl]{1,6}|\d{1,2}|[A-Za-z])[.)]\s+\S`.

Decide where the action ends inside its stretch, using the **outcome endings**: case-insensitive patterns tested against the action's lines joined with single spaces, anchored at the end and allowing trailing full stops and spaces:

    items? recomm\w* to the city council(?: consent)?(?: agen\w*)?(?: by the committee chair\s*[–-]\s*lack of quorum| with (?:a )?no recommendation| with a recommendation to deny| for approval)?
    (?:forwarded|forward item) to the city council agen\w* with(?:out)? a (?:no )?recommendation
    no action\s*[–-]\s*information\w* only
    item withdrawn(?: by (?:the )?administration)?
    item tabled
    item delayed
    minutes were approved(?: as recorded| with said corrections)?
    meeting adjourned

The spellings are the minutes' own, misspellings included ("Recommeded", "Agena"); `recomm\w*` and `agen\w*` cover them. Add lines of the stretch one at a time. At the first line after which the joined text ends with an outcome ending, look one and two lines further within the stretch: if joining them still ends with an outcome ending, and that ending begins at the same word as the one first found, take the longest such extension (this is how "… Agenda By The Committee Chair – Lack of" followed by "Quorum." is kept whole when the first line alone already ended the shorter pattern). The action ends there. If no line of the stretch produces an outcome ending: when the stretch ends at a heading line or the end of the text, the whole stretch is the action; when it ends at another "Action Taken" line, the action is the lines through the first one that ends with a full stop, or the first line if none does. Lines of the stretch after the action's end begin the next item.

Build the items. An item is the lines since the previous action's end (or since the header), and the action. Its `heading_label` and `heading_text` come from the last heading line among its lines, or, when it has none, from the most recent heading line before it; `owns_heading` is true in the first case. Its `body` is its lines that are not heading lines, joined with newlines. Count the actions that share each heading (an item shares the heading it owns or inherits). When a heading is shared by one action, the item's `name` is the heading's text and `group` is None. When it is shared by two or more, each item's `name` is its first body line and its `group` is the heading's label and text. Lines after the last action belong to no item and are counted as `trailing_lines`.

Read the action. `action_text` is the action's lines joined with single spaces. `moved_by` is the first capture of `Councilor(?: Pro Tem| President)? ([A-Z][\w’'-]+) Motioned`, `seconded_by` the first of `Councilor(?: Pro Tem| President)? ([A-Z][\w’'-]+) Seconded`, each None when absent. `action_category` is the first of these whose pattern is found anywhere in `action_text`, case-insensitive, in this order: `minutes_approved` (`minutes were approved`); `recommended_no_quorum` (`recomm\w*.*lack of quorum`); `recommended_deny` (`recommendation to deny`); `no_recommendation` (`(?:with\s+(?:a\s+)?no|without\s+a)\s+recommendation`); `recommended_consent` (`recomm\w*\s+to\s+the\s+city\s+council\s+consent`); `recommended` (`recomm\w*\s+(?:item\s+)?to\s+the\s+city\s+council`); `information_only` (`no\s+action\s*[–-]\s*information`); `withdrawn` (`\bwithdrawn\b`); `tabled` (`\btabled\b`); `delayed` (`\bdelayed\b`); `adjourned` (`\badjourned\b`); else `other`. The order matters: "Approval of Minute Delayed – Lack of Quorum." has no "recomm" and is `delayed`, not `recommended_no_quorum`.

Tests in `tests/unit/test_committee_documents_minutes.py`. The expected values below were read from the fixtures' extracted text line by line.

- `ps_minutes_2026-09-22.pdf`: `present` is "Tate"; 11 items. In order, name and category: "APPROVAL OF MINUTES – September 8, 2026" `delayed`; "Welcome Mart" `recommended_no_quorum`; "LA Cabana" `recommended_no_quorum`; "Bargoods" `recommended_no_quorum`; "Bargoods" `recommended_no_quorum`; "Rock N Roll Sushi 280" `recommended_no_quorum`; "Pike Road Market & Meats" `other`; "Graymont Foods" `recommended_no_quorum`; "Legion Field" `recommended_no_quorum`; "Resolution: Motorola Solutions, Inc." `recommended_no_quorum`; "Resolution: University of Alabama Health Services Foundation, P.C." `recommended_no_quorum`. Items two to nine have the group "C. LIQUOR LICENSES" and the last two "D. Ordinances/Resolutions". The seventh item's `action_text` is exactly "Applicant Not Present for Meeting." and the eighth item's name is "Graymont Foods", which proves a free-text action stops at its first sentence when another action follows. The second item's `action_text` is "Item Recommended to the City Council Agenda By The Committee Chair – Lack of Quorum.", which proves the wrapped ending is kept whole. The third item's body contains "There are no tax delinquencies for this location." and does not contain "PUBLIC SAFETY COMMITTEEMEETING", which proves the repeated page header is dropped. No `moved_by` anywhere.
- `pz_minutes_2026-09-08.pdf`: `present` is "O’Quinn, Tate, Woods"; 4 items: "APPROVAL OF THE MINUTES – July 28, 2026 & August 25, 2026" `minutes_approved`, moved by Woods, seconded by Tate; "ZONING CASES" `recommended`, moved by O’Quinn, seconded by Tate, body containing "ZAC2026-08007", group None; "Birmingham Planning Commission, PEP Staff" `recommended`; "Birmingham Historical Commission, Lauren Havard, PEP- Urban Design" `recommended`, moved by Woods. The third item's `action_text` ends "The terms will expire in 2032. Item Recommended to the City Council Agenda.", which proves an action runs to its outcome ending and not to its first full stop. `trailing_lines` is greater than zero (the adjournment has no "Action Taken").
- `ti_minutes_2026-05-11.pdf`: 6 items with categories, in order, `minutes_approved`, `recommended`, `recommended`, `recommended`, `recommended`, `information_only`. The fifth is named "Parking Reform Update", label "VI.", moved by O’Quinn, seconded by Smith, and its `action_text` contains "including the amendment increasing the fine under Section 10-9-16(A) to $60 for commercial vehicles". The sixth has no mover.
- `bf_minutes_2026-10-12.pdf`: 12 items; categories total 1 `minutes_approved`, 9 `recommended_consent`, 2 `recommended`; one item is named "Friends of Avondale Park", `recommended_consent`, moved by Alexander, seconded by Woods, its body containing "$4,000"; one is named "Consideration of the Consent Agenda", `recommended_consent`; one is named "Space One Eleven" and its body does not contain "Page 2 of 6".
- `ps_cow_joint_minutes_2025-11-25.pdf`: 10 items.
- `pz_agenda_2026-01-27_with_minutes_appended.pdf` is not passed to this function by the service (it is an agenda); no test.

If a fixture's result differs from these, the rule as stated is wrong or the reading here is; do not bend the test. Record the difference in Surprises & Discoveries with the fixture's lines, decide in the Decision Log which is right from the PDF itself, and mend the plan's rule text in the same commit.

### M3: Store documents and items

Scope: a migration, and a service that lists, fetches, reads and stores. No matching to meetings yet.

Add the next free migration (045 unless another has landed; name it `0NN_committee_documents.py`), registered in `runner.MIGRATIONS`, creating:

    committee_documents
      id               serial primary key
      municipality_id  integer not null references municipalities
      url              text not null
      page_url         text not null
      page_committee   text not null
      listed_name      text
      listed_heading   text
      first_seen_at    timestamptz not null default now()
      last_seen_at     timestamptz not null default now()
      status           text not null default 'listed'
                       check (status in ('listed','read','no_text','not_committee','fetch_failed'))
      fetched_at       timestamptz
      fetch_attempts   integer not null default 0
      pdf_sha256       text
      text             text
      kind             text check (kind in ('agenda','minutes'))
      committees       text[] not null default '{}'
      meeting_date     date
      date_source      text check (date_source in ('header','heading'))
      listing_disagrees boolean not null default false
      special          boolean not null default false
      work_session     boolean not null default false
      present          text
      trailing_lines   integer
      parser_version   smallint
      meeting_id       integer references meetings on delete set null
      attached_by      text check (attached_by in ('matched','created'))
      unique (municipality_id, url)

    committee_items
      id               serial primary key
      document_id      integer not null references committee_documents on delete cascade
      position         integer not null
      heading_label    text
      heading_text     text
      owns_heading     boolean not null
      group_text       text
      name             text not null
      body             text not null default ''
      action_text      text not null
      action_category  text not null check (action_category in ('recommended','recommended_consent',
                       'recommended_no_quorum','no_recommendation','recommended_deny','information_only',
                       'withdrawn','tabled','delayed','minutes_approved','adjourned','other'))
      moved_by         text
      seconded_by      text
      unique (document_id, position)

with an index on `committee_documents (meeting_id)`. The same migration sets, for Birmingham only, `municipalities.metadata.committee_document_pages` to a JSON list of eight objects `{"committee": <canonical name>, "url": <page address>}` using the eight slugs in Context, with `jsonb_set` so other keys are untouched. `SQL_DOWN` drops both tables and removes the key. Write `tests/integration/test_0NN_migration.py` after `test_044_migration.py`: registered in order; up creates both tables and the key with eight entries; each CHECK rejects a bad value; up twice is harmless; down removes all three.

In the adapter add `fetch_page(url) -> str` and `fetch_pdf(url) -> bytes | None`. Both go through one module-level one-second gap of this module's own, with `city_calendar._BROWSER_UA`'s value copied as a constant and a 60 second timeout; `fetch_pdf` streams, stops and returns None past 40 MB, and returns None when the body does not begin `%PDF-`. Two different hosts are involved (the city's site and its Amazon bucket); one shared gap is the stricter choice.

Create `src/docket/services/committee_documents.py` with `PARSER_VERSION = 1` and:

- `sync_listings(municipality_id, pages) -> int`: for each configured page, fetch and parse it, and upsert each listing by `(municipality_id, url)`: a new address inserts with status `listed`; a known one updates `last_seen_at`, `listed_name` and `listed_heading` only. A page that fails to fetch or parse is logged and skipped; the function raises only when every page failed. Returns the number of new rows.
- `read_pending(municipality_id, limit) -> int`: for up to `limit` rows with status `listed`, or `fetch_failed` with `fetch_attempts < 3`, oldest first: fetch the PDF; on failure set `fetch_failed` and add one to `fetch_attempts`; otherwise store the sha256 and call `_read(row, pdf_bytes)`. Returns the number read.
- `_read`: extract the text. Fewer than 200 non-space characters: status `no_text`, text NULL, facts from `resolve` with no header. `read_header` returns None: status `not_committee`, text stored, no facts. Otherwise status `read`, the text stored, and the facts from `resolve`; when the kind is `minutes`, replace the document's `committee_items` rows with `parse_minutes_items`'s items, numbered from 1 in order, and store `present` and `trailing_lines`. One transaction per document. Set `parser_version`.
- `reparse(municipality_id) -> int`: for every row with stored text and `parser_version` below `PARSER_VERSION`, run the same reading from the stored text with no fetch.

Tests in `tests/services/test_committee_documents_store.py`, with `fetch_page` and `fetch_pdf` patched to return the fixtures: syncing the Planning and Zoning fixture page inserts 27 rows, and syncing again inserts none and changes no `first_seen_at`; reading with the budget minutes fixture gives a `read` row, kind `minutes`, date 2026-10-12, 12 items; reading the scanned fixture gives `no_text`, kind `agenda`, date from the heading, no items; a fetch that returns None three times leaves `fetch_failed` with three attempts and a fourth `read_pending` does not select it; `reparse` after lowering a row's `parser_version` rebuilds the same 12 items with the same positions; and the counts of `agenda_items` and `votes` are the same before and after every call.

### M4: Attach documents to meetings, and create meetings from minutes

Scope: `attach(municipality_id, today) -> AttachReport` in the service, and its tests.

`committee_of(body_name) -> str | None` returns the single canonical committee `committees_named(body_name)` finds, or None when it finds none or several.

For each document with status `read` or `no_text`, a kind, a `meeting_date`, at least one committee, and `meeting_id` NULL: the candidates are this municipality's meetings on that date with `is_hidden = FALSE`, `meeting_type = 'committee'`, and `committee_of(body_name)` among the document's committees. One candidate: attach, `attached_by = 'matched'`. Several: take those for the document's first-named committee if any, then prefer a row with a `video_url`, then the lowest id; attach, and count the document in `ambiguous`. None: when the kind is `minutes`, `date_source` is `header`, and the date is not after `today`, create a meeting and attach with `attached_by = 'created'`; otherwise leave it unattached (it is retried on every run, so an agenda attaches once a recording creates its meeting).

A created meeting: `external_id` is `cdoc-<slug>-<yyyy-mm-dd>` where the slug is the first-named committee's page slug from Context without the trailing `-committee` (for example `cdoc-budget-finance-2026-10-12`); `title` is the first-named committee's canonical name followed by " Committee Meeting", or " Committee Work Session" when the document's `work_session` is true, with "Special Called " in front when `special` is true; `meeting_type`, `session_kind` and `body_name` are what `classify_title(title)` returns; `type_source` is `'title'`; `source_url` is the document's `page_url`; `agenda_url`, `minutes_url` and `video_url` are NULL. The insert ends `ON CONFLICT (municipality_id, external_id) DO NOTHING RETURNING id`; when it returns nothing, select the existing row's id and attach to it.

`primary_documents(meeting_id) -> dict` returns, per kind, the meeting's one primary document: among its attached documents of that kind, those with `listing_disagrees` false first, then the lowest id. The meeting's items are the primary minutes' items.

`AttachReport` counts `matched`, `created`, `ambiguous`, `unattached_agendas`, `unattached_minutes`, and lists `crowded_days`: each created meeting's date on which the municipality also has a visible Granicus meeting (numeric `external_id`) typed `council` beyond the first, which is the sign of a mislabelled committee clip (2026-10-13 is one). The report is returned and logged; it changes nothing.

Tests in `tests/services/test_committee_documents_attach.py`, on rows inserted by the test: minutes for "Budget and Finance" on a date with a row whose `body_name` is "Budget & Finance Committee" attach to it, matched; minutes for "Economic and Workforce Development / Tourism" attach to a row whose `body_name` is "Economic Development & Tourism Committee Work Session"; minutes with no row create one whose `external_id` is `cdoc-economic-workforce-development-tourism-<date>`, typed `committee`, and a second `attach` creates nothing and reports nothing new; an agenda with no row creates nothing and stays unattached, and attaches on the next call after the test inserts a matching row; minutes dated after `today` create nothing; a hidden meeting is not a candidate; a meeting typed `council` on the same date is not a candidate; joint minutes naming Public Safety then Committee of the Whole, on a date with a row for each, attach to the Public Safety row and count as ambiguous; a meeting with two minutes documents, one with `listing_disagrees` true, has the other as primary whichever was inserted first; deleting a meeting leaves its documents with `meeting_id` NULL.

### M5: Show it on the meeting page

Scope: one service read, one partial, one edit to the meeting route and template, tests.

Add `for_meeting(meeting_id) -> MeetingCommitteeRecord | None` to the service: None when the meeting has no attached document; otherwise the meeting's documents (each with kind, address, whether it is primary, whether it has text), the primary minutes' `present`, and the primary minutes' items in position order.

In `meeting_detail` in `src/docket/web/public.py`, call it and pass the result to the template as `committee_record`. Create `src/docket/web/templates/partials/committee_record.html`, included in `meeting_detail.html` directly after the hero's `kpi-strip` and only when `committee_record` is not None. It renders, in order:

- A heading "From the committee's own documents" and one link per document, primaries first: "Agenda (PDF)" or "Minutes (PDF)", each opening the city's address in a new tab with `rel="noopener"`. A second document of a kind is labelled "another copy". A document with no text adds "scanned image; not read".
- When there are minutes: "Councilors present: " and the `present` text, then the heading "What the committee took up" and the items as an ordered list. Each item shows its group once, before the first item that has it; its name; its body inside a closed `<details>` whose summary is "What the minutes say" (omitted when the body is empty); a line "Moved by X, seconded by Y" when both are stored, "Moved by X" when only one; the category's label; and the `action_text` in a `blockquote` introduced by "The minutes record:". Items whose category is `minutes_approved` or `adjourned` are listed last under "Procedural", closed by default.
- When there is an agenda and no minutes: the sentence "The committee's minutes for this meeting are not yet posted. The agenda shows what was planned; it does not show what the committee did."
- A closing line: "A committee recommends; it does not decide. No committee action is final without a vote of the full council." with no link (the explainer page it would link to is a separate plan).

The category labels: `recommended` "Recommended to the council"; `recommended_consent` "Recommended to the council's consent agenda"; `recommended_no_quorum` "Sent to the council by the chair; no quorum"; `no_recommendation` "Sent to the council with no recommendation"; `recommended_deny` "Sent to the council with a recommendation to deny"; `information_only` "Information only; no action"; `withdrawn` "Withdrawn"; `tabled` "Tabled"; `delayed` "Delayed"; `other` no label, the quoted words only.

In the `kpi-strip`, when `committee_record` has items and the meeting has no `agenda_items`, the first figure reads "Items in the minutes" with the count of non-procedural items and no "consent · regular" line, and the "Votes" figure's sub-line reads "committees record motions, not roll calls" in place of "none recorded". Leave the strip unchanged otherwise.

Styles go in the existing stylesheet the meeting page uses, with existing custom properties; define no new colours. The list must read in order without styles.

Tests in `tests/web/test_committee_record_page.py`, seeding a committee meeting, a minutes document with three items (one `recommended_consent` with mover and seconder, one `other`, one `minutes_approved`) and an agenda document: the page returns 200 and contains both PDF addresses, "What the committee took up", the item's name, "Moved by Alexander, seconded by Woods", "Recommended to the council's consent agenda", the `other` item's exact action text, and "Items in the minutes"; "Procedural" comes after the last substantive item; a meeting with only an agenda document contains "not yet posted" and no "What the committee took up"; a meeting with no document does not contain "From the committee's own documents" and its `kpi-strip` still reads "Agenda items"; a council meeting's page is byte-for-byte unchanged in the strip (assert "Agenda items" present and "Items in the minutes" absent). No page contains the words "passed", "failed" or a tally for a committee item.

### M6: Keep it current, and fill production

Scope: a worker task, an operator script, and the counts the design asked for.

Add to the service `refresh_city(municipality_id, metadata, today, read_limit) -> RefreshReport`, which calls `sync_listings`, `read_pending(limit=read_limit)`, `reparse` and `attach` in that order and returns their counts, and `refresh_all(today) -> int`, which runs it for every active municipality whose metadata has `committee_document_pages`, with `read_limit = 25`. Twenty-five PDFs and eight pages a day is at most 33 requests, one a second.

Register the worker task `committee_documents` after the model of `city_calendar`: `_do_committee_documents` and `task_committee_documents` in `src/docket/worker/tasks.py`, an entry in `TASKS`, `"committee_documents": "HEALTHCHECK_COMMITTEE_DOCUMENTS_UUID"` in `health.TASK_UUID_ENV`, and a job in `build_scheduler` at 07:15 (after `youtube_ingest` at 06:45 has created or matched the day's recordings, so a new document finds its meeting). Update `tests/unit/test_worker_scheduler.py` (the pinned set becomes nineteen ids, and the hour table gains the row) and confirm `tests/unit/test_worker_health.py` passes. Change "eighteen" to "nineteen" in the `scheduler.py` docstring, `README.md` and `docs/runbooks/cron-worker.md`, and add the task to that runbook's inventory, variable block and schedule table.

Add `scripts/backfill_committee_documents.py --city <slug> [--dry-run] [--limit N]`, after the model of `scripts/backfill_youtube_meetings.py`: it runs the same four steps with no read limit unless `--limit` is given. With `--dry-run` it fetches and reads but runs inside one transaction that it rolls back, and prints what it would do. It prints: documents by status and kind; how many took their date from the header and from the heading, and how many have `listing_disagrees`; items by category; the `AttachReport`; the list of meetings it would create; and, per canonical committee, for meetings dated 2026-01-01 or later, how many meetings there are, how many have an agenda, minutes and items, how many have a document and no `video_url`, and how many have a `video_url` and no document.

Tests in `tests/services/test_committee_documents_refresh.py`: `refresh_city` with patched fetches runs the four steps and a second call reads and creates nothing; `read_limit = 1` reads one document per call; a page that fails is skipped while the others are stored. `tests/unit/` gains a test that the script's `--dry-run` leaves the row counts of `committee_documents`, `committee_items` and `meetings` unchanged.

### M7: Write it down

Scope: documents only.

Write `docs/specs/committee-documents.md` in the present tense: the source pages and where they are configured; how a document's committee, date and kind are decided, and the fallback order; the item rules and the category list with each pattern; storage; attaching and creating; what the meeting page shows; the worker task and the script; and how to correct a misread (fix the rule, raise `PARSER_VERSION`, let `reparse` run). Add it to `docs/specs/index.md`. In `docs/specs/meeting-types.md` add one paragraph: a committee meeting can now be created from minutes, with `external_id` beginning `cdoc-` and `type_source = 'title'`. In `docs/birmingham/01-sources.md` correct the sentence that Granicus is the only word on committee meetings, and in `docs/birmingham/02-ingest.md` add the committee documents path. Graduate to `docs/decisions/` the Decision Log entries that outlive this plan, each numbered by the rule in force (the lowest number above every one spent on `origin/main` and on any open pull request at that moment). Add rows to `docs/DEBT.md`, numbered by the same rule: agenda items are not read (trigger: a reader asks what an upcoming committee meeting will take up); scanned agendas are linked and not read (trigger: the share of scanned documents rises, or minutes arrive scanned); committee items are not in search and have no page of their own (trigger: the progress strip of the "how it works" design needs to link one); the committee pages' address carries the council term "2025-2027" and will change (trigger: a `sync_listings` run finds no listing on any page); a `cdoc-` meeting and a later `yt-` meeting for the same committee and date are not merged (trigger: the backfill's report or a reader shows a committee listed twice on one day); the 55 council items under three mislabelled committee meetings (2374, 2541, 2613); and the operator's steps in Validation and Acceptance (trigger: the pull request merges). Do not move this plan to `plans/completed/` and do not write the closing retrospective; the retro stage does both.

## Concrete Steps

Work from the root of the checkout the plan is executed in, with that checkout's own `venv/`. The only test command is:

    ./tools/verify

At authoring, `tools/check-plans plans/active/committee-documents.md` was run on this file and its output is recorded in Artifacts and Notes.

To read a fixture the way the code will, while building M1 and M2:

    venv/bin/python -c "import sys; from docket.analysis.minutes_parser import extract_text_from_pdf; print(extract_text_from_pdf(open(sys.argv[1],'rb').read()))" tests/fixtures/committee_documents/ps_minutes_2026-09-22.pdf

A milestone session fetches nothing from the city's site: every test runs on the committed fixtures with the fetch functions patched. Each milestone ends with `./tools/verify` passing, the plan's living sections updated with what was observed, and a commit.

## Validation and Acceptance

M1 is accepted when `./tools/verify` exits zero with the tests of `tests/unit/test_committee_documents_read.py` passing, and when changing the month rule to require a whole month name makes the `pz_minutes_2026-09-08.pdf` test fail (restore it; record both observations).

M2 is accepted when `./tools/verify` exits zero with the tests of `tests/unit/test_committee_documents_minutes.py` passing, the eleven Public Safety items and their categories among them.

M3 is accepted when `./tools/verify` exits zero, including the new migration test in the integration tier, and the store test's assertion that `agenda_items` and `votes` counts are unchanged.

M4 is accepted when `./tools/verify` exits zero with the attach tests passing, the test that a second `attach` creates nothing among them.

M5 is accepted when `./tools/verify` exits zero, and when, with the dev server running against a local database into which the session has inserted one committee meeting and loaded the budget minutes fixture through `_read` and `attach`, `curl -s http://127.0.0.1:5000/al/birmingham/meetings/<id>/ | grep -c 'Friends of Avondale Park'` prints at least 1 and the same page contains "Recommended to the council's consent agenda".

M6 is accepted when `./tools/verify` exits zero with nineteen scheduled jobs, and `venv/bin/python scripts/backfill_committee_documents.py --help` prints the three options.

M7 is accepted when `./tools/verify` exits zero, `docs/specs/committee-documents.md` exists and is listed in the index, and `docs/DEBT.md` has the rows named in M7.

Before the pull request merges, the operator, from a laptop with `DATABASE_URL` set to production's public address as `docs/specs/operations.md` describes, runs `scripts/backfill_committee_documents.py --city birmingham --dry-run` (about 200 PDF requests at one a second, under five minutes) and compares its output with the survey in Context. The plan's design holds if: at least 180 of the roughly 199 documents are `read` or `no_text` with a committee, date and kind; `other` is at most 5 percent of items; at least 140 documents attach to an existing meeting; and at most 25 meetings would be created, none dated before 2025-11-01 or after the day of the run. A result outside any of these is a Surprises & Discoveries entry and a Decision Log entry before merge, not a silent adjustment. The dry run needs the migration's tables; it creates them inside its own rolled-back transaction if they are absent.

After the merge and the deploy of `docket-web` (which runs the migration) and `worker`: the operator runs the script without `--dry-run`, then a second `--dry-run`, which reports nothing new to read, attach or create; sets `HEALTHCHECK_COMMITTEE_DOCUMENTS_UUID` on the `worker` service; and opens the Transportation and Infrastructure meeting of 2026-05-11 (meeting 3142) and the Budget and Finance meeting of 2026-10-12 (meeting 3183) on the live site, confirming "Parking Reform Update" and "Friends of Avondale Park" appear with their actions and that both PDF links open the city's documents.

## Idempotence and Recovery

Every write is an upsert or a guarded insert: listings by `(municipality_id, url)`, items replaced per document in one transaction, meetings by `(municipality_id, external_id)`, attachment only where `meeting_id` is NULL. Any step can be run again. A document that fails to fetch is retried on later runs up to three attempts. A rule change is applied by raising `PARSER_VERSION`; `reparse` rebuilds items from stored text without fetching. To undo the whole source in production: `DELETE FROM meetings WHERE external_id LIKE 'cdoc-%'` for the municipality (their documents' `meeting_id` becomes NULL by the foreign key), then roll the migration back, which drops both tables and the metadata key. No existing row of any existing table is updated by this plan.

## Artifacts and Notes

Survey figures, production row counts and the fixture list are in Context and Orientation. The scripts that produced them were throwaway and are not in the repository; the operator's dry run in Validation and Acceptance reproduces every figure that matters from the real code.

Output of `tools/check-plans plans/active/committee-documents.md` at authoring:

    plans: plans/active/committee-documents.md ... ok (Progress, Surprises & Discoveries, Decision Log, Outcomes & Retrospective)
    plans: 1 of 1 ok

M1 acceptance, observed 2026-11-15. `./tools/verify`, run at commit `2d8718e` (the module, its tests and the plan's decisions; the only later change is this file's own record of the run):

    verify: test-db ... ok (0s) postgresql://docket:docket_dev@localhost:5432/docket_test_61bde166
    verify: unit+web+services ... ok (93s)
    verify: integration ... ok (106s)
    verify: judge-fixtures ... ok (0s)
    verify: workflows ... ok (0s)
    verify: transcriber ... ok (8s)
    verify: plans ... ok (0s)
    verify: all 6 checks passed in 207s.

The unit, web and services tiers printed `2743 passed, 5 skipped, 4 xfailed, 2 warnings in 91.07s`; the run before any edit printed `2726 passed, 5 skipped, 4 xfailed, 2 warnings in 90.17s`, and the difference is the 17 tests of `tests/unit/test_committee_documents_read.py`, which run alone print `17 passed, 1 warning in 1.50s`.

The month rule changed to require a whole month name, in a copy of the module compiled in memory (the committed file was not edited; `diff` of the copy against it showed the one line), with the same 17 tests run against the copy:

    E       AssertionError: assert None == (2026, 9, 8)
    E        +  where None = <function read_date at 0x77083095e680>('WEDNESDAY, SEPTEBMBER 8, 2026 | 3:00 PM')
    FAILED tests/unit/test_committee_documents_read.py::test_read_date_spellings
    FAILED tests/unit/test_committee_documents_read.py::test_planning_minutes_header_reads_a_misspelled_month
    2 failed, 15 passed, 1 warning in 1.13s

The second failure is the `pz_minutes_2026-09-08.pdf` test: its header's date read None where `(2026, 9, 8)` is expected. With the rule as committed, the 17 pass.

M2 acceptance, observed 2026-11-15. `./tools/verify`, run at commit `178299f` (the function, its tests and the plan's decisions; the only later change is this file's own record of the run), exited zero:

    verify: test-db ... ok (0s) postgresql://docket:docket_dev@localhost:5432/docket_test_61bde166
    verify: unit+web+services ... ok (92s)
    verify: integration ... ok (107s)
    verify: judge-fixtures ... ok (1s)
    verify: workflows ... ok (0s)
    verify: transcriber ... ok (7s)
    verify: plans ... ok (0s)
    verify: all 6 checks passed in 207s.

The unit, web and services tiers printed `2762 passed, 5 skipped, 4 xfailed, 2 warnings in 91.14s`; the run before any edit printed `2743 passed`, and the difference is the 19 tests of `tests/unit/test_committee_documents_minutes.py`, which run alone print `19 passed, 1 warning in 1.24s`. `test_public_safety_minutes_without_a_quorum`, which asserts the eleven Public Safety items by name and category in order, run alone: `1 passed, 18 deselected`. The rule-removal passes are in Surprises & Discoveries.

M3 acceptance, observed 2026-11-15. `./tools/verify`, run at commit `557ed43` (the migration, the fetches, the service, their tests and the plan's decisions; the only later change is this file's own record of the run), exited zero:

    verify: test-db ... ok (0s) postgresql://docket:docket_dev@localhost:5432/docket_test_61bde166
    verify: unit+web+services ... ok (101s)
    verify: integration ... ok (107s)
    verify: judge-fixtures ... ok (1s)
    verify: workflows ... ok (0s)
    verify: transcriber ... ok (8s)
    verify: plans ... ok (0s)
    verify: all 6 checks passed in 217s.

The unit, web and services tiers printed `2794 passed, 5 skipped, 4 xfailed, 2 warnings in 98.76s`; the run before any edit printed `2762 passed`, and the difference is the 23 tests of `tests/services/test_committee_documents_store.py` and the 9 of `tests/unit/test_committee_documents_fetch.py`. The integration tier printed `1023 passed, 2 warnings in 107.09s`; the run before any edit printed `1015 passed`, and the difference is the 8 tests of `tests/integration/test_045_migration.py`, the new migration test. The three files run alone, before that verify, printed `40 passed, 1 warning in 6.78s`. The assertion that the counts of `agenda_items` and `votes` are unchanged is the autouse fixture `only_these_tables` of the store tests: it counts both tables before each of the 23 tests and asserts the same counts after it, so it held 23 times in that run. It compares counts on the throwaway database, which holds few or no rows of either table; what it shows is that no call in a test inserted or deleted one. The rule-removal passes are in Surprises & Discoveries.
M4 acceptance, observed 2026-11-15. `./tools/verify`, run at commit `634429a` (the three functions, their tests and the plan's decisions; the only later change is this file's own record of the run), exited zero:

    verify: test-db ... ok (0s) postgresql://docket:docket_dev@localhost:5432/docket_test_61bde166
    verify: unit+web+services ... ok (105s)
    verify: integration ... ok (110s)
    verify: judge-fixtures ... ok (0s)
    verify: workflows ... ok (1s)
    verify: transcriber ... ok (7s)
    verify: plans ... ok (0s)
    verify: all 6 checks passed in 223s.

The unit, web and services tiers printed `2824 passed, 5 skipped, 4 xfailed, 2 warnings in 102.99s`; M3's last run printed `2794 passed`, and the difference is the 30 tests of `tests/services/test_committee_documents_attach.py`, which run alone print `30 passed, 1 warning in 4.14s`. The integration tier printed `1023 passed, 2 warnings in 109.71s`, as after M3. The test that a second `attach` creates nothing is `test_minutes_with_no_meeting_create_one_and_a_second_attach_creates_nothing`; run alone after that verify it printed `1 passed, 29 deselected`. It asserts that after the second call the only `cdoc-` meeting is the one the first call made and that all five counts and `crowded_days` of the second report are empty. The rule-removal passes are in Surprises & Discoveries.

## Interfaces and Dependencies

No new dependency. `requests`, `BeautifulSoup` and `pdfplumber` are already installed.

In `src/docket/adapters/committee_documents.py`:

    COMMITTEES: tuple[str, ...]                      # equals meeting_types.BIRMINGHAM_COMMITTEES
    COMMITTEE_SLUGS: dict[str, str]                  # canonical name -> page slug

    @dataclass(frozen=True)
    class Listing:
        url: str
        listed_name: str | None
        listed_heading: str | None
        page_url: str

    @dataclass(frozen=True)
    class Header:
        committees: tuple[str, ...]
        date: tuple[int | None, int, int] | None
        is_minutes: bool
        special: bool
        work_session: bool
        lines: tuple[str, ...]

    @dataclass(frozen=True)
    class DocumentFacts:
        committees: tuple[str, ...]
        kind: str | None                 # 'agenda' | 'minutes' | None
        meeting_date: date | None
        date_source: str | None          # 'header' | 'heading' | None
        listing_disagrees: bool
        special: bool
        work_session: bool

    @dataclass(frozen=True)
    class MinutesItem:
        heading_label: str | None
        heading_text: str | None
        owns_heading: bool
        group: str | None
        name: str
        body: str
        action_text: str
        action_category: str
        moved_by: str | None
        seconded_by: str | None

    @dataclass(frozen=True)
    class MinutesFacts:
        present: str | None
        items: tuple[MinutesItem, ...]
        trailing_lines: int

    def committees_named(text: str) -> tuple[str, ...]: ...
    def parse_committee_page(html: str, page_url: str) -> list[Listing]: ...
    def read_date(text: str) -> tuple[int | None, int, int] | None: ...
    def read_header(text: str) -> Header | None: ...
    def resolve(listing: Listing, page_committee: str, header: Header | None) -> DocumentFacts: ...
    def parse_minutes_items(text: str) -> MinutesFacts: ...
    def fetch_page(url: str) -> str: ...
    def fetch_pdf(url: str) -> bytes | None: ...

In `src/docket/services/committee_documents.py`:

    PARSER_VERSION = 1
    class AttachReport: ...   # matched, created, ambiguous, unattached_agendas, unattached_minutes: int; crowded_days: list[date]
    def sync_listings(municipality_id: int, pages: list[dict]) -> int: ...
    def read_pending(municipality_id: int, limit: int | None) -> int: ...
    def reparse(municipality_id: int) -> int: ...
    def committee_of(body_name: str | None) -> str | None: ...
    def attach(municipality_id: int, today: date) -> AttachReport: ...
    def primary_documents(meeting_id: int) -> dict: ...
    def for_meeting(meeting_id: int) -> MeetingCommitteeRecord | None: ...
    def refresh_city(municipality_id: int, metadata: dict, today: date, read_limit: int | None) -> RefreshReport: ...
    def refresh_all(today: date) -> int: ...

Templates: `src/docket/web/templates/partials/committee_record.html`, included by `meeting_detail.html`. Worker task: `committee_documents`, daily at 07:15, health variable `HEALTHCHECK_COMMITTEE_DOCUMENTS_UUID`. Script: `scripts/backfill_committee_documents.py`.

## Revision notes

2026-11-15, M1 session. Three sentences of M1's rule text were changed, each recorded in the Decision Log under the same date: the year rule of `read_date` now reads O as zero in any of the year's four places, because the rule as authored could not produce the plan's own stated result for "2O26", and it states the three limits the session added (day 1 to 31, day not the start of a longer number, month at a word's beginning); `read_header` says it returns None when there is no header line; and the last clause of `resolve` says a header naming no committee does not disagree with its listing, that an impossible date is None, and that `date_source` is None with it. No milestone's scope, acceptance or interface changed.

2026-11-15, M2 session. One sentence of M2's rule text was changed, recorded in the Decision Log under the same date: an ending found one or two lines further extends an action only when it begins at the same word as the ending first found, because the sentence as authored let the next item's lines be taken into an action. No fixture's expected value, and no milestone's scope, acceptance or interface, changed.

2026-11-15, M3 session. No sentence of M3's text was changed. Where it does not say (what a page with no listing is, how a PDF that cannot be fetched or opened is recorded, what the read limit counts, which function writes the hash, the migration's number), the session's readings are in the Decision Log under this date and are to be read with M3. One test file the plan does not name was added, `tests/unit/test_committee_documents_fetch.py`, for the rules M3 states for the two fetches. No milestone's scope, acceptance or interface changed.

2026-11-15, M4 session. No sentence of M4's text was changed. Where it does not say (the order documents are taken in, what each count of `AttachReport` counts, what a held `external_id` is attached as, whether an attached document ever moves, what `primary_documents` returns), the session's readings are in the Decision Log under this date and are to be read with M4. Interfaces and Dependencies gained one line naming `AttachReport`'s fields. No milestone's scope or acceptance changed.
