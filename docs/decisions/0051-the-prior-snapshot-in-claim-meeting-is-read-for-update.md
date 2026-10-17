# 0051 — `claim_meeting()` reads its `prior` snapshot `FOR UPDATE`, so the snapshot and the claim's UPDATE see one row version

## Decision

The SELECT that `claim_meeting()` in `transcriber/transcriber/db.py` runs to take the pre-claim row as `prior` (`SELECT * FROM transcripts WHERE id = %s FOR UPDATE`) holds a row lock until the commit the claim's UPDATE joins, so a worker write that arrives between the snapshot and the UPDATE waits and lands after the claim. The advisory lock the producer already holds does not replace it, and the row lock is not removed as redundant beside it.

## Rationale

The advisory lock (`pg_advisory_xact_lock(hashtext('transcriber_claim'))`) serializes producers only; the worker never takes it, and `mark_low_speech()` in `src/docket/ai/transcripts/pipeline.py` writes `low_speech` in the worker's own transaction. Without the row lock, a worker commit between the two statements gives a `prior` at `uploaded` while the UPDATE's `uploaded_at` CASE (decision `0050`) fires on `low_speech`, and `restore_row()` would then write back `uploaded` with `uploaded_at` set, publishing a row the worker had just hidden. The busy guard narrows that window and does not close it: the worker's `CLAIM_SQL` stamps `last_attempted_at` at its claim and `mark_low_speech()` runs later in the same worker run, so the 30-minute refusal is measured from the stamp, not from the write.

The alternative, relying on the guard alone, was weighed when an external review of the plan asked whether `prior` and the UPDATE could see different rows, and rejected because the window is real and the lock costs nothing. `FOR UPDATE` on `transcripts` needs only the UPDATE privilege the `transcriber` role has (`scripts/sql/create_transcriber_role.sql`; the advisory lock exists because the role lacks UPDATE on `meetings`, which stays true). Both producers take the advisory lock before the row lock, so there is no lock-order cycle between them, and the worker only updates the row, so a worker write that waited lands after the claim, the row state `D52` already covers.

The trap this record guards against is the agent who sees `FOR UPDATE` beside an advisory lock, judges it redundant, and removes it.

## Date

2026-10-16, the operator, from an external review of the plan `plans/completed/low-speech-rerun-stays-hidden.md`, recorded in its Decision Log; graduated here at the plan's close on 2026-10-17.

## Status

accepted
