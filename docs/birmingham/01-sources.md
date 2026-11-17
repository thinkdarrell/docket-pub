# 1. Where Birmingham's records come from

Everything on `/al/birmingham/` traces back to six places the city itself publishes. Nothing is typed in by hand except the one manifest in section 4 and the transcription of the neighborhood schedule in section 6. This chapter names each source, what it supplies, and what it does not.

| Source | What it supplies | Read by | Decision |
| --- | --- | --- | --- |
| Granicus archive (`bhamal.granicus.com`, view 2) | Meetings, agenda index points, agenda and minutes PDFs, the video clip | `src/docket/adapters/granicus.py` | `0002` |
| The city's website, birminghamal.gov (the council page, the events search, and the event pages its sitemap lists) | The council's calendar events, upcoming and past, used to name the body of a generic-titled clip and to tell a stream test from a meeting | `src/docket/adapters/city_calendar.py` | `0087` |
| The council's YouTube channel (`citycouncilbham`) | Recordings of council and committee meetings, most of which Granicus never carries | `src/docket/adapters/youtube.py` | `0067`–`0070` |
| The 2023 archive manifest | 24 Boutwell-era meetings Granicus did not record, from the Wayback Machine and YouTube | `src/docket/services/archived_meetings.py` | `0033` |
| The council committees' pages on birminghamal.gov (eight, one per standing committee) | Each committee's agenda and minutes PDFs: what the committee took up and what it did, and proof that a committee met when nothing recorded it | `src/docket/adapters/committee_documents.py` | `0095`–`0098` |
| The Community Resource Services Division's neighborhood association meeting schedule (a three-page PDF on the city's asset host, revised February 3, 2026) | The monthly meeting rule, meeting type, place and call-in details of each of the 99 neighborhood associations, for 2026 | saved under `content/coming-up/birmingham/sources/` and transcribed by hand into `neighborhood-schedule.yaml` beside it; loaded by `src/docket/services/neighborhood_schedule.py` | `0110` |

The Birmingham row in `municipalities` (seeded by migration `001`, slug `birmingham`, adapter `GranicusAdapter`, `adapter_config` with the Granicus `base_url` and `view_id`) carries the flags that turn each source on in its `metadata` JSONB: `calendar_url` (migration `038`) and the other calendar keys (migration `043`: the search and sitemap addresses, the department, and `calendar_complete_from`), `youtube_channel` and `youtube_channel_id` (migration `040`), `briefing: true` (migration `037`, which turns on the city-page opener), `committee_document_pages` (migration `045`, the eight committee pages), `coming_up: true` (migration `047`, which turns on the coming-up page, its feed, and the reading of scheduled hearings at ingest), and `council_schedule.weekday` (Tuesday). Each worker task picks the cities it serves by one of those keys, so Birmingham is the only city every stage runs for.

## 1. Granicus: the primary source

Granicus is the city's own meeting archive. The adapter reads two tables on the publisher page:

- **Upcoming meetings** (`#upcoming`). Each becomes a meeting whose external id is `event-<event_id>`. It has an agenda link and nothing else: no minutes, no video. Its agenda items come from the agenda PDF.
- **Archived meetings** (`#archive`). Each becomes a meeting whose external id is the numeric `clip_id`. It may carry an agenda link, a minutes link, and a video (the Granicus player page, never the `.mp4`), plus the clip's running time. Its agenda items come from the player page's **index points**, the chapter markers the clerk sets while the video is recorded; each index point has a chapter id and a time in seconds, which is where timed video links (chapter 5) ultimately come from.

Dates and start times are read from a hidden Unix timestamp on each row and converted to Chicago time. The adapter sleeps at least one second between requests, including failed ones (`GOALS.md` Constraints). The minutes PDF is also fetched here, when present, and parsed into votes (chapter 3).

What Granicus does **not** give us: consent-item body text (the agenda lists consent items as title-only references; the text appears only in the minutes), agenda packets, and any meeting the clerk did not record, which is most committee meetings and all of 2023. Granicus and YouTube between them say that a committee met and show the recording; neither says what the committee took up or what it did. That comes from the committees' own documents (section 5).

## 2. The city calendar: naming the body

Once a day the worker reads the council's events from the city's website into `city_calendar_events`, from three places that each fail alone (`0087`): the council page, which embeds its next four events as JSON; the site's events search, which lists every upcoming event of the City Council department; and the event pages the site's sitemap lists, which are the only place past events can still be read. When the sitemap was first read, on 2026-11-11, it held the council's events back to 2026-10-05 (`calendar_complete_from` in the city's metadata); events the city had already removed from its site are not recovered. Only an event whose department is "City Council" is stored, since other departments have committees too.

The events are used for two things. When a Granicus clip's title is generic ("Regular City Council Meeting") but the day's calendar shows a committee, the meeting-type ladder (chapter 2) can name the committee. And a short or speechless clip on a day the calendar shows no council or committee event is not a meeting but a test of the stream, and is hidden (chapter 2). The calendar does not supply times or a meeting list; a cancelled event (by its stored status or its title) names nothing. `docs/specs/meeting-types.md`, "The city calendar", owns the readers' rules.

## 3. YouTube: the second source

The council streams every meeting, council and committee alike, to its YouTube channel. The worker reads the channel through the YouTube Data API (the uploads playlist, then each video's duration and live-stream start) and decides, for each recording whose title carries a date and a meeting word, whether it belongs to a Granicus meeting already in the database or is a meeting of its own:

- A recording that pairs with a Granicus clip on the same day (by body, and by duration when the day has several) is **attached** to that meeting as a row in `meeting_videos`. A meeting page then shows "Watch on YouTube" beside the Granicus video, and the transcriber can measure where the recording sits on the Granicus clip's clock (chapter 5).
- A committee recording whose Granicus clip the calendar has already named for the same committee is attached to that clip **by name**, so one meeting is not listed twice.
- A recording with nothing to attach to **creates** a meeting of its own, external id `yt-<video id>`, but only once it has been public for three days, so the Granicus clip has a chance to appear first (`0069`). If a Granicus clip for the same day arrives later, it **absorbs** the `yt-` row (`0068`).
- The YouTube pass never writes a meeting's classification itself; it hands the touched rows to the meeting-type ladder, where the recording's cleaned title is one rung (`0067`).

`docs/specs/meeting-types.md` ("The council's YouTube channel") states every rule of this pass, including the title grammar, the part-grouping, and the ambiguous-day handling.

## 4. The 2023 archive: the one hand-made list

Granicus has no 2023 Birmingham meetings. `scripts/manifests/birmingham_2023_archived.json` lists 24 meetings with their YouTube ids and Wayback Machine agenda URLs; `scripts/backfill_archived_meetings.py` creates them through the same ingest path as everything else, keyed `yt-<id>` or `archive-<date>` when there is no video. They have agenda items but no minutes link, so they have no votes, and the video OCR job never claims them because it claims only numeric clip ids. Decision `0033` records why they are keyed outside Granicus ids.

## 5. The committee pages: what a committee took up

Each of the council's eight standing committees has a page on the city's website listing its agenda and minutes PDFs under date headings. Once a day the worker lists those PDFs, fetches the ones it has not read (one request a second), and reads each by fixed rules; no language model reads a committee document (`0098`). Three things about these documents shape everything downstream:

- **The document says what it is; the page is the fallback.** Which committee, which date, and whether it is an agenda or minutes are read from the document's own first lines, because documents are posted under the wrong heading, under another committee's page, and with the wrong year in their file names (`0096`).
- **Minutes are read into items; agendas are only linked.** Minutes share one layout across the eight committees: each thing the committee took up ends with "Action Taken:" and the action. Agendas come in eight layouts, some are scanned images, and an agenda does not say what the committee did (`0097`).
- **A committee's action is not a vote.** Minutes record a motion and a second, not a roll call. The action is kept in the minutes' own words with one of twelve categories ("recommended to the council's consent agenda", "delayed", and so on) and never becomes a row in `votes` or `agenda_items` (`0095`, `0098`).

Minutes can also prove a meeting that no recording shows: when minutes name a committee and date with no meeting row, a row is created (chapter 2). `docs/specs/committee-documents.md` owns every rule.

## 6. The neighborhood schedule: the one transcribed document

The city publishes when its neighborhood associations meet as a PDF table, one row per association: a rule ("First Wednesday of each month @ 5:30 p.m."), a meeting type, and a place or call-in details. Nothing fetches it on a schedule. The PDF is saved in the repository as fetched, its rows are transcribed by hand into a YAML file whose loader refuses it when the saved PDF's digest is not the one recorded, and a test compares every transcribed row with the PDF's own table on every run. The coming-up page (chapter 6) computes each association's dates from its rule and links the city's PDF from every one; a rule the schedule does not state (a meeting moved for a holiday, an association whose row says "No Meetings") gives no date (`0110`). The schedule covers 2026 only. `docs/specs/coming-up.md` owns the file's format and how the next schedule is saved.

## What is never a source

- Nothing is typed in from news coverage or from memory; the editorial feature (blog) cites outside journalism, it does not become data.
- No fact is filled from a default. A meeting with no minutes link has no votes; a meeting with no date stops at the title rung of the ladder (`docs/PRINCIPLES.md`, "Source or silence").

## Identifiers to recognise

The `external_id` prefix on a `meetings` row says which source created it, and the sources never collide because `(municipality_id, external_id)` is unique:

| Prefix | Created by |
| --- | --- |
| a bare number, e.g. `3186` | Granicus clip id |
| `event-<n>` | Granicus upcoming event, before its clip exists; upgraded in place to the clip id when the clip appears (chapter 2) |
| `yt-<video id>` | YouTube recording with no Granicus clip, or a 2023 manifest meeting with video |
| `archive-<date>` | 2023 manifest meeting with no video |
| `cdoc-<committee>-<date>` | A committee's minutes for a meeting no other source had a row for (section 5) |

Next: [2. How a meeting enters the database](02-ingest.md).
