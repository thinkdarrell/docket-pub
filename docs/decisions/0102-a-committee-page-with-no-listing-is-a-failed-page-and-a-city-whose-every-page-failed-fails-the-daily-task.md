# 0102 — A committee page with no listing is a failed page, and a city whose every page failed fails the daily task

## Decision

In `sync_listings`, a committee page that fetches and yields no listing is counted as failed, like one that cannot be fetched; one failed page is logged and skipped. When every configured page of a city failed, `sync_listings` raises, `refresh_city` lets the error through and runs no later step, and `refresh_all`, after running the other cities, raises so that the worker task `committee_documents` reports a failure.

## Rationale

The model for a daily reader of the city's site, `city_calendar`'s `refresh_all`, swallows a city's failure, and an empty page could be read as "nothing posted". All eight pages listed documents on 2026-11-13, so a page with none is far likelier the city's error page or a changed layout than a committee with nothing posted. The pages' address carries the council term, "2025-2027", and will change (`D135` in `docs/DEBT.md`); the sign of that change is exactly every page failing. With one configured city, swallowing it would leave a task green every morning while nothing is read.

What is lost on such a morning is one day's reading and attaching, all of it retried the next. The alternative of running the other three steps first and raising after keeps a day's attaching at the cost of a second path through the function, for a case that is the operator's to fix.

## Date

2026-11-15, the M3 and M6 sessions, in plan `committee-documents`.

## Status

accepted
