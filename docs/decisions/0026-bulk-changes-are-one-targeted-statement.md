# 0026 — Bulk reclassification or correction on production is one SQL UPDATE scoped by a WHERE clause, never a per-row sweep driven from the CLI or a script loop.

## Decision

Bulk reclassification or correction on production is one SQL UPDATE scoped by a WHERE clause, never a per-row sweep driven from the CLI or a script loop.

## Rationale

On 2026-05-12 a Wave 0 sweep over about 57,000 items from the CLI wrote roughly 360 MB of write-ahead log, overflowed the 500 MB Railway Postgres volume, and crash-looped the database until the volume was resized to 1 GB. A targeted UPDATE over hundreds of rows writes about 3 MB. If a full sweep is ever genuinely needed, the volume is resized to at least 5 GB first.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-05-12)

## Status

accepted
