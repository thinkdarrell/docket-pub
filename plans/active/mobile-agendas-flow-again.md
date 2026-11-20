# Make Mobile's council agendas flow again through the CivicClerk adapter

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.


## Purpose / Big Picture

docket.pub publishes Alabama cities' council records with every fact linked to the city's own document. Birmingham works. Mobile does not: the page at https://docket.pub/al/mobile/ lists council meetings whose cards say "0 items", and (this plan's research found) the items it does hold probably belong to other meetings. This is stage 1 of bringing the other cities up to Birmingham, Mobile first.

After this plan is merged, deployed, and the operator's written-out steps are run, a reader who opens /al/mobile/ sees Mobile City Council meetings whose cards show the real number of agenda items (51 for the meeting of 2026-11-17, as the city's system held it on 2026-11-20), each item titled with the city's own wording and its ordinance or resolution code, with its sponsor and dollar amount, and, as the existing daily AI budget allows, a headline, newest meetings first. A meeting page links the city's own agenda and, for meetings the city entered into its system before they were held, its minutes. The council shown is the council the city's minutes and council page list, and the roster holds term-dated rows back to November 2021 so a later stage can attach votes.

The work is built as settings and adapter behaviour, not as a Mobile special case. Vestavia Hills, the other city on the same vendor system (CivicClerk), is repaired by the same change, and a later CivicClerk city reuses it. Birmingham's ingest does not change.

Three observations stand in for "it works" before the operator's steps: `./tools/verify` passes with new tests that fail on today's code, built from saved CivicClerk responses; a dry run of the new reset script prints what it would delete; and the read-only production queries in Validation and Acceptance print the figures stated there.

One part of the stated goal is not delivered, and the reader should know it before reading further. The goal asked for agenda items back to the council term that began in November 2021. The city's system holds structured agenda items only for meetings from 2024-06-25 forward (124 meetings on 2026-11-20). The 135 earlier meetings of the window were loaded into the system on 2024-07-25 as PDF files only. This plan stores those meetings with their agenda link and no items; reading items out of the agenda PDFs is a separate piece of work, recorded as a debt row by the closing milestone. The Surprises section gives the evidence.


## Progress

- [x] (2026-11-20 20:51Z) M1: `CivicClerkAdapter.list_meetings` follows the city system's next-page links to the last page, asks only for events on or after the date it is given, waits at least one second between requests, retries a request that fails, and gives each meeting its posted wall-clock start time and links to the city's own agenda file and, for an event created on or before its own date, minutes file; the tests built from the saved responses under `tests/fixtures/civicclerk/` pass and `./tools/verify` passes
- [x] (2026-11-20 21:28Z) M2: `CivicClerkAdapter.fetch_agenda_items` reads a meeting's items from the event's agenda id, raises `AgendaNotReady` where no agenda is published yet and an error where the request fails, and returns each item titled with the city's own item name (its ordinance or resolution code first), with its sponsor and its submitter split out; its tests pass and `./tools/verify` passes
- [x] (2026-11-20 21:56Z) M3: `ingest_municipality` reads `backlog_floor` and `agenda_fetch_cap` from a city's `adapter_config`, fetches agendas newest first up to the cap, leaves a meeting whose agenda is not ready unmarked and unreported, and does not re-fetch a stored agenda for an adapter whose items carry no video timestamps, while a city with neither setting ingests as before; its tests pass and `./tools/verify` passes
- [x] (2026-11-20 22:20Z) M4: `scripts/reset_agenda_items.py --city <slug>` prints what it would delete and, with `--apply`, deletes one city's stored agenda items and re-opens its meetings in one transaction, refusing a city whose items carry vote links or transcript links; its tests pass and `./tools/verify` passes
- [ ] M5: a new numbered migration gives Mobile's council a term-dated roster taken from the city's minutes and council page, with the seated seven active and the members who left since November 2021 kept as dated inactive rows; its test resolves every surname of the saved roll calls on its date and `./tools/verify` passes
- [ ] M6: the close: a new spec `docs/specs/civicclerk-ingest.md` and the edits to `docs/specs/index.md`, `docs/specs/operations.md`, `docs/runbooks/cron-worker.md`, and `README.md` describe what M1 to M5 built, the durable decisions are graduated to `docs/decisions/`, and `docs/DEBT.md` has `D175` deleted, `D9` and `D12` edited, and new rows for the operator's steps after merge and for what this plan left undone; `./tools/verify` passes


## Surprises & Discoveries

As authored on 2026-11-20, nothing has been executed. The observations below were made by the author while researching, with read-only requests to the two cities' public CivicClerk addresses and to Mobile's council page; no production query was run (a factory session cannot reach production). Each is something the scope brief did not know or had differently.

- Observation: the page size parameter `$top` is a total, not a page size. The server returns 15 rows a page whatever is asked, and the next-page link it gives for a `$top=100` request carries `$top=85`, so following links under `$top=100` would stop at 100 rows.
  Evidence: `Events?$top=100&...` for Mobile category 26 printed `@odata.count 492`, 15 rows, and a next link beginning `Events?$top=85&$orderby=...&$skiptoken=eventDate-2027-05-25T10%3A30%3A00Z,id-559`. The same request with no `$top` gave a next link with no `$top`; walking it for Vestavia Hills (`eventCategoryId eq 26 and eventDate ge 2021-11-01T00:00:00Z`) printed `count 113 pages 8 page sizes [15, 15, 15, 15, 15, 15, 15, 8] rows 113 distinct 113`.

- Observation: a date filter works on the server, so a backlog floor costs no extra pages.
  Evidence: `$filter=eventCategoryId eq 26 and eventDate ge 2026-10-27T00:00:00Z and eventDate le 2026-11-21T00:00:00Z` printed `@odata.count 4` and events 501, 500, 499, 498. For Mobile, `eventDate ge 2021-11-01T00:00:00Z and eventDate le 2026-11-20T23:59:59Z` printed count 259; before 2021-11-01, count 191; 492 in all, so 42 are scheduled ahead (through 2027-08-31).

- Observation: the 2026-11-17 Mobile agenda holds 51 items, not 66. `Meetings/473` returns 66 nodes of which 15 are section headings (`isSection` 1: CALL TO ORDER, ROLL CALL and so on), which the adapter already leaves out. The 2026-11-03 agenda (`Meetings/471`) is 78 nodes, 18 headings, 60 items. The brief's "66 to 78 items" counted headings.
  Evidence: a walk of `items` and `childItems` printed `nodes 66 sections 15 non-section 51` and `{'nodes': 78, 'sections': 18, 'items': 60, 'coded': 45, 'sponsored': 43, 'submitted': 29, 'both': 28}`.

- Observation: the ordinance or resolution code lives only at the start of the item's name. On both agendas `ordinanceNumber`, `resolutionNumber`, `ordinanceFormattedNumber`, `resolutionFormattedNumber`, `hasVote`, `passFail` and `minutesItemVotes` were unset on every item, including the 2026-11-03 meeting whose minutes are published. `agendaObjectItemDescription` was empty on every item. `agendaObjectItemNumber` is a file number (`2026-2408`), and for Vestavia Hills too (`26-997`, beside an outline number `11.`).
  Evidence: the tally above printed no `... set` key; names read `01-1211 Authorize Agreement with the Mobile County Commission ...; $7,500,000.00 (sponsored by Mayor Cheriogotis) (submitted by Robert Shreve, City Attorney).` and `40-1225 Declare the structure at 701 N. Joachim Street a public nuisance and order it demolished (sponsored by Councilmember Ingram).`

- Observation: today's enrichment names the wrong sponsor for about half of Mobile's coded items. `extract_sponsor` in `src/docket/enrichment/sponsors.py` tries "(Submitted by" before "(sponsored by", and Mobile writes both.
  Evidence: `extract_sponsor` on the first name above printed `'Robert Shreve, City Attorney'`; 28 of 60 items of the 2026-11-03 agenda carry both parentheticals. `clean_title` on the same name leaves `...$7,500,000.00  .`

- Observation: requesting `Meetings/{event id}` does not merely return nothing; once an agenda with that number exists it returns another meeting's agenda. Production's Mobile items are therefore probably attached to the wrong meetings.
  Evidence: event 441 is the meeting of 2025-10-21 and its `agendaId` is 414. `Meetings/414` printed 72 items, item ids 3199 to 6317, files named `10/21/25 Agenda`. `Meetings/441`, the address today's adapter requests for that meeting, printed 58 items, item ids 10593 to 10656, files named `3/31/26 Agenda`: the agenda of 2026-03-31. Event ids and agenda ids differed on every event sampled (Mobile by 16 to 28, Vestavia Hills by about 800). The weekly worker task `repair_empty_agendas` re-opens an empty meeting, and the re-fetch then stores whatever agenda has since been created under the event's number.

- Observation: a meeting marked scraped with no items is not stuck for ever, as the brief said; it is re-opened every Monday if it is less than 18 months old and has an agenda link (`repair_empty_agendas` in `src/docket/services/maintenance.py`). That is what turns the wrong id into wrong items, above.

- Observation: every stored CivicClerk agenda is fetched again on every daily run. `_ingest_agenda_items` in `src/docket/services/ingest.py` sends an already-scraped meeting whose id does not begin `event-` to `_backfill_video_timestamps`, whose check ("any numbered item without a video timestamp?") is always true for a CivicClerk item, so it calls `adapter.fetch_agenda_items` again. With paging mended that would be about 300 requests a day for Mobile, each returning 0.4 MB.

- Observation: Mobile's system holds structured items only from 2024-06-25. Events before that were created on 2024-07-25, after their own dates, with PDF files attached and no items.
  Evidence: events 256, 248, 242 (2024-06-04 to 06-18) print `created 2024-07-25` and file names like `2024-06-11_10_30_AM-Council_`; event 33 (2024-06-25) prints `created 2024-03-18` and `City Council Agenda 6/25/24`. `Meetings/229` and `Meetings/270` (imported agendas) returned no item nodes; `Meetings/17` (2024-06-25) printed 54 items, 30 coded; `Meetings/27` printed 58 items. Events from 2024-06-25 to 2026-11-20: count 124.

- Observation: the Minutes file attached to an imported Mobile event is often another meeting's minutes. Its Agenda file was the right date in both cases read, but is the whole packet.
  Evidence, label to the date printed on the document's first page: event 2023-03-21 (file 615) AUGUST 30, 2022; 2023-03-28 (603) MARCH 28, 2023; 2023-04-04 (589) JUNE 28, 2022; 2023-04-11 (577) OCTOBER 11, 2022; 2023-04-18 (563) SEPTEMBER 20, 2022; 2023-04-25 (549) SEPTEMBER 27, 2022; 2023-05-02 (534) SEPTEMBER 13, 2022; 2023-05-09 (520) NOVEMBER 1, 2022; 2023-08-01 (359) FEBRUARY 7, 2023; 2023-08-08 (347) FEBRUARY 14, 2023; 2024-01-30 (701) AUGUST 8, 2023. Agenda files 548 and 576 (events 2023-04-25 and 2023-04-11) open "Tuesday, April 25, 2023" and "Tuesday, April 11, 2023" and are 152,718,716 and 68,306,614 bytes (1,947 and 604 pages). Nobody should download an imported Agenda file again to check anything; the author did, twice, and regrets the load.

- Observation: event rows do carry `hasAgenda` (the brief saw no `hasMinutes` key, which is right; `hasAgenda` is present and true on events with an agenda). The file link works: `Meetings/GetMeetingFileStream(fileId=3854,plainText=false)` answered `200 application/pdf`, 693,774 bytes; with `plainText=true` it answered `text/plain`, 114,610 bytes for a 2026 file and 0 bytes for files 197 and 185 (2021), which need a PDF reader (`pdfplumber`, already in the venv, read them).

- Observation: `eventDate` is the posted local time with a false `Z`. The city's own minutes say the 2026-11-03 meeting was "at 10:30 a.m."; its `eventDate` is `2026-11-03T10:30:00Z`. Today's adapter converts that to 04:30 Central.

- Observation: Vestavia Hills is listed with no category filter. Migration `004_expand_meeting_types.py` removed `category_id` from its `adapter_config`, and `README.md` lists seven bodies for it. Unfiltered, the city has 378 events and the first page is fifteen board meetings scheduled for 2027, so today's adapter (rows 1 to 15, 101 to 115, 201 to 215, 301 to 315) sees a council meeting only by accident. That, not the agenda id, is the likely reason its newest meeting with an agenda link is from May 2026. Production's row is the operator's to confirm (query Q1).
  Evidence: `Events?$top=100&$skip=0&$orderby=eventDate desc&$count=true` for `vestaviahillsal` printed `@odata.count 378` and fifteen rows dated 2027-04-20 to 2027-09-16, none of category City Council. Vestavia's council history begins 2023-03-13 and one of its 113 council events was created after its own date.

- Observation: requests to the API fail now and then at the connection.
  Evidence: of about 60 requests on 2026-11-20, five failed: three returned nothing within a 30 or 40 second limit, one `curl: (28) Connection timed out after 60002 milliseconds`, one `requests.exceptions.ReadTimeout` after a TLS handshake timeout. Each succeeded when repeated. Today's `fetch_agenda_items` turns such a failure into "no items" and the meeting is marked scraped.

- Observation: Mobile's roll calls, read from the city's minutes. 2021-11-02 (event 118, file 197): "Penn, Carroll, Small, Reynolds, Daves, Scott and Gregory". 2022-09-13 (file 534): "Penn, Carroll, Small, Reynolds, Daves, Jones, and Gregory". 2023-03-28 (file 603): the same seven with Jones. 2023-08-08 (file 701): the pre-council conference lists six, "Penn, Carroll, Small, Reynolds, Daves, and Gregory", and the regular meeting's roll call that day lists "Chairman: Small, Vice-Chairman: Gregory, Councilmembers: Penn, Carroll, Reynolds, Daves, and Woods". 2025-10-28 (event 442, file 1350): "Penn, Carroll, Small, Reynolds, Daves, Woods, and Gregory". 2025-11-04 (event 443, file 1351): "Penn, Ingram, Small, Reynolds, Fleming, Woods, and Gregory". 2026-11-03 (event 499, file 3854): the same. The city's council page, https://www.cityofmobile.gov/government/city-council/, read 2026-11-20, lists District 1 Cory Penn, District 2 Samantha Ingram, District 3 C.J. Small, District 4 Ben Reynolds, District 5 Beau Fleming, District 6 Josh Woods, District 7 Gina Gregory. The minutes of November 2021 write "Scott" for the member the minutes of September 2022 onward write "Jones". Migration `005_seed_council_rosters.py` seeded William Carroll (District 2) and Beau Fleming (District 5) together, two members who never sat at the same time.

- Observation: `./tools/verify` took 304 seconds in this worktree on 2026-11-20 (`verify: all 6 checks passed in 304s.`), about twice the 150 seconds `AGENTS.md` states.

The observations below were added on 2026-11-20 by the operator's review revision, after the operator had a review of this plan and a set of proposed replacement blocks checked against the code, the city's system, and production. Production was read with read-only queries (`default_transaction_read_only=on`) through the Railway CLI on the Legion; every request to the city's system was followed by a pause of 1.5 seconds.

- Observation: Q3 is answered. Mobile's stored items are another meeting's, as the author supposed. Production holds numeric-id items on 51 Mobile meetings and 52 Vestavia Hills meetings. For six Mobile meetings sampled, the stored item count and id range equal what `Meetings/{event id}` returns today, and that agenda's own Agenda file is named for a different date.
  Evidence, stored against the city's answers: event 460 (2026-02-03) stores 43 items, ids 7474 to 12698; `Meetings/460` returns ids 7474 to 12698 with the file `August 11, 2026 Agenda`; its own agenda, 433, returns 68 items, ids 6853 to 8219. Event 456 (2026-01-06) stores 37, ids 7382 to 11488; `Meetings/456` is `7/14/26 Agenda`; its own agenda 426 is 40 items, ids 6572 to 7981. Event 443 (2025-11-04) stores 56, ids 10581 to 10788; `Meetings/443` is `4/14/26 Agenda`; its own agenda 416 is 40 items, ids 3245 to 6401. Event 441 (2025-10-21) stores 58 items, ids 10593 to 10656, the range the author found for the agenda of 2026-03-31. Event 401 (2025-01-14) stores 69, ids 2900 to 5570; `Meetings/401` is `7/22/25 Agenda`; its own agenda 374 is 72 items, ids 2279 to 3991. Event 424 (2025-06-24) stores 46, ids 3733 to 3889, and `Meetings/424` is `1/2/25 Agenda` (the request for its own agenda, 397, failed at the TLS handshake three times and was not repeated). Event 386 (2018-01-16), an imported event whose own agenda 359 has no item, stores 53 items, ids 2555 to 4677, from `4/8/25 Agenda`. Twenty-three of the 51 Mobile meetings holding items are dated before 2024-06-25, when the city's system has no structured items at all.

- Observation: some of Vestavia Hills' stored items are right. Its older events have an agenda id equal to the event id.
  Evidence: event 166 (2025-01-13) has `agendaId` 166, stores 25 items, ids 2706 to 3918, and `Meetings/166` returns the same 25 under the file `January 13, 2025 City Council Agenda Packet`. Event 167 (2025-02-10) has `agendaId` 1190, stores 15 items, ids 2728 to 2742, which `Meetings/167` returns under `November 2024 Parks and Recreation Board Meeting`; its own agenda is 24 items, ids 4094 to 4178. No predicate in the database tells the two kinds apart, so the reset still removes both, and the right ones are fetched and summarised again.

- Observation: a scheduled meeting can have an agenda record with nothing in it, and `hasAgenda` does not say so.
  Evidence: on 2026-11-20 Mobile events 503, 504, 505, 507 and 539 (2026-12-01 to 2027-01-05) each printed an `agendaId` above zero, `hasAgenda` true and no published file; `Meetings/475` (event 503) printed `agendaIsPublish` false and no node. The published agendas 473, 471, 474 and 426 each printed `agendaIsPublish` true. Events 506, 537 and 540 onward printed `agendaId` 0 and `hasAgenda` false. So `hasAgenda` cannot be used to skip a request, and an unpublished agenda costs one request a day per such meeting, five on that day.

- Observation: the city publishes an agenda before the meeting. `Meetings/474`, the agenda of 2026-11-24, held 46 items on 2026-11-20. Under this plan it is fetched once and never again; whether the city adds items between publishing and the meeting was not observed.

- Observation: the event lookup by id works. `Events?$filter=id eq 501` returned the one event 501 with `agendaId` 473.

- Observation: the codes are zero-padded to three digits. The agenda of 2026-01-06 (`Meetings/426`) carries `03-001`, `64-058` and `64-062`; the agenda of 2026-11-24 carries `17-045`. No two-digit code was seen, so `^(\d{2}-\d{3,4})\b` stands.

- Observation: the four items of the `meeting_473.json` fixture sit under four different headings, and only one is a consent item. In `Meetings/473`: item 13498 is the one child of heading 7752 `INVOCATION`; 13505 is under 7772 `PUBLIC HEARINGS`; 13520 is under 7763 `RESOLUTIONS HELD OVER`; 13512 is under 7764 `CONSENT RESOLUTIONS BEING INTRODUCED` (fourteen children). Every top-level node is a heading and no item has children. The agendas read carry the headings `CONSENT RESOLUTIONS HELD OVER` and `CONSENT RESOLUTIONS BEING INTRODUCED`. Today's adapter sets `is_consent` only when the item's own title contains "consent" (`is_consent_item(full_title)`), so no Mobile consent item is marked.

- Observation: `_upsert_meetings` already replaces a stored link. Both of its statements in `src/docket/services/ingest.py` write `agenda_url = %s, minutes_url = %s` with no `COALESCE`, so a portal-page link becomes the file link on the first run that lists one. Only `start_time` is written through `COALESCE`.

- Observation: a meeting's AI summary is five columns on `meetings`: `executive_summary`, `executive_summary_voice`, `ai_prompt_version`, `ai_metadata`, `ai_generated_at`. `cmd_force_meeting` in `src/docket/ai/cli.py` clears four of them to have a meeting claimed again, and the claim in `src/docket/ai/worker.py` takes a meeting whose `ai_prompt_version` is NULL once all its items are at the current version. `processing_status` has no summary or hearing column (its flags are `agenda_items_scraped`, `agenda_pdf_downloaded`, `votes_scanned`, `votes_matched`, `minutes_checked`). Of the tables that reference `agenda_items`, only `processing_status_audit` neither cascades nor sets NULL on delete.

- Observation: the city's own site names the members the roll calls give by surname. `https://www.cityofmobile.gov/uploads/file_library/2022-acfr-final-032423.pdf` (the annual financial report for fiscal 2022) lists "William Carroll (District 2), Joel Daves (District 5), and Scott Jones (District 6)". `https://www.cityofmobile.gov/uploads/250320103140OrganizationalChart5.pdf` (the organisational chart of March 2025) prints "Council District 5 – Joel Daves" and "Council District 6 – Josh Woods". `https://www.cityofmobile.gov/city-council/city-councils-administrative-services-committee-to-meet/` (dated October 4, 2022) names "Councilman Scott Jones, District 6". `https://www.cityofmobile.gov/city-council/city-council-meeting-recap-august-8-2023/` says "On August 8, Josh Woods took the oath of office as the new Councilman for District 6". A fifth document offered in the review, `https://www.cityofmobile.gov/uploads/file_library/new-organizational-chart---for-council.pdf`, is marked "Draft as of October 12, 2020" and lists District 6 as Bess Rich; it is from before the window and is not cited. That the "Scott" of the 2021-11-02 minutes is Scott Jones written by his first name is likely and is an inference; no document read says so. The resolver in `src/docket/services/member_votes.py` answers to a surname and to an initial with a surname, never to a first name, so a row named `Scott Jones` does not answer to "Scott".

- Observation: a timestamp's fraction of a second is printed with one to three digits (`2026-11-10T12:03:58.71Z`, `2026-11-16T08:48:58.697Z`), which `datetime.fromisoformat` on Python 3.10 refuses for two digits.

The observations below were made on 2026-11-20 by the session that executed M1. It ran no request to any city's site and no production query.

- Observation (M1): the starting state was green. `./tools/verify`, run before any edit, ended `verify: all 6 checks passed in 320s.` (unit+web+services 187s, integration 120s, transcriber 12s).

- Observation (M1): all sixteen new tests fail on the unchanged adapter, as the author expected. The commit that holds this entry holds the two fixture pages and the tests, with `src/` untouched.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_civicclerk.py -q -p no:cacheprovider; tools/test-db --drop` printed `16 failed, 16 passed, 1 warning in 0.55s`; the sixteen failures are the sixteen names M1 lists (the unchanged adapter has no `_session`, so each fails where the test patches it), and the sixteen passes are the seventeen existing tests less `test_event_to_meeting_normalizes_z_suffix_to_central`, deleted as M1 says.

- Observation (M1): M1's acceptance was observed on the edited adapter. The single-file command printed `32 passed, 1 warning in 0.41s`; `./tools/verify` ended `verify: all 6 checks passed in 310s.` (unit+web+services 177s, integration 120s, transcriber 13s). Both were run after the last edit to `src/docket/adapters/civicclerk.py` and before the commit that holds it; nothing was edited while verify ran.

- Observation (M1): every rule M1 states is held by a test. Forty-five alterations of the adapter were tried, one at a time, on a copy of its source compiled in memory by a scratch pytest plugin (the committed file was not edited), and the test file was run against each. Forty-four failed a named test by assertion. The forty-fifth, the page limit taken out altogether, did not end in a failed assertion: the test's server never stops giving a next link, so the walk ran until the process died with no summary line (it was the one run that took minutes); the limit moved from 200 to 201 failed `test_list_meetings_follows_next_links_to_the_last_page` in the ordinary way. No alteration left every test passing, so no assertion was added after the commit that holds the tests failing (`22611fe`).
  Evidence: the run's last line was `45 removals tried, 45 failed a test, survived: []`. What was altered: the delay floor (removed; lowered to 0.5); the timeout; the number of attempts; the doubled second wait; the wait between attempts; the status check; the empty body; the body that is not JSON; the address in the error; a full address joined to the base; `requests.get` in place of the session; `$top` sent; `$skip` sent; the category filter; the date filter; the next link not followed; the next link's scheme, host, host case, path, and path-with-slash checks, each alone, and the check not called; the pause between pages; the page limit; the client-side `since` check; `eventId` read before `id`; the agenda id not remembered; `Z` converted to Central; a numeric offset not converted; the Agenda file not linked; the portal fallback removed, and given without `hasAgenda`; the minutes link given to an imported event, and not given at all; the file type not filtered; the latest file chosen as first in the list, last in the list, by publish time alone, and by file id alone; `createdOn` not turned into a Central date; an event created on its own date taken for an import; an unreadable `createdOn` keeping the link; the fraction of a second not cut off.

- Observation (M1): from M1 until M2, a failed agenda request is tried three times and is then still stored as "no items". `fetch_agenda_items` was not edited (it is M2's), and it still catches `requests.RequestException` and returns an empty list; its request now goes through the new `_get`, so a failure costs three attempts and two waits before that. It also still asks for `Meetings/{event id}`. Neither matters before a deploy, and no deploy precedes M2.

- Observation (M1): an `eventDate` that carried a fraction of a second of one or two digits would not parse on Python 3.10, and `_event_to_meeting` would then date the meeting today, as it did before this plan (`if meeting_date is None: meeting_date = date.today()`). No `eventDate` read while planning carried a fraction; M1 names the fraction rule for `createdOn` only, and the session left the fallback as it found it.

The observations below were made on 2026-11-20 by the session that executed M2. It ran no request to any city's site and no production query.

- Observation (M2): the starting state was green. `./tools/verify`, run before any edit, ended `verify: all 6 checks passed in 304s.` (unit+web+services 174s, integration 118s, transcriber 12s).

- Observation (M2): on the unchanged adapter the test file prints `20 failed, 25 passed`. The commit that holds this entry holds the fixture `meeting_473.json`, the thirteen new tests and the retitled assertions of `TestFlattenItems`, with `src/` untouched.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_civicclerk.py -q -p no:cacheprovider; tools/test-db --drop` printed `20 failed, 25 passed, 1 warning in 0.72s`. The twenty are nine of the thirteen `TestFlattenItems` tests (the nine whose title assertion dropped the number; the other four assert no title) and eleven of the thirteen new tests. The two new tests that pass before the change are `test_section_headings_are_not_items` and `test_an_empty_agenda_of_a_past_meeting_returns_no_items`: each holds something the adapter already did (a heading is not an item; an empty answer is an empty list), so neither can fail first, and what each has to hold after the change is shown by the removal check, recorded below.

- Observation (M2): the single-file command on the edited adapter printed `45 passed, 1 warning in 0.52s`, run after the last edit to `src/` and to the test file.

- Observation (M2): eight of the first fifty-nine alterations of the adapter left every test passing, so the tests as first committed (`11fc960`) did not hold eight clauses. Fifty-nine alterations were tried, one at a time, on a copy of the adapter's source compiled in memory by a scratch pytest plugin (the committed file was not edited), and the test file was run against each. First run: `59 removals tried, 51 failed a test, survived: [ 13 21 27 37 46 47 50 56 ]`. The eight: "no item" judged on the city's raw nodes and not on the flattened items (an agenda of headings alone for a coming meeting returned an empty list); the class attribute `items_carry_video_timestamps` set True; an item that is not a heading, with "consent" in its name, putting its children on the consent agenda; the first collapse of whitespace in `split_item_name` taken out; the sponsor pattern made case-sensitive; the sponsor not stripped; the collapse of whitespace after the parentheticals are removed taken out; and the 300-character cut applied before the submitter is joined as well as after. The last was no change of behaviour (a text cut to 300, joined and cut again is the same text as one joined and cut), so the alteration was rewritten to cut before the join and not after, which `test_description_is_read_from_the_citys_description_field` fails. The other seven each got an assertion inside a named test, listed in the Decision Log. Second run, the same fifty-nine with the one rewritten: `59 removals tried, 59 failed a test, survived: [ ]`.
  What was altered, beside the eight: `Meetings/{event id}` asked; the remembered agenda id ignored; no lookup for a meeting not listed; an agenda id of 0 requested; no pause after the agenda request; a failed request returning an empty list; `agendaIsPublish` not read, and an absent key taken for unpublished; an empty coming agenda returned as empty; an empty past agenda raised as not ready; `>` for `>=` on the date; "today" from `date.today()`, and from UTC; the lookup's filter on another field, and not sent; no pause after the lookup; the lookup taking any row returned; no such event taken for "no agenda"; an id that is not a number swallowed; the looked-up id not remembered; a heading's consent not passed down, read case-sensitively, and not inherited through a heading under it; an item's own name no longer marking it, and the heading's flag ignored on the item; the file number put before the title; an item with a number and no name kept; headings kept as items; the sponsor not stored, and the submitter stored as sponsor; the submitter not added to the description, replacing it, joined with no space, written without its full stop; no cut at 300; the description read from the old key only, the old key first, and with no fallback to it; tags and entities left in the description and in the name; the submitter pattern made case-sensitive and refusing a space after the parenthesis; the submitter not stripped; the last sponsor taken and not the first; either parenthetical left in the title; only the first match of a pattern taken out; the space before punctuation kept; the colon left out of the punctuation set.

- Observation (M2): from M2 until M3, a meeting whose agenda is not ready is reported as an error and left unmarked. `ingest_municipality` stage 3 (`src/docket/services/ingest.py` lines 140 to 143) catches `Exception` and appends `Agenda items for <id>: <error>`; `AgendaNotReady` is an `Exception` and M3 adds the clause that passes it by. On this branch a run for Mobile would therefore report one error for each scheduled meeting with no agenda (42 on 2026-11-20). No deploy precedes M3, and the session ran no ingest.

- Observation (M2): an item with a file number and an empty name is no longer an item. Before M2 the title was `"<number> <name>"`, so a number alone made a title; M2 says an item "is still left out when it is a heading or its title is empty" and the title is now the name alone. No such node was seen in an agenda read while planning; `test_title_is_the_citys_item_name_and_keeps_its_code` holds the rule.

- Observation (M2): the plan's M1 note that `fetch_agenda_items` "still asks for `Meetings/{event id}`" and stores a failure as "no items" is no longer true: both are mended by M2.

- Observation (M2): M2's acceptance was observed on the edited adapter. The single-file command printed `45 passed` (above); `./tools/verify` ended `verify: all 6 checks passed in 305s.` (unit+web+services 176s, integration 117s, transcriber 12s). Verify was run after the last edit to `src/` and `tests/` and before the commit that holds them; nothing was edited while it ran.

The observations below were made on 2026-11-20 by the session that executed M3. It ran no request to any city's site and no production query.

- Observation (M3): the starting state was green. `./tools/verify`, run before any edit, ended `verify: all 6 checks passed in 310s.` (unit+web+services 180s, integration 117s, transcriber 12s).

- Observation (M3): the three existing files of M3's acceptance command print `27 passed` at the session's start.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_ingest_hearings.py tests/integration/test_ingest_backfill_timestamps.py tests/unit/test_ingest_event_guard.py -q -p no:cacheprovider; tools/test-db --drop` printed `27 passed, 1 warning in 3.67s`.

- Observation (M3): on the unchanged ingest, seven of the ten new tests fail and three pass. The commit that holds this entry holds `tests/integration/test_ingest_backlog_settings.py`, with `src/` untouched.
  Evidence: the acceptance command (the new file and the three existing ones) printed `7 failed, 30 passed, 1 warning in 5.60s`. The three that pass before the change are `test_an_explicit_since_wins_over_the_floor`, `test_a_listed_file_link_replaces_a_stored_page_link` (as the author expected) and `test_a_city_with_neither_setting_ingests_as_before`: each holds something ingest already does and must still do, so none can fail first; what each holds after the change is shown by the removal check, recorded below.

- Observation (M3): two returns of `ingest_municipality` that this milestone does not edit raise instead of returning. `IngestResult` has seven fields with no default, and the returns for an unknown slug and for a listing that fails pass six values (`IngestResult(slug, 0, 0, 0, 0, [...])`), so each raises `TypeError: IngestResult.__init__() missing 1 required positional argument: 'errors'`. The worker's `ingest_all` and `ingest_afternoon` catch any exception per city and log it, so a failed listing is logged as that `TypeError` and the next city still runs; the text `Failed to scrape meetings: ...` is never seen. It was so before this plan (the lines are unchanged since before M1), M3 does not name it, and the session left it; M1's adapter now raises after three failed attempts on a listing, so this is the path a Mobile listing failure takes. It is for M6 to put in `docs/DEBT.md`. The new return M3 adds passes seven values, as M3 writes it.
  Evidence: `venv/bin/python -c "from docket.services.ingest import IngestResult; IngestResult('x',0,0,0,0,['e'])"` printed that `TypeError`; `grep -n "IngestResult(slug, 0, 0, 0, 0, \[" src/docket/services/ingest.py` printed lines 116 and 130.

- Observation (M3): M3's acceptance was observed on the edited ingest. The acceptance command printed `37 passed, 1 warning in 6.09s`, ten higher than the `27 passed` of the three existing files at the session's start; `./tools/verify` ended `verify: all 6 checks passed in 333s.` (unit+web+services 186s, integration 134s, transcriber 12s). Both were run after the last edit to `src/` and `tests/` and before the commit that holds them; nothing was edited while verify ran.

- Observation (M3): three of the first fifty alterations of ingest left every test passing, so the tests as first committed (`6cf11bc`), with the three assertions the session had added before the first run, did not hold three clauses. Fifty alterations were tried, one at a time, on a copy of the source of `src/docket/services/ingest.py` compiled in memory by a scratch pytest plugin (the committed file was not edited), and the new test file was run against each. First run: `50 removals tried, 47 failed a test, survived: [13, 16, 39]`. Number 13, two meetings on one date ordered by id and not by the adapter's order: the test's two tied pairs were listed with the higher id first, so both orders gave the same walk; the pairs were re-listed lower id first. Number 16, a stored agenda passed over once the cap is spent: in the test the one waiting meeting was the oldest, so the cap was never spent before a stored agenda was reached; the test now lists a waiting meeting that is the newest, and a second that is the oldest and is passed over. Number 39, a `backlog_floor` that is not text turned into text before it is read as a date, in place of being refused for not being text: on Python 3.10 nothing can tell the two apart, because no JSON value that is not text has a text form `date.fromisoformat` of 3.10 accepts (`20211101` becomes `"20211101"`, which 3.10 refuses and 3.11 reads as a date). The clause stays for the day the project's Python is newer, and the test holds that `20211101` is refused. Second run, the same fifty against the two changed tests: `50 removals tried, 49 failed a test, survived: [39]`.
  What was altered, beside those three: the floor not passed; the floor winning over a caller's `since`; a bad setting ignored, reported without `Bad adapter_config for`, reported without its reason, and reported after the listing was requested; `AgendaNotReady` not passed by with no cap, and under a cap; a meeting not ready counting as a fetch, and left out of "still waiting"; the cap's walk in the adapter's order, oldest first, and with tied dates reversed; `>` for `>=` on the cap; a meeting passed over left out of "still waiting"; a failed fetch not counting, left out of "still waiting", not reported, and reported without the meeting's id; a fetch not counting; a stored agenda counting; the items of a capped run not totalled; no log line, and the cap logged as the count; a cap of 0 taken for no cap; the walk with no cap sorted newest first; the cap ignored; the waiting query with `= FALSE` for `IS NOT TRUE`, with no condition on the mark, with no condition on the city, and with an inner join; the timestamp attribute not read, read with a default of False, and read under another name; each settings key renamed; an unreadable floor taken for no floor; the floor left as text; either error not naming its key; a cap that is true or false, not a whole number, text of digits, or below zero accepted; a cap of 0 refused; a config of None refused; and, in `_upsert_meetings`, the stored `agenda_url` kept over the listed one.

- Observation (M3): with the tests as they stand at the end of the session, the unchanged ingest still fails the same seven and passes the same three. The test file was edited after the commit that holds it failing (Decision Log), so the count was taken again.
  Evidence: the removal run's last lines, against the source of `src/docket/services/ingest.py` at `6cf11bc` compiled in memory: `unchanged ingest: 7 failed, 3 passed, 1 warning in 1.84s`, naming the same seven tests; and against the edited file with the plugin idle, `10 passed`.

- Observation (M3): the first run of the new tests on the edited ingest printed `1 failed, 36 passed`. `test_a_second_run_takes_the_next_meetings` used the fake adapter that says nothing about video timestamps, so its second run asked again for the two agendas the first had stored (the stored item has a number and no timestamp, which is debt row `D102`'s path) and the recorded fetches were four, not two. That is ingest doing what M3 says for an adapter that says nothing; the test was given the fake that sets `items_carry_video_timestamps = False`, as CivicClerk's adapter does.

- Observation (M3): a meeting whose agenda is stored is still passed to `_ingest_agenda_items` on every run, one SELECT a meeting (about 300 a run for Mobile); with the attribute False it returns 0 there and no request goes to the city. M3 says "passed to `_ingest_agenda_items` as today".

- Observation (M3): under a cap, "still waiting" in the log line counts the listed meetings that were waiting at the start of stage 3 and are still unmarked at its end: those the cap passed over, those not ready, and those whose fetch failed. A waiting meeting the adapter did not list (one dated before the floor) is not in it. For Mobile the 42 scheduled meetings with no agenda are in it every day.

The observations below were made on 2026-11-20 by the session that executed M4. It ran no request to any city's site and no production query.

- Observation (M4): the starting state was green. `./tools/verify`, run before any edit, ended `verify: all 6 checks passed in 335s.` (unit+web+services 189s, integration 133s, transcriber 12s).

- Observation (M4): `processing_status_audit` is still the one table whose foreign key to `agenda_items` neither cascades nor sets NULL, so the reset needs the four statements M4 names and no fifth.
  Evidence: `\d agenda_items` on the throwaway database (`psql "$(tools/test-db)" -c '\d agenda_items'`) printed nine tables under `Referenced by:`. `ON DELETE CASCADE`: `agenda_item_badges`, `agenda_item_search_cards`, `ai_batch_items`, `public_hearing_items`, `vote_agenda_items`. `ON DELETE SET NULL`: `agenda_item_badges_audit`, `minutes_discrepancies`, `transcript_segments`. Neither: `TABLE "processing_status_audit" CONSTRAINT "processing_status_audit_agenda_item_id_fkey" FOREIGN KEY (agenda_item_id) REFERENCES agenda_items(id)`.

- Observation (M4): on the unchanged ingest all five new tests fail. The commit that holds this entry holds `tests/integration/test_reset_agenda_items.py`, with `src/` and `scripts/` untouched. Each test imports `reset_agenda_items` inside the test function, so each fails at that import and the file collects.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_reset_agenda_items.py -q -p no:cacheprovider; tools/test-db --drop` printed `5 failed, 1 warning in 0.57s`, naming the five tests M4 lists.

- Observation (M4): M4's acceptance was observed on the edited code. The single-file command on `tests/integration/test_reset_agenda_items.py` printed `5 passed, 1 warning in 1.15s`; `./tools/verify` ended `verify: all 6 checks passed in 321s.` (unit+web+services 179s, integration 128s, transcriber 13s). Both were run after the last edit to `src/`, `scripts/` and `tests/` and before the commit that holds them; nothing was edited while verify ran.

- Observation (M4): `venv/bin/python scripts/reset_agenda_items.py --help` exited 0 and printed `usage: reset_agenda_items.py [-h] --city CITY [--apply]` with both options described.

- Observation (M4): the dry run against the worktree's development database printed the `database:` line, the eight counts and the closing line, and exited 0. That database holds Mobile's meetings and no agenda item for any city, so the dry run there shows the form of the output and not a deletion that would mean anything.
  Evidence: `venv/bin/python scripts/reset_agenda_items.py --city mobile` printed, in this order, `database: localhost/docket_db`, `meetings: 75`, `meetings_scraped: 56`, `meetings_with_summary: 13`, `agenda_items: 0`, `audit_rows: 0`, `vote_links: 0`, `transcript_segments: 0`, `minutes_discrepancies: 0`, `dry run: nothing changed`. The same for `--city birmingham` printed `meetings: 1005`, `meetings_scraped: 926`, `meetings_with_summary: 897` and zeros for the other five. `--city no_such_city` printed `database: localhost/docket_db`, then `Municipality 'no_such_city' not found` on stderr, and exited 2. `--apply` was not run against the development database; the tests are the only observation of an apply.

- Observation (M4): the refusal was seen only through the tests. No city of the development database has an agenda item, so the script's refusal of a city with vote links (Birmingham in production) could not be shown from the command line there; `test_a_city_with_vote_links_is_refused` holds it for the function, and the script only prints the function's `ValueError` and exits 2, the path the unknown city took above.

- Observation (M4): two of forty-seven alterations of the reset left every test passing, and both are the two M4 says have no seeded test. Forty-seven alterations were tried, one at a time, on a copy of the source of `src/docket/services/ingest.py` compiled in memory by a scratch pytest plugin (the committed file was not edited), and the new test file was run against each: `47 removals tried, 45 failed a test, survived: [ 6 7 ]`, then `5 passed` with the plugin idle. Number 6 takes `transcript_segments` out of the guard's condition and number 7 takes `minutes_discrepancies` out; seeding either table needs a transcript or a meeting event behind it, M4 names no seeded test for them, and M6 is to say so in the spec. Their counts are still read and still printed in the refusal (the alterations that drop either count from the message each fail `test_a_city_with_vote_links_is_refused`), so what no test can tell from its absence is only that a count above zero in either of those two tables refuses the city.
  What was altered, beside those two: an unknown slug returning an empty result, and refused without its name; the guard removed, applied only without `apply`, only with `apply`, and blind to vote links; the refusal not naming the city, and not giving each of the three counts; a dry run that writes; `apply` ignored; the audit DELETE removed, and run for every city; the items DELETE removed, and run for every city; the summary UPDATE run for every city, limited to meetings with an `executive_summary`, and with each of its five conditions taken out alone; each of the five columns left as it was; the re-opening UPDATE removed, run for every city, setting TRUE, and clearing `votes_scanned` as well; the count of meetings, of marked meetings and of summaries each taken over every city; marked counted as unmarked; summaries counted by `ai_prompt_version`; the city's items read over every city; the audit count and the vote-link count over every city; the vote-link count fixed at zero; and each of the four statements' row counts left out of the result.
  The first run of the check was on forty-eight; the forty-eighth removed a `logger.info` line the session had written after the transaction and it left every test passing, being a log line M4 does not ask for. The line was taken out of the code and the check run again on forty-seven.

- Observation (M4): that the four statements run in one transaction is not held by a test. The counts, the guard and the four statements all run on one connection inside one `with db() as conn:` block, which commits once when the block ends and rolls back if anything in it raises; no alteration tried could split that, and a test of it would need a statement made to fail midway. The refusal test does show that a `ValueError` raised inside the block leaves every row as it was.

- Observation (M4): with the tests as they stand at the end of the session, the unchanged ingest still fails all five. The test file was edited after the commit that holds it failing (Decision Log), so the count was taken again against the source of `src/docket/services/ingest.py` at `d721799` compiled in memory: `5 failed, 1 warning in 0.13s`.

- Observation (M4): a meeting of the city that has no `processing_status` row is not given one by the reset; it is already waiting (`_waiting_external_ids` reads a missing row as waiting, M3). And `meetings_reopened` counts every `processing_status` row of the city, marked or not, so it is the number of the city's meetings that have such a row, not the number that were marked; `meetings_scraped`, printed above it, is the number that were marked. The second apply in `test_apply_deletes_the_citys_items_and_reopens_its_meetings_only` shows both: `meetings_scraped` 0, `meetings_reopened` 2.

The observations below were made on 2026-11-20 by the session that executed M5. It ran no request to any city's site and no production query.

- Observation (M5): the starting state was green. `./tools/verify`, run before any edit, ended `verify: all 6 checks passed in 313s.` (unit+web+services 182s, integration 118s, transcriber 12s).

- Observation (M5): the session read no minutes file, so the one fact M5 leaves open, the last roll call that lists Jones, is still open, and the migration is written from the facts already in this plan, with Jones's term ending `2023-08-08`. The network was there (`git fetch origin` answered), but the session's own instructions said nothing outside the repository was available to it and that it must not go looking, so the 25 requests M5 allows were not spent. This is the branch M5 writes for a session with no network, taken for that other reason. The roll call of 2023-08-08 that seats Woods (file 701) is the evidence for the date; a day between 2023-03-28 and 2023-08-08 on which Jones had already left and Woods had not yet sat is a day on which the row `Scott Jones` still answers to "Jones", and a later session with leave to ask the city can move the date earlier.

- Observation (M5): the migration's number is `049`. `git fetch origin` then `git ls-tree --name-only origin/main src/docket/migrations/` printed `048_granicus_clip_sound.py` as the highest, and `gh pr list --state open` printed one pull request, #188 (`docs/afternoon-pass-first-observations`), whose diff against `origin/main` is three documentation files and no migration.

- Observation (M5): on the branch without the migration all five new tests fail. The commit that holds this entry holds `tests/integration/test_049_migration.py`, with `src/` untouched. The test file reads the migration module and the runner's list inside the test functions, so it collects.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_049_migration.py -q -p no:cacheprovider; tools/test-db --drop` printed `5 failed, 1 warning in 0.22s`, naming `test_049_a_second_run_adds_no_row_and_changes_none`, `test_049_the_seated_seven_are_the_active_members`, `test_049_every_surname_of_the_saved_roll_calls_resolves_on_its_date`, `test_049_names_that_must_not_resolve` and `test_049_down_restores_the_seeded_roster_and_the_up_applies_again`.



## Decision Log

- Decision: paging follows the server's `@odata.nextLink` exactly as given and the first request sends neither `$top` nor `$skip`.
  Rationale: `$top` is a total and the server pages at 15; a link followed verbatim carries the server's own `$skiptoken`. A link that does not begin with the adapter's own base address is refused, and a walk of more than 200 pages is an error, so a bad answer cannot send the worker elsewhere or loop.
  Date/Author: 2026-11-20, plan author.

- Decision: the backlog floor is the setting `backlog_floor` (a date, `YYYY-MM-DD`) in `municipalities.adapter_config`. `ingest_municipality` passes it to the adapter as `since` when the caller gave none, and the CivicClerk adapter sends it to the server as `eventDate ge <date>T00:00:00Z`.
  Rationale: the protocol already has `since`; a setting read in ingest serves every adapter, and a city without the key (Birmingham) is listed exactly as today. Filtering on the server keeps Mobile's daily listing at 21 pages (259 past and 42 scheduled events) and not 33.
  Date/Author: 2026-11-20, plan author.

- Decision: the per-run cap is the setting `agenda_fetch_cap` (a whole number, 0 or more) in `adapter_config`: at most that many meetings whose agenda is waiting are fetched in one run, newest meeting first. Absent means no cap and today's order. A meeting whose agenda is not ready does not count; a fetch that fails does.
  Rationale: 42 scheduled Mobile events are the newest rows and cost no request, so counting them would spend the whole cap on nothing every day; a failing site must not be asked again and again in one run.
  Date/Author: 2026-11-20, plan author.

- Decision: "no agenda yet" is an exception, `AgendaNotReady`, defined in `src/docket/models/protocol.py` and raised only by the CivicClerk adapter: when the event's `agendaId` is 0 or absent (no request is made), when the agenda the city returns says `agendaIsPublish` false, or when the agenda has no item and the meeting's date is today or later, "today" being the date in `America/Chicago`. `ingest` leaves such a meeting unmarked and reports no error. `hasAgenda` is not used to skip a request.
  Rationale: today an empty answer marks the meeting scraped and it waits for Monday's repair; GOALS.md asks for new records within a day. An exception no other adapter raises changes nothing for Birmingham. An agenda with no item for a past meeting (every imported Mobile agenda) still returns an empty list and is marked scraped, so it is asked for once and not daily. The revision added two things. The worker's clock is UTC, so `date.today()` calls a meeting past from 18:00 Central on its own day; the city's date is the one that counts. And an agenda the city has not published is not ready whatever it holds: five scheduled Mobile meetings had such a record on 2026-11-20. `hasAgenda` was true on all five, so it cannot spare the request; the cost is one request a day for each.
  Date/Author: 2026-11-20, plan author; amended the same day by the operator's review revision.

- Decision: a request that fails is an error, never "no items". The adapter holds one `requests.Session()` and every request goes through it with `timeout=(10, 30)` (ten seconds to connect, thirty to read). `_get` tries three times (waiting the delay, then twice the delay), treats an empty or unparseable body as a failure, and then raises; `fetch_agenda_items` lets it through. Ingest's stage 3 already records a raised error per meeting and leaves the meeting unmarked.
  Rationale: five of about sixty requests failed at the connection on the day of authoring, and one of twenty more during the review, each at the handshake. A session keeps the connection open across a listing's twenty pages, so there are fewer handshakes to fail, and a ten-second connect limit keeps one dead socket from costing three thirty-second waits.
  Date/Author: 2026-11-20, plan author; amended the same day by the operator's review revision.

- Decision: the adapter's delay is never below one second: `max(1.0, config delay)`, default 1.0.
  Rationale: GOALS.md's polite-delay constraint, and debt row `D175`. With the floor in code a stale `delay: 0.5` in a production row cannot make the adapter impolite; the operator's UPDATE still sets the row to 1.0 so the row says what happens.
  Date/Author: 2026-11-20, plan author.

- Decision: `eventDate`'s trailing `Z` is dropped and the time read as the city's wall clock. A numeric offset, never observed, is still converted to America/Chicago.
  Rationale: the city's minutes state 10:30 a.m. for an `eventDate` of `10:30:00Z`. The existing test that expects conversion of a `Z` time is replaced.
  Date/Author: 2026-11-20, plan author.

- Decision: the agenda link is the city's Agenda file (`{base}/Meetings/GetMeetingFileStream(fileId=N,plainText=false)`) when the event's `publishedFiles` has one, and otherwise today's portal page (`https://{tenant}.portal.civicclerk.com/event/{id}/agenda`) when `hasAgenda` is true. The minutes link is the Minutes file, and only for an event whose `createdOn` date is on or before its `eventDate` date; no other event gets a minutes link. Where an event has several files of one type, the file is the one with the latest `publishOn`, the higher `fileId` deciding a tie; and `createdOn`, which is a true UTC time, is turned into its `America/Chicago` date before it is compared with `eventDate`'s date, which is already the city's wall clock (both added by the revision: no event read had two files of a type, and a meeting entered after 18:00 Central on its own day would otherwise be taken for an import and lose its minutes link for good).
  Rationale: the file address was observed to return the PDF; the portal page is a script-built page no session can check, so it stays only as the fallback it already is. An event created after its own date is an after-the-fact import, and ten of the eleven imported Mobile minutes files read were another meeting's minutes; `docs/PRINCIPLES.md` "Source or silence" prefers no link to a wrong one. Stage 2, which reads the minutes, can pair an imported file to its meeting by the date printed on its first page. The Agenda Packet file is not stored.
  Date/Author: 2026-11-20, plan author; amended the same day by the operator's review revision.

- Decision: a CivicClerk item's stored title is the city's item name alone, with tags and entities removed and the "(sponsored by ...)" and "(submitted by ...)" parentheticals taken out; `item_number` stays the city's file number; `sponsor` is the "sponsored by" value; the submitter is kept as the sentence `Submitted by <value>.` at the end of the description. The file number is no longer prefixed to the title.
  Rationale: stage 2 joins votes to items by the code the minutes print as `RESOLUTION: 40-948-2026`, and the code is the first word of the name; a title that begins `2026-2408 01-1211 ...` hides it behind a file number. Splitting the parentheticals in the adapter fixes the wrong-sponsor defect without editing `src/docket/enrichment/sponsors.py`, which Birmingham's titles pass through; after the split, `enrich_agenda_item` finds no attribution in the title, so ingest's `enriched["sponsor"] or item.sponsor` keeps the adapter's value and `clean_title` returns the title unchanged. No new column: the code is recoverable from the stored title with `^(\d{2}-\d{3,4})\b`, and a test holds that.
  Date/Author: 2026-11-20, plan author.

- Decision: an adapter says whether its items carry video timestamps: the class attribute `items_carry_video_timestamps`, `False` on `CivicClerkAdapter`, read in ingest with `getattr(adapter, "items_carry_video_timestamps", True)`.
  Rationale: it stops the daily re-fetch of every stored CivicClerk agenda without touching `src/docket/adapters/granicus.py`; an adapter that says nothing behaves as today.
  Date/Author: 2026-11-20, plan author.

- Decision: `repair_empty_agendas` is not changed. Stuck and wrongly filled meetings are put right by a supervised reset the operator runs once per city, `scripts/reset_agenda_items.py`, which deletes the city's stored agenda items, clears the AI summary of each of the city's meetings, and clears `agenda_items_scraped` on its meetings, in one transaction; the daily ingest then refills, newest first, under the cap.
  Rationale: every CivicClerk item stored before this plan was fetched under an event id and is suspect, and no predicate in the database can tell a right item from a wrong one. Widening the weekly repair to the backlog floor was considered and dropped: it would re-open Mobile's 135 imported meetings, which can never have items, every Monday. The reset refuses a city whose items carry vote links or transcript links, so it cannot be turned on Birmingham. Four statements in one transaction, each scoped to one city, is within decision `0026`; a few thousand rows is far from the 57,000-row sweep that decision records. The summary is cleared (added by the revision) because a summary written from another meeting's items is as wrong as the items, and `docs/PRINCIPLES.md` "Source or silence" prefers no summary to that one; as authored the plan left it live and asked the operator to read one afterwards. Clearing `ai_prompt_version` with it is what lets the meeting stage write a new summary once the refilled items have theirs.
  Date/Author: 2026-11-20, plan author; amended the same day by the operator's review revision.

- Decision: both CivicClerk cities take the same settings, `{"delay": 1.0, "backlog_floor": "2021-11-01", "agenda_fetch_cap": 10}`, and Vestavia Hills keeps listing every body, as its production row does today.
  Rationale: the goal says settings, not a special case. The floor is before Vestavia's first event (2023-03-13), so it costs that city nothing. Ten agendas a run is about 550 Mobile items a day and refills Mobile's 124 structured meetings in about two weeks; the AI pipeline, at `AI_MAX_BATCH_SIZE` 200 items a run under `AI_DAILY_BUDGET_USD`, is the slower stage either way. Changing which Vestavia bodies are scraped is outside the goal.
  Date/Author: 2026-11-20, plan author.

- Decision: no new mechanism for AI summaries. The item claim in `src/docket/ai/worker.py` (`claim_items_v3_sql`) already orders by meeting date, newest first, across cities.
  Rationale: Mobile's structured backlog is about 124 meetings at 51 to 60 items, about 6,800 items, about 34 daily runs at 200, not the 18,000 items and 90 runs the brief estimated. Newest-first across cities means a Birmingham item waiting from before a pending Mobile meeting's date waits longer while the backlog drains; the operator's query Q6 shows how many such items there are, and the closing milestone records the figure the operator reports as the thing to watch, not a defect to fix here.
  Date/Author: 2026-11-20, plan author.

- Decision: the roster goes in by a new numbered migration (decision `0004`), matching rows by surname within Mobile, with `term_start` the date of the first roll call this project has read that lists the member and `term_end` the date of the first roll call that lists the successor.
  Rationale: the resolver in `src/docket/services/member_votes.py` needs a member seated on the days they vote and nothing finer, and a date taken from a city document can be checked; an inauguration date from outside notes cannot. One row per person covers a member who sat through both terms. A member who left is named as the city's documents name them; where no city document read gives a first name, the surname alone is stored. The revision found the documents: the city's financial report for fiscal 2022 and its organisational chart of March 2025 name Joel Daves in District 5 and Scott Jones in District 6 (Surprises), so both are stored in full and their districts are stated by a document, not read from the order of a roll call. Rows are matched by a whole-word surname, since `ILIKE '%<surname>'` misses a name that ends in a suffix.
  Date/Author: 2026-11-20, plan author; amended the same day by the operator's review revision.

- Decision: `D12`'s trigger ("Before the next backfill wave") is reworded by the closing milestone to name Birmingham, and the row gains a dated note that Mobile's and Vestavia's backlog ran without it.
  Rationale: the row is about Birmingham consent items whose body text is in the minutes PDF; a CivicClerk backlog neither touches nor worsens them.
  Date/Author: 2026-11-20, plan author.

- Decision: migration numbers, decision numbers and debt ids are not fixed here. The session that needs one takes the lowest number above every one spent on `origin/main` and on any open pull request at that moment (debt row `D70`).
  Rationale: the plan-author procedure; on 2026-11-20 the highest spent were migration `048`, decision `0117`, debt id `D177`, and the one open pull request (#188, `docs/afternoon-pass-first-observations`) was a documentation branch.
  Date/Author: 2026-11-20, plan author.

- Decision: a CivicClerk item is a consent item when the nearest heading above it in the agenda's tree has "consent" in its name, or, as today, when its own name does. The heading itself is still not an item.
  Rationale: the city says which items are on its consent agenda by where it puts them, under `CONSENT RESOLUTIONS HELD OVER` and `CONSENT RESOLUTIONS BEING INTRODUCED`; today's rule looks only at the item's own name and marks none of them. `enrich_agenda_item` already takes the flag for the consent-placement score, and stage 2 needs it to say why an item has no roll call. Carrying it now costs a few lines; carrying it later means fetching and enriching about 6,800 items again. This lifts one exclusion the plan was authored with ("any change to how `is_consent` is decided"), for CivicClerk only; the Granicus adapter is untouched. The fixture's items are put under their real headings so the test reads what the city sent.
  Date/Author: 2026-11-20, the operator's review revision (written by Claude at the operator's request).

- Decision: `_upsert_meetings` is not changed. A test in M3 holds that a stored portal-page link becomes the file link on a later run.
  Rationale: the review feared the upsert kept the first link it stored. It does not: both statements write the listed link outright. Birmingham's meetings pass through the same statements, so they stay as they are.
  Date/Author: 2026-11-20, the operator's review revision (written by Claude at the operator's request).

- Decision: an agenda fetched before its meeting is not fetched again, and that is recorded as debt by the closing milestone, not solved here.
  Rationale: the city published the agenda of 2026-11-24 four days ahead. If it adds an item after ingest has stored the agenda, this plan never sees the item. Whether Mobile does that was not observed, and a rule for when to look again (once after the meeting, or when the minutes arrive) changes how many requests a day the city is sent; stage 2, which reads the minutes, will show whether stored agendas and minutes disagree.
  Date/Author: 2026-11-20, the operator's review revision (written by Claude at the operator's request).

- Decision: the operator's steps take one city at a time. Both cities' settings are written before the deploy, with Vestavia Hills' `agenda_fetch_cap` at 0; Mobile is reset, refilled by one ingest run started by hand, and checked; only then is Vestavia Hills' cap raised and that city reset. This replaces the authored decision's "both cities take the same settings" for the days between the two resets; afterwards the rows are the same.
  Rationale: Vestavia Hills lists seven bodies and no agenda of the other six was read while planning, so the first proof is Mobile. The settings go in first because the code that reads them is harmless to the code that does not (`config.get` ignores a key it does not know), and with the cap at 0 the mended adapter lists Vestavia Hills' meetings but fetches none of their agendas, so the AI stage is not spent on items the reset is about to delete. The run by hand after a reset is there so the city's page is not left with fewer items than before until the next morning.
  Date/Author: 2026-11-20, the operator's review revision (written by Claude at the operator's request).

- Decision: Q3 is no longer a condition of the merge. It was answered on 2026-11-20 (Surprises) by comparing stored item ids with the city's answers, which is the only way to tell right items from wrong ones; the query stays in a wider form as a look before each reset.
  Rationale: as authored Q3 looked at one meeting and passed on no rows; a wider query alone shows id ranges nobody can judge without asking the city what each agenda holds.
  Date/Author: 2026-11-20, the operator's review revision (written by Claude at the operator's request).

- Decision (M1): a next link's host is compared as the whole network location (`urlsplit(...).netloc`, case ignored), not as the hostname alone.
  Rationale: M1 says "the host equals the base address's host". The hostname alone ignores a port and a `user@` prefix, so `https://mobileal.api.civicclerk.com:8443/v1/...` would pass; the base address has neither, so comparing the whole location refuses both and accepts everything the hostname comparison should. The test refuses six links (another host, the city's host as a prefix of another, the city's host as a `user@` part, `http`, a path under `/v2/`, a path `/v1Events`) and accepts the city's host in mixed case.
  Date/Author: 2026-11-20, M1 session.

- Decision (M1): an event with no `createdOn`, or one that cannot be read as a time, is treated as imported and gets no minutes link; an entry of `publishedFiles` with no `fileId` is not a file.
  Rationale: M1 gives the minutes link "only when `createdOn` is present" and says nothing of one that is present and unreadable; `docs/PRINCIPLES.md` "Source or silence" decides it the same way. A file entry without an id cannot be linked. Neither case was seen in the city's answers.
  Date/Author: 2026-11-20, M1 session.

- Decision (M1): the rules M1 states but names no test for are asserted inside the sixteen named tests, not in further tests, so the count stays `32 passed`.
  Rationale: the acceptance fixes the count. Added inside named tests: a listing that does not end raises `ValueError` after exactly 200 requests, the one pause between pages, and the remembered agenda ids (in `test_list_meetings_follows_next_links_to_the_last_page`); the category filter alone, no filter at all, and the client-side `since` check (in `..._asks_for_events_on_or_after_since`); the `(10, 30)` timeout (in `test_get_retries_a_timeout_then_succeeds`); the two waits and a rejected status (in `test_get_raises_after_three_failures`); a body that is not JSON (in `test_get_treats_an_empty_body_as_a_failure`); a numeric offset converted to Central (in `test_start_time_is_the_posted_wall_clock_time`); `id` read before `eventId` (in `test_agenda_link_falls_back_to_the_event_page_without_an_agenda_file`); publish time over list order and file id, and the tie (in `test_the_latest_file_of_a_type_is_the_one_linked`); an absent `createdOn` (in `test_no_minutes_link_for_an_event_created_after_its_date`). The tests hand the adapter real `requests.Response` objects, so they do not depend on which attribute of a response the adapter reads.
  Date/Author: 2026-11-20, M1 session.

- Decision (M1): `_get` knows a full address by its beginning (`https://` or `http://`) and then sends no params; `_minutes_portal_url` is deleted.
  Rationale: M1 leaves the form of "either an endpoint or a full address" open; one argument keeps the two existing callers unchanged. Nothing else in `src/`, `tests/` or `scripts/` named `_minutes_portal_url` (searched before deleting).
  Date/Author: 2026-11-20, M1 session.

- Decision (M2): the lookup for a meeting this instance did not list takes only the row whose id equals the number asked for; any other answer raises `ValueError`.
  Rationale: M2 says "raises `ValueError` if the server returns no such event". A server that ignored the filter would return the newest events, and taking the first row would attach another meeting's agenda, the defect this plan exists to remove. The looked-up id is remembered in `self._agenda_ids`, as a listed one is (the row is read through `_event_to_meeting`, which records it).
  Date/Author: 2026-11-20, M2 session.

- Decision (M2): the pause after the `Meetings/<agenda id>` request comes straight after the request, before `agendaIsPublish` is read, so a fetch that ends in `AgendaNotReady` has paused as well.
  Rationale: M2 says "requests `Meetings/<agenda id>` and sleeps the delay" and then lists what the answer may raise; ingest calls the adapter again at once for the next meeting, so a not-ready answer that skipped the pause would send the city two requests with nothing between them. Five scheduled Mobile meetings had an unpublished agenda record on 2026-11-20.
  Date/Author: 2026-11-20, M2 session.

- Decision (M2): a heading's "cleaned name" is the title `split_item_name` returns for it, and the heading test is the one `_flatten_items` had (`isSection`, or no number and at least one child). The children of a node that is an item (it has a number) are walked with the value the node itself was walked with, whatever the node's name says.
  Rationale: M2 gives the rule for headings only and says the heading is known "by the test the function already uses". An item with children was not seen in any agenda read ("no item has children", Surprises); passing the flag through unchanged is the reading that marks nothing the city did not put under a consent heading.
  Date/Author: 2026-11-20, M2 session.

- Decision (M2): "today in America/Chicago" is held by a test that replaces the adapter module's `datetime` with a clock fixed at 2026-11-18 01:00 UTC (19:00 on the 17th in Mobile): an empty agenda for the 17th is not ready, and for the 16th is an empty list. The named tests' "yesterday" and "tomorrow" are taken from the real clock in `America/Chicago`.
  Rationale: with the real clock alone, a test run at most hours cannot tell the city's date from the worker's; the removal check showed `date.today()` and a UTC date each fail only the fixed-clock assertion.
  Date/Author: 2026-11-20, M2 session.

- Decision (M2): the rules M2 states but names no test for are asserted inside the thirteen named tests, so the count stays `45 passed`. In the commit that holds the tests failing (`11fc960`): the pause after each request, no request to `Events` for a listed meeting, the three `ValueError` cases of the lookup, the lookup as the only request for an unlisted event with no agenda, an answer without `agendaIsPublish`, a meeting dated today, the fixed clock, an agenda of headings alone for a past meeting, a failed lookup, the consent flag through a heading under a consent heading and its end at the next heading, an item whose own name says consent, an item with a number and no name, the worked results of `split_item_name` from Interfaces and Dependencies with three built names, and the description's key order, join and cut. Added after that commit, in the commit that holds the adapter, because the removal check found the clause unheld: `CivicClerkAdapter.items_carry_video_timestamps is False` (in `test_items_come_from_the_events_agenda_id`); an agenda of headings alone for a coming meeting raises `AgendaNotReady` (in `test_an_empty_agenda_of_a_coming_meeting_raises_agenda_not_ready`); an item, not a heading, named `Consent to an assignment` does not put its child on the consent agenda (in `test_an_item_under_a_consent_heading_is_a_consent_item`); and `split_item_name("Pay ( Sponsored By  Council\xa0 Member Small ) the claim")` gives `("Pay the claim", "Council Member Small", None)` (in `test_sponsor_and_submitter_are_split_from_the_name`), which holds the sponsor pattern's case, the sponsor's strip and both collapses of whitespace. The built names and trees are marked as built in the tests; they are not rows the city sent.
  Date/Author: 2026-11-20, M2 session.

- Decision (M3): `agenda_fetch_cap` must be a JSON whole number: true, false, a number with a fraction part written (`2.0`), text (`"10"` as well as `"ten"`), and a number below zero are each refused. `backlog_floor` must be text that `date.fromisoformat` reads. A key that is absent or null is no setting. A config of None is read as an empty one.
  Rationale: M3 says "an `int` of 0 or more (a `bool` is refused)" and "a value that does not parse" is reported. A row that says `"10"` is a typing slip the operator should see on the first run, not a cap silently honoured or silently dropped; null is the usual way to write "none" in JSON and removing the key is how Idempotence and Recovery says to go back. Each error names its key, so the one error line of the result says which setting to mend.
  Date/Author: 2026-11-20, M3 session.

- Decision (M3): the settings are read after the adapter is built and before stage 1, and a bad one returns before `list_meetings`; the returned result is all zeros with the one error.
  Rationale: M3's words. Building the adapter makes no request (CivicClerk's `__init__` creates a session and sends nothing), so "before any request" holds.
  Date/Author: 2026-11-20, M3 session.

- Decision (M3): the capped walk is `sorted(raw_meetings, key=meeting_date, reverse=True)`, which keeps the adapter's order between two meetings on one date; the log line is written only under a cap, at INFO, once a run; and its "still waiting" is the count described in Surprises (listed, waiting at the start, unmarked at the end).
  Rationale: M3 gives the line's words and not what `<k>` counts. Counting only listed meetings is what the run itself can act on, and it needs no second query. A city with no cap logs nothing new, so Birmingham's log is unchanged.
  Date/Author: 2026-11-20, M3 session.

- Decision (M3): under a cap, a meeting that is not waiting is passed to `_ingest_agenda_items` whether or not the cap is spent, and an `AgendaNotReady` or an error raised there is handled as for a waiting meeting but never counts.
  Rationale: M3 says such a meeting "is passed to `_ingest_agenda_items` as today and never counts". For an adapter that says nothing about video timestamps this is the daily backfill of a stored agenda, which a cap on new agendas must not switch off.
  Date/Author: 2026-11-20, M3 session.

- Decision (M3): the check of `items_carry_video_timestamps` comes first in the already-scraped branch, before the `event-` test, and returns 0.
  Rationale: M3 says the branch "calls `_backfill_video_timestamps` only when" the attribute is true "and returns 0 otherwise"; both orders give the same result, and this one reads as the rule is written.
  Date/Author: 2026-11-20, M3 session.

- Decision (M3): the rules M3 states but names no test for are asserted inside the ten named tests, so the acceptance total stays ten higher. In the commit that holds the tests failing (`6cf11bc`): the floor alone sets no cap; the log line's words and counts; a cap of 0; two meetings on one date; a third and fourth run; `AgendaNotReady` with no cap; a stored agenda not fetched again under a cap; a stored agenda fetched again under a cap without counting; every bad value of either setting, through `_backlog_settings` and through `ingest_municipality`, and what a good row gives. Changed or added after that commit, in the commit that holds the ingest edits: `test_a_second_run_takes_the_next_meetings` uses the fake adapter that says its items carry no timestamps (Surprises: the first run of the edited ingest); the log line of a run with a failed fetch (in `test_a_failed_fetch_is_reported_left_unmarked_and_counted`); another city's waiting meeting with the id of a stored one, and a waiting meeting that is the newest so the cap is spent before the stored agendas are reached (in `test_a_stored_agenda_is_not_fetched_again_when_items_carry_no_timestamps`; the first before the removal check, the second because of it); `_backlog_settings(None)` (in `test_a_bad_setting_is_reported_and_nothing_is_fetched`); and the tied meetings listed lower id first (in `test_cap_fetches_the_newest_waiting_meetings_first`, because of the removal check). Every meeting, id and link in the file is built in the tests; none is a row a city sent.
  Date/Author: 2026-11-20, M3 session.

- Decision (M3): the two returns of `ingest_municipality` that raise `TypeError` (Surprises) are not mended here.
  Rationale: they are outside M3's stated work and were so before this plan; a fix would land with no acceptance of its own. M6, which writes this plan's debt rows, is where it is recorded, and its row should say that a failed CivicClerk listing is logged by the worker as a `TypeError` and not as the city's failure.
  Date/Author: 2026-11-20, M3 session.

- Decision (M4): the counts are returned under the keys `meetings`, `meetings_scraped`, `meetings_with_summary`, `agenda_items`, `audit_rows`, `vote_links`, `transcript_segments`, `minutes_discrepancies`, and an apply adds `audit_rows_deleted`, `agenda_items_deleted`, `summaries_cleared`, `meetings_reopened`, in that order. The script prints each as `<key>: <number>`, one a line, in that order.
  Rationale: M4 names what is counted and not the keys. M6's spec and the operator's step 4 ("the dry run's item count should match Q4's `items`") read these names, so they are fixed here: the line to compare with Q4 is `agenda_items`.
  Date/Author: 2026-11-20, M4 session.

- Decision (M4): the refusal reads `Refusing to reset '<slug>': its agenda items carry <n> vote links, <n> transcript segments and <n> minutes discrepancies`, with all three counts whichever is above zero; an unknown slug reads `Municipality '<slug>' not found`, the words `correct_chapter_ids` already uses.
  Rationale: M4 says "raises `ValueError` naming the counts". All three in one line tells the operator the whole of what hangs on the city's items in one run.
  Date/Author: 2026-11-20, M4 session.

- Decision (M4): the counts, the guard and the four statements run on one connection in one transaction (`with db() as conn:`), not the counts in one and the writes in another.
  Rationale: M4 says the four statements run in one transaction; reading the guard's counts in the same one means a vote link written between a separate count and the delete cannot slip past the guard at the default isolation level any more easily than it must. No lock is taken: the reset is run by hand, once a city, after the morning's ingest has finished (Validation and Acceptance).
  Date/Author: 2026-11-20, M4 session.

- Decision (M4): the re-opening UPDATE sets `agenda_items_scraped = FALSE` on every `processing_status` row of the city with no condition on the mark, and creates no row for a meeting that has none.
  Rationale: M4's words ("an UPDATE setting `agenda_items_scraped = FALSE` on the city's `processing_status` rows"). A meeting with no row is already waiting. The cost is that the statement's row count is not "meetings that were marked" (Surprises).
  Date/Author: 2026-11-20, M4 session.

- Decision (M4): the script takes the host and the database name from `docket.config.DATABASE_URL` with `urllib.parse.urlsplit` (`hostname`, and the path without its leading slash), prints `localhost` for a URL with no host, and flushes that line before it calls the function.
  Rationale: M4 says the line is first and holds "nothing else of" the URL; `hostname` leaves out the user, the password and the port. Without the flush, a refusal written to stderr came out above the `database:` line when the output was piped (seen on the first run of `--city no_such_city`); the operator reads the line to know which database a refusal is about.
  Date/Author: 2026-11-20, M4 session.

- Decision (M4): the script has no test of its own.
  Rationale: M4 names five tests, all of the function, and gives the script's acceptance as two commands run by the session (Surprises holds what they printed). The script is argument parsing, one call and printing.
  Date/Author: 2026-11-20, M4 session.

- Decision (M4): the rules M4 states but names no test for are asserted inside the five named tests, so the count stays `5 passed`. In the commit that holds the tests failing (`d721799`): the exact counts of a dry run and of an apply; a meeting with no `processing_status` row left without one; `votes_scanned`, the titles and the links unchanged; a second apply; a meeting with no `executive_summary` and an `ai_prompt_version` cleared; the refusal's words; and an unknown city refused with and without `apply`. Added after that commit, in the commit that holds the function, before the removal check was run: each of `executive_summary`, `executive_summary_voice`, `ai_metadata` and `ai_generated_at`, set alone on a meeting, is cleared (in `test_apply_clears_the_citys_meeting_summaries_only`), and a second city with no vote link is not refused because the first has one (in `test_a_city_with_vote_links_is_refused`). Every city, meeting, item, vote and summary in the file is built in the tests; none is a row a city sent.
  Date/Author: 2026-11-20, M4 session.



## Outcomes & Retrospective

As authored on 2026-11-20, nothing has been executed and there is no outcome to report. The closing milestone writes what M1 to M5 achieved against the Purpose above, what the operator still has to run, and what was left undone.

M1, 2026-11-20: done, with no carve-out against its acceptance. `CivicClerkAdapter.list_meetings` walks the server's next links, sends the date floor to the server, never waits less than a second, retries a failed request twice, and gives each meeting its posted time and the city's own agenda and minutes files; `self._agenda_ids` holds each listed event's agenda id for M2. Observed: `32 passed` on the test file, `verify: all 6 checks passed in 310s.` Nothing was run against a city's site or production, so what the adapter does with the city's real answers is still unobserved; the fixtures are the only evidence. Next is M2.

M2, 2026-11-20: done, with no carve-out against its acceptance. `CivicClerkAdapter.fetch_agenda_items` asks for `Meetings/<the event's agenda id>` (looking the id up with one `Events` request when this instance did not list the meeting), raises `AgendaNotReady` (new, in `src/docket/models/protocol.py`) for no agenda record, an unpublished agenda, or no item on a date that is today or later in `America/Chicago`, and lets a failed request raise. Each item is titled with the city's own name, code first, with sponsor and submitter split out by the new `split_item_name`, the submitter kept as a sentence in the description, and `is_consent` set from the heading above it; the class says `items_carry_video_timestamps = False`. Observed: `45 passed` on the test file, `verify: all 6 checks passed in 305s.` Nothing was run against a city's site or production; the fixture is the only evidence of what the city sends. Until M3, ingest reports a not-ready meeting as an error (Surprises). Next is M3.

M3, 2026-11-20: done, with no carve-out against its acceptance. `ingest_municipality` reads `backlog_floor` and `agenda_fetch_cap` from the city's `adapter_config` through the new `_backlog_settings`, reports a value it cannot read as the run's one error before any request, passes the floor to the adapter as `since` when the caller gave none, and under a cap fetches the waiting agendas newest meeting first (`_waiting_external_ids` says which wait), counting a failed fetch and not a meeting that is not ready. `AgendaNotReady` is passed by, with or without a cap: the meeting stays unmarked and nothing is reported, which ends the state M2 left. A stored agenda is not fetched again for an adapter that sets `items_carry_video_timestamps = False`. A city with neither setting is listed and fetched as before, and `_upsert_meetings` is untouched. Observed: `37 passed` on the acceptance command against `27 passed` at the start, `verify: all 6 checks passed in 333s.` Nothing was run against a city's site or production; the fake adapter of the test file is the only evidence, and no test runs the real CivicClerk adapter through ingest. Left for M6 to record: two older returns of `ingest_municipality` raise `TypeError` (Surprises). Next is M4.

M4, 2026-11-20: done, with no carve-out against its acceptance. `reset_agenda_items(slug, *, apply=False)` in `src/docket/services/ingest.py` counts what one city holds, refuses an unknown city and a city whose items carry vote links, transcript segments or minutes discrepancies, and with `apply=True` deletes the city's `processing_status_audit` rows and agenda items, sets the five summary columns of its meetings to NULL, and sets `agenda_items_scraped` FALSE on its `processing_status` rows, in one transaction with the counts; `scripts/reset_agenda_items.py --city <slug> [--apply]` prints the database's host and name, the counts, and `dry run: nothing changed` or `applied`, and exits 2 on a refusal. Observed: `5 passed` on the test file, the help and the dry run on the development database (Surprises), `verify: all 6 checks passed in 321s.` Not observed: an apply from the command line, and the script against a database that holds agenda items; the development database holds none, so the first real dry run is the operator's step 4. The guard's `transcript_segments` and `minutes_discrepancies` halves have no seeded test, as M4 says, and M6 is to say so in the spec; the key names and the wording of the output are in the Decision Log for M6's spec. Next is M5.



## Context and Orientation

### The terms this plan uses

CivicClerk is the vendor system two cities use to publish meetings: Mobile (tenant `mobileal`) and Vestavia Hills (tenant `vestaviahillsal`). Its public read address is `https://{tenant}.api.civicclerk.com/v1/`, which needs no login. An event is one meeting on the city's calendar; `Events` lists them. An event carries `id`, `eventName`, `eventDate`, `createdOn`, `eventCategoryId` (26 is City Council in both cities), `agendaId`, `hasAgenda`, and `publishedFiles`, a list of files each with `fileId`, `type` (`Agenda`, `Agenda Packet`, `Minutes`), `name` and `publishOn`. An agenda is a separate record: `Meetings/{agendaId}` returns it, with `items`, a tree whose nodes carry `id`, `isSection` (1 for a heading), `agendaObjectItemName`, `agendaObjectItemNumber`, `agendaObjectItemDescription` and `childItems`. A next link is the address of the following page, which the server puts in `@odata.nextLink`.

An adapter is the class that reads one vendor's system and returns the dataclasses in `src/docket/models/protocol.py` (`RawMeeting`, `RawAgendaItem`); `src/docket/adapters/civicclerk.py` is CivicClerk's. `adapter_config` is the JSONB column on `municipalities` that holds a city's adapter settings. Ingest is `src/docket/services/ingest.py`: `ingest_municipality(slug, since=None)` lists meetings, upserts them, fetches agenda items for meetings not yet marked, and runs later stages. The worker task `ingest_all` (`src/docket/worker/tasks.py`, daily at 06:00 Central by `src/docket/worker/scheduler.py`) calls it for every active city with no `since`. `processing_status.agenda_items_scraped` is the per-meeting mark that the agenda has been fetched. An imported event, in this plan, is one whose `createdOn` date is later than its `eventDate` date: the city loaded it after the meeting was held.

A factory session is the fresh agent session that executes one milestone of this plan in the worktree `.claude/worktrees/mobile-agendas-flow-again` on branch `plan/mobile-agendas-flow-again`. It has no browser and cannot reach production. The operator is the one person who runs this project; the operator's machine is "the Legion", with the repository's main checkout at `~/docket-pub` in WSL.

### The adapter as it stands

`CivicClerkAdapter.__init__` reads `tenant`, `category_id` (None means every category) and `delay` (default 0.5). `_get(endpoint, params)` is one `requests.get` with a 30 second timeout, `raise_for_status`, and `resp.json()`. `list_meetings` requests `Events` with `$top=100`, `$skip`, `$orderby=eventDate desc`, `$count=true` and an optional category filter, adds 100 to `$skip` until it passes `@odata.count`, and ignores the next link, so it sees 15 of every 100 events. `_event_to_meeting` converts a `Z` time to America/Chicago, sets `agenda_url` to the portal page when `hasAgenda` is true, and sets `minutes_url` only when `hasMinutes` is true, a key the events do not carry. `fetch_agenda_items` requests `Meetings/{meeting.external_id}`, the event id, catches any `requests.RequestException` and returns an empty list. `_flatten_items` walks the tree, skips headings, reads the description from a key named `description` (the city's key is `agendaObjectItemDescription`), and titles each item `"<agendaObjectItemNumber> <name>"`. `tests/unit/test_civicclerk.py` holds 17 tests: 13 in `TestFlattenItems`, 4 in `TestEventToMeetingStartTime`.

### Ingest as it stands

Stage 3 of `ingest_municipality` loops over the listed meetings in the adapter's order and calls `_ingest_agenda_items(municipality_id, adapter, raw_meeting)` inside a `try` that appends `"Agenda items for <id>: <error>"` to the result's errors. `_ingest_agenda_items` reads the meeting's row and mark; if marked, and the external id does not begin `event-`, it calls `_backfill_video_timestamps` (which fetches the agenda again whenever a numbered item lacks a video timestamp); if not marked, it calls `adapter.fetch_agenda_items`, and on an empty answer marks the meeting scraped ("so we don't re-try"). Items are inserted with `ON CONFLICT (meeting_id, external_id) DO NOTHING` after `enrich_agenda_item(item.title, item.description, item.is_consent)`; the stored sponsor is `enriched["sponsor"] or item.sponsor` and the stored title `enriched["clean_title"] or item.title`. Stage 4 calls `_ingest_votes` for every listed meeting with a `minutes_url`; `CivicClerkAdapter.fetch_votes` returns an empty list, so the meeting is marked `votes_scanned`. Stage 2, which reads votes from Mobile's minutes, will have to clear that mark; nothing here depends on it.

`repair_empty_agendas` (`src/docket/services/maintenance.py`, Mondays 05:00) clears `agenda_items_scraped` for any city's meeting dated within 18 months that has an `agenda_url`, the mark, no items, and no "cancelled" in its title. This plan does not change it. Its tests are `tests/integration/test_maintenance_repair.py`.

### Every reader of what this plan changes

`processing_status.agenda_items_scraped` is read by `_ingest_agenda_items`, by `repair_empty_agendas`, and by `src/docket/services/archived_meetings.py` (line 201, the Birmingham archive backfill, which reads its own rows). The only new transition is that a CivicClerk meeting whose agenda is not ready stays unmarked where it was marked before. An unmarked meeting with no items is what a newly inserted row already is, and each reader already meets that state. No documented hand statement writes the column: a search of `docs/runbooks/` and `docs/specs/` for `agenda_items_scraped` finds only the task inventory line in `docs/runbooks/cron-worker.md` and one sentence in `docs/birmingham/02-ingest.md`, neither a statement to paste.

`meetings.minutes_url` becomes non-NULL for CivicClerk meetings for the first time. Its readers, and what each does with a Mobile or Vestavia row that has one: the meeting page shows the "minutes" link (`src/docket/web/templates/meeting_detail.html` line 425), which is the purpose; `recast_post_meeting_ai` in `src/docket/worker/tasks.py` re-queues items summarised in the "upcoming" voice once the meeting is past and has minutes or video, so a Mobile meeting's items are re-summarised once after its minutes are published, a cost of one meeting's items a week; `src/docket/services/minutes_adoption.py` (stage 5 of ingest, every city) may now set `minutes_adopted_at` on a Mobile meeting from an "approval of minutes" item; `src/docket/services/meeting_types.py` treats a row with minutes as a real sitting; `src/docket/services/non_meetings.py` hides only rows with no agenda link, no minutes, and no items, so a linked row is safer from it; `src/docket/services/briefing.py`, `src/docket/services/youtube_meetings.py`, `src/docket/ai/transcripts/` and `src/docket/analysis/vote_matcher.py` act only on Birmingham rows (the briefing flag, the YouTube channel, a transcript, a minutes parser run by hand). The link's host is `civicclerk.com`, already in `STATIC_ALLOWED_DOMAINS` in `src/docket/web/source_security.py`.

`meetings.start_time` changes value for CivicClerk rows (10:30 where 04:30 or 05:30 was stored). `_upsert_meetings` writes `COALESCE(new, old)`, so every listed row is corrected on the first run after deploy. `src/docket/services/meeting_time.py` uses it to decide when a meeting stops being "upcoming" (start plus three hours); the corrected time moves that moment later in the day, to where it belongs.

`agenda_items.title` for new CivicClerk rows no longer begins with the file number. Templates print `item.title` and, separately, `Item #<item_number>`; nothing parses a number out of a CivicClerk title (the `ITEM N` pattern in ingest is for Granicus player pages).

The card that prints the count is `src/docket/web/templates/partials/meeting_card.html` ("{{ meeting.agenda_count }} items"). No template or query changes in this plan, so `docs/specs/city-page.md` needs no edit; the closing milestone confirms that by reading its own diff. A scheduled meeting whose agenda the city has not yet published still shows "0 items" until it is published; the city page lists at most four upcoming meetings, within 14 days.

### The prose that states the rules this plan changes

The adapter's module docstring says `delay: seconds between requests (default 0.5)` and its comment says "CivicClerk's eventDate is naive local time in practice; the Z/offset branch is defensive": both are edited by M1. The comment "Mark as scraped even if empty so we don't re-try" in `_ingest_agenda_items` stays true for an empty answer and gains a sentence about `AgendaNotReady` in M3. `README.md` line 725 shows `CivicClerkAdapter('mobile', {'tenant': 'mobileal', 'category_id': 26})`, still valid; its lines 38 and 39 (the city table) and 639 (`test_civicclerk.py # hierarchical agenda flattening`) are left alone unless M6 finds them false. `docs/birmingham/02-ingest.md` describes Birmingham and is left alone. `D175` is cited in `docs/DEBT.md` (its own row) and in `plans/completed/recordings-seen-the-day-posted.md`, an archive that keeps its citation; no clause of this plan says the id prints nowhere.

### Debt this plan touches

`D175` (two cities scraped at half the polite delay; trigger: the next change to `civicclerk.py` or either city's row) is paid: M1 puts the floor in the adapter, the operator's UPDATE sets the rows, and M6 deletes the row. `D9` (no present-tense spec for ingest and other areas) is tripped: M6 writes `docs/specs/civicclerk-ingest.md` and edits the row and the sentence in `docs/specs/index.md` that lists what has a spec. `D12` is tripped in words only; see the Decision Log. `D67` (Birmingham's prior-term roster rows), `D16` and `D33` (roster code for video OCR) are the same kind of work for another city or untouched code and are not paid.

### Work in flight

`plans/active/` held no other plan on 2026-11-20. Pull request #188 is documentation and touches none of this plan's files.

### Production figures the design rests on, and the queries that confirm them

No session of this plan can read production. The operator runs these before merging and pastes the output on the pull request; a result that breaks a stated assumption stops the merge and is a decision recorded in a revision of this plan, not a silent fix. Each is read-only. They are run on the Legion, in the WSL window, in `~/docket-pub`:

    PROD=$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)

    # Q1: the two cities' settings. Assumed: mobile has "tenant": "mobileal", "category_id": 26, "delay": 0.5;
    # vestavia_hills has "tenant": "vestaviahillsal", "delay": 0.5 and no category_id (migration 004).
    psql "$PROD" -c "SELECT slug, adapter_class, active, adapter_config FROM municipalities WHERE slug IN ('mobile','vestavia_hills') ORDER BY slug"

    # Q2: meetings and meetings with items. Reported on 2026-11-20 for mobile: 219 meetings, 51 with items.
    psql "$PROD" -c "SELECT mu.slug, count(*) AS meetings, count(*) FILTER (WHERE EXISTS (SELECT 1 FROM agenda_items a WHERE a.meeting_id = m.id)) AS with_items, count(*) FILTER (WHERE m.minutes_url IS NOT NULL) AS with_minutes, max(m.meeting_date) FILTER (WHERE m.agenda_url IS NOT NULL) AS newest_with_agenda FROM meetings m JOIN municipalities mu ON mu.id = m.municipality_id WHERE mu.slug IN ('mobile','vestavia_hills') GROUP BY 1 ORDER BY 1"

    # Q3: answered on 2026-11-20, see Surprises: Mobile's stored items are other meetings'. Kept as a look before
    # each reset: the newest meetings that hold items, with the id range of each. Observed on 2026-11-20 for mobile:
    # 441 | 2025-10-21 | 58 | 10593 | 10656, then 460 | 2026-02-03 | 43 | 7474 | 12698 and 459 | 2026-01-27 | 55 | 7451 | 12629.
    psql "$PROD" -c "SELECT m.external_id, m.meeting_date, count(a.id) AS items, min(a.external_id::int) AS min_item, max(a.external_id::int) AS max_item FROM meetings m JOIN municipalities mu ON mu.id = m.municipality_id JOIN agenda_items a ON a.meeting_id = m.id AND a.external_id ~ '^[0-9]+\$' WHERE mu.slug = 'mobile' GROUP BY 1, 2 ORDER BY (m.external_id = '441') DESC, m.meeting_date DESC LIMIT 6"

    # Q4: what hangs on the two cities' items. Assumed: vote_links, segments and discrepancies are all 0.
    psql "$PROD" -c "SELECT mu.slug, count(DISTINCT a.id) AS items, count(DISTINCT va.vote_id) AS vote_links, count(DISTINCT ts.id) AS segments, count(DISTINCT md.id) AS discrepancies, count(DISTINCT psa.id) AS audit_rows FROM municipalities mu JOIN meetings m ON m.municipality_id = mu.id JOIN agenda_items a ON a.meeting_id = m.id LEFT JOIN vote_agenda_items va ON va.agenda_item_id = a.id LEFT JOIN transcript_segments ts ON ts.agenda_item_id = a.id LEFT JOIN minutes_discrepancies md ON md.agenda_item_id = a.id LEFT JOIN processing_status_audit psa ON psa.agenda_item_id = a.id WHERE mu.slug IN ('mobile','vestavia_hills') GROUP BY 1 ORDER BY 1"

    # Q5: Mobile's roster. Assumed: the seven rows of migration 005 (Cory Penn, William Carroll, C.J. Small,
    # Ben Reynolds, Beau Fleming, Josh Woods, Gina Gregory), all active, term dates NULL.
    psql "$PROD" -c "SELECT cm.id, cm.name, d.number AS district, cm.term_start, cm.term_end, cm.active FROM council_members cm JOIN municipalities mu ON mu.id = cm.municipality_id LEFT JOIN districts d ON d.id = cm.district_id WHERE mu.slug = 'mobile' ORDER BY d.number, cm.id"

    # Q6: room on the volume and what waits for a summary. No assumption; the figures are the baseline to watch.
    psql "$PROD" -c "SELECT pg_size_pretty(pg_database_size(current_database())) AS database_size"
    psql "$PROD" -c "SELECT mu.slug, count(*) AS pending_items, min(m.meeting_date) AS oldest, max(m.meeting_date) AS newest FROM agenda_items a JOIN meetings m ON m.id = a.meeting_id JOIN municipalities mu ON mu.id = m.municipality_id WHERE a.processing_status = 'pending' GROUP BY 1 ORDER BY 1"

The revision of 2026-11-20 ran a wider form of Q3 (every meeting of the two cities that holds items) against production, read-only, and the Surprises section holds what it printed; Q1, Q2, Q4, Q5 and Q6 are still the operator's to run. The author ran each `psql` statement, Q3 in its authored form, on 2026-11-20 against the worktree's local development database, not production, to prove it parses: each returned without error (Q1 printed, for the local rows the migrations built, `{"delay": 0.5, "tenant": "mobileal", "category_id": 26}` and `{"delay": 0.5, "tenant": "vestaviahillsal"}`; Q5 printed the seven rows of migration 005 with NULL term dates). The `PROD=` line is the form `docs/specs/operations.md` gives and was not run.


## Plan of Work

The work is six milestones. The first two mend the adapter (what it lists, then what it fetches); the third teaches ingest the two settings and the "not ready" answer; the fourth builds the supervised reset that removes what the old adapter stored; the fifth corrects Mobile's roster; the sixth writes the documents. Each leaves the repository coherent and `./tools/verify` passing. No milestone deploys, runs a migration against production, or writes to production; those are the operator's steps in Validation and Acceptance.

Every milestone session starts and ends with `./tools/verify` from the worktree root and records its last line. A single test file is run against the throwaway database with the form verify itself prints, never with bare `pytest` (which `tests/conftest.py` refuses outside a `docket_test_*` database):

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_civicclerk.py -q -p no:cacheprovider; tools/test-db --drop

The author ran that form on 2026-11-20 with `tests/unit/test_civicclerk.py tests/unit/test_sponsors.py tests/integration/test_maintenance_repair.py` and it printed `49 passed, 1 warning in 0.64s`.

No test in this plan reaches a city's site. A session needs the network only in M5, to read a bounded number of the city's minutes; the plan says what M5 does if it has none.


## Milestones

### M1: the listing

The adapter lists every event and tells the truth about each meeting. At the end, `list_meetings` returns every event the server holds on or after the date asked, each with its posted time and the right links, and remembers each event's agenda id for M2.

Create the directory `tests/fixtures/civicclerk/` and the two files `events_page_1.json` and `events_page_2.json` with exactly the content given in Artifacts and Notes ("The saved responses"). They are rows observed on 2026-11-20, cut down to the keys the adapter reads.

In `src/docket/adapters/civicclerk.py`: the delay becomes `max(1.0, float(config.get("delay", 1.0)))` and the docstring says so. `__init__` creates `self._session = requests.Session()` and `self._agenda_ids: dict[str, int] = {}`. `_get` takes either an endpoint (joined to the base address, with params) or a full address (used as given, with no params); it calls `self._session.get(..., timeout=(10, 30))` and tries up to three times, sleeping `self.delay` after the first failure and `2 * self.delay` after the second; a failure is any `requests.RequestException`, a status `raise_for_status` rejects, or a body that is empty or does not parse as JSON; after the third it raises `requests.RequestException` (or a subclass) whose message names the address. No other call in the module uses `requests.get`. `list_meetings(since)` sends one first request to `Events` with `$orderby=eventDate desc`, `$count=true` and, when there is anything to filter, `$filter`: the parts `eventCategoryId eq <category_id>` (when the category is set) and `eventDate ge <since>T00:00:00Z` (when `since` is given), joined by ` and `. It sends neither `$top` nor `$skip`. While the answer carries `@odata.nextLink` it checks the link with `urllib.parse.urlsplit` against the adapter's own base address (the scheme is `https`, the host equals the base address's host with case ignored, and the path begins with the base address's path followed by `/`; anything else raises `ValueError`), sleeps the delay, and requests that address exactly; more than 200 pages raises `ValueError`. The client-side `since` check stays.

`_event_to_meeting` reads the event id from `id` first, then `eventId`. It reads `eventDate` as wall-clock time: a trailing `Z` is removed before parsing; a numeric offset is converted to America/Chicago as today. It records `self._agenda_ids[str(event_id)] = int(event.get("agendaId") or 0)`. Of the entries of `publishedFiles` with a given `type`, the one used is the greatest by the key `(entry.get("publishOn") or "", int(entry.get("fileId") or 0))`. The agenda link: the `Agenda` file so chosen gives `f"{self.base_url}/Meetings/GetMeetingFileStream(fileId={fileId},plainText=false)"`; with no such file and `hasAgenda` true, the portal page as today; otherwise None. The minutes link: the `Minutes` file so chosen gives the same file address, only when `createdOn` is present and its date in `America/Chicago` is not later than the date in the first ten characters of `eventDate`; otherwise None. The date of `createdOn` is found from its first nineteen characters (`YYYY-MM-DDTHH:MM:SS`), read as UTC and converted; the fraction of a second is cut off first because the city prints it with one to three digits and Python 3.10's `fromisoformat` refuses two. `_minutes_portal_url` is deleted if nothing else uses it.

In `tests/unit/test_civicclerk.py`, delete `test_event_to_meeting_normalizes_z_suffix_to_central` and add these sixteen tests. Each builds the adapter and then patches the `get` of that adapter's own session, `patch.object(adapter._session, "get")`, and patches `docket.adapters.civicclerk.time.sleep`: `test_list_meetings_follows_next_links_to_the_last_page` (four meetings from the two fixture pages; the second call's address equals the fixture's next link and carries no params); `test_list_meetings_sends_no_top_or_skip`; `test_list_meetings_asks_for_events_on_or_after_since` (with category 26 and `since=date(2021, 11, 1)` the filter is `eventCategoryId eq 26 and eventDate ge 2021-11-01T00:00:00Z`; with category None it is `eventDate ge 2021-11-01T00:00:00Z`); `test_list_meetings_refuses_a_next_link_on_another_host`; `test_delay_is_never_below_one_second` (0.5 gives 1.0, absent gives 1.0, 2.5 gives 2.5); `test_get_retries_a_timeout_then_succeeds`; `test_get_raises_after_three_failures`; `test_get_treats_an_empty_body_as_a_failure`; `test_start_time_is_the_posted_wall_clock_time` (event 501: date 2026-11-17, time 10:30); `test_agenda_link_is_the_agenda_file` (event 501: `https://mobileal.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=3859,plainText=false)`); `test_agenda_link_falls_back_to_the_event_page_without_an_agenda_file` (event 500: `https://mobileal.portal.civicclerk.com/event/500/agenda`); `test_the_latest_file_of_a_type_is_the_one_linked` (event 501's row with a second `Agenda` entry put first in the list, `{"fileId": 3870, "type": "Agenda", "name": "11/17/26 Agenda amended", "publishOn": "2026-11-17T09:00:00Z"}`: the link ends `fileId=3870,plainText=false)`; this row is built in the test and is not a row the city sent); `test_minutes_link_is_the_minutes_file_of_an_event_created_before_its_date` (event 500: file 3861); `test_an_event_created_on_the_evening_of_its_own_day_keeps_its_minutes_link` (event 500's row with `eventDate` `2026-11-10T10:00:00Z` and `createdOn` `2026-11-11T01:30:00.5Z`, which is 19:30 Central on 2026-11-10: the link is file 3861; built in the test); `test_no_minutes_link_for_an_event_created_after_its_date` (event 297: None, and its agenda link is file 548); `test_a_scheduled_event_has_no_links` (event 573: both None).

Before editing the adapter, run the test file with the sixteen new tests against the unchanged adapter and record how many fail; the author expects all sixteen to fail or error and did not run them.

Acceptance: the single-file command above prints `32 passed` (17 less the one deleted plus the sixteen added) and no failure; `./tools/verify` ends `verify: all 6 checks passed in <N>s.`; the Surprises section holds the count of new tests that failed before the adapter was edited.

### M2: the items

The adapter fetches the right agenda and says so when there is none. At the end, `fetch_agenda_items` for the 2026-11-17 meeting asks for `Meetings/473`, each item it returns is titled as the city titled it, and an item under a consent heading is marked a consent item.

Create `tests/fixtures/civicclerk/meeting_473.json` with the content given in Artifacts and Notes.

In `src/docket/models/protocol.py` add `class AgendaNotReady(Exception)` with a docstring: the source has not published this meeting's agenda yet; the caller leaves the meeting to be asked again. In `src/docket/adapters/civicclerk.py` add the class attribute `items_carry_video_timestamps = False`. `fetch_agenda_items(meeting)` finds the agenda id in `self._agenda_ids`; when the meeting was not listed by this instance it takes `int(meeting.external_id)` (a `ValueError` for an id that is not a whole number is let through), asks `Events` with `$filter=id eq <that number>` (one request, then the delay; the revision saw this form return event 501 on 2026-11-20), reads the row through `_event_to_meeting`, and raises `ValueError` if the server returns no such event. An agenda id of 0 raises `AgendaNotReady` with no request. Otherwise it requests `Meetings/<agenda id>` and sleeps the delay. A failed request propagates; the `try` that returned an empty list is removed. An answer whose `agendaIsPublish` is `False` raises `AgendaNotReady` (an answer without the key is treated as published). Otherwise the items are flattened. No item and `meeting.meeting_date >= datetime.now(ZoneInfo("America/Chicago")).date()` raises `AgendaNotReady`; no item for an earlier date returns an empty list. `hasAgenda` is not consulted here.

`_flatten_items` changes in four ways. It takes one more argument, `in_consent: bool = False`: when a node is a heading (by the test the function already uses), its children are walked with `in_consent` true if the heading's cleaned name contains "consent", case ignored, and otherwise with the value the heading itself was walked with; an item is returned with `is_consent = in_consent or is_consent_item(<its title>)`. The name is split by a new module function `split_item_name(raw: str) -> tuple[str, str | None, str | None]` returning title, sponsor, submitter, by the rule in Interfaces and Dependencies, whose worked results are given there. The description is read from `agendaObjectItemDescription`, then `description`, cleaned as today and, when there is a submitter, followed by `Submitted by <submitter>.` (joined with one space when both exist); the 300-character cut stays and is applied last. The title is the split title alone, the file number is no longer prefixed, `item_number` is unchanged, and `sponsor` is the split sponsor. An item is still left out when it is a heading or its title is empty.

In `tests/unit/test_civicclerk.py`, every assertion in `TestFlattenItems` that expects a title with the number in front drops the number (`"1 Roll Call"` becomes `"Roll Call"`, `"A Item A"` becomes `"Item A"`, and so on); no other line of those thirteen tests changes. Add thirteen tests, patching as M1's do: `test_items_come_from_the_events_agenda_id` (after listing the fixture pages, fetching meeting 501 requests an address ending `/Meetings/473` and none ending `/Meetings/501`); `test_agenda_id_is_looked_up_for_a_meeting_not_listed` (a fresh adapter first requests `Events` with the filter `id eq 501`, then `/Meetings/473`); `test_no_agenda_id_raises_agenda_not_ready_without_a_request` (event 573); `test_an_unpublished_agenda_raises_agenda_not_ready` (a meeting dated yesterday in America/Chicago and the fixture's answer with `"agendaIsPublish": false`: the exception is raised although the answer holds items and the date is past); `test_an_empty_agenda_of_a_coming_meeting_raises_agenda_not_ready` (a meeting dated tomorrow in America/Chicago, an answer with `"agendaIsPublish": true, "items": []`); `test_an_empty_agenda_of_a_past_meeting_returns_no_items` (dated yesterday); `test_a_failed_request_raises`; `test_section_headings_are_not_items` (the fixture's nine nodes give four items); `test_an_item_under_a_consent_heading_is_a_consent_item` (item 13512, under `CONSENT RESOLUTIONS BEING INTRODUCED`, has `is_consent` true; items 13498, 13505 and 13520, under `INVOCATION`, `PUBLIC HEARINGS` and `RESOLUTIONS HELD OVER`, have it false); `test_title_is_the_citys_item_name_and_keeps_its_code`; `test_sponsor_and_submitter_are_split_from_the_name`; `test_the_code_survives_enrichment` (for item 13512, `enrich_agenda_item(title, description, True)` from `docket.services.enrichment` returns a `clean_title` equal to the title, on which `re.match(r"^(\d{2}-\d{3,4})\b", ...)` gives `40-1225`, and a `sponsor` of None, so ingest keeps the adapter's); `test_description_is_read_from_the_citys_description_field`. The expected titles, sponsors and descriptions are in Interfaces and Dependencies.

Acceptance: the single-file command prints `45 passed` (32 plus thirteen) and no failure; `./tools/verify` ends `verify: all 6 checks passed in <N>s.`

### M3: ingest learns the settings

Ingest reads the floor and the cap, honours "not ready", and stops re-fetching stored CivicClerk agendas. At the end, a city whose row carries the two settings is listed from its floor and has at most its cap of agendas fetched in a run, newest first.

In `src/docket/services/ingest.py`, after the adapter is built, read two settings from `adapter_config` with a new function `_backlog_settings(adapter_config: dict) -> tuple[date | None, int | None]`: `backlog_floor` parsed with `date.fromisoformat`, `agenda_fetch_cap` an `int` of 0 or more (a `bool` is refused). A value that does not parse makes `ingest_municipality` return `IngestResult(slug, 0, 0, 0, 0, 0, [f"Bad adapter_config for {slug}: {reason}"])` before any request. When the caller's `since` is None the floor is passed to `adapter.list_meetings` as `since`; a caller's `since` wins. `_upsert_meetings` is not edited: it already writes the listed `agenda_url` and `minutes_url` over the stored ones, and Birmingham's meetings pass through it.

Stage 3 with no cap is today's loop with one added clause, `except AgendaNotReady: continue`, placed before `except Exception`. Stage 3 with a cap first reads, in one SELECT, the external ids of this city's meetings whose `agenda_items_scraped` is not true (`_waiting_external_ids(municipality_id) -> set[str]`; the SELECT is `meetings m LEFT JOIN processing_status ps ON ps.meeting_id = m.id` with `ps.agenda_items_scraped IS NOT TRUE`, so a meeting that has no `processing_status` row yet is waiting), then walks the listed meetings sorted by `meeting_date` descending (ties in the adapter's order). A meeting that is waiting is skipped once the count of fetches has reached the cap; otherwise `_ingest_agenda_items` is called as today; a waiting meeting's call counts as a fetch unless it raised `AgendaNotReady`; a raised error is recorded as today and counts. A meeting that is not waiting is passed to `_ingest_agenda_items` as today and never counts. The run logs one line, `Agenda fetches: <n> of cap <cap>, <k> still waiting`.

In `_ingest_agenda_items`, the already-scraped branch calls `_backfill_video_timestamps` only when `getattr(adapter, "items_carry_video_timestamps", True)` is true, and returns 0 otherwise. The comment on the empty answer gains: an adapter that knows the agenda is not published yet raises `AgendaNotReady` instead, and the meeting stays unmarked.

Add `tests/integration/test_ingest_backlog_settings.py`, modelled on `tests/integration/test_ingest_hearings.py`: `docket.services.ingest.get_adapter` is replaced by a fake adapter, the whole of `ingest_municipality` runs against the throwaway database for the seeded city `mobile` with its `adapter_config` set by the test and restored after, and every meeting the test creates has a title beginning `BACKLOG_TEST_` and is deleted before and after. Ten tests: `test_backlog_floor_is_passed_to_the_adapter_as_since`; `test_an_explicit_since_wins_over_the_floor`; `test_cap_fetches_the_newest_waiting_meetings_first` (five waiting meetings on five dates, cap 2: the adapter is asked for the two newest and only they are marked); `test_a_second_run_takes_the_next_meetings` (the third and fourth); `test_a_meeting_not_ready_is_left_unmarked_unreported_and_uncounted` (the newest of three raises `AgendaNotReady`, cap 2: the other two are fetched, the result's errors are empty, the first is unmarked); `test_a_failed_fetch_is_reported_left_unmarked_and_counted` (the newest of three raises `RuntimeError`, cap 2: one other is fetched, the error names the meeting); `test_a_stored_agenda_is_not_fetched_again_when_items_carry_no_timestamps` (a marked meeting with items: `fetch_agenda_items` is not called when the fake sets the attribute False, and is called when it does not set it); `test_a_listed_file_link_replaces_a_stored_page_link` (the first run lists a meeting whose `agenda_url` is `https://mobileal.portal.civicclerk.com/event/900001/agenda`; the second lists the same meeting with `https://mobileal.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=900001,plainText=false)`; the stored `agenda_url` is then the second; the author expects this to pass on the unchanged upsert, and it is there to hold the behaviour); `test_a_city_with_neither_setting_ingests_as_before` (`since` is None, every waiting meeting is fetched, in the adapter's order); `test_a_bad_setting_is_reported_and_nothing_is_fetched` (`"agenda_fetch_cap": "ten"`: one error beginning `Bad adapter_config for mobile`, `list_meetings` not called).

Acceptance: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_ingest_backlog_settings.py tests/integration/test_ingest_hearings.py tests/integration/test_ingest_backfill_timestamps.py tests/unit/test_ingest_event_guard.py -q -p no:cacheprovider; tools/test-db --drop` prints no failure and a total ten higher than the same command printed for the three existing files at the session's start (the session records both totals); `./tools/verify` ends `verify: all 6 checks passed in <N>s.`

### M4: the supervised reset

One command removes what the old adapter stored for one city, and the meeting summaries written from it, and lets ingest start that city again. At the end, the operator can print what would go and then make it go.

In `src/docket/services/ingest.py` add `reset_agenda_items(slug: str, *, apply: bool = False) -> dict`. It raises `ValueError` for an unknown slug. It counts, for that city: meetings, meetings marked scraped, meetings with an `executive_summary`, agenda items, `processing_status_audit` rows on those items, and rows that block: `vote_agenda_items`, `transcript_segments` and `minutes_discrepancies` rows that reference those items. If any blocking count is above zero it raises `ValueError` naming the counts, whether or not `apply` is set. With `apply=False` it returns the counts and writes nothing. With `apply=True` it runs four statements in one transaction: a DELETE of the `processing_status_audit` rows of the city's items (the one table whose foreign key to `agenda_items` neither cascades nor sets NULL; the session confirms that with `\d agenda_items` on the throwaway database and records what it printed, and if another such table has appeared it stops and records a decision before adding a statement); a DELETE of the city's `agenda_items` (badges, batch items, search cards and hearing links go with them by their own cascades); an UPDATE of the city's `meetings` setting `executive_summary`, `executive_summary_voice`, `ai_prompt_version`, `ai_metadata` and `ai_generated_at` to NULL where any of the five is not NULL; an UPDATE setting `agenda_items_scraped = FALSE` on the city's `processing_status` rows. Each statement selects by `municipality_id`. It returns the counts with the four statements' row counts. The meetings themselves, their links, and `votes_scanned` are not touched. With `ai_prompt_version` NULL, the meeting stage claims a meeting again once all of its refilled items have been summarised, so a new summary is written from the right items and none is shown in between.

Add `scripts/reset_agenda_items.py`, modelled on `scripts/correct_agenda_chapter_ids.py` for its argument parsing and logging: `--city <slug>` (required), `--apply`. It first prints one line naming the database it is connected to, the host and the database name taken from `DATABASE_URL` and nothing else of it (`database: <host>/<name>`). Without `--apply` it then prints the counts and `dry run: nothing changed`; with it, the counts and `applied`. A `ValueError` is printed and the script exits 2.

Add `tests/integration/test_reset_agenda_items.py` with five tests against the throwaway database, each creating its own municipality row (slug beginning `reset_test_`) with meetings (one of them with an `executive_summary`, an `ai_prompt_version` and an `ai_generated_at`), items, a `processing_status` row and a `processing_status_audit` row, and deleting them after: `test_a_dry_run_reports_and_changes_nothing`; `test_apply_deletes_the_citys_items_and_reopens_its_meetings_only` (a second test city's items and marks are untouched); `test_apply_clears_the_citys_meeting_summaries_only` (the five columns are NULL on the city's meeting and unchanged on the second city's); `test_a_city_with_vote_links_is_refused` (a `votes` row and a `vote_agenda_items` row on one item: `ValueError`, nothing deleted and no summary cleared, with and without `apply`); `test_an_unknown_city_is_refused`. The guard's other two tables are covered by the same query and have no seeded test; M6 says so in the spec.

Acceptance: the single-file form on `tests/integration/test_reset_agenda_items.py` prints `5 passed`; `venv/bin/python scripts/reset_agenda_items.py --help` exits 0 and prints both options; `venv/bin/python scripts/reset_agenda_items.py --city mobile` against the worktree's own development database (a dry run, which only reads) prints the `database:` line, the counts and `dry run: nothing changed`, and the session records what it printed; `./tools/verify` ends `verify: all 6 checks passed in <N>s.`

### M5: Mobile's roster

The roster says who sat when, from the city's documents. At the end, `council_members` for Mobile holds the seated seven as active rows and the three members who left since November 2021 as dated inactive rows.

What the documents already read establish is in the Surprises section: the roll calls, the council page, and the four documents on the city's site that name Joel Daves in District 5, Scott Jones in District 6, and the day Josh Woods took his oath. One fact is still open, and the session spends at most 25 requests, two seconds apart, on it: the last roll call that lists Jones, somewhere from 2023-03-28 to 2023-08-01. Minutes of 2023 sit under events labelled some months later, and not by a fixed amount (the minutes of 2023-03-28 are on the event of that date; the minutes of 2023-08-08 are file 701 on the event of 2024-01-30), so the session lists Mobile's events from 2023-09-01 to 2024-01-30 with the `Events` filter form in Concrete Steps, reads the first page of each Minutes file with `pdfplumber` in memory (the form in Concrete Steps), and notes each file's printed date and roll call. It never requests a file of type Agenda or Agenda Packet. It does not fetch the four documents again; the 26 MB financial report in particular is not to be downloaded a second time.

The migration, numbered by the rule in the Decision Log and named `<NNN>_mobile_council_terms.py`, does this, every statement scoped to the municipality whose slug is `mobile` and matched by whole-word surname, `(name = '<surname>' OR name ILIKE '% <surname>' OR name ILIKE '% <surname> %')`, so that neither a spelling difference in a first name nor a suffix after the surname can make it miss. Penn, Small, Reynolds and Gregory: `term_start = '2021-11-02'` where it is NULL. Carroll: `term_start = '2021-11-02'`, `term_end = '2025-11-04'`, `active = FALSE`. Woods: `term_start = '2023-08-08'`. Fleming: `term_start = '2025-11-04'`. Insert, each only where no row of that surname exists for Mobile: `Samantha Ingram`, District 2, `term_start = '2025-11-04'`, active; `Joel Daves`, District 5, `2021-11-02` to `2025-11-04`, inactive; `Scott Jones`, District 6, `term_start = '2021-11-02'`, inactive, with `term_end` the day after the last roll call found that lists him, or `2023-08-08` if the search does not find one. The docstring lists each fact with its document: for a roll call, the meeting date, the event id, the file id, and the words quoted; for a name and district, the address of the city's document and the words quoted, as Surprises gives them. `SQL_DOWN` deletes the three inserted rows by the same whole-word match and sets the changed columns back (term dates NULL, Carroll active).

`council_members` has no unique constraint, so `ON CONFLICT DO NOTHING` protects nothing there; the inserts use `WHERE NOT EXISTS`. The term rule is half-open: a member is seated on a date when `term_start <= date < term_end`. Worked on the boundary: Carroll, ending `2025-11-04`, is seated on 2025-10-28 and not on 2025-11-04; Ingram, starting `2025-11-04`, is seated on 2025-11-04 and not on 2025-10-28.

Add `tests/integration/test_<NNN>_migration.py`. It executes the migration's `SQL_UP` once more inside the test (proving a second run adds no row), then asserts: Mobile has exactly seven active members and by district number their names end Penn, Ingram, Small, Reynolds, Fleming, Woods, Gregory; for each saved roll call, every surname resolves to exactly one member through `docket.services.member_votes.load_roster_index(<mobile id>).resolve(surname, date)`: 2021-11-02 Penn, Carroll, Small, Reynolds, Daves, Gregory; 2022-09-13 and 2023-03-28 those six and Jones; 2023-08-08 and 2025-10-28 Penn, Carroll, Small, Reynolds, Daves, Woods, Gregory; 2025-11-04 and 2026-11-03 Penn, Ingram, Small, Reynolds, Fleming, Woods, Gregory; and these resolve to None: Carroll and Daves on 2025-11-04, Ingram and Fleming on 2025-10-28, Woods on 2023-03-28, Jones on 2023-08-08, and "Scott" on 2021-11-02 (the minutes' spelling of that day; the resolver answers to a surname or an initial with a surname, so the row `Scott Jones` does not answer to it; the test's docstring says the name is probably Scott Jones written by his first name, that no document read says so, and that stage 2 must settle it). Five test functions: the second run, the seven active, the roll calls (one function over the seven dates), the names that must not resolve, and the down-then-up round trip leaving the same rows.

If the session has no network, it writes the migration from the facts in this plan (Jones ending `2023-08-08`), says so in Surprises, and the acceptance below is unchanged.

Acceptance: the single-file form on the new test file prints `5 passed`; `./tools/verify` ends `verify: all 6 checks passed in <N>s.`; the Surprises section lists each minutes file the session read with its printed date and roll call, or says the network was not available.

### M6: the close

The documents say what is true now. At the end, a reader of `docs/specs/` can learn how a CivicClerk city is listed, fetched, capped and reset without opening this plan, and the debt register lists what the operator must run and what was left.

Write `docs/specs/civicclerk-ingest.md` in the present tense: the address and the event, agenda and file records; paging by next link and why `$top` is not sent; the floor and the cap, their keys, and what absent means; the delay floor; retries and what a failure does; the time rule; the two link rules and why an imported event has no minutes link; the item title, number, sponsor and submitter; `AgendaNotReady`; the timestamp attribute; how an item is marked a consent item; the reset script, what it deletes and that it clears the city's meeting summaries, its guard, and that only the vote-link guard has a seeded test; that an agenda fetched before its meeting is not fetched again; what is not read (votes fields, attachments, the packet, video fields). Add its row to the index table in `docs/specs/index.md` and edit that file's sentence about `D9` so it lists CivicClerk ingest among the areas that have a spec. In `docs/specs/operations.md`, under "Railway specifics", add a paragraph on the two settings, the reset script (laptop, public address, dry run first), and how the refill is watched (the queries of Validation and Acceptance, by reference to the spec). In `docs/runbooks/cron-worker.md`, the `ingest_all` row of the task inventory gains the cap and the floor in a clause. In `README.md`, correct only a sentence this plan made false (the session greps for `0.5` and `delay` and for the adapter example and edits what is wrong). Read the diff of the branch against `origin/main` for `src/docket/web/` and confirm it is empty; say so in Outcomes, which is the statement that `docs/specs/city-page.md` needs no edit.

Graduate to `docs/decisions/`, in the format of `docs/decisions/DECISION_FORMAT.md` and numbered by the rule in the Decision Log, the decisions that bind later work: paging by next link with no `$top`; an imported event gets no minutes link until its file's own date is read; the CivicClerk item title is the city's name with the code first and the parentheticals split out; "not ready" is an exception and a failed request is an error, never an empty agenda; backlog floor and per-run cap are `adapter_config` settings read by ingest. One record each, or fewer where two belong together.

In `docs/DEBT.md`: delete the `D175` row. Edit `D9` to name the new spec. Reword `D12`'s trigger and add its dated note. Add rows, numbered by the rule: one whose trigger is "the pull request merges", listing the operator's steps of Validation and Acceptance in order; one for Mobile's 135 meetings from 2021-11-02 to 2024-06-18 whose items exist only in agenda PDFs (trigger: stage 2 needs items to join votes before 2024-06-25, or the operator asks for them); one for the minutes links of imported events and the mislabelled files (trigger: stage 2 reads Mobile's minutes); one for "Scott" in the minutes of late 2021 and for `votes_scanned` being set on every CivicClerk meeting with minutes (trigger: stage 2); one for Vestavia Hills' roster, which this plan did not check (trigger: votes or member pages for that city); one for an agenda stored before its meeting and never fetched again (trigger: stage 2 finds an item in a meeting's minutes that the stored agenda lacks, or the operator sees a stored Mobile agenda differ from the city's).

Write Outcomes & Retrospective against the Purpose, including the part of the goal not delivered. Do not move this file and do not write the closing retrospective; the stage after the last milestone does both.

Acceptance: `ls docs/specs/civicclerk-ingest.md` prints the path and `grep -c 'civicclerk-ingest.md' docs/specs/index.md` prints 1 or more; `grep -c '^| D175 ' docs/DEBT.md` prints `0`; `grep -c 'the pull request merges' docs/DEBT.md` prints a number one higher than it printed at the session's start; `git diff --stat origin/main -- src/docket/web/` prints nothing; `./tools/verify` ends `verify: all 6 checks passed in <N>s.`


## Concrete Steps

All commands run from the worktree root, `/home/thinkdarrell/docket-pub/.claude/worktrees/mobile-agendas-flow-again`, with that checkout's own `venv/`.

At the start and end of every milestone session:

    ./tools/verify

Expected last line, as the author observed it on 2026-11-20 before any work: `verify: all 6 checks passed in 304s.` (the seconds vary).

One test file against the throwaway database (never bare `pytest`):

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest <files> -q -p no:cacheprovider; tools/test-db --drop

Commits in a milestone session each change this plan file as well (decision `0037`), use the repository's commit identity, and never bypass a hook. A Progress line is ticked by changing `- [ ]` to `- [x] (YYYY-MM-DD HH:MMZ)` and changing nothing else on the line.

For M5 only, the two read forms the author used, each followed by a pause of two seconds before the next request. Listing events in a window:

    curl -sS --max-time 60 -G 'https://mobileal.api.civicclerk.com/v1/Events' \
      --data-urlencode '$orderby=eventDate asc' --data-urlencode '$count=true' \
      --data-urlencode '$filter=eventCategoryId eq 26 and eventDate ge 2023-09-01T00:00:00Z and eventDate le 2024-01-30T23:59:59Z'

Reading the first page of a Minutes file in memory, writing nothing to disk (the argument is the file id):

    curl -sS --max-time 120 'https://mobileal.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=701,plainText=false)' \
      | venv/bin/python -I -c "import sys, io, pdfplumber; pdf = pdfplumber.open(io.BytesIO(sys.stdin.buffer.read())); print(pdf.pages[0].extract_text()[:1500])"

Both forms were run by the author on 2026-11-20; the second printed, for file 701, a page beginning `MUNICIPAL BUILDING, MOBILE, ALABAMA, AUGUST 8, 2023`. A request that returns nothing is repeated once after the pause.


## Validation and Acceptance

What a factory session observes is each milestone's acceptance, above. What follows is the operator's, after the pull request merges. None of it is a clause of any milestone. Every step is run on the Legion, in the WSL window, in `~/docket-pub` on a clean `main`, unless the step says otherwise.

Before merging: run queries Q1, Q2, Q4, Q5 and Q6 of Context and Orientation and paste the output on the pull request. Go on only if Q4 prints zero vote links, segments and discrepancies for both cities and Q5 prints the seven names of migration 005. Q3 was answered on 2026-11-20 and is not a condition; it is run again in step 4 as a look.

Steps 1 to 5 are done in one sitting, after the morning's 06:00 run of `ingest_all` has finished and not on a Monday before 05:00's repair has run.

Step 1, before deploying, write both cities' settings, Vestavia Hills held at a cap of 0, then read them back with Q1. The code now running ignores the two new keys:

    psql "$PROD" -c "UPDATE municipalities SET adapter_config = adapter_config || '{\"delay\": 1.0, \"backlog_floor\": \"2021-11-01\", \"agenda_fetch_cap\": 10}'::jsonb WHERE slug = 'mobile'"
    psql "$PROD" -c "UPDATE municipalities SET adapter_config = adapter_config || '{\"delay\": 1.0, \"backlog_floor\": \"2021-11-01\", \"agenda_fetch_cap\": 0}'::jsonb WHERE slug = 'vestavia_hills'"

Expected: `UPDATE 1` twice.

Step 2, deploy both services:

    scripts/deploy.sh --service docket-web
    scripts/deploy.sh --service worker

Step 3, run the roster migration inside the web container, then confirm it:

    railway ssh --service docket-web "python -m docket.migrations.runner"
    railway ssh --service docket-web "python -m docket.migrations.runner --status"

Step 4, reset Mobile, dry run first, from the laptop checkout against the public address, and then at once start one ingest run by hand so the page is refilled the same hour. Run Q3 before the dry run; it should print what Context and Orientation records:

    DATABASE_URL="$PROD" venv/bin/python scripts/reset_agenda_items.py --city mobile
    DATABASE_URL="$PROD" venv/bin/python scripts/reset_agenda_items.py --city mobile --apply
    railway ssh --service worker "python -m docket.worker.scheduler --run-once ingest_all"

The script's first line names the production host. The dry run's item count should match Q4's `items` for Mobile; `--apply` prints `applied`. The ingest run is a light task; it visits every city, Birmingham included, as the morning run does, lists Vestavia Hills and fetches none of its agendas, and fetches ten of Mobile's, newest first.

Step 5, confirm Mobile before touching Vestavia Hills:

    psql "$PROD" -c "SELECT m.meeting_date, m.start_time, count(a.id) AS items, m.agenda_url, m.minutes_url FROM meetings m JOIN municipalities mu ON mu.id = m.municipality_id LEFT JOIN agenda_items a ON a.meeting_id = m.id WHERE mu.slug = 'mobile' AND m.external_id IN ('501', '499') GROUP BY 1, 2, 4, 5 ORDER BY 1"

Expected: 2026-11-03 at 10:30:00 with 60 items and a minutes link ending `fileId=3854,plainText=false)`; 2026-11-17 at 10:30:00 with 51 items and an agenda link ending `fileId=3859,plainText=false)`, unless the city has amended either agenda. Then open https://docket.pub/al/mobile/ in the Windows browser and see that the newest held meetings show item counts above zero. If either look is wrong, stop here: Vestavia Hills is as it was, apart from its meetings' times and links.

Step 6, on a later day, once Mobile's refill is seen to run on its own in the morning, raise Vestavia Hills' cap, reset it, and start one ingest run:

    psql "$PROD" -c "UPDATE municipalities SET adapter_config = adapter_config || '{\"agenda_fetch_cap\": 10}'::jsonb WHERE slug = 'vestavia_hills'"
    DATABASE_URL="$PROD" venv/bin/python scripts/reset_agenda_items.py --city vestavia_hills
    DATABASE_URL="$PROD" venv/bin/python scripts/reset_agenda_items.py --city vestavia_hills --apply
    railway ssh --service worker "python -m docket.worker.scheduler --run-once ingest_all"

Some of what this deletes was right (an older Vestavia Hills event's agenda id equals its event id); it is fetched and summarised again. The run fetches ten Vestavia Hills agendas across its seven bodies; read two of the fetched meetings that are not the council's on the site and say whether their items read as that body's.

Step 7, watch, daily for the first week and then weekly, with Q2 and Q6. Expected: Mobile's `with_items` rises by about ten a day until it reaches the number of its meetings from 2024-06-25 forward that have a published agenda (124 on 2026-11-20, plus one a week); `with_minutes` is above zero after the first run; the database size grows by tens of megabytes, not hundreds. If the size passes 800 MB, set `agenda_fetch_cap` to 0 for both cities with the form of step 1 and stop. The AI stage summarises 200 items a run, newest meeting first across cities, and ten agendas a day for each city is more than that, so a Birmingham item waiting from an older meeting waits longer while the two backlogs drain; Q6 shows how many, and lowering a city's cap is the remedy.

Step 8, the look only a browser gives, in the Windows browser on the Legion. Open each address and say what is seen:

    https://docket.pub/al/mobile/
    https://docket.pub/al/vestavia_hills/

On Mobile's page the newest held meetings show item counts above zero and, as days pass, headlines, amounts and meeting summaries; the council shown is Penn, Ingram, Small, Reynolds, Fleming, Woods, Gregory. Open the 2026-11-03 meeting from the page and click its agenda link and its minutes link: each opens the city's PDF for that date. Open one meeting with no Agenda file (2026-11-10) and click its agenda link, which is the portal page form no session could check: if it does not open the city's agenda, that is a finding for a follow-up, recorded in the debt row. Open one Mobile meeting that had a summary before the reset and say that it shows none until its items have been summarised, and then a new one.


## Idempotence and Recovery

Every milestone's edits are ordinary source changes on the plan's branch; a session that stops halfway commits what stands with the plan file, splits its Progress line in place ("completed: X; remaining: Y"), records the split in the Decision Log, and exits.

The listing is safe to run any number of times: meetings are upserted by `(municipality_id, external_id)`. Items are inserted with `ON CONFLICT (meeting_id, external_id) DO NOTHING`, so a re-fetch adds nothing twice. The migration's inserts are guarded by `WHERE NOT EXISTS` and its updates set fixed values, so a second run changes nothing; its down restores the seeded state. The settings UPDATE merges keys and can be repeated. The reset's dry run only reads; its `--apply` is one transaction, so a failure leaves everything as it was, and a second `--apply` after a refill would delete the refilled items, which is why the operator runs it once per city and the debt row says so.

To stop the backlog at any time, set `agenda_fetch_cap` to 0 for the city: the listing continues, no agenda is fetched. To go back to the old listing, remove `backlog_floor` and `agenda_fetch_cap` from the row; the adapter's paging, links, and delay floor stay, as they are corrections and not settings. To undo the deploy, redeploy the previous `main`; rows written since stay, and are correct.


## Artifacts and Notes

### The saved responses

These are the fixture files M1 and M2 create, byte for byte apart from whitespace. The rows are as the two servers returned them on 2026-11-20, cut down to the keys the adapter reads. Two values are stand-ins the author did not capture: the `createdOn` of events 500 and 573 (given the value seen on event 501 and a date before the event, as every non-imported row seen had).

`tests/fixtures/civicclerk/events_page_1.json`:

    {
      "@odata.context": "https://mobileal.api.civicclerk.com/v1/$metadata#Events",
      "@odata.count": 4,
      "value": [
        {"id": 501, "eventName": "City Council Meeting", "eventDate": "2026-11-17T10:30:00Z",
         "createdOn": "2025-11-18T12:35:16.927Z", "eventCategoryId": 26, "categoryName": "City Council",
         "agendaId": 473, "hasAgenda": true,
         "publishedFiles": [
           {"fileId": 3859, "type": "Agenda", "name": "11/17/26 Agenda", "publishOn": "2026-11-16T08:48:58.697Z"},
           {"fileId": 3860, "type": "Agenda Packet", "name": "11/17/26 Agenda Packet", "publishOn": "2026-11-16T08:48:58.697Z"}
         ]},
        {"id": 500, "eventName": "City Council Meeting", "eventDate": "2026-11-10T10:00:00Z",
         "createdOn": "2025-11-18T12:35:16.927Z", "eventCategoryId": 26, "categoryName": "City Council",
         "agendaId": 472, "hasAgenda": true,
         "publishedFiles": [
           {"fileId": 3853, "type": "Agenda Packet", "name": "November 10, 2026 Agenda Packet", "publishOn": "2026-11-10T12:03:58.71Z"},
           {"fileId": 3861, "type": "Minutes", "name": "November 10, 2026 Minutes", "publishOn": "2026-11-17T16:41:53.053Z"}
         ]}
      ],
      "@odata.nextLink": "https://mobileal.api.civicclerk.com/v1/Events?$orderby=eventDate%20desc&$count=true&$filter=eventCategoryId%20eq%2026&$skiptoken=eventDate-2026-11-10T10%3A00%3A00Z,id-500"
    }

`tests/fixtures/civicclerk/events_page_2.json`:

    {
      "@odata.context": "https://mobileal.api.civicclerk.com/v1/$metadata#Events",
      "@odata.count": 4,
      "value": [
        {"id": 573, "eventName": "City Council Meeting", "eventDate": "2027-08-31T10:30:00Z",
         "createdOn": "2026-08-18T12:00:00Z", "eventCategoryId": 26, "categoryName": "City Council",
         "agendaId": 0, "hasAgenda": false, "publishedFiles": []},
        {"id": 297, "eventName": "City Council Meeting", "eventDate": "2023-04-25T10:30:00Z",
         "createdOn": "2024-07-25T00:00:00Z", "eventCategoryId": 26, "categoryName": "City Council",
         "agendaId": 270, "hasAgenda": true,
         "publishedFiles": [
           {"fileId": 548, "type": "Agenda", "name": "2023-04-25_10_30_AM-Council_Members", "publishOn": "2024-07-25T00:00:00Z"},
           {"fileId": 549, "type": "Minutes", "name": "2023-04-25_10-30_AM-Council_Members", "publishOn": "2024-07-25T00:00:00Z"}
         ]}
      ]
    }

The second page is not in date order (a real page would be); no test depends on the order of rows within a page. Every test that uses these pages builds the adapter as `CivicClerkAdapter("mobile", {"tenant": "mobileal", "category_id": 26})`, so the next link begins with the adapter's own base address.

`tests/fixtures/civicclerk/meeting_473.json`, nine nodes, four of them items:

    {
      "id": 473, "agendaIsPublish": true,
      "items": [
        {"id": 7754, "isSection": 1, "agendaObjectItemName": "ROLL CALL", "agendaObjectItemNumber": "",
         "agendaObjectItemDescription": null, "childItems": []},
        {"id": 7752, "isSection": 1, "agendaObjectItemName": "INVOCATION", "agendaObjectItemNumber": "",
         "agendaObjectItemDescription": null, "childItems": [
          {"id": 13498, "isSection": 0, "agendaObjectItemNumber": "2026-2387", "agendaObjectItemDescription": "", "childItems": [],
           "agendaObjectItemName": "Father Dan Good, Public Safety Chaplain"}
         ]},
        {"id": 7772, "isSection": 1, "agendaObjectItemName": "PUBLIC HEARINGS", "agendaObjectItemNumber": "",
         "agendaObjectItemDescription": null, "childItems": [
          {"id": 13505, "isSection": 0, "agendaObjectItemNumber": "2026-2394", "agendaObjectItemDescription": "", "childItems": [],
           "agendaObjectItemName": "Public hearing to fix costs for demolition of the structure at 1423 Cedar Park Drive; $4,000.00 (District 3)."}
         ]},
        {"id": 7763, "isSection": 1, "agendaObjectItemName": "RESOLUTIONS HELD OVER", "agendaObjectItemNumber": "",
         "agendaObjectItemDescription": null, "childItems": [
          {"id": 13520, "isSection": 0, "agendaObjectItemNumber": "2026-2408", "agendaObjectItemDescription": "", "childItems": [],
           "agendaObjectItemName": "01-1211 Authorize Agreement with the Mobile County Commission for the design and construction of the Regions Arena; $7,500,000.00 (sponsored by Mayor Cheriogotis) (submitted by Robert Shreve, City Attorney)."}
         ]},
        {"id": 7764, "isSection": 1, "agendaObjectItemName": "CONSENT RESOLUTIONS BEING INTRODUCED", "agendaObjectItemNumber": "",
         "agendaObjectItemDescription": null, "childItems": [
          {"id": 13512, "isSection": 0, "agendaObjectItemNumber": "2026-2400", "agendaObjectItemDescription": "", "childItems": [],
           "agendaObjectItemName": "40-1225 Declare the structure at 701 N. Joachim Street a public nuisance and order it demolished (sponsored by Councilmember Ingram)."}
         ]}
      ]
    }

The four item names, ids and file numbers are the city's, as returned for `Meetings/473`, and since the revision of 2026-11-20 each sits under the heading the city has it under, with that heading's own id and name (7752, 7772, 7763, 7764), each heading cut down to the one child. The `ROLL CALL` heading and its id are as the author gave them. `test_an_item_under_a_consent_heading_is_a_consent_item` reads the headings' names; the order of the headings here is not the agenda's.


### What the city's roll calls print

The lines quoted in Surprises are the evidence M5's migration cites. The first page of the 2026-11-03 minutes, in the city's plain-text form, reads in part:

    The City Council of the City of Mobile, Alabama, met in the Auditorium of the Government
    Plaza on Tuesday, November 3, 2026, at 10:30 a.m., for the regular meeting.
    ...
    Present on Roll Call:
    Chairman:               Small
    Vice-Chairman:          Gregory
    Councilmembers:         Penn, Ingram, Reynolds, Fleming, and Woods
    Absent:                 None

and a resolution in the same minutes is headed:

    RESOLUTION:             40-948-2026

    Sponsored by:           Councilmember Small

which is the code stage 2 will join on.


## Interfaces and Dependencies

No new library. `requests` for the adapter, `pdfplumber` (already installed) for M5's reading only, never imported by the adapter.

In `src/docket/models/protocol.py`:

    class AgendaNotReady(Exception):
        """The source has not published this meeting's agenda yet."""

In `src/docket/adapters/civicclerk.py`, at the end of M2:

    class CivicClerkAdapter:
        items_carry_video_timestamps = False
        def __init__(self, municipality_slug: str, config: dict): ...   # self.delay = max(1.0, float(config.get("delay", 1.0)))
        def list_meetings(self, since: date | None = None) -> list[RawMeeting]: ...
        def fetch_agenda_items(self, meeting: RawMeeting) -> list[RawAgendaItem]: ...   # may raise AgendaNotReady

    def split_item_name(raw: str) -> tuple[str, str | None, str | None]: ...   # title, sponsor, submitter

`split_item_name` applies these steps in order: remove tags (`<[^>]+>`), unescape entities, replace non-breaking spaces with spaces and collapse every run of whitespace to one space; the sponsor is group 1, stripped, of the first match of `\(\s*sponsored by\s+([^)]+)\)` ignoring case, or None; the submitter is the same for `submitted by`; the title is the name with every match of both patterns replaced by a space, whitespace collapsed again, and each match of `\s+([.;,:])` replaced by its group 1. The author ran exactly these steps on 2026-11-20 and they gave, for the fixture's four names and two of Vestavia Hills':

    '01-1211 Authorize Agreement with the Mobile County Commission for the design and construction of the Regions Arena; $7,500,000.00.'
        sponsor 'Mayor Cheriogotis', submitter 'Robert Shreve, City Attorney'; description 'Submitted by Robert Shreve, City Attorney.'
    '40-1225 Declare the structure at 701 N. Joachim Street a public nuisance and order it demolished.'
        sponsor 'Councilmember Ingram', submitter None; description None
    'Public hearing to fix costs for demolition of the structure at 1423 Cedar Park Drive; $4,000.00 (District 3).'
        sponsor None, submitter None
    'Father Dan Good, Public Safety Chaplain'
        sponsor None, submitter None
    'City Manager&rsquo;s Report'  gives  'City Manager’s Report'
    'Public Hearing - Ordinance Number 3363 \xa0- Rezoning - <a href="file://cityhall-smb/x.d">4616 Old Looney Mill Road</a>'
        gives  'Public Hearing - Ordinance Number 3363 - Rezoning - 4616 Old Looney Mill Road'

and `enrich_agenda_item` on each resulting title returned a `clean_title` equal to the title, a `sponsor` of None, and dollars of 7500000.00 for the first and 4000.00 for the third. Under the rule the adapter has today, the first name gives the title `2026-2408 01-1211 Authorize ...`, which enrichment turns into a stored title ending `$7,500,000.00  .` with the sponsor `Robert Shreve, City Attorney`; `test_sponsor_and_submitter_are_split_from_the_name` asserts the new sponsor is `Mayor Cheriogotis` and is not the submitter, so it fails on the old rule for the reason it names.

In `src/docket/services/ingest.py`, at the end of M4:

    def ingest_municipality(slug: str, since: date | None = None) -> IngestResult: ...   # unchanged signature
    def _backlog_settings(adapter_config: dict) -> tuple[date | None, int | None]: ...   # raises ValueError on a bad value
    def _waiting_external_ids(municipality_id: int) -> set[str]: ...
    def reset_agenda_items(slug: str, *, apply: bool = False) -> dict: ...               # raises ValueError: unknown slug, or blocked

The settings, all in `municipalities.adapter_config`, all optional: `delay` (seconds, floor 1.0 in the CivicClerk adapter), `backlog_floor` (`"YYYY-MM-DD"`), `agenda_fetch_cap` (whole number, 0 or more). The two new keys are read by ingest for any adapter.

The command `scripts/reset_agenda_items.py --city <slug> [--apply]`.


## Revision notes

2026-11-20, authored. The scope brief this plan was written from is folded into Purpose and Context and is not committed as a file. Its questions list was empty. What the plan deliberately leaves out, from the brief and from the author's research: votes and member records read from Mobile's minutes, including the API's `minutesItemVotes`, `hasVote` and `passFail` fields (stage 2); coming-up and hearings for Mobile (stage 3); YouTube and transcripts, including the events' `youtubeVideoId` and `externalMediaUrl` (stage 4); Homewood, Hoover, Montgomery and the land-use boards on buildmobile.org; any change to Birmingham's behaviour, including `src/docket/enrichment/sponsors.py` and `src/docket/adapters/granicus.py`; Vestavia Hills' council roster and any change to which Vestavia bodies are listed; Mobile event categories other than City Council; setting `metadata.briefing` for Mobile; item attachments and the Agenda Packet file; an item's section heading and any change to how `is_consent` is decided; `D67`, `D16`, `D33`, issues #62 and #63; the stale scope text in `README.md` beyond what this plan's own edits make false; and deploying, the migration, the settings UPDATE, the reset and every other production write, which are the operator's steps written out above. Two things the goal asked for are left out because the research found they cannot be done as asked, and each becomes a debt row in M6: agenda items for Mobile's meetings before 2024-06-25, which the city's system holds only as PDF files, and minutes links for imported events, whose files are often another meeting's. The brief's `repair_empty_agendas` change (re-opening stuck meetings in ingest or the weekly repair) is replaced by the supervised reset, for the reason in the Decision Log.

2026-11-20, revised by the operator's review revision (written by Claude at the operator's request), before any milestone was executed. The operator had a review of the plan (`review.md`) and a set of proposed replacement blocks checked against the code, the city's system and production; the Surprises section holds what the check observed, and the Decision Log holds each change with its reason. Taken from the review: the reset clears the meeting summaries written from the wrong items; a consent item is known by its heading, which lifts the authored exclusion of "any change to how `is_consent` is decided" for CivicClerk only; the date that decides "not ready" is the city's; an unpublished agenda is not ready; the latest file of a type is the one linked and `createdOn` is compared as a Central date; one session and a connect limit; the next-link check by parts; the roster's two departed members named in full from the city's documents, matched by whole-word surname; the operator's steps one city at a time. Changed from what was proposed, because the check found otherwise: no `hasAgenda` gate (it is true on an empty scheduled agenda); `_upsert_meetings` is left alone (it already replaces a stored link); the code pattern stays `\d{3,4}` (no two-digit code exists); the reset names its four statements and deletes nothing found at run time; the consent test reads the city's real headings, not the stand-in; the organisational chart of October 2020 is not cited; "Scott" stays unresolved and is called an inference; Q3 is recorded as answered and is no longer a condition of the merge; the settings are written before the deploy with Vestavia Hills held at a cap of 0; no Progress line is reworded, now or in M6, since the judge knows an entry by its text and the M4 line is still true as written. Added by the check itself: the decision and debt row on an agenda fetched before its meeting, and the two-digit fraction that Python 3.10 refuses. Test counts changed with the tests: M1 `32 passed` (was 30), M2 `45 passed` (was 41), M3 ten tests (was nine), M4 `5 passed` (was 4).
