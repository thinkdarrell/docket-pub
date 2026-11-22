# CivicClerk ingest

How a city on the CivicClerk system (Mobile, tenant `mobileal`; Vestavia Hills, tenant `vestaviahillsal`) is listed, fetched, capped and reset, and how a city that names a minutes reader (Mobile) has its Minutes files read, paired to their meetings and stored as votes. The adapter is `src/docket/adapters/civicclerk.py`; the settings and the reset are in `src/docket/services/ingest.py`, and the reading of Minutes files in `src/docket/services/minutes_votes.py`. Birmingham is on Granicus and none of this applies to it, except the settings, which ingest reads for any adapter. Why each rule was chosen is in decisions `0118` to `0124`, `0129` and `0130`.

## The city's system

The public read address is `https://{tenant}.api.civicclerk.com/v1/` and needs no login.

An event is one meeting on the city's calendar. `Events` lists them. The adapter reads, of each event: `id`, `eventName`, `eventDate`, `createdOn`, `agendaId`, `hasAgenda`, and `publishedFiles`, a list of files each with `fileId`, `type` (`Agenda`, `Agenda Packet`, `Minutes`), `name` and `publishOn`. `eventCategoryId` 26 is the City Council in both cities.

An agenda is a record of its own with its own number: `Meetings/{agendaId}`, the id the event row gives. It is never asked for by the event's id; the two numbers differ, and `Meetings/{event id}` answers with whatever agenda happens to have that number, another meeting's. The agenda's `items` is a tree whose nodes carry `id`, `isSection` (1 for a heading), `agendaObjectItemName`, `agendaObjectItemNumber`, `agendaObjectItemDescription` and `childItems`.

A file is fetched at `{base}/Meetings/GetMeetingFileStream(fileId=N,plainText=false)`, which answers with the PDF.

## The settings

All are keys of the city's `municipalities.adapter_config`, and all but `tenant` are optional.

- `tenant`: the city's name in the address.
- `category_id`: the event category listed. Absent means every category (Vestavia Hills lists every body).
- `delay`: seconds between requests. The adapter never waits less than one second, whatever the row says: `max(1.0, delay)`, default 1.0.
- `backlog_floor`: a date written `YYYY-MM-DD`. Read by `ingest_municipality` for any adapter and passed to the adapter's `list_meetings` as `since` when the caller gave no `since` of its own; a caller's `since` wins. Absent or null means no floor: the city is listed as far back as its system goes.
- `agenda_fetch_cap`: a whole number of 0 or more. Read by `ingest_municipality` for any adapter: at most that many meetings whose agenda is waiting are fetched in one run, newest meeting first. 0 lists the meetings and fetches no agenda. Absent or null means no cap, and the meetings are walked in the adapter's order.

- `minutes_reader`: the name of the reader of the city's minutes; its only value is `mobile`. Absent or null means none: no Minutes file is fetched, no `minutes_files` row is written, and the city is ingested as it was before the key existed. "Minutes files and the votes read from them" below is what a city that names one gets.
- `minutes_read_cap`: a whole number of 0 or more, read only where a reader is named: at most that many waiting Minutes files are fetched in one run, newest event first. Absent or null means 10. 0 fetches none, while the link rule and the code join go on.

A value ingest cannot read (a floor that is not text or not a date; a cap that is true or false, has a fraction, is text, or is below zero; a `minutes_reader` that is not a reader's name) makes the run return one error, `Bad adapter_config for <slug>: <reason naming the key>`, before any request is sent to the city.

## Listing

`list_meetings(since)` sends one request to `Events` with `$orderby=eventDate desc`, `$count=true` and, when there is anything to filter, `$filter`: `eventCategoryId eq <category_id>` and `eventDate ge <since>T00:00:00Z`, joined by ` and `. The date filter is applied by the server, so a floor costs no extra pages.

It sends neither `$top` nor `$skip`. The server pages at 15 rows whatever is asked, and `$top` is a total, not a page size: the next link of a `$top=100` request carries `$top=85`, and a walk under it stops at 100 rows. Each further page is the address the server gives in `@odata.nextLink`, requested exactly as given after the delay. A next link is refused with `ValueError` unless its scheme is `https`, its host (the whole network location, case ignored) is the adapter's own, and its path is under the adapter's base path. A listing of more than 200 pages raises `ValueError`.

## Requests and failures

Every request goes through one `requests.Session` with a limit of ten seconds to connect and thirty to read. Every request an adapter instance sends after its first waits the delay before it is sent, whether the request before it succeeded or failed, and whether it was a listing page, an agenda, a lookup or a file; the request loop (`_request`, under `_get` for JSON and `fetch_file` for a file) is the only place the adapter pauses. A request is tried three times, waiting the delay after the first failure and twice the delay after the second. A failure is a connection error or timeout, a status the server rejects with, or a body that is empty or is not JSON, or, for a file, does not begin `%PDF-`. `fetch_file` refuses with `ValueError`, before any request, an address a next link would be refused for (Listing, above: `https`, the adapter's own host, under its base path). After the third failure the adapter raises `requests.RequestException` naming the address.

A failed request is never an empty answer. A listing that fails ends the city's run with the one error `Failed to scrape meetings: <error>`, as an unknown city ends it with `Municipality '<slug>' not found`. An agenda request that fails is recorded in the run's errors as `Agenda items for <event id>: <error>`, and the meeting stays unmarked, so the next run asks again.

## What a meeting carries

The start time is the posted wall-clock time. `eventDate` is the city's local time written with a false `Z` (the city's minutes say 10:30 a.m. for `10:30:00Z`), so the `Z` is dropped and the time is not converted. A numeric offset, never observed, is converted to `America/Chicago`.

The agenda link is the city's own Agenda file when the event's `publishedFiles` has one. With no Agenda file and `hasAgenda` true it is the portal page, `https://{tenant}.portal.civicclerk.com/event/{id}/agenda`. Otherwise there is none. The Agenda Packet file is not stored.

The minutes link the listing gives is the city's own Minutes file, and only for an event the city created on or before its own date. An event created after its date is an imported event: the city loaded it after the meeting was held, and the Minutes file attached to an imported Mobile event is often another meeting's (ten of eleven read on 2026-11-20). `docs/PRINCIPLES.md`, Source or silence: no link is preferred to a wrong one. `createdOn` is a true UTC time and is turned into its `America/Chicago` date before it is compared with the date of `eventDate`; an event with no readable `createdOn` is treated as imported. For a city that names a minutes reader the listing's link is not the last word: once a Minutes file has been read, the `minutes_files` table decides each meeting's link, and an imported event's meeting gets the link of the file whose own heading names its date ("Minutes files and the votes read from them", below).

Where an event has several files of one type, the one linked is the latest by `publishOn`, the higher `fileId` deciding a tie.

Ingest's upsert writes the listed links over the stored ones, so a meeting stored with the portal page gets the file link on the first run that lists one. For a reader city the listed minutes links are first passed through `with_paired_links`, so the upsert writes the link the table decides.

## Minutes files and the votes read from them

For a city whose `adapter_config` names a `minutes_reader`, ingest reads the city's Minutes files into votes. What a stored vote holds and what a page prints for it are in `docs/specs/votes.md`, "Votes read by a minutes reader"; this section is which file is read, when, and which meeting it belongs to.

The files. While it lists, the adapter records the Minutes file of every event the listing returned, imported or not (`_event_to_meeting`, the latest Minutes file by the rule above), and `listed_minutes_files()` gives them as `RawMinutesFile(file_id, url, event_external_id, event_date)`, the event's id being the `external_id` of the meeting made from that event. The record is emptied at the start of each listing, and an event before `since` leaves none. `fetch_file(url)` returns one file's bytes.

The table. `minutes_files` has one row per city and file id (`UNIQUE (municipality_id, file_id)`): the file's `url` and `event_external_id`, `status`, `header_date`, `meeting_id`, `page_count`, `votes_stored`, `reader_version`, `attempts`, `error` and `read_at`. `status` is one of five. `paired`: the file is the minutes of `meeting_id`, whose reader votes were read from it; a partial unique index allows one `paired` row per meeting. `superseded`: the file names a meeting another file holds; it keeps the id of the meeting it lost. `not_minutes`: its heading printed no single date (Mobile's file 449 is a letter and file 869 an agenda). `no_meeting`: its heading names a date before the city's `backlog_floor`, or a date on which the city has no meeting row or more than one, hidden rows counted. `error`: the fetch or the read raised; `error` holds the text and `attempts` the tries.

Pairing. The date is the one the file's own heading lines print (`MUNICIPAL BUILDING, MOBILE, ALABAMA, NOVEMBER 3, 2026`), when there is at least one such line and all agree; the event the file is attached to does not date it (decision `0123`). With exactly one meeting M of the city on that date: the file pairs when no `paired` row names M, or when the row that does is this same file; when another file holds M, this file pairs only if it sits on M's own event (`event_external_id` equal to M's `external_id`), and the other row becomes `superseded`; otherwise this file is `superseded` (decision `0124`). Before any row becomes `paired` for M, every other `paired` row naming M is set `superseded` in the same transaction.

Storing. A pairing deletes M's votes that carry `minutes_reader` (their member votes and attachments go by cascade), inserts the file's votes with one multi-row statement and their member votes with a second, sets M's `minutes_url` to the file's address, sets `minutes_url` to NULL on every other meeting of the city whose link is that address (the listing gives a file to the meeting of its event, which need not be the meeting its heading dates), and writes the file's row, all in one transaction per file. A link someone removed or set by hand on a vote being replaced is put on the vote that replaces it (`docs/specs/votes.md`). A file recorded `not_minutes`, `no_meeting` or `superseded` sets `minutes_url` to NULL on every meeting of the city whose link is that file's address, in the same transaction, so a link to a file that is not the meeting's minutes goes the moment the file is read. A file that held a meeting and, read again, no longer holds it takes that meeting's reader votes and that link with it. A read that fails says nothing about the file: an `error` written over a row that had a pairing keeps the row's date, meeting, page count and vote count, and no vote and no link is touched (decision `0130`). Such an `error` row still holds its meeting for as long as the meeting's `minutes_url` is the row's address: a later read that no longer pairs it there takes the votes and the link as a `paired` row's would. An `error` row whose meeting's link is another file's address (it was `superseded` before it failed, or another file has taken the meeting since) holds nothing (decision `0131`).

The link rule. `with_paired_links(municipality_id, raw_meetings)`, called after the listing and before the upsert, gives each listed meeting the address of the `paired` file that names it; failing that, the address of an `error` row that names it where that address is the meeting's stored `minutes_url`, so a failed re-read does not blank the link of a meeting that keeps its votes (decision `0131`); failing that, the listing's own link while the file that link names has no row or an `error` row; failing that, none.

Which files are read. Stage 4b of `ingest_municipality`, after the vote stage, calls `read_listed`: of the listed files, newest event first, those waiting are the ones with no row, those whose row's `reader_version` is below the reader's `READER_VERSION`, and those whose row is `error` with fewer than three attempts; the first `minutes_read_cap` of them are read. A file read again under a newer version starts with `attempts` 1; only a retry of an `error` row at the current version adds to the count, a retry that succeeds included. Every file taken is fetched and read first, with no transaction open and nothing written; then each outcome is stored in its own transaction, in the order taken. An exception while fetching or reading is that file's `error` and the run goes on; an exception while storing leaves the earlier files committed and is the stage's one error. Then `link_votes_by_code` attaches coded votes to agenda items (`docs/specs/votes.md`). A second run with nothing waiting fetches nothing and writes nothing. The stage does not consult `votes_scanned`: the vote stage still marks a CivicClerk meeting that has a minutes link, and nothing reads the mark for a reader city.

What the run reports. One line at INFO, `Minutes files: read=<n> paired=<n> superseded=<n> not_minutes=<n> no_meeting=<n> errors=<n> votes=<n> waiting=<n>`, then `Minutes votes linked by code: <n>`. The counts are of each file as it was read: a file paired and then superseded by a later file of the same run is counted `paired`, with its votes, so the table and not the line says how many meetings are paired. `waiting` is the files the cap left unread. A file that could not be read adds `Minutes file <file id>: <error>` to the run's errors and does not stop the join; a failure of the stage itself adds `Minutes files: <error>`, and the join waits for the next run. The votes stored are added to the run's `votes_inserted`. With a cap of 0 the stage still runs: the links are decided by the table, nothing is fetched, the line says `read=0` with the number waiting, and the join runs.

By hand. `scripts/read_minutes_votes.py --city <slug> --limit <n> [--apply]` runs the same read for one city through `minutes_votes.read_city`, which lists the city from its `backlog_floor`; `--limit` is required and takes the place of the cap. Without `--apply` the files are fetched and read, the same statements run on one connection opened after the last file is read, and it is rolled back; the code join is not run. It prints `database: <host>/<name>` first, then one line per file (`file <id> on event <event> names <date> -> paired, <n> votes`, or `-> superseded`, `-> not_minutes`, `-> no_meeting`, `-> error: <reason>`, the date only where the heading printed one), the totals in the words of the log line, and `dry run: nothing changed` or `applied`. An unknown city, a city that names no reader and a setting that cannot be read each print their reason on stderr and exit 2 before any request to the city. `docs/specs/operations.md`, Railway specifics, gives the order it is run in.

How the reading is stopped without a deploy, and how the reader's work is taken out of production, are in `docs/specs/operations.md`, Railway specifics. A wrong reading is corrected in `mobile_minutes.py` with `READER_VERSION` raised: every file whose row is below it is read again, the cap a run, and each meeting's reader votes are replaced.

## What an item carries

A heading (`isSection`, or a node with no number and at least one child) is not an item. Each other node with a name is one.

- `title`: the city's item name alone, with tags and entities removed and the "(sponsored by ...)" and "(submitted by ...)" parentheticals taken out. Mobile writes an ordinance or resolution code as the first word of the name (`01-1211 Authorize Agreement with ...`), and it stays there: `^(\d{2}-\d{3,4})\b` on the stored title gives the code the city's minutes print as `RESOLUTION: 40-948-2026`. The code is in no other field of the city's answer.
- `item_number`: the city's file number (`2026-2408`), from `agendaObjectItemNumber`. It is not put before the title.
- `sponsor`: what the first "(sponsored by ...)" says.
- `description`: `agendaObjectItemDescription`, cleaned, followed by the sentence `Submitted by <submitter>.` when the name had a "(submitted by ...)", and cut at 300 characters.
- `is_consent`: true when any heading above the item in the agenda's tree has "consent" in its name (Mobile's `CONSENT RESOLUTIONS HELD OVER` and `CONSENT RESOLUTIONS BEING INTRODUCED`), or when the item's own title does. The mark is carried down: an item under a heading that does not say "consent", itself under one that does, is a consent item. No agenda read had a heading under a heading.

The function that splits a name is `split_item_name` in the adapter. After the split the title holds no attribution, so ingest's enrichment keeps the adapter's sponsor and leaves the title as it is.

## An agenda that is not ready

`fetch_agenda_items` raises `AgendaNotReady` (`src/docket/models/protocol.py`) in three cases: the event's `agendaId` is 0 or absent (no request is made); the agenda the city returns says `agendaIsPublish` false, whatever it holds; or the agenda holds no item and the meeting's date is today or later, today being the date in `America/Chicago`. `hasAgenda` is not used to skip a request: it is true on a scheduled meeting whose agenda record is empty.

Ingest passes such a meeting by. It is not marked `agenda_items_scraped`, nothing is reported, and under a cap it does not count as a fetch. The next run asks again, so an agenda is stored within a day of the city publishing it.

An agenda with no item for a meeting already held returns an empty list, and the meeting is marked: an imported Mobile meeting, which has no structured items, is asked for once and not daily.

For a meeting the adapter instance did not list, the agenda id is looked up with one request, `Events?$filter=id eq <event id>`; an answer without that event raises `ValueError`.

## The cap

Under a cap, ingest reads which of the city's meetings are waiting (`agenda_items_scraped` not true, a meeting with no `processing_status` row included) and walks the listed meetings newest first. A waiting meeting is fetched until the count of fetches reaches the cap, and passed over after. A fetch that fails counts, so a failing site is not asked again and again in one run; a meeting not ready does not. The run logs one line at INFO, `Agenda fetches: <n> of cap <cap>, <k> still waiting`, where `<k>` is the listed meetings that were waiting at the start and are still unmarked at the end: those passed over, those not ready, and those whose fetch failed.

## A stored agenda is not fetched again

The adapter sets the class attribute `items_carry_video_timestamps = False`. Ingest reads it with a default of true and, for an adapter that says false, never re-fetches the agenda of a meeting already marked. An adapter that says nothing (Granicus) is asked again for its video timestamps as before (`docs/specs/video-links.md`).

It follows that an agenda fetched before its meeting is fetched once. Mobile publishes an agenda some days ahead; an item the city adds after ingest has stored the agenda is not seen (`D183` in `docs/DEBT.md`).

## The reset

`scripts/reset_agenda_items.py --city <slug> [--apply]` removes what is stored for one city so that ingest fetches it again. It exists because every CivicClerk item stored before the adapter asked by agenda id may be another meeting's, and nothing in the database tells a right item from a wrong one. It runs `reset_agenda_items(slug, apply=...)` in `src/docket/services/ingest.py`.

The script prints `database: <host>/<name>` first, the host and database name of `DATABASE_URL` and nothing else of it. Then one count a line, as `<key>: <number>`: `meetings`, `meetings_scraped`, `meetings_with_summary`, `agenda_items`, `audit_rows`, `vote_links`, `transcript_segments`, `minutes_discrepancies`. Without `--apply` it ends `dry run: nothing changed` and has only read. With `--apply` it adds `audit_rows_deleted`, `agenda_items_deleted`, `summaries_cleared`, `meetings_reopened` and ends `applied`.

An apply runs four statements, each scoped to the one city, in the transaction the counts were read in: it deletes the `processing_status_audit` rows of the city's items; deletes the city's agenda items (their badges, batch items, search cards and hearing links go by their own cascades); sets the five summary columns of the city's meetings to NULL (`executive_summary`, `executive_summary_voice`, `ai_prompt_version`, `ai_metadata`, `ai_generated_at`), since a summary written from the deleted items is as untrustworthy as they were; and sets `agenda_items_scraped` FALSE on the city's `processing_status` rows. The meetings, their links and `votes_scanned` are not touched. With `ai_prompt_version` NULL the meeting stage writes a new summary once all of a meeting's refilled items have theirs, and none is shown in between. `meetings_reopened` counts every `processing_status` row of the city, marked or not; `meetings_scraped` is the number that were marked.

The guard: a city whose items are referenced by any `vote_agenda_items`, `transcript_segments` or `minutes_discrepancies` row is refused, with or without `--apply`, with `Refusing to reset '<slug>': its agenda items carry <n> vote links, <n> transcript segments and <n> minutes discrepancies`, and the script exits 2. So it cannot be turned on Birmingham. An unknown city prints `Municipality '<slug>' not found` and exits 2. Only the vote-link half of the guard has a seeded test (`tests/integration/test_reset_agenda_items.py`); the other two tables are read by the same condition and no test seeds them.

It is run once per city. A second `--apply` after ingest has refilled the city deletes the refilled items. `docs/specs/operations.md`, Railway specifics, says where it is run from.

## Watching a refill

After a reset the daily ingest refills the city, its cap of agendas a run, newest first. Two read-only queries show it. Meetings and meetings with items, by city:

    SELECT mu.slug, count(*) AS meetings,
           count(*) FILTER (WHERE EXISTS (SELECT 1 FROM agenda_items a WHERE a.meeting_id = m.id)) AS with_items,
           count(*) FILTER (WHERE m.minutes_url IS NOT NULL) AS with_minutes,
           max(m.meeting_date) FILTER (WHERE m.agenda_url IS NOT NULL) AS newest_with_agenda
      FROM meetings m JOIN municipalities mu ON mu.id = m.municipality_id
     WHERE mu.slug IN ('mobile', 'vestavia_hills')
     GROUP BY 1 ORDER BY 1;

The size of the database, and the items waiting for a summary, by city:

    SELECT pg_size_pretty(pg_database_size(current_database())) AS database_size;

    SELECT mu.slug, count(*) AS pending_items, min(m.meeting_date) AS oldest, max(m.meeting_date) AS newest
      FROM agenda_items a JOIN meetings m ON m.id = a.meeting_id
      JOIN municipalities mu ON mu.id = m.municipality_id
     WHERE a.processing_status = 'pending'
     GROUP BY 1 ORDER BY 1;

`with_items` rises by about the cap each day. The AI stage claims items newest meeting first across cities, so while a city's backlog drains, an older Birmingham item waits longer; the second query shows how many, and lowering a city's cap is the remedy. Setting `agenda_fetch_cap` to 0 stops a city's agenda fetches without a deploy; the listing continues.

## What is not read

Votes in the city's structured fields: the agenda's `hasVote`, `passFail`, `minutesItemVotes`, `ordinanceNumber` and `resolutionNumber` were unset on every item read, and `fetch_votes` returns nothing; a reader city's votes come from its Minutes files instead, and a city that names no reader (Vestavia Hills) has none. `fetch_minutes_text` returns None and no minutes text is stored on the meeting. Also not read: item attachments, the Agenda Packet, and the events' video fields (`youtubeVideoId`, `externalMediaUrl`). The minutes reader does not read a code line that is not `RESOLUTION` or `ORDINANCE`, an optional colon, and two digits, three or four, and four, hyphens between (seven such lines among Mobile's files are malformed, `D190`), and reads no agenda item out of the minutes: a vote before 2024-06-25 is stored with the minutes' code and caption and no `agenda_items` row is made.

## Known limits

- Mobile's system holds structured items only for meetings from 2024-06-25 on. Its earlier meetings were loaded on 2024-07-25 as PDF files; they are stored with their agenda link and no items (`D179`).
- A Mobile meeting has votes and a paired minutes link only where the city's files hold minutes whose heading names its date: of the 135 imported meetings, 29 had none on 2026-11-21, and they show no minutes link and no votes (`D189`).
- Mobile serves a file as a download (`content-disposition: attachment`), so a browser may save the minutes and ignore `#page=<n>` (`D188`).
- A vote in the minutes whose code no stored agenda item opens with has no item page (`D183`).
- An imported event's meeting in a city that names no reader has no minutes link (decision `0119`).
- An `eventDate` that cannot be parsed dates the meeting today, as it did before the rules above; a fraction of a second with one or two digits is such a value on Python 3.10. None was seen.
- The portal-page form of the agenda link is built by a script-run page no session has opened (`D178`, the operator's look).
- Vestavia Hills lists seven bodies; no agenda of the six that are not the council was read when these rules were written (`D178`).
