"""Create meetings Granicus never recorded, from a manifest of YouTube videos
and Wayback-archived agenda PDFs (see services/archived_meetings.py).

Idempotent: re-running skips meetings already backfilled and retries any
whose agenda fetch failed.

    python scripts/backfill_archived_meetings.py --manifest scripts/manifests/birmingham_2023_archived.json --dry-run
    python scripts/backfill_archived_meetings.py --manifest scripts/manifests/birmingham_2023_archived.json
"""

import argparse
import json
import logging
from datetime import date
from pathlib import Path

from docket.db import db
from docket.services.archived_meetings import (
    ArchivedMeeting,
    backfill_archived_meetings,
    fetch_agenda_text,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")

REPO_ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="JSON manifest path")
    parser.add_argument("--dry-run", action="store_true", help="report only; fetch and write nothing")
    parser.add_argument("--cache-dir", default=str(REPO_ROOT / "data" / "archived_agendas"),
                        help="where fetched agenda PDFs are kept so each is pulled from the Wayback Machine once")
    args = parser.parse_args()

    def _polite_fetch(url: str) -> str:
        # Retries 429/5xx on its own; the 20 s pace applies after network fetches only.
        return fetch_agenda_text(url, cache_dir=Path(args.cache_dir), pace_seconds=20.0)

    with open(args.manifest) as f:
        manifest = json.load(f)
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = %s", (manifest["municipality"],))
        row = cur.fetchone()
    if row is None:
        raise SystemExit(f"Unknown city slug: {manifest['municipality']}")

    entries = [
        ArchivedMeeting(
            meeting_date=date.fromisoformat(m["date"]),
            youtube_id=m.get("youtube_id"),
            agenda_url=m.get("agenda_url"),
            title=m.get("title", manifest.get("title", "Regular City Council Meeting")),
        )
        for m in manifest["meetings"]
    ]
    result = backfill_archived_meetings(row[0], entries, fetch_agenda_text=_polite_fetch,
                                        dry_run=args.dry_run)
    if args.dry_run:
        print(f"would create {len(result.planned)} meetings: {', '.join(result.planned)}")
    else:
        print(f"created {len(result.inserted)} meetings (ids {result.inserted})")
    for s in result.skipped:
        print(f"  skipped {s}")
    for e in result.errors:
        print(f"  ERROR {e}")
    raise SystemExit(1 if result.errors else 0)
