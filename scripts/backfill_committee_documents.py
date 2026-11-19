"""Fill a city's committee documents, once: list, fetch, read, attach.

Runs the same four steps as the daily worker task ``committee_documents``
(``docket.services.committee_documents``), with no limit on the documents
read unless ``--limit`` is given: every PDF the city's committee pages list
is fetched (one request a second), read, and attached to its committee
meeting, and minutes for a meeting with no row create one. It then prints
what the tables hold: documents by status and kind, where the dates came
from, items by category, what was attached, the meetings created, and a
table per committee of meetings dated 2026-01-01 or later.

Dry run first:
    python scripts/backfill_committee_documents.py --city birmingham --dry-run
    python scripts/backfill_committee_documents.py --city birmingham

With ``--dry-run`` everything is fetched and read inside one transaction
that is rolled back, so the output is what a real run would do and nothing
is written. A second dry run after a real run reports nothing new to read,
attach or create. On a database that migration 045 has not reached, the dry
run makes the two tables inside its own transaction; until it ends, writes
to ``meetings`` and ``municipalities`` wait, so run it while no worker job
is due (``python -m docket.worker.scheduler --list`` prints the schedule).

Against production the operator sets DATABASE_URL to DATABASE_PUBLIC_URL
(``docs/specs/operations.md``). Plan `committee-documents`, M6.
"""

import argparse
import importlib
import logging
import sys
from datetime import date

from docket.services import committee_documents

logging.basicConfig(level=logging.WARNING, format="%(message)s")


def print_report(report) -> None:
    if report.tables_created:
        print("the tables of migration 045 are absent: made inside this dry run's transaction")
    refresh, attach = report.refresh, report.refresh.attach
    print(f"new listings {refresh.new_listings}, read {refresh.read}, read again {refresh.reparsed}")

    print("\ndocuments by status and kind:")
    for status, kind, n in report.documents:
        print(f"  {status:<14} {kind or '-':<10} {n}")
    sources = report.date_sources
    print(f"date from the header {sources['header']}, from the heading {sources['heading']}, "
          f"no date {sources['none']}; listing disagrees {report.listing_disagrees}")

    print("\nitems by category:")
    total = sum(n for _, n in report.items_by_category)
    for category, n in report.items_by_category:
        print(f"  {category:<24} {n}")
    print(f"  {'total':<24} {total}")

    print(f"\nattach: matched {attach.matched}, created {attach.created}, ambiguous {attach.ambiguous}, "
          f"unattached agendas {attach.unattached_agendas}, unattached minutes {attach.unattached_minutes}")
    if attach.crowded_days:
        print("crowded days (a second Granicus meeting typed council on a created meeting's day): "
              + ", ".join(d.isoformat() for d in attach.crowded_days))

    label = "meetings it would create" if report.dry_run else "meetings created"
    print(f"\n{label}: {len(report.created_meetings)}")
    for meeting in report.created_meetings:
        print(f"  {meeting['meeting_date']}  {meeting['external_id']}  {meeting['title']}")

    print("\nmeetings dated 2026-01-01 or later, per committee:")
    print(f"{'':<64} {'meetings':>8} {'agenda':>7} {'minutes':>8} {'items':>6} {'doc, no video':>14} "
          f"{'video, no doc':>14}")
    for row in report.committees:
        print(f"{row['committee']:<64} {row['meetings']:>8} {row['with_agenda']:>7} {row['with_minutes']:>8} "
              f"{row['with_items']:>6} {row['document_no_video']:>14} {row['video_no_document']:>14}")

    if report.dry_run:
        print("\ndry run: nothing written")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", required=True, help="municipality slug")
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch and read, print what would be done, and roll everything back")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="read at most N documents (default: every document not yet read)")
    args = parser.parse_args(argv)

    schema_sql = importlib.import_module("docket.migrations.045_committee_documents").SQL_UP
    try:
        report = committee_documents.backfill(
            args.city, date.today(), limit=args.limit, dry_run=args.dry_run, schema_sql=schema_sql
        )
    except ValueError as error:
        print(error, file=sys.stderr)
        sys.exit(1)
    print_report(report)


if __name__ == "__main__":
    main()
