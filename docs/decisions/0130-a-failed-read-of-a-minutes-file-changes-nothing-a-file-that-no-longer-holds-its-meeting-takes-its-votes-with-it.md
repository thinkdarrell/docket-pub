# 0130 — A failed read of a minutes file changes nothing it stored; a file that no longer holds its meeting takes its votes with it

## Decision

When a Minutes file that was `paired` is read again and no longer holds its meeting (it now names another meeting, or is `not_minutes`, `no_meeting` or `superseded`), the same transaction deletes the reader votes of the meeting it held and clears that meeting's `minutes_url` where it is the file's address. When the re-read fails, the row becomes `error` and keeps its `header_date`, `meeting_id`, `page_count` and `votes_stored`, and no vote and no link is touched. A re-read under a newer `READER_VERSION` starts its `attempts` at 1; only a retry of an `error` row at the current version adds to the count.

## Rationale

A vote read from a file stays only while that file is its meeting's minutes (`docs/PRINCIPLES.md`, Source or silence). The plan did not say this, because the only way to the case is a re-read after `READER_VERSION` is raised; the M3 session that built the store decided it rather than leave votes standing with no file behind them.

A failed request is different: it is no evidence about the file. Deleting a meeting's votes because the city's server was down for a minute would be a loss with no source behind it, and the file is tried again, three times in all. Without the attempts rule, a file that failed three times under one version would be offered once under the next and never again.

One consequence is left open and is recorded as `D191` in `docs/DEBT.md`: after a failed re-read the meeting keeps its votes and its stored link, but its row is `error`, not `paired`, so `with_paired_links` no longer finds it and the next ingest writes the listing's link, which for an imported event is none, over the stored one until a later try reads the file. It cannot happen while `READER_VERSION` is 1, and whoever first raises it meets it.

## Date

2026-11-22 (UTC), the M3 session of plan `mobile-votes-from-minutes` (Claude); the attempts rule from the outside review of 2026-11-21; graduated by that plan's M6 session on 2026-11-22 (UTC).

## Status

accepted
