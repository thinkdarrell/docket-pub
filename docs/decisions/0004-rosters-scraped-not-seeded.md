# 0004 — Council members and their term dates are scraped and stored by migration, and member votes resolve to council_member_id dynamically from roster plus term dates, never from a hand-maintained name map.

## Decision

Council members and their term dates are scraped and stored by migration, and member votes resolve to council_member_id dynamically from roster plus term dates, never from a hand-maintained name map.

## Rationale

A hand-written name-to-id map rotted at the Birmingham council transition of 2025-10-28, when members changed and the map did not. Term-dated rosters with a half-open date predicate (term_start inclusive, term_end exclusive) resolve the right member for any meeting date, including the boundary day where one member leaves and another arrives. The backfill script scripts/backfill_member_vote_ids.py applies the same resolution to historical votes.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-04)

## Note, 2026-10-20

The sentence above naming `scripts/backfill_member_vote_ids.py` described the resolver as it was until 2026-10: a one-shot script, last changed 2026-05-01, never scheduled, matching exact roster-derived variants built with a straight apostrophe, so the minutes' curly `O’Quinn` never matched. Since the plan `member-votes-name-their-member` the rule lives in `src/docket/services/member_votes.py`, runs at insert in `src/docket/services/ingest.py` and daily as the worker task `resolve_member_votes`, compares names after folding curly and straight apostrophes to one form, and leaves a name that matches two seated members unresolved; the script is deleted. The decision stands.

## Status

accepted
