"""Backfill votes.resolution_number from raw_text.

Idempotent: skips rows where resolution_number is already populated.
Idiomatic batched UPDATE — does not stream per-row updates against Railway.

Usage:
    venv/bin/python scripts/backfill_vote_resolution_numbers.py [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import logging
import sys

from docket.analysis.vote_resolution_extractor import extract_resolution_number
from docket.db import db, db_cursor

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would change, don't write")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap the number of rows processed")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    sql = """
        SELECT id, raw_text FROM votes
        WHERE resolution_number IS NULL
          AND raw_text IS NOT NULL
          AND raw_text <> ''
    """
    if args.limit:
        sql += f" LIMIT {int(args.limit)}"

    updates: list[tuple[str, int]] = []
    with db_cursor() as cur:
        cur.execute(sql)
        for row in cur.fetchall():
            res_num = extract_resolution_number(row["raw_text"])
            if res_num:
                updates.append((res_num, row["id"]))

    logger.info("Extracted %d resolution numbers across %d candidate rows.",
                len(updates), cur.rowcount if cur.rowcount else 0)

    if args.dry_run:
        for res_num, vote_id in updates[:20]:
            logger.info("dry-run: vote %d -> %s", vote_id, res_num)
        if len(updates) > 20:
            logger.info("(... %d more)", len(updates) - 20)
        return 0

    if not updates:
        logger.info("Nothing to update.")
        return 0

    # Batched UPDATE via VALUES list (single round trip).
    with db() as conn:
        with conn.cursor() as cur:
            args_str = ",".join(
                cur.mogrify("(%s::text, %s::int)", (n, vid)).decode()
                for n, vid in updates
            )
            cur.execute(
                f"""UPDATE votes
                    SET resolution_number = v.num
                    FROM (VALUES {args_str}) AS v(num, id)
                    WHERE votes.id = v.id"""
            )
        conn.commit()
    logger.info("Updated %d rows.", len(updates))
    return 0


if __name__ == "__main__":
    sys.exit(main())
