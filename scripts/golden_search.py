#!/usr/bin/env python
"""Golden search check: ask a deployment of the site the golden queries and
report where each target agenda item lands on the first results page.

Each pair in `tests/fixtures/golden_search/queries.json` is a loose, everyday
query and the one agenda item a resident typing it means. The check fetches
`<base-url>/search?q=<query>&city=<city>` once per distinct query, reads the
result cards off the page, and prints one line per pair and a summary:

    golden: 3 of 45 targets on the first page (top 3: 3, top 10: 3, top 20: 3); 0 with spoken moments; 42 queries

It is a measurement, not a gate: the exit status is 0 whatever the score, 1
when a page could not be fetched, and 2 for a refused invocation. It only
reads, uses the standard library alone, and never asks faster than one
request a second (`GOALS.md`, Constraints).

    python scripts/golden_search.py --base-url https://docket.pub
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

DEFAULT_PAIRS = (pathlib.Path(__file__).resolve().parents[1]
                 / "tests" / "fixtures" / "golden_search" / "queries.json")
PAIR_KEYS = ("query", "item_id", "meeting_id", "kind")
USER_AGENT = "docket-golden-search/1.0 (operator's own check)"
MIN_DELAY_S = 1.0
TIMEOUT_S = 60

# The search page's results follow this heading; the page chrome above it
# links no agenda item (src/docket/web/templates/search.html).
RESULTS_MARKER = "Refine search"

# The markup contract with the search page. A result card links its item at
# /al/<slug>/items/<id>/. A spoken moment nested under a card is
# <li class="search-moment" data-item-id="<id>"> holding a link that ends
# /transcript/#t-<seq>. A transcript line of the lower list is
# <li class="search-transcript-hit">; neither kind of <li> nests another.
_ITEM_LINK = re.compile(r'href="/al/[^/"]+/items/(\d+)/"')
_MOMENT = re.compile(r'<li class="search-moment" data-item-id="(\d+)"[^>]*>(.*?)</li>', re.DOTALL)
_MOMENT_LINK = re.compile(r'href="[^"]*/transcript/#t-(\d+)"')
_LOOSE_OPEN = '<li class="search-transcript-hit"'
_LOOSE = re.compile(re.escape(_LOOSE_OPEN) + r".*?</li>", re.DOTALL)


class FetchFailed(Exception):
    """A results page could not be fetched, or what came back is not one."""

    def __init__(self, url: str, error: object):
        super().__init__(f"{url}: {error}")
        self.url = url
        self.error = error


def load_pairs(path) -> list[dict]:
    pairs = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    for n, pair in enumerate(pairs, start=1):
        missing = [k for k in PAIR_KEYS if k not in pair]
        if missing:
            raise ValueError(f"{path}: pair {n} lacks {', '.join(missing)}")
    return pairs


def parse_results(html: str) -> dict:
    """Read one results page: `items`, the agenda item ids of the result cards
    in first-appearance order; `moments`, for each item id the transcript
    `seq` numbers of the spoken moments nested under its card; `loose`, the
    number of transcript lines in the lower list.

    Only the part of the page after "Refine search" is read. An item link
    inside a line of the lower list names the item that line is filed under,
    which is not a result, so it is not read into `items`.
    """
    _, found, results = html.partition(RESULTS_MARKER)
    if not found:
        return {"items": [], "moments": {}, "loose": 0}
    moments: dict[int, list[int]] = {}
    for item_id, body in _MOMENT.findall(results):
        seqs = [int(seq) for seq in _MOMENT_LINK.findall(body)]
        if seqs:
            moments.setdefault(int(item_id), []).extend(seqs)
    items: list[int] = []
    for item_id in _ITEM_LINK.findall(_LOOSE.sub("", results)):
        if int(item_id) not in items:
            items.append(int(item_id))
    return {"items": items, "moments": moments, "loose": results.count(_LOOSE_OPEN)}


def score(pairs: list[dict], results_by_query: dict) -> dict:
    """Where each pair's target landed, and the totals.

    A row's `position` is the target's 1-based place among the page's result
    cards, or None when it is not there; `moments` is how many nested spoken
    moments the page showed for it.
    """
    rows = []
    for pair in pairs:
        result = results_by_query[pair["query"]]
        target = pair["item_id"]
        position = result["items"].index(target) + 1 if target in result["items"] else None
        shown = len(result["moments"].get(target, [])) if position is not None else 0
        rows.append({**{k: pair[k] for k in PAIR_KEYS}, "position": position, "moments": shown})
    found = [r["position"] for r in rows if r["position"] is not None]
    return {
        "rows": rows,
        "pairs": len(rows),
        "queries": len({r["query"] for r in rows}),
        "first_page": len(found),
        "top3": sum(1 for p in found if p <= 3),
        "top10": sum(1 for p in found if p <= 10),
        "top20": sum(1 for p in found if p <= 20),
        "with_moments": sum(1 for r in rows if r["moments"]),
    }


def format_report(scored: dict) -> str:
    lines = []
    for r in scored["rows"]:
        place = "-" if r["position"] is None else str(r["position"])
        lines.append(f"  place {place:>2}  moments {r['moments']}  item {r['item_id']} "
                     f"(meeting {r['meeting_id']}, {r['kind']})  {r['query']}")
    lines.append(
        f"golden: {scored['first_page']} of {scored['pairs']} targets on the first page "
        f"(top 3: {scored['top3']}, top 10: {scored['top10']}, top 20: {scored['top20']}); "
        f"{scored['with_moments']} with spoken moments; {scored['queries']} queries")
    return "\n".join(lines)


def run(pairs: list[dict], fetch) -> dict:
    """Fetch each distinct query's page once, in the order the queries first
    appear, and score the pairs. `fetch(query)` returns the page's HTML."""
    results_by_query: dict[str, dict] = {}
    for pair in pairs:
        if pair["query"] not in results_by_query:
            results_by_query[pair["query"]] = parse_results(fetch(pair["query"]))
    return score(pairs, results_by_query)


def http_fetcher(base_url: str, city: str, delay: float, *, opener=None, sleep=None):
    """The fetcher `main` uses: sleep `delay` seconds, then one GET.

    Raises FetchFailed when the request fails or when the page lacks the
    "Refine search" heading, so an error page is never scored as a miss.
    """
    opener = opener or urllib.request.urlopen
    sleep = sleep or time.sleep
    base = base_url.rstrip("/")

    def fetch(query: str) -> str:
        url = f"{base}/search?{urllib.parse.urlencode({'q': query, 'city': city})}"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        sleep(delay)
        try:
            with opener(request, timeout=TIMEOUT_S) as reply:
                html = reply.read().decode("utf-8", errors="replace")
        except Exception as exc:  # URLError, HTTPError, a timeout, a reset: all one outcome
            raise FetchFailed(url, exc) from exc
        if RESULTS_MARKER not in html:
            raise FetchFailed(url, f'the page has no "{RESULTS_MARKER}" heading, '
                                   "so it is not a search results page")
        return html

    return fetch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ask a deployment of the site the golden queries and report "
                    "where each target agenda item lands on the first results page.")
    parser.add_argument("--base-url", required=True, help="for example https://docket.pub")
    parser.add_argument("--pairs", default=str(DEFAULT_PAIRS),
                        help="JSON list of {query, item_id, meeting_id, kind}")
    parser.add_argument("--city", default="birmingham")
    parser.add_argument("--delay", type=float, default=MIN_DELAY_S,
                        help="seconds to wait before each request; at least 1.0")
    parser.add_argument("--out", metavar="FILE", help="write the per-pair rows here as JSON")
    args = parser.parse_args(argv)
    if not args.delay >= MIN_DELAY_S:
        parser.error(f"--delay must be at least {MIN_DELAY_S} seconds: the check asks a site "
                     "no faster than one request a second. Nothing was fetched.")

    pairs = load_pairs(args.pairs)
    try:
        scored = run(pairs, http_fetcher(args.base_url, args.city, args.delay))
    except FetchFailed as failed:
        print(f"golden: fetch failed for {failed.url}: {failed.error}")
        return 1
    print(format_report(scored))
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(scored["rows"], indent=2) + "\n",
                                          encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
