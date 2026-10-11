# 0010 — An approval title such as 'Approval of Minutes from May 5, 12, 19 and 26, 2026' is tokenised into date lists and ranges in src/docket/analysis/minutes_approval.py. A title with a missing year or an unrecognised word inside the list is rejected and logged as adoption_parse_skip. There is no dateutil fallback.

## Decision

An approval title such as 'Approval of Minutes from May 5, 12, 19 and 26, 2026' is tokenised into date lists and ranges in src/docket/analysis/minutes_approval.py. A title with a missing year or an unrecognised word inside the list is rejected and logged as adoption_parse_skip. There is no dateutil fallback.

## Rationale

Guessing produced wrong adoption dates that PR #101 then had to correct across the archive, and a wrong adoption date promotes provisional links on the wrong meeting. One place owns the title grammar, shared with the agenda parser, so an agenda ingested from PDF keeps the un-numbered approval line as an item with a NULL item_number. The sweep still requires a passed vote in the adopting meeting.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-10)

## Status

accepted
