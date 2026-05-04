# Vote-Matcher v2: lifting the 10.7% substantive match rate

**Date:** 2026-05-04
**Status:** Design — pending user review
**Predecessor:** [2026-05-01-vote-agenda-matching-design.md](2026-05-01-vote-agenda-matching-design.md)

## Problem

After the v1 N:M matcher landed, only **10.7% of substantive (one-off) Birmingham votes** are linked to the agenda items they acted on — 1,067 of 9,934. Consent-block coverage is fine (33,303 active links across the meeting set); the gap is concentrated in standalone roll-call votes whose minutes don't carry an explicit resolution number.

Investigation against a concrete failing example revealed the root cause: the substantive matcher reads the wrong field. This spec proposes four compounding fixes to lift the rate without sacrificing precision.

## Diagnosis

**Working example:** Vote 1342 (Birmingham Regular City Council Meeting, 2025-12-16, meeting_id 26).

The minutes for this vote captured all the substance — *"Shield Property Solutions, LLC"*, *"$11,155.25"*, *"Quitclaim Deed"*, *"609 4th Ave N"* — into `votes.raw_text` (1500 chars). The agenda item being voted on (item 20, agenda_item_id 64) has those same words in its title.

The matcher did not link them.

Reason: `_match_substantive` (`vote_matcher.py:189`) calls `_try_item_number_match` and `_try_keyword_match`, both of which read `vote.match_context` — a 200-char window that on this vote contains only procedural language:

> "City Clerk, whereupon Councilmember Smitherman made a motion that unanimous consent be granted to adopt said ordinance, which motion was seconded by Councilmember Tate, and upon the roll being called…"

No "Shield", no dollar amount, no address. The matcher is searching the wrong haystack.

The `resolution_number` tier didn't fire because `votes.resolution_number` is NULL on this row — and on most rows, because the parser only fills it from a narrow extraction pattern that the Dec 16 minutes don't trip.

## Goals

1. Lift the substantive match rate without lowering the precision of links shown to users.
2. Apply the fix to all ~8,867 currently unmatched substantive votes via backfill.
3. Make the matcher's confidence ladder coherent across tiers, so downstream UI / telemetry can rank links honestly.

## Non-goals

- Consent-block matching is unchanged (it already works well).
- No schema changes. `votes.resolution_number` already exists; `vote_agenda_items` schema is sufficient.
- No ML / NER library. All extraction stays deterministic regex + denylist.
- No public-API changes.
- Cross-meeting matching (e.g., adoption of last meeting's minutes) is out of scope.

## Design overview

The substantive matcher today runs three tiers in order:

| Today | Method | Reads | Confidence |
|---|---|---|---|
| 1 | Resolution number | `votes.resolution_number` column | 0.9 |
| 2 | Item number regex | `match_context` (200 chars) | 0.7 |
| 3 | Keyword overlap | `match_context` (200 chars) | 0.5–0.8 |

After this change:

| New | Method | Reads | Confidence |
|---|---|---|---|
| 1 | Resolution number | `votes.resolution_number` (now populated more aggressively — see #1) | 0.95 |
| 2 | Item number regex | `raw_text` (1500 chars) — Tier 0 fix | 0.7 |
| 3 | **NEW: Structured fact** (proper noun + optional dollar) | `raw_text` | 0.8–0.9 |
| 4 | Keyword overlap, **rank-aware** | `raw_text` | 0.5–0.75 |

First tier to return a match wins; tiers don't compete.

**Single source of truth for matcher input:** All tiers that read free text now read `raw_text`, falling back to `match_context` when `raw_text` is NULL (legacy rows).

---

## Tier 0: Haystack swap

**Change:** Replace `vote["match_context"]` references in `_try_item_number_match` (`vote_matcher.py:347`) and `_try_keyword_match` (`vote_matcher.py:368`) with:

```python
text = vote.get("raw_text") or vote.get("match_context") or ""
```

**Stop word expansion.** The wider window picks up procedural language. Add to `_STOP_WORDS`:

```
councilmember councilmembers motion seconded ordinance resolution mayor
ayes nays council presiding officer chairperson whereupon hereby thereupon
adopted approved granted said item agenda
```

`resolution` and `ordinance` are stop-worded for *keyword overlap only* — the resolution-number tier (#1) extracts the literal number before this stage runs.

**`excerpt_context`:** Continue truncating to 300 chars, but pull from `raw_text`. Reuse `_extract_snippet` to center on the matched keyword/dollar/proper-noun so the UI excerpt is meaningful.

---

## #1: Aggressive resolution / ordinance number extraction

**Today's gap:** `votes.resolution_number` is NULL on most rows. The minutes parser uses a narrow pattern; many votes carry an identifier in their `raw_text` that simply wasn't captured.

**New extraction pass.** Pattern:

```python
_VOTE_RES_RE = re.compile(
    r"\b(?:RESOLUTION|ORDINANCE)\s+(?:NO\.?\s*)?"
    r"(?P<num>(?:R|O)?-?\d{1,5}(?:[-/]\d{2,4})?)\b",
    re.IGNORECASE,
)
```

Matches: `RESOLUTION 1854-25`, `ORDINANCE NO. 23-101`, `Resolution No. R-2024-0419`, `ORDINANCE 22/2024`. Restricts separators to `[-/]` to avoid accidental glue onto adjacent numerals.

**Multiple candidates in one raw_text:** Pick the **last** match before the vote tally. That's the one being voted on. Implementation: take the substring of `raw_text` ending at the first match of any of these tally markers (case-insensitive):

```
the vote was as follows
upon the roll being called
ayes:
yeas:
roll call:
roll being called
```

If none of those markers appear, scan the full `raw_text`. Within the resulting substring, take the rightmost regex match.

**Where it runs:**
1. **Inline** in `analysis/minutes_parser.py` for newly ingested votes.
2. **Backfill** at `scripts/backfill_vote_resolution_numbers.py`, iterating `votes WHERE resolution_number IS NULL AND raw_text IS NOT NULL`. Idempotent.

**Persistence:** Extracted numbers are written to `votes.resolution_number`. The column is already used by the meeting-detail UI, so populating it has the side benefit of richer rendering.

**Sequencing:** Backfill must run *before* re-running the matcher so Tier 1 can consume the newly-populated values.

**Validation:** Spot-check the first 50 backfilled rows manually before letting the script finish the full set.

---

## #2: Structured-fact tier

Inserts between item-number and keyword. High-precision tier that requires a proper-noun anchor.

**Entities extracted from `raw_text`:**

1. **Dollar amounts.** Reuse `enrichment/dollars.py`'s extractor. Returns a set of normalized amounts.
2. **Proper-noun phrases.** Regex pass for capitalized 2-4-token sequences:
   ```python
   _PROPER_NOUN_RE = re.compile(r"\b(?:[A-Z][a-zA-Z&]+(?:\s+[A-Z][a-zA-Z&]+){1,3})\b")
   ```
   Filtered against:
   - Council member surnames for the meeting's municipality (live query on `council_members`).
   - Procedural denylist: `City Clerk, Presiding Officer, Council Chamber, City Council, City Hall, Mayor's Office, the City, the Council, the Mayor`.
   - Month names: `January … December`.

**Match rule (per candidate item):**

| Vote ∩ item title | Confidence |
|---|---|
| ≥1 proper noun **AND** ≥1 dollar amount | 0.9 |
| ≥1 proper noun (no dollar) | 0.8 |
| Dollar only (no proper noun) | no match — defer |

**Comparison surface:** Item `title + description`.

**Tie-breaking:** When multiple items match, pick the one with the most overlapping proper nouns. If still tied, return None (defer to keyword tier — don't guess).

**Telemetry:** New `match_method = "structured_fact"`.

---

## #3: Rank-aware keyword tier

**Today's behavior** (`vote_matcher.py:368`): score every item by Jaccard-like overlap, take the best, commit if ≥ 0.3. No awareness of the runner-up.

**Change:** Compute scores for all items, sort, then commit only if **both**:

1. `best ≥ 0.25` — lowered floor; the rank gate provides safety.
2. `best ≥ second_best * 1.5` **OR** `best - second_best ≥ 0.15` (whichever is more permissive).

**Confidence formula:**

```python
margin = best - second_best
conf = round(min(0.5 + best * 0.3 + margin * 0.5, 0.75), 2)
```

Capped at 0.75 so keyword overlap can't out-confidence the structured-fact tier.

**Edge cases:**

- **Single candidate:** A meeting with one agenda item has no second-best. Fall back to today's absolute threshold (≥ 0.3), no margin gate.
- **Already-matched items:** Don't filter them out of the candidate pool. Two votes can validly link to the same item (e.g., a reconsideration vote).

**Telemetry:** Keep `match_method = "text_similarity"`. Log score margin to `logger.debug`. Don't add a column.

---

## Backfill & rollout

**Sequencing:**

1. Apply code changes locally; unit tests green.
2. Sync Railway → local using `pg_dump` from `postgresql@18` (Railway is on PG 18; local is 16).
3. **Locally:** run resolution-number backfill over `votes WHERE resolution_number IS NULL AND raw_text IS NOT NULL`. Batch, transactional. Spot-check 50 rows.
4. **Locally:** run `match_all_unmatched()` with the new tiers. Capture deltas: new rows in `vote_agenda_items`, updated rows in `votes`.
5. **Push to Railway** via staging table + single `UPDATE … FROM staging` for `votes`, and `COPY` + `INSERT … ON CONFLICT` for `vote_agenda_items`. **Do not** stream per-row UPDATEs (per the standing operational note).
6. **Validate on Railway:** count new matches by `match_method`; spot-check 20 random new links via the production UI; confirm zero changes to `is_manual=TRUE` rows.

**Snapshot/rollback.** Before step 5, snapshot Railway's `vote_agenda_items` and `votes` to `vote_agenda_items_backup_2026_05_04` and `votes_backup_2026_05_04`. Restore from those if validation fails. Drop after a stability window.

**No migration required.** All four changes are code + data; the schema is unchanged.

---

## Testing

TDD. New unit tests live in `tests/unit/test_vote_matcher_v2.py` — leaving `test_vote_matcher.py` as a baseline for the v1 behaviors that remain valid.

**Required test cases:**

- **Tier 0 regression (vote 1342 fixture):** procedural-only `match_context`, substantive `raw_text` → keyword tier links to the correct item.
- **Resolution extraction:**
  - `RESOLUTION 1854-25` → `1854-25`
  - `ORDINANCE NO. R-2024-0419` → `R-2024-0419`
  - `ORDINANCE 22/2024` → `22/2024`
  - Multiple resolutions referenced; picks last before tally marker.
  - No resolution → returns None.
- **Structured-fact tier:**
  - Proper noun + dollar in both vote and item → conf 0.9.
  - Proper noun only → conf 0.8.
  - Dollar only → no match.
  - Two items both share the proper noun → tie → no match (defer).
  - Council member surname is filtered out of proper-noun set.
- **Rank-aware keyword:**
  - Best 0.4, second 0.39 → no match (margin gate).
  - Best 0.4, second 0.15 → match.
  - Single-candidate meeting → falls back to absolute threshold.
- **Stop-word expansion:** `raw_text` containing only procedural words ("councilmember", "motion", "seconded") does not produce a match against an item title that contains the same procedural words.
- **Manual-shield regression:** `vote_agenda_items` rows with `is_manual=TRUE` are not overwritten by any new tier.

**Integration test:** captured Birmingham meeting fixture; run `match_votes_for_meeting`; assert the expected delta of new links.

---

## Open items

- **Tier ordering vs confidence inversion.** Tier 2 (item-number regex, 0.7) runs before Tier 3 (structured-fact, 0.8–0.9). If both would fire and disagree, we accept the lower-confidence match. The ordering choice (specific identifier first, then implicit substance) mirrors the v1 matcher's design and keeps the v2 change contained — but a future iteration could score all tiers and pick the highest-confidence hit. Out of scope for this spec.
- **Confidence values.** 0.95 / 0.7 / 0.8–0.9 / 0.5–0.75 are starting numbers. Tunable after we observe the post-backfill distribution.
- **Margin gate constants.** 1.5× / +0.15 / floor 0.25 in #3 are starting numbers. Same.
- **Procedural noise.** If the expanded stop-word list still leaks into keyword matches in practice, consider stripping a known procedural-preamble prefix from `raw_text` before tokenizing.
- **Proper-noun denylist breadth.** The starting list is intentionally short. Will likely grow as we observe false positives in the backfill spot-checks.

## Out-of-scope follow-ons

- Cross-meeting linking (e.g., the *"approve minutes from prior meeting"* item linking back to that meeting's vote roster).
- Surfacing a "needs review" admin queue for low-confidence matches.
- Tiered display in the UI (dim low-confidence links, separate "probable matches" section). The current display is binary linked / unlinked; this spec preserves that.
