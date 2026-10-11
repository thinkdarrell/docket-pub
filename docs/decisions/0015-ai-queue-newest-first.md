# 0015 — The AI claim queries order by meeting_date DESC so a freshly ingested meeting is processed within one cron tick.

## Decision

The AI claim queries order by meeting_date DESC so a freshly ingested meeting is processed within one cron tick.

## Rationale

Readers care about this week's meeting; the archive backfill can wait its turn. With an ascending or arbitrary order the 2026 meetings sat behind tens of thousands of 2010 items and a new meeting could take days to render. Newest-first costs nothing and keeps the site current while the backfill runs underneath.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes

## Status

accepted
