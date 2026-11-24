"""The admin's two writes from the errors queue.

The statements behind ``POST /admin/errors/<id>/retry`` and
``POST /admin/errors/<id>/escalate``. Each function is one transaction: it
reads the item, updates it and writes one ``processing_status_audit`` row,
or returns ``None`` having written nothing when there is no such item.
"""
from __future__ import annotations

import json

from docket.db import db


def retry_item(item_id: int, actor: str) -> str | None:
    """Reset an item to ``pending`` so the worker runs it again.

    Sets ``processing_status='pending'`` and ``processing_attempts=0`` and
    clears ``backfill_session_id``, ``last_error_at`` and
    ``last_error_message`` (the backfill driver claims an item only when
    ``backfill_session_id IS NULL``). ``score_overrides`` and badges are left
    alone. Returns the status the item had before, or ``None`` when no such
    item exists.
    """
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT processing_status::text FROM agenda_items WHERE id = %s",
                (item_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            from_status = row[0]

            cur.execute(
                """
                UPDATE agenda_items
                   SET processing_status = 'pending'::processing_status_enum,
                       processing_attempts = 0,
                       backfill_session_id = NULL,
                       last_error_at = NULL,
                       last_error_message = NULL
                 WHERE id = %s
                """,
                (item_id,),
            )

            cur.execute(
                """
                INSERT INTO processing_status_audit
                  (agenda_item_id, from_status, to_status, action,
                   actor, actor_role, reason)
                VALUES
                  (%s, %s::processing_status_enum,
                   'pending'::processing_status_enum,
                   'retry', %s, 'admin', %s)
                """,
                (item_id, from_status, actor, "Admin retry from errors queue"),
            )
    return from_status


def escalate_item(item_id: int, actor: str) -> str | None:
    """Flag an item for manual review, leaving its status as it is.

    Merges ``admin_escalated`` and ``admin_escalated_by`` into the item's
    ``score_overrides`` and writes it back, keeping every key already there.
    Returns the item's status, or ``None`` when no such item exists.
    """
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT processing_status::text, score_overrides
                  FROM agenda_items
                 WHERE id = %s
                """,
                (item_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            from_status, existing_overrides = row[0], row[1]

            # Merge admin_escalated into existing score_overrides
            # without clobbering Stage 2.5 floor data. The driver returns
            # JSONB as a Python dict (or None when NULL).
            merged = dict(existing_overrides) if existing_overrides else {}
            merged["admin_escalated"] = True
            merged["admin_escalated_by"] = actor

            cur.execute(
                """
                UPDATE agenda_items
                   SET score_overrides = %s::jsonb
                 WHERE id = %s
                """,
                (json.dumps(merged), item_id),
            )

            cur.execute(
                """
                INSERT INTO processing_status_audit
                  (agenda_item_id, from_status, to_status, action,
                   actor, actor_role, reason, payload)
                VALUES
                  (%s, %s::processing_status_enum,
                   %s::processing_status_enum,
                   'escalate', %s, 'admin', %s, %s::jsonb)
                """,
                (
                    item_id,
                    from_status,
                    from_status,
                    actor,
                    "Admin escalated from errors queue (manual review needed)",
                    json.dumps({"admin_escalated": True}),
                ),
            )
    return from_status
