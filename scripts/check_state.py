"""One-shot state snapshot for the docket.pub v3 pipeline.

Resolves the Railway public DB URL automatically by shelling out to the
``railway`` CLI — no env-var dance required. Prints ai_batches state,
processing_status counts, and 10 random v3 headlines.

Usage:
    venv/bin/python scripts/check_state.py

If DATABASE_URL is already set in the environment, it's used as-is
(useful for pointing at a local DB).
"""

from __future__ import annotations

import os
import subprocess
import sys

import psycopg2


def _resolve_database_url() -> str | None:
    """Return DATABASE_URL from env, or shell out to railway CLI for prod."""
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url
    try:
        out = subprocess.check_output(
            ["railway", "variables", "--service", "docket-web", "--kv"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    for line in out.splitlines():
        if line.startswith("DATABASE_PUBLIC_URL="):
            return line.split("=", 1)[1]
    return None


def main() -> int:
    url = _resolve_database_url()
    if not url:
        sys.exit(
            "Could not resolve DATABASE_URL.\n"
            "Either set it manually, or check that `railway` CLI is installed "
            "and authenticated (try: railway whoami)."
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
