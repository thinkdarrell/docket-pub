# 0073 — Snapped bounds are stored on the search card beside the placement and never overwrite it, and where ranges overlap a segment belongs to the item opened latest

## Decision

Where an agenda item's discussion really starts and ends, as a model read it from the transcript, is stored as `start_seq` and `end_seq` on the item's search card and nowhere else: the card stage never writes `transcript_segments.agenda_item_id`, `assignment_method`, or `agenda_items.video_timestamp_seconds`. A reader that wants an item's discussion (`excerpt_for_item`, `moments_for_items`) uses the bounds of a current card when it has them and the placement otherwise, and decides which item an overlapped segment belongs to with the one statement `SNAPPED_OWNER_SQL` in `src/docket/services/transcripts.py`: the item whose range starts latest.

## Rationale

Placement files each segment under the item whose Granicus index point is the latest at or before it, and the clerk's click is approximate: item 58824's placement begins at 1:43:17, ahead of an unrelated exchange, while the item is called at 1:45:10. The obvious fix is to correct the placement, re-filing the segments from the model's bounds, as the events stage already does from a confident `item_opened` event. That would make a model's reading of a machine transcript the fact that the transcript page's item anchors and the search page's lower list read, with no way back to what the city's own index point said and no record of which rows a model moved. Bounds on the card are additive: with no card, a card that is not current, or bounds the validator refused, every reader behaves exactly as before, and deleting a meeting's card rows restores the old behaviour without touching a transcript row.

Bounds are believed only near the placement: the start segment within ten minutes of the filed range and the end segment ending no more than ten minutes after it (`CARD_SNAP_MAX_S`). The prompt tells the model the marker can be off by several minutes; a start ten minutes outside everything filed under the item is more likely a wrong item, and an end limited only by its start could run to the close of the meeting. On the spike's 138 cards with bounds the two limits cost four their bounds, and those fall back to the placement.

Overlap is kept, not clamped or dropped. Items read one after another and voted together are each given the block's ending, so on the spike 77 of 138 ranges overlapped another and 64 shared an end segment; dropping or clamping overlapping ranges would throw away most of what snapping is for. But a line about one item printed under another as "What was said at the meeting" is a sentence the page would get wrong, so a segment is shown under one item only, the one opened latest, which is the rule placement itself uses. Its cost is that a block's shared vote shows under the block's last item alone; silence under the others is the safer error.

The trap is a second statement of the ownership rule (a reader that joins the card table itself and forgets the later-opened test, or the current-card conditions), or a "cleanup" that writes the bounds back into `agenda_item_id` to make the transcript page agree with the excerpt.

## Date

2026-11-04, Claude, in plan `search-finds-what-was-said` (the storage in its authoring; the end limit in its revision of the same day, from an external review the operator supplied, and the one-owner rule found by that revision while checking the review; built in its M2, M3, and M5; `plans/active/search-finds-what-was-said.md`, under `plans/completed/` once the plan closes).

## Status

accepted
