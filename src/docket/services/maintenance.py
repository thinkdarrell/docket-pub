"""Periodic maintenance / repair operations called from the cron worker."""

from __future__ import annotations

import logging

from docket.db import db

log = logging.getLogger(__name__)


def repair_empty_agendas() -> int:
    """Reset agenda_items_scraped for meetings that ended up with zero items.

    Targets meetings within the last 18 months that have an agenda_url, were
    flagged scraped, but have no agenda_items rows. Skips cancelled meetings
    (title matches /cancell?ed/i) since those legitimately have no agenda.

    The next ingest run will re-fetch whatever this clears.

    Returns:
        Number of meetings whose flag was cleared.
    """
    with db() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE processing_status ps
               SET agenda_items_scraped = FALSE
              FROM meetings m
             WHERE ps.meeting_id = m.id
               AND m.agenda_url IS NOT NULL
               AND m.meeting_date >= CURRENT_DATE - INTERVAL '18 months'
               AND ps.agenda_items_scraped = TRUE
               AND m.title !~* 'cancell?ed'
               AND NOT EXISTS (
                   SELECT 1 FROM agenda_items ai WHERE ai.meeting_id = m.id
               )
        """)
        cleared = cur.rowcount
        conn.commit()
    log.info("repair_empty_agendas cleared=%d", cleared)
    return cleared
