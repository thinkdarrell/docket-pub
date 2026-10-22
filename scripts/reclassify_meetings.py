"""Reclassify one city's meetings through the evidence ladder, in one statement.

Resolves every non-hidden row of the city (admin lock, calendar match,
schedule rule, title; ``docket.services.meeting_types``), prints the
transition table ``(old meeting_type, old session_kind) -> (new meeting_type,
new session_kind, type_source)`` with counts, lists one per line the rows
the schedule rule classifies that predate 2026-01-01 so the operator reads
them before the write, and then writes the changed rows with one
``UPDATE ... FROM (VALUES ...)`` scoped to unlocked rows (decision 0026),
followed by one statement clearing the AI meeting summaries of the rows
whose body left ``council``, which the worker regenerates. A second dry run
after the write prints every count on the diagonal.

Dry run first, one city at a time:
    python scripts/reclassify_meetings.py --city birmingham --dry-run
    python scripts/reclassify_meetings.py --city birmingham

Against production the operator sets DATABASE_URL to DATABASE_PUBLIC_URL
(plans/active/meeting-types-name-the-body.md, M4).
"""

import argparse
import logging

from docket.services.meeting_types import reclassify_city

logging.basicConfig(level=logging.WARNING, format="%(message)s")

CLEAR_SQL = (
    "UPDATE meetings SET executive_summary = NULL, executive_summary_voice = NULL, "
    "ai_prompt_version = NULL, ai_generated_at = NULL "
    "WHERE id = ANY(<ids whose meeting_type left council>) AND executive_summary IS NOT NULL"
)


def print_report(report, *, dry_run: bool) -> None:
    print(f"{'old type':<10} {'old kind':<15} -> {'new type':<10} {'new kind':<15} {'source':<14} {'rows':>6}")
    for (ot, ok, nt, nk, src), n in sorted(report.transitions.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"{ot:<10} {ok:<15} -> {nt:<10} {nk:<15} {src:<14} {n:>6}")
    print(f"rows: {sum(report.transitions.values())}")
    if report.rule_rows_before_2026:
        print("schedule-rule rows before 2026-01-01 (id, date, weekday, title, items):")
        for r in report.rule_rows_before_2026:
            print(f"  {r['id']}  {r['meeting_date']}  {r['weekday']}  {r['title']}  {r['item_count']} items")
    if dry_run:
        print("dry run: 0 rows written")
    else:
        print(f"written: {report.written} rows in one statement")
        print(CLEAR_SQL)
        print(f"summaries cleared: {report.summaries_cleared}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", required=True, help="municipality slug")
    parser.add_argument("--dry-run", action="store_true", help="print the table; write nothing")
    args = parser.parse_args()

    report = reclassify_city(args.city, dry_run=args.dry_run)
    print_report(report, dry_run=args.dry_run)
