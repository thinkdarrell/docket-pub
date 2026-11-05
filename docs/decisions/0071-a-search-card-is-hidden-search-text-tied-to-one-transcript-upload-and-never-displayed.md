# 0071 — A search card is hidden search text tied to one transcript upload, validated by the citation guard, and never displayed

## Decision

What a model writes about an agenda item from the meeting's machine transcript (`agenda_item_search_cards`: aliases, spoken details, identifiers, names and their variants, an outcome word, a `refers_to` sentence, and snapped bounds) reaches a reader only as search text folded into `agenda_items.search_vector` and as a choice of which transcript segments a page shows; no field of a card is rendered on any page. A card belongs to the upload it was written from (`source_uploaded_at` equal to `transcripts.uploaded_at` makes it current), a spoken detail is stored only when `find_citation` finds its quote at the cited segment or the two spoken segments either side, and the card stage records its work in `transcript_card_runs` and never writes the `transcripts` row.

## Rationale

The obvious alternative is to show the card: a model's one-line account of what was said about an item, with its outcome, is exactly what a results page wants under a title. That would put sentences on the site that no person reviewed and no city document says, beside a link that makes them look sourced: the violation `docs/PRINCIPLES.md` names under Source or silence, and the one the comparison stage avoids only by putting a person's approval between a model's finding and the page. Hidden text can be wrong and cost nothing worse than a poor result; a displayed sentence that is wrong is the site misreporting a council. So the card finds the item and the page shows the transcript's own segments, labelled "machine transcript", each linked to its place in the transcript. The moments under a result are therefore chosen by matching the transcript's words, not from the card's `spoken_details`, even though the details are stored and cited.

The guard is applied anyway, to text nobody sees, because the details are search text at weight C and a detail the transcript does not support makes an item findable by something that was never said. The rule is the spike's (a detail survives only when its quote is in the cited turn), widened to two segments either side because production input is one segment a line and a quote of several words can straddle a boundary. A dropped detail leaves the rest of its card.

Tying a card to `uploaded_at` and not to `transcripts.version` or the row's id: the row survives a re-transcription, the version is the producer's output format and repeats on a same-producer re-run, and `upload()` replaces the segments and sets `uploaded_at` in one transaction, so that timestamp is the one value that changes exactly when the `seq` numbers a card cites stop meaning what they meant. A card that is not current keeps its hidden text (the same meeting, heard by an earlier transcription; deleting it would make the item unfindable for the days the new transcript takes to pass the stages) and loses its bounds and cited segments for every reader.

Keeping the bookkeeping out of `transcripts`: `status` has a CHECK list, the public predicate reads `uploaded_at` and `status`, the producer's busy guard reads `last_attempted_at`, and the comparison keys on `compare_skipped_reason`. A stage that writes none of them cannot change what any of their readers sees, and a meeting can legitimately yield zero cards, so a marker per transcript is needed beside the card rows.

The trap is rendering a card field because it is already there and reads well: a `spoken_details` sentence under a result, an `outcome` chip, an alias as a heading. Any of them needs the review and source flag this decision exists to avoid, and a decision of its own.

## Date

2026-11-04, the operator (the goal: hidden cards, shown transcript lines) and Claude, in plan `search-finds-what-was-said` (authored and revised 2026-11-04; built in its M2 to M5 and M7; `plans/completed/search-finds-what-was-said.md`).

## Status

accepted
