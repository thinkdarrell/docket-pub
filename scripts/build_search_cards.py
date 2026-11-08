#!/usr/bin/env python
# scripts/build_search_cards.py
"""Build search cards for Birmingham meetings, bounded: a thin command over `docket.ai.transcripts.cards.run_cards`.

A search card is hidden search text for an agenda item, written by a model
from the meeting's transcript. The worker's daily `transcript_pipeline` tick
builds `TRANSCRIPT_CARDS_PER_TICK` meetings a day; this is the faster route.

    venv/bin/python scripts/build_search_cards.py --count                      # read only: where the archive stands
    venv/bin/python scripts/build_search_cards.py --limit 10                   # the ten newest meetings still waiting
    venv/bin/python scripts/build_search_cards.py --meeting-id 2224 --meeting-id 2231 --dry-run
    venv/bin/python scripts/build_search_cards.py --meeting-id 2224            # rebuild one meeting whatever its run says

Exactly one of `--count`, `--limit N`, or `--meeting-id N` is required, so no
invocation is unbounded. `--limit` and `--meeting-id` call the model (they
need ANTHROPIC_API_KEY) and stop at AI_DAILY_BUDGET_USD unless `--force-budget`
is given. `--dry-run` calls the model and prints each report line but claims
nothing and writes no card and no run row; its `ai_runs` row is written, since
the call is paid for.
"""
from __future__ import annotations

import argparse
import logging
import sys


def _parse(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Build search cards for Birmingham meetings, bounded.")
    ap.add_argument("--count", action="store_true", help="print where the archive stands and exit; reads only")
    ap.add_argument("--limit", type=int, metavar="N", help="build the N newest meetings that lack current cards")
    ap.add_argument("--meeting-id", type=int, action="append", metavar="N",
                    help="build this meeting whatever its run row says; repeatable")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --limit or --meeting-id: call the model and report, write no card and no run row")
    ap.add_argument("--force-budget", action="store_true", help="keep going past AI_DAILY_BUDGET_USD")
    a = ap.parse_args(argv)
    modes = [a.count, a.limit is not None, bool(a.meeting_id)]
    if sum(modes) != 1:
        ap.error("exactly one of --count, --limit N, or --meeting-id N is required")
    if a.limit is not None and a.limit < 1:
        ap.error("--limit must be at least 1")
    if a.count and (a.dry_run or a.force_budget):
        ap.error("--count only reads; it takes neither --dry-run nor --force-budget")
    return a


def main(argv: list[str] | None = None) -> int:
    a = _parse(argv)   # a refusal exits 2 here, before anything is imported or connected
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from docket.ai.exceptions import AIFatalError
    from docket.ai.transcripts import cards

    if a.count:
        c = cards.count_card_runs()
        print(f"cards: {c['public']} Birmingham meetings with a public transcript; {c['past_events']} past the "
              f"events stage; {c['current']} with current cards; {c['waiting']} waiting; {c['held']} held; "
              f"{c['failed']} failed")
        return 0
    try:
        s = cards.run_cards(limit=a.limit if a.limit is not None else len(a.meeting_id), notes="cli_cards",
                            force_budget=a.force_budget, meeting_ids=a.meeting_id, dry_run=a.dry_run)
    except AIFatalError as e:
        print(f"cards: fatal: {e}", file=sys.stderr)
        return 1
    for line in s.reports:
        print(line)
    print(f"cards: built {s.built}, held {s.held}, failed {s.failed}, stopped: {s.stopped_reason or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
