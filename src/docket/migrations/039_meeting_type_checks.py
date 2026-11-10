"""Migration 039 — the CHECK on `meetings.meeting_type`: the body vocabulary is enforced once every city's rows conform.

`meeting_type` names the body that met: `council`, `committee`, `planning`,
`board`, or `other`. Migration 038 added `session_kind` for the sitting and
moved the old values `special` and `work_session` out of this column, but
left its CHECK for this migration, because a CHECK added then would have
failed on the rows still holding the old vocabulary. The operator ran the
reclassification on production through the evidence ladder first, for
Birmingham (2026-10-22) and for Vestavia Hills and Homewood (2026-11-08),
the two cities whose rows still held old values that day, and the
acceptance query `SELECT meeting_type, count(*) FROM meetings WHERE
meeting_type NOT IN (...) GROUP BY 1` printed no rows before this landed.

The UPDATE at the top is a guard, not a reclassification: on production it
writes nothing, and on a copy that still carries a stray test value (the
developer copy held `C`) or old-vocabulary rows never reclassified (the
same copy held 182 `special` and `work_session` rows) it folds those values
into `other`, `type_source` untouched, so the ALTER cannot fail. It
restates no rule of the classifier, since `other` is the vocabulary's own
"no body named" value; a row it touches is re-resolved from its title by
the next ingest that lists it, or by `scripts/reclassify_meetings.py` for
its city.

The vocabulary's one owner is `MEETING_TYPES` in
src/docket/adapters/_helpers.py; the literals here are frozen text, and
tests/integration/test_039_migration.py asserts they are equal so the two
cannot drift silently. The down drops the constraint and nothing else.
Plan `meeting-types-name-the-body` (M6).
"""

from __future__ import annotations


SQL_UP = r"""
UPDATE meetings
   SET meeting_type = 'other'
 WHERE meeting_type NOT IN ('council', 'committee', 'planning', 'board', 'other');

ALTER TABLE meetings DROP CONSTRAINT IF EXISTS meetings_meeting_type_check;
ALTER TABLE meetings ADD CONSTRAINT meetings_meeting_type_check
    CHECK (meeting_type IN ('council', 'committee', 'planning', 'board', 'other'));
"""

SQL_DOWN = r"""
ALTER TABLE meetings DROP CONSTRAINT IF EXISTS meetings_meeting_type_check;
"""
