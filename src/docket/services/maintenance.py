"""Periodic maintenance / repair operations called from the cron worker."""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Callable

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


def _fetch_agenda_text(url: str) -> str | None:
    """Download an agenda PDF and return its text (None if it isn't a PDF)."""
    from docket.analysis.minutes_parser import download_minutes_pdf, extract_text_from_pdf

    pdf = download_minutes_pdf(url)
    time.sleep(1.0)  # polite delay between source-site requests
    return extract_text_from_pdf(pdf) if pdf else None


def backfill_minutes_approval_items(
    municipality_id: int,
    *,
    since: date,
    dry_run: bool = False,
    fetch_agenda_text: Callable[[str], str | None] = _fetch_agenda_text,
) -> list[tuple[int, str]]:
    """Restore the minutes-approval agenda line on already-scraped meetings.

    Agendas ingested from PDF before the parser learned the un-numbered
    "APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: ..." line are missing it, and
    ingest never re-scrapes a meeting flagged agenda_items_scraped. Re-reads
    each such agenda and inserts just that one item, which is what
    minutes_adoption.sweep_adoptions keys off. Idempotent.

    Returns:
        (meeting_id, approval line) for each item inserted (or, with dry_run,
        that would be inserted).
    """
    from docket.analysis.agenda_parser import parse_minutes_approval
    from docket.analysis.minutes_approval import is_adoption_title

    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.id, m.external_id, m.agenda_url,
                   ARRAY(SELECT ai.title FROM agenda_items ai
                          WHERE ai.meeting_id = m.id AND ai.title ILIKE '%%minutes%%') AS minutes_titles
              FROM meetings m
             WHERE m.municipality_id = %s
               AND m.meeting_date >= %s
               AND m.agenda_url IS NOT NULL
               AND EXISTS (SELECT 1 FROM agenda_items ai WHERE ai.meeting_id = m.id)
             ORDER BY m.meeting_date
            """,
            (municipality_id, since),
        )
        meetings = [
            (meeting_id, external_id, agenda_url)
            for meeting_id, external_id, agenda_url, minutes_titles in cur.fetchall()
            if not any(is_adoption_title(t) for t in minutes_titles)
        ]

    added: list[tuple[int, str]] = []
    for meeting_id, external_id, agenda_url in meetings:
        text = fetch_agenda_text(agenda_url)
        line = parse_minutes_approval(text) if text else None
        if not line:
            continue
        if not dry_run:
            with db() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agenda_items (meeting_id, external_id, item_number, title, is_consent)
                    VALUES (%s, %s, NULL, %s, FALSE)
                    ON CONFLICT (meeting_id, external_id) DO NOTHING
                    """,
                    (meeting_id, f"{external_id}-minutes-approval", line),
                )
                conn.commit()
        added.append((meeting_id, line))

    log.info(
        "backfill_minutes_approval_items checked=%d added=%d dry_run=%s",
        len(meetings), len(added), dry_run,
    )
    return added


def reparse_adopted_with_provisional_links(
    municipality_id: int,
    *,
    limit: int | None = None,
    reparse: Callable[[int], dict] | None = None,
) -> list[int]:
    """Finish promoting links on meetings whose minutes are adopted.

    minutes_adoption.sweep_adoptions commits its flips before re-parsing, so
    an interrupted sweep leaves adopted meetings with provisional links and
    nothing retries them. Re-parses each such meeting; one failure doesn't
    stop the rest. Idempotent.

    Returns:
        ids of the meetings re-parsed without error.
    """
    if reparse is None:
        from docket.analysis.vote_matcher import strict_reparse_meeting as reparse

    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT m.id
              FROM meetings m
              JOIN votes v ON v.meeting_id = m.id
              JOIN vote_agenda_items vai ON vai.vote_id = v.id
             WHERE m.municipality_id = %s
               AND m.minutes_adopted_at IS NOT NULL
               AND vai.provisional = TRUE
               AND vai.is_active = TRUE
               AND vai.is_manual = FALSE
             ORDER BY m.id
             LIMIT %s
            """,
            (municipality_id, limit),
        )
        meeting_ids = [r[0] for r in cur.fetchall()]

    done: list[int] = []
    for meeting_id in meeting_ids:
        try:
            result = reparse(meeting_id)
        except Exception as e:
            log.warning("reparse_pending failed for meeting %s: %s", meeting_id, e)
            continue
        log.info("reparse_pending meeting=%s result=%s", meeting_id, result)
        done.append(meeting_id)
    return done
