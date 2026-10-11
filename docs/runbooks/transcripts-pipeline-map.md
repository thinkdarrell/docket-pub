# Transcripts pipeline map (plan 2, PR #106)

A review aid. Every box below names the code that implements it as `file:line`
so you can jump from the picture to the function. Line numbers are as of commit
`336a949` on branch `feat/transcripts-comparison` (after the 2026-10-11 fix commits).

How to use this for review: read section 1 for the shape, section 2 for the
state machine, then walk sections 3 to 7 one stage at a time. Each stage ends
with "What to probe": the questions a reviewer should be able to answer by
reading that code.

---

## 1. The whole thing on one page

```
  LEGION DESKTOP (plan 1, already live)                     RAILWAY WORKER (plan 2, this PR)
  ──────────────────────────────────────                    ────────────────────────────────────────────────────────
  claim video ─► fetch audio ─► faster-whisper ─► upload    cron transcript_pipeline, 10:00 America/Chicago
       │              │              │              │        scheduler.py:80   tasks.py:392
   claimed      audio_fetched    transcribed    uploaded ──┐
                                                  │        │   per tick (up to TRANSCRIPT_PER_TICK = 5 claims):
                             low_speech / failed ◄┘        │
                             (producer side)               ▼
                                                 ┌──────────────────────────────────────────────────────────┐
                                                 │ 0. CLAIM one transcript   pipeline.py:29 CLAIM_SQL        │
                                                 │    Birmingham, not hidden, newest meeting first,          │
                                                 │    FOR UPDATE SKIP LOCKED, attempts < 3, 24 h backoff     │
                                                 │    opens an ai_runs row (budget applies)  pipeline.py:199 │
                                                 └───────────────┬──────────────────────────────────────────┘
                                                                 │ status decides the stage  pipeline.py:24
                 ┌───────────────────────────────────────────────┼─────────────────────────────────────────┐
                 ▼                                               ▼                                         ▼
   ┌─────────────────────────────┐             ┌──────────────────────────────────┐        ┌──────────────────────────────────────┐
   │ 1. SPEAKERS  (Sonnet 5.5)   │             │ 2. EVENTS  (Sonnet 5.5)          │        │ 3. COMPARE  (Opus 5.5)               │
   │ uploaded → speakers_resolved│             │ speakers_resolved →              │        │ events_extracted → compared          │
   │                             │             │              events_extracted    │        │                                      │
   │ fitness gate ≥300 words     │             │ a. transcript-side timeline      │        │ a. aligner (pure Python, no LLM)     │
   │   else low_speech           │             │ b. re-assign segments to items   │        │ b. Opus JUDGE rules on candidates    │
   │ index-point item assignment │             │    from item_opened events       │        │ c. Opus HUNTER finds what aligner    │
   │ roll-call pairs, chair      │             │ c. download minutes PDF, sha,     │        │    missed                            │
   │   addresses, samples → LLM  │             │    page offsets                  │        │ d. deterministic vote check          │
   │ quotes verified, confidence │             │ d. minutes-side timeline         │        │ e. citation guard on every quote     │
   │   capped 0.95/0.75/0.55     │             │    (skipped → no_minutes /       │        │ f. reconcile with prior rows         │
   │ manual rows never touched   │             │     minutes_unavailable)         │        │    (stale / re-proposed / rejected)  │
   │ speakers.py:337             │             │ events.py:201                    │        │ compare.py:390                       │
   └─────────────────────────────┘             └──────────────────────────────────┘        └──────────────────┬───────────────────┘
                                                                                                             │ minutes_discrepancies rows
          any stage: TranscriptHeld → needs_review (+ webhook)         pipeline.py:211                       │ review_state = proposed
          any stage: 3rd transient error → failed (+ webhook)          pipeline.py:227                       ▼
          every tick, even on budget stop: minutes sweep + stall alert pipeline.py:288     ┌─────────────────────────────────────────┐
                                                                                            │ ADMIN  /admin/review/discrepancies      │
                                                                                            │ approve · reject · edit+approve · retry │
                                                                                            │ approve needs citation_match ≠ missing  │
                                                                                            │ speaker correction page per meeting     │
                                                                                            │ admin_transcripts.py · discrepancies.py │
                                                                                            └──────────────────┬──────────────────────┘
                                                                                                               │ review_state = approved
                                                                                                               ▼
                                                                                            ┌─────────────────────────────────────────┐
                                                                                            │ PUBLIC  (flag MINUTES_VS_VIDEO_UI)      │
                                                                                            │ "Minutes vs. Video" block on meeting    │
                                                                                            │   and item pages; /minutes-vs-video/    │
                                                                                            │ transcript page: Who spoke, speaker:    │
                                                                                            │   search (not gated by the flag)        │
                                                                                            │ public.py:293 · :350 · :410 · :1025     │
                                                                                            └─────────────────────────────────────────┘
```

Three LLM stages, one cron, one table of proposals, one human gate, one flag.
Nothing reaches a reader without passing the human gate and the flag.

---

## 2. State machines

### 2a. `transcripts.status` (one row per meeting)

Defined in `migrations/035_transcripts.py:19`. Producer states on the left,
worker states on the right.

```
 producer (Legion)                          worker (Railway, this PR)
 ─────────────────                          ────────────────────────────────────────────────
 claimed ─► audio_fetched ─► transcribed ─► uploaded ─► speakers_resolved ─► events_extracted ─► compared
                                              │               │                   │   ▲             │
                                              │ <300 words    │                   │   │ minutes     │ weekly sweep finds
                                              ▼               │                   │   │ appear or   │ changed PDF
                                          low_speech          │                   │   │ change      │ (pipeline.py:327)
                                                              │                   │   └─────────────┘
                                                              ▼                   ▼
                                                   needs_review (TranscriptHeld / permanent row error)
                                                   failed       (3rd transient error in a row)
                                                              │
                                                              │ admin "Retry" → back to the earliest stage
                                                              ▼ whose output is missing (discrepancies.py:150)
                                                   uploaded / speakers_resolved / events_extracted
```

Side columns that steer the machine:

| Column | Written by | Read by |
|---|---|---|
| `stage_attempts` | bumped at claim `pipeline.py:51`, zeroed on advance `:121` | claim gate `< 3` `:44`, `mark_transient` turns 3 into `failed` `:158`; a 429 hands the attempt back, `mark_rate_limited` `:144` |
| `last_attempted_at` | claim `:51` | 24 h backoff `:45` |
| `compare_skipped_reason` | `advance` `:122`, sweep `:342` | claim gate `:39-43` decides whether `events_extracted` is claimable |
| `needs_review_reason` | `mark_needs_review` `:137` | held tab in admin |
| `last_error` | every failure path | held tab, data debt page |
| `uploaded_at` | producer | public predicate: a worker failure never hides an uploaded transcript `services/transcripts.py:25` |

Claimability of `events_extracted` (`pipeline.py:39-43`): claimable when the
reason is NULL (first compare), `minutes_changed` (sweep), or `no_minutes` /
`minutes_unavailable` **and** the meeting now has a `minutes_url`. A meeting
with no minutes URL sits at `events_extracted` costing nothing until the clerk
posts minutes. `advance` zeroes attempts for those two reasons `:126-128` so
daily retries do not burn the three-attempt cap.

### 2b. `minutes_discrepancies.review_state` (one row per finding)

Defined in `migrations/035_transcripts.py:154`.

```
                 compare stage writes
                        │
                        ▼
   ┌─────────── proposed ───────────┐
   │              │                 │
   │ admin        │ admin           │ Opus judge said "not real"
   │ approve      │ reject          │ (written directly, never proposed)
   ▼              ▼                 ▼
approved       rejected     dismissed_by_model
   │              │                 │
   │ re-compare   │ re-compare:     │ re-compare: deleted and replaced
   │ (minutes     │ matched row     │ (compare.py:335)
   │  changed or  │ stays rejected  │
   │  version     │ (compare.py:351)│
   │  bump)       │                 │
   ▼              │                 │
 stale ◄──────────┘ (proposed also → stale first, compare.py:336)
   │
   │ matched by category + transcript_event_id,
   │ or for minutes-only rows by category + item + excerpt similarity ≥ 0.8  (compare.py:311)
   ▼
 proposed again, with previous_review_state recorded and reviewed_by / reviewed_at / review_note cleared
```

Gates on `approve` (`services/discrepancies.py:54`): the UPDATE itself requires
`review_state = 'proposed' AND citation_match <> 'missing'`. There is no path
to `approved` that skips the citation check. `edit_and_approve` `:126` runs
`_attach_citation` `:86` first, which re-verifies **every** side the row cites
against the live transcript and minutes text, then passes the admin text and the
verified citation into the same single guarded `approve` UPDATE.

---

## 3. Stage 0: claim, gates, and bookkeeping

**Entry:** `run_transcript_pipeline` `pipeline.py:254`, called from
`tasks.py:392` under `_safe_run`, scheduled at `scheduler.py:80`.

**Order of operations per tick:**

1. `_validate_models` `:248`. Every stage model must have a `PRICING` entry or the tick raises `AIFatalError` before touching a row. This and step 2 run inside the `try`, so the housekeeping in step 4 still runs.
2. `reset_for_versions` `:305`. If a prompt version was bumped, affected transcripts are moved back to the right stage. Events bump → `speakers_resolved`. Compare bump → `events_extracted`, but only for meetings with live rows (`proposed`, `approved`, `dismissed_by_model`); counting stale or rejected rows would loop forever.
3. Up to `limit` iterations: check today's spend against `AI_DAILY_BUDGET_USD` `:270`, claim one row `:277`, process it `:280`. Stop on budget or on a 429.
4. `finally` `:288`: run `sweep_minutes_changes` and `alert_if_producer_stalled` regardless. Housekeeping errors never mask the loop's exception; on a clean loop they are re-raised so the Healthchecks ping reports them.

**`process_claim` `:183`, the per-row wrapper every stage runs inside:**

```
claim ──► stage == speakers?
             │ yes: fitness_reason(word_count) :77 ──► under 300 words → mark_low_speech :131 → return (no ai_runs row)
             │      assign_index_points :92        (Granicus index points → segment.agenda_item_id, method index_point)
             ▼
          _open_run(ai_runs) :199
          try:   stage_fn(claim) inside usage_capture()   ← every Anthropic call's tokens land here
                 advance(outcome) :206
          except TranscriptHeld        → mark_needs_review + webhook        :211
          except AIPermanentRowError   → mark_needs_review("permanent") + webhook :217
          except AIRateLimited         → mark_rate_limited (attempt handed back), tick stops :223
          except AITransientError      → mark_transient; 3rd → failed + webhook :227
          except AIFatalError          → re-raise (tick dies, Healthchecks sees it) :234
          except Exception             → logged, mark_transient (a stage bug cannot take the cron down) :236
          finally: _close_run with cost from emissions :241
```

**Tests:** `tests/integration/test_transcript_pipeline.py`,
`test_pipeline_e2e.py`, `tests/unit/test_transcript_fitness.py`,
`test_worker_scheduler_transcripts.py`.

**What to probe:**

- Can two worker processes claim the same row? (`FOR UPDATE OF t SKIP LOCKED` inside the CTE, attempts bumped in the same statement.)
- What does a healthy transcript look like after three consecutive 429 days? (Still `uploaded` with attempts unchanged: a 429 hands its attempt back, `pipeline.py` `mark_rate_limited`.)
- Does a stage crash ever leave a row in a state nothing can claim? (Every path writes a status; `needs_review` and `failed` are claimable only via admin Retry.)
- Is the `low_speech` path visible anywhere? (Data debt page label "Too short to analyze (N words)" via `services/transcripts.py:304`. No `ai_runs` row, by design: no model was called.)

---

## 4. Stage 1: speaker resolution (`speakers.py`)

**Goal:** name each diarization cluster (`SPEAKER_00`, `SPEAKER_01`, ...) as a
council member, or a role, with a confidence that honestly reflects the
evidence.

```
load_speech_segments :251 ──► roster_for_meeting :48 (seated members for that meeting)
        │
        ▼
build_packet :213
   ├─ find_roll_call_pairs :105    clerk/chair says a surname, next utterance within 8 s is "here"/"present"
   ├─ find_chair_addresses :136    "Councilor X" said by one cluster, a different cluster answers within 20 s
   ├─ cluster_stats :172           turns, seconds, first/last appearance per cluster
   └─ sample_utterances :185       up to 6 substantive (≥6 words) utterances per cluster
        │
        ▼
render_speaker_user :223 ──► count_tokens; > TRANSCRIPT_TOKEN_CEILING (500K) → TranscriptHeld("token_ceiling") :350
        │
        ▼
StructuredClient.call  model = AI_TRANSCRIPT_SPEAKER_MODEL, effort medium, max_tokens 16000, SPEAKER_SCHEMA
        │
        ▼
SpeakerResolution.model_validate :354 ──► invalid, or a cluster missing from the answer → TranscriptHeld("schema_invalid")
        │
        ▼
apply_confidence_rules :281   per cluster:
   quote 1 and quote 2 must be found verbatim in that cluster's own text (normalized, ≥ 8 chars unless roll_call)
   unverified primary quote           → method demoted to sample_inference
   member id not on the seated roster → sample_inference
   caps:   two verified quotes 0.95 · one 0.75 · sample_inference 0.55   (CONFIDENCE_CAPS :246)
   confidence = min(model's confidence, cap)
        │
        ▼
write_assignments :311   UPDATE transcript_speakers ... WHERE is_manual = FALSE   ← manual corrections survive re-runs
                         needs_review = confidence < 0.6
                         re-link segments.speaker_id by cluster_label
        │
        ▼
StageOutcome("speakers_resolved")
```

**Where the floor bites:** `SPEAKER_CONFIDENCE_FLOOR = 0.6`
(`services/transcripts.py:19`). Below it a cluster renders as "Speaker N" on the
public page and is left out of "Who spoke" (`speaker_index` `:336`). Since the
sample-inference cap is 0.55, a name backed only by "sounds like them" never
shows publicly. A name needs at least one verified quote.

**Admin correction:** `/admin/transcripts/<meeting>/speakers`
(`admin_transcripts.py:106`). `speaker_correction.reassign` `:56` sets
`is_manual = TRUE`; `release` `:79` clears it so the next run may overwrite.

**Tests:** `tests/unit/test_speaker_signals.py`,
`tests/integration/test_speaker_stage.py`, `test_admin_speakers.py`.

**What to probe:**

- Could the model name a cluster as a member who was absent? (Roster is per meeting; off-roster ids are dropped to NULL in `write_assignments` and capped at 0.55.)
- Could a fabricated quote earn confidence? (Quotes are substring-checked against the cluster's own concatenated text, not the whole transcript.)
- Could a short fragment earn the roll-call waiver? (No. Under 8 characters verifies only when the method is `roll_call` and the quote is one of `RESPONSE_WORDS`.)
- What happens to a meeting with zero speech clusters? (Advances with "no speech clusters"; no model call.)

---

## 5. Stage 2: event extraction, both sides (`events.py`, `minutes.py`)

**Goal:** turn the transcript and the official minutes into two comparable
timelines of typed events, each row anchored to a segment (transcript) or a
page and character offset (minutes).

```
run_events_stage :201
   │
   ├─ A. TRANSCRIPT SIDE
   │     render_transcript :65  (segments with resolved speaker labels + agenda listing)
   │     extract_side :88       Sonnet, effort medium, max_tokens 64000, EVENTS_SCHEMA
   │                            token ceiling / schema failure → TranscriptHeld
   │     write_events :106      DELETE old transcript-side rows for the meeting, INSERT fresh
   │                              agenda_item_refs filtered to real agenda item ids
   │                              actor_member_id must be on roster, else matched from actor_text (match_actor :99)
   │                              start_s + segment_id from segment_seq
   │                              detail = EventDetail.compact() + quote
   │                              prompt_version = EVENTS_PROMPT_VERSION (200)
   │     reassign_segments_from_events :143
   │                              every item_opened and the first adjourn close the previous range;
   │                              only single-item item_opened ranges are written (method 'event');
   │                              manual assignments are never overwritten
   │
   └─ B. MINUTES SIDE   extract_minutes_side :176
         no minutes_url            → return "no_minutes"
         capture_minutes :97       download (browser UA, streamed, 40 MB cap), sha256, pdfplumber per page → text + page_offsets
                                   same sha + same url → reuse stored text
                                   else upsert minutes_texts (extracted_at = now)
         download failed or oversized, nothing stored → "minutes_unavailable"
         under 50 words of text (scan, no text layer) → TranscriptHeld("minutes_no_text")  events.py:188
         extract_side               Sonnet again, EVENTS_MINUTES_SYSTEM
         write_events(source='minutes')
                                   page from the model; char_offset by find_citation(quote) against minutes text;
                                   page corrected from the offset when the quote is found
   │
   ▼
StageOutcome("events_extracted", skipped_reason = None | "no_minutes" | "minutes_unavailable")
```

**Event vocabulary** (`migrations/035_transcripts.py:109`): `item_opened`,
`item_deferred`, `consent_amendment`, `motion`, `second`, `amendment`, `vote`,
`executive_session_motion`, `recusal`, `procedural_ruling`, `roll_call`,
`recess`, `reconvene`, `adjourn`, `public_comment`, `statement`. Scope is
`item`, `consent_block`, or `meeting`.

**Detail fields** (`schemas.py:58`): action, to_date, as_stated, items,
requested_by, mover, seconder, what_changed, result, yeas, nays, abstentions,
roll_call_names, method, stated_reason, statute_cite, member, kind, ruling,
present, absent, clock_time, speaker_text, topic, unlisted_item. Strings and
lists are non-nullable on the wire (`""` and `[]` mean "none") because the API
allows at most 16 nullable fields per schema; a pydantic validator maps them
back to None, and everything reads detail through `compact()`.

**Why events are deleted and rewritten:** a re-extraction replaces the
timeline wholesale. Discrepancy rows that pointed at the old events get their
FK set to NULL (`ON DELETE SET NULL`), which is why migration 036 dropped the
"at least one event id" CHECK and `build_rows` enforces it in code instead
(`compare.py:278`, `:289`).

**Tests:** `tests/unit/test_events_render.py`, `test_minutes_extract.py`,
`test_transcript_schemas.py`, `tests/integration/test_events_stage.py`,
`test_minutes_capture.py`, `test_036_migration.py`.

**What to probe:**

- A minutes PDF that downloads but is a scanned image (no text layer). (Under 50 words of extracted text raises `TranscriptHeld("minutes_no_text")`: held tab plus webhook. A person decides on OCR or a new URL.)
- The model cites an agenda item id that does not exist. (Filtered to `valid_item_ids`; a floor-added item is named in `detail.unlisted_item` instead, per PR #104.)
- A minutes-side hold (token ceiling on a 300-page PDF) after the transcript side already ran. (Admin Retry resumes at `events_extracted`; compare runs the minutes side alone. Only an automatic transient retry re-spends the transcript side.)
- An oversized PDF. (Streamed and abandoned past 40 MB; recorded as `minutes_unavailable`.)

---

## 6. Stage 3: comparison (`aligner.py`, `compare.py`, `guard.py`)

**Goal:** produce proposed discrepancies, each citing exact text from both
sources, for a person to approve or reject. Five sub-steps.

### 6a. Pre-flight (`run_compare_stage` `compare.py:390`)

```
load minutes-side events
   none, or compare_skipped_reason == 'minutes_changed' → extract_minutes_side now
        still not ok → StageOutcome("events_extracted", skipped_reason) and wait
load transcript events, minutes text, segments → TranscriptText (joined text with offset→segment map, :68)
```

### 6b. Aligner, deterministic (`aligner.py:192`)

```
effective_consent_block :60   published consent set ± consent_amendment events (pulled / added), per side
   items in minutes' block but not video's  → candidate "addition"  (pulled on video, still in consent in minutes)
   items in video's block but not minutes'  → candidate "omission"
group_key :74                 ("item", refs) | ("consent",) | ("meeting",) | ("unlisted", name)
pair_group :122               within a group, same event_type pairs k-th with k-th; leftovers are one-sided
details_differ :93            paired events → category:
                                vote result / tallies differ        → vote_outcome
                                actor differs on motion/recusal/...  → speaker
                                statute cite (canonical_statute, guard.py:136) or stated_reason jaccard < 0.5 → wording
                                action / to_date / kind differ      → wording
                                as_stated / what_changed / ruling jaccard < 0.4 → wording
one-sided MINUTED_TYPES :20   transcript-only → omission · minutes-only → addition
sequence_candidates :135      paired events whose order differs across sides (LIS) → sequence
vote_outcome_candidates :168  every transcript vote vs the matching `votes` row (plan 1's OCR'd minutes votes)
                              one votes row per transcript vote; exact item-set match, else largest overlap
```

Output: `Candidate` list with ids 1..N. Everything except `vote_outcome` goes
to the judge. More than `TRANSCRIPT_CANDIDATE_CAP` (40) judged candidates →
`TranscriptHeld("candidate_cap")`: a meeting that noisy needs a person first.

### 6c. Opus judge (`compare.py:410`)

Input: each candidate with a ±45 s transcript window and a ±600-char minutes
window (`render_judge_user` `:125`). Output per candidate: `is_real`,
category, severity, title, description, a transcript quote, a minutes quote,
confidence, dismiss reason. `JUDGE_SYSTEM` carries the materiality rule
(`prompts.py:17`): commitments, dollar figures, legal positions and statute
cites, stated reasons, procedural rulings, vote mechanics. Effort high,
max_tokens 32000.

### 6d. Opus hunter (`compare.py:414`)

Input: the full rendered transcript and full minutes text plus the aligner's
candidate list, so it does not repeat them. Output: new discrepancies with
quotes and item refs. Effort high, max_tokens 16000. Any item ref not on the
agenda is dropped; a hunted row with no event anywhere to anchor to is dropped
with a warning (`:278`).

### 6e. Rows and the citation guard (`build_rows` `compare.py:190`)

```
vote_outcome candidates   → material rows, confidence 0.9, no model involved
                            transcript quote from the vote event's detail.quote; minutes side from the paired
                            minutes event quote, or the raw OCR vote text when there is no minutes event
judge verdicts            → is_real false → row written as dismissed_by_model (kept for audit, never shown)
                            is_real true  → row with the judge's title/description/severity
hunter discrepancies      → origin 'model_initiated', anchored to the nearest event by time / offset / item

every quote on every row passes find_citation (guard.py:82):
   normalize (NFKD with combining marks dropped, curly quotes, soft hyphens, whitespace) with an offset map back to the raw text
   exact substring → 'exact'
   else anchored fuzzy: an anchor is any exact 3-word shingle of the quote; windows tried only around anchors;
        SequenceMatcher ratio ≥ 0.92 after tightening to matched blocks → 'fuzzy'
   else 'missing'
row.citation_match = missing if any cited side is missing, else fuzzy if any is fuzzy, else exact   (citation_match_for :169)
row.confidence halved when missing
excerpts stored are the SOURCE text at the matched span, not the model's quote
```

Rows carry `prompt_version = COMPARE_PROMPT_VERSION` (200), `review_state =
proposed` (or `dismissed_by_model`), `agenda_item_id = min(refs)`.

### 6f. Reconcile (`compare.py:327`)

Described in 2b. The point: a re-comparison never silently un-approves or
un-rejects. Approved rows go `stale` with `previous_review_state = approved`
and come back as `proposed` only if the new run reproduces them; rejected rows
that match stay rejected.

**Tests:** `tests/unit/test_aligner.py`, `test_guard.py`,
`test_compare_render.py`, `tests/integration/test_compare_stage.py`,
`test_recompare.py`; live: `tests/live/test_transcript_pilot_e2e.py`
(reproduced both known 2026-02-17 Item 15 discrepancies twice),
`test_transcript_chaotic.py` (clean on a noisy slice).

**What to probe:**

- Can a model-invented quote reach the public? (It gets `missing`; `approve` refuses `missing`; `edit_and_approve` re-verifies against source text before it can flip.)
- Can the judge upgrade a `minor` to `material`? (Yes, severity is the judge's call; the ship gate counts material rows only, so this is where the gate's denominator comes from.)
- Is `vote_outcome` ever a model's opinion? (No. Both the paired-event mismatch and the OCR vote-row check are deterministic, written before the verdict loop.)
- What happens when the hunter's quote is not found? (Row kept as `missing` with a fallback anchor to the first event on the item, confidence halved. A reviewer sees it in the queue and must attach a real excerpt before approving.)
- Run-to-run variance: the pilot gave 6 rows one run and 8 the next, with the two headline discrepancies both times. Expect the omission count to wobble.

---

## 7. Housekeeping that runs every tick

| Job | Where | What |
|---|---|---|
| Version resets | `pipeline.py:305` | Bumping `EVENTS_PROMPT_VERSION` re-runs events + compare; bumping `COMPARE_PROMPT_VERSION` re-runs compare on meetings with live rows. Versions live only in `meeting_events.prompt_version` and `minutes_discrepancies.prompt_version`. |
| Minutes sweep | `pipeline.py:327` | For `compared` meetings, re-download the minutes at most weekly (`COALESCE(last_checked_at, extracted_at) < now() - 7 days`), 10 per tick. A changed sha → status back to `events_extracted` with reason `minutes_changed`. `last_checked_at` (migration 036) is stamped on every outcome so a failing download waits a week instead of starving the queue. |
| Producer stall alert | `alerts.py:64` | A Birmingham meeting with video, older than 7 days, no transcript row, and no producer heartbeat in 7 days → webhook `producer_stalled`. |
| Alerts | `alerts.py:21` | POST JSON to `ALERT_WEBHOOK_URL`; kinds `transcript_needs_review`, `transcript_failed`, `producer_stalled`. No URL set → logged only. |

---

## 8. Admin surface (`web/admin_transcripts.py`, `services/discrepancies.py`)

```
before_request _guard :19     login required; CSRF validated on every POST (web/csrf.py)
_back :27                     redirects only to local paths ("/" but not "//")

GET  /admin/review/discrepancies            :36   tabs: proposed · approved · rejected · stale · held
                                                   filters: category, meeting; 25 per page; gate readout
POST .../<id>/approve                       :56   → approve()         one UPDATE; requires proposed + citation present
POST .../<id>/reject                        :68   → reject()          reason required
POST .../<id>/edit-approve                  :81   → edit_and_approve  admin title/description; optional replacement
                                                                      excerpts, re-verified; written in the same guarded UPDATE as the approval
POST /admin/transcripts/<meeting>/retry     :95   → retry_transcript  held/failed → earliest stage with missing output
GET  /admin/transcripts/<meeting>/speakers  :106  cluster list with samples, roster dropdown
POST .../speakers/<cluster>                 :119  → reassign (is_manual = TRUE)
POST .../speakers/<cluster>/release         :133  → release  (is_manual = FALSE)
```

State races (two reviewers, one row) surface as a flash message and redirect,
not an error page (`_fail` `:50`).

**Ship gate** (`discrepancies.py:192`): over material rows ordered by
`reviewed_at`, stop at the 10th distinct meeting or the 30th decision,
whichever first. `gate_met` = window complete and approved ÷ total ≥ 0.70.
Shown on the AI panel (`templates/admin/ai_panel.html:76`) with the flag's
current value. The flag is flipped by hand; the gate is advisory.

**Tests:** `tests/integration/test_admin_discrepancies.py`,
`test_admin_speakers.py`, `test_admin_ai_panel_transcripts.py`.

---

## 9. Public surface

Two different gates apply, and it matters which is which.

**Not behind the flag (ships with the PR):**

- Transcript page `/al/birmingham/meetings/<id>/transcript/` (`public.py:317`): resolved names above the 0.6 floor, "Who spoke" index (`speaker_index`), item anchors.
- Search `speaker:oquinn budget` (`public.py:1025`, `parse_speaker_token` `services/transcripts.py:207`): trigram or punctuation-insensitive match on the resolved name.
- `public_predicate` (`services/transcripts.py:25`): an uploaded transcript stays public through `failed` and `needs_review`. A worker bug never takes a readable transcript off the site.

**Behind `MINUTES_VS_VIDEO_UI` (flag off at merge):**

- "Minutes vs. Video" block on meeting pages (`public.py:293`) and item pages (`:410`), via `list_public_for_meeting` / `list_public_for_item`.
- Index `/minutes-vs-video/` (`public.py:350`), 404 while the flag is off.
- All three read only `review_state = 'approved' AND m.is_hidden = FALSE` (`discrepancies.py:171-190`).
- Copy in `templates/partials/minutes_vs_video.html` and `about_methodology.html`: "The minutes remain the official record", every entry "reviewed by a person".

So the chain for one public sentence is: model proposed it → quote found in
source text → a named admin approved it → the meeting is not hidden → the flag
is on. Remove any link and it does not render.

---

## 10. Knobs (`config.py:58-72`)

| Variable | Default | Effect |
|---|---|---|
| `AI_TRANSCRIPT_SPEAKER_MODEL` | `claude-sonnet-5-5` | stage 1 |
| `AI_TRANSCRIPT_EVENTS_MODEL` | `claude-sonnet-5-5` | stage 2, both sides |
| `AI_TRANSCRIPT_COMPARE_MODEL` | `claude-opus-5-5` | judge and hunter |
| `AI_TRANSCRIPT_AB_MODEL` | `claude-haiku-4-5-20251001` | `scripts/transcript_extraction_ab.py` only; verdict was "Sonnet stays" |
| `TRANSCRIPT_PER_TICK` | 5 | claims per daily run |
| `TRANSCRIPT_MIN_WORDS` | 300 | fitness floor → `low_speech` |
| `TRANSCRIPT_TOKEN_CEILING` | 500000 | any single prompt above this → `needs_review` |
| `TRANSCRIPT_CANDIDATE_CAP` | 40 | judged candidates above this → `needs_review` |
| `AI_DAILY_BUDGET_USD` | shared | shared with item/meeting summaries; transcripts yield when it is spent |
| `ALERT_WEBHOOK_URL` | unset | webhook for the three alert kinds |
| `HEALTHCHECK_TRANSCRIPT_PIPELINE_UUID` | unset | Healthchecks ping per tick |
| `MINUTES_VS_VIDEO_UI` | false | public block + index |

Prompt versions `prompts.py:11-13`: SPEAKER 200, EVENTS 200, COMPARE 200.

---

## 11. Known watch items

Fixed after the external review of 2026-10-11 (commits `f20d82e`..`336a949`):
a 429 no longer counts as an attempt; housekeeping runs when setup raises a
fatal; minutes PDFs are capped at 40 MB; a PDF with no text layer holds as
`minutes_no_text`; edit-approve is one guarded statement; a re-proposed row
forgets its old reviewer; the roll-call quote waiver covers response words
only; the citation guard folds accents either way.

Still open, by decision:

- A stage bug surfaces after three days as "Transcription failed" on the data debt page. The webhook names the stage; the page does not.
- `low_speech` writes no `ai_runs` row (no model was called).
- A meeting whose only rows are stale or rejected is not re-compared after a compare version bump. `scripts/transcript_recompare.py --meeting-id N --now` covers the single-meeting case.
- An automatic transient retry of the events stage re-spends the transcript side. The admin Retry path does not: it resumes at `events_extracted` when transcript events exist, and compare runs the minutes side alone.

Checked and not a problem:

- Stale rows render from their own excerpt columns (`transcript_excerpt`, `minutes_excerpt`, `transcript_start_s`, `minutes_page`), not through the event FKs, so a re-extraction that nulls both FKs leaves the row readable in the stale tab.

Unknown until real meetings run:

- Speaker resolution quality (one live run: four members at single-signal confidence, chair unnamed).
- Extraction recall (20 events for a 104-minute, 66-item meeting looked thin; the A/B measured Haiku against Sonnet, not Sonnet against truth).

---

## 12. Suggested review walk

1. Section 2a, then `CLAIM_SQL` and `process_claim`. Convince yourself every exception lands somewhere visible.
2. Section 6e and `approve`. Trace one quote from the model's output to the public template and name each check it passes.
3. Section 4, `apply_confidence_rules`. Decide whether 0.75 for one verified quote is the right public floor, or whether 0.6 should move.
4. Section 6b, `details_differ`. These thresholds (jaccard 0.5 / 0.4, fuzzy 0.92) are judgment calls with tests but no production data behind them yet.
5. Section 2b and `reconcile`. Walk the minutes-changed path end to end: sweep → `minutes_changed` → compare → stale → re-proposed.
6. Section 9. Confirm which public surfaces ship flag-off and that you are comfortable with "Who spoke" and `speaker:` search being live at merge.
