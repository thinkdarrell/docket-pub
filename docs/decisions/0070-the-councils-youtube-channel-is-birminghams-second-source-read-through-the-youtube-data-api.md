# 0070 — The council's YouTube channel is Birmingham's second source, read through the YouTube Data API with a key, and the site names every source host it draws on

## Decision

The web and worker images read the council's channel (`municipalities.metadata.youtube_channel_id`) only through the YouTube Data API v3 with `YOUTUBE_API_KEY` (`src/docket/adapters/youtube.py`, the daily task `youtube_ingest`, `scripts/backfill_youtube_meetings.py`); a recording that is not a row's `video_url` lives in `meeting_videos`. Only the transcriber, on the operator's home machine, downloads YouTube audio, with yt-dlp, and only for `yt-` rows. The footer, the sources paragraph, and the Source health page list every source host of the city's rows of the last 180 days (`briefing.city_provenance`'s `source_hosts`), not the newest row's host.

## Rationale

The alternative was yt-dlp everywhere, which needs no key. YouTube answers datacenter addresses such as Railway's with "sign in to confirm you're not a bot" when scraped, so the worker could not rely on it; the Data API lists a channel from anywhere, returns durations and stream start times in the same call, and the whole channel costs about 100 units of the 10,000-unit free daily quota. The transcriber has to fetch audio, which the API does not serve, and it runs from a home address YouTube does not challenge, with a cookie file (`TRANSCRIBER_YTDLP_COOKIES`) as the escape hatch.

A second source makes "the host of the newest row" wrong: it would flip the footer to www.youtube.com the first morning a YouTube row was newest and hide bhamal.granicus.com, which still holds most of the record. Listing every recent host is one query; a run-log table of sources was the other option and would be a second system for a fact the rows and the worker log already hold. Agenda items or captions derived from YouTube are not part of this decision (`docs/DEBT.md`).

## Date

2026-10-24, the operator (the API key, transcripts in scope) and Claude, in `plans/active/youtube-council-channel.md` (built in its M1, M4, M5, and M6; the file moves to `plans/completed/` when the plan closes).

## Status

accepted
