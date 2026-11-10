# 3. Votes, members, and the facts on an item

Chapter 2 left a meeting with its agenda items and, when it had minutes, its votes. This chapter is how those become facts a reader can rely on: which document a vote was read from, which agenda item it decided, which council member each position belongs to, and the deterministic facts (amount, sponsor, topic) on every item. Nothing here calls a language model; chapter 4 is where the model starts. `docs/specs/votes.md` owns the rules; decisions `0004`–`0010`, `0021`, `0056`, `0062`, `0063`, `0083` record why.

## Two sources of votes, kept apart

Birmingham is the only city with votes, and its votes come from two documents that never merge (`docs/PRINCIPLES.md`, "Keep the sources apart"; decision `0005`):

| | Official minutes | Video OCR |
| --- | --- | --- |
| Read from | the minutes PDF, text-extracted | frames of the Granicus clip, where the vote tally appears on screen |
| Code | `src/docket/analysis/minutes_parser.py`, run inline by ingest (chapter 2) | `src/docket/analysis/ocr/`, run by the daily `video_ocr` task through `src/docket/services/video_ocr.py` |
| `votes.source` | `minutes_text` | `video_ocr` |
| Confidence | `high` | `high`, or `medium` when flagged |
| Positions in `member_votes` | `yea`, `nay`, `abstain`, `absent`, under the name as printed | `yes`, `no`, `abstain`, `absent`, under the on-screen name |
| Available | once the clerk posts minutes, days to weeks after the meeting | the morning after the clip appears |
| Shown to readers as | "official minutes" | "video OCR", with a callout asking the reader to verify against the video |

**From the minutes.** The parser finds the roll call ("Present on Roll Call … Absent …") and every vote block ("the vote was as follows … Ayes … Nays … Abstain"). More ayes is `passed`, more nays `failed`; a tie is `passed` because the council president breaks ties; minutes never yield `tabled`. Each vote keeps the resolution or ordinance number found just before it, the text around it, and whether it sits in a consent block. Members absent at the last roll call are added as `absent` unless they voted. Attendance is not a table of its own; it survives as those `absent` rows.

**From the video.** The OCR job claims up to five recent Birmingham clips a day with `FOR UPDATE SKIP LOCKED` and an attempt counter, so a crash never leaves a clip stuck (`0021`). It streams frames from Granicus, finds the vote-board sequences, reads the terminal frame's header ("Motion Passes / Fails / Tabled") with Tesseract, reads the three coloured count boxes, and places each member's position by where their name sits in the known board layout for that date's roster. A cross-check between the header and the counts yields exactly one of five `review_reason` codes when they disagree or the read failed (`docs/specs/votes.md` lists them); such a vote is stored with `needs_review` and **excluded from every count on the site**. OCR is the reason the worker's memory constraint exists (chapter 7).

A reader sees both when both exist, and the rule for *counting* is one source per meeting: the minutes when the meeting has them, OCR otherwise (`0056`, chapter 6). A disagreement between them is displayed as a disagreement, never reconciled in code (reconciling them is unbuilt, `D28`).

## Which item did the vote decide?

Granicus minutes do not say which agenda item a vote belongs to in any structured way, so the matcher in `src/docket/analysis/vote_matcher.py` has to work it out. Links live in `vote_agenda_items`, many-to-many (`0006`), each with how it was made (`match_method`), how sure (`match_confidence`), whether it is `provisional`, whether an admin made it (`is_manual`), and whether it is still `is_active`. The daily `vote_matching` task runs three strategies in order for every meeting with an unlinked vote:

1. **By timestamp**, for video votes only: the agenda item whose cue point (chapter 2) is the latest at or before the vote's second on the clip. When the vote falls within fifteen seconds *after* a cue point, it is attached to the item *before* that cue, because the clerk advances the chapter as the result is announced (`NEAR_CUE_S`; `0083`, PR #145, issue #142). Confidence falls with the gap and is halved for a flagged vote.
2. **By substance**, for minutes votes that are not consent votes: the resolution number, then the item number, then shared proper nouns and amounts between the vote's text and an item's text (seated members' surnames excluded), then title similarity. First hit wins.
3. **The consent block**: a consent vote is linked to every consent item of the meeting, as `consent_named` when the minutes call the item out and `consent_implicit` otherwise, and **every one of these links is provisional** (`0007`).

**Provisional, and promotion.** A consent link is a guess about which items the block covered, made from minutes the council has not yet adopted. When the adoption sweep (chapter 2) stamps `minutes_adopted_at`, the matcher re-downloads the adopted PDF and parses its enumerated resolution list: items on the list are promoted to non-provisional; a link is deactivated **only** when its item is absent from the list *and* a separate explicit vote on that item exists in the same meeting, which is positive evidence that it was pulled from consent (`0009`); an empty list changes nothing. Readers see "provisional" or "adopted" on every vote (chapter 6).

**Manual links are shielded** (`0008`): an admin's link is never updated or deactivated by any automated pass; every write carries `WHERE is_manual = FALSE`. The known unknown in `GOALS.md` applies here: most minutes votes still have no linked item, and the site leaves them unlinked rather than guessing.

## Which member is "Smitherman"?

`member_votes.member_name` holds the name as the minutes printed it or the OCR read it. `council_members` (seeded and maintained by migration, never a hand-kept map; `0004`) holds each member's district and term. The resolver in `src/docket/services/member_votes.py` builds variants of each member's name (surname, initial-dot-surname, forms without the apostrophe or hyphen), normalises curly apostrophes and case, and matches a stored name to the one member whose term covers the meeting date. Two candidates, or no date, leave the row unresolved. It runs at insert for minutes votes and once a day (`resolve_member_votes`) over every unresolved row of any source, writing one `UPDATE` per name (`0062`). It **never deletes**: a row that stays unresolved is one of three things, a member not on the roster for that date (`D67`: five members' pre-2025 terms are not seeded), parser noise ("Friday"), or an ambiguous surname, and the row stays as evidence. The OCR layout's own name-building is deliberately separate (`0063`).

`council_member_id` is what the council cards, the member pages, and "with Smitherman voting no" in the opener depend on; `docs/specs/votes.md` says what the member page counts and what an unresolved row means there.

## The deterministic facts on an item

At insert (chapter 2), and again on backfill, `src/docket/services/enrichment.py` writes four things from the item's own title and description, with no model involved (`src/docket/enrichment/`):

- `dollars_amount`: the **largest** amount mentioned, in any of the forms `$X million`, `$XK`, or `$1,234.56`. Its display tier (green under $50K, yellow under $250K, orange under $1M, red at $1M and up) is computed at render time by `web/filters.py`, not stored.
- `sponsor`: from "(Submitted by …)" or "(sponsored by …)", else what the adapter saw.
- `topic`: one keyword slug (zoning, public safety, public works, budget, grants, contracts, legal, parks and culture, licensing, appointments, …), first match wins.
- `significance_score` and `consent_placement_score`: **NULL** until chapter 4's pipeline scores the item.

The amount is a candidate, not a fact the prose may quote: chapter 4's dollar check decides whether the city page may say it.

## Badges that come from votes

Three **process badges** are meant to be recomputed nightly from the votes themselves by the `process_badges` task (`src/docket/ai/badges_process.py`): `split_vote` (at least one dissent), `contested` (two or more, and over a fifth of those voting), and `amends_prior_contract`. "Dissent" here is a `nay` or an `abstain`. These feed the `/al/birmingham/split_vote/` landing and the signals list.

> **Known defects.** As the migrations stand, the task's first query reads a column `agenda_items` does not have, so it errors on every run and its wrapper swallows the error (issue #154); and its dissent predicate counts `nay`/`abstain` but not OCR's `no`, which the rest of the site normalises (issue #155). Until both close, these three badges are not being written.

The other process badges (`hidden_on_consent`, `sole_source`, `legal_settlement`, `emergency_action`) are written by the AI pipeline's final step from the item's facts, chapter 4.

## What is never guessed here

- A vote with no matching item stays unlinked; a provisional link is labelled so until adoption promotes it.
- An unresolved member name stays NULL and is never deleted.
- A flagged OCR vote (`needs_review`) is listed, labelled, and excluded from every count.
- A tie is `passed` by the council's rule, not by assumption; an adoption date is parsed from the item's title or the sweep skips it (`0010`).
- Minutes and OCR rows never share a column without their `source`.

Next: [4. Summaries, scores, and badges](04-ai-summaries.md).
