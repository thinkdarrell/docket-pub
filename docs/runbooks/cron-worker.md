# Cron Worker Runbook

The Railway `worker` service runs `python -m docket.worker.scheduler` and fires
the jobs registered in `src/docket/worker/scheduler.py`. That file owns the
schedule: `python -m docket.worker.scheduler --list` inside the worker container
(`venv/bin/python -m docket.worker.scheduler --list` in a checkout) prints every
job with the task it runs and its trigger, in America/Chicago time. The design
spec is `docs/superpowers/specs/2026-05-04-cron-worker-design.md`.

**Status:** Live in production since 2026-05-04. Task count grew from the original 5 through 2026-05 as Phase 2/3 features shipped (`process_badges`, `calibration_report`, `process_batches`, `refresh_backfill_ratio_mv`, `prune_analytics`, `video_ocr`).

## Task inventory

One row per task, in the order `--list` prints the jobs; a task that two jobs run has one row, at its first job. The times are not written here: `--list` prints them.

| Task | Healthchecks env var | Notes |
|---|---|---|
| `prune_analytics` | `HEALTHCHECK_PRUNE_ANALYTICS_UUID` *(silent-by-design)* | Drops Umami events older than 24 months |
| `refresh_backfill_ratio_mv` | `HEALTHCHECK_REFRESH_BACKFILL_RATIO_UUID` | Refreshes `mv_city_backfill_ratio` (concurrent) |
| `recast_post_meeting_ai` | `HEALTHCHECK_RECAST_POST_MEETING_UUID` (optional) | Re-queues forward-voice items + summary once a meeting is past and has video/minutes |
| `repair_empty_agendas` | `HEALTHCHECK_REPAIR_UUID` | Clears stuck `agenda_items_scraped` flags |
| `city_calendar` | `HEALTHCHECK_CITY_CALENDAR_UUID` (optional) | Reads each city's own calendar (`metadata.calendar_url`; Birmingham only at first) into `city_calendar_events` from three readers that fail alone: the council page, the events search, and the event pages the sitemap lists that are not yet stored (at most 60 in a run, one second apart); per-city failure isolation; before `ingest_all` so the resolver sees the day's events. The log line names the count per reader and whether the sitemap read was complete, which `non_meetings` requires (`docs/specs/meeting-types.md`, "The city calendar") |
| `ingest_all` | `HEALTHCHECK_INGEST_UUID` | Loops all municipalities; per-city failure isolation |
| `video_ocr` | `HEALTHCHECK_VIDEO_OCR_UUID` | Claim pattern; 3-attempt cap; 60-day window |
| `youtube_ingest` | `HEALTHCHECK_YOUTUBE_INGEST_UUID` (optional) | Runs twice a day under two job ids, `youtube_ingest` and `youtube_ingest_afternoon`, and pings one check. Reads the council's YouTube uploads of the last 30 days; attaches recordings to Granicus rows or creates yt- rows after 3 days; Birmingham only at first |
| `non_meetings` | `HEALTHCHECK_NON_MEETINGS_UUID` | Runs twice a day under two job ids, `non_meetings` and `non_meetings_afternoon`, and pings one check. Hides a short or speechless generic-titled clip on a day with no stored calendar event (`hidden_reason = 'not_a_meeting'`); hides nothing unless the sitemap reader of `city_calendar` finished a read with no failed page in the last 36 hours; logs the ids hidden and held back per city; after each `youtube_ingest` run so a recording that names a clip is attached first; Birmingham only (`docs/specs/meeting-types.md`, "Clips that are not meetings") |
| `ai_items` | `HEALTHCHECK_AI_ITEMS_UUID` | v3 pipeline; gated by `AI_DAILY_BUDGET_USD` |
| `committee_documents` | `HEALTHCHECK_COMMITTEE_DOCUMENTS_UUID` | Lists the PDFs each council committee page links (`metadata.committee_document_pages`; Birmingham only at first), fetches and reads up to 25 not yet read (at most 33 requests, one second apart), reads stored text again where a rule changed, and attaches each document to its committee meeting, creating a `cdoc-` meeting when minutes prove one that has no row; after the morning `youtube_ingest` so a new document finds the day's recording; a page that fails is skipped, and the task fails only when every page of a city did. The one-time fill is `scripts/backfill_committee_documents.py` |
| `ai_meetings` | `HEALTHCHECK_AI_MEETINGS_UUID` | Sonnet 4.6; two-phase (provisional → adopted) |
| `resolve_member_votes` | `HEALTHCHECK_RESOLVE_MEMBER_VOTES_UUID` | Gives every `member_votes` row with no `council_member_id` its member from the roster; the rule is `docs/specs/votes.md` |
| `vote_matching` | `HEALTHCHECK_VOTE_MATCH_UUID` | N:M matcher + strict re-parse |
| `process_badges` | `HEALTHCHECK_PROCESS_BADGES_UUID` | Conservative policy badge writer |
| `briefing_facts` | `HEALTHCHECK_BRIEFING_FACTS_UUID` | Rebuilds `city_briefing_facts` (split votes, member roll-call counts) for every city whose metadata carries `briefing: true`; one upsert per city |
| `transcript_pipeline` | `HEALTHCHECK_TRANSCRIPT_PIPELINE_UUID` | Transcript LLM stages; see `docs/runbooks/transcripts.md` |
| `calibration_report` | `HEALTHCHECK_CALIBRATION_UUID` *(silent-by-design)* | Daily diagnostic, no production impact |
| `ingest_afternoon` | `HEALTHCHECK_INGEST_AFTERNOON_UUID` | Ingests the cities `AFTERNOON_INGEST_SLUGS` names (Birmingham by default) that are also active, so a recording posted during the day has its row before the Legion's scheduled transcriber run (`transcriber/README.md`, "The scheduled run"); the other cities keep one visit a day; an empty value turns it off; per-city failure isolation; logs one `ingest_afternoon <slug>: found=... errors=...` line per city |
| `process_batches` | `HEALTHCHECK_PROCESS_BATCHES_UUID` | Anthropic Batches API polling (Phase 3 backfill) |

**Silent-by-design** = the task is in `health.py`'s `TASK_UUID_ENV` map (so `ping()` doesn't `KeyError`), but no UUID env var is set on the `worker` service. The ping call short-circuits at the env lookup. Used for tasks whose failure mode is local and self-recovering (`prune_analytics` — slightly longer data retention; `calibration_report` — daily diagnostic with no citizen impact). Adding a UUID later is a no-code change: create the check at healthchecks.io, set the env var, redeploy.

**Which tasks are unmonitored:** at startup the worker logs one WARNING naming every task whose variable is unset, apart from the silent-by-design ones (`unmonitored_tasks` and `SILENT_BY_DESIGN` in `src/docket/worker/health.py`). After adding a task or deploying the worker, read that line: `railway logs --service worker | grep HEALTHCHECK`. No line means every task that should have a check has one.

## Healthchecks.io setup

Each check should be created at https://healthchecks.io. Copy the UUID from the ping URL (`https://hc-ping.com/<UUID>`) and set it on the `worker` service:

```bash
railway variables --service worker --set HEALTHCHECK_INGEST_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_AI_ITEMS_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_AI_MEETINGS_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_VOTE_MATCH_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_REPAIR_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_PROCESS_BADGES_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_PROCESS_BATCHES_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_REFRESH_BACKFILL_RATIO_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_VIDEO_OCR_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_BRIEFING_FACTS_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_RESOLVE_MEMBER_VOTES_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_CITY_CALENDAR_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_NON_MEETINGS_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_COMMITTEE_DOCUMENTS_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_INGEST_AFTERNOON_UUID=<uuid>
railway variables --service worker --set HEALTHCHECK_YOUTUBE_INGEST_UUID=<uuid>
# silent-by-design (do not set unless you want active alerting):
# railway variables --service worker --set HEALTHCHECK_CALIBRATION_UUID=<uuid>
# railway variables --service worker --set HEALTHCHECK_PRUNE_ANALYTICS_UUID=<uuid>
```

Suggested grace per check, and the job or jobs each check hears from. Give each check the schedule of its job as `--list` prints it, in America/Chicago. A check that hears from two jobs (`docket-youtube-ingest`, `docket-non-meetings`) takes one cron expression naming both hours, `<minute> <morning hour>,<afternoon hour> * * *`, so a missed afternoon run pages as a missed morning run does. A job that runs on one day of the week is printed with the day as APScheduler numbers it, counting from Monday (`day_of_week='0'` is Monday), where a cron expression at Healthchecks counts from Sunday (`0` is Sunday, `1` is Monday): write the day into the check's schedule by its name, not by copying the digit.

| Check name | Job or jobs | Grace |
|---|---|---|
| docket-city-calendar | `city_calendar` | 2h |
| docket-ingest | `ingest_all` | 2h |
| docket-video-ocr | `video_ocr` | 2h |
| docket-youtube-ingest | `youtube_ingest`, `youtube_ingest_afternoon` | 2h |
| docket-non-meetings | `non_meetings`, `non_meetings_afternoon` | 2h |
| docket-ai-items | `ai_items` | 2h |
| docket-committee-documents | `committee_documents` | 2h |
| docket-ai-meetings | `ai_meetings` | 2h |
| docket-resolve-member-votes | `resolve_member_votes` | 2h |
| docket-vote-matching | `vote_matching` | 2h |
| docket-process-badges | `process_badges` | 2h |
| docket-briefing-facts | `briefing_facts` | 2h |
| docket-ingest-afternoon | `ingest_afternoon` | 2h |
| docket-process-batches | `process_batches` | 1h |
| docket-refresh-backfill-ratio | `refresh_backfill_ratio_mv` | 2h |
| docket-repair | `repair_empty_agendas` | 24h |

(Optional) Configure notification channels in Healthchecks.io (email, Slack, etc.) after creating the checks.

## Deploy

The `worker` service is a separate Railway service from `docket-web`, both deploying from the same Docker image. **Adding a `worker:` line to `Procfile` does NOT auto-create a Railway service** — you must create it once in the dashboard, then push code via CLI.

**One-time service creation** (already done for production):
1. Railway dashboard → **+ Create** → **Empty Service**, name it `worker`.
2. **Settings → Deploy → Custom Start Command:** `python -m docket.worker.scheduler` (this overrides the Procfile's `web:` line for this service).
3. **Variables tab:** copy from `docket-web` via Raw Editor. `DATABASE_URL` should be `${{Postgres.DATABASE_URL}}` (reference, not literal). Add the `HEALTHCHECK_*_UUID` vars from the table above.
4. Click **Deploy** in the dashboard to commit staged changes.

**Per-deploy:**
```bash
railway up --service worker --detach
```

(The matching `railway up --detach` for `docket-web` is unchanged.)

## Verify each task end-to-end via --run-once

The canonical way to manually trigger a task is `railway ssh --service worker`, which drops you into a shell **inside the running container** where `postgres.railway.internal` resolves and all env vars are set:

```bash
railway ssh --service worker
# now inside the container
python -m docket.worker.scheduler --run-once repair_empty_agendas
python -m docket.worker.scheduler --run-once refresh_backfill_ratio_mv
python -m docket.worker.scheduler --run-once recast_post_meeting_ai
python -m docket.worker.scheduler --run-once city_calendar
python -m docket.worker.scheduler --run-once ingest_all
python -m docket.worker.scheduler --run-once ingest_afternoon
python -m docket.worker.scheduler --run-once video_ocr
python -m docket.worker.scheduler --run-once youtube_ingest
python -m docket.worker.scheduler --run-once non_meetings
python -m docket.worker.scheduler --run-once ai_items
python -m docket.worker.scheduler --run-once committee_documents
python -m docket.worker.scheduler --run-once ai_meetings
python -m docket.worker.scheduler --run-once resolve_member_votes
python -m docket.worker.scheduler --run-once vote_matching
python -m docket.worker.scheduler --run-once process_badges
python -m docket.worker.scheduler --run-once briefing_facts
python -m docket.worker.scheduler --run-once calibration_report
python -m docket.worker.scheduler --run-once process_batches
python -m docket.worker.scheduler --run-once prune_analytics
exit
```

Each should emit a Healthchecks ping (visible on the dashboard within seconds — silent-by-design tasks skip the ping) and complete successfully. Order: do `repair` and `vote_matching` first — they're zero-cost (DB only). `ingest_all` hits Granicus and other adapters. `ai_items` and `ai_meetings` spend a few cents each on Anthropic. `video_ocr` runs ffmpeg + tesseract — note the worker RSS climbs to ~1.7 GB during an active scan (the worker's memory constraint is in `GOALS.md`, Constraints; `docs/specs/operations.md`, Railway specifics, says what follows from it).

**Don't use `railway run --service worker python ...`** — that runs locally on your laptop, not in the container, and `postgres.railway.internal` won't resolve. If you must drive a one-shot from your laptop (e.g., the worker container is down), substitute `DATABASE_URL=$DATABASE_PUBLIC_URL` and run from `~/docket-pub`:

```bash
DATABASE_URL=$(railway variables --service worker --kv | grep ^DATABASE_PUBLIC_URL= | cut -d= -f2-) \
  HEALTHCHECK_REPAIR_UUID=<uuid> \
  venv/bin/python -m docket.worker.scheduler --run-once repair_empty_agendas
```

## Manual one-off triggers

The `--run-once` invocation through `railway ssh` is the right pattern for ad-hoc runs in production. Prefer it over calling the underlying CLIs directly — `--run-once` runs through the same logging and Healthchecks pipeline as scheduled runs, so manual triggers don't silently bypass observability.

## Member vote resolution

`resolve_member_votes` (daily) gives every `member_votes` row whose `council_member_id` is NULL, from either source, its council member from the roster; the rule is `RosterIndex.resolve` in `src/docket/services/member_votes.py`, described in `docs/specs/votes.md`. Each run logs one summary line, `resolve_member_votes resolved=N unresolved=M distinct_names=K` (rows given an id, rows still NULL, distinct stored names among them), and one WARNING line per unresolved name, `member_votes: unresolved name='<name>' municipality_id=<id> rows=<n>`, for the thirty most common, then `member_votes: and N more unresolved names` when more remain. An unresolved name is a parser question (a name the minutes parser should not have produced, fixed in `src/docket/analysis/minutes_parser.py`) or a roster question (a person the roster lacks for that meeting date, fixed by a migration under decision `0004`); it is never a row to delete, because the row is evidence of what the source said. Expected residue today: the five continuing members on meetings dated before 2025-10-28, `D67` in `docs/DEBT.md`.

The one-time production run of `python -m docket.worker.scheduler --run-once resolve_member_votes` after the deploy of plan `member-votes-name-their-member` (`docs/DEBT.md` `D66`) is recorded here by the operator: the summary line it printed and the before-and-after results of that plan's queries 1 and 3. Not yet run.

## When a Healthchecks alert fires

1. Check Railway logs for the worker service for the relevant time window.
2. The `health.ping(task, "fail", body=traceback)` line sends the traceback to Healthchecks, so the alert email/notification will include it.
3. Reproduce — either from a laptop with the public DB URL, or inside the container via `railway ssh --service worker`:
   ```bash
   # laptop
   DATABASE_URL=$(railway variables --service worker --kv | grep ^DATABASE_PUBLIC_URL= | cut -d= -f2-) \
     venv/bin/python -m docket.worker.scheduler --run-once <task>

   # in-container (preferred)
   railway ssh --service worker
   python -m docket.worker.scheduler --run-once <task>
   ```
4. Once fixed, re-trigger the task with `--run-once` via `railway ssh` to clear the "down" state on the corresponding Healthcheck.

**Note**: A green `docket-ingest` ping does not guarantee every city succeeded — `ingest_all` aggregates all cities under a single check. If a specific municipality's data looks stale despite green pings, check Railway logs for per-city `ingest failed for <slug>` exceptions; per-city failures are caught and logged but do not fail the overall task. `docket-ingest-afternoon`, like `docket-ingest`, is also green when a city's ingest returned errors without raising: the `errors=` count of the task's `ingest_afternoon <slug>: found=... errors=...` log line says so. It is green, too, when the afternoon ingest did nothing at all: a city whose ingest raised is logged as `ingest failed for <slug>` (the same text `ingest_all` logs) and passed over, a name in `AFTERNOON_INGEST_SLUGS` that is not an active city's slug (a misspelling, a capital letter) is logged at WARNING as `ingest_afternoon: <slug> is not an active municipality; skipped`, and the task then pings success. With the default of one city, a day with no `ingest_afternoon birmingham: found=...` line in the log is a day the afternoon ingest read nothing, whatever the check shows (`D177` in `docs/DEBT.md`).

## 18-month AI backfill (one-shot, separate from the worker)

The worker handles steady-state. To populate AI summaries/scoring for historical items, use `python -m docket.ai.cli` from a laptop (`docs/specs/operations.md`, Railway specifics, gives the invocation against `DATABASE_PUBLIC_URL`). The cron-driven `process_batches` task polls and ingests Anthropic Batches API results every 30 minutes, so submitting a batch via the CLI and waiting is the recommended path — the worker handles the ingest side automatically.
