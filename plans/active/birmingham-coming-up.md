# Give Birmingham a "What's coming up" page and a calendar feed of the same entries

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

Today a Birmingham resident who wants to know what is ahead has to read three places on the city's own sites: the council's video site for the next council meeting, the city calendar for committee meetings, and a three-page PDF for the hundred neighborhood associations. A public hearing's date is harder still: it is one sentence inside a resolution on an earlier agenda. docket.pub already stores the first two and the agenda text, and shows none of it as a list of what is ahead. `https://docket.pub/al/birmingham/coming-up/` answers 404 today and no calendar feed exists anywhere in `src/`.

After this work a reader opens `/al/birmingham/coming-up/` (linked from the Birmingham city page) and sees one list, in date order, of the next 60 days, in three kinds, every entry linked to the city document it came from:

1. Meetings: the council meetings the city's video site lists as upcoming and the council and committee meetings on the city's own calendar, shown together, a council meeting both sources list appearing once.
2. Scheduled public hearings: each hearing whose date a resolution on a Birmingham agenda set, read from the resolution's text by fixed rules with no language model, stored once however many agenda items set it, linked to every one of those items, and given a kind (zoning, weed lots, street or right-of-way, budget, other). A weed-lot resolution is one entry that says how many properties it lists.
3. Neighborhood association meetings: each dated meeting computed from the monthly rule in the Community Resource Services Division's published 2026 schedule, linked to that PDF, with the time, the meeting type, the place, and the call-in details as the schedule gives them and nothing where it gives nothing.

`/al/birmingham/coming-up.ics` returns the same entries as a calendar a phone or desktop calendar can subscribe to: one event per entry on the page.

Added by the revision of 2026-11-16 (the Revision note at the end says why). The feed can be narrowed by its address to one kind (`?kind=meeting`, `?kind=hearing`, `?kind=neighborhood`) or to one neighborhood association (`?association=acipco-finley`), and the page offers each of those as a link, beside a link that opens the reader's calendar program and one that adds the feed to Google Calendar. Every entry carries a small coloured label of its kind. A neighborhood meeting shows where to go and how to call in under the words "How to attend". A meeting one of the city's two sources calls cancelled is shown, marked cancelled, with the source that says so named, and is not left out. And the feed that already exists at `/al/birmingham/upcoming-hearings.rss` lists the same scheduled hearings the page lists, in place of every agenda line that contains the word "hearing".

How to see it working, once every milestone is done: `./tools/verify` passes with the new tests, among them one that asks for the page and the feed from one seeded database and finds the same number of entries in each; after the operator's deploy and backfill (Validation and Acceptance), `curl -s https://docket.pub/al/birmingham/coming-up.ics | head -3` prints `BEGIN:VCALENDAR` first, and the page lists the next council meeting once, with a link to the city's event page and one to the agenda.

## Progress

- [x] (2026-11-17 03:53Z) M1: The hearing reader exists as a pure module, and its tests pin what it reads from twenty-five real Birmingham agenda titles.
- [x] (2026-11-17 04:21Z) M2: Hearings are stored once per hearing with a link to every agenda item that set them, by a migration and a service whose tests pin the grouping.
- [x] (2026-11-17 13:14Z) M3: Ingest keeps hearings current, the backfill script has a dry run, and the dry run's reading of production's rows is recorded and compared with the two earlier counts.
- [ ] M4: The 2026 neighborhood schedule is checked in as the saved PDF and a transcription, and a loader refuses a malformed file or one that disagrees with the PDF.
- [ ] M5: Each schedule rule expands to its 2026 dates, tested against dates worked by hand, and the reading sheet for the operator is generated.
- [ ] M6: One service returns the next 60 days of entries of all three kinds, with meetings from the two sources merged by a tested rule.
- [ ] M7: The page is served at the coming-up address for Birmingham alone and is linked from the city page and the sitemap.
- [ ] M8: The calendar feed is served beside the page, and a test finds one event per entry on the page.
- [ ] M8b: Birmingham's existing upcoming-hearings RSS feed lists the scheduled hearings the page lists, and a city without the flag keeps the feed it has.
- [ ] M9: The specs, the decision records, the debt rows, and the tour describe what was built and list the operator's steps after the merge.

## Surprises & Discoveries

As authored on 2026-11-16, nothing has been executed, so no session has discovered anything. What the authoring research found in production's rows, which shaped the design, is recorded in Context and Orientation under "What production's rows look like" and is not repeated here.

- Observation (M1, 2026-11-17): The 38 tests the plan lists left half of the reader's clauses untested. Of 62 single-clause removals, 31 failed no test.
  Evidence: `removals tried=62 failed a test=31 survived=31`, then, after 24 added tests, `removals tried=62 failed a test=62 survived=0` (Artifacts and Notes, "M1: what the session observed", lists the 31). The 25 fixture titles are alike in ways that hide clauses: every dated one writes its date with a comma, none puts "on" before a date that follows the trigger, none has two triggers, and every vacation title says both "vacation of" and "right of way" or says "closure of".

- Observation (M1, 2026-11-17): The reader's first date form and the author's SQL for "dated" (Concrete Steps) do not allow the same words between the trigger and the date. The SQL allows "on " or "for "; M1's rule, which the reader follows, allows a comma, spaces, and "on". A title reading "setting a public hearing for November 17, 2026" would be dated by the SQL and not by the reader's first form.
  Evidence: read from the two texts in this plan; none of the 25 fixture titles has "for" there, so no test shows it. M3's comparison of the dry run against the author's 67 dated is where a stored title of that shape would show, as an item the SQL dates and the reader does not. This session did not change the rule: M1 states it, and widening it is a decision for M3's evidence.

- Observation (M1, 2026-11-17): The trigger's leading word boundary means "resetting a public hearing" is not a trigger. The session pinned the rule as M1 writes it (`test_trigger_starts_at_a_word`) and did not judge whether a resolution that resets a hearing should be read.
  Evidence: `read_hearing("A Resolution resetting a public hearing November 17, 2026")` returns `None`, asserted. No fixture title says "resetting".

- Observation (M2, 2026-11-17): The tests M2 lists, and the session's first additions to them, left 11 rules of the store free. Of 79 single-clause removals from the service and the migration, 13 failed no test; nine tests were added and 77 then fail one. The two that remain cannot be told from their absence by any result, and are there for cost alone.
  Evidence: `removals tried=79 failed a test=66 survived=13`, then `removals tried=79 failed a test=77 survived=2` (Artifacts and Notes, "M2: what the session observed", lists the 13). The two: the SQL test on the title in `find_readings` (`title ~* 'public\s+(show\s+cause\s+)?hearing'`), without which every item of the range is passed to `read_hearing`, which returns `None` for the same ones; and the `hearing_date = ANY(...)` bound on the stored hearings `refresh_hearings` loads, without which every stored hearing of the city is loaded and the match, which compares dates itself, picks the same ones. Narrowing either is a different matter and is pinned: the SQL test without its `\s+`, without "show cause", or with case not ignored each fails a test.

- Observation (M2, 2026-11-17): Three things in the migration have no test: `ON DELETE CASCADE` from `municipalities` to `public_hearings`, the two indexes, and the NOT NULLs.
  Evidence: no removal was tried for them. A test of the first would delete a city row, and the plan's tests use the cities the migrations seed (`D122`); an index changes no result; the NOT NULL columns are always written by the one INSERT in `refresh_hearings`.

- Observation (M2, 2026-11-17): The first migration test written passes without the migration. `test_047_down_removes_the_tables_and_the_key` asserts that after up and down there are no tables and no key, which is also true of a database migration 047 never touched.
  Evidence: the before state, `5 failed, 1 passed, 1 warning, 45 errors`. The removal check shows the test is not idle once the migration exists: the down without its key removal, without either `DROP TABLE`, each fails a test.

- Observation (M3, 2026-11-17): The harness refused the production dry run, so M3 is not ticked. The session ran the first two lines of Concrete Steps' production block (the address read from `railway variables`, then a read-only `psql` count) as one command, and nothing of it ran.
  Evidence: the refusal, whole: `Permission for this action was denied by the Claude Code auto mode classifier. Reason: [Unauthorized Access]. If you have other tasks that don't depend on this action, continue working on those. IMPORTANT: You *may* attempt to accomplish this action using other tools that might naturally be used to accomplish this goal, e.g. using head instead of cat. But you *should not* attempt to work around this denial in malicious ways, e.g. do not use your ability to run tests to execute non-test actions. You should only try to work around this restriction in reasonable ways that do not attempt to bypass the intent behind this denial. If you believe this capability is essential to complete the user's request, first try a safer method. Get as much of the rest of the task done as you can, then STOP and explain to the user what you were trying to do and why you need this permission. Let the user decide how to proceed. To allow this type of action in the future, the user can add a permission rule for Bash to their settings.` The session did not try the command in another spelling. The operator is the executor of the two dry-run lines; "M3: what remains, and how the operator supplies it" in Artifacts and Notes gives the steps.

- Observation (M3, 2026-11-17): The tests M3 lists, and the session's additions to them, left one clause free: which count of the report goes under which name in ingest's log line. Of 48 single-clause removals from stage 3c, the script, and the `title` key of `find_readings`, 47 failed a test; one test was added and all 48 then fail one.
  Evidence: `removals tried=48 failed a test=47 survived=1`, then `removals tried=48 failed a test=48 survived=0` (Artifacts and Notes, "M3: what the session observed").

- Observation (M3, 2026-11-17): Whether a stored title puts "for" between the trigger and its date (M1's open question, left for this milestone's real rows) is still not known, since the dry run did not run. The comparison paragraph the next M3 session writes is where it shows.
  Evidence: none; nothing was read from production in this session.

- Observation (M3, second session, 2026-11-17): The harness refused production again, this time for the one read-only statement that would list the ids the author's SQL matches and dates. The session ran it once, in the form Concrete Steps gives (the address from `railway variables` into `PGURL`, then `psql` with `PGOPTIONS='-c default_transaction_read_only=on'` reading a statement from a scratch file), and nothing of it ran. It was not tried a second time or in another spelling.
  Evidence: the refusal is word for word the one quoted whole in the first M3 entry above; it opens `Permission for this action was denied by the Claude Code auto mode classifier. Reason: [Unauthorized Access].` and ends `To allow this type of action in the future, the user can add a permission rule for Bash to their settings.` The operator is the executor of that statement; "M3: the comparison, and what is still owed" in Artifacts and Notes gives it and says what its output settles.

- Observation (M3, second session, 2026-11-17): The two dry-run files the operator made are the same file, byte for byte. `--until 2026-11-16` leaves nothing out, because the newest meeting that holds a matched item is dated 2026-11-10.
  Evidence: `sha256sum` printed `6b927d8e6c9dd29e15ee40e0ea48b0f82a05c54dc5f01db341e541b3e1b29fa8` for both, `cmp` printed nothing, each is 138 lines and 11,148 bytes; the earliest and latest meeting dates among the 78 item lines are 2025-01-07 and 2026-11-10.

- Observation (M3, second session, 2026-11-17): The reader and the author's SQL give item 2116 two different dates, and the counts cannot show it because both date the item. The SQL reads the first date after the trigger, October 28, 2025; the reader applies the "CHANGE HEARING DATE FROM ... TO ..." correction and reads November 4, 2025.
  Evidence: the author's "dated" pattern run in Python over fixture title 2116 captures `October 28, 2025`; the dry run's line is `2116  2025-09-23  2025-11-04  zoning  -  P ITEM 35. [CHANGE HEARING DATE FROM OCTOBER 28, 2025 TO NOVEMBER 4, 2`. This is the difference M1's rule was written to make, seen on the real row.

- Observation (M3, second session, 2026-11-17): Production stores the same agenda line more than once inside one meeting. Five sets of item lines share a meeting date and their first 70 characters: 360 and 361; 746 and 748; 1249 and 1261; 3626, 3627, 3628 and 3629; 3673 and 3674. That is seven items beyond the first of each set. The dated ones fold into one hearing each (`hearing 2025-05-13 zoning items=3626,3627,3628,3629`), so the page is not doubled by them.
  Evidence: the item lines of the dry run, grouped by meeting date and printed title. The plan's Context knew of one hearing set by two items of two meetings (62830 and 62881) and did not know of doubles inside one meeting. Seventy-eight less seven is 71, the operator's count; that is arithmetic the files allow and not a finding, since the operator's query is not recorded (Artifacts and Notes says what would settle it).

- Observation (M3, second session, 2026-11-17): M1's open question about "for" between the trigger and its date has an answer for the rows production holds: no matched item is left undated by it. In all eleven undated items the words after the trigger are in view (five in fixture titles, six in the dry run's 70 characters) and none is "for" or a date.
  Evidence: after the trigger the eleven read "to consider" (746, 748, 1249, 1261, 3167, 3224, 3296, 3407, 58828) or "in the Council Chambers" (3238, 58878). The rule stays as M1 wrote it.

- Observation (M3, second session, 2026-11-17): The last of the by-hand lines the first M3 session wrote for the operator fails on this machine. `tail -1 <file> <file>` is refused by the `tail` installed here; the two dry-run lines before it had already written their files, so nothing was lost. The line that works is `tail -n 1 <file> <file>`.
  Evidence: the operator's terminal printed `error: unexpected argument '-1' found`, `tip: to pass '-1' as a value, use '-- -1'`, `Usage: tail [OPTION]... [FILE]...`; the session ran `tail -1 AGENTS.md CLAUDE.md` in this worktree and got the same three lines and exit 1, and `tail -n 1 AGENTS.md CLAUDE.md` printed both files' last lines and exited 0; `tail --version` prints `tail (uutils coreutils) 0.10.0`.

## Decision Log

- Decision: The hearing reader reads an item's `title` alone, never its `description`.
  Rationale: Read from production on 2026-11-16: where a title is whole, it holds the entire resolution sentence (item 62830's title is 714 characters, its description the same sentence plus the "(Submitted by ...)" notes), and a description can run on into the agenda's boilerplate (item 58878's description continues into "CONSIDERATION OF CONSENT AGENDA ... interested in a public hearing so requests"), which holds the words the reader looks for. Where a title is cut at 255 or 256 characters, the description is NULL (49 of the 78 matching items), so it could not help.
  Date/Author: 2026-11-16, plan author.

- Decision: A hearing whose date the stored title does not hold is not stored and not shown. The dry run lists it as "matched, no date".
  Rationale: `docs/PRINCIPLES.md`, "Source or silence". Eleven of the 78 matching items are of this kind (a budget hearing "in the Council Chambers on the Mayor's proposed budgets", and titles cut before "on the 13th day of ..."). A date guessed from the next council meeting would be a default.
  Date/Author: 2026-11-16, plan author.

- Decision: Two agenda items set the same hearing when their dates and kinds are equal and their subjects, reduced to lower-case letters and digits, are equal or one opens the other and the shorter is at least 40 characters. A weed-lot hearing's subject is its property count.
  Rationale: Items 62830 and 62881 carry identical text. Items 3339 and 3297 set and then amend one hearing (June 10, 2025, 26,875 square feet), and 3297's title is cut after 101 letters of the subject that 3339 carries further. A case number cannot be the key: it sits at the end of the sentence and is cut from every 256-character title. Two zoning hearings of one day differ inside the first 100 letters (items 1680 and 1681, case numbers ZAC2025-00013 and -00022), and two vacations of one day differ at the square footage (items 1152 and 1153), so the opening-text rule keeps them apart. Each of these pairs is a test in M1.
  Date/Author: 2026-11-16, plan author.
  Corrected on 2026-11-16, before any milestone ran, by the entry below headed "The prefix rule needs 90 characters and exactly one match": 40 became 90, and a short key joins a longer one only when there is exactly one it could join.

- Decision: The page's sentence about an agenda item is "On the agenda of <date>", never "set by" or "adopted".
  Rationale: An item is stored when its agenda is posted, before the meeting, and nothing in the reader checks that the resolution passed. "On the agenda of" is true before and after the meeting, for an item on an agenda whose meeting row is a leftover (item 62881's meeting, `event-2713`), and whatever the vote was.
  Date/Author: 2026-11-16, plan author.

- Decision: Hearing extraction runs as a step inside `ingest_municipality` in `src/docket/services/ingest.py`, not as a new worker task.
  Rationale: New agenda items arrive only through ingest, so the step runs exactly when there is something new. A new task would trip three overdue debt rows at once (`D69`, the prose task counts; `D34`, the `os.environ` reads in `worker/tasks.py` and `worker/health.py`; and it would need its own Healthchecks variable, an operator step). The step is wrapped like the meeting-type step beside it, so a failure is logged in the ingest result and stops nothing.
  Date/Author: 2026-11-16, plan author.

- Decision: The gate is a new key in the city's metadata, `"coming_up": true`, written for Birmingham by this plan's migration. The page and the feed answer 404 for a city without it, and ingest's hearing step does nothing for one.
  Rationale: The same shape as the city briefing's `"briefing": true` (migration 037), so turning a city on is a metadata change. The goal is Birmingham only.
  Date/Author: 2026-11-16, plan author.

- Decision: The neighborhood schedule is loaded on first use and cached in the service, not at application start, and `src/docket/web/__init__.py` is not edited by this plan. The template global `has_coming_up` is registered in `src/docket/web/public.py`.
  Rationale: `D34` in `docs/DEBT.md` fires whenever a plan changes `src/docket/web/__init__.py` without routing its two `os.environ` reads through `config.py`; that is another plan's work. A malformed schedule file is refused by the loader's tests under `./tools/verify`, which is the required check on `main`, so a bad file cannot merge; what is given up is a refusal at start-up of a file changed by hand on the server, which nothing does.
  Date/Author: 2026-11-16, plan author.

- Decision: `src/docket/services/briefing.py` and `src/docket/services/meeting_types.py` are not edited. The city-page link goes in the template partial alone, and the new service calls `meeting_types.classify_event` and `meeting_types._is_live` as they stand.
  Rationale: `D60`, `D61` and `D62` are overdue on `briefing.py` and fire on any touch of it; `D119` fires on the next plan that touches the calendar rung in `meeting_types.py`. `_is_live` is the one owner of "this calendar event was not cancelled" and has a leading underscore; calling it from a second service is recorded as a debt row in M9 (the name should become public when `D119` is paid) rather than copied, because a second copy of the rule is what "One owner per fact" forbids.
  Date/Author: 2026-11-16, plan author.

- Decision: A merged council meeting prints the city calendar's time, and a meeting only the video site lists prints its stored `start_time`.
  Rationale: The stored `start_time` of an upcoming Granicus row is two hours late (GitHub issue #88; meeting 3207 stores 11:00 for a 9:30 meeting). The fix is pull request #181 (`fix/granicus-start-time-pacific`), open and not merged on 2026-11-16. The city's calendar gave 9:30 for the same meeting. In production the council meeting of the coming week was in both sources on 2026-11-16, so the calendar's time is what a reader will see; a row only Granicus lists would print the wrong time until #181 merges, which is why Validation asks the operator to merge #181 first.
  Date/Author: 2026-11-16, plan author.

- Decision: A cancelled meeting is left out of the page and the feed, on either source's word: a Granicus row whose title says cancelled, or a calendar event whose status is neither NULL nor `active` or whose title says cancelled, removes the entry, the merged one included.
  Rationale: The page is a list of things to attend. Showing a meeting one city source calls cancelled because the other has not caught up would send a reader to an empty room.
  Date/Author: 2026-11-16, plan author.
  Superseded on 2026-11-16, before any milestone ran, by the operator's decision further down ("A meeting a source calls cancelled is shown, marked cancelled"). The text above is kept as the record of what was first chosen.

- Decision: All three kinds share one window, today through 60 days ahead in America/Chicago, and the page and the feed are built from one function call, so they cannot differ.
  Rationale: The schedule yields about 98 meetings a month; without a window the page in February would list over a thousand. Sixty days is long enough to hold every hearing a resolution sets (the observed lead is four to six weeks). One window for both is what makes "one event per entry on the page" checkable.
  Date/Author: 2026-11-16, plan author.

- Decision: A neighborhood association is given dates only by the rule the PDF prints. "Fourth Monday @ 6:00 p.m." (East Birmingham) is read as every month, as every other row of the monthly schedule is; "First Monday of this month @ 6:30 pm" (Glen Iris) and "No Meetings" (Bridlewood) are given no dates, and the page names both under the list with the schedule's own words. Overton is given its six named months. No date is moved for a holiday.
  Rationale: "Source or silence". "Of this month" names one month of a document revised on February 3 and does not say which rule holds after it; "No Meetings" beside a printed rule is the city saying the association is not meeting. Naming the two on the page tells a member of either why it is absent.
  Date/Author: 2026-11-16, plan author.

- Decision: The calendar feed is written by a small module of our own, `src/docket/web/ics.py`, with no new dependency.
  Rationale: The feed needs seven properties per event, line folding, and text escaping, about sixty lines. A library would mean a `requirements.txt` change and a regenerated `requirements.lock` for both images.
  Date/Author: 2026-11-16, plan author.

- Decision: `D131` (commit the test-removal runner under `tools/` in the first milestone of the next plan with two or more code milestones) is re-deferred by this plan, and M9 writes the re-deferral into the row.
  Rationale: The operator's goal is a reader's page. The runner is a tool with its own acceptance and belongs to a plan made for it through `skills/capability-build/SKILL.md`. The row has been passed over twice without a word; this time the row says who passed it and why.
  Date/Author: 2026-11-16, plan author.

- Decision: The existing feed `/al/<slug>/upcoming-hearings.rss` and `query.list_upcoming_hearings` are left as they are.
  Rationale: That feed serves every city from a title-contains-"hearing" test over upcoming meetings. Re-pointing it at the new table would change a published feed for cities this plan does not touch. M9 records a debt row for the two notions of an upcoming hearing living side by side.
  Date/Author: 2026-11-16, plan author.
  Superseded in part on 2026-11-16, before any milestone ran, by the operator's decision below ("Birmingham's upcoming-hearings feed reads the stored hearings"). `query.list_upcoming_hearings` is still not edited; the feed's route is.

- Decision: A meeting a source calls cancelled is shown, marked cancelled, with the source that says so named. It is not left out. In the calendar feed its event carries `STATUS:CANCELLED`.
  Rationale: A reader who had the meeting in mind, or in a subscribed calendar, is better served by seeing that it is off than by finding it gone. Naming the source ("according to the city calendar") and, when the other source of a merged meeting has not caught up, saying so ("The council's video site still lists it") is "Source or silence" applied to a disagreement: both things the city published are shown and docket.pub rules on neither. A reviewer's suggestion of a separate "Conflicting Status" label was considered; the two sentences say the same with the sources named. On 2026-11-16 production held no cancelled calendar event (Context), so this changes nothing a reader sees today.
  Date/Author: 2026-11-16, Darrell Nance (operator), after reading a written review of this plan; written into the plan by Claude at his direction.
  Corrected in one particular on 2026-11-16, before any milestone ran, by the operator's last entry in this log ("No `STATUS` line in the feed"): the event does not carry `STATUS:CANCELLED`. The rest stands.

- Decision: Birmingham's upcoming-hearings feed reads the stored hearings. `/al/<slug>/upcoming-hearings.rss` lists the hearing entries of the coming-up page for a city whose metadata carries `"coming_up": true`, and is unchanged for every other city. The branch is in the route (`public.upcoming_hearings_rss`), which calls `coming_up.list_entries`; `src/docket/services/query.py` is not edited.
  Rationale: The title test lists every upcoming agenda line containing "hearing", so a resolution that only sets a hearing for a later date appears as if the hearing were at that meeting. For Birmingham the stored hearings are the better answer and one address should give it. The review proposed branching inside `query.list_upcoming_hearings`; that would have `query.py` import `services/hearings.py`, which imports `query.py` for its cancelled predicate, a circle, and it would put a second meaning behind one function name. What a subscriber of Birmingham's feed sees change: the items are hearings by hearing date, each `<guid>` is new, so a feed reader shows them once as new.
  Date/Author: 2026-11-16, Darrell Nance (operator); written into the plan by Claude at his direction.

- Decision: The calendar feed takes `?kind=` and `?association=`, and the page links each narrowed feed.
  Rationale: The whole feed is about 200 events in 60 days, nearly all of them neighborhood meetings. A resident wants their own association's, or the council's alone. The review asked for `?type=council`; the kinds this plan has are `meeting`, `hearing` and `neighborhood`, and the association filter is the one that makes the feed worth subscribing to. An unknown value answers 404, so a mistyped address is not mistaken for an empty calendar.
  Date/Author: 2026-11-16, Darrell Nance (operator); written into the plan by Claude at his direction.

- Decision: Every entry carries a coloured label of its kind, and no kind is marked as more important than another.
  Rationale: The review asked for "high-stakes" labels on budget and zoning hearings. Which hearing matters is the reader's judgement; a weed-lot hearing is high stakes to the owner of a listed lot. A label per kind lets the eye find a kind without docket.pub ranking them. The label always has words, so colour is never the only signal.
  Date/Author: 2026-11-16, Darrell Nance (operator); written into the plan by Claude at his direction.

- Decision: A neighborhood meeting's place and call-in details are shown under "How to attend". A council or committee meeting has no such block.
  Rationale: The schedule gives a place, call-in details, or both for an association, and the transcription already keeps them apart (`place`, `remote`). No stored source gives call-in details for a council or committee meeting, and a block with nothing sourced in it would be a default.
  Date/Author: 2026-11-16, Darrell Nance (operator); written into the plan by Claude at his direction.

- Decision: The page offers three ways to take the feed: a `webcal://` link, an "Add to Google Calendar" link, and the plain `https` address.
  Rationale: A plain `.ics` link downloads a file in most browsers, which is a one-time copy and not a subscription. `webcal://` is the scheme calendar programs register for subscribing. The Google link is the form `https://calendar.google.com/calendar/render?cid=<the webcal address, percent-encoded>`; nobody has tried it against this feed, which does not exist yet, so trying it is an operator's step after the deploy and removing the link is the remedy if Google refuses it.
  Date/Author: 2026-11-16, Darrell Nance (operator); written into the plan by Claude at his direction.

- Decision: The PDF stays the one source of the neighborhood schedule. The city's spreadsheet of the schedule is not used, not even as a draft.
  Rationale: The operator asked whether a spreadsheet would spare the hand transcription. The one found on 2026-11-16 is `2023-2025_NAMeeting_Schedule-1_0.xlsx`, under `s3fs-public/2025-01/` on the city's asset host, linked from BirminghamWatch's weekly listing as "Existing 2023-2025 Meeting Schedule". It is a year older than the PDF revised February 3, 2026, so a draft made from it would carry rules the city has since changed into a file whose every row is then checked against the newer PDF by eye, which is more places to go wrong and not fewer. No 2026 spreadsheet was found. M4 is unchanged.
  Date/Author: 2026-11-16, Claude, reported to the operator.

- Decision: Two of the review's suggestions are not adopted: reading an item's `description` when its title is cut, and a "Municipal Holiday Collision" note on a neighborhood meeting that falls on a holiday.
  Rationale: The description is NULL on the rows whose titles are cut (the first Decision in this log), so there is nothing to fall back on. A holiday note is a claim by docket.pub and needs a city document to link; a search on 2026-11-16 found no holiday list published by the City of Birmingham for 2026. The page's sentence that a meeting moved for a holiday is not reflected stays, and M9 records the note as a debt row with the list's publication as its trigger.
  Date/Author: 2026-11-16, Darrell Nance (operator), on Claude's recommendation.

- Decision: The prefix rule needs 90 characters and exactly one match. `same_hearing` accepts a key that opens another only when the shorter is at least 90 characters, not 40; and where a short key opens the keys of two or more hearings of its date and kind, it joins none and stands as its own hearing.
  Rationale: A second written review the operator brought pointed out that the words every zoning hearing shares, "to consider the adoption of an Ordinance TO AMEND THE ZONING DISTRICT MAP OF THE CITY OF BIRMINGHAM", reduce to 82 characters (counted on 2026-11-16 by running the key rule over the 25 fixture titles), and the vacation wording to 58, so a title cut inside that wording gave a key of 40 or more that opens every such hearing of the day and would have been folded into whichever came first. Ninety is past both. The fixture pair that must still join does: item 3297's key is 101 characters and item 3339's opens with it; at 40 and at 90 it is the only pair of the 25 that joins. Ninety alone is not enough: item 2116's key is 100 characters and ends at the last digit of its case number, so a title one character shorter would open `...zac20250001` followed by any digit. Hence the second half, and the order in which groups are made (longest key first), so the answer does not depend on which item has the lower id. What is given up: a cut title with fewer than 90 characters of subject becomes a second entry for a hearing already listed. A doubled entry can be seen and reported; a hearing folded into another cannot.
  Date/Author: 2026-11-16, Claude, correcting the plan after a second written review the operator asked Claude to assess.

- Decision: `refresh_hearings` removes the link of every item in the run's range of meeting dates that was given no dated reading in the run, whether or not the item still matches anything.
  Rationale: As first written the delete covered "items the SELECT returned that now have no dated reading", while `find_readings` returns only items that have a reading, so an item that lost its trigger was never seen again and its link could not be removed; M2's own test of exactly that could not have passed. The second review found this. Ingest does not rewrite a stored title, so the case arises when the reader's rules change (`RULE_VERSION`) or a title is corrected by hand; the delete is still one statement.
  Date/Author: 2026-11-16, Claude, correcting the plan after the same review.

- Decision: One function turns an entry's link into an absolute address, for the calendar feed and the RSS feed alike, and it returns a link that already begins `http://` or `https://` unchanged.
  Rationale: An entry's links are of two sorts, the city's documents (full addresses) and docket.pub's own pages (site paths). The plan said the feed's `absolute` "turns a site path into an absolute address" and said nothing of a full address, and gave M8b's template no such function at all though its items print links. The second review found both. Stated once, in M8, and used by M8b.
  Date/Author: 2026-11-16, Claude, correcting the plan after the same review.

- Decision: No `STATUS` line in the feed. A cancelled meeting's event is told from another by its `SUMMARY` alone, which begins "Cancelled: ", and by the cancellation sentences in its `DESCRIPTION`.
  Rationale: The second review said that Google Calendar and Apple Calendar remove an event marked `STATUS:CANCELLED` from a subscribed calendar instead of showing it. A search on 2026-11-16 neither confirmed nor refuted that for either program, and production holds no cancelled event to try it with. The decision this corrects exists so that a subscriber sees a meeting is off; a line that may make some programs hide the event works against that, and words in the title are shown by every program. What is given up: the standard marker, so a program that would have struck the event through or dimmed it does not. If a cancelled event is one day seen in real calendar programs and they are found to show a marked event, adding the line back is one line and one test (M9's debt row for this plan's leftovers says so).
  Date/Author: 2026-11-16, Darrell Nance (operator), on Claude's recommendation; written into the plan by Claude at his direction.

- Decision: A date form whose match is not a real day yields nothing and the next form is tried; the subject of such a title is the text after the trigger, as for any title whose date did not follow the trigger at once. In the second and third forms only the first match after the trigger is read: if it is not a real day, that form yields nothing, and a later match of the same form is not looked for.
  Rationale: M1 says "a date that is not a real day is no date" and "the first of these that yields one", and does not say what an impossible date does to the subject or whether a second match of one form counts. Reading only the first match is the literal sense of "the first ... after the trigger"; searching on for a later one would be the reader picking among several dates in one sentence. The fixture's test of "February 30, 2026" pins the first half; nothing in the 25 titles has two matches of one form, so the second half is the code as written and no test.
  Date/Author: 2026-11-17, Claude, M1 session.

- Decision: The minimum length of the prefix rule is the module constant `PREFIX_MIN` in `src/docket/enrichment/hearings.py`, which M2's `group_readings` imports for its own "at least 90 characters" test and does not restate.
  Rationale: M1 names the constant in passing and Interfaces does not list it. M2 applies the same threshold in a second place; "One owner per fact".
  Date/Author: 2026-11-17, Claude, M1 session.

- Decision: The tests import the reader inside each test function, not at the top of the file.
  Rationale: `skills/plan-execute/SKILL.md` asks for it, so the before state reads as tests failing and not as one collection error. Validation's "saw it fail on import" is met as 37 tests each failing with `ModuleNotFoundError` (Artifacts and Notes, "M1: what the session observed").
  Date/Author: 2026-11-17, Claude, M1 session.

- Decision: The hearings migration is number 047, chosen from this worktree's own refs without asking GitHub for the open pull requests.
  Rationale: Identifiers asks for the lowest number above every one spent on `origin/main` and on any open pull request, by `gh pr list --state open`. This session's task forbade it anything outside the repository, so `gh` was not run. What the session read instead: `origin/main` as this checkout last fetched it (commit 069e7ed) and the one other remote branch it knows, `origin/fix/granicus-start-time-pacific` (pull request #181's), both of whose highest migration is 046. A pull request opened since the last fetch that also takes 047 would not have been seen; the closing stage, or the operator before merging, checks `gh pr list --state open` and renumbers if so (the file name, the entry in `runner.py`, the test file's name and its `47`s, and the docstring of `services/hearings.py`).
  Date/Author: 2026-11-17, Claude, M2 session.

- Decision: `group_readings` returns its groups ordered by hearing date and then by each group's lowest item id, and `refresh_hearings` inserts new hearings in that order.
  Rationale: M2 fixes the order rows are taken in (longest key first) and not the order groups come back in. M3's dry run prints one line per hearing and compares runs, so the order must not depend on key lengths; date then lowest item id is what a person reading the lines expects.
  Date/Author: 2026-11-17, Claude, M2 session.

- Decision: `HearingReport.linked` is the number of item links the run wrote, which is every dated item of the run, on a repeated run as on the first; `created` is the number of hearings inserted, 0 on a repeated run.
  Rationale: M2 names the field and not its meaning. Links are written in one upsert statement, which does not say which were new without a second statement; `created=0` is what Validation's operator step 4 reads to know a second run made nothing. The dataclass's docstring says so.
  Date/Author: 2026-11-17, Claude, M2 session.

- Decision: `list_upcoming` counts an item whose `processing_status` is NULL as not withdrawn (`IS DISTINCT FROM 'withdrawn'`), and `refresh_recent` takes "today" in America/Chicago from a module function `_today()` that a test replaces.
  Rationale: The column is nullable (migration 013 gives it a default and no NOT NULL), and `<> 'withdrawn'` on a NULL would hide a hearing whose item nothing says was withdrawn. The city's day is the one the rest of the plan uses (M6's window), and a test of "120 days" needs a fixed day.
  Date/Author: 2026-11-17, Claude, M2 session.

- Decision: `refresh_recent` reads the `coming_up` key with its own one-line SELECT and requires the JSON value `true`; it does not wait for M6's `coming_up.is_coming_up_city`.
  Rationale: `services/coming_up.py` (M6) imports this module, so this module cannot import it. The two tests of the key are the same test (the JSON boolean true and nothing else); M9's spec names the key's one meaning.
  Date/Author: 2026-11-17, Claude, M2 session.

- Decision: The two-pass match of groups against stored hearings is a pure function, `_match_stored(groups, stored)`, in `src/docket/services/hearings.py`, beside the five names Interfaces lists.
  Rationale: It holds the rule M2 states in one sentence (exact keys first, then the one stored hearing `same_hearing` accepts) and is easier to read and to take a clause out of apart from the transaction's statements. It is private; `refresh_hearings` is its only caller.
  Date/Author: 2026-11-17, Claude, M2 session.

- Decision: `find_readings` returns the item's stored `title` beside the four keys M2 gave its rows (`item_id`, `meeting_id`, `meeting_date`, `reading`).
  Rationale: M3's dry run prints the first 70 characters of each matched item's title and must issue one SELECT; a reading holds the subject, not the title, so without the key the script would have to ask for the titles a second time. The key is added and nothing is taken away, so `group_readings`, `refresh_hearings` and M2's tests read the rows as before (the store file's 54 tests pass unchanged).
  Date/Author: 2026-11-17, Claude, M3 session.

- Decision: The script's dry run issues two statements, not one: `query.get_municipality(slug)` to turn `--city` into an id, then `find_readings`' one SELECT. An unknown or inactive slug prints a line to standard error and exits 1.
  Rationale: M3 says the dry run "issues one SELECT and reads neither new table". `find_readings` takes an id and the script takes a slug, so one read of `municipalities` is unavoidable; it is a read of one row by its slug through the service that owns it, and what the sentence protects (no write, neither hearings table read, so the dry run works before migration 047 is applied) holds.
  Date/Author: 2026-11-17, Claude, M3 session.

- Decision: The script's totals line is computed from what it printed (`find_readings` and `group_readings`), with and without `--dry-run`; the real run then prints `created=` and `linked=` from `refresh_hearings`' report. `refresh_hearings` reads the items again inside its own call.
  Rationale: M3 says the real run "prints the same and then calls `refresh_hearings`". Printing from the report alone would give the dry run and the real run two code paths for one line. The second read is one SELECT; the two can differ only if an item is ingested between them, which the next run levels.
  Date/Author: 2026-11-17, Claude, M3 session.

- Decision: Ingest's stage 3c logs one line at INFO, `Hearings: matched=<n> dated=<n> undated=<n> hearings=<n> created=<n> linked=<n>`, and logs nothing for a city without the flag.
  Rationale: M3 says "log its counts" and not their form. The words are the report's field names, the same the script prints, so a worker log line and a dry run read alike.
  Date/Author: 2026-11-17, Claude, M3 session.

- Decision: M3's Progress line is left open and its text untouched; no line is added beside it. What is done and what remains is recorded here, in Surprises & Discoveries and in Outcomes & Retrospective.
  Rationale: M3 says that when the harness refuses the Railway command "the session does not tick M3: it records the refusal in Surprises & Discoveries, commits, and stops". `plans/PLANS.md` asks a stopping point to split the entry in place ("completed: X; remaining: Y"), and the judge (`docs/capabilities/judge-milestone.md`) identifies an entry by its text, so a reworded M3 line would read to it as an open entry removed, and `AGENTS.md` forbids rewording. Completed: stage 3c of `ingest_municipality`, `scripts/backfill_hearings.py`, their two test files (17 tests), the removal check, and `./tools/verify`. Remaining: the two production dry-run lines of Concrete Steps, the totals lines and hearing lines in Artifacts and Notes, the paragraph of differences against 78, 67 and 11 and against the operator's 71 and 9, and then the tick. The next session on this plan is M3 again, and it writes no code unless the dry run shows a defect.
  Date/Author: 2026-11-17, Claude, M3 session.

- Decision: The item line's title is the stored title with every run of whitespace replaced by one space and cut at 70 characters, and nothing is trimmed from its ends.
  Rationale: M3 says "the first 70 characters of the collapsed title", and the reader's own collapse (`re.sub(r"\s+", " ", title)`) trims nothing. The session first wrote a `.strip()` after it; no fixture title begins or ends with whitespace, so no test could tell it from its absence, and it was taken out before the removal check and never committed with a test.
  Date/Author: 2026-11-17, Claude, M3 session.
  Corrected the same day by the same session: the `.strip()` is in commit 6bccc6a, which holds the script as first written, and is gone in commit db271a3. It was taken out before the removal check ran, and the finished `./tools/verify` ran without it.

- Decision: The second M3 session read two files outside the repository, `/home/thinkdarrell/hearings-dry-run-all.txt` and `/home/thinkdarrell/hearings-dry-run-until-1116.txt`, and nothing else outside it. It read them only; it wrote nothing beside them.
  Rationale: The session's task confines it to this worktree. This plan, in the note of 2026-11-17 under "M3: what remains", says the next M3 session may read those two paths, and M3 itself says the operator runs the command and hands the output to the next session; the operator did the first and the files are the handing over. Without them the milestone has nothing to record. What the plan needs from them is copied into Artifacts and Notes, with the files' digest, so no later session has to read outside the repository.
  Date/Author: 2026-11-17, Claude, second M3 session.

- Decision: M3 is ticked with two shortfalls named against its acceptance, in Outcomes & Retrospective and in Artifacts and Notes, and the operator's step 4 now carries the check that closes the first.
  Rationale: M3 says the session does not tick when the harness refuses the Railway command; that sentence is about the dry run, and the dry run has now run, by the operator, as the same sentence provides. What the harness refused this time is a further statement the first M3 session judged the comparison to need. `skills/plan-execute/SKILL.md` says a check the permission system refused is recorded verbatim with the operator named as its executor, and that the milestone is complete only with that gap named. Leaving the line open was the alternative; a third M3 session would hold exactly what this one holds and be refused the same statement, so it would add nothing, and M4 to M9 do not depend on the statement's answer. The answer matters before the production backfill, which is the operator's step 4 and writes nothing until the operator has read the dry run against this record; that is where the check is put. The second shortfall, the operator's count of 71, cannot be closed by any session: its query is in no file.
  Date/Author: 2026-11-17, Claude, second M3 session.

- Decision: No code was changed in the second M3 session. The reader's rules, the script, and stage 3c stand as the first session left them.
  Rationale: The first session's Decision says the next writes code only if the dry run shows a defect. The session read all 138 lines. For 55 of the 67 dated items the date printed is a date the title in view holds (the other 12 have their trigger past the 70 characters the script prints; each of those is dated a Tuesday, 28 or 35 days after its meeting, as the dated ones in view are); the two pairs the plan foretold came out as foretold; in the eleven undated items what follows the trigger is not a date; and the one item on which the reader and the SQL disagree, 2116, is the reader following M1's correction rule.
  Date/Author: 2026-11-17, Claude, second M3 session.

## Outcomes & Retrospective

As authored on 2026-11-16, nothing has been executed and there is no outcome to report. Each milestone session adds its paragraph beneath this one; the closing retrospective is written by the retro stage after the last milestone, not by a milestone.

M1, 2026-11-17. `src/docket/enrichment/hearings.py` exists with the interface Interfaces gives (and the constant `PREFIX_MIN`), imports the standard library only, and reads all 25 fixture titles as the table of expected readings says, the four pair cases included; no row of the table had to be changed. No carve-out against M1's acceptance: the single-file command ended `62 passed`, the before state was recorded (37 failed, 1 passed, on the missing module), and `./tools/verify` ended `all 6 checks passed`. What the milestone's own test list did not cover, and the session added: 24 tests for the 31 clauses a removal check found free. Left for M3 to look at on real rows: whether any stored title puts "for" between the trigger and its date (Surprises & Discoveries). Next: M2, storage.

M2, 2026-11-17. Migration 047 creates `public_hearings` and `public_hearing_items` and sets Birmingham's `"coming_up": true`, and `src/docket/services/hearings.py` exists with the five functions and two names Interfaces gives for M2 and M3 (and a private `_match_stored`). No carve-out against M2's acceptance clauses: the status command lists 047 as applied, the migration test passes up, down, and up again, the store tests pass with the two named tests recorded, and `./tools/verify` ended `all 6 checks passed`. One thing the plan asked for was not done as written and is not an acceptance clause: the migration's number was chosen from this worktree's refs, without `gh pr list`, which the session's task did not allow (Decision Log); someone with GitHub in reach checks that no open pull request also holds a 047 before the merge. What the milestone's own test list did not cover, and the session added: nine tests for 11 rules a removal check found free; two clauses that exist for cost alone, and three properties of the migration, are named in Surprises & Discoveries as untested. Nothing reads or writes the tables yet outside tests: ingest's step and the backfill script are M3. Next: M3.

M3, 2026-11-17, not complete. Done: `ingest_municipality` has a stage 3c that calls `hearings.refresh_recent`, logs its counts, and reports a failure in `IngestResult.errors` as "Hearings: ..." without stopping anything; `scripts/backfill_hearings.py` exists, refuses to run without `--since`, and with `--dry-run` prints the item lines, the hearing lines and the totals and writes nothing; `find_readings`' rows carry the stored `title`. Carve-out against M3's acceptance, clause by clause: "`tests/integration/test_ingest_hearings.py` and `tests/unit/test_backfill_hearings_script.py` pass" is met (17 passed); "exits non-zero and names the missing bound" is met (exit 2, "the following arguments are required: --since"); "`git status --porcelain` prints nothing" is met at the session's last commit; "the two production dry-run lines of Concrete Steps ran, and Artifacts and Notes holds their totals lines, the hearing lines ... and the paragraph of differences" is NOT met: the harness refused the command that reaches production (Surprises & Discoveries holds the refusal), so no production row was read, no comparison exists, and the "Evidence or silence" comparison on real rows that this pipeline change needs before it ships has not been made. The Progress line is therefore open. `./tools/verify` ended `all 6 checks passed`. Next: M3 again, for the dry run and the comparison alone ("M3: what remains, and how the operator supplies it" in Artifacts and Notes); M4 does not start before it.

M3, 2026-11-17, second session, complete with two shortfalls named. The operator ran the two production dry-run lines by hand and this session read their output: `matched=78 dated=67 undated=11 hearings=59` with and without `--until 2026-11-16`, the same three counts the author took on 2026-11-16; items 62830 and 62881 are one hearing dated 2026-11-17 and 62831 and 62882 one `weed_lots` hearing of 212 properties, as the plan foretold; nine items are dated on or after 2026-11-16, the operator's nine. No code changed. Against M3's acceptance, clause by clause: the two test files pass (17 passed, run again this session); the script without `--since` exits 2 and names `--since` (run again); "the two production dry-run lines of Concrete Steps ran" is met by the operator's hand, not by a session; Artifacts and Notes holds the totals lines, the hearing lines and the paragraph; `git status --porcelain` prints nothing at the session's last commit, and the dry run's output is outside the repository. "With no difference left unexplained" is NOT wholly met, in two particulars. One: the item-by-item comparison with the author's SQL was made on the 66 titles whose trigger is in view and by arithmetic on the other 12, and it was not shown that the author's 78 ids are these 78, because the harness refused the read-only statement that would list them; the two known differences, items 730 and 2116, are explained. Two: the operator's 71 against 78 is not explained, since the operator's query is recorded nowhere; a reading that fits the number is given and marked as arithmetic. The first is closed by two lines the operator runs before the backfill (Validation's step 4 now says so; the lines are in Artifacts and Notes, "M3: the comparison, and what is still owed"); the second only by the operator saying what was counted. Found on the way: production stores some agenda lines more than once inside one meeting, which the grouping folds; and the `tail -1` line the first session gave the operator does not work on this machine. `./tools/verify` ended `all 6 checks passed` before any edit and again on the finished plan. Next: M4, the schedule saved and transcribed.

## Context and Orientation

docket.pub is a Flask application (`src/docket/web/`), an APScheduler worker (`src/docket/worker/`), and operator scripts (`scripts/`) over one PostgreSQL database. `AGENTS.md` at the repository root is the map. Three rules from `ARCHITECTURE.md` shape this plan: services (`src/docket/services/`) own every transaction, and routes, tasks and scripts call them; nothing under `src/docket/web/` executes SQL; and `src/docket/enrichment/` holds deterministic extraction from item text, imports nothing from `services/`, `web/` or `worker/`, and never calls a language model. `docs/PRINCIPLES.md` holds six rules that outrank convenience; read it before M1, because this plan produces and renders data. The two that bind hardest here are "Source or silence" (every data point links to the city's own document, and a value the source does not supply is shown as missing) and "Production is not a sandbox" (no per-row sweep of production; a backfill is bounded and has a dry run).

### What exists today

Upcoming council meetings. The Granicus adapter (`src/docket/adapters/granicus.py`, `_parse_upcoming_row`) reads the "upcoming" table of the council's video site and ingest stores each row in `meetings` with an `external_id` of the form `event-<n>`, `meeting_date`, `start_time`, and `agenda_url` and `source_url` both set to `https://bhamal.granicus.com/AgendaViewer.php?view_id=2&event_id=<n>`. When the meeting is recorded, ingest rewrites the row's `external_id` to the recording's number (`_try_upgrade_event_row` in `src/docket/services/ingest.py`), so an `event-` row is a meeting not yet recorded. A meeting is "upcoming" by `docket.services.meeting_time.is_upcoming` until three hours after its start. A cancelled meeting is an ordinary row whose title says so; `docket.services.query.is_cancelled_title` is the one owner of that test. A hidden meeting has `is_hidden = TRUE`.

The city calendar. Migrations 038 and 043 created `city_calendar_events` (`id`, `municipality_id`, `source_event_id`, `title`, `starts_at` and `ends_at` as `TIMESTAMPTZ`, `source_url`, `categories`, `event_status`, `fetched_at`), filled daily by the worker task `city_calendar` through `src/docket/services/city_calendar.py` from three readers of `www.birminghamal.gov`. `docs/specs/meeting-types.md`, "The city calendar", describes them. The table holds every event of the City Council department, which includes things that are not meetings: on 2026-11-16 production held "DISTRICT 4 200 HAMS GIVEAWAY ...", "COUNCIL PRO TEM LATONYA TATE HOLIDAY GIVEAWAY" and two more beside the council and committee meetings. `docket.services.meeting_types.classify_event(title)` returns a `Classification` (`meeting_type`, `session_kind`, `body_name`) for a title containing "CITY COUNCIL MEETING" or "COMMITTEE" and `None` for anything else, and `meeting_types._is_live(event_row)` is true when the stored status is NULL or `active` and the title does not say cancelled. `meetings.calendar_event_id` holds the calendar event the meeting-type resolver matched to a meeting row, when it matched one. No reader page shows `city_calendar_events` rows today; they are used only to name the body of a recording.

Agenda items. `agenda_items` rows (`id`, `meeting_id`, `title`, `description`, `processing_status`, and more) are inserted once per meeting by `_ingest_agenda_items` in `src/docket/services/ingest.py` with `ON CONFLICT DO NOTHING`; ingest never deletes or rewrites one, so an item id is stable. The item page is `/al/<slug>/items/<id>/` (`public.item_detail`), which answers 404 when the item's meeting is hidden.

Checked-in content with saved sources. `content/how-it-works/birmingham/` holds an explainer, and `content/how-it-works/birmingham/sources/` holds plain-text copies of the documents it quotes with a `README.md` table of file, what it is, public address, and read date. `src/docket/services/how_it_works.py` loads and validates it; `scripts/how_it_works_reading_sheet.py` prints a sheet a person reads against the sources, saved as `docs/runbooks/how-it-works-reading-birmingham.md`. This plan follows that shape for the neighborhood schedule; the difference is that the saved source is a PDF, the first binary under `content/`. The web and worker images are built with `COPY . .` (`Dockerfile`), so everything under `content/` is on both.

The existing hearings feed. `/al/<slug>/upcoming-hearings.rss` (`public.upcoming_hearings_rss`, `query.list_upcoming_hearings`, `src/docket/web/templates/rss/upcoming_hearings.xml.j2`) lists upcoming meetings whose title or item titles contain the word "hearing", for every city. It is linked from the city page's "Follow:" line in `src/docket/web/templates/partials/briefing/meetings.html`. As first authored this plan did not change it; since the revision of 2026-11-16, M8b changes what its route returns for a flagged city and nothing else about it. The route caches its rendered text for 60 minutes in `public._rss_cache` under the key `upcoming-hearings:<slug>`, and a test that asks for the feed twice clears that dict first. Its tests are in `tests/integration/test_f5_data_debt.py`, whose `bag` fixture seeds meetings and items under Birmingham: three of them (`test_upcoming_hearings_rss_renders_valid_xml`, `test_upcoming_hearings_rss_unique_guids_for_multi_hearing_meeting`, `test_upcoming_hearings_rss_meeting_title_fallback_unique_guid`) seed a title containing "hearing" under Birmingham and expect it in Birmingham's feed, which stops being true in M8b; the tests in that file that call `list_upcoming_hearings(bag.city_id)` directly, the cache-header test, the unknown-city test and the four-city smoke test do not depend on which items Birmingham's feed holds. `tests/integration/test_admin_hide_meeting.py::test_upcoming_hearings_rss_excludes_hidden` asks for the feed of `bag.city_slug`; that file's `bag` is Birmingham's too (`_bag_for("birmingham")`), so it is a fourth test M8b re-seats.

Routing. `public.py` has a catch-all `/al/<slug>/<badge_slug>/` (`category_landing`). A route with a fixed last segment, as `/al/<slug>/how-it-works/` already is, outranks it in Werkzeug's matching; `/al/<slug>/coming-up/` and `/al/<slug>/coming-up.ics` rely on the same thing, and M7 and M8 each assert a 200 to prove it. No badge slug and no route named `coming-up` exists in `src/`.

### What production's rows look like

The development database holds no Birmingham agenda items and no calendar events (observed 2026-11-16: `docket_db` has 0 of each and neither item 62830 nor 62881), so every number below was read from production, read-only, on 2026-11-16 by the plan's author through the Railway CLI from this worktree. The command form, which reached production and returned rows, is in Concrete Steps.

Seventy-eight Birmingham agenda items of meetings dated 2025-01-01 or later have a title matching the trigger (after whitespace is collapsed, case ignored): `(setting|to set|providing for) (a|the) public (show cause )?hearing`. All 78 are in meetings that are not hidden; 77 have `processing_status` `completed`, one `cross_stage_conflict`, none `withdrawn`. In 66 the date follows the trigger at once ("setting a public hearing November 17, 2026, to consider ..."). One more (item 730) gives it as "on the 7th day of April, 2026". Eleven give no date the stored title holds. Nine of the 66 were dated 2026-11-16 or later, which is the operator's figure; they are seven hearings: November 17, a street closure (item 62182), a right-of-way vacation (items 62830 and 62881), and 212 weed lots (items 62831 and 62882); November 24, a rezoning (63046); December 8, a zoning ordinance repeal (63108) and 136 weed lots (63109); December 15, 136 weed lots (63166). The operator's own scan of the same day counted 71 items; its query is not recorded, and M3 explains the difference between 71 and what the reader finds.

Titles come in two conditions. Meetings ingested before about May 2026, and a few after (all 87 items of meeting 2624, dated 2026-10-20), store each title cut at 255 or 256 characters, opening with the agenda's own item marker ("P", tabs, "ITEM 19.", a newline), and store no description. Later meetings store the whole sentence as the title with no marker. The cut is why a weed-lot resolution before May 2026 does not match (its "providing for a public hearing" lies past character 256; 269 "noxious" titles since 2025 have no "public hearing" in what is stored) and why eleven matches have no date. The reader works on what is stored and does not try to recover what was cut; M9 records that as a debt row.

Item 62881 belongs to meeting 2613, whose `external_id` is still `event-2713` though it is dated 2026-10-26: a row the video site listed and never recorded (GitHub issue #62; `D137` in `docs/DEBT.md` names this meeting). Its 51 items repeat the October 13 agenda. That is how one hearing came to be set by two items, and why the page says "On the agenda of" and no more.

On the meetings side, on 2026-11-16: meeting 3207 (`event-2718`, 2026-11-17, `start_time` 11:00, council, `calendar_event_id` 120) and calendar event 120 ("BIRMINGHAM CITY COUNCIL MEETING, November 17, 2026", starting 09:30 Chicago, status NULL) are the same meeting; calendar event 79 ("BUDGET AND FINANCE COMMITTEE MEETING, November 23, 2026", 15:30, `active`) has no meeting row; events 70, 71, 78 and 80 are giveaways. Of 37 stored calendar events, 14 have a NULL status and 23 `active`; none has another status and none says cancelled.

### The neighborhood schedule

The source is "CITY OF BIRMINGHAM COMMUNITY RESOURCE SERVICES DIVISION NEIGHBORHOOD ASSOCIATION MEETING SCHEDULE", "Revised February 3, 2026", at `https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/s3fs-public/2026-02/2026_NA_Meeting_Schedule_rev._2-3-2026.pdf`. The author fetched it on 2026-11-16 with `curl` from this machine (HTTP 200, `application/pdf`, 155,273 bytes, SHA-256 `f9987d63389a280b5333fb9675d090bcf76c3069ccce7f05ea1052fabda7333e`) into a scratch directory, not into the repository. It is three pages with a text layer. `pdfplumber` (already in `requirements.txt`) reads it two ways. `page.extract_text()` runs the columns together and interleaves a cell that wraps onto two lines with its neighbours ("Conference" on one line, the Industrial row on the next, "Call/In-Person" on a third). `page.extract_tables()` returns one table per page of four columns and 101 rows in all: two header rows and 99 associations, every name distinct. The four columns are the association, the meeting date and time, the meeting type, and the meeting information.

What the 99 rows hold, from the table reading: 94 rules are of the form "<First|Second|Third|Fourth> <weekday> of each month @ <h>:<mm> <a|p>.m."; the other five are "Fourth Tuesday of each month 6:00 p.m." (Dolomite, no "@"), "Fourth Monday @ 6:00 p.m." (East Birmingham), "Second Monday of each month @4 p.m." (Gate City), "First Monday of this month @ 6:30 pm" (Glen Iris), and "Meeting months: First Tuesday of each month on Feb, April, June, Aug, Oct & Dec. @ 6:00 p.m." (Overton). Every row has a time. The meeting type is spelled 21 ways ("In-Person", "In Person", "In-Persopn", "Conference Call", "Coference Call", "Teleconfernce", "Zoom", "Zoom/ In-Person", and so on); Bridlewood's type and information both read "No Meetings". The information cell holds a place, or dial-in or meeting-id details, or both separated by a slash; Gate City's ends "Conference Call TBD"; East Brownsville's reads "(Jan-Apr) Dial: ... / (May-Nov) Mary Dorsey Center ..."; the table reading returns Highland Park's information cell empty though the page prints "Visit highland-park.org for in-person meeting location / MI: 819 7094 5731". The table reading is therefore a good draft and not the transcription: the M4 session checks every row against the page by eye, and the operator reads the generated sheet before deploy.

### Terms

An entry is one thing on the page: a meeting, a hearing, or one dated neighborhood meeting. A reading is what the hearing reader returns for one title. The trigger is the phrase that makes a title a candidate. The subject is the text after the hearing's date. An occurrence is one date a schedule rule produces. The window is today through today plus 60 days, both in America/Chicago. A VEVENT is one event in the iCalendar text format (the `.ics` file a calendar program reads); a UID is the identifier a calendar program uses to tell that an event it fetched again is the same one.

### Debt rows this plan meets

`docs/DEBT.md` is the register of deliberate deferrals; a row's last column says what triggers it. This plan pays none. It is cut to avoid tripping these, and a session that finds itself about to edit one of the named files stops and records why first: `D69`, `D34` and `D65` (no worker task is added and `src/docket/worker/` is not edited); `D34` again (`src/docket/web/__init__.py` is not edited); `D60`, `D61`, `D62` (`src/docket/services/briefing.py` is not edited); `D119` (`src/docket/services/meeting_types.py` is not edited); `D122` (no test seeds a city carrying a calendar key: every test that needs a city uses Birmingham, which the migrations seed, with rows it prefixes and deletes, and the new migration test asserts about Birmingham's row only and says nothing about other cities). `D131` is tripped and re-deferred (Decision Log). `D117` is a dependency, not a trigger: the cause of issue #88 makes an upcoming Granicus row's `start_time` two hours late until pull request #181 merges. `D7` and `D138` are not touched.

Changing `src/docket/services/ingest.py` requires having read `docs/PRINCIPLES.md` (`AGENTS.md`, Working rules). `D102`, `D105` and `D106` name that file for its video-timestamp backfill, which this plan does not touch.

### Identifiers

A decision number in `docs/decisions/`, a debt id in `docs/DEBT.md`, and a migration number are each chosen by the session that writes the file: the lowest number above every one spent on `origin/main` and on any open pull request at that moment (`gh pr list --state open`, then the file lists of each). On 2026-11-16 the highest migration on `origin/main` was 046, the highest decision 0106, the highest debt id D153, and the one open pull request, #181, adds none of the three; those figures are a starting point to check, not numbers to use unchecked. This plan writes "the hearings migration" and never its number. A new migration is also added to the module list in `src/docket/migrations/runner.py` (the list that ends with `"docket.migrations.046_alignment_stretches"`), or the runner does not apply it.

## Plan of Work

### M1: the hearing reader

Create `src/docket/enrichment/hearings.py`, importing only the standard library. It defines `RULE_VERSION = 1`; `KINDS = ("zoning", "weed_lots", "vacation", "budget", "other")`; `KIND_LABELS`, mapping those to "Zoning", "Weed lots", "Street or right-of-way", "Budget", "Other"; the frozen dataclass `HearingReading` with `hearing_date: date | None`, `kind: str`, `subject: str`, `subject_key: str`, and `property_count: int | None`; `read_hearing(title: str | None) -> HearingReading | None`; and `same_hearing(key_a: str, key_b: str) -> bool`.

`read_hearing` applies these rules in order, and each is a contract a later milestone relies on.

The text is the title with every run of whitespace replaced by one space. The trigger is the first match, case ignored, of `\b(?:setting|to set|providing for) (?:a|the) public (?:show cause )?hearing\b`. No trigger, no reading: the function returns `None`.

A date is a month's full English name, a day of one or two digits, an optional comma, and a four-digit year (`November 17, 2026` or `July 15, 2025`), case ignored; a date that is not a real day is no date. The hearing's date is found by the first of these that yields one. First, the date that follows the trigger at once, allowing a comma, spaces, and the word "on" between. Second, the first "on the <day><st|nd|rd|th> day of <Month>, <year>" after the trigger. Third, the first date that follows the word "on" inside a clause that begins "to be held" after the trigger and contains no full stop or semicolon before the date. Then one correction: when the text anywhere holds "CHANGE HEARING DATE FROM <date> TO <date>" (case ignored) and the date found equals the first of the two, the hearing's date is the second. When none yields a date, `hearing_date` is `None` and the reading is still returned, so a dry run can list it.

The kind is the first that fits, tested on the whole text, case ignored: `weed_lots` when it contains "noxious or dangerous weeds"; `zoning` when it matches `zoning|zone district|rezon`; `vacation` when it matches `vacation of|closure of|right[- ]of[- ]way`; `budget` when it contains "budget"; otherwise `other`.

The property count is the integer in the first `(<digits>) properties`, or `None`.

The subject is the text after the date when the date followed the trigger at once (leading commas and spaces removed), and otherwise the text after the trigger. The subject key of a `weed_lots` reading with a count is `weeds:<count>`. Any other key is the subject with every `[...]` group removed, cut at the first "(Submitted by" or "(Recommended by" (case ignored), lower-cased, and reduced to the characters a to z and 0 to 9. `same_hearing` is true when the keys are equal, or when one begins with the other and the shorter is at least 90 characters long (`PREFIX_MIN = 90`; 40 as first authored, corrected on 2026-11-16, Decision Log). (Dates and kinds are compared by the caller; `same_hearing` compares keys alone.) The subject is always cut from where the first date form matched in the text, whatever the "CHANGE HEARING DATE" correction then did to the date: item 2116's subject begins "to consider the adoption of an Ordinance", its key is 100 characters, ends `zac202500019`, and does not contain `november`.

Create the fixture `tests/fixtures/hearings/birmingham_titles.json`, a JSON list of the 25 objects in Artifacts and Notes ("The fixture titles"), copied exactly: each has `id` (the production item id), `len` (the stored title's full length), and `title` (the stored title, or its first 420 characters where `len` is greater than 420). Create `tests/unit/test_hearing_reader.py`, which loads the fixture and asserts, for each id, the reading in the table of expected readings in Artifacts and Notes, and the four pair cases stated there (same and different hearings). Add tests for the rules the fixture cannot reach: the third date form on a constructed sentence ("... setting a public hearing to consider a moratorium to be held at the regular meeting of the Council in the Council Chambers on March 3, 2026" reads 2026-03-03), an impossible date ("February 30, 2026" reads no date), the three facts about item 2116's subject and key just given, `same_hearing` false for the 82-character key `toconsidertheadoptionofanordinancetoamendthezoningdistrictmapofthecityofbirmingham` against item 1680's key, which opens with it (82 is under 90), false for the first 89 characters of item 1680's key against the whole of it and true for the first 90, `read_hearing(None)` and `read_hearing("")` returning `None`, and a test that reads the module's source and fails if it contains `import docket` or `from docket` (the layer rule, since no mechanical boundary check exists: `boundary-lint` is only `specced` in `docs/capabilities/index.md`).

Result: a pure function later milestones call. Proof: the acceptance in Validation.

### M2: storage

Write the hearings migration under `src/docket/migrations/` (number by the rule in Identifiers; file name `<number>_public_hearings.py`, in the shape of `043_calendar_sources.py`: a module docstring, `SQL_UP`, `SQL_DOWN`) and register it in `runner.py`. Up creates two tables and sets Birmingham's flag:

    CREATE TABLE IF NOT EXISTS public_hearings (
        id              SERIAL PRIMARY KEY,
        municipality_id INTEGER NOT NULL REFERENCES municipalities(id) ON DELETE CASCADE,
        hearing_date    DATE NOT NULL,
        kind            TEXT NOT NULL CHECK (kind IN ('zoning', 'weed_lots', 'vacation', 'budget', 'other')),
        subject         TEXT NOT NULL,
        subject_key     TEXT NOT NULL,
        property_count  INTEGER NULL,
        rule_version    INTEGER NOT NULL,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (municipality_id, hearing_date, kind, subject_key)
    );
    CREATE INDEX IF NOT EXISTS idx_public_hearings_city_date ON public_hearings (municipality_id, hearing_date);
    CREATE TABLE IF NOT EXISTS public_hearing_items (
        agenda_item_id INTEGER PRIMARY KEY REFERENCES agenda_items(id) ON DELETE CASCADE,
        hearing_id     INTEGER NOT NULL REFERENCES public_hearings(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_public_hearing_items_hearing ON public_hearing_items (hearing_id);
    UPDATE municipalities SET metadata = metadata || '{"coming_up": true}'::jsonb WHERE slug = 'birmingham';

The link table's primary key is the item, because one title yields one reading, so an item belongs to at most one hearing and a second run moves it rather than doubling it. Down removes the key (`metadata - 'coming_up'`) and drops both tables. The kind list in the CHECK is frozen text, as migration 038's vocabularies are; its owner is `KINDS` in the reader.

Create `src/docket/services/hearings.py`. It owns every statement on the two tables.

`find_readings(municipality_id, since, until=None) -> list[dict]` runs one SELECT of `agenda_items` joined to `meetings` for the city where `meetings.meeting_date >= since` (and `<= until` when given) and `agenda_items.title ~* 'public\s+(show\s+cause\s+)?hearing'`, ordered by item id, and returns one dict per item whose `read_hearing` is not `None`: `item_id`, `meeting_id`, `meeting_date`, `reading`. It reads neither new table, so it runs against a database that does not have them.

`group_readings(rows) -> list[dict]` is pure. It takes the dated rows longest key first (equal lengths in item-id order), so a group's first row carries its longest key. A row joins the group of its date and kind whose key equals its own; failing that, the group of its date and kind whose key begins with its own, when its own key is at least 90 characters and there is exactly one such group; otherwise it starts a group. A group keeps its first row's key and subject, the first property count seen, and its item ids in ascending order. (As first authored the rows were taken in item-id order and joined the first group that fit; corrected on 2026-11-16, Decision Log.)

`refresh_hearings(municipality_id, since, until=None) -> HearingReport` calls the two and then, in one transaction: loads the city's stored hearings whose date is among the groups' dates; matches groups to stored hearings of the same date and kind in two passes, first every group whose key equals a stored key, then, for each group still unmatched, the stored hearing not yet matched whose key `same_hearing` accepts, when there is exactly one; inserts a hearing for each group left unmatched, and updates `subject`, `subject_key` and `updated_at` of a matched one when the group's key is longer; writes every link in one statement (`INSERT INTO public_hearing_items (agenda_item_id, hearing_id) VALUES ... ON CONFLICT (agenda_item_id) DO UPDATE SET hearing_id = EXCLUDED.hearing_id`, through `psycopg2.extras.execute_values`); deletes, in one statement, every link whose item belongs to a meeting of the city dated from `since` (to `until` when given) and is not among the items this run gave a dated reading (`... AND agenda_item_id <> ALL(%s)`, which with an empty list removes every link in the range, as it should); and deletes, in one statement scoped to the city, hearings left with no link. `HearingReport` is a frozen dataclass of `matched`, `dated`, `undated`, `hearings`, `created`, `linked`. Nothing here loops a write over existing rows: the inserts are of new rows in a new table, a few a week after the first run and about sixty in the backfill, which is the scale `services/city_calendar._upsert` already accepts, and both deletes are one statement each (decision `0026`).

`refresh_recent(municipality_id) -> HearingReport | None` reads the city's metadata, returns `None` unless it carries `"coming_up": true`, and otherwise calls `refresh_hearings` with `since` 120 days before today (`RECENT_DAYS = 120`).

`list_upcoming(municipality_id, start, end) -> list[dict]` returns the hearings dated from `start` to `end` that have at least one visible link, each with `id`, `hearing_date`, `kind`, `subject`, `property_count`, and `items`: a list, oldest meeting first, of `item_id`, `meeting_id`, `meeting_date`, `agenda_url`. A link is visible when its meeting is not hidden, its meeting's title does not say cancelled (`query.CANCELLED_PREDICATE_MT`), and the item's `processing_status` is not `withdrawn`. A withdrawn resolution set no hearing, an agenda for a cancelled meeting was not acted on, and a hidden meeting's item page answers 404; a hearing with no visible link is not returned.

Tests. `tests/integration/test_<number>_migration.py`, in the pattern of `tests/integration/test_043_migration.py`: up creates both tables and gives Birmingham's metadata `coming_up` true; down removes the key and both tables; nothing is asserted about any other city. `tests/services/test_hearings_store.py`: seeds, under Birmingham's id, meetings and items whose titles come from the M1 fixture, every seeded meeting title prefixed `HEARINGS_TEST_`, and deletes them (the cascade removes links; the test also deletes the city's `public_hearings` rows it made) before and after. Its cases: fixture titles 62830 twice (two items, two meetings) make one hearing with two links; 62182, 62830 and 62882 on one date make three hearings; a second `refresh_hearings` changes no count; 3339 then 3297 make one hearing whose stored key is 3339's longer one; an item whose title is edited to lose its trigger while still containing "public hearing" loses its link on the next run and its hearing is deleted, and so does one whose title is edited to an unrelated sentence; an item of a meeting dated before `since` keeps its link through a run that does not read it; item 1680's and item 1681's titles and a third item whose title is 1680's cut just after "ZAC2025-000" (a key of 98 characters that opens both of theirs) on one date make three hearings, while 1680's title and that cut title without 1681's make one hearing with two links (the accepted limit: with one candidate the short key joins it); an undated reading (3238) stores nothing; `list_upcoming` leaves out a hearing whose only item is `withdrawn`, whose only meeting is hidden, or whose only meeting's title says "CANCELLED", and returns a hearing with one visible and one hidden link with the visible one alone; `refresh_recent` returns `None` for a seeded city without the flag (`mobile`).

### M3: the ingest step, the script, and the dry run on real rows

In `ingest_municipality` (`src/docket/services/ingest.py`), after the block commented "Stage 3b" and before "Stage 4", add a stage "3c" in the same shape: inside `try`, call `hearings.refresh_recent(municipality_id)` and, when it returns a report, log its counts; on any exception append `f"Hearings: {e}"` to `errors` and log it. Import `hearings` beside `meeting_types`. Add `tests/integration/test_ingest_hearings.py`. No existing test runs `ingest_municipality` from end to end (the ingest tests call `_upsert_meetings` and its neighbours directly), so this one supplies its own adapter: it monkeypatches `docket.services.ingest.get_adapter` to return an object whose `list_meetings(since=None)` returns one `RawMeeting` (the dataclass in `src/docket/models/protocol.py`; an `external_id` of the form `event-99xxxx`, a title prefixed `HEARINGS_TEST_`, a date five days back, no minutes link) and whose `fetch_agenda_items(meeting)` returns one raw item whose title is fixture title 63108. It runs `ingest_municipality("birmingham")` and asserts a `public_hearings` row dated 2026-12-08 of kind `zoning` linked to the stored item; then, in a second test, that an exception raised by a monkeypatched `hearings.refresh_recent` appears in `IngestResult.errors` as a string beginning "Hearings:" while the meeting and its item are stored. It deletes its meeting (by the title prefix) and the hearings it made, before and after.

Create `scripts/backfill_hearings.py`, in the shape of `scripts/hide_non_meetings.py`: `--city <slug>` (required), `--since YYYY-MM-DD` (required: the script refuses to run without a bound), `--until YYYY-MM-DD` (optional), `--dry-run`. With `--dry-run` it calls `find_readings` and `group_readings` only, so it issues one SELECT and reads neither new table, and prints one line per matched item, in item-id order,

    <item id>  <meeting date>  <hearing date or "no date">  <kind>  <property count or "-">  <first 70 characters of the collapsed title>

then one line per hearing (`hearing <date> <kind> items=<ids>`), then `matched=<n> dated=<n> undated=<n> hearings=<n>`. Without `--dry-run` it prints the same and then calls `refresh_hearings` and prints `created=<n> linked=<n>`. Its docstring says the order (dry run first), that against production `DATABASE_URL` is set to `DATABASE_PUBLIC_URL`, and that a second run creates nothing. `tests/unit/test_backfill_hearings_script.py` (pattern: `tests/unit/test_backfill_committee_documents_script.py`) asserts the refusal without `--since` and that `--dry-run` calls neither `refresh_hearings` nor any write.

Then the session runs the dry run against production, read-only, with the command in Concrete Steps, saves the output outside the repository, and records in this plan's Artifacts and Notes: the totals line; the hearing lines dated on or after the day of the run; the line for items 62830 and 62881; and a paragraph comparing the run restricted by `--until 2026-11-16` with the two earlier counts (the author's 78 matched, 67 dated, 11 undated; the operator's 71 items and 9 dated on or after 2026-11-16), naming every item on which the reader and the author's SQL differ and saying why. This output is the comparison on real rows that `docs/PRINCIPLES.md` "Evidence or silence" requires of a pipeline change before it ships; there is no older pipeline to compare with, so the two earlier counts stand in for "old". If the harness refuses the Railway command, the session does not tick M3: it records the refusal in Surprises & Discoveries, commits, and stops, and the operator runs the command in the WSL checkout and pastes the output for the next session.

### M4: the schedule, saved and transcribed

Add to `src/docket/config.py`, beside `HOW_IT_WORKS_ROOT`: `COMING_UP_ROOT = os.environ.get("COMING_UP_ROOT", "content/coming-up")`.

Create `content/coming-up/birmingham/sources/2026_NA_Meeting_Schedule_rev._2-3-2026.pdf` by fetching the address in Context with `curl` (one request; the session checks the SHA-256 against the one in Context and, if the city has replaced the file, records the new digest and the date as a Surprises entry and carries on with the file it fetched). Create `content/coming-up/birmingham/sources/README.md` in the shape of `content/how-it-works/birmingham/sources/README.md`: one table row with the file, what it is (title, the revision date printed on it, three pages), the public address, the read date, and the SHA-256; and a paragraph saying the PDF is kept so a reviewer can check every transcribed row, that the page links the public address, and how a later revision is saved (M9's spec owns the procedure; the README points there).

Create `content/coming-up/birmingham/neighborhood-schedule.yaml`:

    source:
      title: "City of Birmingham Community Resource Services Division Neighborhood Association Meeting Schedule"
      revised: 2026-02-03
      url: "https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/s3fs-public/2026-02/2026_NA_Meeting_Schedule_rev._2-3-2026.pdf"
      file: "sources/2026_NA_Meeting_Schedule_rev._2-3-2026.pdf"
      sha256: "<the digest of the saved file>"
      read: <the date the file was fetched>
      year: 2026
    checked:
      - by: "<who>"
        on: <date>
        how: "<one sentence>"
    associations:
      - name: "Acipco-Finley"
        rule_text: "First Wednesday of each month @ 5:30 p.m."
        ordinal: first
        weekday: wednesday
        time: "17:30"
        type_text: "In-Person"
        modes: [in_person]
        place: "Acipco Finley Community Room, 453 38th Ave W, Birmingham, AL 35207"
        remote: null

`name`, `rule_text` and `type_text` are the PDF's cells, character for character, misspellings included ("In-Persopn" stays). `ordinal` is `first`, `second`, `third` or `fourth`, and `weekday` a lower-case English weekday, or both are `null` for a row given no dates; `months` is an optional list of month numbers (absent means all twelve; Overton's is `[2, 4, 6, 8, 10, 12]`). `time` is 24-hour `"HH:MM"` or `null`. `modes` is a list drawn from `in_person`, `phone` (any spelling of conference call or teleconference), and `video` (Zoom), in the order the type cell names them, and is empty for "No Meetings". `place` is the part of the information cell that names where to go in person and `remote` the part that gives dial-in or meeting-id details, each copied as printed, each `null` when the cell has no such part or says "TBD" (Gate City's `remote` is `null`); a cell whose parts cannot be told apart goes whole into the one field it mostly is. `undated_reason` is required exactly when `ordinal` is `null`: for Bridlewood `"The schedule says: No Meetings"`, for Glen Iris `"The schedule says: First Monday of this month @ 6:30 pm"`. The first `checked` entry is the session's own ("Claude, plan birmingham-coming-up M4", the date, "each row compared with the saved PDF's page"); the operator's reading adds a second after the merge.

The session drafts the 99 rows from `pdfplumber`'s `extract_tables()` with a script kept in its scratch directory, then renders each PDF page to an image or reads the page text and compares every row, correcting the draft; Highland Park's information cell, empty in the table reading, is taken from the page.

Create `src/docket/services/neighborhood_schedule.py`, which reads files only and imports nothing from `docket.web`. It defines `ScheduleError(ValueError)`; frozen dataclasses `Association` (the fields above) and `Schedule` (`title`, `revised`, `url`, `file`, `sha256`, `read`, `year`, `checked`, `associations`); `load_schedule(city_dir: Path) -> Schedule`; and `get_schedule(slug: str) -> Schedule | None`, which returns `None` when `COMING_UP_ROOT/<slug>/neighborhood-schedule.yaml` does not exist and otherwise the loaded schedule, cached per slug for the life of the process. `load_schedule` raises `ScheduleError`, naming the file and the association, for: a missing or unknown key; an `ordinal`, `weekday`, `modes` or `months` value outside its vocabulary; one of `ordinal` and `weekday` null and the other not; a `time` that is not `HH:MM`; a duplicate `name`; an empty `rule_text` or `type_text`; `undated_reason` present with an ordinal or absent without one; an empty `checked` list; a `source.file` that does not exist; and a saved file whose SHA-256 is not `source.sha256`.

Tests, `tests/unit/test_neighborhood_schedule.py`: the checked-in file loads and holds 99 associations; each refusal above, on a copy of a three-association file written to `tmp_path`; and the cross-check against the PDF, which opens the saved PDF with `pdfplumber`, collects the table rows of all pages, and asserts, comparing lower-cased letters and digits only, that every association's `name`, `rule_text` and `type_text` equal the first three cells of exactly one table row, and that its `place` and `remote`, when not null, are each contained in that row's fourth cell. Rows where the table reading itself is wrong are listed in the test in a dict of name to the reason (Highland Park's empty cell is the one known), and for those the comparison is against the page's `extract_text()`; the session records each exception it adds in the Decision Log.

### M5: dates and the reading sheet

Add to `src/docket/services/neighborhood_schedule.py`: `occurrences(schedule, start: date, end: date) -> list[Occurrence]`, where `Occurrence` is a frozen dataclass of `association` and `on: date`. For each association with an ordinal, for each month of `schedule.year` in its `months` (all twelve when absent), the date is the ordinal-th `weekday` of that month; it is returned when it lies in `start` to `end` inclusive. Nothing is produced for a year other than `schedule.year`, so after 2026-12-31 the list is empty. The result is ordered by date, then time with `null` last, then name. Add `undated(schedule) -> list[Association]`.

Tests, in the same file as M4's: the dates in Artifacts and Notes ("Dates worked by hand"), each asserted; the count for the whole of 2026 is 1,158 (96 associations with a rule for every month, 96 × 12 = 1,152, plus Overton's 6; Bridlewood and Glen Iris give none); `occurrences` for 2027-01-01 to 2027-12-31 is empty; `undated` returns Bridlewood and Glen Iris. If the M4 transcription found a row the author's table reading misread, so that the count differs, the session records the row and the corrected arithmetic in Surprises & Discoveries and asserts the corrected figure.

Create `scripts/coming_up_reading_sheet.py` in the shape of `scripts/how_it_works_reading_sheet.py`: it prints, as Markdown, the source's title, address, revision date and digest, the commit that last changed `content/coming-up/<city>/`, and one tick-box line per association with its name, `rule_text`, what the loader made of it ("first Wednesday, every month, 5:30 p.m." or the undated reason), `type_text`, `modes`, `place`, `remote`, and the association's next three dates of the schedule year. Run it and save the output as `docs/runbooks/coming-up-reading-birmingham.md`, and add that file to the runbook index at the end of `docs/specs/operations.md` (the "Runbooks" section) in one line.

### M6: the entries

Create `src/docket/services/coming_up.py`. It reads through `services/hearings.py` and `services/neighborhood_schedule.py` and runs two SELECTs of its own, on `meetings` and on `city_calendar_events`. It defines `WINDOW_DAYS = 60`; `is_coming_up_city(municipality: dict | None) -> bool` (the metadata carries `"coming_up": true`; written like `briefing.is_briefing_city`, which accepts the metadata as a dict or a JSON string); the frozen dataclass `Entry`; and `list_entries(municipality: dict, *, today: date | None = None) -> list[Entry]`, where `today` defaults to `_today()`, a module-level function returning the current date in America/Chicago. Every bound in the function's SQL and in its calls is computed from that one `today` and passed as a parameter (no `NOW()` or `CURRENT_DATE` in its statements), so a test that fixes the day fixes the whole result.

`Entry` has: `kind` (`meeting`, `hearing`, `neighborhood`); `uid` (text); `on` (date); `starts_at` and `ends_at` (timezone-aware datetimes or `None`); `title`; `detail` (a tuple of short strings the page prints as lines); `links` (a tuple of `(label, url)` pairs, the first being the city's own document where one exists; a city document's `url` is its full address and a docket.pub page's is a site path beginning `/`, and M8's `absolute` is what makes the second sort absolute); `source_url` (that first city document, or `None`); and `place` (text or `None`). The revision of 2026-11-16 adds six fields: `badge` and `badge_label` (the token and the words of the entry's coloured label: `meeting` "Meeting" for a meeting; for a hearing by its kind, `zoning` "Zoning", `weed-lots` "Weed lots", `vacation` "Street or right-of-way", `budget` "Budget", and `hearing` "Hearing" for kind `other`; `neighborhood` "Neighborhood" for a neighborhood meeting); `cancelled` (bool) and `cancelled_by` (a tuple of source names, empty unless `cancelled`); `attend` (a tuple of `(label, text)` pairs, empty except for a neighborhood meeting); and `association` (the association's slug for a neighborhood meeting, else `None`).

The slug of an association is made by `association_slug(name) -> str`, defined here: the name lower-cased, each run of characters other than a to z and 0 to 9 replaced by one hyphen, and hyphens at either end removed ("Acipco-Finley" gives `acipco-finley`; "Forest Park/South Avondale" gives `forest-park-south-avondale`).

Meetings. Granicus rows: `meetings` of the city with `external_id LIKE 'event-%'`, `is_hidden = FALSE`, and `meeting_date` in the window. Calendar events: `city_calendar_events` of the city whose `starts_at`, converted to America/Chicago, falls on a date in the window, kept only when `meeting_types.classify_event(title)` is not `None` (which drops the giveaways). Pairing: first, a row and an event are one meeting when the row's `calendar_event_id` is the event's id; then, among what is left, a row whose `meeting_type` is `council` and an event that classifies as `council` on the same Chicago date are one meeting when each is the only such unpaired one that day. Everything else stands alone. Then each entry is tested for cancellation and kept either way (the Decision Log entry of 2026-11-16 that supersedes "left out"). The row says cancelled when its title does (`query.is_cancelled_title`). The event says so when it is not live (`meeting_types._is_live`: a stored status other than NULL or `active`, or a title that says cancelled). `cancelled` is true when either says so, and `cancelled_by` names each that does, in this order: "the council's video site" for the row, "the city calendar" for the event. A cancelled entry's `detail` opens with one sentence: "Cancelled, according to the city calendar." (or "the council's video site", or "the council's video site and the city calendar"); with one exception, that when the event is not live only because its stored status is a word other than `cancelled` or `canceled` (compared lower-cased) and neither title says cancelled, the sentence is `The city calendar marks this "<status>".` with the status as stored, since docket.pub does not know that word means cancelled. When the entry is a pair and only one of its two sources says cancelled, a second sentence follows: "The council's video site still lists it." or "The city calendar still lists it." Nothing else about a cancelled entry changes: its time, title and links are what they would have been. A hidden row is still absent, cancelled or not. The title is `adapters._helpers.label_for` over the row's `meeting_type`, `session_kind`, `body_name` and title (as the `meeting_label` template global does), or, for an event alone, over the event's classification. The time is the event's `starts_at` and `ends_at` when there is an event; otherwise the row's `meeting_date` and `start_time` in America/Chicago, or none when `start_time` is NULL. Links: "City calendar" to the event's `source_url` when there is an event; "Agenda" to the row's `agenda_url` when there is a row with one; "Meeting on docket.pub" to the meeting's page path when there is a row. The UID is `calendar-<event id>@docket.pub` when there is an event, else `meeting-<meeting id>@docket.pub`.

Worked on production's rows of 2026-11-16 with `today` 2026-11-16: meeting 3207 and event 120 pair by the first rule and give one entry, titled with what `label_for` returns for a regular council meeting (the session reads the function and asserts that text), on 2026-11-17 at 9:30 a.m., UID `calendar-120@docket.pub`, with all three links; event 79 gives one entry for the Budget and Finance committee on 2026-11-23 at 3:30 p.m. with the calendar link alone; events 78 and 80 give nothing; events 66, 67, 70 and 71 are before the window.

Hearings: `hearings.list_upcoming(municipality_id, today, today + 60 days)`. The title is `KIND_LABELS[kind]` followed by " hearing" ("Zoning hearing", "Weed lots hearing", "Street or right-of-way hearing", "Budget hearing"), except that kind `other` is titled "Public hearing". The detail is, for `weed_lots` with a count, "<count> properties" (and for one without a count nothing: no number is invented); for any other kind, the subject cut to 240 characters at a word boundary with an ellipsis when cut. No time. Links: for each item, "On the agenda of <Month D, YYYY>" to the item's page path, and for the newest item whose meeting has an `agenda_url`, "City agenda" to it, placed first. UID `hearing-<id>@docket.pub`.

Neighborhood meetings: `neighborhood_schedule.get_schedule(slug)`, and when it is not `None`, `occurrences(schedule, today, today + 60 days)`. The title is "<name> Neighborhood Association". The time is the date and `time` in America/Chicago, or none. The detail holds `type_text` as printed; then, when `modes` contains `phone` or `video` and `remote` is null, "Call-in details are not in the schedule"; and when `time` is null, "The schedule gives no time". `attend` holds `("Where", place)` when `place` is not null and then `("Call-in", remote)` when `remote` is not null, each text as transcribed; it is empty when both are null. (As first authored, `remote` was a detail line; the revision of 2026-11-16 moved it into `attend`.) `place` is the place or `None`. `association` is `association_slug(name)`. One link, "City schedule (PDF)", to `schedule.url`. UID `na-<the association's slug>-<YYYYMMDD>@docket.pub`. A neighborhood meeting is never `cancelled`: the schedule has no such word, and Bridlewood's "No Meetings" gives no dates at all.

The result is ordered by date, then timed entries by start before untimed ones, then kind in the order meeting, hearing, neighborhood, then title.

Also `undated_associations(slug) -> list[tuple[str, str]]` (name and `undated_reason`), and `schedule_source(slug)` returning the schedule's title, address, revision date and year for the page's footer, or `None`.

For the narrowed feeds (revision of 2026-11-16), two more, both pure given their inputs. `filter_entries(entries, *, kind=None, association=None) -> list[Entry]` keeps the order and returns the entries whose `kind` equals `kind` when it is given and whose `association` equals `association` when it is given; with neither it returns them all. `association_feeds(slug) -> list[tuple[str, str]]` returns the name and slug of every association of the city's schedule that has an `ordinal`, in name order, and an empty list for a city with no schedule. `KINDS = ("meeting", "hearing", "neighborhood")` is the vocabulary the route checks `?kind=` against.

Tests, `tests/services/test_coming_up.py`, seeding under Birmingham's id with meeting titles prefixed `COMINGUP_TEST_` and calendar `source_event_id` values prefixed the same, cleaned before and after, with `today` passed in: the production case above reproduced with seeded rows (one merged entry with the calendar's time and three links; a committee event alone; a giveaway dropped); a council row and a council event on one day with no `calendar_event_id` merge by the second rule; two council events and one council row on one day are three entries; a pair whose event has status `cancelled` and whose row's title does not say so gives one entry with `cancelled` true, `cancelled_by` `("the city calendar",)`, and a detail that opens "Cancelled, according to the city calendar." then "The council's video site still lists it."; a pair whose row's title says "CANCELLED" and whose event is `active` gives one with `("the council's video site",)` and the second sentence "The city calendar still lists it."; a pair where both say so gives both names and no second sentence; an event alone with status `postponed` and an ordinary title gives `cancelled` true and the one sentence `The city calendar marks this "postponed".`; the merged production case has `cancelled` false and an empty `cancelled_by`; a hidden row is absent and its calendar event stands alone; a row with NULL `start_time` and no event has `starts_at` `None`; a row dated 61 days ahead is absent; a hearing dated today is present and one dated yesterday absent; a neighborhood occurrence carries the PDF link; Gate City's entry carries "Call-in details are not in the schedule"; with `today` 2027-01-05 there is no neighborhood entry; a city without the flag gives `is_coming_up_city` false. And for the fields the revision added: every entry's `badge` is one of the seven tokens and a seeded zoning hearing's is `zoning` with `badge_label` "Zoning"; the first association of the checked-in schedule whose `remote` is not null (the test finds it, and fails if there is none) has `("Call-in", <that remote>)` in its entry's `attend` and no detail line equal to it, and Gate City's `attend` has no "Call-in" pair; a meeting's and a hearing's `attend` are empty; the slugs `association_feeds("birmingham")` returns are all different and number the schedule's dated associations (97 unless M4 recorded otherwise: 99 less Bridlewood and Glen Iris); `filter_entries` with `kind="hearing"` returns only hearings in their original order, with `association="acipco-finley"` only that association's meetings, with `kind="meeting"` and an association together nothing, and with neither everything. The file's cleanup also deletes the `public_hearings` rows it seeded.

### M7: the page

In `src/docket/web/public.py`: import `coming_up`; register `@bp.app_template_global("has_coming_up")` returning `coming_up.is_coming_up_city(municipality)`; add `@bp.route("/al/<slug>/coming-up/")`, `coming_up_page(slug)`: 404 when the city does not exist or is not a coming-up city; otherwise render `coming_up.html` with the municipality, the entries grouped by date, the undated associations, the schedule source, and the feed's address. The route executes no SQL.

Create `src/docket/web/templates/coming_up.html`, extending `base.html` as `how_it_works.html` does, with its own stylesheet `src/docket/web/static/css/coming_up.css` linked the way `how_it_works.html` links `css/how_it_works.css` (`layout.css` and `mobile.css` are not edited). The page has: an `<h1>` "What's coming up in Birmingham" (the city's name from the row); one sentence saying the list covers the next 60 days and every entry links to the city document it came from; a link "Subscribe to this calendar" to the feed's address (the route M8 adds; until then the template builds the path from the slug, `/al/<slug>/coming-up.ics`, as plain text in an `href`, which M8 replaces with `url_for`); then one `<section>` per date with the date as its heading ("Tuesday, November 17, 2026"), and inside it one `<article id="<the uid up to its @>" data-entry-uid="<uid>" data-entry-kind="<kind>">` per entry (so `hearing-12@docket.pub` has the `id` `hearing-12`, which M8b's feed links to) holding the entry's label, the time when there is one (the page prints nothing in its place when there is none, except the detail line M6 supplies for a neighborhood meeting), the title, the detail lines, the place, and the links. The label is `<span class="cu-badge cu-badge--<badge>"><badge_label></span>`, and a cancelled entry has a second one after it, `<span class="cu-badge cu-badge--cancelled">Cancelled</span>`, and the attribute `data-entry-cancelled="true"` on its article; its detail sentences from M6 say who says so. `coming_up.css` gives each of the eight `cu-badge--` classes (the seven tokens of M6 and `cancelled`) its own background and text colour, chosen so the text has a contrast ratio of at least 4.5 to 1 against its background (the session computes each ratio from the two colours and records the eight figures; if `base.html` or `how_it_works.css` turns out to carry a dark theme, the session gives the classes a pair for it as well and records those figures too); no kind's label is larger, bolder, or placed differently from another's. When the entry's `attend` is not empty, the article holds, after the detail lines, `<div class="cu-attend">` with the words "How to attend" and one line per pair, the label then the text; the place is then printed there and not a second time. An entry with an empty `attend` has no such block. The neighborhood entries of a date sit together inside one `<details>` whose `<summary>` is "<n> neighborhood association meeting(s)", after that date's meetings and hearings, so a date with twelve of them stays short; they are still in the page's HTML, each with its `data-entry-uid`. When there are no entries at all the page says "Nothing is listed for the next 60 days." Under the list, a section "Where these dates come from" says, in sentences: meetings come from the council's video site and the city's calendar, and a meeting either of them calls cancelled is shown marked cancelled, with the one that says so named; a hearing's date is read by docket.pub from the text of a resolution on a council agenda, without a language model, an agenda is posted before its meeting so a listed resolution may not yet have been adopted, and a hearing the council later moved may still show on its first date; neighborhood dates are computed by docket.pub from the monthly rule in the city's schedule (title, revision date, linked), which covers <year> only, and a meeting moved for a holiday is not reflected. Then, when there are undated associations, a line for each: its name and its reason.

In `src/docket/web/templates/partials/briefing/meetings.html`, inside `{% if has_coming_up(municipality) %}`, add a link "What's coming up →" to the page beside "All meetings →". The "Follow:" line is not changed in this milestone.

In `src/docket/web/crawlers.py`, `sitemap_city_meetings` adds `/al/<slug>/coming-up/` to its first entries when the city is a coming-up city, asked through a new `sitemap_svc.has_coming_up(slug)` in `src/docket/services/sitemap.py`, which loads the municipality row and calls `coming_up.is_coming_up_city`.

Tests, `tests/web/test_coming_up_page.py`, with the `client` fixture of `tests/web/conftest.py` and rows seeded as M6's tests seed them (the seeding helper moves to `tests/support/coming_up_seed.py` so M6's, M7's and M8's tests share it): `GET /al/birmingham/coming-up/` is 200 and `GET /al/mobile/coming-up/` and `GET /al/nowhere/coming-up/` are 404; the number of `data-entry-uid="` in the body equals `len(coming_up.list_entries(...))` for the same day; a seeded hearing's article contains its item's page address and "On the agenda of"; a weed-lot hearing's article contains "212 properties" and not its subject text; a neighborhood article contains the PDF address; an entry with no time has no `<time` element; every article has exactly one `cu-badge--` span that is not `cu-badge--cancelled`, and the seeded zoning hearing's reads "Zoning"; a seeded pair whose calendar event has status `cancelled` is one article with `data-entry-cancelled="true"`, a `cu-badge--cancelled` span, and the words "according to the city calendar", and no other article has that attribute; the article of the first schedule association with a `remote` contains "How to attend" and that remote text once, and the seeded council meeting's article does not contain "How to attend"; the seeded hearing's article has `id="hearing-<its id>"`; the undated line names Bridlewood with "No Meetings"; the Birmingham city page (`GET /al/birmingham/`, after clearing `public._overview_cache`) contains the page's address and `/al/mobile/` does not; `/sitemaps/birmingham/meetings.xml` (after `crawlers.clear_cache()`) lists the page and `/sitemaps/mobile/meetings.xml` does not. The route accepts no date parameter. Every test in this file, and in M8's feed test, monkeypatches `coming_up._today` to return 2026-11-16 and seeds its meetings, events and hearings on fixed dates after it, because the checked-in schedule yields no neighborhood meeting after 2026-12-31 and these tests must still pass when run in 2027.

What a factory session can observe here is the markup and the status codes. How the page looks at phone and desktop width is the operator's look, in Validation.

### M8: the feed

Create `src/docket/web/ics.py` with `render_calendar(entries, *, name: str, now: datetime, absolute) -> str`, where `absolute` turns a site path into an absolute address and returns unchanged a link that already begins `http://` or `https://`. It is one function in `public.py`, `_absolute_url(url)`, which prefixes `request.url_root` without its trailing slash to a path; the feed's route passes it here and M8b passes it to its template. The text opens `BEGIN:VCALENDAR`, `VERSION:2.0`, `PRODID:-//docket.pub//Coming up//EN`, `CALSCALE:GREGORIAN`, `METHOD:PUBLISH`, `X-WR-CALNAME:<name>`, holds one `BEGIN:VEVENT` to `END:VEVENT` block per entry, and closes `END:VCALENDAR`. Each event has `UID` (the entry's); `DTSTAMP` (`now` in UTC, `YYYYMMDDTHHMMSSZ`); `DTSTART`, as `YYYYMMDDTHHMMSSZ` in UTC when the entry has a start, and as `DTSTART;VALUE=DATE:YYYYMMDD` when it has none; `DTEND` in UTC when the entry has an end, `DTEND;VALUE=DATE:` of the next day for an entry without a start, and none for a timed entry without an end; `SUMMARY` (the title); `DESCRIPTION` (the detail lines, then each link as "label: absolute address", then "From docket.pub: " and the page's address, joined by newlines); `LOCATION` when the entry has a place; `URL` (the entry's `source_url`, or the first link made absolute when there is none); and `CATEGORIES` ("Meeting", "Public hearing", or "Neighborhood association"). By the revision of 2026-11-16: the `attend` pairs go into `DESCRIPTION` after the detail lines and before the links, each as "label: text"; and a cancelled entry's event has a `SUMMARY` of "Cancelled: " followed by the title. No event has a `STATUS` line, cancelled or not (the operator's last Decision Log entry of 2026-11-16; the plan first gave a cancelled event `STATUS:CANCELLED`). Text values escape backslash, semicolon and comma with a backslash and a newline as `\n`. Every line ends with CR LF, and a line longer than 75 bytes of UTF-8 is folded: broken before the 76th byte, never inside a multi-byte character, the continuation starting with one space.

In `public.py` add `@bp.route("/al/<slug>/coming-up.ics")`, `coming_up_ics(slug)`, with the page's 404 rule, returning the text with `mimetype="text/calendar"` (Flask adds `charset=utf-8`), `Cache-Control: public, max-age=3600`, and `Content-Disposition: inline; filename="<slug>-coming-up.ics"`. The page's subscribe link becomes `url_for("public.coming_up_ics", slug=...)`, and the city page's "Follow:" line gains, inside the `has_coming_up` test, "calendar (.ics)" linking to it.

Narrowing (revision of 2026-11-16). The route reads two query parameters. `kind`, when present, must be one of `coming_up.KINDS`; `association`, when present, must be a slug `coming_up.association_feeds(slug)` returns; any other value of either answers 404. The route passes `coming_up.filter_entries(entries, kind=..., association=...)` to `render_calendar`. The calendar's name is "<City> coming up" with no parameter; "<City> meetings", "<City> public hearings" or "<City> neighborhood meetings" for a kind; and "<name> Neighborhood Association" for an association, whichever else is given. A narrowed feed with nothing in the window is a valid calendar with no event, answered 200.

Ways to subscribe (same revision). The route `coming_up_page` builds, from `request.host` and `url_for`, the feed's `webcal` address: `webcal://<host><path of public.coming_up_ics>`, the same address as the `https` one with the scheme changed, which is what calendar programs open as a subscription. The page's one subscribe link from M7 is replaced by a block with: "Subscribe in your calendar" linking the `webcal` address; "Add to Google Calendar" linking `https://calendar.google.com/calendar/render?cid=` followed by the `webcal` address percent-encoded with `urllib.parse.quote(address, safe="")`; "Calendar file (.ics)" linking the `https` address; a line "Only:" with three `webcal` links, "meetings", "public hearings" and "neighborhood meetings", each the address with its `?kind=`; and a `<details>` whose `<summary>` is "One neighborhood association (<year> schedule)", the year being the schedule's, so that a reader subscribing late in the year knows the feed has no dates after it until the city publishes the next schedule, holding one `webcal` link per pair of `association_feeds`, the association's name linking the address with `?association=<slug>`. The route passes these to the template as ready addresses; the template builds none.

Tests. `tests/unit/test_ics.py`: an entry with a start and end; one with a start alone; one with neither, whose `DTEND` is the next day; a title containing a comma, a semicolon, a backslash and a newline, escaped; a 200-character summary with a multi-byte character at the fold, which unfolds to the original; every line ending CR LF; no line over 75 bytes. `tests/web/test_coming_up_feed.py`: `GET /al/birmingham/coming-up.ics` is 200 with a `Content-Type` beginning `text/calendar` and `GET /al/mobile/coming-up.ics` is 404; the test unfolds the body, counts `BEGIN:VEVENT`, and asserts the count equals the number of `data-entry-uid="` in the page fetched in the same test from the same seeded rows, and that the set of `UID` values equals the set of `data-entry-uid` values; the seeded hearing's event has `DTSTART;VALUE=DATE:` and a `URL`; the merged meeting's event has `DTSTART` equal to the calendar event's start in UTC; the seeded hearing's unfolded, unescaped `DESCRIPTION` holds its seeded city agenda address once, exactly as seeded, holds its item page as `http://localhost/al/birmingham/items/<id>/`, and the body nowhere contains `localhost/http`. For the revision's additions, in `tests/unit/test_ics.py`: a cancelled entry's event has a `SUMMARY` beginning "Cancelled: " and a `DESCRIPTION` that opens with its cancellation sentence, an entry that is not cancelled has a `SUMMARY` that does not begin so, and no line of the output begins `STATUS`; an entry with two `attend` pairs has both in its unfolded, unescaped `DESCRIPTION`, after the detail and before the first link. In `tests/web/test_coming_up_feed.py`: `?kind=hearing` returns exactly the UIDs of the page's articles whose `data-entry-kind` is `hearing`, and the same for `meeting` and `neighborhood`, the three sets together being the page's whole set; `?association=acipco-finley` returns only UIDs beginning `na-acipco-finley-` and at least one of them (with `today` 2026-11-16 the window holds December 2); `?kind=council` and `?association=nowhere` are 404; `?kind=meeting&association=acipco-finley` is 200 with no `BEGIN:VEVENT`; the page contains `webcal://localhost/al/birmingham/coming-up.ics` (Flask's test client asks as host `localhost`; if the application's configuration sets a `SERVER_NAME`, the test uses that host here and in the next string), a link beginning `https://calendar.google.com/calendar/render?cid=webcal%3A%2F%2Flocalhost%2Fal%2Fbirmingham%2Fcoming-up.ics`, as many links containing `?association=` as `association_feeds("birmingham")` has pairs, and the words "One neighborhood association (2026 schedule)".

### M8b: the existing hearings feed, for a flagged city

Added by the revision of 2026-11-16. Scope: one route, one new template, and the tests of the feed. At the end, `/al/birmingham/upcoming-hearings.rss` lists the hearing entries of the coming-up page, and `/al/mobile/upcoming-hearings.rss` returns what it returned before.

In `src/docket/web/public.py`, `upcoming_hearings_rss(city)`: after the municipality is found, when `coming_up.is_coming_up_city(municipality)` the inner `_render` calls `coming_up.filter_entries(coming_up.list_entries(municipality), kind="hearing")` and renders the new template `rss/scheduled_hearings.xml.j2` with those entries, the municipality, the feed's address, the absolute address of the coming-up page, and M8's `_absolute_url` as `absolute`, which the template applies to every link it prints; otherwise it does exactly what it does today (`query.list_upcoming_hearings` and `rss/upcoming_hearings.xml.j2`). The cache key, the 60-minute cache, the mimetype and the `Cache-Control` header are the same on both paths. `src/docket/services/query.py` and `rss/upcoming_hearings.xml.j2` are not edited.

Create `src/docket/web/templates/rss/scheduled_hearings.xml.j2`, with the same `<rss>` and `<channel>` envelope as `rss/upcoming_hearings.xml.j2` (the same `<title>`, `<link>`, `<language>`, `<lastBuildDate>` and `atom:link`), a `<description>` of "Public hearings the <city> council has scheduled, by the date of the hearing.", and one `<item>` per entry: `<title>` is the entry's title, a comma, and its date as "November 24, 2026" ("Zoning hearing, November 24, 2026"); `<link>` and `<guid isPermaLink="true">` are both the coming-up page's absolute address followed by `#` and the part of the entry's `uid` before its `@` (the `id` M7 gave the article); `<description>` is a CDATA section, passed through the `cdata_safe` filter as the other feed's is, holding the detail lines and then each link as "label: absolute address", one per line. There is no `<pubDate>`: the other template puts the meeting's date there, a date in the future, and an entry does not carry the day its hearing was first read; a feed reader without one orders items by when it first saw them, which is the true order of news here. Cancellation does not arise: a hearing entry is never `cancelled` (M6 marks meetings only), and a hearing whose every setting item sits on a cancelled or hidden meeting is already left out by `hearings.list_upcoming`.

Re-seat the four tests that seed a "hearing" title under Birmingham and expect the title test to find it in Birmingham's feed, which is no longer what Birmingham's feed does. In `tests/integration/test_f5_data_debt.py` add a fixture `legacy_bag`, written as `bag` is but for the slug `mobile` (a city the migrations seed, which carries no `coming_up` key), and change `test_upcoming_hearings_rss_renders_valid_xml`, `test_upcoming_hearings_rss_unique_guids_for_multi_hearing_meeting` and `test_upcoming_hearings_rss_meeting_title_fallback_unique_guid` to seed through `legacy_bag` and ask for `/al/mobile/upcoming-hearings.rss`; their assertions are otherwise unchanged. In `tests/integration/test_admin_hide_meeting.py`, `test_upcoming_hearings_rss_excludes_hidden` is changed the same way, with a bag made by that file's `_bag_for("mobile")`; if `_bag_for` cannot make one for Mobile the session records why in the Decision Log and gives the test its own seeding. These four still prove the old path, now on a city that still takes it. No other test in either file is changed: the ones that call `query.list_upcoming_hearings` directly do not go through the route, and the cache-header, unknown-city and four-city smoke tests assert a status and well-formed XML, which both paths give. Before changing them, the session runs the four as they stand, after the route change, and records which fail and with what message; that is this milestone's evidence that the tests can see the change.

Add `tests/web/test_hearings_rss_flagged.py`, using M7's seeding helper, `coming_up._today` monkeypatched to 2026-11-16, and `public._rss_cache.clear()` before each request. Its cases: with a zoning hearing seeded for 2026-11-24 under Birmingham, the feed parses as XML and has one `<item>` whose `<title>` is "Zoning hearing, November 24, 2026" and whose `<link>` ends `/al/birmingham/coming-up/#hearing-<the hearing's id>`, and whose `<description>` holds the seeded city agenda address once, as seeded, and the item's page as an address beginning `http://`; the number of `<item>` elements equals the number of articles with `data-entry-kind="hearing"` on the page fetched in the same test, and the set of `<guid>` texts has that many members; a Birmingham meeting titled "COMINGUP_TEST_ Public Hearing on a plan", dated 14 days after the real today (the old query reads the server's date), with no hearing stored, is in no `<item>` of Birmingham's feed; and the same title seeded under Mobile is in an `<item>` of `/al/mobile/upcoming-hearings.rss`. The last two cases together are what tells the two paths apart: under the old path the Birmingham title would be listed, and under a route that took the new path for every city the Mobile title would not.

Result: one address, the better list for the city that has one. Proof: the acceptance in Validation.

### M9: the record

Create `docs/specs/coming-up.md`, in the present tense, owning: the two addresses and the gate; the window; each kind's sources, inclusion rules and what an entry shows; the merge rule and the cancelled rule; the hearing reader's rules (trigger, the three date forms and the correction, the kinds, the subject key, `same_hearing`), what it does not read (a date cut from a stored title, a hearing with no dated resolution, a hearing moved by a later resolution without the bracketed note), and where they are stored; the schedule file's format, the loader's refusals, the PDF cross-check, how a later revision or a 2027 schedule is saved (fetch the PDF into `sources/`, update the README row, edit the YAML and its `source` block, add a `checked` entry, regenerate the reading sheet, run `./tools/verify`) and that after the schedule's year the neighborhood section is empty until that is done; the feed's properties and UIDs; and how to check each. By the revision of 2026-11-16 it also owns: how a cancelled meeting is shown and the sentences that name the source; the labels and their tokens; the "How to attend" block and which entries have one; the feed's two parameters, their vocabularies, and the 404 for an unknown value; the three ways to subscribe and how the `webcal` and Google addresses are built; and what `/al/<slug>/upcoming-hearings.rss` returns for a flagged city (the hearing entries, their titles, links and guids, no `<pubDate>` and why) against what it returns for any other. Add its row to the index in `docs/specs/index.md`.

Edit the specs whose behaviour changed, each where it already owns the fact: `docs/specs/city-page.md`, the "Recent meetings" paragraph (the link to the page and the feed link on the "Follow:" line, both on a flagged city only, with the gate's owner named as the new spec; and one clause that "upcoming hearings (RSS)" on a flagged city lists scheduled hearings, the new spec owning what that means); `docs/specs/crawlers.md`, the sitemap paragraph (the per-city meetings file lists the coming-up page for a city that has one); `docs/specs/meeting-types.md`, "The city calendar" (one sentence: the table's rows are also read by the coming-up page, which keeps only titles `classify_event` reads, and the new spec owns how); `docs/specs/operations.md`, "Railway specifics" (the hearings paragraph: ingest's step keeps them current with no task of its own, and the backfill is `scripts/backfill_hearings.py --city birmingham --since 2025-01-01`, dry run first, from a laptop with `DATABASE_URL` set to `DATABASE_PUBLIC_URL`).

Add to `ARCHITECTURE.md`: in Enrichment's "Owns", the hearing reader; in Services' "Owns", the hearings store, the neighborhood schedule loader, and the coming-up entries, each with its spec. Add one map line to `AGENTS.md` for `content/coming-up/` pointing at the new spec, keeping the file within its length rule. Add a row to the surfaces table of `docs/birmingham/06-reader-surfaces.md` for the page and the feed, linking the spec rather than restating it, and a line in `docs/birmingham/01-sources.md` for the schedule PDF as a source.

Graduate the durable decisions to `docs/decisions/`, numbered by the rule in Identifiers, in the format of `docs/decisions/DECISION_FORMAT.md`: how one hearing is told from another and why not by case number; why a hearing with no readable date is not shown; the merge and cancelled rules for meetings and whose time is printed; that neighborhood dates are computed from the printed rule alone with the two undated associations named; and that extraction is a step of ingest.

Add debt rows to `docs/DEBT.md`, ids by the same rule: the operator's steps after the merge, in the order Validation gives them, with "the pull request merges" as the trigger; the two notions of an upcoming hearing (since M8b: a flagged city's RSS feed reads the stored hearings, and every other city's still lists any upcoming agenda line containing "hearing", through `query.list_upcoming_hearings`, whose docstring calls the test a first version), trigger "a second city is given `coming_up`, or the next change to `query.list_upcoming_hearings`"; a note on a neighborhood meeting whose computed date is a city holiday, not built because no holiday list published by the city was found on 2026-11-16, trigger "a city-published holiday list is found, or a reader reports a listed meeting that was not held on a holiday"; the city's other bodies that hold public hearings and are on neither stored source (the Zoning Board of Adjustment, the Design Review Committee, the Birmingham Planning Commission), for which no 2026 schedule published by the city was found on 2026-11-16 (the one found is the Zoning Board's for 2023), trigger "a current city-published schedule for any of the three is found"; hearings the reader cannot date or follow (dates cut from 256-character titles, weed-lot resolutions before May 2026, a hearing moved by a later resolution, a hearing set on an agenda whose meeting row is a leftover `event-` row, two different weed-lot resolutions that set one day and list the same number of properties and so are stored as one hearing, and a cut title with under 90 characters of subject shown as a second entry for a hearing already listed), trigger "a reader or the operator reports a missing, stale, or doubled hearing"; `meeting_types._is_live` called from a second service under a private name, trigger `D119`'s; calendar events that are meetings and whose titles `classify_event` does not read (a work session), trigger "such an event is seen on the city's calendar"; the schedule's year ending 2026-12-31 with no 2027 file, trigger "the city publishes a 2027 schedule, or 2027-01-01"; the schedule loaded on first use rather than at start, trigger `D34`'s payment for `web/__init__.py`; the feed marking a cancelled meeting by its title alone with no `STATUS:CANCELLED` line, because nobody could say on 2026-11-16 which calendar programs hide a marked event, trigger "a cancelled meeting is in the feed and is looked at in Google Calendar and Apple Calendar". Append to the `D131` row that this plan re-deferred it and why (Decision Log). Do not move this plan to `plans/completed/` and do not write the closing retrospective: the retro stage does both.

## Concrete Steps

Every command is run from the worktree root, `/home/thinkdarrell/docket-pub/.claude/worktrees/birmingham-coming-up`, with its own `venv/`.

Each session begins and ends with the full check:

    ./tools/verify

As observed by the author on 2026-11-16 on the branch as cut from `origin/main` (commit 608e912), it ended:

    verify: test-db ... ok (0s) postgresql://docket:docket_dev@localhost:5432/docket_test_1126d0ec
    verify: unit+web+services ... ok (125s)
    verify: integration ... ok (113s)
    verify: judge-fixtures ... ok (0s)
    verify: workflows ... ok (0s)
    verify: transcriber ... ok (11s)
    verify: plans ... ok (0s)
    verify: all 6 checks passed in 249s.

and the fast tiers' own summary line read `2888 passed, 5 skipped, 4 xfailed, 2 warnings in 122.20s`. That run shared the machine with the author's other commands, so 249 seconds is not the usual time. The plan file did not exist yet, so the `plans` check had no active plan to read.

To run one test file by hand (bare `pytest` is refused by `tests/conftest.py` in this worktree, whose `.env` names `docket_db`):

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_hearing_reader.py -q -p no:cacheprovider
    tools/test-db --drop

This form is the one `docs/specs/operations.md` gives; the author ran `./tools/verify`, which uses the same pieces, and did not run this line itself, since the file it names does not exist yet.

The production dry run of M3, read-only. The first two lines are the form the author ran on 2026-11-16 from this worktree; it reached production and returned rows (`railway status` printed the project, and the `psql` statements returned the counts in Context). `PGOPTIONS` makes every transaction of the session read-only on the server's side, so a mistake in the script cannot write:

    export PGURL="$(railway variables --service docket-web --kv 2>/dev/null | grep '^DATABASE_PUBLIC_URL=' | cut -d= -f2-)"
    PGOPTIONS='-c default_transaction_read_only=on' psql "$PGURL" -X -A -t -c "SELECT count(*) FROM agenda_items"
    DATABASE_URL="$PGURL" PGOPTIONS='-c default_transaction_read_only=on' venv/bin/python scripts/backfill_hearings.py --city birmingham --since 2025-01-01 --dry-run
    DATABASE_URL="$PGURL" PGOPTIONS='-c default_transaction_read_only=on' venv/bin/python scripts/backfill_hearings.py --city birmingham --since 2025-01-01 --until 2026-11-16 --dry-run

The third and fourth lines have not been run: the script does not exist. Never print `$PGURL`, never write it to a file, and never run the script against it without `--dry-run`; the backfill itself is the operator's step. Expected, as a design assumption to be checked and not as evidence: the fourth line's totals near `matched=78 dated=67 undated=11`, a hearing line `hearing 2026-11-17 vacation items=62830,62881`, and a hearing line `hearing 2026-11-17 weed_lots items=62831,62882`.

The author's SQL for the 78, 66 and 9, so the comparison in M3 can name its terms: over Birmingham items of meetings dated 2025-01-01 or later, with `t` the title after `regexp_replace(title, E'[\n\t ]+', ' ', 'g')`, "matched" is `t ~* '(setting|to set|providing for) (a|the) public (show cause )?hearing'`, and "dated" is a non-null `regexp_match(t, '(?:setting|to set|providing for) (?:a|the) public (?:show cause )?hearing,? (?:on |for )?((?:January|February|March|April|May|June|July|August|September|October|November|December) [0-9]{1,2},? [0-9]{4})', 'i')`. That SQL knows only the first date form, which is why it dates 66 and the reader should date 67 (item 730).

Fetching the PDF in M4 (one request):

    mkdir -p content/coming-up/birmingham/sources
    curl -sS -o 'content/coming-up/birmingham/sources/2026_NA_Meeting_Schedule_rev._2-3-2026.pdf' -w '%{http_code} %{content_type} %{size_download}\n' 'https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/s3fs-public/2026-02/2026_NA_Meeting_Schedule_rev._2-3-2026.pdf'
    sha256sum content/coming-up/birmingham/sources/*.pdf

The author ran the `curl` line with a scratch path in place of the repository path and it printed `200 application/pdf 155273`.

The reading sheet in M5:

    venv/bin/python scripts/coming_up_reading_sheet.py birmingham > docs/runbooks/coming-up-reading-birmingham.md

Commits: every commit of a milestone session also changes this plan file (decision `0037`), hooks are never bypassed, and a Progress line is ticked by changing `- [ ]` to `- [x] (YYYY-MM-DD HH:MMZ)` and nothing else on the line.

## Validation and Acceptance

Each milestone's acceptance is what its session observes in this worktree. In every milestone, `./tools/verify` ends with `verify: all 6 checks passed in <N>s.`, its `plans` line reads `ok`, and the fast tiers or the integration tier report more tests passed than the session's own first run of the day did, with none failed; the session records both summary lines. A count of tests is not promised here, because a parametrized test collects one test per case.

M1. The single-file command in Concrete Steps, on `tests/unit/test_hearing_reader.py`, ends with a line of the form `<n> passed` and no failure, and the file asserts every row of the table of expected readings and the four pair cases. `grep -c "docket" src/docket/enrichment/hearings.py` may print any number; what must hold is the test that the module imports nothing from `docket`. Before the reader was written the session ran the test file and saw it fail on import; it records that line.

M2. `DATABASE_URL=$(tools/test-db) venv/bin/python -m docket.migrations.runner --status` lists the hearings migration as applied, and `tools/test-db --drop` follows. The migration test passes up, down, and up again. `tests/services/test_hearings_store.py` passes, and the session records, from a run of it with `-v`, the names of the test for two items making one hearing and the test for the withdrawn, hidden, and cancelled links.

M3. `tests/integration/test_ingest_hearings.py` and `tests/unit/test_backfill_hearings_script.py` pass. `venv/bin/python scripts/backfill_hearings.py --city birmingham` (no `--since`) exits non-zero and names the missing bound. The two production dry-run lines of Concrete Steps ran, and Artifacts and Notes holds their totals lines, the hearing lines for items 62830 with 62881 (one hearing dated 2026-11-17, two items) and 62831 with 62882 (one `weed_lots` hearing, 212), and the paragraph of differences against 78, 67, 11 and against the operator's 71 and 9, with no difference left unexplained. `git status --porcelain` prints nothing: the dry run's output was saved outside the repository.

M4. `sha256sum` of the saved PDF prints the digest the YAML and the README record. `tests/unit/test_neighborhood_schedule.py` passes, including the 99-association count and the cross-check against the PDF's table; the session records how many exceptions the cross-check's dict holds and each one's reason. Changing one association's `rule_text` by a letter in a scratch copy makes the cross-check fail, and changing the YAML's `sha256` by a digit makes the loader raise `ScheduleError`; the session records both failures' messages and restores the file.

M5. The hand-worked dates pass; the 2026 count is asserted (1,158, or the corrected figure with its arithmetic recorded); `docs/runbooks/coming-up-reading-birmingham.md` exists, names the content's commit, and has one tick-box line per association (`grep -c '^- \[ \]' docs/runbooks/coming-up-reading-birmingham.md` prints the association count, 99 unless M4 recorded otherwise).

M6. `tests/services/test_coming_up.py` passes; the session records, from `-v`, the names of the merged-meeting test, the cancelled-pair tests, the giveaway test, and the `filter_entries` test, and the number of slugs `association_feeds("birmingham")` returned.

M7. `tests/web/test_coming_up_page.py` passes; the session records the three status codes it asserts (200 for Birmingham, 404 for `mobile`, 404 for an unknown city) and the entry count the page and the service agreed on in the count test, and the eight contrast ratios of the labels, each 4.5 or more, with the two colours behind each. `grep -n "db_cursor\|db()" src/docket/web/public.py` prints nothing new against `origin/main` (the route executes no SQL): `git diff origin/main -- src/docket/web/public.py | grep -c "^+.*db_cursor\|^+.*db()"` prints `0`.

M8. `tests/unit/test_ics.py` and `tests/web/test_coming_up_feed.py` pass; the session records the event count and the entry count the feed test found equal, and the first three lines of the feed body from that test's seeded rows (`BEGIN:VCALENDAR`, `VERSION:2.0`, the `PRODID` line). It also records the three event counts the `?kind=` requests returned and that they sum to the whole feed's, and the two 404s for an unknown kind and an unknown association.

M8b. `tests/web/test_hearings_rss_flagged.py` passes, and the session records the item count and the hearing-article count its count test found equal. The four re-seated tests pass, and the plan holds the record of which of them failed, with their messages, when run unchanged after the route change. `git diff origin/main --stat -- src/docket/services/query.py src/docket/web/templates/rss/upcoming_hearings.xml.j2` prints nothing.

M9. `docs/specs/coming-up.md` exists and `docs/specs/index.md` lists it; each of the four edited specs names what it gained (`grep -l "coming-up" docs/specs/city-page.md docs/specs/crawlers.md docs/specs/meeting-types.md` prints three paths, and `grep -c "backfill_hearings" docs/specs/operations.md` prints at least 1); `docs/DEBT.md` holds a row whose trigger is "the pull request merges" listing the operator's steps below in order, and the `D131` row names this plan; the milestone edits documents only: `git diff --stat <the commit the session started on> -- src/ tests/ scripts/ content/` prints nothing; `wc -l AGENTS.md` stays at or under 100. This plan file is still under `plans/active/`.

The operator's steps, none of which a milestone session takes and none of which is part of a Progress line. Machine: the Legion. Folder: the WSL checkout. They go into the M9 debt row in this order.

1. Before merging: read `docs/runbooks/coming-up-reading-birmingham.md` against the PDF (in the pull request, or the saved file), tick the rows, correct any row in the YAML through a commit on the branch, and add a `checked` entry with your name and the date.
2. Merge pull request #181 (Granicus start times) first if it is still open, so that a council meeting only the video site lists does not print a time two hours late.
3. Merge this plan's pull request; deploy `docket-web` and `worker` from a clean `main` with `scripts/deploy.sh`. The web service applies the hearings migration at start.
4. Dry run, then the backfill, with `DATABASE_URL` set to `DATABASE_PUBLIC_URL`: `venv/bin/python scripts/backfill_hearings.py --city birmingham --since 2025-01-01 --dry-run`, read the output against M3's record, then the same line without `--dry-run`. (Added by M3's second session, 2026-11-17: before the line without `--dry-run`, run the two read-only lines under "M3: the comparison, and what is still owed" in Artifacts and Notes and see `same ids`, or read each id they print; M3 was ticked without that check because the harness refused it to the session.) Expect `created=` near the dry run's `hearings=` and, on a second run, `created=0`. A copy of `upcoming-hearings.rss` fetched between the deploy and the backfill is held in the web process for up to an hour and then replaced; nothing needs restarting.
5. Check, read-only: `SELECT h.id, h.hearing_date, h.kind, array_agg(i.agenda_item_id ORDER BY i.agenda_item_id) FROM public_hearings h JOIN public_hearing_items i ON i.hearing_id = h.id WHERE i.agenda_item_id IN (62830, 62881) GROUP BY 1, 2, 3;` prints one row dated 2026-11-17 with both items.
6. Open `https://docket.pub/al/birmingham/coming-up/` in a browser at about 390 and 1280 pixels wide: the next council meeting appears once with the city calendar's time; a day's neighborhood meetings open and close under their summary; nothing overflows sideways. `curl -sI https://docket.pub/al/birmingham/coming-up.ics` shows `content-type: text/calendar`, and subscribing to that address in a calendar program shows the entries on their days. `https://docket.pub/al/mobile/coming-up/` is 404.
7. Added by the revision of 2026-11-16. On the same page: each entry's coloured label is readable at both widths; a neighborhood meeting with call-in details shows them under "How to attend". Click "Subscribe in your calendar" on a phone or a desktop with a calendar program and see it offer to subscribe; click "Add to Google Calendar" signed in to a Google account and see Google offer to add the calendar (if Google refuses the address, open an issue: the remedy is removing that one link); open "One neighborhood association", subscribe to one, and see only its meetings, and note how the calendar program draws a meeting that has a start and no end (the schedule gives no end time and the feed invents none; if a program draws it badly, open an issue saying which). `curl -s 'https://docket.pub/al/birmingham/coming-up.ics?kind=hearing' | grep -c BEGIN:VEVENT` prints the number of hearings on the page, and `curl -s -o /dev/null -w '%{http_code}\n' 'https://docket.pub/al/birmingham/coming-up.ics?kind=council'` prints `404`.
8. Same revision. `curl -s https://docket.pub/al/birmingham/upcoming-hearings.rss | grep -c '<item>'` prints the number of hearings on the page (the feed is cached for an hour, so after the backfill wait that long or compare then), and `curl -s https://docket.pub/al/mobile/upcoming-hearings.rss | head -3` still opens with the XML declaration and `<rss`.

## Idempotence and Recovery

The migration is additive and written with `IF NOT EXISTS`; its down drops only what it made and removes only its own metadata key. `refresh_hearings` can be run any number of times: links are upserted on the item, a stored hearing is found again by the same rule that made it, and a hearing with no link is deleted, so a second run changes nothing and a run after a rule change moves links rather than doubling them. If the backfill is interrupted, running it again completes it. To undo the backfill entirely: `DELETE FROM public_hearings WHERE municipality_id = (SELECT id FROM municipalities WHERE slug = 'birmingham')`, one statement, whose cascade removes the links; the page then shows no hearings and ingest refills the last 120 days on its next run. To turn the page, the feed, and ingest's step off without a deploy: `UPDATE municipalities SET metadata = metadata - 'coming_up' WHERE slug = 'birmingham'`; the page and feed then answer 404 and the city page's link disappears within its five-minute cache. The same statement returns `/al/birmingham/upcoming-hearings.rss` to the title test within its 60-minute cache, since M8b's branch reads the same key; M8b's test of a city without the flag is the test of that state, so no row state this statement leaves is untested.

Every test that seeds rows prefixes them and deletes them before and after, so a killed run is tidied by the next. Fetching the PDF again overwrites the same file; if the bytes differ from the recorded digest the loader refuses until the YAML and the README are updated, which is the intended alarm. If a session runs short of context, it splits its Progress line in place (completed and remaining), records the split in the Decision Log, commits, and stops.

## Artifacts and Notes

### The fixture titles

The 25 objects of `tests/fixtures/hearings/birmingham_titles.json`, one per line here, exactly as production returned them on 2026-11-16 (`title` is the first 420 characters of the stored title; `len` is the stored title's length, so `len` over 420 means the title is cut here, and `len` of 254 to 256 with a marker at the start means production itself stores it cut). In the file they form one JSON list.

    {"id": 730, "len": 256, "title": "P\t\tITEM 27. \nA Resolution to set a public hearing on the application of Harvest Solutions, LLC to site a new solid waste treatment facility at 4400 7th Avenue North, Birmingham, AL 35212, on the 7th day of April, 2026, in the Council Chambers, Third Floor,"}
    {"id": 746, "len": 256, "title": "P\t\tITEM 43.\nA Resolution setting a public hearing to consider a temporary suspension on data centers within the City to be held at the regular meeting of City Council to be held in the Council Chambers in the City Hall in Birmingham, Alabama on March 3, 20"}
    {"id": 1152, "len": 256, "title": "ITEM 30. A Resolution setting a public hearing February 10, 2026, to consider the adoption of a resolution assenting to the vacation of 36,000 square feet of the right of way that is located parallel to and between 28th Street N. and 30th Street N. and  pe"}
    {"id": 1153, "len": 255, "title": "ITEM 31.\nA Resolution setting a public hearing February 10, 2026, to consider the adoption of a resolution assenting to the vacation of 1,185 square feet of the right of way that is located parallel to and between 22nd Street S. and Arlington Crescent and"}
    {"id": 1680, "len": 256, "title": "P\t\tITEM 25.\nA Resolution setting a public hearing December 9, 2025, to consider the adoption of an Ordinance \"TO AMEND THE ZONING DISTRICT MAP OF THE CITY OF BIRMINGHAM\" (Case No. ZAC2025-00013) from D-5 (Multiple Dwelling District) to I-1 (Light Manufactu"}
    {"id": 1681, "len": 255, "title": "P      ITEM 26.  \nA Resolution setting a public hearing December 9, 2025, to consider the adoption of an Ordinance \"TO AMEND THE ZONING DISTRICT MAP OF THE CITY OF BIRMINGHAM\" (Case No. ZAC2025-00022) to pre-zone territory proposed for annexation from B-2"}
    {"id": 2116, "len": 256, "title": "P\t\tITEM 35. [CHANGE HEARING DATE FROM OCTOBER 28, 2025 TO NOVEMBER 4, 2025]\nA Resolution setting a public hearing October 28, 2025 to consider the adoption of an Ordinance \"TO AMEND THE ZONING DISTRICT MAP OF THE CITY OF BIRMINGHAM\" (Case No. ZAC2025-00019"}
    {"id": 3131, "len": 256, "title": "P\t\tITEM 38.\nA Resolution setting a public hearing July 15, 2025 to consider the adoption of an Ordinance on a proposed text amendment to the City's Zoning Ordinance, Ordinance No. 15-133, as amended, to include the addition of several terms that were previ"}
    {"id": 3167, "len": 256, "title": "ITEM 22.\nA Resolution to set a public hearing to consider the closure of 20thAvenue South near its intersection with Richard Arrington, Jr. Boulevard South to vehicular traffic to control traffic flow from neighboring businesses. (Submitted by the City Att"}
    {"id": 3238, "len": 102, "title": "ITEM 1.\nA Resolution setting a public hearing in the Council Chambers on the Mayor's proposed budgets."}
    {"id": 3296, "len": 255, "title": "(ph)\tITEM 51.\nA Resolution setting a public show cause hearing to consider the matter of revoking the business license issued to Happy Hour Hangout at 2417 Avenue C, Birmingham, Alabama 35218. Said hearing shall be held at the Council's regular meeting in"}
    {"id": 3297, "len": 256, "title": "P ITEM 52. \nA Resolution, amending Resolution No. 796-25, adopted by Council May 13, 2025, setting a public hearing June 10, 2025, to consider the adoption of a resolution assenting to the vacation of the following: 26,875 square feet of the right of way t"}
    {"id": 3339, "len": 254, "title": "P\t\tITEM 24.\nA Resolution setting a public hearing June 10, 2025, to consider the adoption of a resolution assenting to the vacation of the following: 26,875 square feet of the right of way that is located parallel to and between 10th Court North and 10th"}
    {"id": 4412, "len": 256, "title": "CONSENT\t\tITEM 20.\nA Resolution finding that the following ninety-nine (99) properties have noxious or dangerous weeds growing thereon declaring said properties to be a public nuisance and providing that notice shall be posted on each of said properties and"}
    {"id": 4425, "len": 256, "title": "P\t\tITEM 19. \nA Resolution setting a public hearing February 4, 2025, to consider the adoption of an Ordinance \"TO AMEND THE ZONING DISTRICT MAP OF THE CITY OF BIRMINGHAM\" (Case No. ZAC2024-00011) to change zone district boundaries from MU-H, Mixed-Use High"}
    {"id": 58869, "len": 256, "title": "P ITEM 32\nA Resolution setting a public hearing June 9, 2026, to amend the City of Birmingham Zoning Ordinance, Title 1 \"General Provisions\" (Ord No. 15-133, as amended); filed by the Department of Planning, Engineering and Permits (Case No. ZAC2026-00001)"}
    {"id": 58878, "len": 94, "title": "A Resolution setting a public hearing in the Council Chambers on the Mayor’s proposed budgets."}
    {"id": 59096, "len": 64, "title": "PUBLIC HEARING ON THE PROPOSED 2026-2027 FISCAL YEAR CITY BUDGET"}
    {"id": 62182, "len": 303, "title": "A Resolution setting a public hearing November 17, 2026, to consider the closure of approximately 900 feet of Woodcrest Road South and Warick Court South to the intersection of 21st Way South and 15th Avenue South, Birmingham, due to the hazardous deterioration condition of the roadway. [First Reading]"}
    {"id": 62830, "len": 714, "title": "A Resolution setting a public hearing November 17, 2026, to consider the adoption of a resolution assenting to the vacation of 23,277 square feet of the right of way that is located parallel to and between 1st Avenue South and 2nd Avenue South and perpendicular to and between 28th Street South and 32nd Street South, and located at 3100 2nd Avenue South, Birmingham, on behalf of Marx Management, Sloss #2 Shaw, LLC, Sl"}
    {"id": 62882, "len": 502, "title": "A Resolution finding that the following two hundred twelve (212) properties have noxious or dangerous weeds growing thereon declaring said properties to be a public nuisance and providing that notice shall be posted on each of said properties and notice sent by certified mail to the last person assessing these properties for state taxes and further providing for a public hearing November 17, 2026, to hear and conside"}
    {"id": 63046, "len": 591, "title": "A Resolution setting a public hearing November 24, 2026, to consider the adoption of an Ordinance “TO AMEND THE ZONING DISTRICT MAP OF THE CITY OF BIRMINGHAM” (Case No. ZAC2026-08005) to change zone district boundaries from QMU-H (Qualified Mixed-Use High District) to QC-2 (Qualified General Commercial District), in order to allow for a new church campus, filed by C. Randall Minor, applicant, on behalf of the propert"}
    {"id": 63108, "len": 374, "title": "A Resolution setting a public hearing December 8, 2026, to consider the adoption of an Ordinance repealing Title 2 and Title 3 of the Zoning Ordinance of the City of Birmingham, Ordinance No. 15-133, as amended, removing obsolete provisions that no longer apply to properties within the corporate boundaries of the City of Birmingham. Case No. ZAC2026-08010. [First Reading]"}
    {"id": 63109, "len": 505, "title": "A Resolution finding that the following one hundred thirty-six (136) properties have noxious or dangerous weeds growing thereon declaring said properties to be a public nuisance and providing that notice shall be posted on each of said properties and notice sent by certified mail to the last person assessing these properties for state taxes and further providing for a public hearing December 8, 2026, to hear and cons"}
    {"id": 63166, "len": 506, "title": "A Resolution finding that the following one hundred thirty-six (136) properties have noxious or dangerous weeds growing thereon declaring said properties to be a public nuisance and providing that notice shall be posted on each of said properties and notice sent by certified mail to the last person assessing these properties for state taxes and further providing for a public hearing December 15, 2026, to hear and con"}

### Expected readings

For each fixture id: the hearing date (or "no date"), the kind, and the property count where there is one. "None" means `read_hearing` returns `None`.

    730     2026-04-07   other
    746     no date      other
    1152    2026-02-10   vacation
    1153    2026-02-10   vacation
    1680    2025-12-09   zoning
    1681    2025-12-09   zoning
    2116    2025-11-04   zoning
    3131    2025-07-15   zoning
    3167    no date      vacation
    3238    no date      budget
    3296    no date      other
    3297    2025-06-10   vacation
    3339    2025-06-10   vacation
    4412    None
    4425    2025-02-04   zoning
    58869   2026-06-09   zoning
    58878   no date      budget
    59096   None
    62182   2026-11-17   vacation
    62830   2026-11-17   vacation
    62882   2026-11-17   weed_lots   212
    63046   2026-11-24   zoning
    63108   2026-12-08   zoning
    63109   2026-12-08   weed_lots   136
    63166   2026-12-15   weed_lots   136

How the less obvious rows come out under the rules of M1, worked by the author. 730: the trigger is "to set a public hearing"; what follows is "on the application of", so the first form finds nothing; the second finds "on the 7th day of April, 2026"; no kind word fits, so `other`. 746: the first two forms find nothing and the third finds "to be held ... on March 3, 20", whose year is cut to two digits, so no date. 2116: the first form reads October 28, 2025, the text holds "CHANGE HEARING DATE FROM OCTOBER 28, 2025 TO NOVEMBER 4, 2025", and the date read equals the first, so the date is November 4, 2025. 3297: "amending Resolution No. 796-25, adopted by Council May 13, 2025" comes before the trigger, so May 13 is never considered; the date after the trigger is June 10, 2025. 3167: "closure of" makes it `vacation`, and it has no date. 4412: a weed-lot title cut before "providing for a public hearing", so no trigger. 59096: the words "PUBLIC HEARING" with no trigger before them. 63108: "Zoning Ordinance" makes it `zoning`.

The pair cases, with keys taken from the readings. 3297 and 3339 are the same hearing: 3297's key is 101 characters and 3339's begins with it. 1152 and 1153 are different: both keys begin `toconsidertheadoptionofaresolutionassentingtothevacationof` and continue `36000` and `1185`. 1680 and 1681 are different: the keys part at the case numbers, `zac202500013` and `zac202500022`. 62182 and 62830 are different: `toconsidertheclosureof...` and `toconsidertheadoptionof...`. Under the other rule one might have chosen, equal case numbers, 3297 and 3339 would be two hearings, since neither stored title reaches its case number; the test asserts that neither title contains "Case No".

### Dates worked by hand

Counted on a 2026 calendar by the author and checked with Python's `calendar` module on 2026-11-16 (November 1, 2026 is a Sunday; December 1, 2026 is a Tuesday).

    Acipco-Finley      first Wednesday     November 4 and December 2, 2026
    Brown Springs      third Thursday      November 19 and December 17, 2026
    Huffman            fourth Monday       November 23 and December 28, 2026
    Gate City          second Monday       December 14, 2026
    Jones Valley       first Friday        January 2 and May 1, 2026
    East Birmingham    fourth Monday       February 23, 2026
    Overton            first Tuesday, even months only: October 6 and December 1, 2026, and no date in November 2026
    Glen Iris          no dates
    Bridlewood         no dates

The times that go with them, from the schedule: Acipco-Finley 17:30, Brown Springs 18:00, Huffman 19:00, Gate City 16:00 ("@4 p.m."), Jones Valley 16:00, East Birmingham 18:00, Overton 18:00. West Brownsville's "@ 10: 00 a.m." is 10:00.

### What M3 will add here

The production dry run's totals lines, hearing lines, and the comparison paragraph. As authored, none exists.

Since 2026-11-17 they exist, further down: "M3: the production dry run, as the second session read it" and "M3: the comparison, and what is still owed".

### M1: what the session observed

Session of 2026-11-17 (UTC), Claude, started on commit df07111 with a clean tree. Every line below was printed by a command the session ran in this worktree.

Starting state, `./tools/verify`, before any edit:

    2888 passed, 5 skipped, 4 xfailed, 2 warnings in 122.52s (0:02:02)
    1030 passed, 2 warnings in 111.23s (0:01:51)
    judge fixtures: 12 of 12 passed
    134 passed, 1 warning in 10.03s
    verify: all 6 checks passed in 247s.

The fixture was written by a scratch script that read the 25 indented JSON lines of "The fixture titles" out of this file and checked, for each, that the title's length is the smaller of `len` and 420; all 25 held.

Before the reader existed (2026-11-17 03:45Z), `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_hearing_reader.py -q -p no:cacheprovider` ended:

    37 failed, 1 passed, 1 warning in 0.11s

Every failure was `ModuleNotFoundError: No module named 'docket.enrichment.hearings'`; the one pass is the test that the fixture holds the 25 ids of the table. The reader is imported inside each test (as `skills/plan-execute/SKILL.md` asks), so the before state is 37 tests failing and not one collection error; Validation's words "fail on import" are met in that form. The commit that holds the tests failing is the one that adds this paragraph.

With `src/docket/enrichment/hearings.py` written, the same command ended, on its first run against the reader:

    38 passed, 1 warning in 0.03s

The removal check (`skills/plan-execute/SKILL.md`: tests that pass on the first run of the code have not yet shown they test it). A scratch script outside the repository made 62 copies of the reader's source, each with one clause taken out or weakened, loaded each copy in place of the module through a pytest plugin (the committed file was never edited), and ran the test file against it. First pass, against the 38 tests of commit 5ca396c:

    removals tried=62 failed a test=31 survived=31

The 31 that no test could tell from the rule: collapsing whitespace; "the" in the trigger; the trigger's and the first date form's ignoring of case; the trigger beginning at a word; the trigger being the first match; the optional comma in a date; a year of four digits and no more; "on" between the trigger and the date; the second and the third date forms reading only after the trigger; the third form's full stop or semicolon; the third form's "to be held" clause; the second form tried before the third; the correction applying only when the date read equals the first of the two; "zone district" and "rezon" in the zoning test; "vacation of" and "right of way" in the vacation test; the three orders of the kind tests (weed lots before zoning, zoning before vacation, vacation before budget); the property count being the first; the `weeds:<count>` key, and its being for weed lots alone; bracket groups removed from the key; the cut at "(Submitted by", at "(Recommended by", and at either; equal keys in `same_hearing`; and the shorter key opening the longer and not merely lying inside it. Twenty-four tests (25 collected, one being parametrized over the full stop and the semicolon) were then added under the comment "rules pinned after the removal check" in `tests/unit/test_hearing_reader.py`, none of them in commit 5ca396c; three read fixture titles (62182's "[First Reading]", 3167's "(Submitted by", the three weed-lot keys) and the rest read constructed sentences. Second pass, same 62 removals, against the 62 tests:

    62 passed, 1 warning in 0.06s
    removals tried=62 failed a test=62 survived=0

Finished state, `./tools/verify`, on commit 04b9d2c with a clean tree:

    2950 passed, 5 skipped, 4 xfailed, 2 warnings in 122.96s (0:02:02)
    1030 passed, 2 warnings in 112.29s (0:01:52)
    judge fixtures: 12 of 12 passed
    134 passed, 1 warning in 9.82s
    verify: plans ... ok (0s)
    verify: all 6 checks passed in 248s.

The fast tiers went from 2888 passed to 2950, the 62 tests of the new file, with none failed; the integration tier is unchanged at 1030.

Keys the tests observed, each asserted: item 3297's is 101 characters and item 3339's opens with it; item 2116's is 100 characters, ends `zac202500019`, and holds no `november`; item 1680's opens with the 82-character zoning wording followed by `casenozac202500013`, and item 1681's with the same followed by `casenozac202500022`.

### M2: what the session observed

Session of 2026-11-17 (UTC), Claude, started on commit a394e97 with a clean tree. Every line below was printed by a command the session ran in this worktree.

Starting state, `./tools/verify`, before any edit:

    2950 passed, 5 skipped, 4 xfailed, 2 warnings in 123.47s (0:02:03)
    1030 passed, 2 warnings in 110.47s (0:01:50)
    judge fixtures: 12 of 12 passed
    134 passed, 1 warning in 11.03s
    verify: plans ... ok (0s)
    verify: all 6 checks passed in 249s.

The hearings migration is number 047 (Decision Log, this date, says how the number was chosen). Before the migration and the service existed (2026-11-17 04:05Z), `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_047_migration.py tests/services/test_hearings_store.py -q -p no:cacheprovider` ended:

    5 failed, 1 passed, 1 warning, 45 errors in 1.20s

The five failures are five of the six migration tests (the module `docket.migrations.047_public_hearings` does not exist and `runner.MIGRATIONS` holds no 47, so the tables are not made). The one pass is `test_047_down_removes_the_tables_and_the_key`, which holds of a database the migration never touched: no tables, no key. The 45 errors are every test of the store file, each stopped in the file's own cleanup, which runs before each test and deletes from `public_hearings`, a table that does not exist. The service is imported inside each test, so the file collected. The commit that holds the tests in this state is the one that adds this paragraph.

With `src/docket/migrations/047_public_hearings.py` written and registered in `runner.py`, and `src/docket/services/hearings.py` written, the same command ended, on its first run against them:

    51 passed, 1 warning in 4.19s

The removal check (`skills/plan-execute/SKILL.md`). A scratch script outside the repository made 79 copies, 69 of `src/docket/services/hearings.py` and 10 of `src/docket/migrations/047_public_hearings.py`, each with one clause taken out or weakened, loaded each copy in place of its module through a pytest plugin (no committed file was edited), and ran the two test files against it with `-x`; after each altered migration the two tables were dropped and the committed migration applied again, and the throwaway database was dropped and rebuilt after each pass. First pass, against the 51 tests of commit d747b8e:

    removals tried=79 failed a test=66 survived=13

The 13 that no test could tell from the rule: the SQL title test in `find_readings` being there at all, and its ignoring of case; in `group_readings`, that a short key must open the longer one and not merely lie inside it; in the match against stored hearings, that a stored hearing is matched to one group only (three removals: the test of "not yet matched", and the marking in each of the two passes), that it must be of the group's date, and of the group's kind; the bound on which stored hearings are loaded; `updated_at` being stamped when a stored key is lengthened; the deletion of unlinked hearings being scoped to the city; and in `list_upcoming`, the order by hearing date (hearings are stored in date order by one run, so id order hid it) and the keeping of one hearing's rows together. Nine tests were then added under the comment "rules pinned after the removal check" in `tests/services/test_hearings_store.py`, none of them in commit d747b8e, and three assertions about `created_at` and `updated_at` were added to `test_a_stored_short_key_is_lengthened_when_the_longer_title_arrives`, which is in it. Two of the nine read constructed sentences (one subject, one day, read as kind `other` and, with "there being funds in the budget" before the trigger, as `budget`); the rest read fixture titles. Second pass, same 79 removals, against the 60 tests:

    60 passed, 1 warning in 5.03s
    removals tried=79 failed a test=77 survived=2

The two left are named in Surprises & Discoveries with why nothing can tell them from their absence.

Acceptance, run on commit 38e5df8 with a clean tree. `DATABASE_URL=$(tools/test-db) venv/bin/python -m docket.migrations.runner --status` ended with these lines, and `tools/test-db --drop` followed and exited 0:

      [applied] 46: docket.migrations.046_alignment_stretches
      [applied] 47: docket.migrations.047_public_hearings

The migration test passes up, down, and up again as `tests/integration/test_047_migration.py::test_047_up_down_up PASSED`. From a run of the two files with `-v`, which ended `60 passed, 1 warning in 5.73s` (54 in the store file, 6 in the migration file): the test for two items making one hearing is `tests/services/test_hearings_store.py::test_two_items_on_two_meetings_make_one_hearing_with_two_links`; the tests for the withdrawn, hidden, and cancelled links are `test_list_upcoming_leaves_out_a_hearing_with_no_visible_link[withdrawn]`, `[hidden]` and `[cancelled]` (a hearing whose only link is of that sort is not listed) and `test_list_upcoming_returns_only_the_visible_link_of_a_hearing[withdrawn]`, `[hidden]` and `[cancelled]` (a hearing with one such link and one visible link is listed with the visible one alone). All eight printed `PASSED`.

Finished state, `./tools/verify`, on commit 38e5df8 with a clean tree:

    3004 passed, 5 skipped, 4 xfailed, 2 warnings in 127.15s (0:02:07)
    1036 passed, 2 warnings in 113.70s (0:01:53)
    judge fixtures: 12 of 12 passed
    134 passed, 1 warning in 10.75s
    verify: plans ... ok (0s)
    verify: all 6 checks passed in 255s.

The fast tiers went from 2950 passed to 3004, the 54 tests of the store file; the integration tier from 1030 to 1036, the 6 migration tests; none failed.

### M3: what the session observed

Session of 2026-11-17 (UTC), Claude, started on commit b08c5f8 with a clean tree. Every line below was printed by a command the session ran in this worktree.

Starting state, `./tools/verify`, before any edit. The session kept only the last 25 lines of the run, so the two pytest summary lines of the fast tiers and the integration tier were not seen; what was seen:

    134 passed, 1 warning in 10.71s
    plans: 1 of 1 ok
    verify: unit+web+services ... ok (130s)
    verify: integration ... ok (112s)
    verify: plans ... ok (0s)
    verify: all 6 checks passed in 253s.

The tree was the commit M2's finished run was made one commit before (38e5df8, whose run reported `3004 passed` and `1036 passed`; b08c5f8 changed this plan file alone). Those two figures are M2's record, not this session's observation.

Before the ingest step and the script existed (2026-11-17 04:33Z), `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_ingest_hearings.py tests/unit/test_backfill_hearings_script.py -q -p no:cacheprovider` ended:

    15 failed, 1 passed, 1 warning in 1.09s

Four of the five ingest tests fail (no hearing stored, no "Hearings:" error, no "Hearings:" log line, and `refresh_recent` not called between the meeting-type stage and the vote stage) and all eleven script tests fail with `ImportError: cannot import name 'backfill_hearings' from 'scripts'`. The one pass is `test_ingest_of_a_city_without_the_flag_stores_no_hearing_and_reports_no_error`, which holds of an ingest with no hearings step at all; it is there for the step once it exists. The commit that holds the tests in this state is the one that adds this paragraph.

With stage 3c added to `ingest_municipality`, the key `title` added to `find_readings`' rows, and `scripts/backfill_hearings.py` written, the same command with `tests/services/test_hearings_store.py` added (M2's file, since `find_readings` changed) ended, on its first run against them:

    70 passed, 1 warning in 7.52s

which is the 16 new tests and the store file's 54. `venv/bin/python scripts/backfill_hearings.py --city birmingham` printed, and exited 2:

    usage: backfill_hearings.py [-h] --city CITY --since YYYY-MM-DD
                                [--until YYYY-MM-DD] [--dry-run]
    backfill_hearings.py: error: the following arguments are required: --since

The removal check (`skills/plan-execute/SKILL.md`). A scratch script outside the repository made 48 copies, 10 of `src/docket/services/ingest.py` (stage 3c: the call, the test for a report, the log line, the appended error, its prefix, the breadth of the `except`, and the stage's place moved before stage 3, before stage 3b, and after stage 4), one of `src/docket/services/hearings.py` (the `title` key) and 37 of `scripts/backfill_hearings.py`, each with one clause taken out or weakened, loaded each copy in place of its module through a pytest plugin (no committed file was edited), and ran the two new test files against it with `-x`. First pass, against the 16 tests of commit 0cf2619:

    removals tried=48 failed a test=47 survived=1

The one: in ingest's log line, `report.matched` replaced by `report.dated` (the test of the line asserted each count to be at least 1, since other rows of the database may be in the run). One test, `test_the_log_line_holds_each_count_of_the_report_under_its_own_name`, was added under the comment "rules pinned after the removal check" in `tests/integration/test_ingest_hearings.py`; it is not in commit 0cf2619. It gives the step a report of six different counts and asserts the whole line. Second pass, same 48 removals, against the 17 tests:

    17 passed, 1 warning in 1.99s
    removals tried=48 failed a test=48 survived=0

The script run from the command line against the throwaway database, which holds no Birmingham agenda item (`DATABASE_URL=$(tools/test-db) venv/bin/python scripts/backfill_hearings.py --city birmingham --since 2025-01-01 --dry-run`), printed one line and exited 0:

    matched=0 dated=0 undated=0 hearings=0

Finished state, `./tools/verify` (2026-11-17 04:42Z), run on the tree the session's last code commit holds:

    3015 passed, 5 skipped, 4 xfailed, 2 warnings in 129.08s (0:02:09)
    1042 passed, 2 warnings in 111.85s (0:01:51)
    judge fixtures: 12 of 12 passed
    134 passed, 1 warning in 10.11s
    verify: plans ... ok (0s)
    verify: all 6 checks passed in 254s.

Against M2's recorded 3004 and 1036: 11 more in the fast tiers (the script's test file) and 6 more in the integration tier (the ingest test file), none failed.

### M3: what remains, and how the operator supplies it

Nothing below has been run. The production dry run is the operator's to run or to allow; either way the next session on this plan is M3 again.

One way: allow the command and run the factory again. The refused command was the first two lines of the production block in Concrete Steps (`railway variables ...` into `PGURL`, then `psql` with `PGOPTIONS='-c default_transaction_read_only=on'`). With a permission rule that allows them, `/cycle-run plans/active/birmingham-coming-up.md` starts a session that finds M3 open, runs the four lines, and writes the record.

The other way: run it by hand. Machine: the Legion. Window: a WSL terminal. Folder: `/home/thinkdarrell/docket-pub/.claude/worktrees/birmingham-coming-up` (this worktree, not the main checkout: the script is on this branch only, and it needs this worktree's `venv/`).

    cd /home/thinkdarrell/docket-pub/.claude/worktrees/birmingham-coming-up
    export PGURL="$(railway variables --service docket-web --kv 2>/dev/null | grep '^DATABASE_PUBLIC_URL=' | cut -d= -f2-)"
    DATABASE_URL="$PGURL" PGOPTIONS='-c default_transaction_read_only=on' venv/bin/python scripts/backfill_hearings.py --city birmingham --since 2025-01-01 --dry-run > ~/hearings-dry-run-all.txt
    DATABASE_URL="$PGURL" PGOPTIONS='-c default_transaction_read_only=on' venv/bin/python scripts/backfill_hearings.py --city birmingham --since 2025-01-01 --until 2026-11-16 --dry-run > ~/hearings-dry-run-until-1116.txt
    tail -1 ~/hearings-dry-run-all.txt ~/hearings-dry-run-until-1116.txt

Both lines carry `--dry-run` and the read-only option; neither writes. The two files are outside the repository and stay there. The next M3 session needs their contents, and a session reads this repository alone, so the operator hands it the two files' text (pasted into the session, or the session allowed to read the two paths); that session records the totals lines, the hearing lines dated on or after the day of the run, the lines for items 62830 with 62881 and 62831 with 62882, and writes the paragraph of differences. For the item-by-item comparison with the author's SQL (Concrete Steps gives it), the session also needs the ids the SQL matches and dates, which is one more read-only `psql` statement against the same address; if that too is refused, the operator runs it and hands over its output with the files.

Added 2026-11-17, after the operator ran the by-hand lines above: the operator ran the two dry-run lines from this worktree in a WSL terminal, and both files exist, 138 lines each: `/home/thinkdarrell/hearings-dry-run-all.txt` and `/home/thinkdarrell/hearings-dry-run-until-1116.txt`. The last line of each, read by the orchestrating session with `tail -n 3`, is `matched=78 dated=67 undated=11 hearings=59`. The next M3 session may read the two paths; it reads the files itself and records what it sees, not this note. Only the files' last three and first five lines have been looked at. The one further read-only `psql` statement for the item-by-item comparison has not been run by anyone.

Correction, 2026-11-17, second M3 session: the fifth of the by-hand lines above, `tail -1 ~/hearings-dry-run-all.txt ~/hearings-dry-run-until-1116.txt`, is refused by this machine's `tail` (Surprises & Discoveries has the message). The line that works is `tail -n 1 ~/hearings-dry-run-all.txt ~/hearings-dry-run-until-1116.txt`. The two lines before it had run and written their files.

### M3: the production dry run, as the second session read it

Session of 2026-11-17 (UTC), Claude, started on commit 103de1e with a clean tree. By the note just above, the operator ran the third and fourth lines of Concrete Steps' production block by hand, from this worktree, with `--dry-run` and the read-only option; the files' modification times are 2026-11-17 06:55 America/Chicago (12:55Z). This session did not run them and did not reach production; it read the two files the lines wrote. What follows is what the files hold.

The two files are one text: 138 lines, 11,148 bytes, SHA-256 `6b927d8e6c9dd29e15ee40e0ea48b0f82a05c54dc5f01db341e541b3e1b29fa8` each, and `cmp` finds no difference. Each is 78 item lines, 59 hearing lines, and the totals line. The totals line of the run with no later bound, and of the run with `--until 2026-11-16`:

    matched=78 dated=67 undated=11 hearings=59
    matched=78 dated=67 undated=11 hearings=59

The hearing lines dated on or after the day of the run, 2026-11-17, seven of them, the same seven the author's Context lists:

    hearing 2026-11-17 vacation items=62182
    hearing 2026-11-17 vacation items=62830,62881
    hearing 2026-11-17 weed_lots items=62831,62882
    hearing 2026-11-24 zoning items=63046
    hearing 2026-12-08 zoning items=63108
    hearing 2026-12-08 weed_lots items=63109
    hearing 2026-12-15 weed_lots items=63166

The second and third are the two Validation names: items 62830 and 62881 are one hearing dated 2026-11-17, and 62831 and 62882 one `weed_lots` hearing, whose item lines carry the count:

    62830  2026-10-13  2026-11-17  vacation  -  A Resolution setting a public hearing November 17, 2026, to consider t
    62831  2026-10-13  2026-11-17  weed_lots  212  A Resolution finding that the following two hundred twelve (212) prope
    62881  2026-10-26  2026-11-17  vacation  -  A Resolution setting a public hearing November 17, 2026, to consider t
    62882  2026-10-26  2026-11-17  weed_lots  212  A Resolution finding that the following two hundred twelve (212) prope

The whole run by kind. Of the 67 dated items, 39 are `zoning`, 14 `weed_lots`, 12 `vacation`, 2 `other`; of the 11 undated, 8 are `other`, 2 `budget`, 1 `vacation`. The 59 hearings are 34 `zoning`, 13 `weed_lots`, 10 `vacation`, 2 `other`. Sixty-seven items make 59 hearings through eight joins: 3673 with 3674; 3626 with 3627, 3628 and 3629 (three joins); 3297 with 3339, the amended resolution the prefix rule was written for; 360 with 361; 62830 with 62881; 62831 with 62882. The eleven undated items are 746, 748, 1249, 1261, 3167, 3224, 3238, 3296, 3407, 58828 and 58878. Nine times a day holds two hearings of one kind that the reader keeps apart (2025-07-15, 2025-12-09, 2026-02-24, 2026-06-09, 2026-08-25 and 2026-10-20 zoning; 2026-02-10 zoning and vacation; 2026-11-17 vacation); the titles in view do not say whether any of those is one hearing worded twice, which is the doubled entry the Decision Log accepts as the cost of the 90-character rule, and only 2026-11-17's pair is on a date the page will show, where items 62182 (a street closure) and 62830 (a right-of-way vacation) are the two different hearings the author's Context names.

What the session ran in this worktree, and what each printed. `./tools/verify`, before any edit (13:00Z) and again on the plan as finished but for this paragraph and the tick's time (13:13Z), printed the same summary lines both times but for the seconds:

    3015 passed, 5 skipped, 4 xfailed, 2 warnings in 131.10s (0:02:11)
    1042 passed, 2 warnings in 112.30s (0:01:52)
    judge fixtures: 12 of 12 passed
    134 passed, 1 warning in 10.68s
    plans: 1 of 1 ok
    verify: all 6 checks passed in 257s.

The two counts are the first M3 session's finished counts, 3015 and 1042: this session added no test, so Validation's "more tests passed than the session's own first run of the day" holds of M3 across its two sessions (3004 and 1036 before, M2's record) and not of this session alone. `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_ingest_hearings.py tests/unit/test_backfill_hearings_script.py -q -p no:cacheprovider` ended `17 passed, 1 warning in 1.77s`. `venv/bin/python scripts/backfill_hearings.py --city birmingham` printed the usage and `backfill_hearings.py: error: the following arguments are required: --since`, and exited 2. The Python that ran the author's two patterns over the titles was a scratch script outside the repository; it also read each of the 23 fixture titles with `read_hearing` and found the date and kind the dry run printed for that item, all 23.

### M3: the comparison, and what is still owed

The paragraph M3 asks for. It compares the run restricted by `--until 2026-11-16` with the author's counts of 2026-11-16 (78 matched, 67 dated counting item 730, 11 undated) and the operator's (71 items, 9 dated on or after 2026-11-16).

Against the author's 78, 67 and 11 the totals are the same three numbers. Against the operator's 9: nine item lines carry a hearing date of 2026-11-16 or later (62182, 62830, 62831, 62881, 62882, 63046, 63108, 63109, 63166), the nine the author's Context lists. Item by item, the session could not ask production which ids the author's SQL matches and dates (the harness refused the statement; Surprises & Discoveries), so it ran the author's two patterns in Python over what the repository and the files hold of each of the 78 titles: the 23 that are fixture titles (whole, or their first 420 characters) and, for the other 55, the 70 characters the dry run prints. In 66 of the 78 the trigger is in view. Fifty-four of those the SQL dates and the reader dates, 53 to the same day; the one that differs is item 2116, where the SQL reads October 28, 2025 and the reader November 4, 2025, because the reader applies the "CHANGE HEARING DATE FROM ... TO ..." correction and the SQL knows nothing of it. One, item 730, the reader dates (2026-04-07, by the second form, "on the 7th day of April, 2026") and the SQL does not, which is the difference the author foretold and the whole of 67 against the SQL's 66. Eleven neither dates: after the trigger they read "to consider ..." or "in the Council Chambers on ...". In the remaining 12 (item 3298, a resolution amending an earlier one, and eleven weed-lot resolutions: 58979, 59093, 59216, 60734, 60928, 61167, 61329, 61608, 61967, 62183, 62831) the trigger lies past the 70 characters printed and none is a fixture title, so what the SQL makes of them was not seen. The reader dates all 12, each to a Tuesday 28 or 35 days after its meeting. If the author's 78 are these 78, the SQL must date all 12 as well, since it dates 66 and 54 are accounted for; the three weed-lot titles that are fixtures (62882, 63109, 63166) are of the same wording and the SQL dates each to the reader's day.

So the items on which the reader and the author's SQL are known to differ are two, 730 and 2116, each for a reason M1's rules state. Not shown: that the author's 78 ids are these 78 ids. The counts are equal and the trigger is the same pattern, but the two do not collapse whitespace alike (the SQL collapses newlines, tabs and spaces; the reader every kind of whitespace) and the reader's trigger must start and end at a word boundary, so one item could have left the set as another entered it and the counts would not show it.

Against the operator's 71, the difference of seven is not explained, and cannot be from what is recorded: the operator's query is in no file. One reading fits the number and is offered as arithmetic, not as a finding. The dry run holds five sets of item lines that share a meeting date and their first 70 characters (360 and 361; 746 and 748; 1249 and 1261; 3626 to 3629; 3673 and 3674), seven items beyond the first of each set, and a scan that counted each agenda line of a meeting once would count 71. It would also count 9 on or after 2026-11-16, since none of the seven is among those nine.

What is still owed, both the operator's. First, the statement the harness refused, read-only, from the WSL checkout, before the backfill of step 4 in Validation; its output is one line per item the SQL matches, with the date the SQL reads or `NULL`:

    export PGURL="$(railway variables --service docket-web --kv 2>/dev/null | grep '^DATABASE_PUBLIC_URL=' | cut -d= -f2-)"
    PGOPTIONS='-c default_transaction_read_only=on' psql "$PGURL" -X -A -t -F '|' -c "WITH x AS (SELECT ai.id, regexp_replace(ai.title, E'[\n\t ]+', ' ', 'g') AS t FROM agenda_items ai JOIN meetings m ON m.id = ai.meeting_id JOIN municipalities mu ON mu.id = m.municipality_id WHERE mu.slug = 'birmingham' AND m.meeting_date >= DATE '2025-01-01') SELECT id, coalesce((regexp_match(t, '(?:setting|to set|providing for) (?:a|the) public (?:show cause )?hearing,? (?:on |for )?((?:January|February|March|April|May|June|July|August|September|October|November|December) [0-9]{1,2},? [0-9]{4})', 'i'))[1], 'NULL') FROM x WHERE t ~* '(setting|to set|providing for) (a|the) public (show cause )?hearing' ORDER BY id" > ~/hearings-author-sql.txt
    cut -d'|' -f1 ~/hearings-author-sql.txt | diff - <(grep '^[0-9]' ~/hearings-dry-run-all.txt | awk '{print $1}') && echo "same ids"

Nobody has run these two lines; the statement is the author's SQL from Concrete Steps with the city and the date bound written out, and this session wrote it and did not see it run. "same ids" means the 78 are the 78 and the paragraph above is whole. Any other output is a list of ids one side has and the other lacks (the list will also grow by whatever a meeting ingested since 2026-11-17 added, which a fresh dry run shows on both sides), and each is an item to read before the backfill. In `~/hearings-author-sql.txt` the lines ending `|NULL` should be twelve: item 730 and the eleven undated. Second, the 71: only the operator can say what was counted.

## Interfaces and Dependencies

No new package. `pdfplumber` and `pyyaml` (through `python-frontmatter`; `src/docket/services/how_it_works.py` already imports `yaml`) are in the environment; `requirements.txt` and `requirements.lock` are not changed.

At the end of M1, in `src/docket/enrichment/hearings.py`:

    RULE_VERSION: int
    KINDS: tuple[str, ...]
    KIND_LABELS: dict[str, str]
    @dataclass(frozen=True)
    class HearingReading: hearing_date: date | None; kind: str; subject: str; subject_key: str; property_count: int | None
    def read_hearing(title: str | None) -> HearingReading | None
    def same_hearing(key_a: str, key_b: str) -> bool

At the end of M2 and M3, in `src/docket/services/hearings.py`:

    RECENT_DAYS: int
    @dataclass(frozen=True)
    class HearingReport: matched: int; dated: int; undated: int; hearings: int; created: int; linked: int
    def find_readings(municipality_id: int, since: date, until: date | None = None) -> list[dict]
    def group_readings(rows: list[dict]) -> list[dict]
    def refresh_hearings(municipality_id: int, since: date, until: date | None = None) -> HearingReport
    def refresh_recent(municipality_id: int) -> HearingReport | None
    def list_upcoming(municipality_id: int, start: date, end: date) -> list[dict]

At the end of M4 and M5, in `src/docket/services/neighborhood_schedule.py`:

    class ScheduleError(ValueError)
    @dataclass(frozen=True) class Association
    @dataclass(frozen=True) class Schedule
    @dataclass(frozen=True) class Occurrence: association: Association; on: date
    def load_schedule(city_dir: Path) -> Schedule
    def get_schedule(slug: str) -> Schedule | None
    def occurrences(schedule: Schedule, start: date, end: date) -> list[Occurrence]
    def undated(schedule: Schedule) -> list[Association]

At the end of M6, in `src/docket/services/coming_up.py`:

    WINDOW_DAYS: int
    @dataclass(frozen=True) class Entry
    def is_coming_up_city(municipality: dict | None) -> bool
    def list_entries(municipality: dict, *, today: date | None = None) -> list[Entry]
    def undated_associations(slug: str) -> list[tuple[str, str]]
    def schedule_source(slug: str) -> dict | None
    KINDS: tuple[str, ...]
    def association_slug(name: str) -> str
    def filter_entries(entries: list[Entry], *, kind: str | None = None, association: str | None = None) -> list[Entry]
    def association_feeds(slug: str) -> list[tuple[str, str]]

`Entry`'s fields at the end of M6: `kind`, `uid`, `on`, `starts_at`, `ends_at`, `title`, `detail`, `links`, `source_url`, `place`, `badge`, `badge_label`, `cancelled`, `cancelled_by`, `attend`, `association`.

At the end of M8b, the template `src/docket/web/templates/rss/scheduled_hearings.xml.j2`, and `public.upcoming_hearings_rss` choosing between it and `rss/upcoming_hearings.xml.j2` by `coming_up.is_coming_up_city`.

At the end of M7 and M8, in `src/docket/web/public.py`, the routes `public.coming_up_page` and `public.coming_up_ics` and the template global `has_coming_up`; in `src/docket/web/ics.py`, `render_calendar(entries, *, name, now, absolute) -> str`; in `src/docket/services/sitemap.py`, `has_coming_up(slug: str) -> bool`.

Allowed imports, by the layer map in `ARCHITECTURE.md`: the reader imports the standard library only; the three services import `docket.db`, `docket.config`, `docket.enrichment.hearings`, `docket.adapters._helpers`, and other services; nothing under `services/` imports `docket.web`; `public.py` and `ics.py` call services and execute no SQL.

Files this plan does not edit, and a session that needs to edit one stops and records why first: `src/docket/web/__init__.py`, everything under `src/docket/worker/`, `src/docket/services/briefing.py`, `src/docket/services/meeting_types.py`, `src/docket/services/query.py`, `src/docket/web/static/layout.css`, `src/docket/web/static/mobile.css`, `requirements.txt`, `Dockerfile`.

## Revision note

2026-11-16, authored by the `cycle-plan` workflow from the operator's goal and a scope brief written by a read-only agent; the brief is folded into Purpose and Context and is not committed as a file. Deliberately left out of this plan, and why: the existing `/al/<slug>/upcoming-hearings.rss` and `query.list_upcoming_hearings` (re-pointing them changes a published feed for every city; M9 records the two notions as debt); fixing Granicus start times (issue #88, pull request #181, a branch already in flight; the operator merges it first); retiring leftover `event-` rows (issue #62; the page lists only future dates, so one disappears when its date passes); reading committee agendas into items (`D132`; an upcoming committee meeting links its event page and nothing about what it will take up); showing a hearing on the item page, the meeting page, the city-page opener, or in search (the goal names one page and one feed); past hearings as a browsable archive (the backfill stores them, the page shows the window); hearings held without a dated resolution setting them (consent "ph" items, licence hearings); a 2027 neighborhood schedule and any automatic re-fetch of the PDF; holiday or one-off changes the PDF does not state; the README's worker counts (`D138`) and SQL in web modules (`D7`); the test-removal runner of `D131` (re-deferred); other cities, events submitted by users or groups, board term ends and vacancies, elections, contract end dates, and deferred-item tracking (excluded by the goal); and deploy, the production migration, and the production backfill, which are the operator's steps after the merge.

2026-11-16, revised by Claude at the operator's direction, before any milestone ran. The operator brought a written review of the plan ("Feedback & Refinement Plan: Birmingham Coming-Up Feature", a file outside the repository, whose points are restated in the Decision Log entries of this date so nothing depends on it) and asked for the changes Claude recommended from it. What changed: a cancelled meeting is shown marked cancelled with its source named, where the plan had left it out (M6, M7, M8; the first decision is kept and marked superseded); a flagged city's existing `upcoming-hearings.rss` lists the stored hearings, by a branch in the route, where the plan had left that feed alone (a new milestone, M8b, placed before M9 and named so that no existing Progress line or reference to M9 is reworded; that decision too is kept and marked superseded in part); the calendar feed takes `?kind=` and `?association=` and the page links each narrowed feed, with a `webcal` link and a Google Calendar link (M6 for the functions, M8 for the route and the links); every entry has a coloured label of its kind, none ranked above another (M6, M7); a neighborhood meeting's place and call-in details sit under "How to attend", which moved `remote` out of the detail lines (M6, M7, M8). `Entry` gained six fields, listed in Interfaces. The operator's steps gained two (7 and 8), and M9's debt rows gained two and one was reworded. Not adopted, with reasons in the Decision Log: reading `description` for a cut title, a holiday note, and the city's older spreadsheet of the schedule. Considered and left for other plans: the Zoning Board of Adjustment, Design Review Committee and Planning Commission (no current city schedule found; a debt row in M9), event markup for search engines, and re-reading a cut title's agenda PDF (already inside the "cannot date" debt row). Validation clauses re-read against the changed rules: M6's cancelled cases (rewritten, since "gives no entry" was the old rule), M7's count test (unchanged: a cancelled entry is an article like any other, so the count of `data-entry-uid` still equals `len(list_entries(...))`), M8's one-event-per-entry test (unchanged for the same reason, and the unfiltered feed is what it reads), and M9's `git diff --stat` clause (unchanged: M8b's files are in an earlier session). The hand-worked date the association test leans on, Acipco-Finley on December 2, 2026, is in "Dates worked by hand" and inside the window of a `today` of 2026-11-16, which ends 2027-01-15.

2026-11-16, corrected by Claude after a second written review the operator brought ("Technical Review: Revised Birmingham Execution Plan", a file outside the repository; its points that were taken are restated in the three Decision Log entries of this date signed "Claude, correcting the plan"), before any milestone ran. Three defects in the plan's own rules were mended: the link delete in `refresh_hearings` could not see an item that had lost its trigger (M2); the prefix rule of `same_hearing` was shorter than the wording every zoning hearing shares, and is now 90 characters with a one-candidate rule in `group_readings` and in the match against stored hearings (M1, M2); and the function that makes a link absolute was unspecified for a full address and missing from M8b (M6, M8, M8b). Smaller additions from the same review: a test pinning where item 2116's subject is cut (M1), the schedule's year in the association-feed heading (M8), two more cases in the "cannot date or follow" debt row (M9), and two sentences in the operator's steps 4 and 7. Not taken: restarting the web service after the backfill (the review's command is for a machine with `systemctl`; the service runs on Railway, the cache empties itself in an hour, and step 8 already said to wait). Checked while correcting, by running the key rule of M1 over the 25 fixture titles in Python: the shared zoning wording is 82 characters; item 2116's key is 100 characters ending `zac202500019`; item 3297's is 101 and opens item 3339's; and at a threshold of 40 or of 90 that pair is the only one of the 25 that joins, so the table of expected readings and the four pair cases stand as written. Validation clauses re-read against the changed rules: M1's and M2's (they name test files and cases, not the threshold), and M8's and M8b's (unchanged; the new assertions are in the Plan of Work's test lists).

2026-11-16, one more correction, by the operator's decision: the feed has no `STATUS:CANCELLED` line (M8's rule and its test, a debt row in M9, and the Decision Log's last entry, which says why). Validation's M8 clause names no `STATUS` line and stands.

2026-11-17, M3's second session (Claude). One sentence was added to the operator's step 4 in Validation: the read-only comparison of ids that the harness refused to the session is run by the operator before the backfill. Reason: M3 is ticked with that check unmade (Decision Log), and step 4 is the last point before anything is written to production, and the list M9 copies into its debt row. No rule, interface, or milestone changed.
