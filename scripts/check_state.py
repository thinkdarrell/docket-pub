"""One-shot state snapshot for the docket.pub v3 pipeline.

Run with the public DB URL exported, or it falls through to the
local DATABASE_URL from .env. Prints ai_batches state, processing_status
counts, and 10 random v3 headlines.

Usage:
    export DATABASE_URL=$(railway variables --service docket-web --kv \\
        | grep '^DATABASE_PUBLIC_URL=' | cut -d= -f2-)
    venv/bin/python scripts/check_state.py

Or from the project root with the env preset:
    DATABASE_URL=$DATABASE_PUBLIC_URL venv/bin/python scripts/check_state.py
"""

from __future__ import annotations

import os
import sys

import psycopg2


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit(
            "DATABASE_URL not set. Export it via:\n"
            "  export DATABASE_URL=$(railway variables --service docket-web "
            "--kv | grep '^DATABASE_PUBLIC_URL=' | cut -d= -f2-)"
        )
    cur = psycopg2.connect(url).cursor()

    print("=== ai_batches (most recent 3) ===")
    cur.execute(
        "SELECT id, anthropic_batch_id, stage, status, "
        "item_count, ingested_at FROM ai_batches ORDER BY id DESC LIMIT 3"
    )
    for row in cur.fetchall():
        print(" ", row)
    print()

    print("=== agenda_items status counts ===")
    cur.execute(
        "SELECT processing_status::text, COUNT(*) "
        "FROM agenda_items GROUP BY 1 ORDER BY 2 DESC"
    )
    for row in cur.fetchall():
        print(" ", row)
    print()

    print("=== 10 random v3 headlines ===")
    cur.execute(
        "SELECT ai.headline, ai.why_it_matters "
        "FROM agenda_items ai "
        "WHERE ai.processing_status = 'completed' "
        "  AND ai.ai_rewrite_version = 3 "
        "  AND ai.headline IS NOT NULL "
        "ORDER BY RANDOM() LIMIT 10"
    )
    for headline, why in cur.fetchall():
        print(f"  {headline}")
        print(f"    → {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
