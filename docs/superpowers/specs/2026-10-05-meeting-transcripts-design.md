# Meeting transcripts and minutes comparison

**Status:** Design — awaiting user review
**Filed:** 2026-10-05
**Surface:** New `transcriber/` desktop producer package; new worker task `transcript_pipeline`; migration 035 (seven tables); new AI stages under `docket/ai/transcripts/` with a 200-series prompt family; public transcript page, search result type, admin discrepancy queue and speaker correction; public "Minutes vs. Video" block
**Severity:** High — first speech-to-text pipeline for the site; first automated check of the official record against what was actually said

---

## TL;DR

docket.pub indexes Birmingham council video but has no transcripts. Granicus publishes no captions for Birmingham (the VTT endpoint is empty), so a real transcript means running speech-to-text ourselves. The user's Lenovo Legion desktop (RTX 5070 Ti, 16 GB VRAM) does the GPU work inside Docker on WSL2 and uploads raw, timestamped, speaker-clustered segments to Railway Postgres. The existing Railway AI worker then does all the thinking: resolves speaker clusters to people, extracts an event timeline from both the transcript and the official minutes, and compares the two. Discrepancies are proposed by the pipeline, reviewed by the admin, and only approved ones are shown publicly under the site's honesty-protocol framing.

The headline consumer is the comparison. A hand-verified pilot on the 2/17/2026 meeting, Item 15 (ALEA / Alabama Power CJI agreement), shows the minutes placing the executive session after the vote when the video shows it before, and citing a different statutory reason than the one the city attorney stated on camera. The pipeline must reproduce that finding from raw audio and the minutes PDF.

Secondary consumers, all cheaper and shipped first: a public, searchable, timestamped transcript per meeting; attributable quotes per item; transcript-informed AI summaries later.

---

## Goals

1. Every Birmingham council meeting with a Granicus video gets a speech-to-text transcript with timestamps and speaker labels resolved to council members where confident. New meetings are transcribed weekly without operator intervention beyond the desktop being on.
2. Transcripts are public, searchable, labeled machine-generated, and linkable to the turn.
3. For every meeting with both a transcript and minutes, the pipeline proposes discrepancies between what was said and what the minutes record, in priority order: vote outcomes, omissions and additions, motion and amendment wording, sequence, and who acted.
4. No discrepancy reaches readers without a verbatim quote from each side it cites and without a human approving it.
5. The desktop stays a normal Windows gaming PC. All desktop work runs in one Docker container with a start-and-stop command. Nothing is installed on Windows itself.
6. Every LLM call inherits the existing AI worker's budget cap, cost telemetry, retry handling, and admin dashboard.

## Non-goals

- Other municipalities. Only Birmingham has video URLs today. The design is city-agnostic but no other adapter is touched.
- Hosted transcription providers (Deepgram, AssemblyAI). The upload contract allows swapping one in later; none is wired now.
- Cloud object storage for audio or raw outputs. Postgres on Railway is the source of truth; the GPU can regenerate anything else.
- Semantic (vector) search. Phase 2, on pgvector 0.8.6, which is available but not installed on the Railway Postgres.
- Cross-meeting speaker identification by voice. Phase 2. The embeddings are stored from day one so the labeled data accumulates.
- Message Batches mode for the new stages. The request builders are shaped for it; the toggle lands only if the pre-2021 backfill is approved.
- Exact-second video seeking. Granicus's player ignores time fragments. Phase 1 links to the agenda chapter and shows the timestamp. A spike in the plan tests the two upgrade paths.
- Transcript-informed rewrites of existing AI item and meeting summaries. Follows once transcripts exist; separate spec.

---

## Decisions reached in brainstorming

| ID | Decision |
|---|---|
| A | Architecture B: desktop does GPU-only work and uploads raw segments; Railway worker runs every LLM stage |
| B | Speakers are resolved to people provisionally, with a confidence score and a manual-correction shield |
| C | Discrepancies are proposed by the pipeline, approved by the admin, and public only when approved, with honesty-protocol labeling |
| D | Raw transcript is fully public, labeled machine-generated, timestamped, with per-turn anchors and search |
| E | Search is Postgres full-text plus trigram in phase 1 (pg_trgm 1.6 already installed); pgvector in phase 2; stay on Railway Postgres |
| F | Backfill order: current council era first (seated 2025-10-28, about 60 meetings), then 2021 to 2025 (about 300), pre-2021 decided after seeing results |
| G | Models: Sonnet 5.5 for speaker resolution and event extraction, Opus 5.5 for comparison. Haiku 4.5 for extraction is an A/B experiment, not a default |
| H | Structured outputs instead of forced tool choice, which the 5.5 models reject with a 400 |
| I | Omission is defined narrowly by a shared materiality rule, not as "anything discussed but not minuted" |
| J | Vote-outcome comparison is deterministic code against existing `votes` rows; no model involved |

**Interpretation flag on F.** "Current council era" was read as the council seated October 28, 2025. If the user meant 2021 onward as one batch, only the `--since` cutoff in the producer changes.

---

## Pilot evidence

Run on the user's Premiere export of the Item 15 window from the 2/17/2026 meeting (meeting id 15, Granicus clip 1950, 530.6 s of video), transcribed locally with whisper.cpp `ggml-small.en` on an M1 Pro in 27 s wall-clock. Files are in `data/transcript_pilot/` and move to `tests/fixtures/transcript_pilot/` in the first implementation task. Granicus index points for the item: open 3309 s, motion 3393 s, vote 3847 s.

What the video shows, in order:

1. The clerk reads the ordinance (CJI access security agreement, ALEA, Alabama Power, City of Birmingham). A motion and second are on the floor.
2. Councilor O'Quinn asks for a layman's summary and notes the agreement itself is not in the packet.
3. The city attorney explains the agreement verifies Alabama Power's license plate reader cameras give access to the Alabama criminal justice information system and binds them to its rules.
4. The city attorney recommends executive session "under 36-25A-7(a)(4) to discuss security plans and measures." Someone moves; a voice vote follows.
5. Recess of roughly fifteen minutes (silence in the audio), roll call on return.
6. The chair notes the motion and second are still on the floor, calls the vote, and announces "Item 15 passes."

What the minutes record: the ordinance adopted, then a motion by O'Quinn seconded by Tate to go into executive session "to discuss with legal counsel the legal ramifications of and legal options for pending litigation, controversies not yet litigated, but imminently likely to be litigated" (the §36-25A-7(a)(3) ground), a roll-call vote, recess at 10:20, reconvene at 10:40.

Expected pipeline output for this meeting: a `sequence` discrepancy (executive session before the vote on video, after it in the minutes) and a `wording` discrepancy on the executive session reason ((a)(4) security plans stated versus (a)(3) pending litigation recorded), both `material`. The O'Quinn "not in the packet" remark and the attorney's LPR explanation qualify as `statement` events under the materiality rule and may surface as an `omission`. Who moved the executive session is unclear on the audio and should produce at most a low-confidence `speaker` candidate.

The small model misheard "ALEA" as "aliyah" and "Vasa" as "Vassa." The roster-seeded initial prompt in the producer and the worker's name-resolution stage both exist to fix this class of error.

---

## Section 1: Data model

One migration (035), seven tables. Minutes text is not stored today, only vote snippets, so the comparison captures it.

### Tables

**`transcripts`**, one row per meeting (unique on `meeting_id`). Pipeline status machine for the whole flow. Columns: `meeting_id` FK to `meetings`, `status`, `version` integer, `engine`, `asr_model`, `diarization_model`, `audio_duration_s`, `speech_ratio`, `word_count`, `producer_host`, `claimed_at`, `uploaded_at`, `audio_sha256`, `raw_output_path` (desktop path of the producer JSON, for debugging), per-stage `attempts`, `last_error`, `last_attempted_at`, `compare_skipped_reason`, `needs_review_reason`.

Status values, in order: `claimed`, `audio_fetched`, `transcribed` (JSON on disk, not yet uploaded), `uploaded`, `speakers_resolved`, `events_extracted`, `compared`. Side states: `failed`, `needs_review`, `low_speech`. There is no dead state: minutes capture runs inside event extraction, and a meeting with no minutes stops at `events_extracted` with `compare_skipped_reason = 'no_minutes'`.

**`transcript_segments`**, the transcript itself. `transcript_id` FK with `ON DELETE CASCADE`, `seq`, `start_s`, `end_s`, `text`, `cluster_label` (anonymous diarization label), `speaker_id` nullable FK to `transcript_speakers`, `agenda_item_id` nullable FK, `assignment_method` (`index_point`, `event`, `manual`), `avg_logprob`, `no_speech_prob`, `is_silence` boolean for gaps longer than a minute (the recess detector). Generated `search_vector tsvector` over `text` with a GIN index; trigram GIN index on `text`; index on `(transcript_id, seq)`; index on `agenda_item_id`.

Word-level timestamps are deliberately not stored in Postgres. Nothing in phase 1 reads them (there is no embedded player), and at roughly 20,000 words per meeting they would be the largest column in the database. They stay in the producer's JSON archive on the desktop and can be loaded later if an embedded player ships.

The resolved speaker name is deliberately not in the search vector. Speaker search is a join filter (`speaker:` token and facet), which returns segments spoken by a person rather than segments mentioning them, and keeps a correction from rewriting thousands of GIN entries.

**`transcript_speakers`**, one row per speaker cluster per meeting, keyed to `meeting_id` and `cluster_label` so it survives a segment re-run. `council_member_id` nullable FK, `display_name`, `role` (`council`, `mayor`, `clerk`, `attorney`, `staff`, `public`, `unknown`), `confidence`, `method` (`roll_call`, `addressed_by_chair`, `llm_inference`, `manual`), `is_manual` boolean (the shield, same idea as `vote_agenda_items`), `embedding` float array from the diarizer (phase 2 similarity input), `remapped_from_version`, `needs_review` boolean.

**`minutes_texts`**, one row per meeting: `meeting_id` FK, `source_url`, `pdf_sha256`, `text`, `page_offsets` JSONB (character offset where each page starts), `extracted_at`. Filled from the existing minutes PDF download path on first need. A changed `pdf_sha256` on re-ingest re-extracts and re-runs comparison; URL change is the secondary trigger.

**`meeting_events`**, the event timeline from both sides. `meeting_id` FK, `source` (`transcript`, `minutes`), `seq`, `event_type` (fixed set, Section 4), `scope` (`item`, `consent_block`, `meeting`), `agenda_item_refs` integer array (agenda item ids), `actor_member_id` nullable FK, `actor_text`, `summary`, `detail` JSONB (typed per event type), `start_s` nullable (transcript), `page` and `char_offset` nullable (minutes), `prompt_version`, `segment_id` nullable FK for transcript events.

**`producer_heartbeats`**, one row per desktop host: `host` primary key, `last_seen_at`, `last_status`, `last_meeting_id`, `producer_version`. The producer upserts it at startup, after every meeting, and on clean exit. The worker's daily tick compares it against the newest meeting with video and no transcript (Section 3, alerting).

**`minutes_discrepancies`**, the product. `meeting_id` FK, `category` (`vote_outcome`, `omission`, `addition`, `wording`, `sequence`, `speaker`), `severity` (`material`, `minor`), `title`, `description`, `admin_title` and `admin_description` nullable (edits never overwrite the model text), `transcript_event_id` and `minutes_event_id` both nullable with a CHECK that at least one is set, `transcript_excerpt`, `transcript_start_s`, `minutes_excerpt`, `minutes_page`, `citation_match` (`exact`, `fuzzy`, `missing`), `confidence`, `origin` (`aligner`, `model_initiated`), `review_state` (`proposed`, `approved`, `rejected`, `dismissed_by_model`, `stale`), `reject_reason`, `reviewed_at`, `reviewed_by`, `review_note`, `prompt_version`, `agenda_item_id` nullable FK (denormalized for the item page).

Rows with `citation_match = 'missing'` cannot be approved until a reviewer attaches a citation. Only `approved` rows render publicly.

### Design rules

- Nothing public reads `meeting_events`. It exists so the comparison is explainable and re-runnable.
- Re-transcribing a meeting bumps `transcripts.version` and replaces segments by cascade. Speakers and discrepancies key to `meeting_id`, not segment ids, so manual work survives.
- **Diarization re-run remap.** Before the cascade, snapshot every `is_manual` speaker's time intervals from the old segments. After the new segments load, the rule works from the new cluster's point of view, not the old speaker's: any new cluster with at least 80 percent of its speaking time inside one manual speaker's old intervals inherits that speaker's assignment. A newer diarizer that breaks one monologue into several clusters therefore yields several clusters all mapped to the same person, which the design already treats as normal, instead of a wave of dropped assignments. A new cluster that straddles two old speakers inherits nothing and gets `needs_review`; a manual speaker that no new cluster inherits keeps its row, unlinked, with `needs_review`. Record `remapped_from_version`. Never silently drop a manual assignment.
- **Index point drift.** Granicus index points are the clerk clicking a button, sometimes late (the pilot shows Item 15 opening at 50:07 and Item 12 at 50:21). They set the initial `agenda_item_id` with `assignment_method = 'index_point'`. Confident `item_opened` events from extraction re-assign segments with `assignment_method = 'event'`.
- **Storage.** Roughly one million segments for the full archive. Without word-level timestamps, segment text is about 120 MB, the tsvector and trigram indexes together about three times that, so on the order of 500 to 700 MB total with indexes against today's 307 MB database. The current council era is about a tenth of that. The scale check in Section 6 measures the real figure before the backfill runs.
- **Dedicated role.** A `transcriber` Postgres role with INSERT, UPDATE, and DELETE on `transcripts`, `transcript_segments`, `transcript_speakers`, `producer_heartbeats` and SELECT on `meetings`, `municipalities`, `council_members`, `agenda_items`. The desktop never holds the app's credentials. It connects through Railway's public TCP proxy, which is the same endpoint the laptop already uses for operations, with `sslmode=require` and a long random password. Railway offers no private mesh to a residential desktop, so the mitigation is the narrow role and TLS, not network isolation.

---

## Section 2: Desktop producer

A standalone package at `transcriber/` in the docket-pub repo with its own Dockerfile and requirements. It shares nothing with the Railway image except the upload contract. The Railway build never installs torch.

### Runtime on the Legion

- Docker Desktop with the WSL2 backend, container started with GPU access. Image: NVIDIA CUDA 12.8 runtime base, Python 3.11, faster-whisper (CTranslate2), WhisperX for word alignment, pyannote 3.1 for diarization. A named volume caches models (about 5 GB, downloaded once). The archive folder is a host bind mount visible in Explorer.
- `.wslconfig` written by the setup runbook: 16 GB memory ceiling and `autoMemoryReclaim=gradual`, so Windows keeps half the machine during a weekend run.
- One `.env`: transcriber database URL (`sslmode=require`), Hugging Face token, work directory, backfill cutoff date. The work directory and the archive folder are both on the host bind mount, so audio is written to and deleted from NTFS directly. Nothing large ever lands inside the WSL2 virtual disk, which grows but never shrinks on its own.
- The runbook also sets the Windows power plan to never sleep while plugged in and to allow wake timers, since a sleeping desktop is the most likely cause of a quiet week.
- Start and stop by hand with one `docker compose run` command, or from a Task Scheduler entry at login. Flags: `--since`, `--limit`, `--max-hours` (stop cleanly), `--dry-run` (write JSON, touch nothing). Ctrl-C finishes the current meeting and exits.

### Per-meeting flow

0. **Heartbeat.** Upsert `producer_heartbeats` for this host at startup, after every meeting, and on exit.
1. **Claim.** One query selects the newest Birmingham meeting with a video URL, a date on or after the cutoff, and either no `transcripts` row or a row in `claimed`/`audio_fetched` older than six hours (zombie release lives in the claim query, no restart needed). Insert or update the row as `claimed` with host and time. A row already in `transcribed` is claimed straight to the upload step, so no GPU time is repeated for a database hiccup.
2. **Fetch audio.** Resolve the Granicus player page to the HLS stream URL using the resolver the OCR pipeline already has, pulled into a shared helper. ffmpeg with the browser user agent (PR #96) extracts 16 kHz mono PCM, audio only. Serial, with a polite delay, three attempts, then `failed` with the error. Record `audio_sha256`.
3. **Transcribe.** faster-whisper large-v3, batched, word timestamps on, built-in Silero VAD filter on (the actual cure for silence hallucination). Initial prompt built from that meeting's roster names first, then a short fixed local vocabulary (ALEA, CJI, APC, BJCC, Woodlawn, and so on), under a hard 224-token budget with a unit test; the builder refuses to build a prompt that would truncate. Record `speech_ratio` as telemetry. The `low_speech` guard exists to catch a dead or silent stream, so it is an absolute floor, not a percentage: a meeting with under three minutes of detected speech is marked `low_speech` instead of uploaded. A ten-minute emergency session with two minutes of business and eight of waiting for quorum is still uploaded. Silence gaps over a minute become `is_silence` segments.
4. **Diarize.** pyannote assigns cluster labels per word, then per segment by majority, and emits one embedding per cluster. No names here.
5. **Write output.** One JSON file per meeting in the archive folder: meeting id, version, engine and model names, duration, speech ratio, checksum, segments, speakers with embeddings. This file is the contract. Status becomes `transcribed`.
6. **Upload.** One transaction as the `transcriber` role: delete any segments for this transcript version, COPY segments, upsert speaker clusters, set `uploaded`. All or nothing, and idempotent on replay. Then delete the audio and keep the JSON.

### VRAM

Large-v3 fp16 is about 3 GB and pyannote 3.1 about 1 to 2 GB; both stay resident on the 16 GB card. A CUDA out-of-memory on either step falls back to unload-and-reload sequencing for that meeting. If the fallback fires more than once per batch it logs loudly.

### Throughput

Roughly 5 to 8 minutes wall-clock per 2.4-hour meeting, diarization the larger share. The current council batch is one evening; 2021 to 2025 is a weekend of background time. Audio download is the real bottleneck and is kept serial on purpose.

### Known risk, verified first

The RTX 5070 Ti is Blackwell. CTranslate2's prebuilt wheels may not ship kernels for it. The first implementation task is environment bring-up on the Legion with a 30-second clip. Fallback inside the same container is WhisperX's PyTorch path on the CUDA 12.8 build, slower but supported. The engine is a one-line swap in the producer.

---

## Section 3: Worker stages on Railway

Three LLM stages plus deterministic steps, run in order by one new cron task, each claiming `transcripts` rows by status with the OCR claim pattern (CTE, `FOR UPDATE SKIP LOCKED`, `ORDER BY meeting_date DESC`). Every LLM call goes through the existing AI client, writes an `ai_runs` row, and respects `AI_DAILY_BUDGET_USD`. Prompt versions use a new 200-series family so the item and meeting dispatcher gates never see them.

| Stage | Input | Model | Output | Status after |
|---|---|---|---|---|
| Speaker resolution | Roster for that date; roll-call call-and-response pairs; segments where the chair addresses someone by name and the next cluster to speak; a sample of utterances per cluster spread across the meeting | Sonnet 5.5 | `transcript_speakers` rows with name, role, confidence, method | `speakers_resolved` |
| Event extraction | (a) transcript with speakers, agenda list, index points; (b) minutes text captured first if missing | Sonnet 5.5, one call per side | `meeting_events` for both sources | `events_extracted` |
| Comparison | Aligner candidates, both timelines, excerpts (judge); full texts (hunter) | Opus 5.5, two calls | `minutes_discrepancies` as `proposed` | `compared` |

### Speaker resolution signals

Diarization fragments monologues under cross-talk and sometimes merges two voices, so the resolution stage never relies on a cluster's first utterances alone. Signals in priority order: roll-call pairs (clerk reads a name, the next cluster answers "here" or "present"), the chair addressing a member by name followed by that cluster speaking, self-identification, then a sample of utterances spread across the whole meeting. The "next cluster to speak" is never trusted blindly. A roll-call response counts only if the next utterance is short and matches an expected response ("here," "present," "yes," "no," "aye"). A floor-yield counts only if the next utterance is substantive, more than a few words, and reads as the addressed member speaking; a cough, a mic bump, or a two-word interjection is skipped and the following cluster is considered instead. The prompt carries this rule explicitly and asks the model to quote the utterance it relied on. High confidence requires two independent signals agreeing (for example a roll-call pair and a later address by the chair); a single signal caps at medium confidence. Two clusters resolved to the same member is normal and is how a fragmented speaker is merged. A cluster that mixes two speakers gets low confidence and displays as "Speaker N"; splitting it at segment level is phase 2.

### Rules that hold across stages

- **Structured outputs.** The current client forces tool choice, which Opus 5.5 and Sonnet 5.5 reject. New stages use `output_config.format` with a JSON schema, built as a sibling of the existing call pattern in `client.py`. Per the house rule, a live smoke test against both models runs before the first prompt is written. Stop reason is checked: `refusal` or `max_tokens` fails the row rather than parsing a truncated document.
- **Hallucination guard.** Every discrepancy must quote an excerpt from each side it cites. The model is shown the same extracted text the guard matches against, never the PDF itself, and the prompt instructs it to quote the source exactly as shown, artifacts included, rather than cleaning it up. After the model returns, the worker normalizes both sides (Unicode NFKC so ligatures such as "ﬁ" become "fi", strip soft hyphens, collapse whitespace, unify quotes, join hyphenated line breaks, lowercase) and substring-matches; a second pass does a fuzzy window match at a high threshold for what the normalizer misses, such as a stray space inside a word. Minutes are extracted without layout mode, since they are single-column and layout mode is what introduces column breaks. The rate of `missing` citations is tracked per prompt version in the admin AI panel; above 10 percent over the first ten meetings the normalizer and prompt are tuned before the queue is used in earnest. `citation_match` records which pass matched. A discrepancy that loses an excerpt is kept with `citation_match = 'missing'` and downgraded confidence, visible in the queue, not approvable until a reviewer attaches a citation.
- **Vote outcomes are deterministic.** Transcript `vote` events carry the tally as spoken. Code compares them against existing `votes` rows (minutes and OCR) and emits `vote_outcome` discrepancies directly.
- **Failure states.** Per stage: attempts, last error, 24-hour backoff, three-attempt cap, then `failed`. Schema validation failures, token-ceiling breaches, and tripped candidate caps go to `needs_review` immediately with a reason. Both are visible in the admin AI panel and never block the queue.
- **Token ceiling.** Sonnet 5.5 and Opus 5.5 have 1M-token windows. Council speech runs about 9,000 words an hour, so a twelve-hour budget hearing is roughly 110,000 words or 150,000 tokens, and a 300-page minutes packet about 150,000 more. The configurable ceiling defaults to 500,000 tokens, which no realistic meeting reaches; it guards against runaway cost from a bad input, not against long meetings. The worker counts tokens before each call and marks a breach `needs_review`. No chunking is built unless that fires.
- **Shared materiality fragment.** One prompt fragment defines what counts as material (a commitment, a dollar figure, a legal position or statute cite, a stated reason for a decision, a procedural ruling). It is included verbatim in the transcript extraction prompt and the comparison prompt. Extraction captures at a lower threshold; comparison filters. The fragment carries worked examples from the pilot, positive (the attorney's explanation of what the CJI agreement gives Alabama Power access to; O'Quinn's point that the agreement is not in the packet) and negative (a clarifying question answered with a procedural fact). Because the surveillance and data-sharing items this site cares about most are exactly where floor debate and minutes diverge, the first ten reviewed meetings also produce a labeled set of material statements, and extraction recall against that set is reported alongside the Haiku A/B. The hunter pass, which sees the full texts, is the safety net for statements extraction missed.
- **Request builders return parameter dicts.** Same shape the Batches API takes. Synchronous in phase 1; a batch submit-and-poll path behind an environment toggle reuses `ai_batches` if the larger backfill is approved (its `stage` CHECK constraint would be extended then).
- **Re-runs are per stage.** Bumping a stage's prompt version resets that stage and later ones only.
- **Concurrency.** The worker processes meetings serially, one stage call in flight at a time, with a per-tick cap (default 5 meetings). One 100K-token request a minute sits well inside the account's tokens-per-minute limit, and the client's existing retry path honors `retry-after` if a 429 does arrive. Backfill speed is governed by raising the per-tick cap, not by parallelism.

### Cost, synchronous

About $0.50 per meeting, dominated by the Opus comparison at roughly 90K input tokens plus the hunter pass. Current council batch about $30; 2021 to 2025 about $150; full archive under $500. Batch mode would halve these.

### Haiku experiment

Event extraction is judgment over long context, and Haiku 4.5 has the tightest window. It is not the default. The plan includes a task: run Sonnet 5.5 and Haiku 4.5 on the first ten meetings, compare event timelines against each other and against the review outcomes. If Haiku matches, it takes the stage.

### Scheduling

New `transcript_pipeline` task in `worker/scheduler.py` at 10:00 America/Chicago, after vote matching, processing a configurable number of meetings per tick through all stages.

### Alerting

A single env-gated `ALERT_WEBHOOK_URL`. The worker posts a small JSON payload on a transcript entering `failed` or `needs_review`, on a tripped candidate cap, and once a day when the desktop looks stalled: a Birmingham meeting with video older than seven days has no transcript and no `producer_heartbeats` row is newer than seven days. The desktop is not required for the site to function, but a quiet stall should not go unnoticed for a month. Slack and Discord both accept the shape. This is the first active alert in the codebase; the precedent is video OCR being silently broken since June.

---

## Section 4: Comparison method

### Event schema

Both extraction calls emit the same shape. `event_type` is a fixed set:

| Type | `detail` fields |
|---|---|
| `item_opened` | — |
| `item_deferred` | `action` (`table`, `postpone`, `carry_over`), `to_date`, `as_stated` |
| `consent_amendment` | `action` (`pulled`, `added`), `items`, `requested_by` |
| `motion` | `action` (`approve`, `deny`, `table`, `postpone`, `amend`, `substitute`, `other`), `mover`, `seconder`, `as_stated` |
| `second` | folded into `motion.seconder`; standalone only when the second is contested |
| `amendment` | `what_changed`, `mover`, `as_stated` |
| `vote` | `result`, `yeas`, `nays`, `abstentions`, `roll_call_names`, `method` (`roll_call`, `voice`, `unanimous_consent`) |
| `executive_session_motion` | `stated_reason`, `statute_cite`, `mover`, `seconder` |
| `recusal` | `member`, `stated_reason` |
| `procedural_ruling` | `kind` (`point_of_order`, `appeal`, `suspend_rules`, `attorney_ruling`), `ruling` |
| `roll_call` | `present`, `absent` |
| `recess`, `reconvene`, `adjourn` | `clock_time` when stated |
| `public_comment` | `speaker_text`, `topic` |
| `statement` | `kind` (`commitment`, `dollar_figure`, `legal_position`, `stated_reason`, `material_fact`), `as_stated` |

Every event also carries `scope` (`item`, `consent_block`, `meeting`) and `agenda_item_refs`. A consent motion and vote carry every item id in the block. Invocation, pledge, and ordinary clarifying exchanges are not extracted.

### Alignment, deterministic first

Code pairs the two timelines before any model judges:

1. **Group by agenda item references**, not by contiguous time. An item opened, paused for another item, and reopened an hour later is one group with two `item_opened` events.
2. **Consent handling.** The published `is_consent` flags are only the starting point, because councils amend the consent agenda on the floor. For each source the aligner computes an effective consent block: published consent items, minus items in `consent_amendment` events with `action = 'pulled'`, plus items `added`. The consent motion and vote satisfy the effective block for that source, and a pulled item becomes its own group with its own expected motion and vote. The two effective blocks are then compared: an item in one block and not the other is a candidate in its own right (pulled on video, still inside consent in the minutes, or the reverse). Without this step a pulled item would be marked satisfied by the consent vote and its later debate and vote would cascade into false sequence and addition candidates.
3. **Within a group, pair by type and order.** Transcript event with no counterpart: omission candidate. Minutes event with no counterpart: addition candidate. Pair with differing details: mismatch candidate (`wording`, `vote_outcome`, `speaker`).
4. **Across the meeting, longest common subsequence** over paired events. Pairs out of order are `sequence` candidates. The pilot's executive session before versus after the vote falls out here.
5. **Actors** are compared as `council_member_id`s. Transcript actors come from speaker resolution (who was speaking), minutes actors from roster matching of typed names with a fuzzy fallback for typos. No phonetic matching on actor text.
6. **Vote tallies** are compared against `votes` rows directly. The baseline is the minutes-derived rows (`source = 'minutes_text'`), which exist for every year back to 2008. Video OCR rows exist only for 2026 and act as corroboration where present; their absence is not a discrepancy and not a failure.

### Model judgment, two calls

**Judge (Opus 5.5).** Receives the candidate list, both timelines, and windowed excerpts around each candidate (transcript segments around `start_s`, the minutes paragraph around `char_offset`). For each candidate it decides real or not, assigns category and severity, writes title and description, and quotes the excerpts the guard verifies. Rejected candidates are stored as `dismissed_by_model` with the reason, so the admin can audit the model's judgment.

**Hunter (Opus 5.5).** Receives both full texts and both timelines, tasked only with finding discrepancies the aligner missed. Its output is flagged `origin = 'model_initiated'`. It runs on every meeting at first, because its hit rate measures whether the aligner is good enough; it becomes sampled once that rate is known.

### Severity

`material` when a discrepancy changes a legal basis, an outcome, who acted, a recusal, or the order of a vote relative to a closed session. `minor` for wording differences that leave meaning intact. The queue sorts material first.

### Candidate cap

A meeting producing more candidates than a configurable cap (default 40) is held as `needs_review` with a single queue row, since that pattern usually means a timestamp offset or hallucination, not forty real problems.

### Re-comparison

A changed `minutes_texts.pdf_sha256` re-extracts the minutes side and re-runs comparison. The transcript side does not change, so transcript event ids are stable across the re-run and reconciliation is deterministic:

- Every existing `approved` or `proposed` row is set to `stale` first.
- Each new candidate is matched to a stale row by category plus `transcript_event_id`. Additions, which have no transcript event, match by category, agenda item, and normalized minutes excerpt similarity above a threshold.
- A matched stale row is updated in place with the new minutes excerpt and page, set back to `proposed` with `previous_review_state` recorded, and badged "re-review" in the queue. No duplicate row is created.
- An unmatched stale row stays `stale`. That means the corrected minutes no longer show the discrepancy, which is itself worth a look, so stale rows remain visible in the admin queue under their own filter.
- Stale rows never render publicly.

---

## Section 5: Web surfaces

### Public transcript page

`/meetings/<id>/transcript`, a full server-rendered page. The tab on the meeting page is a plain link that HTMX intercepts with `hx-get` and `hx-push-url`, the pattern the category landing page already uses, so crawlers and direct links always get rendered text. Speaker turns with resolved names (clusters under the confidence threshold display as "Speaker N"), a timestamp per turn, an anchor per turn, and `#item-N` anchors at each item's opening matching the meeting page. A standing label names the model, says the transcript is machine-generated, and links to the methodology page. Jump links go to the Granicus chapter via the existing `chapter_url` helper with the exact timestamp shown beside them.

### Item pages

A "From the video" block: the first few turns of the item's transcript span (bounded by `item_opened` events), with "Read the full discussion" linking to the transcript page anchored at the item.

### Search

A Transcripts result type on the search page using the existing `websearch_to_tsquery` pattern over `transcript_segments.search_vector`, with `ts_headline` snippets. A `speaker:` token filters through the speaker join; a speaker facet appears on transcript results. Trigram covers misspellings and partial words. Results link to the transcript page turn anchor, which highlights via a CSS `:target` rule; the chapter link is secondary.

### Admin discrepancy queue

Routes under the existing admin review area, modeled on `/admin/review/conflicts`. List sorted material first, filtered by state, category, and meeting. Each row: title, both excerpts side by side with timestamp and page, chapter link, minutes link, confidence, origin, citation match. Actions: approve, reject with reason, edit title and description then approve (edits go to `admin_*` columns; the form states that this changes only what docket.pub shows). A second tab lists `dismissed_by_model` rows. `needs_review` meetings appear as single rows. Auth is the blueprint's existing login hook.

### Admin speaker correction

Per meeting: each cluster with resolved name, role, confidence, method, three sample excerpts, and a dropdown to reassign to a roster member or a free-text name. Saving sets `is_manual`. Assigning two clusters to the same person merges a fragmented speaker. Splitting a mixed cluster at segment level is phase 2.

### Public "Minutes vs. Video" block

On the meeting page and affected item pages, `approved` rows only: title, description, category, both excerpts with links. Framed in the site's honesty-protocol voice: what was compared, that a person reviewed it, that the minutes remain the official record, link to methodology. A listing page `/minutes-vs-video` shows all approved discrepancies newest first. The block ships behind a feature flag (see ship gate).

### Operational surfaces

Meetings with video but no transcript, and `failed`/`needs_review` transcripts, appear on the data debt page with the reason. The admin AI panel gains rows for the new stages' runs, cost, and throughput, plus the approve-to-reject ratio.

---

## Section 6: Testing strategy

### Fixtures

- `tests/fixtures/transcript_pilot/`: the Item 15 pilot transcript, the 2/17/2026 minutes text, and an `expected.json` naming the two material discrepancies by category and the statute cites.
- A second, chaotic fixture cut from the user's local archive of Birmingham meetings: a public comment stretch plus a messy procedural exchange. Expected: zero action events during public comment, no discrepancies.
- A two-minute hand-corrected reference transcript for word error rate, proofed once by the user.

### Unit (no DB, no API)

Aligner: consent block satisfaction, item pulled from consent, LCS sequence detection, omission and addition pairing, reopened item, tabled versus postponed, actor comparison by member id. Guard: normalization, fuzzy pass, `missing` handling. Deterministic vote check. Candidate cap. Webhook payload. Prompt builders: both prompts contain the materiality fragment byte-for-byte; request builders emit structured outputs and never `tool_choice`. Response parser: `refusal` and `max_tokens` stop reasons fail the row. Client: mocked rate-limit error takes the existing retry path and honors retry-after. Producer: initial prompt budget, JSON contract, claim logic.

### Integration (real Postgres, each test owns its cleanup)

Migration 035 up and down. Claim SQL: newest first, skip-locked, zombie release after six hours, `transcribed` claims straight to upload. Upload as the `transcriber` role: writes succeed on the three transcript tables, fail elsewhere, and a replayed upload is idempotent. Version bump preserves `is_manual` speakers via the remap, flags low-overlap ones. Minutes hash change re-runs comparison and marks approvals `stale`. Transcript search, transcript page anchors, item excerpt bounds. Every admin route, including CSRF and unauthenticated refusal.

### Scale check before backfill

Inside one transaction: synthetic fill of about one million `transcript_segments`, then `ANALYZE` on the new tables, then `EXPLAIN (ANALYZE, BUFFERS)` on the search and transcript page queries, then `ROLLBACK`. Without the `ANALYZE` the planner sees an empty table and the check proves nothing.

### Live (opt-in, `-m live`)

1. Structured outputs smoke test against Sonnet 5.5 and Opus 5.5, before any pipeline code calls them.
2. Full pipeline pass on the pilot fixture asserting the two expected discrepancies with the right categories and severity.
3. Chaotic fixture pass asserting no fabricated actions.
4. Haiku versus Sonnet extraction A/B over the first ten meetings, recorded in `ai_runs` notes.

### Desktop producer

Unit tests above plus one acceptance check for the Blackwell bring-up: large-v3 on CUDA inside the container against the pilot clip, word error rate reported against the hand-corrected reference.

### Ship gate for the public block

Transcript page and search ship when their tests pass. The public "Minutes vs. Video" block stays behind its flag until at least 70 percent of `material` candidates over the first 10 reviewed meetings or the first 30 reviewed candidates, whichever comes first, are approved or edited-then-approved. The admin panel shows the running ratio. The flip is manual.

---

## Reviewer dispositions worth preserving

Rejected during brainstorming, with reasons, so they are not re-raised:

- Speaker name in the segment tsvector: couples a generated column to another table; replaced by a join filter.
- Cloud object storage for audio or JSON: new account and failure mode for data held twice already.
- Separate ffmpeg silence pass: faster-whisper's VAD already measures it.
- Haiku as the extraction default: judgment over long context; kept as an A/B.
- Chunking for 200K-context overflow: the 5.5 models have 1M windows; a ceiling check replaces chunking.
- Phonetic matching on actor names: actors are member ids after resolution.
- Markdown fence stripping: structured outputs make it unnecessary; stop-reason checks added instead.
- Role-based admin access: one admin, one login hook.
- Inbound webhook idempotency: the webhook is outbound only.
- Weekly `wsl --compact` runbook: unnecessary once audio lives on the host bind mount instead of the WSL2 disk.
- Chunking for marathon meetings: a twelve-hour meeting is about 150K tokens against a 500K ceiling and a 1M window.
- Video OCR backfill as a hard blocker: the vote baseline is minutes-derived rows, present for every year; OCR is corroboration only.
- Treating the public Postgres port as a new exposure: Railway's TCP proxy is already the operations path; the mitigation is the narrow role and TLS.
- Percentage-based `low_speech` threshold: replaced by an absolute speech floor so short meetings pass.
- Speaker-recall remap threshold (60 percent of the old speaker's time in one cluster): replaced by a cluster-precision rule so a finer diarizer does not drop assignments.

## Side notes surfaced, not in scope

- Video OCR claims only meetings within 60 days, so historical video votes need a backfill mode before `vote_outcome` comparisons work on old meetings.
- Homewood's adapter config carries an unused YouTube channel URL; a YouTube audio source would be a small addition to the producer later.
