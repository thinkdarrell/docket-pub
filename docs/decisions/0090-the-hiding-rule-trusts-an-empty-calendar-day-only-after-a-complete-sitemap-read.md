# 0090 — The hiding rule trusts an empty calendar day only after a complete sitemap read

## Decision

`non_meetings` hides nothing for a city unless `municipalities.metadata.calendar_sitemap_read_at` is within `CALENDAR_FRESH_HOURS` (36). Only the sitemap reader of `docket.services.city_calendar` writes that stamp, and only after a run in which no event page failed and none was left over by the page cap. `fetch_event_page` raises `UnreadableEventPage` for a page it fetched and could read no event from, so such a page is a failure and not "another department's". This replaces the 36-hour test on the newest `city_calendar_events.fetched_at` that `0089` describes; the rest of `0089` stands.

## Rationale

The rule in `0089` reads a day with no stored event as a day on which nothing was scheduled. Only the sitemap reader stores past days. The council page and the search rewrite `fetched_at` every morning, so the old test passed on a morning when the sitemap had failed, had stopped after three failed pages, or had never run under the new code (migration 043 sets `calendar_complete_from` at deploy). On such a morning every short generic clip without documents back to `calendar_complete_from` would have been hidden, a real six-minute committee meeting among them, with a reason that was false for it. The closing review of plan `committee-clips-named-or-hidden` found this before any deploy (`D120`, now closed).

The operator's instruction on 2026-11-11 set the direction of every doubt: a stream test left on the site costs less than a meeting taken off it. So the stamp is all or nothing. One event page that fails, or is served without a readable event, leaves the read incomplete, and the rule stops for the whole city once the stamp is 36 hours old, even though only that page's day is in doubt. The cost is that a page the city leaves broken in its sitemap stops all hiding until it is read or removed; the calendar task's log line names the page and says the read was incomplete. A narrower rule (doubt only the failed page's day, read from the date in its address) was not taken: it trusts the address's date over the page's own, and nothing has shown a persistent failure to exist.

The stamp lives in the metadata beside the other calendar keys and needs no migration. It is compared by the database's clock, as the old test was.

## Date

2026-11-11, the operator (fix before merging; prefer a non-meeting shown over a meeting hidden) and Claude, in the session that ran the plan's `cycle-run`, after the closing review.

## Status

accepted
