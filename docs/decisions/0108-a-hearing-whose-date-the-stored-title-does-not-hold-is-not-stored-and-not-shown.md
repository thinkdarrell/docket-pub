# 0108 — A hearing whose date the stored title does not hold is not stored and not shown

## Decision

The hearing reader reads an agenda item's `title` alone, and a reading with no date creates no row in `public_hearings` and no entry on the coming-up page or in either feed. The backfill script's dry run lists such an item as "no date", and that is the only place it appears.

## Rationale

`docs/PRINCIPLES.md`, "Source or silence". On 2026-11-16 eleven of the 78 Birmingham agenda items since 2025 that match the trigger held no date in what is stored: a budget hearing "in the Council Chambers on the Mayor's proposed budgets", and titles cut at 256 characters before "on the 13th day of ...". The alternative that looks obvious is to place such a hearing at the next council meeting. That is a default: the page would then print a date no city document states, with a link to a document that does not state it.

The other alternative is to read the item's `description` when the title is cut. Where a title is cut, the description is NULL (49 of the 78), so there is nothing to fall back on; and where a title is whole, the description can run on into the agenda's boilerplate ("... interested in a public hearing so requests"), which holds the very words the reader looks for. Recovering a cut date means reading the agenda PDF again, which is a different piece of work (`D158`).

A hearing that is absent can be reported by a reader and found in the dry run. A hearing on a guessed day sends someone to a room on the wrong day.

## Date

2026-11-16, the plan author (Claude) of plan `birmingham-coming-up`; the operator declined the review's suggestion to read `description` the same day, on Claude's recommendation. Built by the plan's M1 and M2 sessions on 2026-11-17.

## Status

accepted
