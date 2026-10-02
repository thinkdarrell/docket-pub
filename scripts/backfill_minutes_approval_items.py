"""Restore minutes-approval agenda lines on already-scraped meetings, run the
adoption sweep so the meetings they name flip to adopted, then finish
promoting vote links on any adopted meeting still marked provisional.

Safe to re-run: each step skips what is already done, so an interrupted run
is resumed by running it again.

Run inside the Railway container (in-VPC), dry run first:
    python scripts/backfill_minutes_approval_items.py --dry-run
    python scripts/backfill_minutes_approval_items.py
"""

import argparse
import logging
from datetime import date

from docket.db import db
from docket.services.maintenance import (
    backfill_minutes_approval_items,
    reparse_adopted_with_provisional_links,
)
from docket.services.minutes_adoption import sweep_adoptions

logging.basicConfig(level=logging.INFO, format="%(message)s")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", default="birmingham", help="municipality slug")
    parser.add_argument("--since", type=date.fromisoformat, default=date(2026, 5, 1),
                        help="earliest meeting date to re-read (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be inserted; write nothing, skip the sweep")
    args = parser.parse_args()

    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = %s", (args.city,))
        row = cur.fetchone()
    if row is None:
        raise SystemExit(f"Unknown city slug: {args.city}")
    municipality_id = row[0]

    added = backfill_minutes_approval_items(
        municipality_id, since=args.since, dry_run=args.dry_run
    )
    verb = "Would insert" if args.dry_run else "Inserted"
    print(f"\n{verb} {len(added)} approval item(s):")
    for meeting_id, line in added:
        print(f"  meeting {meeting_id}: {line}")

    if not args.dry_run:
        flipped = sweep_adoptions(municipality_id)
        print(f"\nAdoption sweep flipped {len(flipped)} meeting(s): {sorted(flipped)}")
        finished = reparse_adopted_with_provisional_links(municipality_id)
        print(f"Finished promotion on {len(finished)} adopted meeting(s) that still had provisional links")
