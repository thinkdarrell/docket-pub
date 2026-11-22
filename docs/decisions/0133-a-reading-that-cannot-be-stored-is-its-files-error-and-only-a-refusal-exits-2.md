# 0133 — A minutes reading that cannot be stored is its file's error, and the script exits 2 only for a refusal

## Decision

When storing one file's reading raises, what that store wrote is undone (its transaction rolled back; in a dry run, a savepoint) and the file is recorded `error` with the exception's text and its try counted, exactly as a failed fetch is; the run goes on to the next file. A store that raises `psycopg2.OperationalError`, or a failure to write that `error` row, ends the run and spends no try. `read_city` raises `Refused`, a `ValueError`, for an unknown city, a city that names no reader and a setting that cannot be read, each before any request to the city; `scripts/read_minutes_votes.py` exits 2 for `Refused` and for nothing else.

## Rationale

The M3 session of plan `mobile-votes-from-minutes` decided that a statement that fails is a fault of the database or of the code, not of one file, so the run should stop and stage 4b report it. The plan's closing review showed a failure that is one file's: a NUL character in a page's extracted text, which the reader accepts and psycopg2 refuses with a `ValueError`. Such a file got no row, so it was "never read" on the next run, was taken again ahead of every older file (newest event first), and failed again: the limit of three tries never applied and the backlog behind it was never read (`D195`). And because the refusal was a `ValueError`, the script printed it and exited 2, the status kept for a refusal before any request.

The line between a file's fault and the database's is drawn by the exception's class, coarsely. `psycopg2.OperationalError` is what the driver raises for the connection and the server's own state (a lost connection, a deadlock, a serialization failure, out of memory or disk); none of it is evidence about the file, so it ends the run as before and the file is tried again by the next one. Everything else (the data refused, a constraint, a fault in the code) is counted against the file and written as its `error` row on a fresh transaction; if that write fails too, the run ends. Counting every failure against the file, the first form of this change, would have let three passing deadlocks strand a file until the reader's version is raised. The cost of the line as drawn is the reverse case: a file whose store reliably raises an `OperationalError` (a statement the server cannot hold) blocks the files behind it every day, as every such file did before this record, and stage 4b's daily `Minutes files: ...` is what shows it.

Stripping NUL characters in the reader was not done: it would mend one cause and leave the file-blocks-the-backlog shape for the next. A distinct exception class, and not a second exit status for errors, keeps the script's contract in one place: 2 means nothing was asked of the city.

## Date

2026-11-22, the operator's session that mended the closing review's findings before pull request #193 merged (Claude, at the operator's request).

## Status

accepted
