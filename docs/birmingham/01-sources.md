# 1. Where Birmingham's records come from

Everything on `/al/birmingham/` traces back to four places the city itself publishes. Nothing is typed in by hand except the one manifest in section 4. This chapter names each source, what it supplies, and what it does not.

| Source | What it supplies | Read by | Decision |
| --- | --- | --- | --- |
| Granicus archive (`bhamal.granicus.com`, view 2) | Meetings, agenda index points, agenda and minutes PDFs, the video clip | `src/docket/adapters/granicus.py` | `0002` |
| City council page on birminghamal.gov | Upcoming calendar events, used only to name the body of a generic-titled clip | `src/docket/adapters/city_calendar.py` | — |
| The council's YouTube channel (`citycouncilbham`) | Recordings of council and committee meetings, most of which Granicus never carries | `src/docket/adapters/youtube.py` | `0067`–`0070` |
| The 2023 archive manifest | 24 Boutwell-era meetings Granicus did not record, from the Wayback Machine and YouTube | `src/docket/services/archived_meetings.py` | `0033` |

The Birmingham row in `municipalities` (seeded by migration `001`, slug `birmingham`, adapter `GranicusAdapter`, `adapter_config` with the Granicus `base_url` and `view_id`) carries the flags that turn each source on in its `metadata` JSONB: `calendar_url` (migration `038`), `youtube_channel` and `youtube_channel_id` (migration `040`), `briefing: true` (migration `037`, which turns on the city-page opener), and `council_schedule.weekday` (Tuesday). Each worker task picks the cities it serves by one of those keys, so Birmingham is the only city every stage runs for.

## 1. Granicus: the primary source

Granicus is the city's own meeting archive. The adapter reads two tables on the publisher page:

- **Upcoming meetings** (`#upcoming`). Each becomes a meeting whose external id is `event-<event_id>`. It has an agenda link and nothing else: no minutes, no video. Its agenda items come from the agenda PDF.
- **Archived meetings** (`#archive`). Each becomes a meeting whose external id is the numeric `clip_id`. It may carry an agenda link, a minutes link, and a video (the Granicus player page, never the `.mp4`), plus the clip's running time. Its agenda items come from the player page's **index points**, the chapter markers the clerk sets while the video is recorded; each index point has a chapter id and a time in seconds, which is where timed video links (chapter 5) ultimately come from.

Dates and start times are read from a hidden Unix timestamp on each row and converted to Chicago time. The adapter sleeps at least one second between requests, including failed ones (`GOALS.md` Constraints). The minutes PDF is also fetched here, when present, and parsed into votes (chapter 3).

What Granicus does **not** give us: consent-item body text (the agenda lists consent items as title-only references; the text appears only in the minutes), agenda packets, and any meeting the clerk did not record, which is most committee meetings and all of 2023.

## 2. The city calendar: naming the body

Birmingham's council page embeds its next few events as JSON. Once a day the worker reads that page into `city_calendar_events`. The events are used for exactly one thing: when a Granicus clip's title is generic ("Regular City Council Meeting") but the day's calendar shows a committee, the meeting-type ladder (chapter 2) can name the committee. The calendar does not supply cancellations, times, or a meeting list, and because the page lists only upcoming events, there is no backfill into the past. `D116` in `docs/DEBT.md` records the known gap: an event can enter and leave the page's short window between two daily reads.

## 3. YouTube: the second source

The council streams every meeting, council and committee alike, to its YouTube channel. The worker reads the channel through the YouTube Data API (the uploads playlist, then each video's duration and live-stream start) and decides, for each recording whose title carries a date and a meeting word, whether it belongs to a Granicus meeting already in the database or is a meeting of its own:

- A recording that pairs with a Granicus clip on the same day (by body, and by duration when the day has several) is **attached** to that meeting as a row in `meeting_videos`. A meeting page then shows "Watch on YouTube" beside the Granicus video, and the transcriber can measure where the recording sits on the Granicus clip's clock (chapter 5).
- A recording with nothing to attach to **creates** a meeting of its own, external id `yt-<video id>`, but only once it has been public for three days, so the Granicus clip has a chance to appear first (`0069`). If a Granicus clip for the same day arrives later, it **absorbs** the `yt-` row (`0068`).
- The YouTube pass never writes a meeting's classification itself; it hands the touched rows to the meeting-type ladder, where the recording's cleaned title is one rung (`0067`).

`docs/specs/meeting-types.md` ("The council's YouTube channel") states every rule of this pass, including the title grammar, the part-grouping, and the ambiguous-day handling.

## 4. The 2023 archive: the one hand-made list

Granicus has no 2023 Birmingham meetings. `scripts/manifests/birmingham_2023_archived.json` lists 24 meetings with their YouTube ids and Wayback Machine agenda URLs; `scripts/backfill_archived_meetings.py` creates them through the same ingest path as everything else, keyed `yt-<id>` or `archive-<date>` when there is no video. They have agenda items but no minutes link, so they have no votes, and the video OCR job never claims them because it claims only numeric clip ids. Decision `0033` records why they are keyed outside Granicus ids.

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

Next: [2. How a meeting enters the database](02-ingest.md).
