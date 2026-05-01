"""Backfill resolution_number and match_context on minutes_text votes.

Re-parses minutes PDFs and matches parsed votes to existing DB votes
by external_id index pattern ({clip_id}-vote-{i+1}).

Parse results are cached to data/minutes_cache/<meeting_id>.json for fast re-runs.
"""

import json
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import psycopg2

from docket.analysis.minutes_parser import (
    download_minutes_pdf,
    extract_text_from_pdf,
    parse_minutes,
)

from docket.config import DATABASE_URL

DEFAULT_WORKERS = 8

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


def _warm_one(meeting):
    """Worker (module-scope so ProcessPoolExecutor can pickle it).

    Parse + cache one meeting. Returns (meeting_id, ok).
    """
    result = cached_parse(meeting["id"], meeting["minutes_url"])
    return (meeting["id"], result is not None)


def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Find meetings with minutes_text votes that need re-parsing.
    # Predicate is `raw_text IS NULL` (not match_context/resolution_number) because
    # raw_text was added in the parser-widening pass and is NULL for every vote
    # ingested before that change. Re-parsing populates raw_text + refreshes
    # resolution_number / match_context from the wider 1500-char context window
    # (which can find resolution numbers the old 200-char window missed).
    cur.execute("""
        SELECT DISTINCT m.id, m.external_id, m.minutes_url
        FROM meetings m
        JOIN votes v ON v.meeting_id = m.id
        WHERE v.source = 'minutes_text'
          AND v.raw_text IS NULL
          AND m.minutes_url IS NOT NULL
        ORDER BY m.id
    """)
    meetings_raw = cur.fetchall()

    # Convert to list of dicts for cleaner parallel phase
    meetings_to_process = [
        {"id": m[0], "external_id": m[1], "minutes_url": m[2]}
        for m in meetings_raw
    ]

    logger.info(f"{len(meetings_to_process)} meetings need vote context backfill\n")

    # Phase 1: Warm the cache in parallel
    workers = int(os.environ.get("BACKFILL_WORKERS", DEFAULT_WORKERS))
    print(f"Phase 1: parsing {len(meetings_to_process)} meetings with {workers} workers...")

    completed = 0
    failed_phase1: list[int] = []
    total = len(meetings_to_process)

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_warm_one, m): m for m in meetings_to_process}
        for future in as_completed(futures):
            meeting_id, ok = future.result()
            completed += 1
            if not ok:
                failed_phase1.append(meeting_id)
            if completed % 25 == 0 or completed == total:
                print(f"  parsed {completed}/{total} ({len(failed_phase1)} failed)")

    print(f"Phase 1 complete: {completed - len(failed_phase1)} cached, {len(failed_phase1)} failed\n")

    # Phase 2: Serial DB UPDATEs
    print("Phase 2: updating votes from cache...")

    updated_total = 0
    failed_phase2 = 0

    for i, meeting in enumerate(meetings_to_process):
        meeting_id = meeting["id"]
        ext_id = meeting["external_id"]
        minutes_url = meeting["minutes_url"]

        cached = cached_parse(meeting_id, minutes_url)
        if not cached:
            failed_phase2 += 1
            time.sleep(DELAY)
            continue

        for j, vote in enumerate(cached["votes"]):
            vote_ext_id = f"{ext_id}-vote-{j + 1}"
            # WHERE raw_text IS NULL guards against double-updating votes already
            # backfilled. Idempotent: re-running this script is a no-op for any
            # vote whose raw_text has been populated.
            cur.execute(
                """UPDATE votes
                   SET resolution_number = COALESCE(%s, resolution_number),
                       match_context = %s,
                       raw_text = %s
                   WHERE meeting_id = %s AND external_id = %s
                     AND raw_text IS NULL""",
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
            logger.info(f"  Progress: {i + 1}/{len(meetings_to_process)} meetings, {updated_total} votes updated, {failed_phase2} failed")

        time.sleep(DELAY)

    conn.close()
    logger.info(f"\nDone: {updated_total} votes updated with context, {failed_phase2} PDF failures")


if __name__ == "__main__":
    main()
