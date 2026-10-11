# 0023 — The cron worker is its own Railway service with a custom start command running python -m docket.worker.scheduler. The worker: line in the Procfile is informational only.

## Decision

The cron worker is its own Railway service with a custom start command running python -m docket.worker.scheduler. The worker: line in the Procfile is informational only.

## Rationale

Railway runs only the web: line of a Procfile. The worker was created once in the dashboard as an empty service pointing at the same image with the web service's environment variables copied over, and is redeployed with scripts/deploy.sh --service worker. A single service running both processes would couple the web app's restarts to a long-running OCR scan.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-05-04)

## Status

accepted
