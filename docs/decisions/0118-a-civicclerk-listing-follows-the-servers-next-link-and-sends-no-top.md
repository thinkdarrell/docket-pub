# 0118 — A CivicClerk listing follows the server's next-page link and sends no `$top`

## Decision

`CivicClerkAdapter.list_meetings` sends one first request to `Events` with no `$top` and no `$skip`, and reaches every further page by requesting the address the server gives in `@odata.nextLink`, exactly as given. A link that does not lead back to the adapter's own `https` address is refused, and a listing of more than 200 pages is an error. A date floor is sent to the server as `eventDate ge <date>T00:00:00Z`, not applied after the fact.

## Rationale

The obvious way to page an OData listing is `$top=100` with `$skip` advanced by 100, and that is what the adapter did. On this server it is wrong twice. The server returns 15 rows a page whatever is asked, so a walk by `$skip` in hundreds saw rows 1 to 15, 101 to 115, and so on: 15 of every 100 events. And `$top` is a total, not a page size: the next link of a `$top=100` request carries `$top=85`, so following links under it stops at 100 rows. Mobile's council has 492 events. The result was a city page whose meetings showed "0 items" and, for Vestavia Hills (378 events over seven bodies), a council meeting listed only by accident.

A link followed verbatim carries the server's own `$skiptoken`, so the adapter does not have to know how the server pages. The checks on the link exist because the adapter then requests whatever address an answer names: one bad answer must not send the worker to another host or round a loop.

The filter is sent to the server because it works there (observed on 2026-11-20) and keeps Mobile's daily listing at 21 pages and not 33. The client-side check of `since` stays as a second guard.

## Date

2026-11-20, the authoring session of plan `mobile-agendas-flow-again` (Claude); built by that plan's M1 and graduated by its M6 session the same day.

## Status

accepted
