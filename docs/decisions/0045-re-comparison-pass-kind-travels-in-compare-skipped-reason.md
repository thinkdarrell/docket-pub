# 0045 — The kind of re-comparison pass travels in `transcripts.compare_skipped_reason`, and every writer of that column sets or preserves it deliberately.

## Decision

The compare stage learns what kind of pass it is running from the one column its claim already carries, `transcripts.compare_skipped_reason`: `'minutes_changed'` (the weekly sweep, or `scripts/transcript_recompare.py --minutes-changed`), `'transcript_changed'` (the `EVENTS_PROMPT_VERSION` branch of `reset_for_versions()`, or the script with `--transcript-changed`), or NULL for a pass over unchanged input. No separate column records the pass kind. A write to that column anywhere under `src/docket/` either sets the kind on purpose or leaves the stored value alone, as `advance()` in `src/docket/ai/transcripts/pipeline.py` does for a stage before compare that reports no reason.

## Rationale

Issue #112 needed the stage to tell a pass that re-reads unchanged input from a pass whose input changed. The claim dictionary already carried `compare_skipped_reason`, `run_compare_stage` already tested it for `'minutes_changed'` to decide whether to re-extract the minutes side, and the only production writer of that value was the sweep, so the two paths #112 named (`reset_for_versions` and `run_for_meeting`) got the unchanged-input behaviour with no migration and no new plumbing, and a caller that forgets the keyword gets the safer default. The alternative, the issue's option B, a `stale_reason` column with an admin bucket, needs a migration and a template for the same signal and still hides an approved row from the public page.

The cost is that the column now carries two meanings, why the last compare was skipped and what kind of pass the next one is, and every writer has to respect the second one. The plan found one writer that did not (`advance()` cleared the marker on the events stage's status write and was changed to keep it), and the closing review found two more that still do not: `retry_transcript()` writes NULL, and the events stage's own minutes check writes `no_minutes` or `minutes_unavailable` over it (`D52` in `docs/DEBT.md`). An agent adding a writer of the column, or paying `D52` by adding a column, reads this record first: the choice was made for the size of one pull request, not on the merits of overloading the column, and a record superseding this one is the right way to move the signal.

## Date

2026-10-12, the plan author (Claude, for the operator) in `plans/completed/transcript-compare-row-fidelity.md`, with the `advance()` rule added by the M4 session; graduated from the plan's Decision Log at its retrospective.

## Status

accepted
