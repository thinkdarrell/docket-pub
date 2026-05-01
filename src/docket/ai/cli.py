# src/docket/ai/cli.py
"""CLI for the AI pipeline (summaries + scoring).

Examples:
    python -m docket.ai.cli --status
    python -m docket.ai.cli --dry-run --items --limit 5
    python -m docket.ai.cli --items
    python -m docket.ai.cli --meetings --limit 10
    python -m docket.ai.cli --force --meeting-id 5
    python -m docket.ai.cli --items --force-budget
"""

from __future__ import annotations

import argparse
import logging
import sys

from docket.ai.prompts import ITEM_PROMPT_VERSION, MEETING_PROMPT_VERSION
from docket.ai.worker import (
    BudgetExceededError,
    _today_spend,
    claim_items_sql,
    claim_meetings_sql,
    run_once,
)
from docket.config import AI_DAILY_BUDGET_USD, AI_ITEM_DEBOUNCE_MINUTES, AI_MAX_BATCH_SIZE
from docket.db import db


log = logging.getLogger(__name__)


def cmd_status() -> None:
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM agenda_items
                 WHERE (ai_prompt_version IS NULL OR ai_prompt_version < %s)
                   AND created_at < NOW() - (%s || ' minutes')::interval
            """, (ITEM_PROMPT_VERSION, AI_ITEM_DEBOUNCE_MINUTES))
            items_pending = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM meetings m
                 WHERE (
                   ((m.ai_prompt_version IS NULL OR m.ai_prompt_version < %s)
                    AND m.minutes_adopted_at IS NULL
                    AND NOT EXISTS (
                      SELECT 1 FROM agenda_items ai
                       WHERE ai.meeting_id = m.id
                         AND (ai.ai_prompt_version IS NULL OR ai.ai_prompt_version < %s)
                    ))
                   OR (m.minutes_adopted_at IS NOT NULL
                       AND COALESCE(m.ai_metadata->>'phase', '') != 'adopted')
                 )
            """, (MEETING_PROMPT_VERSION, ITEM_PROMPT_VERSION))
            meetings_pending = cur.fetchone()[0]

            cur.execute("""
                SELECT id, started_at, stage, rows_processed, rows_failed, cost_usd
                  FROM ai_runs
                 ORDER BY id DESC
                 LIMIT 5
            """)
            recent_runs = cur.fetchall()

            spent_today = _today_spend(conn)

    print(f"Item prompt version:    {ITEM_PROMPT_VERSION}")
    print(f"Meeting prompt version: {MEETING_PROMPT_VERSION}")
    print(f"Items pending:          {items_pending:,}")
    print(f"Meetings pending:       {meetings_pending:,}")
    print(f"Today's spend:          ${spent_today:.4f} / ${AI_DAILY_BUDGET_USD:.2f}")
    print()
    print("Recent runs:")
    for run in recent_runs:
        rid, started, stage, processed, failed, cost = run
        print(f"  #{rid} {started.isoformat()} {stage:8s} processed={processed:5d} "
              f"failed={failed:3d} cost=${float(cost):.4f}")


def cmd_dry_run(stage: str, limit: int) -> None:
    with db() as conn:
        with conn.cursor() as cur:
            if stage == "items":
                cur.execute(claim_items_sql(),
                            (ITEM_PROMPT_VERSION, AI_ITEM_DEBOUNCE_MINUTES, limit))
                rows = cur.fetchall()
                print(f"Would process {len(rows)} item(s):")
                for r in rows:
                    title = r[2] or ""
                    print(f"  item #{r[0]} (meeting={r[1]}) — {title[:80]}")
            else:
                cur.execute(claim_meetings_sql(),
                            (MEETING_PROMPT_VERSION, ITEM_PROMPT_VERSION, limit))
                rows = cur.fetchall()
                print(f"Would process {len(rows)} meeting(s):")
                for r in rows:
                    print(f"  meeting #{r[0]} {r[1]} {r[2]}  "
                          f"(adopted={r[3] is not None})")
            conn.rollback()


def cmd_force_meeting(meeting_id: int) -> None:
    """Reset a single meeting's prompt version so it'll be re-claimed."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE meetings
                   SET ai_prompt_version = NULL,
                       ai_metadata       = NULL,
                       executive_summary = NULL,
                       ai_generated_at   = NULL
                 WHERE id = %s
            """, (meeting_id,))
            cur.execute("""
                UPDATE agenda_items
                   SET ai_prompt_version       = NULL,
                       ai_metadata             = NULL,
                       summary                 = NULL,
                       significance_score      = NULL,
                       consent_placement_score = NULL,
                       ai_generated_at         = NULL
                 WHERE meeting_id = %s
            """, (meeting_id,))
        conn.commit()
    print(f"Reset AI state for meeting #{meeting_id} and its items.")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI pipeline (summaries + scoring)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true")
    group.add_argument("--items", action="store_true", help="Process pending items")
    group.add_argument("--meetings", action="store_true", help="Process pending meetings")
    parser.add_argument("--limit", type=int, default=AI_MAX_BATCH_SIZE)
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be processed without calling AI")
    parser.add_argument("--force", action="store_true",
                        help="Bypass version check (with --meeting-id)")
    parser.add_argument("--meeting-id", type=int)
    parser.add_argument("--force-budget", action="store_true",
                        help="Override daily budget cap")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.status:
        cmd_status()
        return

    stage = "items" if args.items else "meetings"

    if args.force and args.meeting_id is None:
        sys.exit("--force requires --meeting-id")
    if args.meeting_id is not None:
        if not args.force:
            sys.exit("--meeting-id requires --force")
        cmd_force_meeting(args.meeting_id)
        return

    if args.dry_run:
        cmd_dry_run(stage, args.limit)
        return

    try:
        summary = run_once(stage=stage, limit=args.limit,
                           notes=f"cli_{stage}", force_budget=args.force_budget)
    except BudgetExceededError as e:
        sys.exit(str(e))

    print(f"Processed {summary.rows_processed} {stage}, "
          f"{summary.rows_failed} failed, cost ${summary.cost_usd:.4f}")


if __name__ == "__main__":
    main()
