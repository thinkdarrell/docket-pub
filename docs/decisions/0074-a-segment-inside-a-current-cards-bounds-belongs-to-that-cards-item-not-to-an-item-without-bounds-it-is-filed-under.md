# 0074 — A segment inside a current card's bounds belongs to that card's item, not to an item without bounds that it is filed under

## Decision

An agenda item that has no current search card with bounds reads the segments filed under it except those inside the bounds of any current card of the same transcript; the card's item keeps those. The rule has one statement, `PLACED_OWNER_SQL` in `src/docket/services/transcripts.py`, beside `SNAPPED_OWNER_SQL`, and `moments_for_items` and `excerpt_for_item` both use it.

## Rationale

Decision `0073` gave an overlapped segment to one item only where both items have bounds. An item without them (its card says not discussed, the validator dropped its bounds, an incomplete run skipped it, or no card exists yet) took every segment filed under it, so when a neighbour's snapped range reached into those segments the same line was printed under two search results as "What was said at the meeting" and opened two items' excerpts. The closing review of plan `search-finds-what-was-said` showed it on seeded rows.

Three owners were possible. The item the segment is filed under would undo the card's correction wherever a neighbour has no bounds, and those are the likeliest places for it to matter: bounds are dropped, or an item is marked not discussed, because its filed segments are really a neighbour's discussion. The item opened latest, `0073`'s rule with an unbounded item counted as opening at its first filed segment, gives the reviewer's own contested line ("the new late night ordinance is adopted and we move on", filed under the paving item) to the paving item. The item with bounds keeps it: a card's range is the later and better evidence of where a discussion is. The cost is that an item whose every filed segment a neighbour's bounds cover shows no moment and no excerpt, and `0073` already chose silence under an item as the safer error.

The trap is reading `PLACED_OWNER_SQL` as the second statement of the ownership rule that `0073` warns against and folding it away, or restoring the plain `s.agenda_item_id = c.item_id` in either reader.

## Date

2026-11-05, the operator, asked which item keeps the segment, after the closing review of plan `search-finds-what-was-said` (`plans/completed/search-finds-what-was-said.md`, Decision Log); built by Claude on the plan's branch.

## Status

accepted
