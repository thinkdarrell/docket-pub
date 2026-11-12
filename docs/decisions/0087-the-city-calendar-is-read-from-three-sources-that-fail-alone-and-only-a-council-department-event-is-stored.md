# 0087 — The city calendar is read from three sources that fail alone, and only a council-department event is stored

## Decision

`city_calendar_events` is filled each morning by three readers, each named by its own key in the city's metadata, each committing its own events, and each isolated from the others' failure: the council page (the next four events), the site's events search (every upcoming event of the City Council department), and the sitemap's event pages (the only listing that holds past events), fetched newest first, only when not already stored, at most 60 in a run. An event is stored from the search or from an event page only when its department is the city's `calendar_department`; the refresh raises only when every reader failed. The city's own status for an event is stored (`event_status`) and never overwritten by a source that reports none.

## Rationale

The obvious alternative was the one already built: read the council page once a day. That page lists four events, so an event could enter and leave it between two reads, and nothing past was ever recoverable; on 2026-11-03 the council's own event was missed while a committee's on the same day was stored, and the council clip (meeting 3186) was named after the committee (the debt row `D116`, now deleted). On 2026-11-11 ten Birmingham committee cards read only "Council committee meeting" because their days' events had never been stored.

No single source replaces the page. The search answers for upcoming events only (a query for October 2026 returned `total: 0` in November), and the sitemap is a list of addresses, one request per event. So the past comes from the sitemap, the future from the search, and the page stays as a third reader because it costs one request a day and still works if the search's address changes. One transaction for all three would roll the search's rows back with a sitemap failure, the opposite of failing alone, and the sitemap reader can skip what the search stored only if that is already committed, so it runs last. Swallowing every failure would report a morning with no calendar at all as a refresh of zero events, which is why the refresh raises when all three fail.

The department test exists because a title is not enough: the sitemap's path filter (`committee`, `council-meeting`, `work-session`) admits the Planning department's Framework Plan Implementation Committee, whose public meeting of 2026-10-14 would otherwise have named a council clip of that day. The search's `department=55` parameter is the only thing that keeps its results the council's, so the parser checks the department each result names as well, in case the site ever ignores the parameter. The cost is that a rejected page is fetched again every day, bounded by the cap and by the newest-first order, which keeps a growing set of other departments' pages from using up a run before the newest council events are reached.

The status is written `COALESCE(new, stored)` because the search reports none and runs every morning over events the sitemap reader stored from their pages; a plain overwrite would turn every `active` back to NULL within a day, and any cancelled value with it. One event page that cannot be fetched is passed over and three end the sitemap read for the run: with the reader's one `try` alone, a page the city removed while the sitemap still listed it would raise at the same place every morning and hide every page after it for good.

## Date

2026-11-11, Claude as the author of plan `committee-clips-named-or-hidden` (the three sources, the department test) and the plan's M1 session (the status write, the per-page failures, the raise when every reader fails); graduated by the M5 session the same day.

## Status

accepted
