# 0084 — A meeting's classification is two columns, the body and the sitting, each with a closed vocabulary the database enforces

## Decision

`meetings.meeting_type` names the body that met (`council`, `committee`, `planning`, `board`, `other`) and `meetings.session_kind` names the kind of sitting (`regular`, `special`, `work_session`, `budget_hearing`); `body_name` carries the body's name when a source supplies it, and `type_source` the rung of the evidence ladder (`0085`) that decided the row. A new kind of sitting is a `session_kind` value, never a `meeting_type` value. The two vocabularies have one owner, `MEETING_TYPES` and `SESSION_KINDS` in `src/docket/adapters/_helpers.py`, every other file imports them from there, and the database enforces them: migration 038 holds the CHECK on `session_kind` (and on `type_source`, widened by 040), migration 039 the CHECK on `meeting_type`, whose literals `tests/integration/test_039_migration.py` asserts equal to the tuple.

## Rationale

Before this, the one column `meeting_type` mixed bodies (`council`, `committee`, `planning`, `board`) with sittings (`special`, `work_session`), and the classifier's keyword order decided which won. "Special Called Finance Committee" lost its body to the word "special" and filed under no committee; "City Council Regular Work Session" counted as a council meeting, so the city page's opener could say "the council met" of a sitting at which nothing was voted; and every reader that wanted the body had to know which values were really sittings. The obvious alternative, one richer vocabulary (`council_special`, `committee_special`, `council_work_session`, ...), would have multiplied every predicate on the site by the number of sittings and still left a reader unable to ask "which body" without listing them all. The other alternative, leaving `meeting_type` alone and adding only `body_name`, would have kept the misfiling. Two columns let a predicate name the body or the sitting or both, and the briefing's "the council met" became `meeting_type = 'council' AND session_kind <> 'work_session'`, which admits a special called meeting at which the council voted and excludes a work session.

The CHECK on `meeting_type` did not land with the columns. Migration 038 could not add it, because production's rows still held `special` and `work_session` under the old vocabulary, and a migration that remapped them in SQL would have restated the classifier's rules in a second place (`docs/PRINCIPLES.md`, one owner per fact). Instead the operator reclassified each city's rows through the evidence ladder itself, one city at a time with a dry run first (Birmingham 2026-10-22, Vestavia Hills and Homewood 2026-11-08), and the CHECK landed in migration 039 once `SELECT meeting_type, count(*) FROM meetings WHERE meeting_type NOT IN (...) GROUP BY 1` printed no rows on production. The guard UPDATE at the top of 039 folds a stray value into `other` so the ALTER cannot fail on a copy that was never reclassified; it restates no rule, because `other` is the vocabulary's own "no body named" value and the next ingest re-resolves such a row from its title.

## Date

2026-10-21, Claude as the author of plan `meeting-types-name-the-body` with the operator's review findings; built in its M1, M2, and M6 and graduated by the M6 session on 2026-11-08.

## Status

accepted
