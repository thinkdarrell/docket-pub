# 0043 — Calibration keys freshness on `agenda_items.ai_generated_at`, and the Phase C UPDATE that writes the scores stamps it in the same statement.

## Decision

Both calibration readers filter and bucket rows of `agenda_items` by `ai_generated_at`, and the Phase C `UPDATE agenda_items` in `src/docket/ai/pipeline.py` sets `ai_generated_at = NOW()` in the same statement that writes `score_overrides` and the scores. No other column stands in for "when this item was last scored", and the stamp is not moved to a separate write.

## Rationale

The worker's queries filtered on `ai.updated_at`, a column `agenda_items` has never had (migration 001 gave `updated_at` to `meetings` and `municipalities` only), so the task crashed daily from 2026-05-11. The service's queries already used `ai_generated_at`, the column migration 012 added for exactly this meaning, and `GOALS.md` requires a generated-at timestamp stored on the same row as every AI-generated sentence. Keying both readers on the same column makes the worker's log line and the admin page agree on which rows are recent.

The column was the right one, but the v3 pipeline had never written it: the Phase C UPDATE set nine columns and not this one, so on 2026-10-12 about 36,000 of the 40,000 production rows holding `score_overrides` had it NULL, and the readers, once they no longer crashed, reported zeros that read as "no drift". The alternative considered was to key freshness on a column v3 does write; there is none that means scoring time (`created_at` is ingest time, and the badge tables cover only items that got a badge). Stamping in the same UPDATE is one SET line, atomic with the scores it describes, and matches what the v2 writers in `src/docket/ai/worker.py` did. The rows scored before the stamp are a separate, recorded piece of work (`D47` in `docs/DEBT.md`); this record binds only the column and where it is written.

## Date

2026-10-12, the operator (with Claude) in `plans/completed/calibration-float-scores.md`, after the closing review's severe finding; graduated from the plan's Decision Log at its retrospective.

## Status

accepted
