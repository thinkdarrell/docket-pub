# 0007 — Consent links insert as provisional and become official when the council adopts the minutes. The adoption sweep sets meetings.minutes_adopted_at and calls the matcher; the matcher calls strict re-parse for any adopted meeting that still holds provisional links.

## Decision

Consent links insert as provisional and become official when the council adopts the minutes. The adoption sweep sets meetings.minutes_adopted_at and calls the matcher; the matcher calls strict re-parse for any adopted meeting that still holds provisional links.

## Rationale

Birmingham approves minutes weeks later, in batches that name several dates. Until then the consent links are the best available reading of the agenda, so they are shown with a provisional pill rather than hidden. The dual trigger exists so that links always exist before promotion is attempted, and so the daily cron does not re-download a minutes PDF for a meeting already promoted. services/maintenance.py finishes any adopted meeting an interrupted sweep left provisional.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes

## Status

accepted
