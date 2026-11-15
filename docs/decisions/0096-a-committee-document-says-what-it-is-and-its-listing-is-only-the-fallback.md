# 0096 — A committee document says what it is, and its listing is only the fallback

## Decision

Which committee a document is for, which date, and whether it is an agenda or minutes are read from the document's own first lines. The committee page it is listed on, the date heading it sits under and its listed name are used only for a fact those lines do not give, and a document whose header disagrees with its listing is marked `listing_disagrees` and keeps the header's reading.

## Rationale

The obvious alternative, and what the design first said, is to take the date from the page's heading: it is structured, it is there for every listing, and it needs no PDF. Measured on all 199 documents the eight pages listed on 2026-11-13, fourteen sat under a heading for a different meeting than the one they record, several file names carried the wrong year, one committee's minutes were posted on another committee's page, and one document was a full council agenda. The document's own heading was right in every case read by hand.

A wrong date attaches a committee's minutes to another meeting's page, where every quoted action is then false of the meeting shown. The fallback remains because some headers give no year or no committee (a logo read as noise) and thirteen documents were scanned images with no text at all; for those the listing is the only statement there is.

A disagreement needs two statements: a header that names no committee does not disagree with its page.

## Date

2026-11-13, the plan author, and 2026-11-15 (what counts as a disagreement), the M1 session, in plan `committee-documents`.

## Status

accepted
