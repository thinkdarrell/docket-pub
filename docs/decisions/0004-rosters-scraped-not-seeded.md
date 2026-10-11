# 0004 — Council members and their term dates are scraped and stored by migration, and member votes resolve to council_member_id dynamically from roster plus term dates, never from a hand-maintained name map.

## Decision

Council members and their term dates are scraped and stored by migration, and member votes resolve to council_member_id dynamically from roster plus term dates, never from a hand-maintained name map.

## Rationale

A hand-written name-to-id map rotted at the Birmingham council transition of 2025-10-28, when members changed and the map did not. Term-dated rosters with a half-open date predicate (term_start inclusive, term_end exclusive) resolve the right member for any meeting date, including the boundary day where one member leaves and another arrives. The backfill script scripts/backfill_member_vote_ids.py applies the same resolution to historical votes.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-04)

## Status

accepted
