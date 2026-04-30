"""CLI for backfilling enrichment data on existing agenda items.

Usage:
    python -m docket.enrichment.cli --municipality vestavia_hills
    python -m docket.enrichment.cli --all
"""

from __future__ import annotations

import argparse
import logging
import sys

from docket.db import db_cursor
from docket.services.enrichment import backfill_municipality


def main():
    parser = argparse.ArgumentParser(description="Backfill enrichment for agenda items")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--municipality", type=str, help="Municipality slug to backfill")
    group.add_argument("--all", action="store_true", help="Backfill all municipalities")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.all:
        with db_cursor() as cur:
            cur.execute("SELECT slug FROM municipalities WHERE active = TRUE ORDER BY slug")
            slugs = [row["slug"] for row in cur.fetchall()]
    else:
        slugs = [args.municipality]

    total_processed = 0
    total_enriched = 0

    for slug in slugs:
        print(f"Backfilling {slug}...")
        result = backfill_municipality(slug)
        print(f"  {result.items_processed} items processed, {result.items_enriched} enriched with dollars")
        if result.errors:
            for err in result.errors[:5]:
                print(f"  ERROR: {err}")
        total_processed += result.items_processed
        total_enriched += result.items_enriched

    print(f"\nTotal: {total_processed} items processed, {total_enriched} enriched")


if __name__ == "__main__":
    main()
