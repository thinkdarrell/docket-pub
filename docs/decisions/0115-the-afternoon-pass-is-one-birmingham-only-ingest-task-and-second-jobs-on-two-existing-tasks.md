# 0115 — The afternoon pass is one Birmingham-only ingest task and second jobs on two existing tasks

## Decision

The worker's afternoon pass is three scheduler jobs in `src/docket/worker/scheduler.py`. `ingest_afternoon` is a task of its own, with its own entry in `TASKS` and its own Healthchecks variable, `HEALTHCHECK_INGEST_AFTERNOON_UUID` (check `docket-ingest-afternoon`). `youtube_ingest_afternoon` and `non_meetings_afternoon` are second jobs that call the existing task functions `youtube_ingest` and `non_meetings` and ping those tasks' checks, each of which takes one cron expression naming both hours. Which cities the afternoon ingest visits is the setting `AFTERNOON_INGEST_SLUGS` in `src/docket/config.py`, a comma-separated list whose default is `birmingham`; the task visits each named city that is also active (`docket.services.ingest.active_slugs()`), and an empty value turns it off. The other cities are visited once a day.

## Rationale

The pass exists so that a recording Birmingham posts during the day has its meeting row and its `video_url` before the Legion's scheduled transcriber run (`transcriber/README.md`, "The scheduled run"), and its transcript is public that evening and not the next.

The ingest needs a body of its own because `_do_ingest_all` visits every active city and the operator's answer of 2026-11-19 keeps the other cities at one visit a day; a `TASKS` key also gives the operator `--run-once ingest_afternoon`. `_do_youtube_ingest` and `_do_non_meetings` already read only the cities whose metadata names a YouTube channel or a complete calendar, which is Birmingham alone, so a second trigger on the same function is the whole change, and a second task key for each would have duplicated a body for nothing.

The checks follow from what one Healthchecks schedule can say, which is one cron expression. The two YouTube runs share a minute and the two non-meetings runs share a minute, so one expression with two hours covers both and a missed afternoon run pages as a missed morning run does. The two ingest runs fall on different minutes, which no single expression covers without also naming two times at which nothing runs, so an afternoon ingest pinging `docket-ingest` could be missed silently; it has its own check. `GOALS.md` requires every scheduled task to ping and a missed ping to page.

The cities are a setting because the alternatives each cost more: a city name written into `src/docket/worker/tasks.py` puts a business fact in the worker, a new key in `municipalities.metadata` is a migration and a production statement for what is a scheduling choice, and reusing the `youtube_channel_id` key would tie the ingest to an unrelated fact. A setting also gives the operator an off switch without a code change, which matters because the pass doubles Birmingham's requests to Granicus (`docs/DEBT.md`, `D102`). The task honours `municipalities.active`, or deactivating a city would no longer stop the worker from scraping it.

Only these three tasks have an afternoon run. A same-day clip's votes read from the video, its AI text and its committee documents arrive the next morning. No second calendar read is needed: `non_meetings` hides nothing unless the calendar's sitemap read is at most 36 hours old (`CALENDAR_FRESH_HOURS`), and the morning read is well inside that at the afternoon run.

## Date

2026-11-19, the authoring session of plan `recordings-seen-the-day-posted` (Claude), from the operator's goal and answers of that day; built by that plan's M1 and graduated by its M4 session the same day.

## Status

accepted
