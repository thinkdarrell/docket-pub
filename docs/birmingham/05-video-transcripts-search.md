# 5. Video, transcripts, search, and the timed link

This is the longest content flow on the site, and the only one that runs on two machines. A council video becomes a transcript on the operator's desktop; the Railway worker then names its speakers, extracts what happened, compares that with the minutes, and builds hidden search text; the web request, finally, decides which video to open and at which second. Every stage leaves the previous stage's output public and intact.

```
Granicus clip / YouTube recording
        │  (Windows desktop "Legion", Docker, GPU)
        ▼
  transcriber: claim → audio → Whisper + diarization → clean → upload
        │  writes transcripts, transcript_segments, transcript_speakers
        │  measures YouTube against Granicus → meeting_video_alignments
        ▼
  Railway worker, one stage per transcript per day:
    speakers → events (transcript side + minutes side) → compare
    then search cards for placed items
        │
        ▼
  web request: /transcript/, /search, item vote link, minutes-vs-video
    builds each timed link at render time from the alignment
```

## 1. The transcriber (desktop)

The transcriber is a Docker container on the operator's Windows machine, with an NVIDIA GPU, run by hand from the Windows clone of this repository (`transcriber/README.md`, `docs/runbooks/transcripts.md`). It reaches the production database only through `TRANSCRIBER_DATABASE_URL`, a role that can read `meetings`, `municipalities`, `council_members`, `agenda_items`, and `meeting_videos`, write the four transcript tables and its heartbeat, and insert or update (never delete) `meeting_video_alignments` (`scripts/sql/create_transcriber_role.sql`; decisions `0030`, `0076`).

A run does three things in order:

1. **Measure** (section 5): for up to a handful of YouTube recordings attached to Granicus meetings, work out where the recording sits on the Granicus clip's clock. No GPU, and no audio is kept (`0077`).
2. **Load the models**: faster-whisper `large-v3` on CUDA and pyannote speaker diarization.
3. **Transcribe**, newest meeting first, until `--limit` or `--max-hours` runs out. A meeting qualifies when it is Birmingham's, has a video, is not hidden, is a Granicus clip or a `yt-` row, and is on or after the run's `--since` date. The transcriber claims it with a `transcripts` row at `claimed`, fetches the audio (Granicus by ffmpeg from the download URL; YouTube by yt-dlp), records its hash and duration, and runs Whisper with a **prose prompt**: "Birmingham City Council. Councilors present are …" from the roster for that date, plus vocabulary sentences, within a character budget (`0046`).

What comes out is cleaned before it is uploaded (`0047`, `0064`): Whisper hallucinations and prompt leaks are dropped by log-probability and by matching the prompt's own words; words are split to speakers by diarization cluster; same-speaker fragments are merged; gaps of a minute or more become silence markers. A meeting with under three minutes of cleaned speech ends at `low_speech` and uploads nothing. Everything else is uploaded in one transaction: old segments deleted, speakers upserted, segments copied, the row set to `uploaded`. **A transcript is public the moment it is uploaded** (`0049`); no later stage can hide it.

Everything the run touched is archived under `C:\docket-archive\transcripts\<meeting id>\` (audio, raw ASR output, diarization, the transcript, word timestamps), so a re-run can replay without the GPU and the pipeline can be compared old against new (`0065`). A re-run of one meeting (`--meeting-id`) re-claims the row in place and, if it fails, restores the previous row so the old transcript stays public (`0048`, `0051`). `docs/specs/transcripts.md` owns the producer's rules; `docs/runbooks/transcripts.md` is how to run it.

## 2. The transcript tables

- `transcripts`: one row per meeting; its `status` walks `claimed → audio_fetched → transcribed → uploaded → speakers_resolved → events_extracted → compared`, with `failed`, `needs_review`, and `low_speech` as side exits. It records the engine, model, duration, word count, producer host, and the reason a comparison was skipped.
- `transcript_segments`: the spoken lines, each with start and end seconds, text, diarization cluster, the agenda item it is filed under and how (`index_point`, `event`, or `manual`), and a generated `search_vector`.
- `transcript_speakers`: one row per diarization cluster, with the council member it resolved to, the method that resolved it, a confidence, and an `is_manual` flag an admin's correction sets.
- `minutes_texts`: the minutes PDF's text, cached the first time the pipeline needs it, with its hash so a changed PDF is noticed.
- `meeting_events` and `minutes_discrepancies`: what the worker's stages produce, below.

## 3. The worker's stages (Railway)

Once a day the `transcript_pipeline` task claims a few transcripts and advances **each by exactly one stage**, chosen by its current status, so a new transcript takes three days to reach `compared`. Each stage is an `ai_runs` row under the daily AI budget (chapter 4). The claim requires a numeric Granicus id, so `yt-` meetings are transcribed but never analysed. `docs/runbooks/transcripts-pipeline-map.md` is the function-by-function map; `docs/specs/transcripts.md` states the rules a reader can observe.

**Speakers** (`uploaded → speakers_resolved`). First a fitness check: under 300 words, the transcript is marked `low_speech` instead. Then each segment is filed under the latest agenda item whose cue point (chapter 2) is at or before it. The model is shown roll-call pairs (the clerk's name, the member's answer), the chair addressing members by name, and samples of each cluster, and asked who each cluster is. Its answer is checked against the transcript's own text: a quoted line must appear verbatim in that cluster, and the confidence is capped by how the cluster was identified (roll call highest, a sample-only guess lowest). Manual rows an admin set are never overwritten.

**Events** (`speakers_resolved → events_extracted`). The model extracts what happened, as typed events with the segment they came from: motions, votes, amendments, public comment, recesses, and so on; segments are re-filed to items when an event names one. Then the **minutes side**: the minutes PDF is captured into `minutes_texts` and the same extraction runs over it, so the two records can be compared event to event.

**Compare** (`events_extracted → compared`). A deterministic aligner pairs transcript events with minutes events and lists the candidates where they differ: an item in one record and not the other, details that disagree, sequence differences, and a vote outcome that disagrees with the `votes` table. A judge model decides which candidates are real discrepancies and a second pass hunts for ones the aligner missed. Every quoted excerpt goes through the **citation guard**, which finds it in the source text exactly or by anchored fuzzy match; a quote it cannot find is marked `missing` and its confidence halved. A vote-outcome discrepancy is only ever the aligner's; a model that claims one is remapped to a wording difference. The rows land in `minutes_discrepancies` as `proposed`.

A held transcript (too many candidates, no minutes text) goes to `needs_review`; three transient failures go to `failed`; both fire a webhook, as does a stalled producer (a video over a week old with no transcript and no heartbeat). A re-comparison, after a changed transcript or a changed minutes PDF (a weekly sweep re-checks the hashes), marks the previous rows `stale` and matches them to the new ones; **a row an admin approved is never rewritten by a model pass** (`0044`, `0045`).

## 4. Search cards and the search page

At the end of the same tick, the **search-card** stage runs for a couple of transcripts that have reached `events_extracted` or later (`docs/specs/search.md`; decisions `0071`–`0075`). For each agenda item that has spoken segments, a model writes one `agenda_item_search_cards` row: the item's spoken aliases, details that were said aloud, identifiers, names, outcome, and what it refers to. Spoken details are quoted, and the citation guard verifies each quote in the segments it cites. The card's text is folded into the item's `search_vector` at weights B and C; **nothing on a card is ever displayed**. A card is tied to one upload (`source_uploaded_at`) and stops counting the moment the transcript is re-uploaded. The stage keeps its own bookkeeping in `transcript_card_runs` and never writes `transcripts`.

A card also stores **snapped bounds**, the segment range the model found the item actually being discussed, within ten minutes of where the cue point placed it. The bounds live beside each segment's `agenda_item_id` and never overwrite it (`0073`); where two items' ranges overlap, the segment belongs to the one opened latest, and an item with no bounds gives up segments that fall inside another item's current bounds (`0074`).

The `/search` page (`src/docket/services/query.py` `search_agenda_items`, `src/docket/services/search_query.py`) reads the typed text as words, quoted phrases, identifiers, excluded words, a `speaker:` token, and the recency words; an item matches on any unit and is ordered by typed identifiers matched, then matched words, then rank (`0072`). Under each result, up to three **spoken moments**, the transcript's own segments inside the item's snapped or placed range, each linking into the transcript page at that line. Below the results, "Also said at meetings" lists transcript lines matching every word, leaving out only the lines already nested above (`0075`). All of it is PostgreSQL full-text search with GIN indexes and no external engine (`0003`).

## 5. Measuring YouTube against Granicus, and the timed link

A Granicus clip's agenda items carry cue points: `agenda_items.video_timestamp_seconds` and the chapter id in `external_id`, both from the player page (chapter 2). Those are seconds on the **Granicus** clock. The council's YouTube recording of the same meeting starts at a different moment and may cover only part of the clip, so a link into YouTube needs a measured offset.

The transcriber's **measuring pass** (`transcriber/transcriber/measure.py`, `align.py`) takes both recordings' audio, reduces each to a band-energy envelope, and cross-correlates them in five-minute windows; a measurement passes when the windows agree on one offset by a clear margin and the ends of the covered span confirm it. The result is one `meeting_video_alignments` row per recording: `passed` with `offset_s` and the Granicus span it covers, or `rejected`, or `failed`, stamped with the `method_version`. A `rejected` row at the current method is final; a `failed` one is retried after a week.

At **render time**, `src/docket/services/video_links.py` builds every timed link (`0078`): for a moment at second `s` on the Granicus clock, the link opens **YouTube** at `s − offset_s` only when a `passed` measurement at a trusted method version, against the meeting's current clip, covers `s` (half-open: `start ≤ s < end`) and the converted second is not negative; otherwise it opens the **Granicus** chapter (the player with `meta_id` set to the chapter id) or, with no chapter, the plain player. Each link's wording names the site it opens. Nothing converted is stored. `yt-` meetings, which have no Granicus clock, link straight into their own video.

Which moment a link opens (`docs/specs/video-links.md`):

- an item's link opens its cue point;
- a **consent item** opens the start of the consent agenda, found as the largest run of consent cue points (`0079`); on YouTube only, a consent vote read well after the block opens at the vote's own second (`0082`);
- a **vote read from the video** (chapter 3) that falls within fifteen seconds after a cue point is attached to the item *before* that cue, because the clerk advances the chapter as the vote is announced (`NEAR_CUE_S` in `src/docket/analysis/vote_matcher.py`; `0083`, PR #145);
- a transcript line opens at its own second; a discrepancy row opens at its transcript excerpt's second.

## 6. What a reader sees

**The transcript page**, `/al/birmingham/meetings/<id>/transcript/`, exists only for a transcript that is uploaded and not `low_speech`, and for a hidden meeting only to an admin. It opens with a "Machine-generated transcript" notice naming the ASR model and linking the original video. Turns are grouped by speaker and agenda item; each turn has a timestamp anchor (`#t-<seq>`), and each item's first turn carries a marker linking to the item page and its timed video link. A speaker is named only when the resolution's confidence is at least 0.6 or an admin set it; otherwise "Speaker N", or "Unknown speaker" with no cluster. A named speaker links to the member page. Silences read "No speech detected (recess or dead air)". A "Who spoke" list closes the page under the same rule.

**Minutes vs. video**, `/al/birmingham/minutes-vs-video/` and the matching block on meeting and item pages, shows discrepancy rows only when all of these hold: the citation was found, an admin approved the row in `/admin/review/discrepancies`, the meeting is not hidden, and the `MINUTES_VS_VIDEO_UI` flag is on. Each row shows its title, the transcript excerpt and the minutes excerpt taken from the source texts, and a timed video link. The **ship gate** (`0032`) on the admin AI panel reports the approval ratio over the first reviewed meetings and is advisory: the operator flips the flag by hand.

## Honesty rules in this chapter

1. An upload is public at once; a worker failure never hides it, `low_speech` does, and a failed re-run restores the previous transcript.
2. A name appears only at confidence 0.6 or above, which no sample-only guess can reach; a name needs a verified quote.
3. A search card is never displayed and is used only while current; the moments shown are always the transcript's own words.
4. A discrepancy is public only with a found citation, a human approval, a visible meeting, and the flag on; a vote-outcome discrepancy is never a model's call.
5. YouTube opens only under a passing measurement that covers the moment; otherwise the link opens Granicus, and the link says which.

Next: [6. What the reader sees, page by page](06-reader-surfaces.md).
