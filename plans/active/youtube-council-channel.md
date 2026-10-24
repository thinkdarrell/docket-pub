# The council's YouTube channel becomes Birmingham's second source: every committee meeting the clerk never put on Granicus appears once, named, with its video, and the ones Granicus did record gain their name and a second link

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

docket.pub indexes Birmingham from one place: the Granicus publisher page at https://bhamal.granicus.com/ViewPublisher.php?view_id=2. The city clerk publishes the Tuesday council meetings there, plus a handful of short committee clips that happen to be recorded in the council chamber. The council's own YouTube channel, citycouncilbham (channel id `UCxKV8MgjDbqw9PMGTsF_NUw`), carries every committee meeting as a live stream, and those never reach Granicus. Measured on 2026-10-24: the channel's streams tab has 121 meeting-titled streams for 2026, 47 council and 74 committee, while Granicus has 5 committee clips for the year. The Committee of the Whole meeting of 2026-09-30 (3 hours 10 minutes, video `6Cocqqq95Ew`) is one of roughly 70 Birmingham committee meetings of 2026 that docket.pub does not know exist. Across all years the channel holds about 870 meeting-titled videos (285 live streams since 2024 and 1,736 uploads back to 2015).

After this plan, every meeting the council records on YouTube appears on docket.pub exactly once. A committee meeting Granicus never had becomes a meeting row keyed to its YouTube video, classified by its title ("Committee of the Whole", "Budget and Finance Committee"). A meeting Granicus already has gains a YouTube link and, where Granicus called it "Regular City Council Meeting", the body name from the YouTube title, instead of a second row. A daily worker task keeps this up, and a backfill script runs the same code over the whole channel once. YouTube-only meetings are transcribed by the same transcriber that reads Granicus clips today, so a Committee of the Whole row, which has no agenda, still has content.

How to see it working once the whole plan has shipped and the operator has run the backfill on production: open https://docket.pub/al/birmingham/meetings/?type=committee and find "Committee of the Whole" dated Sep 30, 2026, whose page offers "Watch video · YouTube (council channel)" and, a few days later, a transcript; open the Sep 28, 2026 committee row and read "Budget and Finance Committee" with the provenance line "The council's YouTube recording names it."; open https://docket.pub/al/birmingham/ and read in the footer that the records come from bhamal.granicus.com and www.youtube.com; and see the Committees filter count for 2026 near 75 rather than 5.

## Progress

Nothing has been executed. Every entry below is open. A completed entry is written as `- [x] (YYYY-MM-DD HH:MMZ) <text>` with the time the work was observed, never an estimate, and an entry's text is never reworded once written (decision `0037`; the judge in `docs/capabilities/judge-milestone.md` identifies entries by text).

- [ ] M1: `docket.adapters.youtube` lists a channel's uploads through the YouTube Data API v3 from a fake transport in tests; `docket.services.youtube_meetings.parse_title` reads the date and the cleaned title out of every title shape in the inventory and rejects the non-meeting ones; `group_videos` folds parts and test streams into one candidate per date and body with the longest video as the recording; `tests/unit/test_youtube_adapter.py` and `tests/unit/test_youtube_titles.py` fail before and pass after.
- [ ] M2: migration 040 creates `meeting_videos`, adds `meetings.duration_s`, re-creates the `type_source` CHECK with `video`, and writes `youtube_channel` and `youtube_channel_id` into Birmingham's metadata; `RawMeeting.duration_s` exists, the Granicus adapter fills it from the archive row's Duration cell, and `_upsert_meetings` writes it on INSERT and UPDATE; `tests/integration/test_040_migration.py` and the new cases in `tests/unit/test_granicus_adapter.py` and `tests/integration/test_ingest_meeting_types.py` pass.
- [ ] M3: the ladder's new rung `video` names a row from its YouTube recording's cleaned title; `_MEETING_ROWS_SQL` carries the row's YouTube clean titles; `TYPE_SOURCES` lists `video`; the admin override still sits above it; `docs/specs/meeting-types.md` describes the rung; the new cases in `tests/unit/test_meeting_types.py` pass.
- [ ] M4: `youtube_meetings.sync_city` runs the matching ladder (attach to council, attach to the day's committee candidate, pair by duration, create after 3 days), the absorption check, and the resolver call over the rows it touched; the worker task `youtube_ingest` runs daily at 06:45; `scripts/backfill_youtube_meetings.py --city birmingham --dry-run` prints a decision per date; `docs/runbooks/cron-worker.md` has the row; `tests/integration/test_youtube_sync.py` passes.
- [ ] M5: the meeting page prints the YouTube link and the parts, the provenance line for a `video` row, and `city_provenance` lists every source host of the last 180 days so the footer and the sources paragraph name both; the operator has created the API key, set `YOUTUBE_API_KEY` on the worker, deployed, run the backfill dry run and then the write on production, and the counts are recorded here; the web tests pass.
- [ ] M6: the transcriber reads a `yt-` meeting's audio through yt-dlp, the four eligibility filters admit `yt-` ids, `transcriber/tests` pass, the operator has rebuilt the image and the Committee of the Whole of 2026-09-30 has a transcript on the site.
- [ ] M7: the durable decisions graduate to `docs/decisions/`, `docs/specs/meeting-types.md` and `docs/specs/operations.md` read in the present tense, the follow-ups are recorded in `docs/DEBT.md`, and the plan moves to `plans/completed/`.

## Surprises & Discoveries

Found while authoring, on 2026-10-24, before any milestone ran:

- Observation: the channel's committee meetings are live streams, which YouTube lists under the channel's streams tab and not its videos tab. A flat listing of the videos tab alone finds one 2026 meeting; the streams tab finds 121.
  Evidence: `yt-dlp --flat-playlist --print "%(title)s" https://www.youtube.com/@citycouncilbham/videos` printed 1,736 titles with one `.26` meeting date; the same against `/streams` printed 285 titles with 121 `.26` meeting dates. The uploads playlist the Data API exposes contains both.
- Observation: no Committee of the Whole date of 2026 exists in any Granicus view. The only 2026 Wednesday clip on Granicus is the June 3 budget hearing.
  Evidence: `curl https://bhamal.granicus.com/ViewPublisher.php?view_id=N` for N in 1..15 and a grep for each fourth Wednesday of 2026 printed 0 for every date; a weekday scan of view 2 listed 2026-06-03 as the only Wednesday.
- Observation: `classify_title` returns the trailing date as part of `body_name` when given a raw YouTube title, so titles must be cleaned first.
  Evidence: `classify_title("Committee of the Whole Meeting 9.30.26")` printed `committee regular 'Committee of the Whole Meeting 9.30.26'`; `classify_title("Committee of the Whole Meeting")` printed body name `Committee of the Whole`.
- Observation: a YouTube title is sometimes date-first ("10.13.26 Public Safety Committee meeting"), sometimes two bodies with a slash ("Committee of the Whole/Administration & Governmental Affairs Committee Meeting 3.12.26"), sometimes "&" for "and" ("Budget & Finance Committee Meeting 6.22.26"), and the council posted seven streams titled "Birmingham City Council Meeting 10.13.26" of 0 to 2 minutes before the 30-minute one.
  Evidence: the streams listing of 2026-10-24, kept in the Artifacts section.
- Observation: anything written to a Granicus row's `body_name` outside the ladder is undone the next morning, because `ingest_municipality` calls `meeting_types.resolve_and_store` over every listed row and a schedule-rule resolution carries `body_name = None`.
  Evidence: `src/docket/services/ingest.py` stage 3b and `_changes` in `src/docket/services/meeting_types.py`, read on 2026-10-24.
- Observation: `meetings.start_time` cannot pair a YouTube stream with a Granicus clip: the stored Granicus values are wrong by construction (issue #88, archived clips carry 02:00). Durations can: Granicus 25 minutes against YouTube 23 minutes on 2026-09-28, Granicus 6 minutes against YouTube 13 minutes on 2026-10-05.
  Evidence: the view 2 duration cells and the yt-dlp duration field, same day.

M1 session, 2026-10-24 (observed):

- Observation: the baseline before any edit passed; the tool printed six checks, not the seven the Concrete Steps guessed.
  Evidence: `./tools/verify` at 22:14Z printed `verify: all 6 checks passed in 107s.` (test-db, unit+web+services, integration, judge-fixtures, workflows, transcriber, plans lines all `ok`).
- Observation: the two new test files fail before the modules exist, each test failing on its own import rather than the files failing collection.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_youtube_titles.py tests/unit/test_youtube_adapter.py -q -p no:cacheprovider` printed `59 failed in 0.54s`; the reasons were 18 × `ModuleNotFoundError: No module named 'docket.adapters.youtube'` and 41 × `ModuleNotFoundError: No module named 'docket.services.youtube_meetings'`.

## Decision Log

- Decision: the source is the YouTube Data API v3 with an API key, not yt-dlp, for the web and worker images.
  Rationale: YouTube answers datacenter addresses such as Railway's with "sign in to confirm you're not a bot" when scraped; the Data API lists a channel from anywhere, gives durations and live-stream start times in the same call, and the whole channel costs about 100 units of a 10,000-unit free daily quota. The operator has a Google Cloud account and approved creating the key.
  Date/Author: 2026-10-24, the operator and Claude.
- Decision: the YouTube pass never writes a classification; the ladder gains a rung `video` that reads the recording's cleaned title.
  Rationale: the resolver re-runs over every Granicus row every morning and would undo a body name written around it. Evidence enters the ladder with its own `type_source`, which the provenance line can name honestly; the admin lock stays above it.
  Date/Author: 2026-10-24, Claude, after the design review.
- Decision: pairing uses recording duration; `meetings.duration_s` is added and the Granicus adapter fills it.
  Rationale: start times are known to be wrong (issue #88) and the resolver already refuses to read them; the publisher page prints each clip's duration and YouTube reports each video's, and the observed 2026 overlaps pair correctly on duration and not on anything else available.
  Date/Author: 2026-10-24, Claude.
- Decision: a YouTube video may create a new row only when it is at least 3 days old by publish time, and each daily run re-checks its own recent `yt-` rows against newly arrived Granicus clips (absorption).
  Rationale: Granicus clips post within a day or two of a meeting; waiting lets the Granicus row exist first so the video attaches instead of racing it. Absorption covers a clip that arrives later still, so the "one row per meeting" promise holds in both orders.
  Date/Author: 2026-10-24, Claude.
- Decision: on an ambiguous committee day (more candidates than groups, or the reverse, with no duration pair), the YouTube video creates its row, the Granicus clips are left alone, and the date is logged at WARNING and listed by the backfill.
  Rationale: a cosmetic duplicate is recoverable in admin; a wrong merge misattributes a recording. Observed ambiguous days in 2026 number one (2026-09-28).
  Date/Author: 2026-10-24, Claude.
- Decision: the footer and the sources paragraph list every source host of the last 180 days; there is no run-log table.
  Rationale: `city_provenance` reads the newest row's host today and would flip to www.youtube.com the first time a YouTube row is newest. Listing hosts is one query; a run-log table is a second system for a fact Healthchecks and the worker log already hold.
  Date/Author: 2026-10-24, Claude.
- Decision: transcripts for YouTube-only meetings are in scope (M6); YouTube's own captions and agenda items derived from transcripts are out of scope.
  Rationale: a Committee of the Whole row has no agenda, so the transcript is its only content. Captions have no speakers and nothing official to compare against. Derived agenda items would be inferences and need a source flag the schema lacks; the operator wants that considered later, together with a meaningful title for such rows.
  Date/Author: 2026-10-24, the operator.
- Decision: the migration is 040, leaving 039 to the still-open M6 of `plans/active/meeting-types-name-the-body.md`.
  Rationale: the runner reads the number from the module name, so a gap costs nothing, and the two plans then never collide.
  Date/Author: 2026-10-24, Claude.
- Decision: a group's duration for pairing is the total over its parts, and a group whose date has a Granicus candidate with no stored duration is never created (`no_duration`).
  Rationale: from the operator's external review of the plan. Granicus records one clip where the stream broke into parts, so the primary alone under-measures; and the historical backfill runs over rows whose `duration_s` is filled by the first ingest after deploy, so a run before that ingest must refuse rather than twin every clip. Two further points from the same review were taken as written: paging stops only after a whole page is older than the cutoff, and the duration parser accepts any subset of hour, minute, and second tokens (the live page uses a non-breaking space between them). Two were declined: hyphenated or spaced date tokens (none exist in the 2,021 titles inventoried; the inventory is the contract, and a new shape is a one-line test and regex later), and a yt-dlp cookie file as a requirement (kept optional through `TRANSCRIBER_YTDLP_COOKIES`, since the transcriber runs from a home address that YouTube does not challenge today).
  Date/Author: 2026-10-24, Claude, from the operator's review.

## Outcomes & Retrospective

Nothing has shipped. The yardstick is the Purpose above: the Committee of the Whole of 2026-09-30 visible once, named, with video and transcript, and no 2026 date on the Birmingham list showing two rows for one meeting. Each milestone session appends its outcome here; the M7 session writes the retrospective.

## Context and Orientation

docket.pub is a Flask application over PostgreSQL in `src/docket/`, run on Railway as a web service and a cron worker, with a GPU transcriber in `transcriber/` that runs on the operator's home machine. Read `AGENTS.md` first; it is the map.

A **meeting row** is one row of the `meetings` table (`src/docket/models/meeting.py` is its dataclass). Its `external_id` is unique per city: Birmingham rows from Granicus carry the numeric clip id (`"2024"`) or `event-N` for a meeting listed before it was recorded; the 2023 Boutwell Auditorium rows that `src/docket/services/archived_meetings.py` created from YouTube carry `yt-<video id>`. This plan reuses `yt-<video id>` for rows whose only recording is on YouTube. The columns this plan reads or writes: `title` (the source's own name for the recording), `meeting_date`, `meeting_type` / `session_kind` / `body_name` / `type_source` (the classification, migration 038), `type_locked_at` (the admin lock), `video_url`, `source_url`, `start_time`, `is_hidden`, and the new `duration_s`.

**Ingest** is `src/docket/services/ingest.py`. `ingest_municipality(slug)` asks the city's adapter (`src/docket/adapters/granicus.py` for Birmingham, chosen by `municipalities.adapter_class`) for `RawMeeting` objects (`src/docket/models/protocol.py`), upserts them in `_upsert_meetings`, fetches agenda items, then calls `meeting_types.resolve_and_store` over every listed row. The worker task `ingest_all` (`src/docket/worker/tasks.py`, scheduled in `src/docket/worker/scheduler.py` at 06:00 America/Chicago) runs it daily for every active city. Tasks are wrapped by `_safe_run`, which pings Healthchecks through `src/docket/worker/health.py`; each task has an env var named there.

**The ladder** is `src/docket/services/meeting_types.py`. `resolve(municipality, meeting, calendar_events=..., item_count=...)` is pure and returns a `Resolution(classification, type_source, calendar_event_id)` or `None` for a locked row; its rungs are admin lock, specific title, city calendar, schedule rule, generic title. `_load` reads rows with `_MEETING_ROWS_SQL`, `_changes` resolves them and keeps the ones whose five columns differ, `_write` updates them in one statement. `classify_title` in `src/docket/adapters/_helpers.py` turns a title into a `Classification(meeting_type, session_kind, body_name)`; the generic case is `("council", "regular", None)`.

**The site** reads rows through `src/docket/services/query.py` and renders `src/docket/web/templates/meeting_detail.html` (the meeting page; lines near 77 print the provenance sentence and lines near 414 the "Watch video" link). The footer (`partials/footer.html`) and the sources paragraph (`partials/page_sources.html`) call the Jinja global `city_provenance`, backed by `briefing.city_provenance` in `src/docket/services/briefing.py` near line 1225, which today takes the host of the newest non-hidden row's `source_url`.

**The transcriber** is `transcriber/transcriber/`. `cli.py` claims an eligible meeting through `db.py` (`_CANDIDATE_SQL`, `_MEETING_SQL`, `meeting_source`, each filtered by `external_id ~ '^[0-9]+$'`), builds a Granicus download URL with `audio.download_url_for(external_id)`, and reads it with ffmpeg in `audio.fetch_audio`. `src/docket/services/transcripts.py` near line 319 lists transcript debt with the same numeric filter. `src/docket/services/video_ocr.py` near line 122 also filters numeric ids and must keep doing so: there is no vote board on committee video.

**YouTube Data API v3**, the service this plan adds as a source. Three read-only calls, each one quota unit, all `GET https://www.googleapis.com/youtube/v3/...?key=<key>`: `channels?part=contentDetails&forHandle=citycouncilbham` returns the uploads playlist id under `items[0].contentDetails.relatedPlaylists.uploads` (for this channel it is `UUxKV8MgjDbqw9PMGTsF_NUw`, the channel id with `UC` replaced by `UU`); `playlistItems?part=snippet,contentDetails&playlistId=<uploads>&maxResults=50&pageToken=<token>` pages through every upload including completed live streams, newest first, giving `contentDetails.videoId`, `snippet.title`, and `contentDetails.videoPublishedAt`; `videos?part=contentDetails,liveStreamingDetails,snippet&id=<up to 50 ids>` gives `contentDetails.duration` as an ISO 8601 duration such as `PT3H10M6S`, `liveStreamingDetails.actualStartTime` for a finished stream, and `snippet.liveBroadcastContent` (`none` once a stream has ended; `live` and `upcoming` are skipped). A 403 whose error reason is `quotaExceeded` ends the run; a 400 means the key is wrong.

**Terms.** A **candidate** is a YouTube video whose title carries a meeting date and a meeting word. A **group** is the candidates of one date and one body, folded into one meeting with the longest video as its recording. A **Granicus candidate row** for a committee group is a non-`yt-` row on the same date that is either committee-typed with no `body_name`, or council-typed with zero agenda items and no minutes link while another council row that day has agenda items. **Attach** means inserting a `meeting_videos` row for an existing meeting; **create** means inserting a `yt-` meeting row and its `meeting_videos` row; **absorb** means moving a `yt-` row's recordings onto a Granicus row that arrived later and removing the `yt-` row.

## Plan of Work

Build from the outside in: first the pure pieces (the API client and the title parser), then the schema and the Granicus duration, then the ladder rung, then the matching and the task, then the site and the production run, then the transcriber, then the close.

M1 adds `src/docket/adapters/youtube.py` (a thin client returning `YouTubeVideo` dataclasses, with the HTTP call injectable so tests pass a fake) and the pure half of `src/docket/services/youtube_meetings.py` (`parse_title`, `clean_title`, `body_key`, `group_videos`). M2 adds migration `src/docket/migrations/040_youtube_recordings.py` and the duration plumbing through `RawMeeting`, the Granicus adapter, `_upsert_meetings`, and `Meeting.from_row`. M3 edits `src/docket/services/meeting_types.py`: `_MEETING_ROWS_SQL` gains an array of the row's YouTube clean titles, `resolve` gains the rung, `TYPE_SOURCES` gains `video`, and the spec's ladder section gains a step. M4 completes `youtube_meetings.py` with `sync_city` and its helpers, registers the task in `tasks.py`, `scheduler.py`, and `health.py`, writes `scripts/backfill_youtube_meetings.py`, and adds the runbook row. M5 edits the meeting page, the provenance sentence, `city_provenance` and its two templates, and the Source health page, then the operator deploys and runs the backfill. M6 edits `transcriber/transcriber/audio.py`, `db.py`, `cli.py`, `requirements.txt`, and `src/docket/services/transcripts.py`. M7 graduates decisions and closes the plan.

## Milestones

### M1: the API client and the title parser

At the end of this milestone the repository can turn a channel listing into candidates without a network. `docket.adapters.youtube.YouTubeClient(api_key, get=requests.get)` has `uploads_playlist_id(handle) -> str`, `list_uploads(playlist_id, *, published_after: datetime | None) -> list[YouTubeVideo]` (pages until the playlist ends or every item of a whole page is older than `published_after`; the playlist is newest-first but a stream's `videoPublishedAt` can sit a little out of order, so one old item never stops the walk, and items older than the cutoff are dropped from the result), and `fill_details(videos) -> list[YouTubeVideo]` (batches of 50 through `videos.list`). `YouTubeVideo` is a frozen dataclass: `video_id, title, published_at: datetime, duration_s: int | None, started_at: datetime | None, broadcast: str` (`none`, `live`, `upcoming`). `parse_iso_duration("PT3H10M6S") -> 11406`. A `quotaExceeded` answer raises `QuotaExceeded(RuntimeError)`; any other non-200 raises `YouTubeAPIError` with the status and the error reason.

`docket.services.youtube_meetings.parse_title(title) -> ParsedTitle | None` returns `ParsedTitle(meeting_date: date, clean_title: str, part: int | None)` or `None` for a non-candidate. The date token is `M.D.YY` or `M.D.YYYY`, also with `/` separators and a leading zero on the day (`8.03.26`), anywhere in the title; a two-digit year is `20YY`; a date before 2008-01-01 or after tomorrow returns `None`. After removing the token, the title must contain `meeting`, `committee`, `council`, or `hearing` (case-insensitive) and must not contain `highlights`, `recap`, `tease`, `test`, or `edition`. The clean title is the remainder with any `Pt. N`, `Pt N`, or `Part N` removed (the N kept as `part`), leading and trailing punctuation and dashes stripped, whitespace collapsed, and `&` kept. `body_key(clean_title) -> str` lower-cases, replaces `&` with `and`, removes the words `special called` and `joint`, and keeps letters only. `group_videos(videos) -> list[Candidate]` keeps videos whose `parse_title` is not `None`, whose `broadcast` is `none`, and whose `duration_s` is at least 300, groups them by `(meeting_date, body_key)`, and returns one `Candidate(meeting_date, clean_title, classification, primary: YouTubeVideo, others: list[YouTubeVideo])` per group with the longest video as `primary` and the rest sorted by `part` then duration. `classification` is `classify_title(clean_title)`.

Tests, in `tests/unit/test_youtube_titles.py`, cover every shape in the Artifacts inventory: `Committee of the Whole Meeting 9.30.26` → 2026-09-30, `Committee of the Whole Meeting`; `10.13.26 Public Safety Committee meeting` → 2026-10-13, `Public Safety Committee meeting`; `Community Development Committee Meeting 8.03.26` → 2026-08-03; `Arts and Parks Committee Meeting 8.17.26 Pt. 1` → part 1; `Birmingham City Council Meeting Part 2 12.23.24` → part 2; `Committee of the Whole/Administration & Governmental Affairs Committee Meeting 3.12.26` → the clean title with the slash and ampersand intact and `classify_title` giving `committee`; `Budget & Finance Committee Meeting 6.22.26` and `Budget and Finance Committee Meeting 6.8.26` sharing a `body_key`; `Council Highlights: September 29 Edition`, `SYSTEM TEST`, `Test Stream`, `Birmingham City Council Week Ahead Tease: 11/7 - 11/11`, and `D7 WENONAH PARADE 2025` → `None`. A grouping test feeds the seven `Birmingham City Council Meeting 10.13.26` streams (six under 300 seconds, one of 1,800) and expects one candidate with the 1,800-second video as primary and no others; another feeds `Public Safety Committee Meeting 2.10.26 Pt. 1` (300 s) and `Pt. 2` (1,800 s) and expects primary Pt. 2 with Pt. 1 in `others`. `tests/unit/test_youtube_adapter.py` drives the client with a fake `get` returning canned JSON pages and asserts paging continues past a page that mixes new and old items and stops after the first page whose items are all older than `published_after`, that `fill_details` batches 50 ids per call, that `PT3H10M6S` becomes 11406, and that a 403 `quotaExceeded` body raises `QuotaExceeded`.

Acceptance: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_youtube_titles.py tests/unit/test_youtube_adapter.py -q -p no:cacheprovider` fails before the code exists and passes after; `./tools/verify` passes.

### M2: the schema, and Granicus learns its clips' durations

Migration `040_youtube_recordings.py` (registered in `runner.MIGRATIONS` after 038, or after 039 if it exists by then) does four things in `SQL_UP` and undoes them in `SQL_DOWN`. It creates `meeting_videos (id SERIAL PRIMARY KEY, meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE, provider TEXT NOT NULL, video_id TEXT NOT NULL, url TEXT NOT NULL, title TEXT NOT NULL, clean_title TEXT NOT NULL, duration_s INTEGER NULL, started_at TIMESTAMPTZ NULL, is_primary BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (provider, video_id))` with `CHECK (provider IN ('youtube'))`, an index on `(meeting_id)`, and a partial unique index on `(meeting_id, provider) WHERE is_primary`. It adds `meetings.duration_s INTEGER NULL`. It drops and re-adds `meetings_type_source_check` as `CHECK (type_source IN ('title', 'calendar', 'schedule_rule', 'admin', 'video'))`. It writes `{"youtube_channel": "citycouncilbham", "youtube_channel_id": "UCxKV8MgjDbqw9PMGTsF_NUw"}` into Birmingham's `municipalities.metadata` with `||`, and the down removes the two keys, the constraint value, the column, and the table.

`RawMeeting` gains `duration_s: int | None = None` at the end of its fields so every adapter still constructs. `GranicusAdapter._parse_archive_row` reads the cell `row.find("td", headers="Duration")` into seconds through a new module-level `parse_duration_cell(text) -> int | None`. Every one of the 1,027 cells on the live page reads `01h 27m` with a non-breaking space (`&nbsp;`, `\xa0` after `get_text`) between the tokens, so the parser normalises whitespace first and then accepts any of the hour, minute, and second tokens independently (`(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?`), returning `None` for an empty cell or one with no token; upcoming rows keep `None`. `_upsert_meetings` writes `duration_s` on INSERT and `duration_s = COALESCE(%s, duration_s)` on UPDATE and in `_try_upgrade_event_row`. `Meeting` gains `duration_s: int | None = None` read by `from_row`. Because `list_meetings` parses the whole publisher page every morning, the first `ingest_all` after deploy fills `duration_s` for every Birmingham clip, which M5's backfill relies on.

Tests: `tests/integration/test_040_migration.py` follows `test_038_migration.py` (apply, roll back 40, assert the table and column are gone and the constraint rejects `video`; apply, assert they exist, the constraint accepts `video`, and Birmingham's metadata carries both keys). `tests/unit/test_granicus_adapter.py` gains a case that parses `ARCHIVE_ROW_HTML` (its Duration cell reads `01h 27m`) and asserts `duration_s == 5220`, one that an upcoming row yields `None`, and direct `parse_duration_cell` cases: `"01h\xa027m"` → 5220, `"43m"` → 2580, `"01h 27m 12s"` → 5232, `"45s"` → 45, `""` → `None`, `"Video"` → `None`. `tests/integration/test_ingest_meeting_types.py` gains a case that upserts a `RawMeeting` with `duration_s=1500` and reads it back, then upserts the same id with `duration_s=None` and reads 1500 still.

Acceptance: `tools/test-db` prints `Applying migration 40`; the three test files pass; `./tools/verify` passes.

### M3: the ladder names a row from its YouTube recording

`_MEETING_ROWS_SQL` gains the column `(SELECT array_agg(v.clean_title ORDER BY v.is_primary DESC, v.id) FROM meeting_videos v WHERE v.meeting_id = m.id AND v.provider = 'youtube') AS video_titles`. `resolve` gains the keyword argument `video_titles: list[str] | None = None`, and `_changes` passes `m.get("video_titles")`. The rung sits between the specific-title rung and the calendar rung: for a row whose own title is generic, the first `video_titles` entry whose `classify_title` is not `_GENERIC` decides, with `type_source = "video"` and `calendar_event_id = None`. A row whose own title is specific is unchanged by this milestone (the title rung already won), and a locked row is still `None`. `TYPE_SOURCES` becomes `("title", "video", "calendar", "schedule_rule", "admin")`. The docstring ladder at the top of the module and `docs/specs/meeting-types.md` "The ladder" gain the step between 2 and 3: "**Video.** For a generic title, a YouTube recording attached to the row (`meeting_videos`) whose cleaned title names a body is final; the council's own name for its stream outranks the calendar and the rule."

Tests in `tests/unit/test_meeting_types.py` (the file exists; add a class): a generic-titled Tuesday row with `video_titles=["Budget and Finance Committee Meeting"]` resolves to `committee`, `regular`, `Budget and Finance Committee`, source `video`; the same row with `video_titles=["Birmingham City Council Meeting"]` falls through to the title rung as before; a specific-titled row ("Budget Hearing") with a committee video title keeps `title`; a locked row returns `None`; a row with `video_titles=None` behaves exactly as today (the whole existing class still passes).

Acceptance: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_meeting_types.py -q -p no:cacheprovider` passes with the new cases; `./tools/verify` passes.

### M4: the matching ladder, the daily task, and the backfill script

`youtube_meetings.sync_city(slug, *, client: YouTubeClient, since: date | None, today: date, dry_run: bool) -> SyncReport` is the one entry point for the task and the script. It loads the city (`id`, `metadata`), returns an empty report with a WARNING when the metadata has no `youtube_channel_id` or the environment has no `YOUTUBE_API_KEY` (the task reads `config.YOUTUBE_API_KEY`, a new `os.environ.get` in `src/docket/config.py`), lists uploads with `published_after = today - 30 days` when `since` is `None` and the whole playlist otherwise, fills details, groups, and then for each group on each date decides as follows against `SELECT id, external_id, title, meeting_type, body_name, minutes_url, duration_s, is_hidden, (SELECT count(*) FROM agenda_items a WHERE a.meeting_id = m.id) AS item_count FROM meetings m WHERE municipality_id = %s AND meeting_date = %s`.

A group whose primary `video_id` already exists in `meeting_videos` is skipped (`skip_seen`). The duration a group brings to every comparison is `Candidate.total_duration_s`, the sum over the primary and the parts: Granicus records one continuous clip where the council's stream broke into Pt. 1 and Pt. 2. A council group (its classification's `meeting_type` is `council`) attaches to the day's council row; among several council rows, the one whose `duration_s` pairs, else the one with the most agenda items, logged at INFO. A committee group (any other `meeting_type`) with exactly one Granicus candidate row and exactly one committee group that day attaches to it. With several on either side, pairs are made by duration (`pairs(a, b)` is true when `abs(a - b) <= max(300, 0.25 * max(a, b))`, both non-`None`), nearest difference first, each row once; paired groups attach, unpaired groups create, and the date goes into `report.ambiguous_days` with a WARNING naming the unpaired clip ids. A group with no match creates when `primary.published_at <= today - 3 days` and otherwise is `deferred`. One guard sits before any create: when any Granicus candidate row on that date has `duration_s IS NULL`, nothing can be paired, so the group is recorded as `no_duration` and not created; the backfill prints the count with the line "run ingest_all first so Granicus durations are stored", which is what protects the historical backfill from creating a `yt-` twin for every committee clip Granicus already holds. Attach inserts one `meeting_videos` row per video in the group (primary flagged) with `url = https://www.youtube.com/watch?v=<id>`. Create inserts the meeting row with `external_id = yt-<primary id>`, `title = clean_title`, the classification from `classify_title(clean_title)` and `type_source = 'title'`, `video_url` and `source_url` both the watch URL, `duration_s = primary.duration_s`, `start_time` from `started_at` in America/Chicago when present, then the `meeting_videos` rows. Hidden rows take part in matching (an attach to a hidden row is still an attach) and are never un-hidden.

After the groups, absorption: every `yt-` row of the city dated within the last 30 days (never the 2023 rows, never a row with agenda items) whose date has an unmatched Granicus candidate row that pairs by duration with the `yt-` row's `duration_s`, or is the day's only candidate, has its `meeting_videos` rows re-pointed to the candidate and is then deleted when no `transcripts` row references it and hidden (`is_hidden = TRUE`) when one does, logged at WARNING with both ids. The delete is safe: every foreign key that points at `meetings(id)` (`agenda_items`, `votes`, `processing_status` in migration 001; `transcripts`, `transcript_speakers`, `minutes_texts`, `minutes_discrepancies`, `meeting_events` in 035; `meeting_videos` in 040) is `ON DELETE CASCADE`, verified on 2026-10-24, and a `yt-` row young enough to absorb has no items, no votes, and no minutes. Finally `meeting_types.resolve_and_store(municipality_id, touched_ids)` runs over every row attached, created, or absorbed into, so the `video` rung names them the same run. On `dry_run` every decision is recorded in the report and nothing is written; the report's `decisions` is a list of `(meeting_date, action, detail)` with actions `attach`, `create`, `defer`, `no_duration`, `skip_seen`, `absorb`, `ambiguous`, and the report carries counts per action.

The task `youtube_ingest` in `tasks.py` is `_safe_run("youtube_ingest", _do_youtube_ingest)`, where `_do_youtube_ingest` builds a client from `config.YOUTUBE_API_KEY` and calls `sync_city` for every active city whose metadata has `youtube_channel_id` (Birmingham only at first), logging the counts; a `QuotaExceeded` is logged and ends the city, not the task. `health.py` maps it to `HEALTHCHECK_YOUTUBE_INGEST_UUID`; `scheduler.py` adds it at 06:45 America/Chicago with the same `coalesce` and `max_instances` as the others and a comment naming this plan; `docs/runbooks/cron-worker.md` gains the row `youtube_ingest | Daily 06:45 | HEALTHCHECK_YOUTUBE_INGEST_UUID (optional) | Reads the council's YouTube uploads of the last 30 days; attaches recordings to Granicus rows or creates yt- rows after 3 days; Birmingham only at first`.

`scripts/backfill_youtube_meetings.py --city birmingham [--dry-run] [--since YYYY-MM-DD]` follows `scripts/reclassify_meetings.py` in shape: it builds the client from the environment, calls `sync_city(slug, client=client, since=args.since or date(2008, 1, 1), today=date.today(), dry_run=args.dry_run)`, prints one line per decision ordered by date, then the ambiguous days, then the counts, and exits 1 when the key is missing.

Tests in `tests/integration/test_youtube_sync.py` use `seeded_birmingham` and a fake client whose `list_uploads` returns fixed `YouTubeVideo`s. Cases, each asserting the report and the rows: a committee video dated to a day with one body-less committee clip of 1,500 seconds and a 1,380-second video attaches and the clip's `body_name` reads `Budget and Finance Committee` with `type_source = 'video'` after the run; a council video attaches to the council row and the row's classification is unchanged; a Committee of the Whole video dated to a day with no rows and published 10 days ago creates `yt-<id>` with `meeting_type = 'committee'` and `body_name = 'Committee of the Whole'`; the same published yesterday is deferred and no row exists; a second run of the same listing changes no row counts; a day with two body-less clips (360 s and 1,500 s) and one 1,380-second video attaches to the 1,500-second clip and lists the day as ambiguous; a day with one zero-item council-typed clip beside a council row with items and a committee video attaches to the zero-item clip, which then reads `committee`; the 2026-10-13 shape, a council row with items, one zero-item council-typed clip of 300 seconds, and two committee videos of 2,220 and 1,320 seconds, creates two `yt-` rows (neither pairs: 1,020 and 2,220 seconds apart against a 330- and 555-second allowance), leaves the clip alone, and lists the day as ambiguous; a two-part committee group (300 and 1,800 seconds) against a 2,100-second clip attaches, because the group's total is compared; a committee video on a day whose only candidate clip has `duration_s IS NULL` is `no_duration` and creates nothing; a `yt-` row created 5 days ago with no items on a day that now has one body-less clip of matching duration is absorbed (its video now on the clip, the `yt-` row gone); a `yt-` row with a `transcripts` row is hidden instead; `dry_run=True` writes nothing. A unit test in `tests/unit/test_worker_tasks.py` (or the file that already tests `city_calendar`'s task) asserts `TASKS["youtube_ingest"]` exists and that `_do_youtube_ingest` logs and returns when `YOUTUBE_API_KEY` is unset.

Acceptance: the two test files pass; `venv/bin/python -m docket.worker.scheduler --run-once youtube_ingest` against the local database with no key prints the WARNING and exits 0; `./tools/verify` passes.

### M5: the site shows the recording and the provenance, and the operator runs it on production

`query.py` gains `videos_for_meeting(meeting_id) -> list[dict]` (`provider, video_id, url, title, duration_s, is_primary`, primary first), and `meeting_detail` in `src/docket/web/public.py` passes it to the template as `recordings`. The meeting page's links rail prints, when `recordings` has a YouTube entry and `meeting.video_url` does not contain `youtube.com`, a second rail link "Watch on YouTube" with the meta "council channel", and when `recordings` has more than one entry, a line under the video links listing the others as "Part N" links (or "another recording" when no part number). The provenance paragraph gains `{% elif meeting.type_source == 'video' %} The council's YouTube recording names it.` with a link to the primary recording's `url`.

`briefing.city_provenance` keeps its keys and adds `source_hosts: list[dict]`, one `{"host", "source_url", "rows"}` per distinct hostname of `source_url` over the city's non-hidden rows with `meeting_date >= current_date - 180`, most rows first, where `source_url` is the newest such row's for that host; `source_host` stays the first host so nothing else changes. `partials/footer.html` prints the hosts joined by " and ", and `partials/page_sources.html` prints "The records on this page come from bhamal.granicus.com and www.youtube.com." when there are two, each host linked to its `source_url`. The Source health page (`public.source_health`) prints the same list. `docs/specs/meeting-types.md` "Provenance" gains the video sentence; `docs/specs/city-page.md` notes the footer lists every source host of the last 180 days.

Tests in `tests/web/` (the pattern of the existing meeting-page tests): a meeting with a Granicus `video_url` and one YouTube `meeting_videos` row renders both rail links; a `yt-` meeting renders one; a row with `type_source = 'video'` prints "The council's YouTube recording names it."; a city whose rows carry two hosts prints both in the footer.

Operator steps, recorded in Progress with observed output: in the Google Cloud console enable "YouTube Data API v3" on a project and create an API key restricted to that API; set `YOUTUBE_API_KEY` on the Railway worker service (and `HEALTHCHECK_YOUTUBE_INGEST_UUID` when convenient); deploy; wait for the next `ingest_all` or run it once so `duration_s` is filled (`SELECT count(*) FROM meetings WHERE municipality_id = <bhm> AND external_id ~ '^[0-9]+$' AND duration_s IS NULL` should be near 0); run `DATABASE_URL=$DATABASE_PUBLIC_URL YOUTUBE_API_KEY=... venv/bin/python scripts/backfill_youtube_meetings.py --city birmingham --dry-run > /tmp/yt-dry.txt`, read the ambiguous days and the create count (expected: on the order of 800 creates across all years, under 80 for 2026, and attaches for every council meeting since 2015), then run it without `--dry-run`, then run the dry run again and observe zero creates and zero attaches. Then check the three pages the Purpose names.

Acceptance: the web tests pass; `./tools/verify` passes; the production counts and the dry-run-after-write transcript are in Progress and Artifacts.

### M6: the transcriber reads YouTube recordings

`transcriber/requirements.txt` gains `yt-dlp>=2025.1`. `audio.py` gains `source_for(external_id, work_dir: Path) -> str`: a numeric id returns `download_url_for(external_id)` unchanged; a `yt-` id downloads the best audio track of `https://www.youtube.com/watch?v=<id>` with `yt_dlp.YoutubeDL({"format": "bestaudio/best", "outtmpl": str(work_dir / f"{external_id}.%(ext)s"), "quiet": True, "noplaylist": True})`, adding `"cookiefile": os.environ["TRANSCRIBER_YTDLP_COOKIES"]` when that variable is set (a Netscape-format cookie file the operator exports from a signed-in browser, mounted into the container; the escape hatch if YouTube ever asks the home address to sign in), and returns the downloaded file's path, raising `AudioFetchError` on any `yt_dlp.utils.DownloadError`. `cli.py` replaces each `download_url_for(x)` with `source_for(x, cfg.work_dir)` (three sites: `process_claim`, `cache_audio`, `capture_inputs`) and, in the same `finally` that removes the wav, removes every `work_dir.glob(f"{external_id}.*")` file, since yt-dlp chooses the extension (`.m4a`, `.webm`, `.opus`). `transcriber/README.md` documents the variable and when to set it. `db.py` changes the three filters from `m.external_id ~ '^[0-9]+$'` to `(m.external_id ~ '^[0-9]+$' OR m.external_id LIKE 'yt-%')`, and `meeting_source`'s docstring says "clip id or yt- id". `src/docket/services/transcripts.py` `list_transcript_debt` widens the same way. `video_ocr.py` is not touched. `transcriber/README.md` names yt-dlp and that a rebuild is needed.

Tests: `transcriber/tests/test_audio.py` gains a case that `source_for("2024", tmp_path)` returns the Granicus URL, a case that `source_for("yt-abc", tmp_path)` with a monkeypatched `YoutubeDL` whose `download` writes `yt-abc.webm` returns that path and raises `AudioFetchError` when `download` raises `DownloadError`, and a case that the options carry `cookiefile` only when `TRANSCRIBER_YTDLP_COOKIES` is set. `transcriber/tests/test_db.py` gains a `yt-` meeting that `claim_next` returns and a `event-` meeting it does not. A unit test for `list_transcript_debt` (where its existing test lives) adds a `yt-` row older than 14 days with no transcript and expects it listed.

Operator steps: `docker compose build` on the transcriber machine, run the loop once, and observe the Committee of the Whole of 2026-09-30 (meeting id from the backfill output) move through `claimed`, `audio_fetched`, `transcribed`, `uploaded`; the next morning's `transcript_pipeline` publishes it and the meeting page offers the Transcript link.

Acceptance: `./tools/verify` passes (its `transcriber` check runs `transcriber/tests`); the transcript is visible on the site and the observation is in Progress.

### M7: the close

Graduate to `docs/decisions/` (next numbers after 0066, format in `DECISION_FORMAT.md`): the ladder's `video` rung, duration as the pairing key, the 3-day wait and absorption, and YouTube as a second source for Birmingham. Make `docs/specs/meeting-types.md`, `docs/specs/operations.md` (the task), and `docs/specs/transcripts.md` (eligibility) read in the present tense. Add to `docs/DEBT.md` the two follow-ups the operator named: agenda items or a meaningful title derived for YouTube-only rows, and the captions idea explicitly declined. Write `Outcomes & Retrospective`, move this file to `plans/completed/`, and run `./tools/verify`.

## Concrete Steps

Every command runs from `/home/thinkdarrell/docket-pub` (or the worktree `.claude/worktrees/youtube-council-channel` when the factory runs a milestone) with the repository's `venv/`. The test database comes from `tools/test-db`; never point a test tier at `docket_db` or at production.

Baseline before any edit, to record in Progress:

    ./tools/verify

Expect the summary `verify: all 7 checks passed` (the count the tool prints on main at the time; record what it prints). The unit tier runs with `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit -q -p no:cacheprovider`; the integration tier with `tests/integration`; the web tier with `tests/web`.

M1: write the two test files, run `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_youtube_titles.py tests/unit/test_youtube_adapter.py -q -p no:cacheprovider` and record the failure (`ModuleNotFoundError: docket.adapters.youtube`), write the modules, re-run and record `N passed`, commit with the plan file.

M2: write `tests/integration/test_040_migration.py` and the adapter and ingest cases, run them and record the failures, write the migration (and its line in `runner.MIGRATIONS`), the dataclass field, the parser, the writes, re-run, then `tools/test-db --drop && tools/test-db` and record `Applying migration 40: docket.migrations.040_youtube_recordings`.

M3: add the cases to `tests/unit/test_meeting_types.py`, record the failure, edit `meeting_types.py` and the spec, record the pass.

M4: write `tests/integration/test_youtube_sync.py`, record the failures, write `sync_city` and the task, the scheduler and health entries, the script, the runbook row; run `venv/bin/python -m docket.worker.scheduler --run-once youtube_ingest` with `YOUTUBE_API_KEY` unset and record the WARNING line; run the script with `--dry-run` against the local database with a real key once if one is at hand (optional; the local database is a stale copy) and keep the output in Artifacts.

M5: write the web tests, record the failures, edit the templates and `briefing.py` and `query.py` and `public.py`, record the pass; then the operator steps listed in the milestone, each with its observed output pasted into Progress.

M6: write the transcriber tests, record the failures, edit the four transcriber files and `transcripts.py`, run `./tools/verify`, then the operator rebuilds and runs, and the observed status transitions go into Progress.

M7: the edits listed, then `./tools/verify`, then `git mv plans/active/youtube-council-channel.md plans/completed/`.

## Validation and Acceptance

The plan is done when, on production, https://docket.pub/al/birmingham/meetings/?type=committee lists "Committee of the Whole" on Sep 30, 2026 with a page that offers the YouTube video and a transcript; https://docket.pub/al/birmingham/meetings/ shows no 2026 date with two rows of the same body; the Sep 28, 2026 committee row reads "Budget and Finance Committee" and its provenance line says the council's YouTube recording names it; the Oct 13, 2026 list shows one City Council meeting and two named committee meetings; the Birmingham footer names both hosts; the worker log shows `youtube_ingest` completing daily with counts; and a dry run of the backfill after the write reports zero creates and zero attaches. Each milestone's own acceptance is in its section; every one ends with `./tools/verify` passing and its summary line recorded.

## Idempotence and Recovery

The migration uses `IF NOT EXISTS` and `DROP ... IF EXISTS` throughout and has a full `SQL_DOWN`; `tools/test-db` rebuilds a disposable database at any time. `sync_city` skips any video already in `meeting_videos` and never updates a `yt-` row, so the backfill and the task can run any number of times; the only writes that are not pure inserts are absorption (logged with both ids, the moved `meeting_videos` rows keep their video ids, and a hidden `yt-` row can be un-hidden in admin) and the resolver's classification write, which is the same idempotent ladder ingest already runs. The production backfill is always a dry run first, with its output kept, and the dry run after the write must print zero creates and zero attaches. Should the backfill need undoing, `DELETE FROM meetings WHERE municipality_id = <bhm> AND external_id LIKE 'yt-%' AND meeting_date >= '2024-01-01'` and `DELETE FROM meeting_videos` return the database to its pre-backfill shape (the 2023 Boutwell rows are older than that date and untouched), subject to decision 0026's rule that the operator runs such statements with a narrow `WHERE` and records them. A missing or exhausted API key ends the task without error and without writes.

## Artifacts and Notes

The streams listing captured on 2026-10-24 with `yt-dlp --flat-playlist --print "%(id)s|%(duration)s|%(title)s" https://www.youtube.com/@citycouncilbham/streams`, 2026 meeting titles with minutes, used as the inventory for M1's tests (the full file is `/tmp/claude-1000/-mnt-c-Users-darre/8a869beb-3bdd-45bb-bf41-e8464be3e03f/scratchpad/yt_streams.txt` on the authoring machine; M1 copies the lines it needs into its test file):

      190 | 6Cocqqq95Ew | Committee of the Whole Meeting 9.30.26
       81 | pUGb-d8PnY8 | Committee of the Whole Meeting 2.18.26
      120 | 0BoYE1yTf98 | Committee of the Whole/Administration & Governmental Affairs Committee Meeting 3.12.26
       23 | gjvBCa3zcnU | Budget and Finance Committee Meeting 9.28.26
       38 | 4MFuTy0q9WI | Budget & Finance Committee Meeting 6.22.26
       13 | r_fVFTdoG1g | Community Development Committee Meeting 10.5.26
       18 | aLPZ9Rws1rg | Community Development Committee Meeting 8.03.26
       37 | rJ6PPd2MDTE | 10.13.26 Public Safety Committee meeting
       22 | pRNunlGGr5A | Planning and Zoning Committee Meeting 10.13.26
        0 | _9DmYeCsKlw | Planning and Zoning Committee Meeting 4.14.26 Pt. 1
       31 | yfn1ox-fCmo | Planning and Zoning Committee Meeting 4.14.26 Pt. 2
        5 | clN1E49-fyg | Public Safety Committee Meeting 2.10.26 Pt. 1
       30 | 2Gni3U6ODyM | Public Safety Committee Meeting 2.10.26 Pt. 2
       11 | q4YEdeTsFPY | Special Called Community Development Committee Meeting 9.8.26 Pt. 1
        3 | 8VXMCjFstkg | Arts and Parks Committee Meeting 8.17.26 Pt. 1
       28 | NriKn6URliE | Arts and Parks Committee Meeting 8.17.26 Pt. 2
        0 | 75hCkY1R9JU | Birmingham City Council Meeting 10.13.26
        2 | _sWVd6g4R0o | Birmingham City Council Meeting 10.13.26
       30 | ara-4Ve6XCU | Birmingham City Council Meeting 10.13.26
       52 | Z8fZqUME4LU | Birmingham City Council Meeting 9.29.26
      105 | uvqFjIfPLLU | Birmingham City Council Meeting 10.20.26

Non-meeting titles from the videos tab, for the rejection cases: `Council Highlights: September 29 Edition`, `SYSTEM TEST`, `Test Stream`, `Birmingham City Council Week Ahead Tease: 11/7 - 11/11`, `D7 WENONAH PARADE  2025`, `Your City Budget, Simplified`, `Administration and Governmental Affairs Meeting 1.9.24` (a candidate: `other` by `classify_title`, which is acceptable; it is created as `other` if nothing matches).

Granicus 2026 clips that are not on a Tuesday, from view 2 on 2026-10-24, the rows M4's pairing meets on production: 2026-10-15 Thu 00h 04m and 00h 05m; 2026-10-05 Mon 00h 06m; 2026-09-28 Mon 00h 06m and 00h 25m; 2026-08-03 Mon 00h 21m; 2026-06-03 Wed Budget Hearing 00h 53m. The council Tuesday 2026-10-13 has two Granicus clips (2017 with items, 2018 without) and two YouTube committee streams (Public Safety 37 minutes, Planning and Zoning 22 minutes).

## Interfaces and Dependencies

No new dependency for the web or worker image: the Data API is called with `requests`, already required. The transcriber gains `yt-dlp` (M6). `YOUTUBE_API_KEY` is a new environment variable read in `src/docket/config.py` as `YOUTUBE_API_KEY: str | None = os.environ.get("YOUTUBE_API_KEY")`.

In `src/docket/adapters/youtube.py`:

    @dataclass(frozen=True)
    class YouTubeVideo:
        video_id: str
        title: str
        published_at: datetime          # timezone-aware UTC
        duration_s: int | None = None
        started_at: datetime | None = None
        broadcast: str = "none"         # 'none' | 'live' | 'upcoming'

    class YouTubeAPIError(RuntimeError): ...
    class QuotaExceeded(YouTubeAPIError): ...

    def parse_iso_duration(text: str) -> int | None: ...

    class YouTubeClient:
        def __init__(self, api_key: str, *, get=requests.get, delay: float = 0.0): ...
        def uploads_playlist_id(self, handle: str) -> str: ...
        def list_uploads(self, playlist_id: str, *, published_after: datetime | None = None) -> list[YouTubeVideo]: ...
        def fill_details(self, videos: list[YouTubeVideo]) -> list[YouTubeVideo]: ...

In `src/docket/services/youtube_meetings.py`:

    @dataclass(frozen=True)
    class ParsedTitle:
        meeting_date: date
        clean_title: str
        part: int | None

    @dataclass(frozen=True)
    class Candidate:
        meeting_date: date
        clean_title: str
        classification: Classification      # docket.adapters._helpers.Classification
        primary: YouTubeVideo
        others: list[YouTubeVideo]

        @property
        def total_duration_s(self) -> int | None: ...   # sum over primary and others; None when any is None

    @dataclass
    class SyncReport:
        decisions: list[tuple[date, str, str]]
        ambiguous_days: list[date]
        counts: dict[str, int]              # attach, create, defer, no_duration, skip_seen, absorb, ambiguous
        touched_ids: list[int]

    MIN_RECORDING_S = 300
    CREATE_AFTER_DAYS = 3
    DAILY_WINDOW_DAYS = 30

    def parse_title(title: str) -> ParsedTitle | None: ...
    def clean_title(title: str) -> str: ...
    def body_key(clean: str) -> str: ...
    def pairs(a: int | None, b: int | None) -> bool: ...
    def group_videos(videos: list[YouTubeVideo]) -> list[Candidate]: ...
    def sync_city(slug: str, *, client: YouTubeClient, since: date | None, today: date, dry_run: bool = False) -> SyncReport: ...

In `src/docket/models/protocol.py`, `RawMeeting` ends with `duration_s: int | None = None`. In `src/docket/adapters/granicus.py`, module-level `parse_duration_cell(text: str) -> int | None`. In `src/docket/services/meeting_types.py`, `resolve(municipality, meeting, *, calendar_events, item_count, video_titles=None)` and `TYPE_SOURCES = ("title", "video", "calendar", "schedule_rule", "admin")`. In `src/docket/services/query.py`, `videos_for_meeting(meeting_id: int) -> list[dict]`. In `src/docket/services/briefing.py`, `city_provenance` returns the existing keys plus `source_hosts: list[dict]` of `{"host", "source_url", "rows"}`. In `src/docket/worker/tasks.py`, `TASKS["youtube_ingest"]`. In `transcriber/transcriber/audio.py`, `source_for(external_id: str, work_dir: Path) -> str`.

The `meeting_videos` table, as M2 creates it, is the one place a recording that is not the row's `video_url` lives; the site, the ladder, and the transcriber all read it by `meeting_id` and never by position.

## Revision notes

2026-10-24: authored from the approved design (the design document lived on the authoring machine; everything it decided is restated above, so this plan stands alone).

2026-10-24, later: the operator's external review led to five changes, recorded in the Decision Log's last entry: whole-page paging termination (M1), a tolerant duration parser with the `\xa0` fact and its test cases (M2), group-total pairing, the `no_duration` guard, the 2026-10-13 and two-part test cases, and the foreign-key cascade check behind absorption (M4), and the optional cookie file plus the glob cleanup in the transcriber (M6).
