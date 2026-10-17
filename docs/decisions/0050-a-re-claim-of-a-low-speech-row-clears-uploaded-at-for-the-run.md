# 0050 — The producer re-claims a `low_speech` row with `uploaded_at` NULL, so the one transcript the predicate hides by status alone stays hidden through a re-run

## Decision

`claim_meeting()` in `transcriber/transcriber/db.py` sets `uploaded_at` to NULL in the same UPDATE that sets `status = 'claimed'` when the row it re-claims rests at `low_speech`, after reading the row whole as `prior`, so `restore_row()` puts the original `uploaded_at` back when the re-run ends without an upload and `upload()` sets it anew. The public predicate of decision `0049`, `uploaded_at IS NOT NULL AND status <> 'low_speech'`, does not change, and no status, column, or `word_count` clause is added to it.

## Rationale

This record extends decision `0049`, whose Rationale says `uploaded_at` "is never cleared"; this is the one clearing. `0049` made a transcript public once uploaded so that a `--meeting-id` re-run no longer takes the page down, and excluded `low_speech` because both writers of that status mean there is no usable transcript. The worker's fitness gate (`mark_low_speech()` in `src/docket/ai/transcripts/pipeline.py`) writes `low_speech` on a row that has been uploaded and keeps `uploaded_at` and the segments, so the predicate hides such a row by its status alone, and `claim_meeting()` overwrites that status with `claimed`: from the claim until the upload or the restore, a transcript the site hides at rest was public (`D58`, found by the closing review of `plans/completed/rerun-keeps-transcript-public.md`). The predicate reads only the row, so the fact that this transcript is hidden has to travel in the row through the producer statuses, and `uploaded_at` is the column the predicate already keys on. The alternatives each cost more. A new status needs a migration altering the CHECK in `src/docket/migrations/035_transcripts.py` and a change at every reader of `status`, the reason `0049` rejected one. A new column (migration 037) is a second owner of the public fact beside `uploaded_at`. A predicate clause on `word_count` makes the row public at `transcribed`, when `mark_status()` writes the new count while the old segments are still in the table, and couples the predicate to the config value `TRANSCRIPT_MIN_WORDS`. Deleting the segments at the claim hides the row, but `restore_row()` could not bring them back. The accepted cost is the crash case: a producer that dies mid-run of such a row leaves `uploaded_at` NULL, the next run takes no `prior`, and a failure then writes `failed` with `uploaded_at` NULL, hidden and absent from the admin held tab, which `docs/specs/transcripts.md` names with its recovery.

The trap this record guards against is the agent who reads the comment above `_PUBLIC_PREDICATE` or `0049`, takes "`uploaded_at` is set only by `upload()`" as a rule, and removes the CASE from `claim_meeting()` as an anomaly; or who, seeing that `restore_row()` writes `uploaded_at` back, has the claim keep the timestamp and adds `status <> 'claimed'` or a `word_count` test to the predicate instead, which re-opens the hour of exposure or publishes the row at `transcribed`.

## Date

2026-10-16, the plan author of `plans/active/low-speech-rerun-stays-hidden.md`, from the closing review of `plans/completed/rerun-keeps-transcript-public.md` (`D58`).

## Status

accepted
