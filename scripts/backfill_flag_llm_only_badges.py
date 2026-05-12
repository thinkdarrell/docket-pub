"""One-shot: reclassify existing LLM-only policy badges to status='flagged'.

Refactor #2 — companion to the new writer in
``src/docket/ai/badges_policy.py``. The writer now classifies LLM-only
suggestions as ``'flagged'`` at INSERT time; this script catches up the
rows that landed under the old auto-apply rules. After running, every
``kind='policy' AND source='llm' AND status='applied'`` row lives in
the admin review queue (``/admin/badge-review``).

Idempotent: re-running is a no-op once every row has been moved.

Run from project root::

    venv/bin/python scripts/backfill_flag_llm_only_badges.py

Or in-VPC on Railway (faster — many small UPDATEs over the public proxy
are slow at ~50ms each)::

    railway ssh --service worker "cd /app && python scripts/backfill_flag_llm_only_badges.py"

Reads ``DATABASE_URL`` from the environment (resolved via
``docket.config``) so the same module works locally and in-container.
"""

from __future__ import annotations

import sys

from docket.db import db


def run_backfill() -> dict:
    """Reclassify and audit. Returns ``{'flagged_count': int}``.

    Caller can introspect the count to decide whether to refresh
    ``mv_badge_volume_monthly`` (see plan E2 step 4). Single transaction —
    either every row flips together with its audit row, or nothing does.
    """
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source, status, COUNT(*)
                  FROM agenda_item_badges
                 WHERE kind = 'policy'
                 GROUP BY source, status
                 ORDER BY source, status
                """
            )
            pre = list(cur.fetchall())

            cur.execute(
                """
                UPDATE agenda_item_badges
                   SET status = 'flagged'
                 WHERE kind = 'policy'
                   AND source = 'llm'
                   AND status = 'applied'
             RETURNING id, agenda_item_id, badge_slug
                """
            )
            flipped = cur.fetchall()
            n_flagged = len(flipped)

            if flipped:
                cur.executemany(
                    """
                    INSERT INTO agenda_item_badges_audit
                      (agenda_item_id, badge_slug, action, actor, actor_role, reason)
                    VALUES (%s, %s, 'flagged',
                            'backfill_flag_llm_only_badges.py',
                            'cron',
                            'Refactor #2 backfill: LLM-only suggestions moved to review queue')
                    """,
                    [(row[1], row[2]) for row in flipped],
                )

    return {"flagged_count": n_flagged, "pre_breakdown": pre}


def main() -> int:
    summary = run_backfill()
    print("Flagged", summary["flagged_count"],
          "previously-applied LLM-only policy badges.")
    print("Pre-backfill breakdown (policy badges):")
    for row in summary["pre_breakdown"]:
        print(" ", row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
