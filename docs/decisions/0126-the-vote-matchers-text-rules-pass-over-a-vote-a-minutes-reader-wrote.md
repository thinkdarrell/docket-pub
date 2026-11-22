# 0126 — The vote matcher's text rules pass over a vote a minutes reader wrote

## Decision

A vote written by a minutes reader carries the reader's name in `votes.minutes_reader`, and `_match_substantive`, `_match_consent_block` and `match_all_unmatched` in `src/docket/analysis/vote_matcher.py` select only votes where it is NULL. A reader vote is attached to an agenda item by the code the minutes print and by nothing else (`link_votes_by_code` in `src/docket/services/minutes_votes.py`).

## Rationale

The matcher's keyword and consent-block rules were written for Birmingham's minutes, and the daily `vote_matching` task applies them to every meeting that has a `minutes_text` vote with no active attachment. Mobile's minutes hold a motion to suspend the rules for "consent resolutions being introduced"; read by the consent-block rule it would be attached to every consent item of its meeting. Mobile's minutes instead print the item's code beside its vote, and the agenda item's title opens with the same code, so the join is exact where it exists and absent where it does not.

The gate could have been the city (skip Mobile) or the city's setting. A marker on the row was chosen because it holds when the setting is later removed or a second city gets a reader, and because the question the matcher needs answered is who wrote the row, not where it sits. The third SELECT, `match_all_unmatched`, does not name `minutes_text` and was gated too: without it the task would visit every Mobile meeting every day to attach nothing.

This changed which votes the matcher's rules apply to and left the module's shape alone; that it opens its own transactions from under `analysis/` is still `D111` in `docs/DEBT.md`.

## Date

2026-11-21, the authoring session of plan `mobile-votes-from-minutes` (Claude); built by that plan's M2 and graduated by its M6 session on 2026-11-22 (UTC).

## Status

accepted
