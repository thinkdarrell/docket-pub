"""Fix minutes-adoption dates the pre-2026-10-02 parser took from the wrong line.

Re-derives, for each meeting with a recorded adoption date, the agenda
lines that name it; a date no line supports is replaced with the earliest
line whose meeting recorded a passed vote. Idempotent.

Dry run first:
    python scripts/correct_adoption_dates.py --dry-run
    python scripts/correct_adoption_dates.py
"""

import argparse
import logging

from docket.db import db
from docket.services.maintenance import correct_adoption_dates

logging.basicConfig(level=logging.INFO, format="%(message)s")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", default="birmingham", help="municipality slug")
    parser.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    args = parser.parse_args()

    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = %s", (args.city,))
        row = cur.fetchone()
    if row is None:
        raise SystemExit(f"Unknown city slug: {args.city}")

    fixes = correct_adoption_dates(row[0], dry_run=args.dry_run)
    verb = "would correct" if args.dry_run else "corrected"
    print(f"{verb} {len(fixes)} meetings")
    for meeting_id, old, new in fixes:
        print(f"  meeting {meeting_id}: {old} -> {new}")
