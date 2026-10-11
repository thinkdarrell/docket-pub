# 0008 — A vote_agenda_items row with is_manual = TRUE is never changed by automation. The shield is enforced twice: an application check in _upsert_link and a WHERE is_manual = FALSE predicate on every UPDATE the matcher issues.

## Decision

A vote_agenda_items row with is_manual = TRUE is never changed by automation. The shield is enforced twice: an application check in _upsert_link and a WHERE is_manual = FALSE predicate on every UPDATE the matcher issues.

## Rationale

A human correction must survive every future matcher run, including runs by code that has not been written yet. The application check gives a clear error path; the SQL predicate guarantees the row even if a future caller bypasses the helper. One layer alone was judged insufficient for a correction a reader may have been told about.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes

## Status

accepted
