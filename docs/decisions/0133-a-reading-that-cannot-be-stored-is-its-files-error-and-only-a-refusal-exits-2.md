# 0133 — A minutes reading that cannot be stored is its file's error, and the script exits 2 only for a refusal

## Decision

When storing one file's reading raises, what that store wrote is undone (its transaction rolled back; in a dry run, a savepoint) and the file is recorded `error` with the exception's text and its try counted, exactly as a failed fetch is; the run goes on to the next file. Only a failure to write that `error` row ends the run. `read_city` raises `Refused`, a `ValueError`, for an unknown city, a city that names no reader and a setting that cannot be read, each before any request to the city; `scripts/read_minutes_votes.py` exits 2 for `Refused` and for nothing else.

## Rationale

The M3 session of plan `mobile-votes-from-minutes` decided that a statement that fails is a fault of the database or of the code, not of one file, so the run should stop and stage 4b report it. The plan's closing review showed a failure that is one file's: a NUL character in a page's extracted text, which the reader accepts and psycopg2 refuses with a `ValueError`. Such a file got no row, so it was "never read" on the next run, was taken again ahead of every older file (newest event first), and failed again: the limit of three tries never applied and the backlog behind it was never read (`D195`). And because the refusal was a `ValueError`, the script printed it and exited 2, the status kept for a refusal before any request.

The code cannot tell a file's fault from the database's by the exception, and does not try. It tries to write the `error` row on a fresh transaction: if the database is there, the fault was the file's or a passing one, and three counted tries is the rule a failed fetch already has; if it is not there, that write fails and the run ends as it did before. The cost is that a passing database fault (a deadlock) spends one of a file's three tries.

Stripping NUL characters in the reader was not done: it would mend one cause and leave the file-blocks-the-backlog shape for the next. A distinct exception class, and not a second exit status for errors, keeps the script's contract in one place: 2 means nothing was asked of the city.

## Date

2026-11-22, the operator's session that mended the closing review's findings before pull request #193 merged (Claude, at the operator's request).

## Status

accepted
