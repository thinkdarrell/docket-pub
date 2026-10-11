# 0009 — Strict re-parse deactivates a consent link only when the item is absent from the minutes' enumerated resolution list and the minutes record a separate vote on that item. A mere failure to match leaves the link active, and an empty resolved set is safe.

## Decision

Strict re-parse deactivates a consent link only when the item is absent from the minutes' enumerated resolution list and the minutes record a separate vote on that item. A mere failure to match leaves the link active, and an empty resolved set is safe.

## Rationale

The earlier rule deactivated any consent link the resolver failed to match, which hid most consent votes on adopted meetings behind ordinary parser misses. PR #95 changed the rule to require positive evidence that the item was pulled from consent and voted separately, and PR #100 restored the links the old rule had hidden. Video OCR links do not count as that evidence because OCR cannot see which item a vote concerned.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-10)

## Status

accepted
