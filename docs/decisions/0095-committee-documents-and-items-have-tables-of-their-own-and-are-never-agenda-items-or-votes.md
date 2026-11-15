# 0095 — Committee documents and items have tables of their own, and are never agenda items or votes

## Decision

A council committee's agenda, minutes and items are stored in `committee_documents` and `committee_items` (migration 045). Nothing that reads a committee document writes `agenda_items`, `votes`, `member_votes`, `meetings.agenda_url` or `meetings.minutes_url`.

## Rationale

The obvious alternative is to put a committee item in `agenda_items`, where the pages, search and the summaries already are. Every existing reader of `agenda_items` treats a row as council business. A new row there defaults to `processing_status = 'pending'` and is claimed by the daily AI stage, which has no meeting-type filter; the city page's money list, search, the sitemap and the member pages have none either, so a committee item would appear beside the council item for the same resolution and be counted twice.

`meetings.minutes_url` is worse. The meeting-type resolver never gives a row with a minutes link a committee event, the minutes-adoption sweep selects on it, and the daily Granicus ingest overwrites both address columns from its own feed.

New tables change no existing reader. The cost is that committee items are not in search and have no page of their own (`D134` in `docs/DEBT.md`), and that every surface that should show them must be taught to. The trap is the tidy-looking merge: "an item is an item". It is not until every reader of `agenda_items` filters by the meeting's type.

## Date

2026-11-13, the plan author, in plan `committee-documents` (built in its M3).

## Status

accepted
