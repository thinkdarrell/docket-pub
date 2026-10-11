# 0033 — Birmingham meetings that Granicus never recorded (the May to December 2023 Boutwell Auditorium meetings) are created by services/archived_meetings.py from the council's YouTube channel and Wayback Machine copies of the old council site's agenda PDFs, with external ids yt-<video id> or archive-<date>, through the same item write path as ingest.

## Decision

Birmingham meetings that Granicus never recorded (the May to December 2023 Boutwell Auditorium meetings) are created by services/archived_meetings.py from the council's YouTube channel and Wayback Machine copies of the old council site's agenda PDFs, with external ids yt-<video id> or archive-<date>, through the same item write path as ingest.

## Rationale

Granicus external ids are numeric clip ids, so the yt- and archive- prefixes guarantee the daily ingest never collides with an archived row and the video OCR claim (numeric ids only) never picks one up. Boutwell-era video has no electronic vote board, so no OCR votes are possible for these meetings, and no minutes exist online for them (a City Clerk records request would be needed). Using the ingest write path keeps enrichment and AI processing identical to every other meeting.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md as merged from PRs #105 and #106 (original decision 2026-10)

## Status

accepted
