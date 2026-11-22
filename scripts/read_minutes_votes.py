"""Read one city's listed Minutes files into votes, as a dry run or for real.

The supervised run of what the daily ingest does a few files at a time, for a
city whose ``adapter_config`` names a ``minutes_reader``. It runs
``docket.services.minutes_votes.read_city``: the city's events are listed
from its ``backlog_floor``, and up to ``--limit`` of their Minutes files that
are waiting (never read, read by an older reader, or failed fewer than three
times) are fetched, newest event first, one request at a time under the
adapter's delay. Each is read, paired to the one meeting its first page
dates, and stored: that meeting's votes from the minutes with their member
votes, its minutes link, and the file's row in ``minutes_files``. With
``--apply`` each file is one transaction, and afterwards every coded vote is
attached to the agenda item that opens with its code.

Without ``--apply`` the same files are fetched and read and the same
statements are run on one connection, opened after the last file is read,
and rolled back. Nothing is changed, and nothing is attached by code. A full
dry run inserts and rolls back every vote, so run it once.

The first line printed names the database it is connected to, as the host
and the database name of DATABASE_URL and nothing else of it. Then one line
per file read, the totals, and ``dry run: nothing changed``; with ``--apply``,
``attached to agenda items by code: <n>``, the votes the run attached across
the whole city (a vote stored by an earlier run whose item has arrived since
is counted), and ``applied``:

    database: localhost/docket_test_5e7545f1
    file 3861 on event 500 names 2026-11-10 -> paired, 48 votes
    file 3854 on event 499 names 2026-11-03 -> paired, 40 votes
    read: 2  paired: 2  superseded: 0  not_minutes: 0  no_meeting: 0  errors: 0  votes: 88  waiting: 252
    dry run: nothing changed

A file's line says the date its heading prints when it prints one, then what
became of it: ``paired`` with the votes stored, ``superseded``,
``not_minutes``, ``no_meeting``, or ``error:`` and the reason. ``waiting``
is the files the limit left unread.

Dry run first, one city at a time:
    python scripts/read_minutes_votes.py --city mobile --limit 300
    python scripts/read_minutes_votes.py --city mobile --limit 60 --apply

Against production the operator sets DATABASE_URL to DATABASE_PUBLIC_URL.
Exits 2 for an unknown city, a city whose settings name no reader, and a
setting that cannot be read, each before any request to the city, and for
nothing else. A file whose reading cannot be stored is that file's ``error``
line and the run goes on. A run that fails once under way (the database goes
away) ends with a traceback and exit status 1; with ``--apply`` the files
before the failure are stored, though their lines were not printed, and the
same command again reads the ones that are left.
"""

import argparse
import logging
import sys
from urllib.parse import urlsplit

from docket.config import DATABASE_URL
from docket.services.minutes_votes import Refused, read_city

logging.basicConfig(level=logging.WARNING, format="%(message)s")

STATUSES = ("paired", "superseded", "not_minutes", "no_meeting", "error")


def database_label(url: str) -> str:
    """The host and database name of a database URL, and nothing else of it."""
    parts = urlsplit(url)
    return f"{parts.hostname or 'localhost'}/{parts.path.lstrip('/')}"


def whole_number(text: str) -> int:
    number = int(text)
    if number < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return number


def file_line(outcome) -> str:
    """One file of a report, as the script prints it."""
    line = f"file {outcome.file_id} on event {outcome.event_external_id}"
    if outcome.header_date is not None:
        line += f" names {outcome.header_date.isoformat()}"
    if outcome.status == "paired":
        return f"{line} -> paired, {outcome.votes} votes"
    if outcome.status == "error":
        return f"{line} -> error: {outcome.error}"
    return f"{line} -> {outcome.status}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", required=True, help="municipality slug")
    parser.add_argument("--limit", required=True, type=whole_number, help="read at most this many waiting files")
    parser.add_argument("--apply", action="store_true", help="store; without it, read, run the statements and roll back")
    args = parser.parse_args(argv)

    print(f"database: {database_label(DATABASE_URL)}", flush=True)
    try:
        report = read_city(args.city, limit=args.limit, apply=args.apply)
    except Refused as e:
        print(e, file=sys.stderr)
        return 2

    counts = dict.fromkeys(STATUSES, 0)
    for outcome in report.files:
        counts[outcome.status] += 1
        print(file_line(outcome))
    print(
        f"read: {len(report.files)}  paired: {counts['paired']}  superseded: {counts['superseded']}  "
        f"not_minutes: {counts['not_minutes']}  no_meeting: {counts['no_meeting']}  errors: {counts['error']}  "
        f"votes: {sum(o.votes for o in report.files)}  waiting: {report.waiting}"
    )
    if report.linked is not None:
        print(f"attached to agenda items by code: {report.linked}")
    print("applied" if args.apply else "dry run: nothing changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
