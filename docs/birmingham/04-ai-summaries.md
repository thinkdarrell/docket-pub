# 4. Summaries, scores, and badges

This is the one stage where a language model touches Birmingham's records, and it is fenced on every side: the model sees only the item's own text, its output is checked against deterministic facts and floored by rules, every sentence is stored with the prompt version and the time it was generated, a daily budget stops the whole thing, and anything the model alone asserts is flagged for a human. The code is `src/docket/ai/`; `docs/specs/calibration.md` covers the daily check on the scores; decisions `0011`–`0019` and `0027`, `0028` record the policy. The models themselves, and their prices, are named in `src/docket/config.py` and `src/docket/ai/pricing.py`; a model with no price entry cannot run.

## The item pipeline

Every morning `ai_items` claims up to 200 agenda items whose `processing_status` is `pending` and whose extraction or rewrite version is below the current one, newest meeting first (`0015`), and runs each through `pipeline.process_item`:

**Wave 0, no model** (`wave0.py`). Three checks, in order, each of which ends the item's processing:

1. A withdrawn or deferred item is marked `withdrawn` and gets no text and no scores (`0019`). It stays out of the money prose and the counts.
2. A procedural item (roll call, pledge, invocation, "minutes not ready", …) is marked `procedural_skipped` and gets no text and no scores (`0012`). It renders as a one-line row.
3. An item with no usable text is marked `data_quality_skipped` with the reason (`no_text_layer`, `no_agenda_text`, `empty`, `foreign_language`) and a priority; these are the rows the **data debt** page lists. A long title can stand in for a missing body (`0017`), and a "big fish" title bypasses the gate.

**Stage 1, extraction** (`extraction.py`, versioned by `EXTRACTION_PROMPT_VERSION`). The item model returns structured facts through tool use: funding source, counterparty, procurement method, location, action type, next steps, parcels and acres. These are stored as `extracted_facts` and shown on the card's facts strip.

**Stage 2, the rewrite** (`rewrite.py`, `ITEM_REWRITE_PROMPT_VERSION`; the upcoming-meeting voice is a 100-series version, `0016`). The item model returns whether the item is substantive, a headline of at most 80 characters, a "why it matters" of at most 280, two 0–10 scores with rationales (**significance**, how much a resident should care; **consent placement**, how much an item of this weight belongs on a consent agenda), suggested badge slugs, and a confidence. A non-substantive answer must have every field empty (`0031`). The voice is `upcoming` when the meeting has not happened yet, Chicago time; an upcoming meeting's card shows the raw title and no "why it matters" (chapter 6), and the `recast_post_meeting_ai` task re-queues the item the morning after the meeting so it is rewritten in the past tense.

**Reconcile** (`reconcile.py`). If Stage 2 called the item procedural but Stage 1 found a counterparty, a funding source, an amount of $50K or more, or a high-attention action type, Stage 2 is retried once with that evidence. A second disagreement is `cross_stage_conflict`: the card reads "Verification in progress" and the item waits in the admin queue; it is never re-claimed automatically.

**Stage 2.5, the floors** (`floors.py`). Rules move the model's scores in one direction only: significance can only rise, consent placement can only fall. The triggers are the facts, not the prose: a red-tier amount, a sole-source award at orange tier or above, any settlement, surveillance or licence-plate readers, police oversight, eminent domain, a red-tier item on the consent agenda. Per-city thresholds live in `city_score_floor_overrides`. Both the model's original and the final score are kept in `score_overrides`, with the triggers that fired, which is what the calibration report compares.

**Phase C, the write.** In one transaction the item receives its `headline`, `why_it_matters`, the two final scores, `ai_confidence`, `ai_rewrite_version`, `ai_rewrite_voice`, `ai_generated_at`, `processing_status = completed`, and its badges. `GOALS.md` makes this a success condition: no AI sentence is shown without its prompt version and timestamp on the same row. Template gates compare versions with a floor (`>=`), never equality (`0014`), so a reprompt does not blank the site.

## Badges

A badge is a row in `agenda_item_badges` with a `kind`, a `confidence`, a `source`, and a `status`. Policy and definitions live in `src/docket/ai/badges_policy.py` and the `priority_badge_templates` table, and nowhere else (`docs/PRINCIPLES.md`, "One owner per fact").

- **Process badges written at Phase C** from the facts: `hidden_on_consent` (a consent item whose final consent-placement score is low enough, with a floor fired or good confidence), `sole_source`, `legal_settlement`, `emergency_action`. Always `applied`.
- **Process badges from the votes** (`split_vote`, `contested`, `amends_prior_contract`) are chapter 3's, with its known defect.
- **Policy badges** (housing, surveillance, and the rest of the city's enabled list) are decided by `decide_status_and_confidence` (`0018`): when the model suggests one *and* a deterministic signal (keyword, action type, or topic) agrees, it is `applied` at 1.0; a deterministic signal alone is `applied` at 0.8; **the model alone is `flagged` at 0.4** with an audit row, and a flagged badge is not shown until an admin approves it in `/admin/badge-review`. A suggestion for a badge the city has not enabled is dropped.

Badges drive the landing pages (`/al/birmingham/<badge_slug>/`), the "What they keep dealing with" door, the signals list, and the primary chip on each card.

## The meeting summary

`ai_meetings` writes the **executive summary** at the top of a meeting page in two phases (`0011`): a **provisional** pass once every item of the meeting has finished the item pipeline, and an **adopted** pass once the minutes are adopted (chapter 2), so the summary can say what was decided with the official record behind it. The meeting model is shown the **distinctive** items, those whose significance is 6 or above, in full, and the rest grouped by topic with counts (`0013`), and writes to `meetings.executive_summary` with its voice, phase, confidence, model, prompt version, and timestamp. The page labels the summary "Provisional · minutes not yet adopted" or "Adopted", and "Auto summary — under review" at low confidence (chapter 6).

## The fences

- **Budget.** Every call records an `ai_runs` row with its token usage and cost. When the day's cost since UTC midnight reaches `AI_DAILY_BUDGET_USD`, the gate raises and the task logs a skip; nothing runs past it. `/admin/ai` shows the day.
- **Cache.** `ai_response_cache` is keyed by model, prompt version, and input hash, so a re-run of an unchanged item costs nothing; entries unused for 90 days are pruned.
- **Batches.** Large backfills go through the Anthropic Batches API from the operator's CLI (`src/docket/ai/cli.py --wave N --stage S`, always with a limit; `docs/PRINCIPLES.md`, "Production is not a sandbox"); the worker's half-hourly `process_batches` collects the results into the same Phase C write.
- **Every call site mirrors `client.py`** (`0027`), and a pipeline change is compared old against new on real rows before it ships (`0028`; the transcript A/B harness in chapter 5 is one such comparison).
- **Calibration.** The daily `calibration_report` logs where the floors moved scores by more than three points in a day, where a prompt version under- or over-scores an action type, and where a badge's weekly volume drifts from its twelve-week baseline; `/admin/calibration` shows the same six panels (`docs/specs/calibration.md`; `0042`, `0043`).

## Where prose meets numbers: the dollar check

The city page's opener and money door, the quote door, and the amount-ordered search all run an item's stored amount through `passes_dollar_check` before saying it aloud (`src/docket/services/briefing.py`; `0060`): either the item's own title and description contain exactly one amount and it equals the stored one, or the model's headline carries a figure close enough to it. An amount that fails the check still shows as the card's dollar chip, because the chip is the extraction; it does not appear in a sentence, because a sentence is a claim.

## What a reader can hold the pipeline to

- No AI text without its prompt version and generation time on the same row.
- No scores and no text on procedural or withdrawn items; NULL scores until the pipeline has run.
- No badge on the model's word alone without a human's approval.
- No sentence in the opener or the doors written by a model: the briefing is composed from facts (chapter 6).
- No spend past the daily budget; no unbounded batch.
- No "on the other hand" the record does not contain (`docs/PRINCIPLES.md`, "Framing follows the data").

Next: [5. Video, transcripts, search, and the timed link](05-video-transcripts-search.md).
