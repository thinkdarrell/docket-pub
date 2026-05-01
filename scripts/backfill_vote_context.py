"""Backfill resolution_number and match_context on minutes_text votes.

Re-parses minutes PDFs and matches parsed votes to existing DB votes
by external_id index pattern ({clip_id}-vote-{i+1}).

Parse results are cached to data/minutes_cache/<meeting_id>.json for fast re-runs.
"""

import json
import logging
import sys
import time
from pathlib import Path

import psycopg2

from docket.analysis.minutes_parser import (
    download_minutes_pdf,
    extract_text_from_pdf,
    parse_minutes,
)

from docket.config import DATABASE_URL

DELAY = 0.5
CACHE_DIR = Path("data/minutes_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _cache_path(meeting_id: int) -> Path:
    """Return the cache file path for a given meeting_id."""
    return CACHE_DIR / f"{meeting_id}.json"


def cached_parse(meeting_id: int, minutes_url: str) -> dict | None:
    """Return cached parse result if present, else parse and cache.

    Returns a dict with the same shape as ParsedMinutes (full_text + list of
    parsed votes), or None if download/parse failed.
    """
    p = _cache_path(meeting_id)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            # Corrupted cache file — re-parse below
            pass

    pdf = download_minutes_pdf(minutes_url)
    if not pdf:
        return None
    text = extract_text_from_pdf(pdf)
    if not text:
        return None
    parsed = parse_minutes(text)
    payload = {
        "full_text": parsed.full_text,
        "votes": [
            {
                "ayes": v.ayes,
                "nays": v.nays,
                "abstentions": v.abstentions,
                "result": v.result,
                "resolution_number": v.resolution_number,
                "context": v.context,
                "raw_text": v.raw_text,
                "is_likely_consent": v.is_likely_consent,
            }
            for v in parsed.votes
        ],
    }
    try:
        p.write_text(json.dumps(payload))
    except OSError as e:
        # Don't fail the run if we can't write cache; log to stderr
        print(
            f"WARN: failed to write cache for meeting {meeting_id}: {e}",
            file=sys.stderr,
        )
    return payload


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
        cached = cached_parse(meeting_id, minutes_url)
        if not cached:
            failed += 1
            time.sleep(DELAY)
            continue

        for j, vote in enumerate(cached["votes"]):
            vote_ext_id = f"{ext_id}-vote-{j + 1}"
            cur.execute(
                """UPDATE votes
                   SET resolution_number = %s, match_context = %s, raw_text = %s
                   WHERE meeting_id = %s AND external_id = %s
                     AND resolution_number IS NULL""",
                (
                    vote["resolution_number"],
                    (vote["context"][-200:] if vote["context"] else None),
                    (vote["raw_text"] or None),
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
