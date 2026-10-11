# 0011 — A meeting's executive summary is written provisionally when its items are processed and overwritten once meetings.minutes_adopted_at is set.

## Decision

A meeting's executive summary is written provisionally when its items are processed and overwritten once meetings.minutes_adopted_at is set.

## Rationale

Readers want a summary within a day of the meeting, but the official record arrives weeks later when the minutes are adopted. Writing once, late, would leave the busiest week of a meeting's life unsummarised; writing once, early, would freeze a summary built on provisional links. Two passes keyed off minutes_adopted_at give both, and the adopted pass is the one that stands. Under IMPACT_FIRST_ENABLED the claim query also refuses a meeting whose items are still mid-pipeline, so a summary never describes an agenda that is still settling (fix of 2026-10-06).

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes

## Status

accepted
