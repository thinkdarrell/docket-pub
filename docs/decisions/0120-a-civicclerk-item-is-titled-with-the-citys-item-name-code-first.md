# 0120 — A CivicClerk item is titled with the city's item name, code first

## Decision

A CivicClerk agenda item's stored title is the city's item name alone, with the "(sponsored by ...)" and "(submitted by ...)" parentheticals taken out by the adapter. The city's file number stays in `item_number` and is never put before the title; `sponsor` is the "sponsored by" value; the submitter is kept as the sentence `Submitted by <value>.` at the end of the description. An item is a consent item when the nearest heading above it has "consent" in its name. No column holds the ordinance or resolution code: it is the first word of the title, recoverable with `^(\d{2}-\d{3,4})\b`.

## Rationale

The adapter used to title an item `"<file number> <name>"`, which gave `2026-2408 01-1211 Authorize Agreement ...`. The code the city's minutes print for a vote (`RESOLUTION: 40-948-2026`) is the first word of the item's name and is in no other field of the city's answer: `ordinanceNumber`, `resolutionNumber` and the formatted forms were unset on every item read. The work that joins Mobile's votes to items needs that code, and a title that begins with a file number hides it. A test holds that the code survives ingest's enrichment.

The parentheticals are split in the adapter and not in `src/docket/enrichment/sponsors.py` because Birmingham's titles pass through that module. Left to enrichment, which tries "(Submitted by" before "(sponsored by", about half of Mobile's coded items were given the city attorney as their sponsor (28 of the 60 items of the 2026-11-03 agenda carry both), and the cleaned title was left ending `$7,500,000.00  .`. After the split the title holds no attribution, so enrichment finds none and ingest keeps the adapter's sponsor.

The consent mark follows the heading because that is how the city says it: the items sit under `CONSENT RESOLUTIONS HELD OVER` and `CONSENT RESOLUTIONS BEING INTRODUCED`, and none has "consent" in its own name, so the old rule marked none. Carrying the mark at ingest costs a few lines; carrying it later means fetching and summarising about 6,800 items again. The Granicus adapter's rule is untouched.

## Date

2026-11-20, the authoring session of plan `mobile-agendas-flow-again` (Claude); the consent rule added the same day by the operator's review revision; built by that plan's M2 and graduated by its M6 session the same day.

## Status

accepted
