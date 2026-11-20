# 0122 — The backlog floor and the per-run agenda cap are `adapter_config` settings read by ingest

## Decision

How far back a city is listed and how many waiting agendas are fetched in one run are two optional keys of `municipalities.adapter_config`, `backlog_floor` (a date) and `agenda_fetch_cap` (a whole number, 0 or more), read by `ingest_municipality` for any adapter. A city with neither key is ingested exactly as before. A city's backlog is brought in by setting them, not by a city-specific code path or a backfill script. Whether a stored agenda is ever fetched again is said by the adapter, with the class attribute `items_carry_video_timestamps`.

## Rationale

The work was asked for as settings and adapter behaviour so that the next CivicClerk city, and the next city on any adapter, reuses it. The adapter protocol already had `since`; a floor read in ingest and passed as `since` serves every adapter, and a caller's own `since` still wins. A one-off backfill script was the alternative: it would have fetched Mobile's 124 structured agendas in one sitting, about 6,800 items, at whatever pace its author chose, outside the worker's failure isolation and its logs, and it would have been written again for the next city.

The cap counts meetings whose agenda is waiting, newest first. A meeting not ready does not count, because Mobile's 42 scheduled meetings are the newest rows and cost no request; counting them would spend the cap on nothing every day. A fetch that fails does count, so a failing site is not asked again and again in one run. A cap of 0 is the stop: the listing continues and no agenda is fetched, without a deploy.

A value that cannot be read is the run's one error, before any request, and not a silent default: a row that says `"10"` is a typing slip the operator should see on the first run.

The timestamp attribute is there because ingest re-fetched every stored agenda that had a numbered item without a video timestamp, which is every CivicClerk agenda, every day: about 300 requests a day for Mobile once its listing was complete. An adapter that says nothing behaves as before, so `src/docket/adapters/granicus.py` was not edited. Its cost is recorded as `D183` in `docs/DEBT.md`: an agenda stored before its meeting is not looked at again.

Widening the weekly `repair_empty_agendas` to the floor was considered for the old, wrongly filled meetings and dropped: it would re-open Mobile's imported meetings every Monday. They are put right once, by hand, with `scripts/reset_agenda_items.py` (`docs/specs/civicclerk-ingest.md`, "The reset").

## Date

2026-11-20, the authoring session of plan `mobile-agendas-flow-again` (Claude); built by that plan's M3 and M4 and graduated by its M6 session the same day.

## Status

accepted
