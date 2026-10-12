# Calibration

How docket.pub watches its own AI scoring for drift. Present tense. The schedule itself is the code in `src/docket/worker/scheduler.py`; this file does not restate it.

## What calibration compares

Every substantive agenda item is scored twice by the language model (Stage 2): a significance score and a consent-placement score, each 0 to 10. A deterministic step (Stage 2.5, `src/docket/ai/floors.py`) may then raise the significance score or lower the consent score when a rule fires. Calibration compares the model's original scores with the floored ones, and tracks the floored scores over time, so an operator can see a model that is drifting before readers do.

## Where the data lives

`agenda_items.score_overrides` is a JSONB column written by `src/docket/ai/pipeline.py` on every successful Stage 2 / 2.5 run. Its keys are `original_ai_significance`, `final_significance`, `original_ai_consent`, `final_consent`, `triggers` (a list), `conflicts` (a list), and `admin_override_used` (a boolean). The four scores are stored as JSON floats (`9.0`, not `9`), because the pipeline serialises pydantic float fields. The same Phase C UPDATE stamps `ai_generated_at = NOW()` since 2026-10 (issue #110); before that change the v3 pipeline never wrote the column. Rows scored by the v3 pipeline before that change, about 36,000 in production, have `ai_generated_at` NULL and fall outside every window below, so the dashboard and the report describe scoring since the change. `agenda_items` has `created_at` but no `updated_at`.

## The two readers

The daily worker task `calibration_report` (`src/docket/worker/tasks.py`, queries in `src/docket/ai/calibration.py`) runs four queries, prunes `ai_response_cache` rows not accessed in 90 days, and logs exactly one line:

    calibration_report: divergence=N underscoring=N overscoring=N drift_alerts=N cache_cleanup=N

`divergence` is the number of items in the last 24 hours whose final significance differs from the model's by more than 3. `underscoring` and `overscoring` are the number of `(action_type, prompt_version)` categories over the last 7 days with at least 30 items where more than 20 percent were boosted (significance) or reduced (consent). `drift_alerts` is the number of `(action_type, week)` rows in the 12-week baseline whose average significance fell by more than 1.0 week over week while volume moved by less than 30 percent. `cache_cleanup` is the number of cache rows deleted. A failure is logged as `task=calibration_report failed` with a traceback and is not re-raised. The task pings Healthchecks only when `HEALTHCHECK_CALIBRATION_UUID` is set on the `worker` service; it is unset in production, so a failure is silent (`docs/runbooks/cron-worker.md`).

The admin page `/admin/calibration` (`src/docket/web/admin.py`, queries in `src/docket/services/calibration.py`) renders six panels, each a table or a one-line empty state. A. Per-item divergence: items in the last 24 hours with a significance delta greater than 3, with the model's score, the final score, the delta, and the triggers that fired. B1. Under-scoring Impact and B2. Over-scoring Consent: per `(action_type, prompt_version)` over 7 days, at least 30 items, more than 20 percent boosted or reduced. C. Baseline drift: per `action_type` and week over 12 weeks, weeks with at least 10 items, with week-over-week deltas in average significance and volume. Badge volume calibration: per `(city, badge, week)` over 12 weeks, the share of policy badges detected only deterministically or only by the model. Top False Positives: policy badges that admins removed at least 5 times in the last 7 days.

## Rules every calibration query follows

Every score read from `score_overrides` is cast as `(ai.score_overrides->>'<key>')::numeric::int`, never `::int` directly, because PostgreSQL rejects the text `9.0` as an integer; `numeric` accepts both `9.0` and `9`, and `NULL` passes through as `NULL`. Every freshness filter and week bucket over `agenda_items` uses `ai.ai_generated_at`; the badge-volume and false-positive panels read badge tables instead and bucket on `aib.detected_at` and `aiba.occurred_at` respectively. `tests/integration/test_calibration.py` seeds a float-valued row shaped as production writes it and runs every query in both files against a real database, so either rule cannot regress silently.

## Known difference between the readers

The two files hold the same four queries written independently. Their Query C differs in where weeks with fewer than 10 items are dropped: the service drops them inside the weekly aggregate (`HAVING COUNT(*) >= 10`), so the week-over-week comparison skips low-volume weeks; the worker drops them after the window function (`WHERE n >= 10`), so a low-volume week still serves as the previous week for the one after it. The dashboard and the log line can therefore disagree on a drift row at a low-volume boundary. This is known and unresolved.
