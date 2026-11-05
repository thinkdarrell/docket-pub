"""The search results page: spoken moments nested under each result, and the transcript lines left over.

Plan: plans/completed/search-finds-what-was-said.md (M7). Cards are written by
hand through `write_cards`; nothing here calls a model.

The page is requested through the Flask test client and read with
`parse_results` from `scripts/golden_search.py`, the parser the golden check
runs against the live site, so the page's markup and the check's reading of
it are held together here.

The integration tier shares one database, so an assertion about the page's
items reads the seeded ids out of what the page lists; rows other files left
behind may sit beside them and change nothing asserted here.

The three row keys M7 adds to `search_transcripts` are used inside the tests,
so the file collects before they exist. The lower list leaves out the lines
nested above and nothing else (`exclude_segments`), which the fixes after the
plan's closing review put in place of M7's `exclude_item_ids`.
"""
import importlib
import importlib.util
import pathlib
import re
from datetime import date

import pytest

from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner
from docket.services import transcripts as tsvc
from docket.web import create_app

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)

MODEL = "test-model"
VERSION = 200
REPO = pathlib.Path(__file__).resolve().parents[2]
EXTERNAL_IDS = ["999981", "999982", "999983"]
URL = "/search?q=new+late+night+ordinance&city=birmingham"

CLUB_TITLE = "An amendment to the Kelvyn Felder Ordinance, the safety plan for clubs"
# 151 characters, and none of the words the tests search for.
PAVING_TITLE = ("A Resolution authorizing the Mayor to execute an agreement for street paving and resurfacing "
                "along several avenues in the northern and eastern districts")

# (seq, text, cluster label, key of the item the segment is filed under or None).
# Item "club" is filed from segment 3 to 8 and its card has the bounds 5 to 9,
# so its snapped range leaves out segments 3 and 4 and reaches one segment
# past its placement, into segment 9, which is filed under "paving". Item
# "paving" is filed from segment 9 on, has a card without bounds, and matches
# none of the query's words. Segments 1, 3, 7, 9, and 11 each hold every word
# of `new late night ordinance`, which is what the lower list requires of a
# line.
SEGMENTS = [
    (0, "good morning and welcome to the council meeting", "S0", None),
    (1, "in public comment the new late night ordinance worries my neighbours", "S5", None),
    (2, "we have a quorum", "S0", None),
    (3, "the new late night ordinance parade was a joy", "S2", "club"),
    (4, "congratulations to the city on the parade", "S2", "club"),
    (5, "item fourteen an ordinance on late hours", "S1", "club"),
    (6, "late night establishments must keep camera footage", "S3", "club"),
    (7, "this new late night ordinance keeps footage thirty days", "S3", "club"),
    (8, "the ordinance passes", "S0", "club"),
    (9, "the new late night ordinance is adopted and we move on", "S0", "paving"),
    (10, "item fifteen street paving", "S1", "paving"),
    (11, "unlike the new late night ordinance <b>paving</b> is simple", "S3", "paving"),
    (12, "the resolution passes", "S0", "paving"),
]
# Cluster label -> (display name, confidence). S2 has no speaker row.
SPEAKERS = {"S0": ("Madam President", None), "S1": ("Maybe Clerk", 0.3),
            "S3": ("Darrell O'Quinn", 0.95), "S5": ("Maybe Resident", 0.3)}

# The crowded meeting: twelve lines that hold every word of the query, filed
# under the item the search returns, then one such line outside any item with
# the same words and a later seq, so it sorts after all twelve.
CROWD_LINE = "the new late night ordinance again"
CROWD_SEGMENTS = [(seq, CROWD_LINE, "S0", "club") for seq in range(12)] + [(12, CROWD_LINE, "S0", None)]


def _golden():
    spec = importlib.util.spec_from_file_location("golden_search", REPO / "scripts" / "golden_search.py")
    golden = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(golden)
    return golden


def _delete_all():
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE external_id = ANY(%s)", [EXTERNAL_IDS])


@pytest.fixture(scope="module", autouse=True)
def ensure_041_function():
    """Install 041's trigger function before this file's tests.

    `test_013_up_down_up_cycle` in `tests/integration/test_migration_013.py`
    leaves the function at migration 013's body for every file that runs
    after it, and this file sorts after it. 041's `SQL_UP` is idempotent.
    """
    m041 = importlib.import_module("docket.migrations.041_search_cards")
    with db() as conn:
        runner.apply_migrations(conn)
        with conn.cursor() as cur:
            cur.execute(m041.SQL_UP)


def _install(external_id: str, meeting_date: date, titles: dict[str, str], segments: list[tuple],
             speakers: dict | None = None) -> dict:
    """A Birmingham meeting with one item per key and, when it has segments, a public transcript.

    A segment's start is ten times its seq and it lasts nine seconds.
    """
    out: dict = {}
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
        muni = cur.fetchone()["id"]
        cur.execute("""INSERT INTO meetings (municipality_id, title, meeting_date, external_id, video_url)
                       VALUES (%s, 'Nested page test', %s, %s, 'https://x/v') RETURNING id""",
                    [muni, meeting_date, external_id])
        mid = out["meeting_id"] = cur.fetchone()["id"]
        cur.execute("INSERT INTO processing_status (meeting_id) VALUES (%s)", [mid])
        for number, (key, title) in enumerate(titles.items(), 1):
            cur.execute("INSERT INTO agenda_items (meeting_id, item_number, title) VALUES (%s, %s, %s) RETURNING id",
                        [mid, str(number), title])
            out[key] = cur.fetchone()["id"]
        if not segments:
            return out
        cur.execute("""INSERT INTO transcripts (meeting_id, status, uploaded_at)
                       VALUES (%s, 'events_extracted', now()) RETURNING id, uploaded_at""", [mid])
        tr = cur.fetchone()
        out["transcript_id"], out["uploaded_at"] = tr["id"], tr["uploaded_at"]
        speaker_ids = {}
        for cluster, (name, confidence) in (speakers or {}).items():
            cur.execute("""INSERT INTO transcript_speakers (meeting_id, cluster_label, display_name, confidence)
                           VALUES (%s, %s, %s, %s) RETURNING id""", [mid, cluster, name, confidence])
            speaker_ids[cluster] = cur.fetchone()["id"]
        for seq, text, cluster, key in segments:
            cur.execute("""INSERT INTO transcript_segments (transcript_id, seq, start_s, end_s, text, cluster_label,
                                                            speaker_id, agenda_item_id, assignment_method)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        [tr["id"], seq, seq * 10.0, seq * 10.0 + 9.0, text, cluster, speaker_ids.get(cluster),
                         out.get(key), "index_point" if key else None])
    return out


def _write_cards(inst: dict, cards: dict[str, tuple[tuple[int, int] | None, str]]) -> None:
    """Replace the transcript's cards: per item key, its bounds (or None) and its weight-B search text."""
    rows = []
    for key, (pair, search_b) in cards.items():
        start, end = pair if pair else (None, None)
        rows.append({"item_id": inst[key], "discussed": True, "start_seq": start, "end_seq": end,
                     "start_s": None if start is None else start * 10.0,
                     "end_s": None if end is None else end * 10.0 + 9.0,
                     "card": {"aliases": []}, "search_b": search_b, "search_c": ""})
    store = importlib.import_module("docket.ai.transcripts.cards")
    assert store.write_cards(inst["transcript_id"], inst["uploaded_at"], rows,
                             model=MODEL, prompt_version=VERSION) == len(rows)


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def seeded():
    """One meeting, two items, a transcript, and both items' cards; only "club" answers the query."""
    _delete_all()
    inst = _install("999981", date(2026, 10, 27), {"club": CLUB_TITLE, "paving": PAVING_TITLE}, SEGMENTS, SPEAKERS)
    _write_cards(inst, {"club": ((5, 9), "late night establishment rules"), "paving": (None, "street resurfacing")})
    yield inst
    _delete_all()


@pytest.fixture
def crowded():
    """One meeting whose returned item has twelve matching lines filed under it and one such line outside any item."""
    _delete_all()
    inst = _install("999983", date(2026, 10, 27), {"club": CLUB_TITLE}, CROWD_SEGMENTS)
    _write_cards(inst, {"club": (None, "late night establishment rules")})
    yield inst
    _delete_all()


@pytest.fixture
def long_list():
    """One result with three matching lines filed under it, then twenty-five matching lines outside any item."""
    _delete_all()
    segments = ([(seq, CROWD_LINE, "S0", "club") for seq in range(3)]
                + [(seq, CROWD_LINE, "S0", None) for seq in range(3, 28)])
    inst = _install("999983", date(2026, 10, 27), {"club": CLUB_TITLE}, segments)
    _write_cards(inst, {"club": (None, "late night establishment rules")})
    yield inst
    _delete_all()


def _get(client, url: str) -> str:
    resp = client.get(url)
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def _anchor(inst: dict, seq: int) -> str:
    return f'/al/birmingham/meetings/{inst["meeting_id"]}/transcript/#t-{seq}"'


def _lower(html: str) -> str:
    """The part of the page from the lower list's heading on."""
    assert "Also said at meetings" in html
    return html[html.index("Also said at meetings"):]


def _lower_line(html: str, inst: dict, seq: int) -> str:
    """The lower list's `<li>` for one segment of the seeded meeting."""
    for line in re.findall(r'<li class="search-transcript-hit".*?</li>', html, re.DOTALL):
        if _anchor(inst, seq) in line:
            return line
    raise AssertionError(f"segment {seq} is not in the lower list")


# --- What the page nests --------------------------------------------------------------------------------


def test_the_carded_item_is_a_result_and_the_item_it_does_not_return_is_not(seeded, client):
    page = _golden().parse_results(_get(client, URL))
    assert seeded["club"] in page["items"]
    assert seeded["paving"] not in page["items"]


def test_the_results_moments_are_segments_inside_its_bounds(seeded, client):
    page = _golden().parse_results(_get(client, URL))
    seqs = page["moments"].get(seeded["club"])
    assert seqs, "no spoken moment was nested under the carded item"
    assert len(seqs) == 3 and seqs == sorted(seqs)
    assert set(seqs) <= {5, 6, 7, 8, 9}
    # The two lines inside the bounds that hold every counted word lead.
    assert {7, 9} <= set(seqs)


def test_a_line_filed_under_the_item_but_outside_its_bounds_is_listed_below_and_not_nested(seeded, client):
    """Segment 3 holds every word and is filed under the item; the card says the item starts at segment 5."""
    html = _get(client, URL)
    assert 3 not in _golden().parse_results(html)["moments"][seeded["club"]]
    assert html.count(_anchor(seeded, 3)) == 1
    line = _lower_line(html, seeded, 3)
    assert f'during <a class="link" href="/al/birmingham/items/{seeded["club"]}/">' in line


def test_a_line_inside_a_results_bounds_is_not_nested_under_the_result_it_is_filed_under(seeded, client):
    """Both items are results; segment 9 is inside the club card's bounds and filed under paving, which has none."""
    html = _get(client, "/search?q=late+night+ordinance+paving&city=birmingham")
    page = _golden().parse_results(html)
    assert seeded["club"] in page["items"] and seeded["paving"] in page["items"]
    assert 9 in page["moments"][seeded["club"]]
    assert page["moments"][seeded["paving"]] == [10, 11]
    assert html.count(_anchor(seeded, 9)) == 1


def test_each_moment_links_to_its_segment_on_the_transcript_page(seeded, client):
    html = _get(client, URL)
    moments = re.findall(r'<li class="search-moment" data-item-id="(\d+)">(.*?)</li>', html, re.DOTALL)
    ours = [body for item_id, body in moments if int(item_id) == seeded["club"]]
    assert len(ours) == 3
    seqs = _golden().parse_results(html)["moments"][seeded["club"]]
    for body, seq in zip(ours, seqs, strict=True):
        assert f'href="{_anchor(seeded, seq)}' in body
        assert re.search(r"<mark>\w+</mark>", body), "a moment shows the transcript's words with the match marked"


def test_a_moment_carries_its_time_and_a_confident_speaker_only(seeded, client):
    html = _get(client, URL)
    moments = {}
    for item_id, body in re.findall(r'<li class="search-moment" data-item-id="(\d+)">(.*?)</li>', html, re.DOTALL):
        if int(item_id) == seeded["club"]:
            moments[int(re.search(r'#t-(\d+)"', body).group(1))] = body
    # Segment 7 starts at 70 seconds and is said by a speaker the site is confident of.
    assert "1:10" in moments[7] and "Quinn:</strong>" in moments[7]
    # Segment 9's speaker has no confidence recorded, which is a resolved name.
    assert "Madam President:</strong>" in moments[9]
    # A name the site is not confident of never reaches the page, nested or below.
    assert "Maybe Clerk" not in html and "Maybe Resident" not in html


def test_the_moments_sit_under_the_results_card_and_are_labelled(seeded, client):
    html = _get(client, URL)
    card = html.index(f'id="item-{seeded["club"]}"')
    moments = html.index('<ul class="search-moments"')
    assert card < moments < html.index("Also said at meetings")
    assert "What was said at the meeting · machine transcript" in html


# --- What the page says it searches ---------------------------------------------------------------------


def test_the_page_says_what_it_searches(seeded, client):
    html = _get(client, URL)
    assert "Search · agenda items and what was said" in html
    assert "Full-text search · agenda items" not in html
    assert "machine transcript" in html
    assert "Search agenda items and what was said…" in html
    assert "Refine search" in html


def test_the_page_without_a_query_says_what_a_search_reads(client):
    html = _get(client, "/search")
    assert "Search · agenda items and what was said" in html
    assert ("Type a query to search agenda items, dollar amounts, topic tags, "
            "and what was said at meetings that have a transcript.") in html
    assert "where a meeting has a machine transcript, what was said about them" in html
    assert "results that match all of your words come first, then results that match most of them" in html
    assert "Search agenda item titles and descriptions across every indexed meeting." not in html
    assert "search-moment" not in html


# --- The lower list -------------------------------------------------------------------------------------


def test_the_lower_list_comes_after_the_results_and_keeps_its_eyebrow(seeded, client):
    html = _get(client, URL)
    assert html.index(">Results<") < html.index("From transcripts") < html.index("Also said at meetings")
    assert "speaker:name" in _lower(html)
    assert ">What was said<" not in html


def test_a_line_outside_any_item_says_so(seeded, client):
    line = _lower_line(_get(client, URL), seeded, 1)
    assert "outside any agenda item · " in line
    assert "during" not in line


def test_a_line_of_an_item_the_search_did_not_return_names_that_item(seeded, client):
    html = _get(client, URL)
    line = _lower_line(html, seeded, 11)
    link = re.search(r'during <a class="link" href="/al/birmingham/items/(\d+)/">(.*?)</a> · ', line, re.DOTALL)
    assert link, line
    assert int(link.group(1)) == seeded["paving"]
    # The title is cut to 90 characters; the whole of it is 151.
    assert len(link.group(2)) <= 90 and link.group(2).startswith("A Resolution authorizing the Mayor")
    assert PAVING_TITLE not in line
    # The item named beside a line is not a result, and the golden check does not read it as one.
    assert seeded["paving"] not in _golden().parse_results(html)["items"]


def test_markup_in_a_transcript_line_is_escaped_on_the_page(seeded, client):
    html = _get(client, URL)
    assert "<b>paving</b>" not in html
    assert "&lt;b&gt;paving&lt;/b&gt;" in _lower_line(html, seeded, 11)


def test_a_line_already_nested_is_not_repeated_in_the_lower_list(seeded, client):
    """Segment 9 is filed under an item the search did not return, so only the route can leave it out."""
    html = _get(client, URL)
    assert 9 in _golden().parse_results(html)["moments"][seeded["club"]]
    assert html.count(_anchor(seeded, 9)) == 1
    assert _anchor(seeded, 9) not in _lower(html)
    # Segment 7 is nested too, and is filed under the result itself.
    assert html.count(_anchor(seeded, 7)) == 1


def test_every_matching_line_of_a_result_is_nested_or_listed_below(crowded, client):
    """Twelve matching lines under the returned item and one outside any item: each is on the page once."""
    html = _get(client, URL)
    page = _golden().parse_results(html)
    assert crowded["club"] in page["items"]
    nested = page["moments"][crowded["club"]]
    assert nested == [0, 1, 2]
    lower = _lower(html)
    # The three nested lines are left out ahead of the list's limit of ten, so the other ten all fit.
    assert [seq for seq in range(13) if _anchor(crowded, seq) in lower] == list(range(3, 13))
    assert all(html.count(_anchor(crowded, seq)) == 1 for seq in range(13))
    assert "outside any agenda item · " in _lower_line(html, crowded, 12)
    assert f'/al/birmingham/items/{crowded["club"]}/' in _lower_line(html, crowded, 3)


def test_search_transcripts_leaves_out_the_named_segments_ahead_of_its_limit(crowded):
    q = "new late night ordinance"

    def ours(rows: list[dict]) -> list[int]:
        return [r["seq"] for r in rows if r["meeting_id"] == crowded["meeting_id"]]

    # With nothing left out the first ten of the thirteen fill the list.
    assert ours(tsvc.search_transcripts(q, municipality_slug="birmingham", speaker=None, limit=10)) == list(range(10))
    nested = [(crowded["meeting_id"], seq) for seq in (0, 1, 2)]
    rows = tsvc.search_transcripts(q, municipality_slug="birmingham", speaker=None, limit=10,
                                   exclude_segments=nested)
    assert ours(rows) == list(range(3, 13))
    # The same seq of another meeting leaves nothing of this one out.
    rows = tsvc.search_transcripts(q, municipality_slug="birmingham", speaker=None, limit=100,
                                   exclude_segments=[(crowded["meeting_id"] + 1000000, 0)])
    assert ours(rows) == list(range(13))
    # An empty list and None both mean nothing is left out.
    for nothing in ([], None):
        rows = tsvc.search_transcripts(q, municipality_slug="birmingham", speaker=None, limit=100,
                                       exclude_segments=nothing)
        assert ours(rows) == list(range(13))


def test_search_transcripts_rows_name_their_item_and_hide_an_unsure_speaker(seeded):
    rows = tsvc.search_transcripts("new late night ordinance", municipality_slug="birmingham", speaker=None,
                                   limit=100)
    by_seq = {r["seq"]: r for r in rows if r["meeting_id"] == seeded["meeting_id"]}
    assert sorted(by_seq) == [1, 3, 7, 9, 11]
    assert by_seq[1]["agenda_item_id"] is None and by_seq[1]["item_title"] is None
    assert by_seq[11]["agenda_item_id"] == seeded["paving"] and by_seq[11]["item_title"] == PAVING_TITLE
    assert by_seq[7]["agenda_item_id"] == seeded["club"] and by_seq[7]["item_title"] == CLUB_TITLE
    # Confidence 0.3 is below the floor: the name is withheld. 0.95 and an absent confidence keep theirs.
    assert by_seq[1]["speaker_name"] is None and float(by_seq[1]["speaker_confidence"]) == pytest.approx(0.3)
    assert by_seq[7]["speaker_name"] == "Darrell O'Quinn"
    assert by_seq[9]["speaker_name"] == "Madam President" and by_seq[9]["speaker_confidence"] is None
    # Every key the function returned before M7 is still there.
    assert {"meeting_id", "municipality_slug", "meeting_title", "meeting_date", "seq", "start_s", "speaker_name",
            "rank", "headline", "anchor_url"} <= set(by_seq[1])


# --- The lower list's own pages -------------------------------------------------------------------------


def _lower_seqs(html: str, inst: dict, upto: int) -> list[int]:
    lower = _lower(html)
    return [seq for seq in range(upto) if _anchor(inst, seq) in lower]


def test_the_lower_list_has_pages_of_its_own_cut_from_one_list(long_list, client):
    """Twenty-five lines below one result: ten a page, each line on exactly one of the list's pages."""
    pages = [_get(client, URL + (f"&tpage={n}" if n > 1 else "")) for n in (1, 2, 3)]
    for html in pages:
        assert _golden().parse_results(html)["moments"][long_list["club"]] == [0, 1, 2]
    assert _lower_seqs(pages[0], long_list, 28) == list(range(3, 13))
    assert _lower_seqs(pages[1], long_list, 28) == list(range(13, 23))
    assert _lower_seqs(pages[2], long_list, 28) == list(range(23, 28))


def test_the_lower_lists_links_go_to_its_next_and_previous_page_and_keep_the_query(long_list, client):
    first, second, third = (_get(client, URL + (f"&tpage={n}" if n > 1 else "")) for n in (1, 2, 3))
    more = re.search(r'<a class="link" href="([^"]*)">More lines', first)
    assert more, "the first page of the list links to the second"
    href = more.group(1).replace("&amp;", "&")
    assert "tpage=2" in href and "q=new" in href and "city=birmingham" in href and href.endswith("#also-said")
    assert _lower_seqs(_get(client, href.split("#")[0]), long_list, 28) == list(range(13, 23))
    assert "Earlier lines" not in first
    assert "Earlier lines" in second and "More lines" in second
    assert "Earlier lines" in third and "More lines" not in third
    assert 'id="also-said"' in first


def test_a_list_that_fits_on_one_page_has_no_links(crowded, client):
    html = _get(client, URL)
    assert "More lines" not in html and "Earlier lines" not in html


def test_the_lower_list_does_not_move_with_the_results_page(long_list, client):
    """Page two of the results has no result, so nothing is nested and the list starts at its top."""
    html = _get(client, URL + "&page=2")
    assert _golden().parse_results(html)["items"] == []
    assert _lower_seqs(html, long_list, 28) == list(range(10))


def test_the_results_pager_does_not_carry_the_lists_page(long_list, client):
    """Twenty newer results fill page one, so the results have a Next link; it leaves `tpage` behind."""
    titles = {f"filler{n}": f"A late night ordinance, filler number {n}" for n in range(20)}
    _install("999982", date(2026, 10, 28), titles, [])
    html = _get(client, URL + "&tpage=2")
    nxt = re.search(r'<a class="link" href="([^"]*)">Next', html)
    assert nxt, "the results have a second page"
    assert "page=2" in nxt.group(1) and "tpage" not in nxt.group(1)


def test_past_the_end_of_the_list_the_page_says_so_and_links_back(long_list, client):
    html = _get(client, URL + "&tpage=9")
    assert long_list["club"] in _golden().parse_results(html)["items"]
    assert "No more transcript lines" in _lower(html)
    assert "Earlier lines" in html and "More lines" not in html
    assert ">No results<" not in html


# --- Other shapes of the request ------------------------------------------------------------------------


def test_a_speaker_only_query_lists_that_speakers_lines_and_no_items(seeded, client):
    html = _get(client, "/search?q=speaker:oquinn&city=birmingham")
    page = _golden().parse_results(html)
    assert page["items"] == [] and page["moments"] == {}
    for seq in (6, 7, 11):
        assert "Quinn:</strong>" in _lower_line(html, seeded, seq)
    assert _anchor(seeded, 8) not in html
    assert "during" in _lower_line(html, seeded, 6)
    assert ">No results<" not in html


def test_a_speaker_token_narrows_the_nested_moments_too(seeded, client):
    page = _golden().parse_results(_get(client, "/search?q=speaker:oquinn+late+night+ordinance&city=birmingham"))
    assert seeded["club"] in page["items"]
    assert page["moments"][seeded["club"]] == [6, 7]


def test_page_two_computes_moments_for_page_twos_items(seeded, client):
    """Twenty newer items that match every word fill page one; the carded item and its moments are on page two."""
    titles = {f"filler{n}": f"A late night ordinance, filler number {n}" for n in range(20)}
    filler = _install("999982", date(2026, 10, 28), titles, [])
    golden = _golden()
    first = golden.parse_results(_get(client, URL))
    assert seeded["club"] not in first["items"]
    assert {filler[k] for k in titles} <= set(first["items"])
    assert seeded["club"] not in first["moments"]
    second = golden.parse_results(_get(client, URL + "&page=2"))
    assert seeded["club"] in second["items"]
    assert {7, 9} <= set(second["moments"][seeded["club"]])


def test_a_query_nothing_matches_still_says_no_results(seeded, client):
    html = _get(client, "/search?q=zzyzxqq&city=birmingham")
    assert ">No results<" in html
    assert "Also said at meetings" not in html and "search-moment" not in html


def test_the_amount_list_has_no_moments(seeded, client):
    html = _get(client, "/search?city=birmingham&order=amount")
    assert "search-moment" not in html and "Also said at meetings" not in html
