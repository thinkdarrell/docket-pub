"""The golden search check (plan search-finds-what-was-said, M1).

`scripts/golden_search.py` asks a deployment of the site the golden queries
and reports where each target item lands. These tests need no database and
make no request: the script is loaded by path, inside each test, so that a
missing script fails the tests that need it and not the collection of the
file.
"""
import functools
import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "golden_search.py"
PAIRS = ROOT / "tests" / "fixtures" / "golden_search" / "queries.json"


@functools.lru_cache(maxsize=1)
def _gs():
    spec = importlib.util.spec_from_file_location("golden_search", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Today's markup: transcript lines first, then the result cards. The masthead
# link above "Refine search" must not be read as a result.
TODAY_PAGE = """
<nav><a href="/al/birmingham/items/11111/">a link in the page chrome</a></nav>
<div class="t-eyebrow">Full-text search · agenda items</div>
<h2 class="feed-title t-display">Refine search</h2>
<form method="get" action="/search"><input type="text" name="q" value="Kelvyn Felder"></form>
<section class="feed">
  <div class="t-eyebrow">From transcripts</div>
  <ul class="search-transcript-hits" style="list-style:none; padding:0;">
    <li class="search-transcript-hit">
      <a class="link" href="/al/birmingham/meetings/2224/transcript/#t-309">
        <span class="t-mono t-meta">1:52:10</span> the <mark>Felder</mark> ordinance
      </a>
      <div class="t-meta">City Council · May 5, 2026 · machine transcript</div>
    </li>
  </ul>
</section>
<section class="feed">
  <div class="notable-list smart-brevity-list smart-brevity-list--regular">
    <article><a class="card-headline"
       href="/al/birmingham/items/58874/">Recall of Ordinance No. 26-50</a>
       <a href="/al/birmingham/items/58874/">Read more</a></article>
    <article><a class="card-headline"
       href="/al/birmingham/items/58824/">Kelvyn Felder Ordinance</a></article>
    <article><a href="/al/hoover/items/42/">An item of another city</a></article>
  </div>
</section>
"""

# The markup M7 implements: result cards first, each with its spoken moments
# nested under it, then the remaining transcript lines, which name the item
# each belongs to.
NESTED_PAGE = """
<nav><a href="/al/birmingham/items/11111/">a link in the page chrome</a></nav>
<div class="t-eyebrow">Search · agenda items and what was said</div>
<h2 class="feed-title t-display">Refine search</h2>
<section class="feed">
  <div class="notable-list smart-brevity-list smart-brevity-list--regular">
    <article><a href="/al/birmingham/items/58824/">Kelvyn Felder Ordinance</a></article>
    <ul class="search-moments" aria-label="What was said">
      <li class="search-moment" data-item-id="58824">
        <a class="link" href="/al/birmingham/meetings/2224/transcript/#t-265">
          <span class="t-mono t-meta">1:45:10</span> Item 14
        </a>
      </li>
      <li class="search-moment" data-item-id="58824">
        <a class="link" href="/al/birmingham/meetings/2224/transcript/#t-309">
          <span class="t-mono t-meta">1:52:10</span>
          <strong>Phil Morton:</strong> <mark>late</mark> <mark>night</mark> establishments
        </a>
      </li>
      <li class="t-meta search-moments-label">What was said at the meeting · machine transcript</li>
    </ul>
    <article><a href="/al/birmingham/items/42399/">An ordinance on late night hours</a></article>
    <article><a href="/al/birmingham/items/58874/">Recall of Ordinance No. 26-50</a></article>
    <ul class="search-moments" aria-label="What was said">
      <li class="search-moment" data-item-id="58874">
        <a class="link" href="/al/birmingham/meetings/2231/transcript/#t-147">
          <span class="t-mono t-meta">1:02:11</span> I want to publicly apologize
        </a>
      </li>
      <li class="t-meta search-moments-label">What was said at the meeting · machine transcript</li>
    </ul>
  </div>
</section>
<section class="feed">
  <div class="t-eyebrow">From transcripts</div>
  <ul class="search-transcript-hits" style="list-style:none; padding:0;">
    <li class="search-transcript-hit">
      <a class="link" href="/al/birmingham/meetings/2231/transcript/#t-12">
        <span class="t-mono t-meta">0:04:02</span> a late night
      </a>
      <div class="t-meta">during <a class="link" href="/al/birmingham/items/60000/">An item the
        query did not return</a> · City Council · May 12, 2026 · machine transcript</div>
    </li>
    <li class="search-transcript-hit">
      <a class="link" href="/al/birmingham/meetings/2231/transcript/#t-400">
        <span class="t-mono t-meta">2:10:00</span> a late night
      </a>
      <div class="t-meta">outside any agenda item · City Council · May 12, 2026 · machine transcript</div>
    </li>
  </ul>
</section>
"""


def _pair(query, item_id, meeting_id=1, kind="user"):
    return {"query": query, "item_id": item_id, "meeting_id": meeting_id, "kind": kind}


def _result(items, moments=None, loose=0):
    return {"items": items, "moments": moments or {}, "loose": loose}


# ── the fixture file ────────────────────────────────────────────────


def test_fixture_holds_45_pairs_and_42_distinct_queries():
    pairs = json.loads(PAIRS.read_text())
    assert len(pairs) == 45
    assert len({p["query"] for p in pairs}) == 42
    for p in pairs:
        assert set(p) == {"query", "item_id", "meeting_id", "kind"}
        assert isinstance(p["item_id"], int) and isinstance(p["meeting_id"], int)
    kinds = [p["kind"] for p in pairs]
    assert {k: kinds.count(k) for k in set(kinds)} == {
        "paraphrase": 18, "spoken": 18, "user": 2, "spec": 7}


def test_fixture_holds_both_targets_of_the_headline_query():
    pairs = json.loads(PAIRS.read_text())
    targets = {(p["item_id"], p["meeting_id"]) for p in pairs
               if p["query"] == "new late night ordinance"}
    assert targets == {(58824, 2224), (58874, 2231)}


def test_load_pairs_reads_the_fixture_and_refuses_a_row_missing_a_key(tmp_path):
    gs = _gs()
    assert len(gs.load_pairs(PAIRS)) == 45
    assert gs.DEFAULT_PAIRS == PAIRS
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"query": "x", "item_id": 1}]))
    with pytest.raises(ValueError):
        gs.load_pairs(bad)


# ── parse_results ───────────────────────────────────────────────────


def test_parse_results_on_todays_markup():
    got = _gs().parse_results(TODAY_PAGE)
    # The chrome link above "Refine search" is ignored, the order of first
    # appearance is kept, a second link to the same item adds nothing, and
    # any city's slug is read.
    assert got["items"] == [58874, 58824, 42]
    assert got["moments"] == {}
    assert got["loose"] == 1


def test_parse_results_on_the_nested_markup():
    got = _gs().parse_results(NESTED_PAGE)
    assert got["items"] == [58824, 42399, 58874]
    assert got["moments"] == {58824: [265, 309], 58874: [147]}
    assert got["loose"] == 2


def test_parse_results_does_not_count_an_item_named_by_a_loose_transcript_line():
    # Item 60000 is linked only from a line of the lower list ("during ...").
    # It is not a result, so it has no position among the results.
    assert 60000 not in _gs().parse_results(NESTED_PAGE)["items"]


def test_parse_results_reads_nothing_from_a_page_without_the_marker():
    got = _gs().parse_results('<a href="/al/birmingham/items/5/">x</a>')
    assert got == {"items": [], "moments": {}, "loose": 0}


# ── score and format_report ─────────────────────────────────────────


def test_score_positions_and_totals():
    gs = _gs()
    pairs = [
        _pair("alpha", 1),             # first
        _pair("alpha", 2),             # the same query's second target, fourth
        _pair("beta", 3),              # eleventh
        _pair("gamma", 4),             # twenty-first: on the page, outside the top 20
        _pair("delta", 5),             # absent
    ]
    results = {
        "alpha": _result([1, 90, 91, 2], moments={1: [7, 9], 2: []}),
        "beta": _result(list(range(100, 110)) + [3]),
        "gamma": _result(list(range(200, 220)) + [4]),
        "delta": _result([300, 301], moments={300: [1]}),
    }
    got = gs.score(pairs, results)
    assert [r["position"] for r in got["rows"]] == [1, 4, 11, 21, None]
    assert [r["moments"] for r in got["rows"]] == [2, 0, 0, 0, 0]
    assert got["pairs"] == 5 and got["queries"] == 4
    assert got["first_page"] == 4
    assert (got["top3"], got["top10"], got["top20"]) == (1, 2, 3)
    assert got["with_moments"] == 1
    assert got["rows"][0]["query"] == "alpha" and got["rows"][0]["item_id"] == 1


def test_format_report_prints_a_line_per_pair_and_the_summary_last():
    gs = _gs()
    pairs = [_pair("alpha", 1, 2224, "spoken"), _pair("delta", 5, 2231, "spec")]
    results = {"alpha": _result([1], moments={1: [7]}), "delta": _result([300])}
    lines = gs.format_report(gs.score(pairs, results)).splitlines()
    assert len(lines) == 3
    assert "alpha" in lines[0] and "item 1 " in lines[0] and "2224" in lines[0]
    assert "delta" in lines[1] and "item 5 " in lines[1] and "spec" in lines[1]
    assert not lines[0].startswith("golden: ")
    assert lines[2] == ("golden: 1 of 2 targets on the first page "
                        "(top 3: 1, top 10: 1, top 20: 1); 1 with spoken moments; 2 queries")


def test_format_report_summary_has_the_plans_shape_for_45_pairs():
    gs = _gs()
    pairs = gs.load_pairs(PAIRS)
    found = {"Kelvyn Felder": [58874, 58824], "26-50": [58874]}
    results = {p["query"]: _result(found.get(p["query"], [])) for p in pairs}
    last = gs.format_report(gs.score(pairs, results)).splitlines()[-1]
    assert last == ("golden: 3 of 45 targets on the first page "
                    "(top 3: 3, top 10: 3, top 20: 3); 0 with spoken moments; 42 queries")


# ── run, the fetcher, and main ──────────────────────────────────────


def test_run_fetches_each_distinct_query_once_in_order():
    gs = _gs()
    asked = []

    def fetch(query):
        asked.append(query)
        return TODAY_PAGE

    pairs = [_pair("Kelvyn Felder", 58824), _pair("Kelvyn Felder", 58874), _pair("26-50", 99)]
    got = gs.run(pairs, fetch)
    assert asked == ["Kelvyn Felder", "26-50"]
    assert [r["position"] for r in got["rows"]] == [2, 1, None]
    assert got["queries"] == 2


class _Reply:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_http_fetcher_builds_the_url_sleeps_first_and_names_itself():
    gs = _gs()
    events = []

    def opener(request, timeout):
        events.append(("open", request.full_url, request.get_header("User-agent"), timeout))
        return _Reply(TODAY_PAGE)

    fetch = gs.http_fetcher("https://docket.pub/", "birmingham", 1.5,
                            opener=opener, sleep=lambda s: events.append(("sleep", s)))
    assert fetch("new late night ordinance") == TODAY_PAGE
    assert events == [
        ("sleep", 1.5),
        ("open", "https://docket.pub/search?q=new+late+night+ordinance&city=birmingham",
         "docket-golden-search/1.0 (operator's own check)", 60),
    ]


def test_http_fetcher_reports_a_failed_request_and_a_page_that_is_not_search():
    gs = _gs()

    def refused(request, timeout):
        raise OSError("connection refused")

    fetch = gs.http_fetcher("http://localhost:1", "birmingham", 1.0,
                            opener=refused, sleep=lambda s: None)
    with pytest.raises(gs.FetchFailed) as failed:
        fetch("26-50")
    assert failed.value.url == "http://localhost:1/search?q=26-50&city=birmingham"
    assert "connection refused" in str(failed.value)

    fetch = gs.http_fetcher("http://localhost:1", "birmingham", 1.0,
                            opener=lambda request, timeout: _Reply("<h1>Maintenance</h1>"),
                            sleep=lambda s: None)
    with pytest.raises(gs.FetchFailed) as failed:
        fetch("26-50")
    assert "Refine search" in str(failed.value)


def test_main_refuses_a_delay_under_one_second_without_fetching(monkeypatch, capsys):
    gs = _gs()

    def no_request(*args, **kwargs):
        raise AssertionError("a request was made")

    monkeypatch.setattr(gs.urllib.request, "urlopen", no_request)
    monkeypatch.setattr(gs.time, "sleep", no_request)
    with pytest.raises(SystemExit) as stopped:
        gs.main(["--base-url", "https://docket.pub", "--delay", "0.5"])
    assert stopped.value.code == 2
    assert "--delay" in capsys.readouterr().err


def test_main_prints_the_report_writes_the_rows_and_exits_zero(monkeypatch, capsys, tmp_path):
    gs = _gs()
    pairs = tmp_path / "pairs.json"
    pairs.write_text(json.dumps([_pair("Kelvyn Felder", 58824, 2224, "spec"),
                                 _pair("26-50", 99, 2231, "spec")]))
    out = tmp_path / "rows.json"
    monkeypatch.setattr(gs.urllib.request, "urlopen",
                        lambda request, timeout: _Reply(TODAY_PAGE))
    monkeypatch.setattr(gs.time, "sleep", lambda s: None)
    code = gs.main(["--base-url", "https://docket.pub", "--pairs", str(pairs), "--out", str(out)])
    assert code == 0  # a measurement, not a gate: one target was missed
    printed = capsys.readouterr().out.splitlines()
    assert printed[-1] == ("golden: 1 of 2 targets on the first page "
                           "(top 3: 1, top 10: 1, top 20: 1); 0 with spoken moments; 2 queries")
    rows = json.loads(out.read_text())
    assert [(r["query"], r["item_id"], r["position"]) for r in rows] == [
        ("Kelvyn Felder", 58824, 2), ("26-50", 99, None)]


def test_main_reports_a_failed_fetch_and_exits_one(monkeypatch, capsys, tmp_path):
    gs = _gs()

    def refused(request, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(gs.urllib.request, "urlopen", refused)
    monkeypatch.setattr(gs.time, "sleep", lambda s: None)
    code = gs.main(["--base-url", "http://localhost:1"])
    assert code == 1
    assert capsys.readouterr().out.startswith(
        "golden: fetch failed for http://localhost:1/search?q=new+hotel+and+condos+redmont+park"
        "&city=birmingham: ")
