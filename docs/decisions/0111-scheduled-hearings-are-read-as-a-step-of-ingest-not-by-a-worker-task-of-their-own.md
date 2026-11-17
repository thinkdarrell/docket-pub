# 0111 — Scheduled hearings are read as a step of ingest, not by a worker task of their own

## Decision

Hearing extraction is stage 3c of `ingest_municipality` in `src/docket/services/ingest.py`: after the meeting-type stage, for a city whose metadata carries `"coming_up": true`, it re-reads the agenda items of the last 120 days of meetings and brings `public_hearings` level with them. A failure is recorded in the ingest result's errors and stops nothing. There is no scheduler entry, task wrapper, or Healthchecks check for hearings.

## Rationale

New agenda items arrive only through ingest, so a step of ingest runs exactly when there is something new to read, and a hearing appears on the page in the same run that stored the resolution setting it. A task of its own would run on a clock beside ingest's and be either early or redundant.

The alternative also had a cost counted at the time: a new worker task changes `src/docket/worker/`, which on 2026-11-16 would have tripped three overdue debt rows at once (`D69`, the prose task counts; `D34`, the `os.environ` reads in `worker/tasks.py` and `worker/health.py`) and needed a Healthchecks variable, an operator step.

The step is wrapped as the meeting-type stage beside it is, so a defect in the reader costs a line in the ingest result and not a day's ingest. It is idempotent by construction: links are upserted on the item, a stored hearing is found again by the rule that made it, and a hearing with no link is deleted, so re-reading 120 days on every run changes nothing when nothing changed and moves links when the reader's rules change. Meetings older than the window are read once by `scripts/backfill_hearings.py`, which has a dry run.

## Date

2026-11-16, the plan author (Claude) of plan `birmingham-coming-up`; built by the plan's M3 session on 2026-11-17.

## Status

accepted
