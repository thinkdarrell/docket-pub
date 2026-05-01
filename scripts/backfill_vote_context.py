"""Backfill resolution_number and match_context on minutes_text votes.

Re-parses minutes PDFs and matches parsed votes to existing DB votes
by external_id index pattern ({clip_id}-vote-{i+1}).
"""

import logging
import time

import psycopg2

from docket.analysis.minutes_parser import (
    download_minutes_pdf,
    extract_text_from_pdf,
    parse_minutes,
)

from docket.config import DATABASE_URL
DELAY = 0.5

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Find meetings with minutes_text votes missing context
    cur.execute("""
        SELECT DISTINCT m.id, m.external_id, m.minutes_url
        FROM meetings m
        JOIN votes v ON v.meeting_id = m.id
        WHERE v.source = 'minutes_text'
          AND v.resolution_number IS NULL
          AND v.match_context IS NULL
          AND m.minutes_url IS NOT NULL
        ORDER BY m.id
    """)
    meetings = cur.fetchall()
    logger.info(f"{len(meetings)} meetings need vote context backfill\n")

    updated_total = 0
    failed = 0

    for i, (meeting_id, ext_id, minutes_url) in enumerate(meetings):
        pdf_bytes = download_minutes_pdf(minutes_url)
        if not pdf_bytes:
            failed += 1
            time.sleep(DELAY)
            continue

        text = extract_text_from_pdf(pdf_bytes)
        if not text:
            failed += 1
            time.sleep(DELAY)
            continue

        result = parse_minutes(text)

        for j, vote in enumerate(result.votes):
            vote_ext_id = f"{ext_id}-vote-{j + 1}"
            cur.execute(
                """UPDATE votes
                   SET resolution_number = %s, match_context = %s
                   WHERE meeting_id = %s AND external_id = %s
                     AND resolution_number IS NULL""",
                (
                    vote.resolution_number,
                    vote.context[-200:] if vote.context else None,
                    meeting_id,
                    vote_ext_id,
                ),
            )
            if cur.rowcount:
                updated_total += 1

        conn.commit()

        if (i + 1) % 50 == 0:
            logger.info(f"  Progress: {i + 1}/{len(meetings)} meetings, {updated_total} votes updated, {failed} failed")

        time.sleep(DELAY)

    conn.close()
    logger.info(f"\nDone: {updated_total} votes updated with context, {failed} PDF failures")


if __name__ == "__main__":
    main()
