"""Write Granicus chapter ids onto agenda items that were cued without one.

An agenda item ingested from the agenda PDF, before the meeting was recorded,
keeps an id such as ``event-2715-1``. The Granicus player can only jump to a
chapter (``&meta_id=<chapter id>``), so a video link for such an item opens
the start of the recording. The ingest run now writes the chapter id together
with the timestamp, but it fetches a meeting's player page only while a
numbered item lacks its timestamp, so the meetings cued before that change
are never fetched again. This script corrects them: it runs
``docket.services.ingest.correct_chapter_ids`` over the city's clip meetings
that have a numbered item with a timestamp and an id that is not all digits,
newest first, at most ``--limit`` of them (default 50).

It requests one Granicus player page per listed meeting, with the adapter's
polite delay after each, and writes one UPDATE per meeting. It prints one
line per meeting and then the totals; an id it had to leave alone (an item
number that repeats in the meeting, or a chapter id another row holds) is a
WARNING line on stderr. A second run after the write lists only meetings
that hold such ids, or none.

Dry run first, one city at a time (the dry run makes the same requests and
writes nothing):
    python scripts/correct_agenda_chapter_ids.py --city birmingham --dry-run
    python scripts/correct_agenda_chapter_ids.py --city birmingham

Against production the operator sets DATABASE_URL to DATABASE_PUBLIC_URL.
Exits 1 for an unknown city or when a meeting's player page could not be read.
"""

import argparse
import logging
import sys

from docket.services.ingest import correct_chapter_ids

logging.basicConfig(level=logging.WARNING, format="%(message)s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", required=True, help="municipality slug")
    parser.add_argument("--limit", type=int, default=50, help="visit at most this many meetings (default 50)")
    parser.add_argument("--dry-run", action="store_true", help="print what would change; write nothing")
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be at least 1")

    try:
        results = correct_chapter_ids(args.city, limit=args.limit, dry_run=args.dry_run)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    verb = "would change" if args.dry_run else "changed"
    for r in results:
        head = f"meeting {r['meeting_id']} clip {r['external_id']} {r['meeting_date']}"
        if r["error"]:
            print(f"{head}: failed ({r['error']})")
        else:
            print(f"{head}: {r['changed']} rows {verb}")
    print(f"{len(results)} meetings, {sum(r['changed'] for r in results)} rows")
    return 1 if any(r["error"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
