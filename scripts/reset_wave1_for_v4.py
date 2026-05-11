"""Reset Wave 1 items to processing_status='extracted' so they can be
re-processed by Stage 2 with the new prompt v4.

Scope: every item whose ``backfill_session_id`` matches the Wave 1
Stage 1 session UUID (=cda052ba-c779-4023-9bb3-653573c5cb22). That's
the 536 items that successfully passed Stage 1. The 15 items that
failed Stage 1 validation are left alone — those need a Stage 1 prompt
fix, not a Stage 2 re-run.

Idempotent: re-running is harmless. Items already at 'extracted' with
NULL session_id stay there; the UPDATE matches zero rows.

Run from the project root:
    venv/bin/python scripts/reset_wave1_for_v4.py
"""

from __future__ import annotations

import os
import subprocess
import sys

import psycopg2

WAVE1_SESSION = "cda052ba-c779-4023-9bb3-653573c5cb22"


def _resolve_db_url() -> str:
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url
    out = subprocess.check_output(
        ["railway", "variables", "--service", "docket-web", "--kv"], text=True
    )
    for line in out.splitlines():
        if line.startswith("DATABASE_PUBLIC_URL="):
            return line.split("=", 1)[1]
    sys.exit("DATABASE_URL not resolvable")


def main() -> int:
    conn = psycopg2.connect(_resolve_db_url())
    cur = conn.cursor()

    # 1. Count what we're about to reset.
    cur.execute(
        """
        SELECT processing_status::text, COUNT(*)
          FROM agenda_items
         WHERE backfill_session_id = %s::uuid
         GROUP BY processing_status::text
         ORDER BY 2 DESC
        """,
        [WAVE1_SESSION],
    )
    rows = cur.fetchall()
    if not rows:
        print(f"No items found with backfill_session_id={WAVE1_SESSION}; nothing to reset.")
        return 0
    print("Pre-reset breakdown:")
    for status, n in rows:
        print(f"  {status:25s} {n}")

    # 2. Reset items (Stage 1 facts stay; Stage 2 outputs cleared).
    cur.execute(
        """
        UPDATE agenda_items
           SET processing_status     = 'extracted'::processing_status_enum,
               headline              = NULL,
               why_it_matters        = NULL,
               ai_rewrite_version    = NULL,
               ai_confidence         = NULL,
               score_overrides       = NULL,
               significance_score    = NULL,
               consent_placement_score = NULL,
               backfill_session_id   = NULL,
               last_error_at         = NULL,
               last_error_message    = NULL
         WHERE backfill_session_id = %s::uuid
           AND processing_status IN ('completed',
                                     'cross_stage_conflict',
                                     'failed_permanent')
        """,
        [WAVE1_SESSION],
    )
    items_reset = cur.rowcount
    print(f"\nReset {items_reset} items to processing_status='extracted'.")

    # 3. Delete badges for those items (they'll be re-computed).
    cur.execute(
        """
        DELETE FROM agenda_item_badges
         WHERE agenda_item_id IN (
            SELECT id FROM agenda_items
             WHERE backfill_session_id IS NULL
               AND extracted_facts IS NOT NULL
               AND ai_rewrite_version IS NULL
               AND processing_status = 'extracted'
         )
        """
    )
    badges_deleted = cur.rowcount
    print(f"Deleted {badges_deleted} badge rows (will recompute via Stage 2 + on-write).")

    conn.commit()
    print("\nReady to re-submit Wave 1 Stage 2 with prompt v4.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
