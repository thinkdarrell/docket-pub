"""Delete one city's stored agenda items and re-open its meetings.

The supervised reset for a city whose stored agenda items cannot be trusted.
It runs ``docket.services.ingest.reset_agenda_items``: in one transaction it
deletes the city's agenda items (and the status-audit rows on them), clears
the AI summary of each of the city's meetings, and clears the
``agenda_items_scraped`` mark on its meetings, so the daily ingest fetches
the city's agendas again. The meetings, their links and their other marks
are not touched.

It refuses a city whose items carry vote links, transcript segments or
minutes discrepancies, with or without ``--apply``, and prints the three
counts.

The first line printed names the database it is connected to, as the host
and the database name of DATABASE_URL and nothing else of it. Then the
counts, and ``dry run: nothing changed`` or ``applied``.

Dry run first, one city at a time (the dry run only reads):
    python scripts/reset_agenda_items.py --city mobile
    python scripts/reset_agenda_items.py --city mobile --apply

Run it once per city: a second ``--apply`` after the ingest has refilled the
city deletes the refilled items. Against production the operator sets
DATABASE_URL to DATABASE_PUBLIC_URL. Exits 2 for an unknown city or a city
that is refused.
"""

import argparse
import logging
import sys
from urllib.parse import urlsplit

from docket.config import DATABASE_URL
from docket.services.ingest import reset_agenda_items

logging.basicConfig(level=logging.WARNING, format="%(message)s")


def database_label(url: str) -> str:
    """The host and database name of a database URL, and nothing else of it."""
    parts = urlsplit(url)
    return f"{parts.hostname or 'localhost'}/{parts.path.lstrip('/')}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", required=True, help="municipality slug")
    parser.add_argument("--apply", action="store_true", help="delete and re-open; without it, print the counts and write nothing")
    args = parser.parse_args(argv)

    print(f"database: {database_label(DATABASE_URL)}", flush=True)
    try:
        counts = reset_agenda_items(args.city, apply=args.apply)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2

    for name, value in counts.items():
        print(f"{name}: {value}")
    print("applied" if args.apply else "dry run: nothing changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
