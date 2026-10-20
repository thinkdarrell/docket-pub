# 0062 — A member vote is resolved to its council member from the roster at insert and by a daily sweep, and an unresolved row stays as evidence

## Decision

`src/docket/services/member_votes.py` owns the rule that turns a stored member name into a `council_member_id`: roster-derived variants compared after apostrophe folding, scoped to the municipality and the half-open term window of decision `0004`, with a name that matches more than one seated member left unresolved. `src/docket/services/ingest.py` applies it to every minutes member vote at insert, and the worker task `resolve_member_votes` applies it daily to every row still NULL from any source. Nothing deletes an unresolved row; it is logged by name and count.

## Rationale

The one-shot `scripts/backfill_member_vote_ids.py` (deleted by the plan `member-votes-name-their-member`) was the only resolver from 2026-04 to 2026-10, was never scheduled, and built its variants with a straight apostrophe, so on 2026-10-20 76 percent of Birmingham's minutes member votes of the last twelve months carried no id and the one name the minutes print with a curly apostrophe could never match; the member pages counted a quarter of the real roll calls. Resolving at insert removes the lag for the source that produces most rows, and the sweep covers the OCR path's misses and any roster change. The script also deleted rows whose name it judged to be parser noise; a row read from the minutes is evidence of what the parser produced, and a noise name is a parser bug to fix at its source, so the sweep logs and keeps. The sweep writes one UPDATE per (municipality, stored name, member) bucket scoped by meeting dates, which keeps it inside decision `0026`.

## Date

2026-10-20, the plan author (Claude) in `plans/completed/member-votes-name-their-member.md`, applied in M2.

## Status

accepted
