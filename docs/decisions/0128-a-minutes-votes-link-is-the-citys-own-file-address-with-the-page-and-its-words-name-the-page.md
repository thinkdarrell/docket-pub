# 0128 — A minutes vote's link is the city's own file address with `#page=N`, and the link's words name the page

## Decision

A vote read from a minutes file links to the city's own address for that file with `#page=<n>` added, n being `votes.source_page`, and the link's text states the page ("Minutes, page 5"). docket.pub serves no copy of the file and no viewer of its own. The link opens a new tab with `rel="noreferrer"` and is printed only where `is_source_url_safe` passes the address.

## Rationale

`docs/PRINCIPLES.md`, Source or silence, asks that a fact link to the city's own document. Mobile serves its files with `content-disposition: attachment` (read on 2026-11-21 from the response headers of file 3854), so a browser that obeys the header saves the PDF and ignores the fragment. The alternative that would always open at the page is to fetch the file and serve it, or a page of it, from docket.pub: that is a copy of the source in place of the source, new surface to secure and keep in step with the city's file, and storage on a volume the project's constraints bound. It was left out, and the page number was put into the link's words so that the reader who gets a download still knows where to look.

The new tab is for the same case: when the browser downloads the file instead of showing it, the meeting page, with the page number, is still on screen.

Whether this is enough is the operator's to judge from a real browser, which no session could do (`D188` in `docs/DEBT.md`).

## Date

2026-11-21, the authoring session of plan `mobile-votes-from-minutes` (Claude); the link's attributes settled the same day from an outside review; built by that plan's M2 and M5 and graduated by its M6 session on 2026-11-22 (UTC).

## Status

superseded by 0134
