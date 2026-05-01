"""Backfill video_timestamp_seconds on agenda_items by re-scraping Granicus player pages.

For each Birmingham meeting, fetches the Granicus player page and extracts
index-point timestamps, then updates existing agenda_items rows.
"""

import time
import logging

import psycopg2
import requests
from bs4 import BeautifulSoup

PG_DSN = "postgresql://docket@localhost:5432/docket_db"
GRANICUS_BASE = "https://bhamal.granicus.com"
DELAY = 1.0

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main():
    conn = psycopg2.connect(PG_DSN)
    cur = conn.cursor()

    # Find meetings with agenda items that lack timestamps
    cur.execute("""
        SELECT DISTINCT m.id, m.external_id
        FROM meetings m
        JOIN agenda_items ai ON ai.meeting_id = m.id
        WHERE m.municipality_id = 1
          AND ai.video_timestamp_seconds IS NULL
        ORDER BY m.id
    """)
    meetings = cur.fetchall()
    logger.info(f"{len(meetings)} meetings need timestamp backfill\n")

    updated_total = 0
    for i, (meeting_id, ext_id) in enumerate(meetings):
        try:
            clip_id = int(ext_id)
        except (ValueError, TypeError):
            continue

        url = f"{GRANICUS_BASE}/MediaPlayer.php?view_id=2&clip_id={clip_id}"
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning(f"  [{ext_id}] fetch failed: {e}")
            time.sleep(DELAY)
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        index_points = soup.find_all("div", class_="index-point")

        updated = 0
        for j, point in enumerate(index_points):
            ts = point.get("time")
            meta_id = point.get("data-id")
            if ts is None:
                continue

            # Match by external_id (meta_id) or by item_number (j+1)
            ext = meta_id or f"{clip_id}-{j}"
            cur.execute(
                """UPDATE agenda_items
                   SET video_timestamp_seconds = %s
                   WHERE meeting_id = %s AND (external_id = %s OR item_number = %s)
                     AND video_timestamp_seconds IS NULL""",
                (float(ts), meeting_id, ext, str(j + 1)),
            )
            updated += cur.rowcount

        if updated:
            conn.commit()
            updated_total += updated

        if (i + 1) % 50 == 0:
            logger.info(f"  Progress: {i + 1}/{len(meetings)} meetings, {updated_total} items updated")

        time.sleep(DELAY)

    conn.commit()
    conn.close()
    logger.info(f"\nDone: {updated_total} agenda items updated with timestamps")


if __name__ == "__main__":
    main()
