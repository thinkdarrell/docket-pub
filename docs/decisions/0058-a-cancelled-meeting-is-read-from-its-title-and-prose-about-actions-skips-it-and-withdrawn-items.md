# 0058 — A cancelled meeting is read from its title, and the page's prose about what the council did skips cancelled meetings and withdrawn items while its counts do not

## Decision

"This meeting was cancelled" has one owner, `query.CANCELLED_PREDICATE_SQL` (`title ~* 'cancell?ed'`, with `CANCELLED_PREDICATE_MT` on the `mt.` alias), read by the opener's last- and next-meeting queries, the money query, the meetings list, `query.list_items_by_amount`, and `maintenance.repair_empty_agendas`. A cancelled meeting is never "the last meeting" or "the next meeting" and its items are never under "Where the money went"; its "Recent meetings" row stays, saying "cancelled" in place of counts. An item whose `processing_status` is `withdrawn` is never "The largest" and never a money line. The topics door, the priority lines, and the signals list keep counting a cancelled agenda's items (`D59`), and "acted on <n> items" keeps counting withdrawn ones.

## Rationale

Nothing in the schema marks a cancellation: the Granicus adapter only normalises the " - Cancelled" suffix for reconciliation, `is_hidden` is set by hand in admin, and ingest scrapes a cancelled meeting's posted agenda like any other, so once its date passed it was the newest council meeting with items and the first sentence of the page said the council met and acted on items it never took up (the second closing review's severe finding). The title is the only evidence the rows hold, and `maintenance.py` already read it this way; a second regex would be a second owner. The predicate also matches two historical rescheduled sittings whose titles carry the earlier date's cancellation (2019-12-30 and 2020-04-03); accepted, because both are years outside every window the page uses, neither can be the newest meeting, and parsing dates out of titles would cost more than it hides. The row stays in the list because `/al/<slug>/meetings/` shows it, and a list that disagreed with that page would be two owners of one fact.

Withdrawn items leave the amount prose because "The largest was" and the heading "Where the money went" assert an action on the item while the item page says no action was taken; the count sentence asserts the agenda's size, which the design prescribes. An outside review's further proposal, to disqualify a past meeting with no votes and no minutes when its agenda was scraped, was declined: Birmingham publishes minutes a week or more after a sitting, so for that week every real meeting has an agenda and nothing else, and the opener would skip the newest meeting after every sitting.

## Date

2026-10-19, the plan author (Claude) revising `plans/active/birmingham-city-briefing.md` after its second closing review, applied in M9; graduated at the plan's retrospective on 2026-10-20.

## Status

accepted
