"""Migration 050 — what a minutes reader stores, and Scott Jones's row from the roll calls read.

Three additions and one correction. Plan `mobile-votes-from-minutes`, M2.

`votes` gains five columns, all NULL on every row written before a minutes
reader: `minutes_reader` (which reader wrote the row; `'mobile'` is the first),
`source_page` (the page of the minutes file the vote is printed on),
`caption` (the item's caption as the minutes print it), `motion_text` (the
motion), and `declared_text` (what the presiding officer declared, in the
minutes' words). A row with `minutes_reader` set is passed over by the text
rules of `docket.analysis.vote_matcher`.

`minutes_files` holds one row per Minutes file a reader has read for a city:
the file's id and address in the city's system, the event it is attached to,
what became of it (`paired` to the one meeting its heading dates,
`superseded` by another file of the same meeting, `not_minutes`, `no_meeting`,
`error`), and the reader version that read it. A meeting has at most one
`paired` file (the partial unique index), so a replacement sets the old row
`superseded` before the new one becomes `paired`, in one transaction. A
meeting that is deleted leaves its file rows, naming no meeting.

`council_members.aliases` holds other names a source prints for a member.
`docket.services.member_votes.RosterIndex` answers to an alias inside the
member's own term, as it answers to the surname.

The correction is to Scott Jones's row (District 6), which migration
`049_mobile_council_terms` wrote without having read a minutes file. The roll
calls, from the minutes on the city's CivicClerk system
(`https://mobileal.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=N,plainText=false)`),
read 2026-11-21:

- "Scott" and "Jones" are one member. Every roll call from 2021-11-02 to
  2022-07-19 lists `Scott` in the seventh place, and the same minutes list
  `Jones` in some of their votes. 2021-11-09, file 185: the roll call reads
  "Councilmembers: Penn, Carroll, Reynolds, Daves, Scott and Gregory", 19 votes
  list `Scott`, 4 list `Jones`, and a waiver is "seconded by Councilmember
  Jones". 2021-11-23, file 160: the conference lists `Scott` and a motion is
  "seconded by Councilmember Jones" with "Ayes: Penn, Carroll, Small, Reynolds,
  Jones and Gregory". Across the 1,275 votes of November 2021 to July 2022
  none lists both names. So his row takes the alias `Scott`, and its
  `term_start` of 2021-11-02 stands.
- His last roll call is that of 2023-04-04, file 213: "Councilmembers: Penn,
  Carroll, Reynolds, Daves, and Jones". That of 2023-04-11, file 253, lists
  "Penn, Carroll, Reynolds, and Daves", and every roll call after it until
  2023-08-08 lists six members without him. Under decision `0004` a term ends
  on the date of the first roll call that does not list the member, so
  `term_end` moves from 2023-08-08 to 2023-04-11; the seat is vacant until
  Josh Woods's term begins on 2023-08-08. Two votes in the minutes of
  2023-04-25 print `Jones` among seven ayes while that meeting's roll call
  lists six; under the new date those two names resolve to nobody and are
  shown as printed.

The roster statement is scoped to the municipality whose slug is `mobile` and
finds the row by its whole-word surname, as migration 049 does. It is exported
as `ROSTER_SQL` because `tests/integration/test_049_migration.py` rolls 049
back and applies it again inside a test, which leaves the row as 049 alone
writes it; that test runs `ROSTER_SQL` afterwards. Every statement of the up
is harmless to repeat.

The down sets the date back to 2023-08-08 and drops the index, the table and
the six columns, in that order; what a reader stored in them goes with them.
"""

from __future__ import annotations

_MOBILE = "(SELECT id FROM municipalities WHERE slug = 'mobile')"
_JONES = "(name = 'Jones' OR name ILIKE '% Jones' OR name ILIKE '% Jones %')"

ROSTER_SQL = f"""
UPDATE council_members SET aliases = ARRAY['Scott'], term_end = DATE '2023-04-11'
 WHERE municipality_id = {_MOBILE}
   AND {_JONES};
"""

SQL_UP = f"""
ALTER TABLE votes ADD COLUMN IF NOT EXISTS minutes_reader TEXT;
ALTER TABLE votes ADD COLUMN IF NOT EXISTS source_page INTEGER;
ALTER TABLE votes ADD COLUMN IF NOT EXISTS caption TEXT;
ALTER TABLE votes ADD COLUMN IF NOT EXISTS motion_text TEXT;
ALTER TABLE votes ADD COLUMN IF NOT EXISTS declared_text TEXT;
ALTER TABLE council_members ADD COLUMN IF NOT EXISTS aliases TEXT[] NOT NULL DEFAULT '{{}}';

CREATE TABLE IF NOT EXISTS minutes_files (
    id                SERIAL PRIMARY KEY,
    municipality_id   INTEGER NOT NULL REFERENCES municipalities(id) ON DELETE CASCADE,
    file_id           TEXT NOT NULL,
    url               TEXT NOT NULL,
    event_external_id TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('paired', 'superseded', 'not_minutes', 'no_meeting', 'error')),
    header_date       DATE,
    meeting_id        INTEGER REFERENCES meetings(id) ON DELETE SET NULL,
    page_count        INTEGER,
    votes_stored      INTEGER NOT NULL DEFAULT 0,
    reader_version    INTEGER NOT NULL,
    attempts          INTEGER NOT NULL DEFAULT 1,
    error             TEXT,
    read_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (municipality_id, file_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS minutes_files_one_paired_per_meeting
    ON minutes_files (meeting_id) WHERE status = 'paired';
{ROSTER_SQL}"""

SQL_DOWN = f"""
UPDATE council_members SET term_end = DATE '2023-08-08'
 WHERE municipality_id = {_MOBILE}
   AND {_JONES};

DROP INDEX IF EXISTS minutes_files_one_paired_per_meeting;
DROP TABLE IF EXISTS minutes_files;
ALTER TABLE council_members DROP COLUMN IF EXISTS aliases;
ALTER TABLE votes DROP COLUMN IF EXISTS declared_text;
ALTER TABLE votes DROP COLUMN IF EXISTS motion_text;
ALTER TABLE votes DROP COLUMN IF EXISTS caption;
ALTER TABLE votes DROP COLUMN IF EXISTS source_page;
ALTER TABLE votes DROP COLUMN IF EXISTS minutes_reader;
"""
