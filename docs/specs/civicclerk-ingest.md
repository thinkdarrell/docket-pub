# CivicClerk ingest

How a city on the CivicClerk system (Mobile, tenant `mobileal`; Vestavia Hills, tenant `vestaviahillsal`) is listed, fetched, capped and reset. The adapter is `src/docket/adapters/civicclerk.py`; the two settings and the reset are in `src/docket/services/ingest.py`. Birmingham is on Granicus and none of this applies to it, except the two settings, which ingest reads for any adapter. Why each rule was chosen is in decisions `0118` to `0122`.

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

A value ingest cannot read (a floor that is not text or not a date; a cap that is true or false, has a fraction, is text, or is below zero) makes the run return one error, `Bad adapter_config for <slug>: <reason naming the key>`, before any request is sent to the city.

## Listing

`list_meetings(since)` sends one request to `Events` with `$orderby=eventDate desc`, `$count=true` and, when there is anything to filter, `$filter`: `eventCategoryId eq <category_id>` and `eventDate ge <since>T00:00:00Z`, joined by ` and `. The date filter is applied by the server, so a floor costs no extra pages.

It sends neither `$top` nor `$skip`. The server pages at 15 rows whatever is asked, and `$top` is a total, not a page size: the next link of a `$top=100` request carries `$top=85`, and a walk under it stops at 100 rows. Each further page is the address the server gives in `@odata.nextLink`, requested exactly as given after the delay. A next link is refused with `ValueError` unless its scheme is `https`, its host (the whole network location, case ignored) is the adapter's own, and its path is under the adapter's base path. A listing of more than 200 pages raises `ValueError`.

## Requests and failures

Every request goes through one `requests.Session` with a limit of ten seconds to connect and thirty to read. Every request an adapter instance sends after its first waits the delay before it is sent, whether the request before it succeeded or failed, and whether it was a listing page, an agenda or a lookup; the request helper (`_get`) is the only place the adapter pauses. A request is tried three times, waiting the delay after the first failure and twice the delay after the second. A failure is a connection error or timeout, a status the server rejects with, or a body that is empty or is not JSON. After the third failure the adapter raises `requests.RequestException` naming the address.

A failed request is never an empty answer. A listing that fails ends the city's run. An agenda request that fails is recorded in the run's errors as `Agenda items for <event id>: <error>`, and the meeting stays unmarked, so the next run asks again.

## What a meeting carries

The start time is the posted wall-clock time. `eventDate` is the city's local time written with a false `Z` (the city's minutes say 10:30 a.m. for `10:30:00Z`), so the `Z` is dropped and the time is not converted. A numeric offset, never observed, is converted to `America/Chicago`.

The agenda link is the city's own Agenda file when the event's `publishedFiles` has one. With no Agenda file and `hasAgenda` true it is the portal page, `https://{tenant}.portal.civicclerk.com/event/{id}/agenda`. Otherwise there is none. The Agenda Packet file is not stored.

The minutes link is the city's own Minutes file, and only for an event the city created on or before its own date. An event created after its date is an imported event: the city loaded it after the meeting was held, and the Minutes file attached to an imported Mobile event is often another meeting's (ten of eleven read on 2026-11-20). `docs/PRINCIPLES.md`, Source or silence: no link is preferred to a wrong one. `createdOn` is a true UTC time and is turned into its `America/Chicago` date before it is compared with the date of `eventDate`; an event with no readable `createdOn` is treated as imported.

Where an event has several files of one type, the one linked is the latest by `publishOn`, the higher `fileId` deciding a tie.

Ingest's upsert writes the listed links over the stored ones, so a meeting stored with the portal page gets the file link on the first run that lists one.

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

Votes: the agenda's `hasVote`, `passFail`, `minutesItemVotes`, `ordinanceNumber` and `resolutionNumber` fields were unset on every item read, and `fetch_votes` returns nothing. A CivicClerk meeting with a minutes link is still marked `votes_scanned` by ingest's vote stage (`D181`). Also not read: item attachments, the Agenda Packet, the events' video fields (`youtubeVideoId`, `externalMediaUrl`), and the text of the minutes.

## Known limits

- Mobile's system holds structured items only for meetings from 2024-06-25 on. Its earlier meetings were loaded on 2024-07-25 as PDF files; they are stored with their agenda link and no items (`D179`).
- An imported event has no minutes link (`D180`).
- An `eventDate` that cannot be parsed dates the meeting today, as it did before the rules above; a fraction of a second with one or two digits is such a value on Python 3.10. None was seen.
- When a listing fails, `ingest_municipality` raises `TypeError` instead of returning its error (`D184`).
- The portal-page form of the agenda link is built by a script-run page no session has opened (`D178`, the operator's look).
- Vestavia Hills lists seven bodies; no agenda of the six that are not the council was read when these rules were written (`D178`).
