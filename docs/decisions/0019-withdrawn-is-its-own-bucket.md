# 0019 — Items the council withdrew, deferred, or postponed get processing_status = 'withdrawn', a bucket distinct from procedural_skipped.

## Decision

Items the council withdrew, deferred, or postponed get processing_status = 'withdrawn', a bucket distinct from procedural_skipped.

## Rationale

The procedural-skipped queue, meant for roll calls and invocations, was polluted by 332 items the council had removed from the agenda, which made its counts and its admin view meaningless. Migration 023 added the enum value and is_withdrawn_or_deferred runs before is_procedural in Wave 0. Alternate marker shapes not yet matched are docs/DEBT.md D13.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-05-12)

## Status

accepted
