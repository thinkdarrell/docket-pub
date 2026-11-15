# 0097 — Committee items come from minutes only, and only minutes create a meeting

## Decision

What a committee took up is read from its minutes; an agenda is stored and linked and its items are not read. Minutes for a committee and date with no meeting row create one (`external_id` beginning `cdoc-`), when their date came from their own header and is not in the future. An agenda alone never creates a meeting, and waits unattached until one exists.

## Rationale

The design said items come from the agenda until minutes exist. The eight committees print agendas in eight layouts, with dot leaders, sub-items and presenter names; thirteen of the 106 agendas surveyed were scanned images with no text; and an agenda does not say what the committee did, which is the fact the page exists to show. Minutes share one layout across all eight committees. A meeting whose minutes are not yet posted shows its agenda link and says the minutes are not yet posted. Reading agenda items is `D132` in `docs/DEBT.md`.

Minutes prove a meeting was held; a posted agenda does not, because meetings are cancelled and rescheduled. Without creation a committee whose meetings are not recorded stays invisible: the Economic and Workforce Development / Tourism Committee had 13 sets of minutes and one meeting row. A meeting created from an agenda would put on the site a meeting that may never have happened (`docs/PRINCIPLES.md`, "Source or silence"). The header-date condition is the same caution: a date taken from the page's heading is the listing's word, not the minutes'.

## Date

2026-11-13, the plan author, in plan `committee-documents` (built in its M2 and M4).

## Status

accepted
