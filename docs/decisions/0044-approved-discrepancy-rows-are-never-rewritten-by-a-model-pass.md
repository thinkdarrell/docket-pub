# 0044 — A discrepancy row a person approved is never rewritten by a model pass; it is kept untouched on unchanged input and goes stale only when the input it was anchored to changed.

## Decision

`reconcile()` in `src/docket/ai/transcripts/compare.py` leaves a matched `approved` row of `minutes_discrepancies` exactly as the person approved it, every column including `prompt_version`, and uses the match only to stop the same finding from being inserted again beside it. An approved row goes `stale` only on a pass whose claim says the minutes PDF changed (`'minutes_changed'`) or the transcript events were re-extracted (`'transcript_changed'`), never because the model read the same input differently. `reset_for_versions()` in `pipeline.py` therefore counts only `proposed` and `dismissed_by_model` rows when deciding whether a `COMPARE_PROMPT_VERSION` bump re-queues a meeting.

## Rationale

The public meeting page says every difference it shows was reviewed by a person before it appeared (`src/docket/web/templates/partials/minutes_vs_video.html`), and the methodology page says a person reads both excerpts and approves or rejects each one. The plan that fixed issue #112 first shipped the obvious alternative: keep the row `approved` with its reviewer but refresh its title, description, severity, excerpts, confidence, and `prompt_version` from the model's second reading, on the argument that `GOALS.md` wants every AI sentence to carry the prompt version that produced it. The closing review showed where that lands: after any prompt bump or manual rerun the reader sees prose and quotes no person read, under a person's name, with no re-review chip (the queue keys it on `previous_review_state`, which that path never set) and only an aggregate log line. The other alternative, the pre-plan behaviour of staling every approved row on every pass, makes a human decision vanish from the public page whenever the model's second opinion differs, which is the defect #112 reported.

Freezing the row is the smallest rule that makes the page's promise true, and it has two costs that are accepted and recorded. First, a frozen row keeps the `prompt_version` that produced its text, so `reset_for_versions()` must not count approved rows or it would re-queue the meeting on every tick; a meeting whose only live rows are approved is therefore not re-compared by a prompt bump and is re-run by hand with `scripts/transcript_recompare.py`. Stamping the current version onto the untouched row was rejected because the column records which prompt wrote the text. Second, `match_stale()` matches an anchored row by category and `transcript_event_id` alone, so a different finding of the same category on the same event is suppressed like a verbatim restatement, with only the `kept=` count in the log naming it; a text comparison that re-proposes such a row beside the approval was not taken because it reintroduces the duplicate the match exists to prevent. The trap this record guards against is the later "refresh" that looks like keeping data current: an agent that sees an approved row carrying an old `prompt_version` and updates its text from a newer pass re-creates the finding the review called severe.

## Date

2026-10-12, the operator (Darrell Nance, with Claude) in `plans/completed/transcript-compare-row-fidelity.md`, reversing the plan's own earlier decision after the closing review's severe finding; graduated from the plan's Decision Log at its retrospective.

## Status

accepted
