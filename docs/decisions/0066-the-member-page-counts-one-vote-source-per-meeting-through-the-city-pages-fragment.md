# 0066 — The member page counts one vote source per meeting through the city page's fragment, lists every row with its source, and its Dissent view is the against-the-outcome predicate with or without a date

## Decision

`get_member_stats` and the counts of `get_member_vote_summary` in `src/docket/services/query.py` join each member vote through `briefing.chosen_source_cte` (decision `0056`), scoped to the member's non-hidden meetings and reached by a function-local import, so a member's attendance, alignment, and roll-call total count one source per meeting with flagged votes excluded, and the rule is written in one place. The history lists every row carrying the member's id, each with its source shown. `list_member_voting_history` applies `AGAINST_OUTCOME_PREDICATE` to the Dissent filter whether or not `since` is given (decision `0057`).

## Rationale

A meeting that holds both a minutes vote and a video vote on one motion gave the member page two roll calls for one position (`D68` in `docs/DEBT.md`, observed on the throwaway database as `votes_total: 2, attendance_pct: 100` for one meeting and one member), and the daily resolver (decision `0062`) makes that visible on every meeting of the window that has both sources once its one-time sweep runs (`D66`). Three ways to count were open. Counting every row is the double count. Choosing per motion would need the reconciliation `D28` defers and would mix the two sources inside one number. Choosing per meeting, minutes first, is the rule the city page's council card already counts under, so the member page prints the same roll-call total as the card over the same meetings and the rule has one owner; writing it a second time in `query.py` would let the two drift, and the function-local import is the price of `briefing` importing `query` at module level. The history is not a count: it lists both rows so the reader sees what each source recorded (`docs/PRINCIPLES.md`, Keep the sources apart), the source column tells the two rows apart, and a flagged vote is listed for the same reason and counted nowhere.

The undated Dissent view had kept an older filter that listed an abstention and any present vote on a tabled motion as dissent (`D58`, carried by decisions `0056` and `0057` because the city page design excluded the member page beyond `since`). With the stat strip counting under the card's rule, two definitions of dissent on one page would leave the strip and the list disagreeing about the same member; the swap is one predicate and one test, so it is paid here rather than left.

## Date

2026-10-20, the plan author (Claude, cycle-plan) from the operator's goal, in `plans/active/member-page-counts-one-source.md`, written in its M1.

## Status

accepted
