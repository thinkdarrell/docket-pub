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
  It claims Birmingham meetings newest-first, fetches audio from Granicus with ffmpeg
  (or, for a `yt-` meeting recorded only on YouTube, downloads it with yt-dlp first),
  transcribes, diarizes, and uploads raw segments to Railway Postgres through the
  public proxy as the narrow `transcriber` role. It never calls an LLM.
  An ordinary run first measures, without the GPU, where each YouTube recording
  attached to a Granicus meeting sits on that clip's clock, one
  `meeting_video_alignments` row per recording; "Measuring YouTube recordings" in
  `transcriber/README.md` has the log lines and the `--measure-limit` flag.
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
| `low_speech` | producer; worker (fitness gate) | Under the producer's speech floor (for example a Granicus test stream), or under the worker's word floor (`TRANSCRIPT_MIN_WORDS`) after an upload, in which case the row keeps `uploaded_at` and its segments and the predicate hides it by status. Terminal; never retried. A `--meeting-id` re-run of an uploaded meeting never writes it; the row is restored instead. |
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
`transcript_compare`, `transcript_ab`, `transcript_cards`) so `AI_DAILY_BUDGET_USD` applies.
Manual run: `railway ssh --service worker` then `python -m docket.worker.scheduler --run-once transcript_pipeline`.
One meeting: `venv/bin/python scripts/transcript_recompare.py --meeting-id N --now` (laptop, public DB URL, API key);
add `--minutes-changed` when the minutes PDF changed, or `--transcript-changed` after re-extracting the transcript events (see Re-comparison).

Search cards. After the three stages the same tick builds search cards (hidden search text for each
agenda item the transcript places; `src/docket/ai/transcripts/cards.py`). The stage is not a status.
`docs/specs/search.md` owns its rules and this runbook does not restate them: Search cards says what
a card is and how a reply is validated, and Card runs says which transcripts the stage claims and how
many a tick, what `done`, `failed` (with or without `incomplete:`), and `held` mean and when each is
retried, what a 429 does, and the lines the stage logs. `docs/specs/transcripts.md` (Search cards)
says where the stage sits and what it never writes. The by-hand command,
`scripts/build_search_cards.py`, and its flags are in `docs/specs/operations.md` (Railway specifics);
what the operator records from it goes under Search cards: measurements below.

## Worker environment

`AI_TRANSCRIPT_SPEAKER_MODEL`, `AI_TRANSCRIPT_EVENTS_MODEL` (default `claude-sonnet-5-5`),
`AI_TRANSCRIPT_COMPARE_MODEL` (default `claude-opus-5-5`), `AI_TRANSCRIPT_AB_MODEL`
(A/B script only), `TRANSCRIPT_TOKEN_CEILING`,
`TRANSCRIPT_CANDIDATE_CAP`, `TRANSCRIPT_PER_TICK`, `TRANSCRIPT_MIN_WORDS`,
`AI_TRANSCRIPT_CARDS_MODEL` (the search-card model, default `claude-sonnet-5-5`; it needs a `PRICING` entry),
`TRANSCRIPT_CARDS_PER_TICK` (meetings given search cards per tick, default 2; 0 turns the card stage off),
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
bumped `transcripts.version` to 2; the 48 earlier uploads stay at version 1; the
2026-10-17 signature-phrase and same-speaker merge change bumped it to 3).
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
    # expect: 3 | uploaded | transcript_changed | ...

    $PSQL "$URL" -c "select count(*) from transcript_segments s join transcripts t on t.id = s.transcript_id
      where t.meeting_id = 2543 and (s.text ilike '%ALEA, CJI, APC%'
        or s.text ~* '^thank(s| you) for watching'
        or (s.text ilike 'Thank you for joining us%' and s.avg_logprob <= -0.9 and length(s.text) < 60));"
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

## Archived inputs: cache, capture, replay

Every run keeps `audio.flac`, `raw.json`, and `diarization.json` in the meeting's archive folder
(`docs/specs/transcripts.md` says what each holds). A re-run of a meeting with `audio.flac`
decodes it instead of downloading (the log says `audio from the archive's audio.flac`).
From `C:/docket-pub/transcriber` on the Legion:

    docker compose run --rm transcriber --cache-audio 2543 1 2       # download only; no GPU, no DB writes
    docker compose run --rm transcriber --capture-inputs 2543 1 2    # GPU; writes raw.json + diarization.json, no DB writes
    docker compose run --rm transcriber --replay 2543 1 2            # CPU; writes replay.json, never transcript.json

Each prints one `... done {id: result}` line and exits 1 when any meeting did not succeed;
a hidden or otherwise ineligible meeting is `ineligible`. Replay is for checking a change to
`engine.py` before a backlog re-run: run it over every folder, compare `replay.json` with
`transcript.json`, and only then re-run with `--meeting-id` to upload. A capture is a fresh
GPU pass, so its inputs can in principle differ slightly from the ones behind the uploaded
transcript (on 2543 they did not: the replay matched the upload row for row).

## Measuring YouTube recordings (the backlog)

An ordinary run measures up to 20 attached YouTube recordings against their
Granicus clips before it transcribes (`transcriber/README.md`, "Measuring YouTube
recordings"). To measure without transcribing, after any transcribing run has
exited so two runs never download from YouTube at once:

    docker compose run --rm transcriber --limit 0 --measure-limit 400 --max-hours 8

Repeat until the `measure done` line says `remaining=0`; each run picks up where
the last stopped. The cost is the downloads: about 30 MiB of YouTube audio per
recording, and for a meeting whose audio is not in the archive the whole Granicus
MP4 (`D110`). The run of 2026-11-06 measured 20 in under an hour.

After a run, query 4 under "The operator's read-only queries" in
`plans/completed/video-links-land-on-the-moment.md` lists what was stored. Read
every `rejected` row and the lowest-scoring `passed` rows. On the 18 that passed
first, the runner-up score was 3.3 to 6.0; a `rejected` row whose runner-up is
near its score is a recording that matches at two offsets (`D98`), not a wrong
match. The count of `rejected` rows by reason is the trigger of `D97` and `D98`.

A rejected row can be passed by hand when its confirmed span is exactly its
confirmed windows: `granicus_end_s - granicus_start_s = windows_confirmed * 300`.
Then every window inside the span agreed on the offset and the windows that
disagreed all lie outside it, so links inside the span land where they should
and links outside it stay on Granicus. The statement is the reverse of the
operator's off switch in the plan's "Idempotence and Recovery":

    UPDATE meeting_video_alignments
       SET status = 'passed', reason = 'operator'
     WHERE meeting_video_id = <id> AND status = 'rejected'
       AND granicus_end_s - granicus_start_s = windows_confirmed * 300
    RETURNING meeting_video_id, status, granicus_start_s, granicus_end_s;

The row is then current and is not measured again until `ALIGN_METHOD_VERSION`
rises. Record each override under History with the figures that justified it.
A rejected row whose span is longer than its confirmed windows is not a
candidate: the span holds windows that did not confirm.

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

It can read `meetings`, `municipalities`, `council_members`, `agenda_items`,
`meeting_videos` and write only `transcripts`, `transcript_segments`,
`transcript_speakers`, `producer_heartbeats`, and `meeting_video_alignments`
(insert and update, no delete: a re-measure overwrites the row). The grants on
`meeting_videos` and `meeting_video_alignments` came with migration 042; a role
created before it needs the last two `GRANT` statements of that file run alone
by the database owner. The connection string lives only in `transcriber/.env` on
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
The Granicus listing exposes a `Duration` column per clip, which the adapter
stores in `meetings.duration_s` (migration 040). The worker task `non_meetings`
now hides the ones that fall on a day the city's calendar shows no council or
committee event (`docs/specs/meeting-types.md`, "Clips that are not meetings");
a Monday test on a day the calendar does list a committee is not hidden by it
(`D119`) and is still the operator's to hide by hand, as below.

What the producer does with them: the speech floor catches the silent ones as
`low_speech`; a mic-check clip with real speech passes and uploads a tiny
transcript (the plan 2 word-count floor, `TRANSCRIPT_MIN_WORDS`, sends it to `low_speech`).

What to do: hide the meeting from the admin meeting page (`/admin/meetings/<id>/hide`),
which sets `is_hidden`, `hidden_at`, `hidden_by`, and `hidden_reason = 'admin'`. The public page and transcript page
return 404, the producer skips it, and the hidden-meetings admin list keeps it
reversible. Existing transcript rows stay attached to the hidden meeting.
On 2026-10-11, 19 such meetings were hidden this way (all 18 unhidden Monday test
streams since 2025-10-28 plus the one-minute 2019-12-30 clip).

## Search cards: measurements

What the card stage and ranked search measured on real rows. The factory sessions of plan
`search-finds-what-was-said` (2026-11) had no API key and no production database, so they
filled in only what they could observe; the operator ran the rest on 2026-11-08, in the order
the plan's operator-steps row gave (`D86`, deleted in the commit that recorded them), and each
heading below carries that run with its date. Later backfill runs and golden checks go under
their headings the same way.

### Live smoke report and cost (step 1, before the merge)

Run 2026-11-08 at about 03:40Z by the operator in the plan's worktree at its merged head `f2dde8b`, with the worker's `ANTHROPIC_API_KEY`, the command above. `1 passed in 16.16s` (the one warning is `anyio`'s pytest-plugin deprecation, present on every run). The report line, whole:

    cards: meeting 1 transcript 1: 9 placed, 9 cards (5 discussed, 0 missing, 0 extra), details 12 kept 0 re-pointed 0 dropped, bounds 5 kept 0 dropped, 3 starts moved 20 s or more, 29058 in 2583 out, $0.0852
    9 cards, 12 spoken details, every quote found at its segment or beside it

No 400 from the API. One meeting of nine placed items cost $0.0852.

### Production counts (step 2, before the merge)

Run 2026-11-08 at about 03:55Z by the operator through `DATABASE_PUBLIC_URL`; the four queries are in `plans/completed/search-finds-what-was-said.md`, Context and Orientation. Each result beside its assumption:

- Birmingham meetings with a public transcript, by status: `compared 21`, `events_extracted 12`, `uploaded 9`, `speakers_resolved 7`, `needs_review 1` (50 in all; 33 past the events stage). Assumed: 50 to 150 in all, nearly all at `compared` or `events_extracted`; two in three are.
- Placed items in those meetings: `placed_items 589`, `meetings 41`. Assumed: about one item in five.
- `SELECT count(*) FROM agenda_items`: `61952`. Assumed: about 60,000.
- `pg_column_size(search_vector)`: `median_bytes 488`, `p95_bytes 666`. Assumed: a median no more than twice the scale check's 3.2 kB; production's is a seventh of it, so the scale check's timings (`rare-word 2 ms; three-word 339 ms; common-words 435 ms` at 60,000 synthetic rows, 2026-11-05) are an upper bound and no re-run was needed.

### Backfill log (steps 4 and 5, after the deploy)

Deploy: pull request #140 merged as `f54e986` on 2026-11-08 at about 04:05Z; `docket-web` then `worker` deployed from clean `main` by the operator (the web start applied migration 041; the live search page carried the new template at 04:20Z). Step 4, from the main checkout against `DATABASE_PUBLIC_URL` with the worker's key, 04:23Z:

    cards: 50 Birmingham meetings with a public transcript; 33 past the events stage; 0 with current cards; 33 waiting; 0 held; 0 failed
    cards: meeting 2224 transcript 29: 26 placed, 26 cards (26 discussed, 0 missing, 0 extra), details 33 kept 0 re-pointed 0 dropped, bounds 25 kept 1 dropped, 9 starts moved 20 s or more, 47698 in 6895 out, $0.1656
    cards: meeting 2231 transcript 28: 21 placed, 21 cards (21 discussed, 0 missing, 0 extra), details 33 kept 0 re-pointed 0 dropped, bounds 21 kept 0 dropped, 2 starts moved 20 s or more, 26788 in 5501 out, $0.1041
    cards: built 2, held 0, failed 0, stopped: none

(the dry run wrote no card and no run row). Step 5, each `--limit N` run with its date, last line, and the day's `transcript_cards` dollars from `/admin/ai`:

Run 1, 2026-11-08, after step 4 and before the worker's tick: `--limit 10` built meetings 2543, 2536, 2493, 2487, 2440, 2391, 2387, 2380, 2376, and 2373 (6 to 18 placed items each, every placed item a card, 0 missing, 0 extra, 0 details re-pointed or dropped, bounds dropped on three meetings: 2 on 2536, 1 on 2380, 1 on 2376), last line

    cards: built 10, held 0, failed 0, stopped: none

and the count straight after read `33 past the events stage; 10 with current cards; 23 waiting; 0 held; 0 failed`. The ten report lines' dollars sum to $0.94 (the largest meeting 2387 at $0.1668 for 15 items, 65,388 tokens in). The count on 2026-11-08 at 17:49Z, after the worker's daily tick, read `37 past the events stage; 12 with current cards; 25 waiting; 0 held; 0 failed`: the tick built two and four more transcripts had passed the events stage since the morning.

Run 2, 2026-11-08 at 18:04Z: `--limit 25` built the remaining 25 (meetings 2624, 2367, 2364, 2356, 2351, 2337, 2334, 2249, 2245, 2243, 2238, 2232, 2231, 2224, 1, 2, 4, 6, 8, 10, 12, 13, 15, 17, and 18; 2 to 28 placed items each, every placed item a card, 0 missing, 0 extra, 2 details re-pointed in all (one each on 2224 and meeting 1), 0 dropped, bounds dropped on three meetings: 1 each on 2367, 2238, and 2224), last line and the count straight after

    cards: built 25, held 0, failed 0, stopped: none
    cards: 50 Birmingham meetings with a public transcript; 37 past the events stage; 37 with current cards; 0 waiting; 0 held; 0 failed

The 25 report lines' dollars sum to $2.73 (927,252 tokens in; the largest meeting 2245 at $0.2083 for 14 items, 86,422 tokens in). The whole backfill of 37 meetings cost about $3.60 by the report lines, under one day's `AI_DAILY_BUDGET_USD` of $10. The 13 transcripts not yet past the events stage (`uploaded`, `speakers_resolved`, `needs_review`) get their cards from the worker's tick, two a day, as each passes it. Meeting 10 built 27 cards for 14 discussed items, the widest gap between placed and discussed in either run; `D87` (f) is read against rows like it.

### Golden check, before and after (step 6)

Before, 2026-11-05 01:27Z, against production as it was before this plan's deploy (every-word
matching, no cards, no nested moments), run by the plan's first session:

    golden: 3 of 45 targets on the first page (top 3: 3, top 10: 3, top 20: 3); 0 with spoken moments; 42 queries

After the deploy, before any card was built (ranked matching and placement-based moments alone), 2026-11-08 04:27Z, from a development checkout at `398a6a4`:

    golden: 15 of 45 targets on the first page (top 3: 8, top 10: 14, top 20: 15); 15 with spoken moments; 42 queries

Items 58824 and 58874 were not on the first page of `new late night ordinance` (both `place -`); the common-word search `curl -s -o /dev/null -w '%{time_total}\n' 'https://docket.pub/search?q=city+ordinance+resolution+contract&city=birmingham'` took 0.88, 0.68, and 0.69 seconds over three tries.

After the backfill, 2026-11-08 at 18:08Z, with 37 meetings carrying cards, from the main checkout at `398a6a4`:

    golden: 34 of 45 targets on the first page (top 3: 28, top 10: 33, top 20: 34); 34 with spoken moments; 42 queries

Item 58824 is first for `new late night ordinance` with three spoken moments, and the live page carries its nested lines linking into meeting 2224's transcript (`/al/birmingham/meetings/2224/transcript/#t-309`, `#t-310`, `#t-313`, read with `curl` at 18:12Z); item 58874 is not on that page (`place -`), as the spike predicted, since neither its discussion nor its agenda text holds "late" or "night" (`D87` (a)). The eleven targets still off the first page are all paraphrase or spoken queries whose words name neither the card nor a segment (`help for families of disabled kids`, `kids crawling under trains west side`, `never knew birmingham had a port`, `downtown park place eatery serving alcohol`, `ski jump exit highland avenue`, `house illegally split into two apartments`, `land use overhaul west side neighborhoods`, `owner says city stealing his property`, `outside help fixing city software system`, `911 agency gives city used suv`, and `new late night ordinance` for 58874). The common-word search `city ordinance resolution contract` took 0.66, 0.68, and 0.66 seconds (three `curl` runs at 18:12Z; 0.61 for the late-night query), against 0.88 and 0.6 before the cards. Whole-plan acceptance, read as `D86` asked: more targets on the first page than 3 of 45 (34), a nonzero count with spoken moments (34), item 58824 on the first page with a nested transcript line (yes, first), and 58874 recorded either way (not on the page).

What to record on each later run: the summary line of
`venv/bin/python scripts/golden_search.py --base-url https://docket.pub` once after the
deploy with no cards built (ranked matching and placement-based moments alone) if convenient,
and once after the backfill; whether items 58824 and 58874 are on the first page of
`new late night ordinance`; where the excerpt on `/al/birmingham/items/58824/` begins (it
should be near 1:45:10); and the time of one common-word search
(`curl -s -o /dev/null -w '%{time_total}\n' 'https://docket.pub/search?q=city+ordinance+resolution+contract&city=birmingham'`).

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
- 2026-11-06: timed video links went to production (pull request #141, merge
  `9438243`; the row was `D94`). Deployed `docket-web` then `worker` from the WSL
  checkout on the Legion; both reported `COMMIT_SHA` `94382431d0cb…`; migration
  042 applied on start. The two `GRANT` statements for `meeting_videos` and
  `meeting_video_alignments` run by the owner; `has_table_privilege(...,
  'INSERT')` printed `t`. Query 6 printed `0 | 0 | 0`;
  `scripts/correct_agenda_chapter_ids.py --city birmingham` dry run and write
  both listed 24 meetings and 1,434 rows (8 WARNING lines naming 12 items with
  no cue point, meetings 3186, 3184, 2536, 2387, 2364, 2351, 2249, 2237); the
  count after the write printed `0 | 0`. The first transcriber run after the
  deploy measured nothing: its heartbeat read `producer_version 0.4.0`, the
  image from before the merge (the build had not taken); `docker compose build`
  again (490 s), `python -c "import transcriber; print(transcriber.__version__)"`
  in the image printed `0.5.0`, and `--limit 0 --measure-limit 20 --max-hours 3`
  measured 20 recordings (2026-10-27 back to 2026-06-16) in under an hour:
  18 `passed` (scores 12.3 to 152.5), 2 `rejected` (meeting 2387 `conflict`,
  meeting 2373 `windows`; both with a runner-up near the score, `D98`), 0
  `failed`, all at method version 2. Meeting 3184, clip 2026, `FR84h22hQvA`:
  offset 635.48 s, covers 635.5 to 3,958.7 s, score 23.6, the README's example
  line exactly. Clip 2017 (meeting 2609): offset 3,232.20 s, covers 3,472.2 to
  5,033.2 s, as the row expected; clip 1831 was not among the 20 and waits for
  the backlog, 339 remaining. In a browser, item 64 of meeting 3184 opened
  `FR84h22hQvA` at `t=1620s` (27:00) on both of its "Watch this vote" links,
  where the transcript has item 64 beginning; the vote shown there as prevailing
  is item 3's, filed under item 64 by the vote matcher (issue #142, not a
  video-links fault). The yt-dlp warning about a missing JavaScript runtime
  printed once per download and stopped none (`D85`).
- 2026-11-12: the backlog's state read from the laptop (query 4), after the
  backlog runs of 2026-11-07: 171 of the 359 recordings measured, newest first,
  back to 2023-01-31; 108 `passed` (scores 12.3 to 188.5), 60 `rejected`, 3
  `failed`. The rejections by reason: `conflict` 24, `windows` 23, `margin` 5,
  `score` 5, `no_window` 3. Read against the runner-up: about 33 are recordings
  that match at two offsets (runner-up 35 percent or more of the score, the
  `D98` shape; meetings 157 to 168 of early 2023 all have it, with offsets near
  2,000 s and confirmation starting half an hour or more into the stream), about
  12 are strong single matches lost to one conflict window or the 60 percent
  share (meeting 2238: 34 of 40 windows, score 158.9, runner-up 4.7), 8 score 4
  to 7 against an offset of hours and are probably the wrong video attached
  (meeting 14, 2026-02-24, `rPj70c-TJlY`, score 5.1, offset -6,417.8 s; the
  three `no_window` rows and four `score` rows look the same), and the 3
  `failed` are Granicus clips 1662, 1666, and 1667 (2023), which return 404 or
  403 and are retried every run. Meetings 71 and 78 each have two uploads with
  identical measurements. `D98`'s trigger has fired. One override by the
  statement above: meeting 15 (2026-02-17, clip 1950, `N_-LpyP62Lo`, row 832),
  rejected `windows` with 9 of 16, offset 948.84 s, span 948.84 to 3,648.84 s,
  which is exactly 9 windows, set to `passed` with reason `operator`. Checked in
  a browser: item 687's "Watch this vote" opens YouTube at `t=2360s`, and the
  transcript page's item links read 13 on YouTube and 7 on Granicus.
