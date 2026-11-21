# 0121 — An agenda that is not ready is an exception, and a failed request is an error, never an empty agenda

## Decision

An adapter that knows a meeting's agenda is not published yet raises `AgendaNotReady` (`src/docket/models/protocol.py`); ingest leaves the meeting unmarked, reports nothing, and asks again on the next run. A request that fails raises after its retries; ingest records the error and leaves the meeting unmarked. An empty list from `fetch_agenda_items` means only "this agenda has no items", and the meeting is marked `agenda_items_scraped`. For CivicClerk, an agenda is asked for by the event's `agendaId`, never by the event's id.

## Rationale

The adapter used to catch every request error and return an empty list, and ingest marks a meeting with an empty answer as scraped "so we don't re-try". Three different things were therefore stored as one: the city has no agenda yet, the request failed, and the agenda really is empty. Five of about sixty requests to the city's system failed at the connection on 2026-11-20, each succeeding when repeated; each such failure would have closed a meeting until the Monday repair task re-opened it. `GOALS.md` asks for a new record within a day of the city publishing it.

The alternative considered was a flag on the event row: skip the request when `hasAgenda` is false. It does not work. `hasAgenda` was true on five scheduled Mobile meetings whose agenda record was empty and unpublished, so the request has to be made and the answer's `agendaIsPublish` read. An agenda with no item for a meeting already held is still an empty list and still marks the meeting, so the 135 imported Mobile meetings, which can never have structured items, are asked for once and not every day. "Already held" is judged on the date in `America/Chicago`: the worker's clock is UTC and calls a meeting past from 18:00 Central on its own day.

An exception that only this adapter raises changes nothing for any other. Under a per-run cap a meeting not ready does not count as a fetch and a failed fetch does (decision `0122`).

The agenda id matters for the same reason. `Meetings/{event id}` does not fail: once an agenda with that number exists it returns that agenda, another meeting's. Production held such items on 51 Mobile meetings (the event of 2026-02-03 stored the agenda of August 11, 2026). A wrong answer that looks right is the case `docs/PRINCIPLES.md` exists for.

## Date

2026-11-20, the authoring session of plan `mobile-agendas-flow-again` (Claude), amended the same day by the operator's review revision; built by that plan's M1 to M3 and graduated by its M6 session the same day.

## Status

accepted
