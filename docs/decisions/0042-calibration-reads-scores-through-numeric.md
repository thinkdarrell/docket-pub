# 0042 — Calibration readers cast every `score_overrides` score through `numeric` before `int`, whatever the writer serialises today.

## Decision

Every read of a score from `agenda_items.score_overrides` in `src/docket/ai/calibration.py` and `src/docket/services/calibration.py` has the shape `(ai.score_overrides->>'<key>')::numeric::int`. The cast is not simplified to `::int` when, or if, the writer is changed to serialise whole numbers, and the production rows are not rewritten to make such a simplification safe.

## Rationale

The pipeline writes the four scores as JSON floats (`9.0`), because `ItemRewrite` in `src/docket/ai/rewrite_schema.py` types them `float | None` and `json.dumps` keeps the decimal point. PostgreSQL's integer input rejects the text `9.0`, so a bare `::int` crashed both readers (issue #110; runbook item #56 in `docs/runbooks/v3-cutover.md`). `numeric` accepts `9.0`, `9`, and `NULL`, so the cast reads every shape the column has ever held.

The obvious alternative, retyping the schema to `int` so the writer stores `9`, was rejected because it does not fix the readers: on 2026-10-12 about 40,000 production rows already held floats and would keep them under any writer change, so the readers must cope regardless; a backfill to rewrite them is an operator step under decision `0026`, not part of a bug fix; and retyping the pydantic schema changes what the model's tool-use output must validate against, which decision `0027` says needs a live smoke test. The trap this record guards against is the later simplification: an agent that makes the writer store whole numbers, sees `::numeric::int` as redundant, and reverts it to `::int` re-creates the crash on every row written before that change. The cast stays until no row holds a float, which is a count to observe, not an assumption.

## Date

2026-10-11, the plan author (Claude, for the operator) in `plans/completed/calibration-float-scores.md`; graduated from the plan's Decision Log at its retrospective.

## Status

accepted
