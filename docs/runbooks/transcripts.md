# Meeting Transcripts Runbook

Operator notes for the transcript pipeline. Plan 1 (migration 035, the desktop
producer, the public transcript page, item excerpts, and search) is live since
2026-10-10. Plan 2 (speaker resolution, event extraction, the transcript-versus-
minutes comparison, the admin review queue, and the public discrepancy block
behind `MINUTES_VS_VIDEO_UI`) is implemented on `feat/transcripts-comparison`
and ships with the steps under "Ship gate". Design: `docs/superpowers/specs/2026-10-05-meeting-transcripts-design.md`.
Plan 1: `docs/superpowers/plans/2026-10-07-transcripts-foundation.md` (PR #99).

## Shape

- **Producer** (`transcriber/`): runs on the Lenovo Legion (Windows 11, RTX 5070 Ti)
  inside Docker with WSL2 GPU passthrough. faster-whisper large-v3 plus pyannote 3.1.
  It claims Birmingham meetings newest-first, fetches audio from Granicus with ffmpeg,
  transcribes, diarizes, and uploads raw segments to Railway Postgres through the
  public proxy as the narrow `transcriber` role. It never calls an LLM.
  Setup and run commands: `transcriber/README.md`, which also has the desktop
  operating notes, a "What to expect" section from the first runs, and the
  bring-up log.
- **Railway worker**: the `transcript_pipeline` cron (10:00 CT) runs the LLM stages
  on uploaded transcripts; see "Worker stages (plan 2)".
- **Web**: `/al/<slug>/meetings/<id>/transcript/` (full machine transcript with
  per-turn anchors `#t-N`, HTMX tab on the meeting page), a "From the video"
  excerpt on item pages, transcript hits in `/search` with `speaker:` filter,
  and transcript failures on the data debt page.
- **Tables** (migration 035): `transcripts` (one row per meeting, the status
  machine), `transcript_segments` (cascade from transcripts; re-transcription is
  delete-and-replace), `transcript_speakers` (keyed by `meeting_id` +
  `cluster_label`, so manual names survive a re-run), `producer_heartbeats`,
  and three plan 2 tables written by the worker: `minutes_texts`,
  `meeting_events`, `minutes_discrepancies`.

## Status machine (`transcripts.status`)

| Status | Set by | Meaning |
|---|---|---|
| `claimed` | producer | Row inserted, or re-claimed by `--meeting-id` (a re-claimed row keeps its old transcript public until the new upload lands; one re-claimed from `low_speech` stays hidden, its `uploaded_at` cleared for the run); audio not fetched yet. Stale after 6 h and reclaimable. |
| `audio_fetched` | producer | ffmpeg wrote the WAV. Stale after 6 h. |
| `transcribed` | producer | JSON written to the Legion archive, upload pending. Only the same host may resume it until it is stale. |
| `uploaded` | producer | Segments are in Postgres. Public page renders. The worker picks up here. The producer's `--meeting-id` can return a row at any later status to it (the re-run section below). |
| `low_speech` | producer | Under the speech floor (for example a Granicus test stream). Terminal; never retried. A `--meeting-id` re-run of an uploaded meeting never writes it; the row is restored instead. |
| `failed` | producer | ffmpeg 403 or timeout, upload error, and so on. `last_error` has the reason. Retried only with `--retry-failed`. A `--meeting-id` re-run of an uploaded meeting never writes it either; the row is restored instead. |
| `speakers_resolved` | worker | Speaker names resolved per cluster; event extraction is next. |
| `events_extracted` | worker | Event timelines extracted (transcript side always, minutes side when the PDF downloads); comparison is next. |
| `compared` | worker | Aligner, judge, hunter, and vote check done; discrepancies are in the review queue. |
| `needs_review` | worker | Schema failure, refusal, token ceiling, candidate cap, or a minutes PDF with no text layer; `needs_review_reason` says which. Retry from the held tab. |

## Worker stages (plan 2)

`transcript_pipeline` runs at 10:00 America/Chicago (after vote matching) and
advances up to `TRANSCRIPT_PER_TICK` (default 5) transcripts one stage each:

| From | Stage | Model | To |
|---|---|---|---|
| `uploaded` | fitness gate (`TRANSCRIPT_MIN_WORDS`, default 300) then index-point item assignment, then speaker resolution | Sonnet 5.5 | `speakers_resolved` (or `low_speech` when under the floor) |
| `speakers_resolved` | event extraction: transcript side always; minutes side when the minutes PDF downloads | Sonnet 5.5 | `events_extracted` (`compare_skipped_reason` = `no_minutes` / `minutes_unavailable` when the minutes side did not run; re-claimed when minutes appear) |
| `events_extracted` | aligner, Opus judge, Opus hunter, deterministic vote check | Opus 5.5 | `compared` |

Per stage: three attempts with a 24-hour backoff, then `failed`. A 429 does
not count as an attempt (the claim's attempt is handed back; the row still
waits a day). Schema failures, refusals, token-ceiling breaches
(`TRANSCRIPT_TOKEN_CEILING`), candidate-cap trips (`TRANSCRIPT_CANDIDATE_CAP`),
and a minutes PDF with no text layer (`minutes_no_text`: under 50 words
extracted, usually a scan that needs OCR or a different URL) go straight to
`needs_review` with the reason. Minutes PDFs over 40 MB are treated as
unavailable and retried daily.
A transcript that was uploaded stays public through `failed`/`needs_review`.
Every call writes `ai_runs` (stages `transcript_speakers`, `transcript_events`,
`transcript_compare`, `transcript_ab`) so `AI_DAILY_BUDGET_USD` applies.
Manual run: `railway ssh --service worker` then `python -m docket.worker.scheduler --run-once transcript_pipeline`.
One meeting: `venv/bin/python scripts/transcript_recompare.py --meeting-id N --now` (laptop, public DB URL, API key);
add `--minutes-changed` when the minutes PDF changed, or `--transcript-changed` after re-extracting the transcript events (see Re-comparison).

## Worker environment

`AI_TRANSCRIPT_SPEAKER_MODEL`, `AI_TRANSCRIPT_EVENTS_MODEL` (default `claude-sonnet-5-5`),
`AI_TRANSCRIPT_COMPARE_MODEL` (default `claude-opus-5-5`), `AI_TRANSCRIPT_AB_MODEL`
(A/B script only), `TRANSCRIPT_TOKEN_CEILING`,
`TRANSCRIPT_CANDIDATE_CAP`, `TRANSCRIPT_PER_TICK`, `TRANSCRIPT_MIN_WORDS`,
`ALERT_WEBHOOK_URL` (Slack or Discord incoming webhook; unset = silent),
`HEALTHCHECK_TRANSCRIPT_PIPELINE_UUID`. Web service: `MINUTES_VS_VIDEO_UI` (see ship gate).
`AI_DAILY_BUDGET_USD` is shared with `ai_items` and `ai_meetings`; when it is exhausted the
tick advances no transcripts, but the weekly minutes sweep and the stalled-producer alert still run.

## Review queue

`/admin/review/discrepancies`: proposed rows, material first. Approve, reject with a
reason, or edit title/description then approve (edits go to `admin_*` columns; the
model text is kept). Rows with `citation_match = 'missing'` cannot be approved until
you paste the exact excerpt and the guard finds it. Tabs: dismissed by model, stale
(re-comparison no longer shows it), held (needs_review/failed transcripts, with Retry).
Speaker fixes: `/admin/transcripts/<meeting_id>/speakers`; a saved row is manual and
never overwritten by the stage; Release lets the stage try again.

## Ship gate

The public "Minutes vs. Video" block and `/minutes-vs-video/` stay off until at least
70% of material candidates over the first 10 reviewed meetings or the first 30 reviewed
candidates (whichever comes first) are approved. `/admin/ai` shows the running ratio.
When it reads "met", set `MINUTES_VS_VIDEO_UI=true` on the `docket-web` service and
redeploy. The flip is manual and reversible.

## Re-comparison

Corrected minutes: the daily tick re-downloads each compared meeting's minutes at most
weekly; a changed PDF re-extracts the minutes side and re-runs the comparison as a
minutes-changed pass. On that pass approved rows go `stale`, a candidate that comes
back is re-proposed in place (badged "re-review") instead of duplicated, and unmatched
approvals stay `stale` and visible under the stale tab. Every other re-comparison (a
`COMPARE_PROMPT_VERSION` bump, `scripts/transcript_recompare.py` without
`--minutes-changed`) is an unchanged-minutes pass: approved rows are left untouched, a
matched one is kept exactly as the person approved it (its text, excerpts, and
`prompt_version` included) and only stops a duplicate, and only unreviewed proposals go
`stale` (`compare.reconcile`, issue #112). A prompt bump re-queues only meetings with a
proposed or model-dismissed row below the new version, so a meeting whose rows are all
approved is re-run by hand with the script. Bumping `EVENTS_PROMPT_VERSION` re-extracts
the transcript side, which deletes the transcript events approvals are anchored to; the
reset marks the transcript `transcript_changed`, and that pass stales approvals the same
way a minutes-changed pass does (the script's `--transcript-changed` flag runs the same
pass by hand); keep that rare.

## Alerts

`ALERT_WEBHOOK_URL` receives a JSON post when a transcript enters `failed` or
`needs_review` and once a day when the Legion looks stalled (a meeting with video older
than seven days has no transcript and no heartbeat is newer than seven days).

## Haiku A/B and live tests

`venv/bin/python scripts/transcript_extraction_ab.py --meetings 10` writes
`docs/superpowers/experiments/<date>-haiku-extraction-ab.md` with the decision rule and
a verdict. Flip `AI_TRANSCRIPT_EVENTS_MODEL` only on a passing verdict.

Result 2026-10-11 on the meeting 2543 fixture: "Sonnet stays" (Haiku recall 0.79,
precision 0.21, action-type recall floor 0.5; cost $0.17 vs $0.14; 252 s vs 34 s), so
events extraction stays on Sonnet 5.5. The report the live test wrote was not committed.

Live tests (`-m live`, API key required) on 2026-10-11: the pilot end-to-end test
reproduced both hand-verified discrepancies (sequence and wording, both material, exact
citations). The chaotic-meeting test passes with `CHAOTIC_SEQ_RANGE=166-190` on the
meeting 2543 fixture; seq 191 holds a real motion and vote, so 166-191 correctly fails.


## Running the producer (on the Legion)

    docker compose run --rm transcriber --since 2025-10-28 --limit 10 --max-hours 3

- `--since` is a floor on `meeting_date`; the queue is newest-first.
- `--limit` counts loop iterations, including `low_speech` skips.
- The loop exits on its own when nothing is claimable, at `--max-hours`, or after
  5 consecutive `failed` results (`--max-consecutive-failures`).
- Re-running is always safe. Ctrl-C finishes the current meeting.
- `--retry-failed` re-queues `failed` rows (not `low_speech`).
- Throughput seen 2026-10-10: about 15x real time on the GPU; a 104-minute
  council meeting went from claim to upload in about 6 minutes including the
  audio download. The current council era (seated 2025-10-28) is about 70
  meetings, so roughly 7 hours of Legion time.
- The producer skips meetings with `is_hidden = TRUE`, so hiding a junk meeting
  also stops the GPU spending time on it.

## Re-transcribing one meeting

The producer's `--meeting-id N` re-claims one Birmingham meeting whatever its
status and replaces its transcript. Use it after a producer change (the first
case is meeting 2543 after the 2026-10 cleaning and speaker-split change, which
bumped `transcripts.version` to 2; the 48 earlier uploads stay at version 1).
A re-run deletes the meeting's segments, drops the non-manual
`transcript_speakers` rows whose cluster label the new output no longer has,
clears the worker's resolution (`council_member_id`, `display_name`, `role`,
`confidence`, `method`, `needs_review`) on the non-manual rows that remain, and
writes `compare_skipped_reason = 'transcript_changed'` when the row had been
uploaded before, so the worker's next tick re-resolves speakers, re-extracts
events, and runs the comparison as a changed-input pass (approved discrepancies
go `stale` and are re-proposed; see Re-comparison). `docs/specs/transcripts.md`
states those rules and the busy guard below; this section is the procedure.

Before the run:

- Do not start it inside the worker's daily `transcript_pipeline` window
  (10:00 America/Chicago, `src/docket/worker/scheduler.py`). The producer refuses
  a row whose `last_attempted_at` is within the last 30 minutes (`meeting N was
  touched at ...; wait 30 minutes`, exit 1); the worker's claim is the only
  writer that stamps that column (the producer's own status writes never stamp
  it; the other writers reset it to NULL), and a stage in flight would
  otherwise overwrite the claim.
- Manual speaker rows (`is_manual`) are kept as they are and stay attached to
  whatever new cluster reuses their `cluster_label`; the remap is unbuilt
  (`docs/DEBT.md` `D54`). List them first and expect to redo them in
  `/admin/transcripts/<meeting_id>/speakers` after the run:

      $PSQL "$URL" -c "select cluster_label, display_name, council_member_id
        from transcript_speakers where meeting_id = 2543 and is_manual;"

- Optionally copy `C:\docket-archive\transcripts\2543\` aside; the run overwrites
  `transcript.json` and `words.json` there.

On the Legion, in Git Bash from `C:/docket-pub`: `git pull`, `cd transcriber`,
`docker compose build` (the image copies the package), then

    docker compose run --rm transcriber --meeting-id 2543

Expect the log to end `done {'uploaded': 1, 'failed': 0, 'low_speech': 0} oom_fallbacks=0`.
The run exits 1 whenever `uploaded` is 0: the id was not an eligible Birmingham
meeting (hidden, no video, non-numeric external id), the busy refusal above, or a run
that ended `failed` or `low_speech`. In the last two cases the `transcripts` row is
put back exactly as it was before the claim, the old transcript stays on the site, the
held tab does not list it, and the reason is in the log line `meeting N re-run ended
failed (...)`; fix the cause and run it again, there is no 30-minute wait. A producer
that died mid-run (power loss) is the one case that leaves the row at a producer
status with the old transcript still public (still hidden, when the row started from
`low_speech`); run `--meeting-id N` again.

After the run, from the laptop (`URL` and `PSQL` as in "Checking progress"):

    $PSQL "$URL" -c "select version, status, compare_skipped_reason, word_count
      from transcripts where meeting_id = 2543;"
    # expect: 2 | uploaded | transcript_changed | ...

    $PSQL "$URL" -c "select count(*) from transcript_segments s join transcripts t on t.id = s.transcript_id
      where t.meeting_id = 2543 and (s.text ilike '%ALEA, CJI, APC%' or s.text ilike 'Thank you for joining us%');"
    # expect: 0

    $PSQL "$URL" -c "select percentile_cont(0.5) within group (order by s.end_s - s.start_s)
      from transcript_segments s join transcripts t on t.id = s.transcript_id
      where t.meeting_id = 2543 and not s.is_silence;"
    # expect well under 26.8 (the version-1 median)

The public page serves the old turns until the upload lands and the new turns
from then on. A row the worker's fitness gate had sent to `low_speech` (a data-debt
row labelled "Too short to analyze (N words)") is the exception: `claim_meeting()`
clears its `uploaded_at` for the run, so its page stays a 404 and the meeting page
has no transcript link until the new upload lands, as before the run; a re-run that
ends without an upload puts `uploaded_at` back with the rest of the row. The worker's
10:00 CT tick does the rest. If the transcript lands in the admin held tab and is
retried from there, `retry_transcript()` nulls the `transcript_changed` marker
(`docs/DEBT.md` `D52`); once it reaches `events_extracted`, run
`venv/bin/python scripts/transcript_recompare.py --meeting-id 2543 --now --transcript-changed`
instead of relying on the tick's compare.

## Checking progress from the laptop

All read-only. The URL is the app's public proxy URL from Railway.

    URL=$(railway variables --service docket-web --json | jq -r .DATABASE_PUBLIC_URL)
    PSQL=/opt/homebrew/opt/postgresql@18/bin/psql   # Railway is PostgreSQL 18

    # Every transcript with its evidence
    $PSQL "$URL" -c "select t.id, m.meeting_date, t.status, round(t.audio_duration_s/60) mins,
      round(t.speech_ratio::numeric,2) speech, t.word_count, left(t.last_error,60) err
      from transcripts t join meetings m on m.id=t.meeting_id order by m.meeting_date desc;"

    # Is the Legion alive? last_status is started / processing / exited
    $PSQL "$URL" -c "select host, last_status, now()-last_seen_at as age from producer_heartbeats;"

    # What the producer will claim next
    $PSQL "$URL" -c "select m.id, m.meeting_date, m.external_id from meetings m
      join municipalities mu on mu.id=m.municipality_id
      left join transcripts t on t.meeting_id=m.id
      where mu.slug='birmingham' and m.video_url is not null and not m.is_hidden
        and m.external_id ~ '^[0-9]+$' and m.meeting_date >= '2025-10-28' and t.id is null
      order by m.meeting_date desc limit 10;"

A heartbeat older than a few minutes with `last_status = 'processing'` means the
producer died mid-meeting; its claim becomes reclaimable after 6 hours, or sooner
if you re-run on the same host.

## The transcriber role

Created once per database (done on Railway 2026-10-10):

    psql "$URL" -v password="$(openssl rand -hex 32)" -f scripts/sql/create_transcriber_role.sql

It can read `meetings`, `municipalities`, `council_members`, `agenda_items` and
write only `transcripts`, `transcript_segments`, `transcript_speakers`,
`producer_heartbeats`. The connection string lives only in `transcriber/.env` on
the Legion. Rotate with `ALTER ROLE transcriber PASSWORD '...'` and update that file.

## Granicus junk clips (Monday test streams)

Birmingham's Granicus archive carries a short "Regular City Council Meeting"
clip on most Mondays before the Tuesday meeting: a staff test of the stream,
1 to 25 minutes long, often "mic check, one, two" or silence. Granicus later
deletes many of them, but docket.pub has already ingested the meeting row.
Tells: Monday date, a real meeting the next day, no votes, no minutes, zero or a
handful of agenda items that duplicate the Tuesday agenda. Real Monday meetings
exist (2024-12-23 before Christmas Eve, 2019-12-30, 2010-05-10) and are all over
an hour with full agendas, so **duration is the discriminator, not the weekday**.
The Granicus listing exposes a `Duration` column per clip that the adapter does
not read yet; an ingest-side auto-hide for short clips is the open follow-up.

What the producer does with them: the speech floor catches the silent ones as
`low_speech`; a mic-check clip with real speech passes and uploads a tiny
transcript (the plan 2 word-count floor, `TRANSCRIPT_MIN_WORDS`, sends it to `low_speech`).

What to do: hide the meeting from the admin meeting page (`/admin/meetings/<id>/hide`),
which sets `is_hidden`, `hidden_at`, `hidden_by`. The public page and transcript page
return 404, the producer skips it, and the hidden-meetings admin list keeps it
reversible. Existing transcript rows stay attached to the hidden meeting.
On 2026-10-11, 19 such meetings were hidden this way (all 18 unhidden Monday test
streams since 2025-10-28 plus the one-minute 2019-12-30 clip).

## Tests

Run the two suites separately; both directories are packages named `tests`, so a
single pytest invocation fails collection:

    pytest tests                 # root suite; integration tests need a local DATABASE_URL
    pytest transcriber/tests     # producer suite; GPU tests skip without CUDA

`./tools/verify` runs both suites, the producer suite as its fifth check against the
throwaway database it builds (`docs/specs/operations.md`).

## History

- 2026-10-08: PR #99 merged (plan 1); deployed, migration 035 applied.
- 2026-10-10: Legion bring-up passed on the first try (PR #102: torch 2.8.0+cu128,
  CTranslate2 4.8.2 sees the Blackwell GPU; pins for pyannote 3.x). Transcriber
  role created on Railway. First runs: 10 meetings in about 39 minutes, three
  caught as `low_speech`.
- 2026-10-11: 19 Monday test-stream meetings hidden.
- 2026-10: plan 2 (worker stages, review queue, public block behind flag).
- 2026-10: migration 036: dropped the has_event CHECK; added minutes_texts.last_checked_at.
  Deploy: migrations run at container start; 036 applies.
- 2026-10: a `--meeting-id` re-run keeps the old transcript public until the new upload lands, a re-run that ends `failed` or `low_speech` restores the row, and the busy guard reads the worker's stamp alone (plan `rerun-keeps-transcript-public`).
- 2026-10: a `--meeting-id` re-run of a row resting at `low_speech` keeps it hidden until the new upload lands (`claim_meeting()` clears `uploaded_at` for the run; plan `low-speech-rerun-stays-hidden`, decision `0050`).
