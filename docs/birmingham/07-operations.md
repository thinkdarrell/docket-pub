# 7. Where it runs, and the daily rhythm

One operator runs docket.pub from one machine, the Legion, with the production pieces on Railway. `docs/specs/operations.md` is the authoritative statement of how the system is run; this chapter is the orientation that page assumes. Every step below names its machine and folder.

## The machines

| Where | Runs | Notes |
| --- | --- | --- |
| **Railway, service `docket-web`** | the Flask site, under gunicorn | the Procfile runs the migrations, then the server |
| **Railway, service `worker`** | the APScheduler process, `python -m docket.worker.scheduler` | a separate service (`0023`); idles near 954 MB, and a video OCR scan adds about 750 MB, so nothing may start a second heavy process on it |
| **Railway, PostgreSQL 18** | the one database | 1 GB volume; bulk changes are one targeted statement (`0026`) |
| **Railway, `analytics` + Valkey** | Umami | its own `umami` database; read through views only (`0024`) |
| **The Legion, WSL checkout** `~/docket-pub` | development, `./tools/verify`, the factory, deploys | Docker is not available here |
| **The Legion, Windows clone** `C:\docket-pub` | the transcriber, in Docker Desktop with the GPU | archive at `C:\docket-archive`; chapter 5 |
| **Healthchecks.io** | one check per worker task | a missed ping pages the operator |
| **Namecheap DNS** | `docket.pub` apex CNAME to Railway; `www` is an HTTP-only redirect, which is why HSTS omits subdomains (`0025`, `D10`) | |

## The daily rhythm

`src/docket/worker/scheduler.py` is the single owner of the schedule; `docs/runbooks/cron-worker.md` lists every task with its Healthchecks variable. The times live there and are not repeated here. What matters for the content flow is the **order**, because each task eats what the one before it produced. Every morning, Chicago time:

1. **Housekeeping** before dawn: refresh the backfill-ratio view; re-queue items on meetings that have now happened so their summaries are rewritten in the past tense (`recast_post_meeting_ai`, chapter 4); once a week, clear the scraped flag on recent meetings with an agenda but no items.
2. **Sources** (chapters 1 and 2): `city_calendar`, then `ingest_all` (Granicus), then `video_ocr` (reads the day's votes off up to five clips' frames, chapter 3), then `youtube_ingest`, then `non_meetings` (hides the stream tests the calendar and the channel leave unexplained, chapter 2).
3. **AI** (chapter 4): `ai_items` on the queue of new or re-queued items, then `ai_meetings` for meeting summaries, each under the daily budget.
4. **Facts** (chapter 3): `resolve_member_votes` names the members behind stored member votes, then `vote_matching` links unmatched votes to items, then `process_badges` recomputes process badges on recently completed items.
5. **The front page** (chapter 6): `briefing_facts` rebuilds `city_briefing_facts` for every `briefing` city, which is what "Where they disagreed" and the council cards read.
6. **Transcripts** (chapter 5): `transcript_pipeline` advances a few transcripts one stage each and builds search cards.
7. **Reporting**: `calibration_report` (`docs/specs/calibration.md`) and cache cleanup.
8. **All day**, twice an hour: `process_batches` collects finished Anthropic batch jobs.
9. **Monthly**: `prune_analytics` keeps 24 months of Umami events.

Every task runs through one wrapper that pings its check at start, success, and failure with the traceback, and never re-raises, so one task's failure never stops the next. Each job is `coalesce=True, max_instances=1`. Any task can be run by hand: `python -m docket.worker.scheduler --run-once <task>`, through `railway ssh` for production, mindful of the memory constraint above.

The transcriber is **not** on this schedule. The operator starts it by hand on the Windows side (`docker compose run --rm transcriber --since … --limit … --max-hours …`; an optional at-logon task exists), and its uploads are picked up by the worker's next `transcript_pipeline` tick.

## How a change reaches production

1. Work happens on a branch (`feat/*` by hand, `plan/<slug>` from the factory), in a worktree with its own `venv/`, and `./tools/verify` passes locally.
2. The branch merges to `main` by pull request; branch protection requires the green `verify` check (`0052`).
3. A human, on the Legion in the WSL checkout, from a clean `main`: `scripts/deploy.sh --service docket-web` and, when the worker changed, `--service worker`. The script refuses a dirty tree or any other branch, stamps `COMMIT_SHA`, and runs `railway up` (`0022`). Nothing automated deploys.
4. Migrations run at the web service's start. Data backfills that a change needs are separate scripts, run by the operator from a laptop against the public database URL, each recorded with its count in `docs/specs/operations.md`.
5. A reader-visible change is reflected in `docs/specs/` before its plan closes (`docs/specs/index.md`, "The reflection rule").

## Configuration

Settings reach code only through `src/docket/config.py` (`ARCHITECTURE.md` invariants; `D34` lists the exceptions). `.env.example` names the variables. The ones that change what Birmingham readers see:

- `SMART_BREVITY_UI` (web; on in production) selects the item card face, chapter 6.
- `MINUTES_VS_VIDEO_UI` (web; unset until the ship gate, `0032`) shows the discrepancy rows, chapter 5.
- `IMPACT_FIRST_ENABLED` (worker; on) enables the Stage 2 rewrite, chapter 4.
- `AI_DAILY_BUDGET_USD`, the `AI_*_MODEL` family, and the `TRANSCRIPT_*` limits bound the AI stages, chapters 4 and 5.
- `YOUTUBE_API_KEY` turns the YouTube source on; without it the task logs a warning and reads nothing.
- `TRANSCRIBER_DATABASE_URL` is the transcriber's only credential, on the Windows side.

## Watching it

- `/al/birmingham/source-health/` shows the five stages (source, adapter, parser, index, briefing facts) with their last-success ages and an overall "All systems live / Some stages stale / Pipeline behind".
- `/admin/ai` shows the day's spend against the budget and the ship gate; `/admin/calibration` shows score drift; `/admin/review/discrepancies` and the badge review queue are the two human-approval queues.
- Healthchecks.io pages on a missed ping; the `ALERT_WEBHOOK_URL` receives transcript holds, failures, and a stalled producer.
- `docs/DEBT.md` is the list of known deferrals with the trigger that pays each; `docs/runbooks/` has the procedures for the worker, the transcriber, analytics, and the two UI flips.

## Testing

`./tools/verify` builds a throwaway database `docket_test_<hash>` from the migrations, runs the unit, web, services, and integration tiers plus the judge fixtures, the workflow and plan checks, and the transcriber's suite, and drops the database. Birmingham-shaped data for the web tests comes from `tests/support/briefing_seed.py`. Never run bare `pytest` against a database you care about (`AGENTS.md`).

Back to the [index](README.md).
