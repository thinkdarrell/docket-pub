"""Periodic maintenance / repair operations called from the cron worker."""

from __future__ import annotations

import logging
import re
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
    nothing retries them. Runs vote matching (which links, then promotes) on
    each such meeting; one failure doesn't stop the rest. Idempotent.

    Returns:
        ids of the meetings that no longer have provisional links.
    """
    from docket.analysis.vote_matcher import has_provisional_links

    if reparse is None:
        from docket.analysis.vote_matcher import match_votes_for_meeting as reparse

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
        # A re-parse that couldn't fetch the minutes PDF returns normally
        # having changed nothing; only count meetings that actually finished.
        if has_provisional_links(meeting_id):
            log.warning("reparse_pending meeting=%s still provisional result=%s", meeting_id, result)
            continue
        log.info("reparse_pending meeting=%s result=%s", meeting_id, result)
        done.append(meeting_id)
    return done


def reactivate_consent_links_without_pull_evidence(
    municipality_id: int, *, dry_run: bool = False,
) -> list[tuple[int, int]]:
    """Bring back consent-vote links the old strict re-parse hid without evidence.

    Before 2026-10-02 the strict re-parse deactivated every consent link whose
    item it could not find in the minutes' enumerated list. The current rule
    (vote_matcher.strict_reparse_meeting) hides a link only when the minutes
    also record a separate vote on that item. This restores, on adopted
    meetings, every non-manual consent link that the current rule would not
    have hidden: no separate active explicit minutes-text link for the item.
    (Video-OCR links don't count, matching the re-parse.) Withdrawn items stay
    hidden: the consent-block matcher links every consent item, withdrawn ones
    included, and restoring those would show "passed on consent" on item
    pages. Restored links are official (minutes adopted). Idempotent.

    Returns:
        (meeting_id, links restored) per meeting, ordered by meeting id.
    """
    from docket.ai.wave0 import is_withdrawn_or_deferred

    sql = """
        SELECT vai.id, v.meeting_id, ai.title, ai.processing_status::text
          FROM vote_agenda_items vai
          JOIN votes v ON v.id = vai.vote_id
          JOIN meetings m ON m.id = v.meeting_id
          JOIN agenda_items ai ON ai.id = vai.agenda_item_id
         WHERE m.municipality_id = %s
           AND m.minutes_adopted_at IS NOT NULL
           AND vai.is_active = FALSE
           AND vai.is_manual = FALSE
           AND vai.association_type IN ('consent_named', 'consent_implicit')
           AND NOT EXISTS (
               SELECT 1 FROM vote_agenda_items sep
               JOIN votes sv ON sv.id = sep.vote_id
               WHERE sep.agenda_item_id = vai.agenda_item_id
                 AND sep.vote_id <> vai.vote_id
                 AND sv.meeting_id = v.meeting_id
                 AND sv.source = 'minutes_text'
                 AND sep.association_type = 'explicit'
                 AND sep.is_active = TRUE
           )
         ORDER BY v.meeting_id, vai.id
    """
    with db() as conn, conn.cursor() as cur:
        cur.execute(sql, (municipality_id,))
        rows = [
            (link_id, meeting_id)
            for link_id, meeting_id, title, status in cur.fetchall()
            if status != "withdrawn"
            and not is_withdrawn_or_deferred(title)
            and not _WITHDRAWN_HEADER_RE.search(" ".join((title or "").split()))
        ]
        per_meeting: dict[int, int] = {}
        for _link_id, meeting_id in rows:
            per_meeting[meeting_id] = per_meeting.get(meeting_id, 0) + 1
        if rows and not dry_run:
            # Re-check the cheap invariants: an admin edit or a vote_matching
            # tick could have landed between the SELECT and this UPDATE.
            cur.execute(
                """UPDATE vote_agenda_items
                      SET is_active = TRUE, provisional = FALSE, updated_at = NOW()
                    WHERE id = ANY(%s)
                      AND is_active = FALSE
                      AND is_manual = FALSE""",
                ([link_id for link_id, _ in rows],),
            )
            conn.commit()
    result = sorted(per_meeting.items())
    log.info("reactivate_consent_links: %d links on %d meetings%s",
             len(rows), len(result), " (dry run)" if dry_run else "")
    return result


# Clerk markings in the item header that the wave0 patterns miss:
# "CONSENT ITEM 32.withdrawn A Resolution…", "CONSENT ITEM 22. WITHDRAWNA
# Resolution…", "CONSENT ITEM 56. [WITHDRAWN PER P.E.P.] A Resolution…".
# Header position only: "[WITHDRAW PROPERTY #38 …]" pulls one property from
# a resolution that still passed, and "withdrawing" in the body is just the
# resolution's subject.
_WITHDRAWN_HEADER_RE = re.compile(
    r"^(?:withdrawn\s+)?consent\s*(?:\(ph\))?\s*item\s+\d+\.?\s*"
    r"(?:withdrawn|\[withdrawn\b[^\]]*\])"
    r"|^withdrawn\b",
    re.IGNORECASE,
)


def correct_adoption_dates(
    municipality_id: int, *, dry_run: bool = False,
) -> list[tuple[int, date, date]]:
    """Fix adoption dates the pre-2026-10-02 parser assigned from the wrong line.

    For every meeting with a recorded ``minutes_adopted_at``, re-derive the
    agenda lines that name it (minutes_adoption.adoption_lines_by_target).
    A recorded date that matches one of them stands, including when an
    earlier line exists (the sweep's "first recorded" rule). One that matches
    none was taken from a line naming other meetings; it is replaced with the
    earliest line whose meeting recorded a passed vote (the sweep's evidence
    rule). No such line: left alone. Unrecorded meetings are the sweep's job.

    Returns:
        (meeting_id, old_date, new_date) per corrected meeting.
    """
    import psycopg2.extras

    from docket.services.minutes_adoption import adoption_lines_by_target

    fixes: list[tuple[int, date, date]] = []
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            lines = adoption_lines_by_target(cur, municipality_id)
            cur.execute(
                """SELECT id, minutes_adopted_at::date AS recorded
                   FROM meetings
                   WHERE municipality_id = %s AND is_hidden = FALSE
                     AND minutes_adopted_at IS NOT NULL
                   ORDER BY meeting_date, id""",
                (municipality_id,),
            )
            for row in cur.fetchall():
                named = lines.get(row["id"], [])
                if row["recorded"] in {d for d, _ in named}:
                    continue
                evidenced = sorted(d for d, has_vote in named if has_vote)
                if not evidenced:
                    continue
                fixes.append((row["id"], row["recorded"], evidenced[0]))
            if fixes and not dry_run:
                for meeting_id, old, new in fixes:
                    cur.execute(
                        """UPDATE meetings SET minutes_adopted_at = %s
                           WHERE id = %s AND minutes_adopted_at::date = %s""",
                        (new, meeting_id, old),
                    )
                conn.commit()
    log.info("correct_adoption_dates: %d meetings%s", len(fixes), " (dry run)" if dry_run else "")
    return fixes
