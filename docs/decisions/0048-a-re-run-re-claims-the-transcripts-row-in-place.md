# 0048 — The producer re-transcribes a meeting by re-claiming its existing `transcripts` row in place, never by deleting the row

## Decision

`claim_meeting()` in `transcriber/transcriber/db.py` serves `--meeting-id N` by setting the meeting's existing `transcripts` row back to `claimed` under the same advisory lock as `claim_next()`, resetting `stage_attempts`, `last_attempted_at`, `needs_review_reason`, and `last_error`, writing `compare_skipped_reason = 'transcript_changed'` when the row had been uploaded, and refusing with `MeetingBusy` a row whose `last_attempted_at` is within the last 30 minutes. `upload()` then clears the model's speaker resolution on the meeting's non-manual `transcript_speakers` rows, deletes the non-manual rows whose cluster label the new output lacks, and leaves `is_manual` rows alone. Deleting the `transcripts` row by SQL so that `claim_next()` finds the meeting again is not a supported re-run path.

## Rationale

`claim_next()` never selects a row at `uploaded` or any later status, so before this the only way to re-run a meeting was a SQL delete. A row re-created after a delete can carry no pass-kind marker, and the marker is what decision `0045` keys the worker's compare on: re-extracting the transcript side deletes the events every approved discrepancy is anchored to, so a re-upload over a compared meeting is a changed-input pass, and without `'transcript_changed'` `reconcile()` would insert the returning findings as duplicates beside the person's approvals instead of staling them. The marker is written only when `uploaded_at IS NOT NULL` because a never-uploaded row was never compared and its stored reason is then the honest one. Clearing the model's speaker columns on upload closes a window of up to a day in which the public page would show the old cluster's name on a new cluster that reuses its label; since `retry_transcript()` keys its restart stage on `method IS NOT NULL`, the cleared rows also send a retry back to `uploaded`, which is right for a re-run. The busy guard exists because the worker's `advance()` writes `status` with no guard on the status it claimed at, so a stage in flight would overwrite the claim and a compare finishing in that window would clear the marker; the worker's claim stamps `last_attempted_at` and no stage runs 30 minutes.

The accepted cost, found by the closing review, is that the row passes back through the producer statuses with `uploaded_at` set and the old segments still in the table, a state the Railway side's public predicate and held tab were written to exclude; decision `0049` records what that did to the public page and to a failed re-run, and the rule that removed it. The trap this record guards against is the agent who "simplifies" the re-run to a delete, or who nulls `compare_skipped_reason` on re-claim because the column's name says it is about a skipped compare.

## Date

2026-10-16, the plan author and the operator session in `plans/completed/transcriber-clean-speaker-segments.md` (the busy guard and the ghost-row delete are the operator's revisions after an external review); graduated from the plan's Decision Log at its retrospective.

## Status

accepted
