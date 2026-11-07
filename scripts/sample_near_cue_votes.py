"""Print the video votes that sit near an agenda item's cue point, with the
two items each could belong to and the transcript's words around the vote,
for the operator to read.

A video vote (``votes.source = 'video_ocr'``) is attached to the agenda item
whose cue point (``agenda_items.video_timestamp_seconds``, the second at
which the clerk marked the item as beginning in the Granicus player) is the
latest one at or before the vote's second. When a roll call closes and the
clerk advances the player in the same breath, the vote lands on or a few
seconds after the *next* item's cue point and is filed under an item that
has not started yet (GitHub issue #142). This script lists, for a city,
every active timestamp attachment whose gap from the vote to its item's cue
is at most ``--within`` seconds (default 30), and for each prints the
attached item, the meeting's latest item with a strictly earlier cue second,
how many video votes each already carries, and the transcript's words from
``--before`` seconds before the vote (default 120) to ``--after`` seconds
after it (default 15), so the reader can decide which item's roll call the
words name. A block whose earlier item is itself within ``--within`` of the
vote is marked ``(earlier also near)``; a vote whose stored item is no
longer the latest cue at or before it is marked ``(cue changed since
matching)``. The verdicts go in the plan's Decision Log, not here.

    python scripts/sample_near_cue_votes.py --city birmingham --within 30

Against production the operator sets DATABASE_URL to DATABASE_PUBLIC_URL.
The script writes nothing. Exits 1 for an unknown city.
"""

import argparse
import sys

from docket.services.vote_rematch import list_timestamp_links, transcript_window

TITLE_WIDTH = 90


def _title(text: str | None) -> str:
    text = text or ""
    if len(text) > TITLE_WIDTH:
        return text[: TITLE_WIDTH - 1] + "…"
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", required=True, help="municipality slug")
    parser.add_argument("--within", type=float, default=30.0,
                        help="list votes at most this many seconds after their item's cue (default 30)")
    parser.add_argument("--before", type=float, default=120.0,
                        help="transcript window starts this many seconds before the vote (default 120)")
    parser.add_argument("--after", type=float, default=15.0,
                        help="transcript window ends this many seconds after the vote (default 15)")
    args = parser.parse_args(argv)

    try:
        links = list_timestamp_links(args.city, within_s=args.within)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    meetings: set[int] = set()
    with_transcript = 0
    for link in links:
        meetings.add(link.meeting_id)
        header = (f"vote {link.vote_id}  meeting {link.meeting_id} {link.meeting_date}"
                  f"  at {link.vote_timestamp:.1f}s  {link.result} {link.yeas}-{link.nays}")
        if link.needs_review:
            header += " needs_review"
        print(header)
        attached = (f"  attached: item {link.item_number} (id {link.item_id}, cue {link.item_cue:.1f}s,"
                    f" gap {link.gap:.1f}s, {link.item_active_video_votes} video votes)"
                    f"  {_title(link.item_title)}")
        if not link.is_latest_cue:
            attached += " (cue changed since matching)"
        print(attached)
        if link.earlier_item_id is None:
            print("  earlier:  none")
        else:
            earlier_gap = link.vote_timestamp - link.earlier_cue
            earlier = (f"  earlier:  item {link.earlier_item_number} (id {link.earlier_item_id},"
                       f" cue {link.earlier_cue:.1f}s, gap {earlier_gap:.1f}s,"
                       f" {link.earlier_active_video_votes} video votes)"
                       f"  {_title(link.earlier_item_title)}")
            if earlier_gap <= args.within:
                earlier += " (earlier also near)"
            print(earlier)
        if link.has_transcript:
            with_transcript += 1
            start = link.vote_timestamp - args.before
            end = link.vote_timestamp + args.after
            print(f"  words {start:.1f}-{end:.1f}s:")
            for start_s, text in transcript_window(link.meeting_id, start, end):
                print(f"    [{start_s:.1f}] {text}")
        else:
            print("  (no transcript)")

    print(f"{len(links)} votes within {args.within:.1f}s of their item's cue point"
          f" on {len(meetings)} meetings; {with_transcript} with a transcript")
    return 0


if __name__ == "__main__":
    sys.exit(main())
