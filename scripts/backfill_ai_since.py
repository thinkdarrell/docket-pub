"""One-shot AI backfill restricted to meetings on or after a cutoff date.

Mirrors the existing AI worker (docket.ai.worker._process_items / _process_meetings)
but uses a date-filtered claim that joins agenda_items → meetings on meeting_date.
Items are processed newest-first so the most recent (and most user-visible)
content surfaces first.

Usage:
    python scripts/backfill_ai_since.py --items --since 2024-11-04
    python scripts/backfill_ai_since.py --meetings --since 2024-11-04
    python scripts/backfill_ai_since.py --items --since 2024-11-04 --dry-run
    python scripts/backfill_ai_since.py --items --since 2024-11-04 --max-cost 15

The cron worker is unaffected — this script doesn't touch claim_items_sql.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from docket.ai.client import AIClient
from docket.ai.contexts import AgendaItemContext, MeetingContext
from docket.ai.exceptions import (
    AIFatalError,
    AIPermanentRowError,
    AIRateLimited,
    AITransientError,
)
from docket.ai.pricing import PRICING, calculate_cost_usd, usage_add
from docket.ai.prompts import ITEM_PROMPT_VERSION, MEETING_PROMPT_VERSION
from docket.ai.worker import (
    AI_DAILY_BUDGET_USD,
    AI_MAX_BATCH_SIZE,
    RunSummary,
    _close_run,
    _make_client,
    _open_run,
    mark_item_failed,
    mark_meeting_empty,
    mark_meeting_failed,
    write_item_result,
    write_meeting_result,
)
from docket.config import AI_ITEM_DEBOUNCE_MINUTES
from docket.db import db

log = logging.getLogger(__name__)


def claim_items_in_range_sql() -> str:
    """Like claim_items_sql but joined to meetings.meeting_date.

    Args (in order): (current_item_version, debounce_minutes, since_date, limit)
    """
    return """
        SELECT ai.id, ai.meeting_id, ai.title, ai.description, ai.sponsor,
               ai.dollars_amount, ai.topic, ai.is_consent
        FROM agenda_items ai
        JOIN meetings m ON m.id = ai.meeting_id
        WHERE (ai.ai_prompt_version IS NULL OR ai.ai_prompt_version < %s)
          AND ai.created_at < NOW() - (%s || ' minutes')::interval
          AND m.meeting_date >= %s
        ORDER BY m.meeting_date DESC, ai.id
        FOR UPDATE OF ai SKIP LOCKED
        LIMIT %s
    """


def claim_meetings_in_range_sql() -> str:
    """Like claim_meetings_sql but with a meeting_date floor.

    Args (in order): (meeting_version, item_version, since_date, limit)
    """
    return """
        SELECT m.id, m.meeting_type, m.meeting_date, m.minutes_adopted_at, m.ai_metadata
        FROM meetings m
        WHERE m.meeting_date >= %s
          AND (
            ((m.ai_prompt_version IS NULL OR m.ai_prompt_version < %s)
             AND m.minutes_adopted_at IS NULL
             AND NOT EXISTS (
               SELECT 1 FROM agenda_items ai
               WHERE ai.meeting_id = m.id
                 AND (ai.ai_prompt_version IS NULL OR ai.ai_prompt_version < %s)
             ))
            OR
            (m.minutes_adopted_at IS NOT NULL
             AND COALESCE(m.ai_metadata->>'phase', '') != 'adopted')
          )
        ORDER BY m.meeting_date DESC, m.id
        FOR UPDATE OF m SKIP LOCKED
        LIMIT %s
    """


def _count_pending(conn, since: date) -> tuple[int, int]:
    """Returns (pending_items, pending_meetings) within the date window."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM agenda_items ai
            JOIN meetings m ON m.id = ai.meeting_id
            WHERE (ai.ai_prompt_version IS NULL OR ai.ai_prompt_version < %s)
              AND m.meeting_date >= %s
        """, (ITEM_PROMPT_VERSION, since))
        items_pending = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM meetings m
            WHERE m.meeting_date >= %s
              AND (
                ((m.ai_prompt_version IS NULL OR m.ai_prompt_version < %s)
                 AND m.minutes_adopted_at IS NULL
                 AND NOT EXISTS (
                   SELECT 1 FROM agenda_items ai
                   WHERE ai.meeting_id = m.id
                     AND (ai.ai_prompt_version IS NULL OR ai.ai_prompt_version < %s)
                 ))
                OR
                (m.minutes_adopted_at IS NOT NULL
                 AND COALESCE(m.ai_metadata->>'phase', '') != 'adopted')
              )
        """, (since, MEETING_PROMPT_VERSION, ITEM_PROMPT_VERSION))
        meetings_pending = cur.fetchone()[0]
    return items_pending, meetings_pending


def _process_items_batch(conn, client: AIClient, since: date,
                         limit: int, summary: RunSummary) -> int:
    """Process one batch. Returns rows actually claimed."""
    with conn.cursor() as cur:
        cur.execute(
            claim_items_in_range_sql(),
            (ITEM_PROMPT_VERSION, AI_ITEM_DEBOUNCE_MINUTES, since, limit),
        )
        rows = cur.fetchall()

    columns = ["id", "meeting_id", "title", "description", "sponsor",
               "dollars_amount", "topic", "is_consent"]

    for row in rows:
        row_dict = dict(zip(columns, row))
        ctx = AgendaItemContext.from_row(row_dict)
        try:
            result, usage = client.summarize_item(ctx)
            write_item_result(conn, row_dict["id"], result, model=client.item_model)
            summary.usage = usage_add(summary.usage, usage)
            summary.cost_usd += calculate_cost_usd(client.item_model, usage)
            summary.rows_processed += 1
            conn.commit()
        except AIRateLimited:
            log.warning("Rate limited; ending batch (will resume on next iteration)")
            conn.rollback()
            break
        except AITransientError as e:
            log.warning("Transient error on item %s: %s", row_dict["id"], e)
            conn.rollback()
            continue
        except AIPermanentRowError as e:
            log.error("Permanent failure on item %s: %s", row_dict["id"], e)
            conn.rollback()
            mark_item_failed(conn, row_dict["id"], reason=str(e)[:200])
            summary.rows_failed += 1
            conn.commit()
        except AIFatalError:
            conn.rollback()
            raise

    return len(rows)


def _process_meetings_batch(conn, client: AIClient, since: date,
                            limit: int, summary: RunSummary) -> int:
    """Process one batch of meetings. Returns rows actually claimed."""
    with conn.cursor() as cur:
        cur.execute(
            claim_meetings_in_range_sql(),
            (since, MEETING_PROMPT_VERSION, ITEM_PROMPT_VERSION, limit),
        )
        rows = cur.fetchall()

    for row in rows:
        meeting_id, meeting_type, meeting_date, minutes_adopted_at, ai_metadata = row

        # Build the per-meeting item context the same way worker._process_meetings does.
        with conn.cursor() as cur:
            cur.execute("""
                SELECT summary, significance_score, topic, title
                  FROM agenda_items
                 WHERE meeting_id = %s
                   AND COALESCE(ai_metadata->>'is_substantive', '') = 'true'
                   AND summary IS NOT NULL
                 ORDER BY significance_score DESC NULLS LAST, id
            """, (meeting_id,))
            item_rows = [
                {"summary": r[0], "significance_score": r[1], "topic": r[2], "title": r[3]}
                for r in cur.fetchall()
            ]

        if not item_rows:
            mark_meeting_empty(conn, meeting_id)
            conn.commit()
            summary.rows_processed += 1
            continue

        phase = "adopted" if minutes_adopted_at else "provisional"
        ctx = MeetingContext.from_meeting_items(
            meeting_id=meeting_id,
            meeting_type=meeting_type,
            meeting_date=meeting_date,
            phase=phase,
            rows=item_rows,
        )
        try:
            result, usage = client.summarize_meeting(ctx)
            write_meeting_result(conn, meeting_id, result, model=client.meeting_model)
            summary.usage = usage_add(summary.usage, usage)
            summary.cost_usd += calculate_cost_usd(client.meeting_model, usage)
            summary.rows_processed += 1
            conn.commit()
        except AIRateLimited:
            log.warning("Rate limited; ending batch")
            conn.rollback()
            break
        except AITransientError as e:
            log.warning("Transient error on meeting %s: %s", meeting_id, e)
            conn.rollback()
            continue
        except AIPermanentRowError as e:
            log.error("Permanent failure on meeting %s: %s", meeting_id, e)
            conn.rollback()
            mark_meeting_failed(conn, meeting_id, reason=str(e)[:200])
            summary.rows_failed += 1
            conn.commit()
        except AIFatalError:
            conn.rollback()
            raise

    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-shot AI backfill scoped to a date window",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--items", action="store_true", help="Process pending items")
    group.add_argument("--meetings", action="store_true", help="Process pending meetings")
    parser.add_argument(
        "--since", required=True,
        help="Cutoff date YYYY-MM-DD; only rows with meeting_date >= this date are processed",
    )
    parser.add_argument(
        "--max-cost", type=float, default=20.0,
        help="Stop after this many USD have been spent on this run (safety cap)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=AI_MAX_BATCH_SIZE,
        help="Items per batch; defaults to AI_MAX_BATCH_SIZE",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be processed without calling the AI")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        since = date.fromisoformat(args.since)
    except ValueError:
        sys.exit(f"--since must be YYYY-MM-DD, got: {args.since!r}")

    stage = "items" if args.items else "meetings"

    with db() as conn:
        items_pending, meetings_pending = _count_pending(conn, since)
        print(f"Window: meeting_date >= {since}")
        print(f"  Items pending in window:    {items_pending:,}")
        print(f"  Meetings pending in window: {meetings_pending:,}")

    if args.dry_run:
        print("(dry-run — no AI calls made)")
        return

    target = items_pending if stage == "items" else meetings_pending
    if target == 0:
        print(f"Nothing pending for stage={stage} in this window. Exiting.")
        return

    print(f"Processing stage={stage}, max-cost=${args.max_cost:.2f}, "
          f"batch={args.batch_size}")

    client = _make_client()
    model = client.item_model if stage == "items" else client.meeting_model
    if model not in PRICING:
        sys.exit(f"Model {model!r} has no PRICING entry — refusing to run")

    summary = RunSummary(stage=stage)

    with db() as conn:
        run_id = _open_run(conn, stage, model, notes=f"backfill_18mo_{since.isoformat()}")
        conn.commit()

        try:
            while True:
                if summary.cost_usd >= args.max_cost:
                    print(f"Reached --max-cost ${args.max_cost:.2f}; stopping. "
                          f"Spent so far: ${summary.cost_usd:.4f}")
                    break

                if stage == "items":
                    claimed = _process_items_batch(
                        conn, client, since, args.batch_size, summary,
                    )
                else:
                    claimed = _process_meetings_batch(
                        conn, client, since, args.batch_size, summary,
                    )

                print(f"  batch claimed={claimed} processed_so_far="
                      f"{summary.rows_processed} cost=${summary.cost_usd:.4f}")

                if claimed == 0:
                    print("No more rows to process in this window.")
                    break
        finally:
            _close_run(conn, run_id, summary)
            conn.commit()

    print()
    print(f"Done. Processed {summary.rows_processed} {stage}, "
          f"{summary.rows_failed} failed, spent ${summary.cost_usd:.4f}.")


if __name__ == "__main__":
    main()
