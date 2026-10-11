# 0001 — The database is PostgreSQL in every environment; there is no SQLite path.

## Decision

The database is PostgreSQL in every environment; there is no SQLite path.

## Rationale

The predecessor repository, al-municipal-meetings, ran on SQLite and was Birmingham-only. Generalising it to several cities needed full-text search, JSONB for extracted facts, materialised views, and concurrent writers from the web app and the worker, none of which SQLite offers well. Carrying a SQLite fallback would have meant two schemas and two sets of migrations for one developer. The obvious alternative, SQLite locally and Postgres in production, was rejected because the integration tests would then exercise a different engine from the one serving readers.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-04)

## Status

accepted
