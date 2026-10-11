# 0024 — Analytics are read only through the v_* views in the umami database, as the read-only umami_reader role. The raw Umami tables (website_event, event_data, session) are never queried.

## Decision

Analytics are read only through the v_* views in the umami database, as the read-only umami_reader role. The raw Umami tables (website_event, event_data, session) are never queried.

## Rationale

Umami's internal schema changes between versions. The view layer is the one place that absorbs those changes, so every query written against the views survives an upgrade and every query written against raw tables breaks silently. The schema fixture at tests/fixtures/umami_schema_v3.sql is regenerated only on an Umami version bump.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-05-17)

## Status

accepted
