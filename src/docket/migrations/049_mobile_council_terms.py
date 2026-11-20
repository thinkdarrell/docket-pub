"""Migration 049 — Mobile's council roster with term dates, from the city's own documents.

Migration 005 seeded seven Mobile members with no term dates, two of whom
(William Carroll and Beau Fleming) never sat at the same time. This migration
dates the seated seven, keeps the three members who left since November 2021
as dated inactive rows, and adds the member 005 did not have. Decision `0004`:
a roster goes in by migration, and a name resolves to a member through the
half-open term window, `term_start <= meeting date < term_end`.

`term_start` is the date of the first roll call this project has read that
lists the member; `term_end` is the date of the first roll call that lists the
successor. Neither is an inauguration date. One row covers a member who sat
through both council terms.

The roll calls, from the minutes on the city's CivicClerk system
(`https://mobileal.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=N,plainText=false)`),
read 2026-11-20:

- 2021-11-02, event 118, file 197: "Penn, Carroll, Small, Reynolds, Daves,
  Scott and Gregory".
- 2022-09-13, file 534 (attached to the event of 2023-05-02): "Penn, Carroll,
  Small, Reynolds, Daves, Jones, and Gregory".
- 2023-03-28, file 603 (the event of that date): the same seven, with Jones.
- 2023-08-08, file 701 (attached to the event of 2024-01-30): the pre-council
  conference lists "Penn, Carroll, Small, Reynolds, Daves, and Gregory"; the
  regular meeting's roll call lists "Chairman: Small, Vice-Chairman: Gregory,
  Councilmembers: Penn, Carroll, Reynolds, Daves, and Woods".
- 2025-10-28, event 442, file 1350: "Penn, Carroll, Small, Reynolds, Daves,
  Woods, and Gregory".
- 2025-11-04, event 443, file 1351: "Penn, Ingram, Small, Reynolds, Fleming,
  Woods, and Gregory".
- 2026-11-03, event 499, file 3854: "Chairman: Small, Vice-Chairman: Gregory,
  Councilmembers: Penn, Ingram, Reynolds, Fleming, and Woods".

The names and districts:

- The seated seven, `https://www.cityofmobile.gov/government/city-council/`,
  read 2026-11-20: District 1 Cory Penn, District 2 Samantha Ingram,
  District 3 C.J. Small, District 4 Ben Reynolds, District 5 Beau Fleming,
  District 6 Josh Woods, District 7 Gina Gregory.
- `https://www.cityofmobile.gov/uploads/file_library/2022-acfr-final-032423.pdf`
  (the annual financial report for fiscal 2022): "William Carroll (District
  2), Joel Daves (District 5), and Scott Jones (District 6)".
- `https://www.cityofmobile.gov/uploads/250320103140OrganizationalChart5.pdf`
  (the organisational chart of March 2025): "Council District 5 – Joel Daves"
  and "Council District 6 – Josh Woods".
- `https://www.cityofmobile.gov/city-council/city-councils-administrative-services-committee-to-meet/`
  (dated October 4, 2022): "Councilman Scott Jones, District 6".
- `https://www.cityofmobile.gov/city-council/city-council-meeting-recap-august-8-2023/`:
  "On August 8, Josh Woods took the oath of office as the new Councilman for
  District 6".

What each row is given:

- Penn, Small, Reynolds, Gregory: `term_start` 2021-11-02, where none is stored.
- Carroll: 2021-11-02 to 2025-11-04, inactive (Ingram is on the roll call of
  2025-11-04 and he is not).
- Woods: `term_start` 2023-08-08. Fleming: `term_start` 2025-11-04.
- Samantha Ingram, District 2, from 2025-11-04, active: inserted.
- Joel Daves, District 5, 2021-11-02 to 2025-11-04, inactive: inserted.
- Scott Jones, District 6, 2021-11-02 to 2023-08-08, inactive: inserted.

Two things this does not settle. The last roll call that lists Jones was not
found: he is on the roll call of 2023-03-28 and not on that of 2023-08-08, so
his row ends on the day Woods's begins, and on a date between the two on which
he had already left the row still answers to "Jones". And the "Scott" of the
2021-11-02 minutes is probably Scott Jones written by his first name, which no
document read says; the resolver in `docket.services.member_votes` answers to
a surname or an initial with a surname, so the row `Scott Jones` does not
answer to "Scott".

Every statement is scoped to the municipality whose slug is `mobile` and finds
a row by its whole-word surname (the name is the surname, ends with a space
and the surname, or holds the surname between spaces), so a first name spelled
another way or a suffix after the surname does not make it miss.
`council_members` has no unique constraint, so the inserts are guarded by
`WHERE NOT EXISTS` on the surname; a second run adds no row and changes none.

The down deletes the rows of the three inserted surnames, sets the term dates
of the other seven back to NULL, and makes Carroll active again: the state
migration 005 left.

Plan `mobile-agendas-flow-again`, M5.
"""

from __future__ import annotations

_MOBILE = "(SELECT id FROM municipalities WHERE slug = 'mobile')"


def _surname(surname: str, column: str = "name") -> str:
    """The whole-word match of one surname, as SQL."""
    return (
        f"({column} = '{surname}' OR {column} ILIKE '% {surname}' "
        f"OR {column} ILIKE '% {surname} %')"
    )


def _surnames(*surnames: str) -> str:
    return "(" + " OR ".join(_surname(s) for s in surnames) + ")"


def _insert(name: str, district: int, term_start: str, term_end: str | None, active: bool) -> str:
    surname = name.rsplit(" ", 1)[-1]
    end = f"DATE '{term_end}'" if term_end else "NULL"
    return f"""
INSERT INTO council_members (municipality_id, district_id, name, term_start, term_end, active)
SELECT m.id, d.id, '{name}', DATE '{term_start}', {end}, {'TRUE' if active else 'FALSE'}
  FROM municipalities m
  JOIN districts d ON d.municipality_id = m.id AND d.number = {district}
 WHERE m.slug = 'mobile'
   AND NOT EXISTS (
       SELECT 1 FROM council_members cm
        WHERE cm.municipality_id = m.id AND {_surname(surname, 'cm.name')});
"""


SQL_UP = f"""
UPDATE council_members SET term_start = DATE '2021-11-02'
 WHERE municipality_id = {_MOBILE}
   AND term_start IS NULL
   AND {_surnames('Penn', 'Small', 'Reynolds', 'Gregory')};

UPDATE council_members
   SET term_start = DATE '2021-11-02', term_end = DATE '2025-11-04', active = FALSE
 WHERE municipality_id = {_MOBILE} AND {_surname('Carroll')};

UPDATE council_members SET term_start = DATE '2023-08-08'
 WHERE municipality_id = {_MOBILE} AND {_surname('Woods')};

UPDATE council_members SET term_start = DATE '2025-11-04'
 WHERE municipality_id = {_MOBILE} AND {_surname('Fleming')};
{_insert('Samantha Ingram', 2, '2025-11-04', None, True)}
{_insert('Joel Daves', 5, '2021-11-02', '2025-11-04', False)}
{_insert('Scott Jones', 6, '2021-11-02', '2023-08-08', False)}
"""

SQL_DOWN = f"""
DELETE FROM council_members
 WHERE municipality_id = {_MOBILE} AND {_surnames('Ingram', 'Daves', 'Jones')};

UPDATE council_members SET term_start = NULL, term_end = NULL
 WHERE municipality_id = {_MOBILE}
   AND {_surnames('Penn', 'Carroll', 'Small', 'Reynolds', 'Fleming', 'Woods', 'Gregory')};

UPDATE council_members SET active = TRUE
 WHERE municipality_id = {_MOBILE} AND {_surname('Carroll')};
"""
