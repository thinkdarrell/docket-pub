# 0030 — The desktop transcriber connects as a PostgreSQL role that can write only transcripts, transcript_segments, transcript_speakers, and producer_heartbeats. Uploads are public on arrival.

## Decision

The desktop transcriber connects as a PostgreSQL role that can write only transcripts, transcript_segments, transcript_speakers, and producer_heartbeats. Uploads are public on arrival.

## Rationale

The transcriber runs on a machine outside Railway and holds database credentials on disk, so the role bounds what a leaked credential can do. The role is created once by scripts/sql/create_transcriber_role.sql and rotated with ALTER ROLE. Uploads are public immediately because a transcript is a verbatim record of a public meeting and holding it for review would add a human step with no editorial decision behind it.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-10)

## Status

accepted
