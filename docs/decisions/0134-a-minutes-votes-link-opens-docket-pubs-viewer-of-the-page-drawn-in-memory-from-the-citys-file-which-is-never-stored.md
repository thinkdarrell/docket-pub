# 0134 — A minutes vote's link opens docket.pub's viewer of the page, drawn in memory from the city's file, which is never stored

## Decision

A vote read from a minutes file links to a docket.pub page, `/al/<slug>/meetings/<id>/minutes/page/<n>/`, that shows the page as a picture drawn by the server from the city's own file and always prints a link to that file. The file is fetched when a reader asks, only from the meeting's stored `https` address after `is_viewer_url` has passed it, in one bounded attempt that follows no redirect; it is held in the web process's memory for at most an hour and is never written to Postgres or to disk. A vote whose minutes address the viewer may not fetch keeps the direct link of decision `0128`.

## Rationale

Decision `0128` linked the vote to the city's own file address with `#page=<n>` and left a viewer out until someone had seen a real browser. The operator saw it on 2026-11-22: on a desk and on a phone, the link on Mobile's meeting of 2026-11-03 downloaded the PDF and opened nothing at page 5. Mobile's file endpoint answers `content-disposition: attachment` and `x-frame-options: DENY`. This record supersedes `0128` for any vote whose minutes address is a viewer address.

The mechanism. Framing the city's address is forbidden by the city. Passing the PDF through with an inline header would open it on a desk, but phone browsers do not honour `#page=`, so it would not open at the page on a phone. A vendored JavaScript PDF library would be the repository's first and still needs the pass-through. A picture of the one page, drawn with libraries already installed (`pypdfium2`, `pillow`) in under a tenth of a second, is the same on a desk and on a phone. It is lossless WebP, a fifth of the PNG's size and the same pixels, so no lossy step stands between the reader and the city's record; PNG is the fallback. The picture is inside the page as a `data:` address: one reader request is one code path and at most one request to the city, where a second image route could be answered by a process with its own cache.

No copy. `0128` refused a viewer as "a copy of the source in place of the source" and storage on a bounded volume. The viewer keeps both objections answered: the page always prints the city's link and says the city's file is the record, and nothing is persisted. The in-memory cache (the constants in `src/docket/services/minutes_viewer.py`) is what keeps reader traffic polite: moving from page 5 to page 6 sends the city nothing, and an hour bounds how stale a replaced file can be.

The fetch. It runs inside a web worker that answers one request at a time under gunicorn's 30-second limit, so it is one attempt with bounds that end within about 13 seconds (`src/docket/adapters/source_file.py`); `CivicClerkAdapter.fetch_file`, with three attempts and a 30-second read, was not reused. Requests to one host are a second apart (`GOALS.md`, Constraints). A failure is remembered for a minute, for the whole host when the host did not answer, so a city that is down costs one stall a minute and not one for every meeting asked for. Callers of one file share one fetch, and the service holds no lock across a sleep, a fetch or a draw: the first design's single lock would have made every viewer request wait behind one slow file as soon as the web service ran threads.

Which address. Only the stored `minutes_url`, never anything from the request, and only `https` with no redirect followed, so the fetch stays on the address the allowlist passed. `is_viewer_url` is stricter than `is_url_safe` because a yes makes a request and no longer only prints a link: the allowlist and the fetching library read an address with a backslash before an `@` as two different hosts, so the predicate refuses the characters on which URL readers disagree, a user name, and any port but 443.

When the file cannot be had. The viewer answers 200 with the city's link and the page number, not 502: the reader is then no worse off than under `0128`, and nothing at Cloudflare's edge replaces the page. A page past the file's end is a 404 that is still the viewer page with the city's link, because a city that replaces its minutes with a shorter file must not turn a link docket.pub printed into a bare not-found page.

The layering. The fetch is a city-neutral adapter module, the drawing is in analysis, the cache and politeness are a service with no SQL, and the route reads the meeting through the query service; the viewer is keyed on the meeting and the page, so any city whose votes carry a page gets it. The viewer's path is disallowed in `robots.txt` and its responses carry `X-Robots-Tag: noindex`, because each crawl could be a request to the city.

Whether it reads well in a real browser is the operator's to see after the deploy (`D188` in `docs/DEBT.md`).

## Date

2026-11-22, the authoring session of plan `minutes-open-at-the-vote-page` (Claude), from the operator's goal; revised against two outside reviews on 2026-11-22 and 2026-11-23; built by that plan's M1 to M4 and graduated by its M5 session on 2026-11-23 (UTC).

## Status

accepted
