# 0103 — A dry run of the committee documents backfill is the real code on one connection that is rolled back

## Decision

`backfill(..., dry_run=True)` in `src/docket/services/committee_documents.py` runs the same functions as a real run on one connection, each of their transactions a savepoint, and rolls the connection back at the end. The switch is a module global behind the service's own `db_cursor`; `backfill` is its only entry, and it is called from a script, never from the web process or the worker. Only a dry run may create migration 045's tables, inside its transaction, when they are absent.

## Rationale

Each function of the service opens and commits its own transactions (one per page, one per document), so a script cannot wrap the calls in a transaction of its own. The alternatives lost: passing a connection through seven functions changes every signature; a dry run that computes without writing would be a second implementation of `attach`, which is the thing the operator needs to see the real one do; and copying the database is not available against production. A savepoint per block keeps what each block's own transaction gave: a document the database refuses is undone alone and the documents after it are still read.

Two traps follow. A module global is safe for a one-shot script and not for a process serving requests, where a second thread would write through the dry run's connection; so nothing but the script may call `backfill`. And a dry run that creates the tables holds, until it ends, a lock under which every write to `meetings` and `municipalities` waits (a reference to another table takes it; observed on 2026-11-15), so a dry run on a database without the tables is run outside the worker's morning tasks. A real run never makes the tables, because that would leave a schema the migration runner does not know it applied. The summary the script prints is read by `backfill` inside the same transaction, before the rollback, which is also why the script holds no SQL.

## Date

2026-11-15, the M6 session, in plan `committee-documents`.

## Status

accepted
