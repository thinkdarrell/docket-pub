# Meeting Transcripts Runbook

Operator notes for the transcript pipeline. Plan 1 (migration 035, the desktop
producer, the public transcript page, item excerpts, and search) is live since
2026-10-10. Plan 2 (speaker resolution, event extraction, the transcript-versus-
minutes comparison, the admin review queue, and the public discrepancy block)
is not written yet. Design: `docs/superpowers/specs/2026-10-05-meeting-transcripts-design.md`.
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
- **Railway worker**: nothing yet. Plan 2 adds the `transcript_pipeline` cron
  (10:00 CT) that runs the LLM stages on uploaded transcripts.
- **Web**: `/al/<slug>/meetings/<id>/transcript/` (full machine transcript with
  per-turn anchors `#t-N`, HTMX tab on the meeting page), a "From the video"
  excerpt on item pages, transcript hits in `/search` with `speaker:` filter,
  and transcript failures on the data debt page.
- **Tables** (migration 035): `transcripts` (one row per meeting, the status
  machine), `transcript_segments` (cascade from transcripts; re-transcription is
  delete-and-replace), `transcript_speakers` (keyed by `meeting_id` +
  `cluster_label`, so manual names survive a re-run), `producer_heartbeats`,
  and three plan 2 tables that are empty today: `minutes_texts`,
  `meeting_events`, `minutes_discrepancies`.

## Status machine (`transcripts.status`)

| Status | Set by | Meaning |
|---|---|---|
| `claimed` | producer | Row inserted; audio not fetched yet. Stale after 6 h and reclaimable. |
| `audio_fetched` | producer | ffmpeg wrote the WAV. Stale after 6 h. |
| `transcribed` | producer | JSON written to the Legion archive, upload pending. Only the same host may resume it until it is stale. |
| `uploaded` | producer | Segments are in Postgres. Public page renders. Plan 2 picks up here. |
| `low_speech` | producer | Under the speech floor (for example a Granicus test stream). Terminal; never retried. |
| `failed` | producer | ffmpeg 403 or timeout, upload error, and so on. `last_error` has the reason. Retried only with `--retry-failed`. |
| `speakers_resolved`, `events_extracted`, `compared`, `needs_review` | worker (plan 2) | Not used yet. |

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
transcript (a word-count floor is a plan 2 item).

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

## History

- 2026-10-08: PR #99 merged (plan 1); deployed, migration 035 applied.
- 2026-10-10: Legion bring-up passed on the first try (PR #102: torch 2.8.0+cu128,
  CTranslate2 4.8.2 sees the Blackwell GPU; pins for pyannote 3.x). Transcriber
  role created on Railway. First runs: 10 meetings in about 39 minutes, three
  caught as `low_speech`.
- 2026-10-11: 19 Monday test-stream meetings hidden.
