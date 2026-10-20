# 0063 — The member-vote resolver builds its own name variants and does not share the OCR roster's name builder

## Decision

`name_variants` in `src/docket/services/member_votes.py` builds the short forms of a council member's name itself and does not import `_to_initial_lastname` from `src/docket/analysis/ocr/rosters.py`, although the initial-dot-surname form (`C. Woods`) is built in both places. The two builders are not merged, and neither is changed to match the other.

## Rationale

The obvious alternative is one shared builder: the layer map allows a service to import from `docket.analysis`, and the overlap is two lines. It was rejected because the two forms are already different rules with different owners, and a merge would couple them. The OCR builder's output is the key of the `member_map` that spatial matching on video frames uses, so any change to it is a pipeline change that decision `0028` says is compared old against new on real frames before it ships, and the plan that wrote the resolver (`member-votes-name-their-member`, 2026-10) had no frames to compare on. The resolver drops a generational suffix and the OCR builder does not: `Paul S. Simmons II` (Homewood's roster) is `p. simmons` to the resolver, the form the minutes would print, and `P. II` to the OCR key. A shared builder would change the OCR key on the day the suffix rule is applied to it, without the comparison `0028` requires; two builders let the minutes rule and the frame rule move separately. `docs/specs/votes.md` names the overlap, and this record is what stops a later tidy-up from removing it.

## Date

2026-10-20, the plan author (Claude) in the Decision Log of `plans/completed/member-votes-name-their-member.md`; graduated at the plan's close.

## Status

accepted
