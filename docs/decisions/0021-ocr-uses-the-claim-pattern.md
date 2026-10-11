# 0021 — OCR work is claimed with an atomic UPDATE ... RETURNING fed by a CTE using FOR UPDATE SKIP LOCKED. The attempt counter is bumped at claim time, with a cap of 3 attempts, a 24-hour backoff, and a 60-day window.

## Decision

OCR work is claimed with an atomic UPDATE ... RETURNING fed by a CTE using FOR UPDATE SKIP LOCKED. The attempt counter is bumped at claim time, with a cap of 3 attempts, a 24-hour backoff, and a 60-day window.

## Rationale

Two worker instances must never scan the same meeting, and a crash in the middle of a scan must still consume an attempt or a broken video would be retried forever. Claiming first and holding no row lock during the scan gives both properties. The 60-day window bounds the daily work; widening it is docs/DEBT.md D20.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-05-22)

## Status

accepted
