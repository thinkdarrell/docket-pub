# 0131 — A failed minutes file row holds its meeting while the meeting's link is its address; a file that pairs clears its address from every other meeting

## Decision

An `error` row of `minutes_files` that names a meeting holds that meeting for as long as the meeting's `minutes_url` is the row's own address: `with_paired_links` gives the meeting that address, and a later read of the file that no longer pairs it there deletes the meeting's reader votes and clears the link, as for a `paired` row. An `error` row whose meeting's link is anything else holds nothing. A file that is `paired` sets `minutes_url` to NULL on every other meeting of its city whose link is the file's address, in the same transaction.

## Rationale

Decision `0130` let a failed re-read keep the row's meeting and touch nothing, and left two consequences open (`D191`): the next ingest wrote the listing's link, usually none, over the stored one, because `with_paired_links` looked only at `paired` rows; and `_store` took "the meeting this file held" only from a `paired` row, so a file that failed once and then read as something else left its votes standing with no file behind them. The closing review of plan `mobile-votes-from-minutes` reproduced the second on a rolled-back transaction.

The obvious rule, "an `error` row that names a meeting holds it", is wrong: a `superseded` row keeps the id of the meeting it lost, and it too becomes `error` with that id when its re-read fails. Raising `READER_VERSION` while the city's server is down makes the holder and the superseded file fail together, and the superseded one, read later as not minutes, would delete the holder's votes. "No `paired` row names the meeting" fails on the same case. The row itself does not say which it was, and a new column or status would need a migration for a case that cannot happen at version 1. The meeting's stored link does say it: pairing sets the link to the holder's address, a file that takes the meeting sets it to its own, and a superseded file's address is cleared from every meeting when it is read. So the link is the test, and `with_paired_links` keeping it is what makes the test hold across ingests.

The second sentence closes `D193`, the review's first finding: the listing gives a file's address to the meeting of the event it is filed on, and a file whose heading dates another meeting left both meetings linking it until the next ingest. Decision `0123` had cleared such a link only for a file that is not paired.

## Date

2026-11-22, the operator's session that mended the closing review's findings before pull request #193 merged (Claude, at the operator's request).

## Status

accepted
