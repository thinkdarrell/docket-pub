"""Match a city's whole YouTube channel to its meeting rows, once.

Runs the same code as the daily worker task ``youtube_ingest``
(``docket.services.youtube_meetings.sync_city``) over every upload published
since ``--since`` (default 2008-01-01) instead of the last 30 days: a
recording attaches to the Granicus row it belongs to, or becomes a
``yt-<video id>`` row when Granicus never had the meeting. It prints one
line per decision ordered by date, then the ambiguous days, then the counts.
A second dry run after the write prints zero creates and zero attaches.

Dry run first, one city at a time, after ``ingest_all`` has stored the
Granicus clips' durations (a ``no_duration`` count says it has not):
    YOUTUBE_API_KEY=... python scripts/backfill_youtube_meetings.py --city birmingham --dry-run
    YOUTUBE_API_KEY=... python scripts/backfill_youtube_meetings.py --city birmingham

Against production the operator sets DATABASE_URL to DATABASE_PUBLIC_URL
(plans/completed/youtube-council-channel.md, M4 and M5). Exits 1 without a key.
"""

import argparse
import logging
import sys
from datetime import date

from docket import config
from docket.adapters.youtube import YouTubeClient
from docket.services.youtube_meetings import sync_city

logging.basicConfig(level=logging.WARNING, format="%(message)s")


def print_report(report, *, dry_run: bool) -> None:
    for meeting_date, action, detail in sorted(report.decisions, key=lambda d: d[0]):
        print(f"{meeting_date}  {action:<11} {detail}")
    if report.ambiguous_days:
        print("ambiguous days: " + ", ".join(str(d) for d in sorted(set(report.ambiguous_days))))
    print("counts: " + ", ".join(f"{a}={n}" for a, n in report.counts.items()))
    if report.counts.get("no_duration"):
        print(f"{report.counts['no_duration']} recordings not matched: "
              "run ingest_all first so Granicus durations are stored")
    if dry_run:
        print("dry run: nothing written")
    else:
        print(f"rows touched and re-resolved: {len(report.touched_ids)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", required=True, help="municipality slug")
    parser.add_argument("--dry-run", action="store_true", help="print the decisions; write nothing")
    parser.add_argument("--since", type=date.fromisoformat, default=None,
                        help="read uploads published on or after this date (YYYY-MM-DD; default 2008-01-01)")
    args = parser.parse_args()

    if not config.YOUTUBE_API_KEY:
        print("YOUTUBE_API_KEY is not set", file=sys.stderr)
        sys.exit(1)
    client = YouTubeClient(config.YOUTUBE_API_KEY, delay=0.2)
    report = sync_city(args.city, client=client, since=args.since or date(2008, 1, 1),
                       today=date.today(), dry_run=args.dry_run)
    print_report(report, dry_run=args.dry_run)
