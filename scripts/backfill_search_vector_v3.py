"""Backfill search_vector for agenda_items after the v3 trigger update.

Run AFTER migration 015 has been applied. Idempotent — safe to re-run
or resume; uses an id cursor so already-touched rows are never re-touched
(the UPDATE WHERE id IN (SELECT ... WHERE id > last_id ...) pattern means
each batch advances the cursor forward — interrupted runs simply restart
from id=0 and re-walk).

Usage:
    venv/bin/python scripts/backfill_search_vector_v3.py [--batch-size 5000] [--sleep 0.1]

On Railway (in-VPC, where pg latency is <1ms instead of ~50ms):
    railway ssh --service docket-web
    python scripts/backfill_search_vector_v3.py --batch-size 5000 --sleep 0.05

The trigger fires on UPDATE — touching `search_vector = search_vector` is
enough to invoke it and recompute from the new function body.

The WHERE clause restricts to rows where v3 data exists OR where the
trigger recompute would differ from the 013 body (i.e., items with
extracted_facts or headline set). Rows with neither are left alone —
their existing tsvectors remain valid under the new function since
headline=NULL and extracted_facts=NULL coalesce to '' in both old and
new functions.
"""

from __future__ import annotations

import argparse
import logging
import time

from docket.db import db

log = logging.getLogger(__name__)


def backfill(batch_size: int = 5000, sleep_seconds: float = 0.1) -> int:
    """Batch-recompute search_vector for items with v3 data. Returns total updated."""
    total = 0
    last_id = 0
    while True:
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agenda_items
                   SET search_vector = search_vector
                 WHERE id IN (
                   SELECT id FROM agenda_items
                    WHERE id > %s
                      AND (extracted_facts IS NOT NULL OR headline IS NOT NULL)
                    ORDER BY id
                    LIMIT %s
                 )
                 RETURNING id
                """,
                [last_id, batch_size],
            )
            updated = cur.fetchall()
        if not updated:
            break
        total += len(updated)
        last_id = max(row[0] for row in updated)
        log.info(
            "backfilled %d rows (cumulative %d, last_id=%d)",
            len(updated),
            total,
            last_id,
        )
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recompute search_vector for agenda_items with v3 data."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="Rows per UPDATE batch (default: 5000)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.1,
        help="Seconds to sleep between batches (default: 0.1; use 0 for local/dev)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    total = backfill(batch_size=args.batch_size, sleep_seconds=args.sleep)
    print(f"backfill complete: {total} rows updated")


if __name__ == "__main__":
    main()
