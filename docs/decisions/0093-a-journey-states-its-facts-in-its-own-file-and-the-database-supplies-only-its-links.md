# 0093 — A journey states its facts in its own file, and the database supplies only its links

## Decision

A journey on the "How it works" page carries every date, tally, name and quotation in its own YAML file, with the kind of record each rests on; `resolve_journey` reads the database only to decide which links a stop may carry. A meeting that is missing, hidden or another city's, or an item that is missing or belongs to another meeting, costs a stop those links and never its text, and the marks on the path ("in the record", "not in the record", "not on this item's route") come from the file alone. Every journey accounts for every main stop of the path, as recorded, as `none` with the reason no record shows it, or as `not_on_route` with the reason.

## Rationale

The obvious alternative is to store ids and render the facts live: read the tally from `votes`, the date from `meetings`, the title from `agenda_items`. That fails in two ways this site already knows. Vote rows are re-created by a re-parse, so their ids are not stable, and a journey whose vote id vanished would lose its tally or, worse, show another vote's. And a live tally changes under the reader when a later pass corrects a row, on a page whose whole claim is that a person traced this item through the records and wrote down what they show. A hand-checked fact with a link to the city's document is stable; when the linked row is gone the reader loses a convenience, not a fact.

The marks follow the same rule. Marking a stop "not in the record" because its meeting row was hidden would turn a missing row in this database into a statement about the city's records.

Requiring every main stop to be accounted for keeps the path the same shape for every journey. A stop a journey said nothing about would be drawn blank, which reads as "a rezoning is never submitted"; a blank that carries a written reason is a statement someone can check.

The cost is that a journey does not correct itself: when adopted minutes replace a tally read from video, someone edits the file (`D124` in `docs/DEBT.md`). That is the intended cost. The trap is reading "just the tally" or "just the title" from a row because the id is already in the file.

## Date

2026-11-12 (facts in the file, links from the database) and 2026-11-13 (every main stop accounted for, after the external review of the plan), the operator and Claude, in plan `how-it-works-explainer` (built in its M3 and M4).

## Status

accepted
