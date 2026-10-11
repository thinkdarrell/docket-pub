# 0031 — Transcript-stage response schemas never put null inside an enum and keep at most 16 nullable fields; an EventDetail string or list that does not apply is the empty string or the empty list, never null, and the pydantic models in src/docket/ai/transcripts/schemas.py stay in sync with the JSON schemas.

## Decision

Transcript-stage response schemas never put null inside an enum and keep at most 16 nullable fields; an EventDetail string or list that does not apply is the empty string or the empty list, never null, and the pydantic models in src/docket/ai/transcripts/schemas.py stay in sync with the JSON schemas.

## Rationale

The structured-outputs API rejects a schema with null inside an enum and caps nullable fields at 16 per schema, which the transcript event schema exceeded. Encoding "not applicable" as an empty value keeps every field present and the schema accepted, at the cost of callers checking for emptiness rather than None. Found during plan 2 of the transcripts work.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md as merged from PRs #105 and #106 (original decision 2026-10)

## Status

accepted
