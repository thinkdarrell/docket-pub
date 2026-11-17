"""List the public hearings a city's agenda items set, and store them, or only list them with --dry-run.

For every agenda item of the city's meetings dated ``--since`` to
``--until`` whose title reads as a resolution setting a public hearing
(``docket.enrichment.hearings.read_hearing``), prints one line, in item-id
order:

    <item id>  <meeting date>  <hearing date or "no date">  <kind>  <property count or "-">  <first 70 characters of the title>

then one line per hearing the dated items make
(``hearing <date> <kind> items=<ids>``), then
``matched=<n> dated=<n> undated=<n> hearings=<n>``. An item with no date is
listed and never stored.

With ``--dry-run`` that is all: the script looks the city up, issues one
SELECT of its agenda items, and reads neither hearings table, so it runs
against a database migration 047 has not reached. Without ``--dry-run`` it
then brings ``public_hearings`` and ``public_hearing_items`` in step with
what was printed, in one transaction (``docket.services.hearings``), and
prints ``created=<n> linked=<n>``. A second run creates nothing and prints
``created=0``.

``--since`` is required: the script refuses to run without a bound.

Dry run first:
    python scripts/backfill_hearings.py --city birmingham --since 2025-01-01 --dry-run
    python scripts/backfill_hearings.py --city birmingham --since 2025-01-01

Against production the operator sets DATABASE_URL to DATABASE_PUBLIC_URL
(``docs/specs/operations.md``). The undo is one statement, whose cascade
removes the links:
``DELETE FROM public_hearings WHERE municipality_id = (SELECT id FROM municipalities WHERE slug = '<city>')``.
Plan `birmingham-coming-up`, M3.
"""

import argparse
import logging
import re
import sys
from datetime import date

from docket.services import hearings, query

logging.basicConfig(level=logging.WARNING, format="%(message)s")

TITLE_SHOWN = 70


def _item_line(row: dict) -> str:
    reading = row["reading"]
    title = re.sub(r"\s+", " ", row["title"])
    count = "-" if reading.property_count is None else reading.property_count
    return (
        f"{row['item_id']}  {row['meeting_date']}  {reading.hearing_date or 'no date'}  "
        f"{reading.kind}  {count}  {title[:TITLE_SHOWN]}"
    )


def _hearing_line(group: dict) -> str:
    items = ",".join(str(item_id) for item_id in group["item_ids"])
    return f"hearing {group['hearing_date']} {group['kind']} items={items}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", required=True, help="municipality slug")
    parser.add_argument("--since", required=True, type=date.fromisoformat, metavar="YYYY-MM-DD",
                        help="read the items of meetings dated this day or later (required)")
    parser.add_argument("--until", type=date.fromisoformat, default=None, metavar="YYYY-MM-DD",
                        help="and dated this day or earlier (default: no later bound)")
    parser.add_argument("--dry-run", action="store_true", help="print the readings; write nothing")
    args = parser.parse_args(argv)

    municipality = query.get_municipality(args.city)
    if municipality is None:
        print(f"no active city with the slug '{args.city}'", file=sys.stderr)
        sys.exit(1)

    rows = hearings.find_readings(municipality["id"], args.since, args.until)
    groups = hearings.group_readings(rows)
    for row in rows:
        print(_item_line(row))
    for group in groups:
        print(_hearing_line(group))
    dated = sum(len(group["item_ids"]) for group in groups)
    print(f"matched={len(rows)} dated={dated} undated={len(rows) - dated} hearings={len(groups)}")
    if args.dry_run:
        return

    report = hearings.refresh_hearings(municipality["id"], args.since, args.until)
    print(f"created={report.created} linked={report.linked}")


if __name__ == "__main__":
    main()
