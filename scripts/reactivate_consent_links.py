"""Restore consent-vote links hidden by the pre-2026-10-02 strict re-parse.

The old rule hid every consent link it could not confirm from the minutes'
enumerated list; the current rule hides one only when the minutes record a
separate vote on the item. This brings back the links the current rule
would have left alone, on meetings whose minutes are adopted. Idempotent.

Dry run first:
    python scripts/reactivate_consent_links.py --dry-run
    python scripts/reactivate_consent_links.py
"""

import argparse
import logging

from docket.db import db
from docket.services.maintenance import reactivate_consent_links_without_pull_evidence

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

    result = reactivate_consent_links_without_pull_evidence(row[0], dry_run=args.dry_run)
    total = sum(n for _, n in result)
    verb = "would restore" if args.dry_run else "restored"
    print(f"{verb} {total} links on {len(result)} meetings")
    for meeting_id, n in result:
        print(f"  meeting {meeting_id}: {n}")
