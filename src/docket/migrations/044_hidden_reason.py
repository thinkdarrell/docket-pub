"""Migration 044 — why a meeting is hidden, and the exemption an admin's unhide leaves: `meetings.hidden_reason` and `meetings.keep_visible_at`.

Until now a hidden row (`is_hidden`, migration 033) said when it was hidden
and by which admin, and nothing said why. Three writers set the flag after
this migration, and each writes its reason:

- `admin`: the admin route `hide_meeting`;
- `absorbed`: the YouTube pass, for a `yt-` row merged into the Granicus
  clip that arrived later and kept because it has a transcript;
- `not_a_meeting`: the daily task `non_meetings`
  (`docket.services.non_meetings`), for a short or speechless clip on a
  day the city's calendar shows no council or committee event.

No value is set on existing rows: a hidden row with a NULL reason predates
the column. `keep_visible_at` is set by the admin's unhide and never
cleared; the `non_meetings` rule does not hide a row that carries it, so a
clip brought back by hand does not vanish again the next morning.

Additive. The down drops the constraint and the two columns and leaves
`is_hidden` as it was, so hidden rows stay hidden and lose only their reason.
Plan `committee-clips-named-or-hidden`, M4.
"""

from __future__ import annotations


SQL_UP = r"""
ALTER TABLE meetings
    ADD COLUMN IF NOT EXISTS hidden_reason TEXT NULL,
    ADD COLUMN IF NOT EXISTS keep_visible_at TIMESTAMPTZ NULL;

ALTER TABLE meetings DROP CONSTRAINT IF EXISTS meetings_hidden_reason_check;
ALTER TABLE meetings ADD CONSTRAINT meetings_hidden_reason_check
    CHECK (hidden_reason IN ('admin', 'absorbed', 'not_a_meeting'));
"""

SQL_DOWN = r"""
ALTER TABLE meetings DROP CONSTRAINT IF EXISTS meetings_hidden_reason_check;

ALTER TABLE meetings
    DROP COLUMN IF EXISTS keep_visible_at,
    DROP COLUMN IF EXISTS hidden_reason;
"""
