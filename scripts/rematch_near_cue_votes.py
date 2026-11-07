"""Move the video votes that sit near an agenda item's cue point to the item
whose roll call they close.

A video vote (``votes.source = 'video_ocr'``) is attached to an agenda item
by ``docket.analysis.vote_matcher.match_votes_by_timestamp``: the item
whose cue point (``agenda_items.video_timestamp_seconds``) is the latest at
or before the vote's second, except that a vote within ``NEAR_CUE_S``
seconds of that cue is the close of the previous item's roll call, read as
the clerk advanced the player, and goes to the latest item with a strictly
earlier cue second (GitHub issue #142). The matcher visits only votes with
no active link, so the attachments stored before that rule shipped are
moved by this script: it runs ``docket.services.vote_rematch
.rematch_near_cue_links`` over the city's active, non-manual timestamp
attachments and, for each one the rule now places elsewhere, deactivates
the old ``vote_agenda_items`` row and inserts (or revives) the new one, in
one transaction. Nothing is deleted; a manual link is never touched; a link
whose stored item is no longer even the latest cue before its vote (cue
points changed after matching) is listed as left alone and not moved.

It prints one line per move, one per link left alone, and the totals. A
second run after the write prints zero moves. Dry run first; the order the
operator runs it in, with the count query before and after, is in
docs/specs/operations.md ("Railway specifics"):
    python scripts/rematch_near_cue_votes.py --city birmingham --dry-run
    python scripts/rematch_near_cue_votes.py --city birmingham

Against production the operator sets DATABASE_URL to DATABASE_PUBLIC_URL.
Exits 1 for an unknown city.
"""

import argparse
import sys

from docket.services.vote_rematch import rematch_near_cue_links


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", required=True, help="municipality slug")
    parser.add_argument("--dry-run", action="store_true", help="print what would move; write nothing")
    args = parser.parse_args(argv)

    try:
        moves = rematch_near_cue_links(args.city, dry_run=args.dry_run)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    meetings: set[int] = set()
    moved = 0
    left = 0
    for m in moves:
        link = m.link
        if m.reason == "near_cue":
            moved += 1
            meetings.add(link.meeting_id)
            print(f"vote {link.vote_id}  meeting {link.meeting_id} {link.meeting_date}"
                  f"  at {link.vote_timestamp:.1f}s:"
                  f" item {link.item_number} (id {link.item_id}, cue {link.item_cue:.1f}s,"
                  f" gap {link.gap:.1f}s)"
                  f" -> item {m.new_item_number} (id {m.new_item_id}, cue {m.new_cue:.1f}s,"
                  f" gap {m.new_gap:.1f}s), confidence {m.new_confidence}")
        else:
            left += 1
            print(f"left alone (cue changed): vote {link.vote_id}  meeting {link.meeting_id}"
                  f"  item {link.item_number} (id {link.item_id}, cue {link.item_cue:.1f}s)"
                  f" is no longer the latest cue before {link.vote_timestamp:.1f}s")

    verb = "would be written" if args.dry_run else "written"
    print(f"{moved} moves on {len(meetings)} meetings {verb}; {left} left alone (cue changed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
