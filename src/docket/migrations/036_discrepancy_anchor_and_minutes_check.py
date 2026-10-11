"""Migration 036 — drop the discrepancy has-event CHECK; add minutes_texts.last_checked_at.

minutes_discrepancies.transcript_event_id / minutes_event_id are FKs with
ON DELETE SET NULL. Re-extracting one side of a meeting's events deletes that
side's meeting_events rows, and Postgres then NULLs the reference on every
one-sided row (an `addition` or `omission`) — which the CHECK rejected, so a
minutes-changed re-comparison, a forced recompare, or an EVENTS_PROMPT_VERSION
bump crashed. compare.build_rows still refuses to insert a row with no
anchor; a stale or unmatched row may end with both anchors NULL after a
re-extraction, and such rows never render.

last_checked_at records when the weekly minutes sweep last re-downloaded a
meeting's minutes (whatever the outcome), so failing rechecks no longer
starve the sweep. extracted_at keeps meaning "text extracted at".
"""

from __future__ import annotations


SQL_UP = r"""
ALTER TABLE minutes_discrepancies DROP CONSTRAINT IF EXISTS minutes_discrepancies_has_event;
ALTER TABLE minutes_texts ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ;
"""

# The constraint comes back NOT VALID: rows left with both anchors NULL by a
# re-extraction while 036 was applied would make a validating ADD CONSTRAINT
# fail, so existing rows are not checked; new and updated rows are.
SQL_DOWN = r"""
ALTER TABLE minutes_texts DROP COLUMN IF EXISTS last_checked_at;
ALTER TABLE minutes_discrepancies DROP CONSTRAINT IF EXISTS minutes_discrepancies_has_event;
ALTER TABLE minutes_discrepancies ADD CONSTRAINT minutes_discrepancies_has_event
    CHECK (transcript_event_id IS NOT NULL OR minutes_event_id IS NOT NULL) NOT VALID;
"""
