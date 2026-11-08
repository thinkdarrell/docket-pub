# 2. How a meeting enters the database

The daily ingest turns what chapter 1's sources publish into rows in `meetings`, `agenda_items`, `votes`, and `member_votes`. One service owns the whole transaction: `ingest_municipality("birmingham")` in `src/docket/services/ingest.py`, called by the worker task `ingest_all` (`src/docket/worker/tasks.py`) and runnable by hand. This chapter follows one meeting through it.

## The order of the morning

The worker (`src/docket/worker/scheduler.py` owns the times; this page does not repeat them) runs the ingest-side tasks each morning, Chicago time, in this order: `city_calendar` (refresh the council page's events), then `ingest_all` (Granicus), then `youtube_ingest` (the channel). Once a week, before them, `repair_empty_agendas` clears the "scraped" flag on recent meetings that have an agenda link but zero items, so they are tried again. Every task pings its Healthchecks.io check at start, success, and failure (`src/docket/worker/health.py`; `docs/runbooks/cron-worker.md` lists the checks).

## Step 1: the meeting row

For each meeting the Granicus publisher page lists, ingest looks for a row by `(municipality_id, external_id)`.

- **Found.** The row is updated: title, date, agenda, minutes, video, and source URLs are always rewritten from the feed; `start_time` and `duration_s` keep a stored value if the feed has none. The five classification columns are rewritten from the title only while the row is still title-classified and not locked by an admin (`_CLASSIFICATION_GATE`), so a body name the calendar, a YouTube title, or an admin placed survives the daily refresh.
- **Not found, and the id is a clip id.** Before inserting, ingest tries to **upgrade an `event-` row in place**: the upcoming-meeting row created weeks earlier is renamed to the clip id, keeping its agenda items, if exactly one `event-` row on that date matches by title, or failing that, if exactly one exists that day. When that is ambiguous, a new row is inserted instead; a duplicate meeting is recoverable, a wrong merge is not.
- **Not found otherwise.** A new row is inserted, classified from its title, `type_source = 'title'`.

A `processing_status` row per meeting carries two gates, `agenda_items_scraped` and `votes_scanned`, so each later step runs once per meeting and a re-run of ingest is cheap.

## Step 2: agenda items

For a meeting not yet scraped:

- A **clip** meeting's items are the player page's index points. Each becomes an `agenda_items` row whose `external_id` is the chapter id, `item_number` its position, `video_timestamp_seconds` the point's time, and `is_consent` from the title's consent markers.
- An **event** meeting's items come from the agenda PDF, text-extracted and parsed. Their ids are `event-<id>-<item_number>`. When any items were found, one extra un-numbered item, `event-<id>-minutes-approval`, is added so that the adoption sweep (step 4) has something to find.

Inserts use `ON CONFLICT DO NOTHING` on `(meeting_id, external_id)`, so items are never duplicated. An empty scrape still marks the meeting scraped; the weekly repair task is what gives it another chance.

Every new item is **enriched inline** (`src/docket/services/enrichment.py`): the dollar amount and its display tier, the sponsor, a cleaned title, a keyword topic, and the two AI scores set to their not-yet-processed state. Chapter 3 describes these columns.

For a clip meeting that was already scraped (because it began life as an `event-` row from the PDF), ingest instead **backfills video timestamps**: it matches index points to the PDF-born items by the `ITEM N` number in their titles, fills `video_timestamp_seconds` where NULL, and rewrites `external_id` to the chapter id. This is what lets a meeting whose agenda was read before the video existed still open its video at the right moment. The supervised repair of older rows is `scripts/correct_agenda_chapter_ids.py` (`docs/specs/video-links.md`, "Where a cue point comes from").

## Step 3: what kind of meeting this is

After the rows are written, `meeting_types.resolve_and_store` runs over every meeting the feed listed and climbs the **evidence ladder** for each one that an admin has not locked: a specific title wins outright ("Special Called Finance Committee"); for a generic title, an attached YouTube recording's cleaned title wins; then the day's calendar events; then the schedule rule (a generic clip on a day other than the council's Tuesday, with no minutes and not cancelled, is a committee recording); and otherwise the generic council reading stands. The winning rung is recorded in `type_source`, and the five columns are written in one statement. `docs/specs/meeting-types.md` owns every rule and the reader-facing label; the key point for the content flow is that **a reader never sees the clip's raw name as the meeting's name**, and a row moves back down the ladder on its own when it gains minutes or a cancelled title.

A cancelled meeting is detected from its title alone (`query.is_cancelled_title`); there is no flag column. It stays an ordinary row, labelled "(cancelled)", and the city-page prose about actions skips it (`0058`).

## Step 4: votes and the adoption sweep

For a clip meeting with a minutes link whose `votes_scanned` gate is open, the adapter fetches the minutes PDF and parses it into votes with each member's position; ingest writes `votes` and `member_votes`, resolving each stored member name to a `council_members` row at insert (chapter 3). `event-` rows are skipped; they have no minutes yet.

Then the **minutes adoption sweep** (`src/docket/services/minutes_adoption.py`): when a later meeting carries an agenda item whose title approves the minutes of an earlier date or date range, and that item has a passed vote, the earlier meeting's `minutes_adopted_at` is set. Adoption is the moment a meeting's minutes become official, and chapter 3 explains why it matters: a vote-to-item link made from unadopted minutes is provisional, and adoption promotes it. Dates are parsed from the item's title, never guessed (`0010`); when several rows share the adopted date, only those with minutes are flipped, and when none has minutes the sweep warns and skips.

## What ingest does not store

- **No PDFs.** Agenda and minutes PDFs are downloaded, parsed in memory, and discarded; the meeting row keeps the URLs. The minutes text is cached later, by the transcript pipeline, in `minutes_texts` (chapter 5).
- **No cancellations flag, no attendance table** of its own: attendance comes from the minutes parser (chapter 3).
- **No merges on doubt.** Every place ingest could merge two records (event-to-clip upgrade, YouTube-to-clip pairing) inserts or creates a new row when the match is not certain.

## Where to look

| Question | Owner |
| --- | --- |
| Exactly which URLs the adapter fetches and what each returns | `src/docket/adapters/granicus.py` |
| The upsert, the gates, the upgrade-in-place, the timestamp backfill | `src/docket/services/ingest.py` |
| The ladder, the label, the calendar, the YouTube pass | `docs/specs/meeting-types.md` |
| The adoption sweep | `src/docket/services/minutes_adoption.py`, decisions `0007`, `0010` |
| Task order and times | `src/docket/worker/scheduler.py`; `docs/runbooks/cron-worker.md` for operating it |

Next: [3. Votes, members, and the facts on an item](03-votes-and-facts.md).
