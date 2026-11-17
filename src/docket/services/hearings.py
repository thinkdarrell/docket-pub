"""Store each scheduled public hearing once, linked to every agenda item that set it.

A resolution on a council agenda sets a public hearing for a later date.
`docket.enrichment.hearings.read_hearing` reads that from an item's title;
this module finds the items (`find_readings`), tells which readings are one
hearing (`group_readings`), keeps `public_hearings` and
`public_hearing_items` in step with them (`refresh_hearings`,
`refresh_recent`), and lists the hearings of a span of dates for a reader
(`list_upcoming`). It owns every statement on the two tables (migration
047).

Two readings are one hearing when their dates and kinds are equal and
their subject keys are equal, or one key opens the other, the shorter is at
least `PREFIX_MIN` characters, and there is exactly one hearing it could
join. A short key that opens two hearings joins neither: a doubled entry
can be seen and reported, a hearing folded into another cannot.

A run can be repeated: links are upserted on the item, a stored hearing is
found again by the rule that made it, and a hearing left with no link is
deleted. No write loops over existing rows; the inserts are of new
hearings, a few a week (decision 0026).

Plan `birmingham-coming-up`, M2, whose Decision Log says why each rule is
what it is.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from psycopg2.extras import RealDictCursor, execute_values

from docket.db import db, db_cursor
from docket.enrichment.hearings import PREFIX_MIN, RULE_VERSION, read_hearing, same_hearing
from docket.services.query import CANCELLED_PREDICATE_MT

log = logging.getLogger(__name__)

# How far back `refresh_recent` reads, in days of meeting date. A hearing is
# set four to six weeks ahead, so every hearing still to come was set inside it.
RECENT_DAYS = 120

_CHICAGO = ZoneInfo("America/Chicago")


@dataclass(frozen=True)
class HearingReport:
    """What one run found and wrote.

    `matched` items whose title holds a trigger, of which `dated` gave a
    hearing date and `undated` none; `hearings` the dated ones make;
    `created` hearings stored for the first time; `linked` item links
    written, which on a repeated run is every dated item again.
    """

    matched: int
    dated: int
    undated: int
    hearings: int
    created: int
    linked: int


def _today() -> date:
    return datetime.now(_CHICAGO).date()


# The SQL test is wider than the reader's trigger (any "public hearing"); it
# only spares the reader the city's other titles. `read_hearing` decides.
_FIND_SQL = r"""
    SELECT ai.id AS item_id, ai.meeting_id, mt.meeting_date, ai.title
      FROM agenda_items ai
      JOIN meetings mt ON mt.id = ai.meeting_id
     WHERE mt.municipality_id = %(city)s
       AND mt.meeting_date >= %(since)s
       AND (%(until)s::date IS NULL OR mt.meeting_date <= %(until)s::date)
       AND ai.title ~* 'public\s+(show\s+cause\s+)?hearing'
     ORDER BY ai.id
"""


def find_readings(municipality_id: int, since: date, until: date | None = None) -> list[dict]:
    """Every item of the city's meetings dated `since` to `until` whose title reads as setting a hearing.

    One dict per item, in item-id order: `item_id`, `meeting_id`,
    `meeting_date`, `reading`. A reading with no date is returned too. One
    SELECT, which reads neither hearings table.
    """
    with db_cursor() as cur:
        cur.execute(_FIND_SQL, {"city": municipality_id, "since": since, "until": until})
        rows = cur.fetchall()
    found = []
    for row in rows:
        reading = read_hearing(row["title"])
        if reading is not None:
            found.append(
                {
                    "item_id": row["item_id"],
                    "meeting_id": row["meeting_id"],
                    "meeting_date": row["meeting_date"],
                    "reading": reading,
                }
            )
    return found


def group_readings(rows: list[dict]) -> list[dict]:
    """The hearings the dated rows make. Pure.

    Rows are taken longest key first (equal lengths in item-id order), so a
    group's first row carries its longest key and the answer does not
    depend on which item has the lower id. Each group is a dict of
    `hearing_date`, `kind`, `subject`, `subject_key`, `property_count` and
    `item_ids` (ascending); the groups are ordered by date and then by
    their lowest item id.
    """
    dated = [r for r in rows if r["reading"].hearing_date is not None]
    dated.sort(key=lambda r: (-len(r["reading"].subject_key), r["item_id"]))
    groups: list[dict] = []
    for row in dated:
        reading = row["reading"]
        key = reading.subject_key
        peers = [g for g in groups if g["hearing_date"] == reading.hearing_date and g["kind"] == reading.kind]
        home = next((g for g in peers if g["subject_key"] == key), None)
        if home is None and len(key) >= PREFIX_MIN:
            opened = [g for g in peers if g["subject_key"].startswith(key)]
            if len(opened) == 1:
                home = opened[0]
        if home is None:
            groups.append(
                {
                    "hearing_date": reading.hearing_date,
                    "kind": reading.kind,
                    "subject": reading.subject,
                    "subject_key": key,
                    "property_count": reading.property_count,
                    "item_ids": [row["item_id"]],
                }
            )
            continue
        home["item_ids"].append(row["item_id"])
        if home["property_count"] is None:
            home["property_count"] = reading.property_count
    for group in groups:
        group["item_ids"].sort()
    groups.sort(key=lambda g: (g["hearing_date"], g["item_ids"][0]))
    return groups


def _match_stored(groups: list[dict], stored: list[dict]) -> dict[int, dict]:
    """Which stored hearing each group is, by the group's index. Pure.

    Two passes over hearings of the group's date and kind: every group
    whose key a stored hearing holds exactly; then, for each group still
    unmatched, the one stored hearing not yet matched whose key
    `same_hearing` accepts, when there is exactly one.
    """
    matched: dict[int, dict] = {}
    taken: set[int] = set()

    def candidates(group: dict) -> list[dict]:
        return [
            s
            for s in stored
            if s["id"] not in taken and s["hearing_date"] == group["hearing_date"] and s["kind"] == group["kind"]
        ]

    for index, group in enumerate(groups):
        exact = [s for s in candidates(group) if s["subject_key"] == group["subject_key"]]
        if exact:
            matched[index] = exact[0]
            taken.add(exact[0]["id"])
    for index, group in enumerate(groups):
        if index in matched:
            continue
        accepted = [s for s in candidates(group) if same_hearing(s["subject_key"], group["subject_key"])]
        if len(accepted) == 1:
            matched[index] = accepted[0]
            taken.add(accepted[0]["id"])
    return matched


def refresh_hearings(municipality_id: int, since: date, until: date | None = None) -> HearingReport:
    """Bring the stored hearings in step with the items of meetings dated `since` to `until`.

    One transaction. An item in the range that no longer gives a dated
    reading loses its link, whether or not its title still matches
    anything; an item outside the range is not touched.
    """
    rows = find_readings(municipality_id, since, until)
    groups = group_readings(rows)
    dated_items = [item_id for group in groups for item_id in group["item_ids"]]
    created = 0

    with db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        stored: list[dict] = []
        if groups:
            cur.execute(
                """SELECT id, hearing_date, kind, subject_key
                     FROM public_hearings
                    WHERE municipality_id = %s AND hearing_date = ANY(%s)
                    ORDER BY id""",
                (municipality_id, sorted({g["hearing_date"] for g in groups})),
            )
            stored = [dict(r) for r in cur.fetchall()]
        matched = _match_stored(groups, stored)

        links: list[tuple[int, int]] = []
        for index, group in enumerate(groups):
            hearing = matched.get(index)
            if hearing is None:
                cur.execute(
                    """INSERT INTO public_hearings
                              (municipality_id, hearing_date, kind, subject, subject_key, property_count, rule_version)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       RETURNING id""",
                    (
                        municipality_id,
                        group["hearing_date"],
                        group["kind"],
                        group["subject"],
                        group["subject_key"],
                        group["property_count"],
                        RULE_VERSION,
                    ),
                )
                hearing_id = cur.fetchone()["id"]
                created += 1
            else:
                hearing_id = hearing["id"]
                if len(group["subject_key"]) > len(hearing["subject_key"]):
                    cur.execute(
                        "UPDATE public_hearings SET subject = %s, subject_key = %s, updated_at = now() WHERE id = %s",
                        (group["subject"], group["subject_key"], hearing_id),
                    )
            links.extend((item_id, hearing_id) for item_id in group["item_ids"])

        if links:
            execute_values(
                cur,
                """INSERT INTO public_hearing_items (agenda_item_id, hearing_id) VALUES %s
                   ON CONFLICT (agenda_item_id) DO UPDATE SET hearing_id = EXCLUDED.hearing_id""",
                links,
            )
        # With no dated item, `<> ALL('{}')` holds of every link in the range, as it should.
        cur.execute(
            """DELETE FROM public_hearing_items phi
                USING agenda_items ai, meetings mt
                WHERE ai.id = phi.agenda_item_id
                  AND mt.id = ai.meeting_id
                  AND mt.municipality_id = %(city)s
                  AND mt.meeting_date >= %(since)s
                  AND (%(until)s::date IS NULL OR mt.meeting_date <= %(until)s::date)
                  AND phi.agenda_item_id <> ALL(%(dated)s::int[])""",
            {"city": municipality_id, "since": since, "until": until, "dated": dated_items},
        )
        cur.execute(
            """DELETE FROM public_hearings h
                WHERE h.municipality_id = %s
                  AND NOT EXISTS (SELECT 1 FROM public_hearing_items phi WHERE phi.hearing_id = h.id)""",
            (municipality_id,),
        )

    return HearingReport(
        matched=len(rows),
        dated=len(dated_items),
        undated=len(rows) - len(dated_items),
        hearings=len(groups),
        created=created,
        linked=len(links),
    )


def refresh_recent(municipality_id: int) -> HearingReport | None:
    """`refresh_hearings` over the last `RECENT_DAYS` days, for a city whose metadata carries `"coming_up": true`; None for any other."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT metadata -> 'coming_up' = 'true'::jsonb AS flagged FROM municipalities WHERE id = %s",
            (municipality_id,),
        )
        row = cur.fetchone()
    if row is None or row["flagged"] is not True:
        return None
    return refresh_hearings(municipality_id, _today() - timedelta(days=RECENT_DAYS))


def list_upcoming(municipality_id: int, start: date, end: date) -> list[dict]:
    """The city's hearings dated `start` to `end` that have a visible link, in date order.

    Each is `id`, `hearing_date`, `kind`, `subject`, `property_count`, and
    `items`: its visible links, oldest meeting first, each `item_id`,
    `meeting_id`, `meeting_date`, `agenda_url`. A link is visible when its
    meeting is not hidden, its meeting's title does not say cancelled, and
    the item was not withdrawn: a withdrawn resolution set no hearing, an
    agenda for a cancelled meeting was not acted on, and a hidden meeting's
    item page answers 404. A hearing with no visible link is not returned.
    """
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT h.id, h.hearing_date, h.kind, h.subject, h.property_count,
                       ai.id AS item_id, mt.id AS meeting_id, mt.meeting_date, mt.agenda_url
                  FROM public_hearings h
                  JOIN public_hearing_items phi ON phi.hearing_id = h.id
                  JOIN agenda_items ai ON ai.id = phi.agenda_item_id
                  JOIN meetings mt ON mt.id = ai.meeting_id
                 WHERE h.municipality_id = %s
                   AND h.hearing_date >= %s
                   AND h.hearing_date <= %s
                   AND mt.is_hidden = FALSE
                   AND NOT {CANCELLED_PREDICATE_MT}
                   AND ai.processing_status::text IS DISTINCT FROM 'withdrawn'
                 ORDER BY h.hearing_date, h.id, mt.meeting_date, ai.id""",
            (municipality_id, start, end),
        )
        rows = cur.fetchall()
    listed: list[dict] = []
    for row in rows:
        if not listed or listed[-1]["id"] != row["id"]:
            listed.append(
                {
                    "id": row["id"],
                    "hearing_date": row["hearing_date"],
                    "kind": row["kind"],
                    "subject": row["subject"],
                    "property_count": row["property_count"],
                    "items": [],
                }
            )
        listed[-1]["items"].append(
            {
                "item_id": row["item_id"],
                "meeting_id": row["meeting_id"],
                "meeting_date": row["meeting_date"],
                "agenda_url": row["agenda_url"],
            }
        )
    return listed
