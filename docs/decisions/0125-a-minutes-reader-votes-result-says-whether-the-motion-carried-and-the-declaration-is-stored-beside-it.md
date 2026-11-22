# 0125 — A minutes-reader vote's `result` says whether the motion carried, read from the declaration and the motion, and the declaration is stored beside it

## Decision

`votes.result` on a row a minutes reader writes is `passed`, `failed` or `unknown` and means "the motion carried", decided from what the presiding officer declared and, for the word `denied`, from the motion; it is never `tabled` or `held over`. The declaration itself is stored in `votes.declared_text` and is what a page prints. A vote whose declaration was not read (`declaration_not_read`), says `denied` where neither the motion nor the count settles which side prevailed (`declaration_ambiguous`), or says the motion carried with fewer ayes than nays (`declaration_contradicts_count`) is stored with `needs_review` true and that `review_reason`. What a page prints and how it is coloured are the two functions `vote_label` and `vote_tone` in `src/docket/models/vote.py` and nothing else.

## Rationale

The obvious rule is to store what the minutes say: `denied` as `failed`, `tabled` as `tabled`. But what Mobile's minutes declare is about the thing voted on, not the motion: "declared the waiver denied" follows a 7 to 0 vote on a motion to deny. The member page counts a yea on a `passed` vote as voting with the outcome and a yea on a `failed` one as against it (`query.AGAINST_OUTCOME_PREDICATE`, decisions `0057` and `0066`), so that row stored as `failed` would list seven members as dissenting on a unanimous vote. Birmingham's minutes rows already mean "the motion carried"; keeping that meaning lets every counting query read Mobile's rows unchanged, and the declaration, stored whole, keeps the minutes' own words for the reader.

The other obvious rule is Birmingham's, to count the names. In Mobile's minutes `failed` follows 4 ayes to 2 nays and 5 to 2 on ordinances, which need more than a majority of those voting, so a count would call a failed ordinance passed. The declaration is the city's own statement of the outcome; the count is used only to break the one ambiguous word and to flag a contradiction.

Flagging instead of guessing: 14 of the 8,354 votes read on 2026-11-21 are of the three kinds (7, 5 and 2), among them two votes of 2025-11-18 declared carried at 1 aye to 5 nays, which read as the clerk's two lines exchanged. A flagged vote is shown with its callout and not counted, the rule every other flagged vote already follows; deciding which line the clerk meant is not a parser's to do.

The tone is neutral for a declaration that says `tabled`, `held over`, `laid over` or `withdrawn`, because a carried motion to table decided nothing about the item, and green would say it passed. `failed` or `denied` in the declaration is tested first, so a carried motion to deny is red: the reader sees what happened to the thing, while the count behind the member page sees who prevailed.

## Date

2026-11-21, the authoring session of plan `mobile-votes-from-minutes` (Claude), `laid over` and `withdrawn` added the same day from an outside review; built by that plan's M1, M2 and M5 and graduated by its M6 session on 2026-11-22 (UTC).

## Status

accepted
