# 0100 — A committee document that has a meeting is never moved or detached by `attach`

## Decision

`attach` gives a meeting only to a document that has none. Whatever a later reading (`reparse`) makes of an attached document's committee, date or kind, the document stays on its meeting, and a meeting created from minutes is never deleted by code. To re-attach on purpose, an operator sets `meeting_id` to NULL on the rows concerned and runs `attach`.

## Rationale

The obvious alternative is to keep attachment a pure function of the facts: when a mended rule re-dates a document, move it. That would move a document silently between meeting pages, and where the document had created its meeting it would leave a `cdoc-` row with nothing on it or delete a page a reader may have linked. A rule change that re-dates a document is rare and is the operator's to see (the backfill script prints documents by date source); a silent move is the worse failure, and a wrong merge is harder to recover than a stale attachment.

The same rule makes every run idempotent: the update that attaches carries `meeting_id IS NULL` itself, so two runs, or two processes, cannot attach a document twice. The cost is that `reparse` corrects what a page says and not which page says it.

## Date

2026-11-15, the M4 session, in plan `committee-documents`.

## Status

accepted
