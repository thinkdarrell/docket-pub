"""Hide the clips that are not meetings, in one statement per city, or list them with --dry-run.

For every active city whose metadata carries ``calendar_complete_from``
(Birmingham only), prints one line per clip the rule in
``docket.services.non_meetings`` finds: the meeting id, its date, its title,
its stored length in seconds, its transcript's status, and ``hide`` or
``held: has speech``. A held clip meets the rule but has a public transcript
with speech; it is never hidden by this script and is listed on
``/admin/meetings/hidden`` for the operator to judge. A city whose sitemap
reader has not finished a read without a failed page in the last 36 hours
prints nothing, with a warning.

Then, without ``--dry-run``, the ``hide`` rows of each city are hidden with
one ``UPDATE`` scoped to rows still visible and not exempt (decision 0026),
and the ids written are printed. A second run prints no ``hide`` line.

Dry run first:
    python scripts/hide_non_meetings.py --dry-run
    python scripts/hide_non_meetings.py

Against production the operator sets DATABASE_URL to DATABASE_PUBLIC_URL.
The undo for one row is its Unhide button on /admin/meetings/hidden, which
also exempts it; for all of them,
``UPDATE meetings SET is_hidden = FALSE, hidden_at = NULL, hidden_reason = NULL WHERE hidden_reason = 'not_a_meeting'``.
Plan `committee-clips-named-or-hidden`, M4.
"""

import argparse
import logging

from docket.services import non_meetings

logging.basicConfig(level=logging.WARNING, format="%(message)s")


def _line(row: dict, verdict: str) -> str:
    return (
        f"{row['id']}  {row['meeting_date']}  {row['title']}  "
        f"duration_s={row['duration_s']}  transcript={row['transcript_status']}  {verdict}"
    )


def main(*, dry_run: bool) -> None:
    found = non_meetings.find_all()
    for slug, (to_hide, held) in found.items():
        print(f"{slug}: {len(to_hide)} to hide, {len(held)} held back")
        for verdict, rows in (("hide", to_hide), ("held: has speech", held)):
            for row in rows:
                print("  " + _line(row, verdict))
    if dry_run:
        print("dry run: 0 rows written")
        return
    for slug, (hidden, _) in non_meetings.hide_non_meetings().items():
        print(f"{slug}: hidden {len(hidden)} rows in one statement: {hidden}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print the rows; write nothing")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
