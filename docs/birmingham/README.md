# How Birmingham on docket.pub works

A guided tour of everything behind `https://docket.pub/al/birmingham/`: where the records come from, how they become rows, how rows become votes, members, summaries, transcripts and search, what a reader sees, and where it all runs. It is written for anyone who needs the whole picture in one sitting: the operator after a month away, a contributor's first day, a journalist asking "how do you know that?".

It is a **map, not an owner**. By the project's rule that every fact lives in exactly one file (`docs/PRINCIPLES.md`, "One owner per fact"), the detailed rules stay where they are: the behaviour specs in `docs/specs/`, the decisions in `docs/decisions/`, the schedule in `src/docket/worker/scheduler.py`. Each chapter says what happens and why, then points at the file that owns the exact rule. When this guide and an owner disagree, the owner is right and this guide needs a fix.

## The chapters

| | Chapter | One line |
| --- | --- | --- |
| 1 | [Where Birmingham's records come from](01-sources.md) | Granicus, the city calendar, the council's YouTube channel, and the 2023 manifest; what each supplies and what it does not |
| 2 | [How a meeting enters the database](02-ingest.md) | The daily ingest: the meeting row, agenda items and cue points, the meeting-type ladder, minutes votes, and the adoption sweep |
| 3 | [Votes, members, and the facts on an item](03-votes-and-facts.md) | Minutes votes and video-OCR votes kept apart, matching votes to items, provisional links and promotion, resolving member names, amounts and topics |
| 4 | [Summaries, scores, and badges](04-ai-summaries.md) | The one stage a language model touches: Wave 0, extraction, rewrite, reconcile, floors, badges, the meeting summary, the budget, the dollar check |
| 5 | [Video, transcripts, search, and the timed link](05-video-transcripts-search.md) | The desktop transcriber, the worker's three stages, minutes-vs-video, search cards, measuring YouTube against Granicus, and which video a link opens |
| 6 | [What the reader sees, page by page](06-reader-surfaces.md) | Every public page under `/al/birmingham/`, the city page section by section, the card faces, and the honesty labels |
| 7 | [Where it runs, and the daily rhythm](07-operations.md) | Railway, the Legion, Healthchecks, the order of the morning's tasks, deploys, flags, and how to watch it |

## The whole flow on one screen

```
  THE CITY PUBLISHES                      DOCKET.PUB READS (Railway worker, every morning)
  ───────────────────                     ──────────────────────────────────────────────
  Granicus archive ──────────────────▶  ingest_all ─▶ meetings, agenda_items (+cue points),
    agendas, minutes PDF, video clip,                   votes + member_votes from the minutes,
    index points                                        minutes_adopted_at from the adoption sweep
  Council page (calendar) ───────────▶  city_calendar ─▶ city_calendar_events ─┐
  YouTube channel ───────────────────▶  youtube_ingest ─▶ meeting_videos ──────┼─▶ meeting-type ladder
  2023 manifest (operator, once) ────▶  backfill script ─▶ meetings, agenda_items ┘   (type, sitting, body)

  Granicus clip frames ──────────────▶  video_ocr ─▶ votes + member_votes (source video_ocr)

                                        ai_items ─▶ headline, why it matters, 2 scores, badges
                                        ai_meetings ─▶ executive_summary (provisional → adopted)
                                        resolve_member_votes ─▶ member_votes.council_member_id
                                        vote_matching ─▶ vote_agenda_items (provisional → promoted)
                                        process_badges ─▶ split_vote, contested, …   (defective, see below)
                                        briefing_facts ─▶ city_briefing_facts (splits, member counts)

  THE OPERATOR'S DESKTOP (Windows, GPU, by hand)
  ─────────────────────────────────────────────
  Granicus / YouTube audio ──────────▶  transcriber ─▶ transcripts, transcript_segments, transcript_speakers
  both recordings' audio ────────────▶  measuring pass ─▶ meeting_video_alignments (offset, span)

                                        transcript_pipeline (worker, one stage per day):
                                          speakers ─▶ events (+ minutes_texts, meeting_events)
                                          ─▶ compare ─▶ minutes_discrepancies (human-approved before public)
                                          ─▶ search cards ─▶ agenda_item_search_cards (hidden search text)

  THE READER (Flask web, per request)
  ───────────────────────────────────
  /al/birmingham/            opener + doors composed from facts, no model
  /meetings/<id>/            summary, votes (source + provisional/adopted), cards, source rail
  /items/<id>/               headline, facts, "from the video", vote block with a timed link
  /meetings/<id>/transcript/ turns, speakers at ≥0.6 confidence, timed links
  /search                    ranked items + spoken moments + "Also said at meetings"
  /council/<id>/             one vote source per meeting, dissent = against the outcome
```

## The six rules you will meet in every chapter

These are `docs/PRINCIPLES.md` as they show up in the Birmingham flow; the chapters cite them by name.

1. **Source or silence.** Every fact links to the city's document; a missing value is shown as missing, never defaulted. (Unlinked votes stay unlinked; unresolved names stay NULL; NULL scores until the model has run.)
2. **Keep the sources apart.** Minutes votes and video-OCR votes carry their `source` everywhere and are never merged; the site counts one source per meeting and shows a disagreement as a disagreement.
3. **Framing follows the data.** The opener and the doors are composed from facts, not written by a model; the model's text may not add a side the record lacks.
4. **Evidence or silence.** A pipeline change is compared old against new on real rows; a claim of "working" comes with the command's output.
5. **Production is not a sandbox.** One targeted statement for a bulk change; every AI batch bounded by a limit and the daily budget; no second heavy process on the worker.
6. **One owner per fact.** Which is why this guide links instead of restating.

## Which table does what

| Table | Written by | Chapter |
| --- | --- | --- |
| `municipalities` | migrations (the Birmingham row and its `metadata` flags) | 1 |
| `meetings`, `agenda_items`, `processing_status` | `ingest_all`, the YouTube pass, the 2023 backfill | 2 |
| `city_calendar_events` | `city_calendar` | 1, 2 |
| `meeting_videos` | `youtube_ingest` | 1, 5 |
| `votes`, `member_votes` | ingest (minutes), `video_ocr` (video), `resolve_member_votes` (member ids) | 3 |
| `vote_agenda_items` | `vote_matching`, the adoption promotion, admins | 3 |
| `council_members` | migrations | 3 |
| `agenda_item_badges`, `agenda_item_badges_audit` | the item pipeline, `process_badges`, badge review | 3, 4 |
| `ai_runs`, `ai_response_cache`, `ai_batches`, `ai_batch_items` | the AI pipeline | 4 |
| `city_briefing_facts` | `briefing_facts` | 4, 6 |
| `transcripts`, `transcript_segments`, `transcript_speakers`, `producer_heartbeats` | the transcriber (desktop) | 5 |
| `meeting_video_alignments` | the transcriber's measuring pass | 5 |
| `minutes_texts`, `meeting_events`, `minutes_discrepancies` | `transcript_pipeline` | 5 |
| `agenda_item_search_cards`, `transcript_card_runs` | the search-card stage | 5 |

Schema detail is in the top-level `README.md` ("Database Schema") and the migrations themselves.

## Vocabulary

- **Clip, event, `yt-` row**: a meeting's origin, visible in its `external_id` (chapter 1).
- **Cue point / index point / chapter**: the clerk's marker on the Granicus video for an agenda item; a time in seconds and a chapter id (chapter 2).
- **Ladder, rung**: how a meeting's type, sitting, and body are decided from evidence, strongest first (chapter 2).
- **Adoption**: the later vote that makes a meeting's minutes official; promotes provisional links and triggers the adopted summary (chapters 2–4).
- **Provisional**: a vote-to-item link, or a summary, made from minutes not yet adopted (chapter 3).
- **One source per meeting**: the counting rule; minutes when present, else OCR (chapters 3, 6).
- **Against the outcome**: the dissent definition; a no on a motion that passed or a yes on one that failed; a tabled motion has no outcome (chapters 3, 6).
- **Dollar check**: whether an item's text backs its stored amount well enough for prose to say it (chapter 4).
- **Floor**: a rule that can only raise significance or lower consent placement (chapter 4).
- **Flagged badge**: one the model alone suggested; hidden until a human approves (chapter 4).
- **Card**: either an item's rendered card (chapter 6) or a search card, hidden text that makes an item findable by what was said about it (chapter 5). Context tells which.
- **Alignment / measurement**: where a YouTube recording sits on the Granicus clip's clock; the thing a timed link needs before it may open YouTube (chapter 5).
- **Door**: one of the city page's sections that opens onto a fuller page (chapter 6).

## Known gaps this guide describes as designed

Writing this guide (2026-11-08) surfaced two defects in the vote-derived badge stage, filed as issues #154 (`process_badges` filters a column `agenda_items` does not have) and #155 (its dissent predicate misses OCR's `no`). Chapter 3 describes that stage as designed and notes the defect. Drop this section when both issues close.
