# 0086 — An admin's meeting-type correction is a lock on the row that every writer checks

## Decision

An admin's correction of a meeting's type, sitting, or body name writes the four classification columns with `type_source = 'admin'` and sets the lock pair `type_locked_at` / `type_locked_by` on the row (`services/meeting_types.set_override`). Every writer of the classification scopes itself to `type_locked_at IS NULL`: the three ingest writers, `resolve_and_store`, and the one-statement reclassification; the lock is the first rung of the evidence ladder (`0085`), so a locked row is returned unchanged. The lock is lifted only by `clear_override`, which clears it and resolves the row once through the ladder in one transaction. The write lives in `src/docket/services/meeting_types.py`, not in the admin route.

## Rationale

`_upsert_meetings` rewrites every listed row on every daily ingest, so a correction that was only a value in the column would last one day; the correction has to be a fact the writers can see and refuse to overwrite. The lock mirrors the existing `is_hidden` pattern (`hidden_at`, `hidden_by` from migration 033), so an admin's action carries who and when, and an operator can lock a row by SQL before the admin form exists, as happened on 2026-10-22 when six pre-2026 Birmingham rows the schedule rule would have relabelled were locked as `council` before the production reclassification. The alternative, a `type_source` value meaning "set by hand" with no timestamp, would have required every writer and every later rung to know which source values mean hands-off, and would have recorded nothing about who set it; a lock is one predicate, and `type_source = 'admin'` beside it says why the row reads as it does.

The write goes through a service because `docs/DEBT.md` `D7` already lists `admin.py` among the web modules that execute SQL directly, and a new admin write added there would have grown the row; the service owns the transaction, as `AGENTS.md` requires of every write. Unlocking resolves under the same cursor as the clear so that a failed unlock leaves the lock in place, visible to the admin, rather than an unlocked row still marked `admin`.

## Date

2026-10-21, Claude as the author of plan `meeting-types-name-the-body`; used by the operator on production 2026-10-22; built in M2 and M5 and graduated by the M6 session on 2026-11-08.

## Status

accepted
