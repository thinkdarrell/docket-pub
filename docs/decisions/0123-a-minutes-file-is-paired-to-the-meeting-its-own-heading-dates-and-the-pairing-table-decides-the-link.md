# 0123 — A minutes file is paired to the meeting its own heading dates, and the pairing table decides the meeting's minutes link

## Decision

For a city whose `adapter_config` names a minutes reader, a Minutes file belongs to the meeting whose date the file's own heading prints, and only when the city has exactly one meeting row on that date; the event the file is attached to does not date it. The pairing is stored in `minutes_files`, and once a file has been read that table, not the adapter's listing, decides each meeting's `minutes_url`: the paired file's address, or the listed link only while the file it names is unread or failed, or none. A file read and found not to be a meeting's minutes clears, in the same transaction, every link of its city that names it.

## Rationale

Decision `0119` gave an imported CivicClerk event no minutes link "until something reads the date printed in the file itself". This is that reading, and it replaces `0119`'s rule for a city that names a reader: an imported event's meeting now gets the link of the file whose heading names its date. `0119` stands unchanged for a city with no reader (Vestavia Hills), where the listing is still the only evidence.

The plan's brief asked for pairing by "date and roll call". The author read all 254 Minutes files Mobile listed on 2026-11-21: 252 print one date in their heading lines and the other two are not minutes (a letter, an agenda), and where two files name one date they hold the same votes (26 of 26). The date alone decides, so the roll call was not made part of the rule. A file whose heading lines disagree, or name no real date, has no date and is `not_minutes`: pairing on less than the heading says would be a guess (`docs/PRINCIPLES.md`, Source or silence).

The pairing has to be stored because ingest's upsert writes the listed links over the stored ones on every run, and the listing gives an imported event no minutes link: a link written by the reader alone would be gone the next morning. Reading the table before the upsert (`with_paired_links`) is the one place that conflict is settled. The alternative, teaching the adapter which events are imported-but-paired, would put database state into an adapter, which returns what the city says and writes nothing.

The clearing rule is there because the link rule alone acts a day late: file 869, listed as the minutes of 2024-10-22, is the agenda of another meeting, and without the clearing its link would stand until the next run.

The cost: a date with two meeting rows, a hidden duplicate included, pairs nothing, and 29 of Mobile's 135 imported meetings have no file naming their date and show neither link nor votes (`D189` in `docs/DEBT.md`).

## Date

2026-11-21, the authoring session of plan `mobile-votes-from-minutes` (Claude), with the clearing rule added the same day from an outside review the operator supplied; built by that plan's M3 and M4 and graduated by its M6 session on 2026-11-22 (UTC).

## Status

accepted
