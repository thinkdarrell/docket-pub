"""Ranked matching: which agenda items a typed query returns, and in what order.

Plan: plans/completed/search-finds-what-was-said.md (M6). Cards are written by
hand through `write_cards`; nothing here calls a model.

The rows are shaped like the five the plan's author ran the ranking SQL on
(Artifacts and Notes, "The ranking shapes"): an item found through its card,
a 2013 item holding every typed word in its title, an item holding two of
the words, an item repeating one of them, and the item that recalls an
ordinance by its number.

The integration tier shares one database, so every assertion about order
reads the seeded items out of a longer list; rows other files left behind
may sit between them and change nothing asserted here.

`parse_query`, `STOP_WORDS`, and `build_search_sql` are read inside the
tests, not at the top of this file, so the file collects before they exist.
"""
import importlib
import importlib.util
import pathlib
from datetime import date

import pytest

from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner
from docket.models.agenda import AgendaItem
from docket.services import query
from docket.web import create_app

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)

MODEL = "test-model"
VERSION = 200
REPO = pathlib.Path(__file__).resolve().parents[2]

# key -> (external id, meeting date, hidden, title). One item per meeting, so
# each item has its own date.
ROWS = {
    "felder": ("999971", date(2026, 5, 5), False,
               "An Ordinance to amend the Kelvyn Felder Ordinance, the safety plan for clubs"),
    "old": ("999972", date(2013, 6, 4), False, "An ordinance on new late night hours"),
    "nno": ("999973", date(2025, 8, 5), False, "National Night Out proclamation late"),
    "rezone": ("999974", date(2026, 10, 20), False,
               "An Ordinance to rezone 26 lots and 50 acres; ordinance ordinance"),
    "recall": ("999975", date(2026, 5, 12), False,
               "A recall from the Mayor of Ordinance No. 26-50, the Kelvyn Felder Ordinance"),
    "hidden": ("999976", date(2026, 6, 2), True, "An ordinance on new late night hours for clubs"),
}
EXTERNAL_IDS = [row[0] for row in ROWS.values()]

# The card of the "felder" item: the alias and the name variant go to
# `search_b` (weight B), a spoken detail to `search_c` (weight C). Its title
# holds none of "late", "night", or "Kelvin".
FELDER_B = "late night establishment rules . Kelvin Felder Ordinance"
FELDER_C = "Establishments must have cameras with footage kept for up to 30 days."


def _sqm():
    return importlib.import_module("docket.services.search_query")


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


@pytest.fixture
def seeded():
    """Six Birmingham meetings of one item each, one of them hidden; the "felder" meeting has a public transcript."""
    _delete_all()
    ids: dict = {}
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
        muni = cur.fetchone()["id"]
        for key, (external_id, meeting_date, hidden, title) in ROWS.items():
            cur.execute("""INSERT INTO meetings (municipality_id, title, meeting_date, external_id, video_url, is_hidden)
                           VALUES (%s, 'Ranking test', %s, %s, 'https://x/v', %s) RETURNING id""",
                        [muni, meeting_date, external_id, hidden])
            mid = cur.fetchone()["id"]
            cur.execute("INSERT INTO processing_status (meeting_id) VALUES (%s)", [mid])
            cur.execute("INSERT INTO agenda_items (meeting_id, item_number, title) VALUES (%s, '1', %s) RETURNING id",
                        [mid, title])
            ids[key] = cur.fetchone()["id"]
            if key == "felder":
                cur.execute("""INSERT INTO transcripts (meeting_id, status, uploaded_at)
                               VALUES (%s, 'events_extracted', now()) RETURNING id, uploaded_at""", [mid])
                tr = cur.fetchone()
                ids["transcript_id"], ids["uploaded_at"] = tr["id"], tr["uploaded_at"]
                cur.execute("""INSERT INTO transcript_segments (transcript_id, seq, start_s, end_s, text, cluster_label,
                                                                agenda_item_id, assignment_method)
                               VALUES (%s, 0, 10, 19, 'item fourteen the felder ordinance', 'S0', %s, 'index_point')""",
                            [tr["id"], ids[key]])
    yield ids
    _delete_all()


def _write_card(s: dict, search_b: str = FELDER_B, search_c: str = FELDER_C) -> None:
    cards = importlib.import_module("docket.ai.transcripts.cards")
    row = {"item_id": s["felder"], "discussed": True, "start_seq": None, "end_seq": None, "start_s": None,
           "end_s": None, "card": {"aliases": []}, "search_b": search_b, "search_c": search_c}
    assert cards.write_cards(s["transcript_id"], s["uploaded_at"], [row], model=MODEL, prompt_version=VERSION) == 1


@pytest.fixture
def carded(seeded):
    """The seeded rows with the "felder" item's card written."""
    _write_card(seeded)
    return seeded


def _found(s: dict, q: str, **kwargs) -> list[str]:
    """The keys of the seeded items the search returns, in the order it returns them."""
    kwargs.setdefault("municipality_slug", "birmingham")
    kwargs.setdefault("limit", 500)
    by_id = {v: k for k, v in s.items() if k in ROWS}
    return [by_id[it.id] for it in query.search_agenda_items(q, **kwargs) if it.id in by_id]


def _rank(item_id: int, *words: str) -> float:
    """`ts_rank` of the item against the any-word query, as the search computes it."""
    ors = " || ".join(["plainto_tsquery('english', %s)"] * len(words))
    with db_cursor() as cur:
        cur.execute(f"SELECT ts_rank(search_vector, {ors}) AS rank FROM agenda_items WHERE id = %s",
                    [*words, item_id])
        return cur.fetchone()["rank"]


# --- The headline query -----------------------------------------------------------------------


def test_loose_words_find_the_item_through_its_card_ahead_of_the_2013_item(carded):
    """Both hold all three words, so the recency word decides: the 2026 item, then the 2013 one."""
    assert _found(carded, "new late night ordinance") == ["felder", "old", "nno", "rezone", "recall"]


def test_without_the_card_the_item_drops_below_the_2013_item(seeded):
    found = _found(seeded, "new late night ordinance")
    assert found[:2] == ["old", "nno"]
    assert found.index("felder") > found.index("old")
    assert sorted(found) == sorted(["old", "nno", "felder", "rezone", "recall"]), "one word is enough to be found"


def test_removing_the_card_drops_the_item_again(carded):
    cards = importlib.import_module("docket.ai.transcripts.cards")
    assert _found(carded, "new late night ordinance")[0] == "felder"

    assert cards.write_cards(carded["transcript_id"], carded["uploaded_at"], [], model=MODEL,
                             prompt_version=VERSION) == 0

    assert _found(carded, "new late night ordinance")[:2] == ["old", "nno"]


def test_without_a_recency_word_the_same_tier_is_ordered_by_rank(carded):
    """Both lead items match three words; the 2013 item holds them in its title and ranks higher."""
    words = ("late", "night", "ordinance")
    assert _rank(carded["old"], *words) > _rank(carded["felder"], *words)

    found = _found(carded, "late night ordinance")

    assert found[:3] == ["old", "felder", "nno"]


@pytest.mark.parametrize("word", ["new", "recent", "latest", "Latest"])
def test_each_recency_word_is_a_preference_and_never_a_requirement(carded, word):
    """None of the five titles the query returns holds "recent" or "latest", and three do not hold "new"."""
    assert _found(carded, f"{word} late night ordinance") == ["felder", "old", "nno", "rezone", "recall"]


def test_among_equal_coverage_a_recency_word_puts_the_newer_meeting_first(carded):
    """All four hold the one word. Without a recency word rank decides, with one the date does.

    The "felder" item (2026-05-05) says ordinance twice in its title and once
    in its card, the "recall" item (2026-05-12) twice in its title, so rank
    puts "felder" ahead and the date puts "recall" ahead.
    """
    assert _rank(carded["felder"], "ordinance") > _rank(carded["recall"], "ordinance")

    assert _found(carded, "ordinance") == ["rezone", "felder", "recall", "old"]
    assert _found(carded, "latest ordinance") == ["rezone", "recall", "felder", "old"], \
        "newest meeting first: 2026-10-20, 2026-05-12, 2026-05-05, 2013-06-04"


# --- Coverage ----------------------------------------------------------------------------------


def test_an_item_matching_more_words_leads_one_that_repeats_a_single_word(carded):
    """The "rezone" title says ordinance three times; "nno" holds two different words of the query once each."""
    found = _found(carded, "late night ordinance")
    assert found.index("nno") < found.index("rezone")


def test_one_matching_word_is_enough_and_no_matching_word_is_not(carded):
    assert _found(carded, "proclamation zeppelin") == ["nno"]
    assert _found(carded, "zeppelin dirigible") == []


def test_a_quoted_phrase_needs_its_words_side_by_side(carded):
    assert _found(carded, '"night hours"') == ["old"]
    assert _found(carded, '"hours night"') == []
    assert _found(carded, '"late night"') == ["old", "felder"], "the title's phrase outranks the card's"
    assert _found(carded, '"night late"') == []


def test_an_excluded_word_removes_its_items(carded):
    assert "rezone" in _found(carded, "ordinance")
    found = _found(carded, "ordinance -rezone")
    assert "rezone" not in found
    assert sorted(found) == sorted(["felder", "old", "recall"])


def test_an_excluded_phrase_removes_the_items_holding_its_words_side_by_side(carded):
    assert sorted(_found(carded, "ordinance")) == sorted(["felder", "old", "recall", "rezone"])
    assert sorted(_found(carded, 'ordinance -"late night"')) == sorted(["recall", "rezone"])
    # The same words in the other order are in no item side by side, so nothing is removed.
    assert sorted(_found(carded, 'ordinance -"night late"')) == sorted(["felder", "old", "recall", "rezone"])


# --- Identifiers -------------------------------------------------------------------------------


def test_an_identifier_returns_the_item_that_carries_it_and_not_one_holding_its_numbers_apart(carded):
    assert _found(carded, "26-50") == ["recall"]


def test_an_item_carrying_the_identifier_leads_items_matching_more_words(carded):
    """The "rezone" title holds two of the typed words, the "recall" title one and the number."""
    assert _found(carded, "ordinance rezone 26-50")[:2] == ["recall", "rezone"]
    assert _found(carded, "ordinance rezone")[0] == "rezone"


# --- Names as the transcript spells them ---------------------------------------------------------


def test_a_name_variant_in_the_card_finds_an_item_whose_title_spells_it_otherwise(seeded):
    assert _found(seeded, "Kelvin") == [], "no title says Kelvin"

    _write_card(seeded)

    assert _found(seeded, "Kelvin") == ["felder"]
    assert _found(seeded, "Kelvin Felder") == ["felder", "recall"], "two words through the card, then one"


def test_a_spoken_detail_in_the_card_finds_the_item(carded):
    assert _found(carded, "camera footage 30 days") == ["felder"]


# --- What does not change -----------------------------------------------------------------------


def test_a_hidden_meetings_item_is_absent(carded):
    with db_cursor() as cur:
        cur.execute("""SELECT search_vector @@ plainto_tsquery('english', 'late night ordinance') AS hit
                         FROM agenda_items WHERE id = %s""", [carded["hidden"]])
        assert cur.fetchone()["hit"], "the hidden item holds every word"
    for q in ("late night ordinance", "new late night ordinance", "clubs"):
        assert "hidden" not in _found(carded, q)
        assert "hidden" not in _found(carded, q, municipality_slug=None)


def test_the_city_scopes_the_search(carded):
    assert _found(carded, "late night ordinance", municipality_slug=None)[:3] == ["old", "felder", "nno"]
    assert _found(carded, "late night ordinance", municipality_slug="no-such-city") == []


def test_limit_and_offset_page_through_the_ordered_list_without_repeats(carded):
    q = "new late night ordinance"
    whole = [it.id for it in query.search_agenda_items(q, municipality_slug="birmingham", limit=500)]
    assert len(whole) >= 5 and len(set(whole)) == len(whole)

    paged = []
    for offset in range(0, len(whole) + 2, 2):
        page = query.search_agenda_items(q, municipality_slug="birmingham", limit=2, offset=offset)
        assert len(page) <= 2
        paged.extend(it.id for it in page)

    assert paged == whole


def test_a_result_is_an_agenda_item_with_its_meeting_and_city(carded):
    results = [it for it in query.search_agenda_items("new late night ordinance", municipality_slug="birmingham",
                                                      limit=500) if it.id == carded["felder"]]
    assert len(results) == 1
    item = results[0]
    assert isinstance(item, AgendaItem)
    assert item.title == ROWS["felder"][3]
    assert item.meeting_title == "Ranking test"
    assert item.meeting_date == date(2026, 5, 5)
    assert item.municipality_slug == "birmingham" and item.municipality_name
    assert item.badges == []


@pytest.mark.parametrize("q", ["", "   ", "the of", "-zoning", "what are the"])
def test_a_query_with_no_units_returns_nothing(carded, q):
    assert query.search_agenda_items(q, municipality_slug="birmingham") == []
    assert query.search_agenda_items(q) == []


def test_a_stop_word_inside_a_token_reaches_the_server_and_matches_nothing(carded):
    """`it's` is not in the stop list; the server splits it into two stop words and drops the query."""
    assert _found(carded, "it's") == []
    assert _found(carded, "it's proclamation") == ["nno"]


# --- The statement itself -------------------------------------------------------------------------


def test_the_statement_runs_on_a_callers_own_connection(carded):
    """The scale check times the statement on the connection that holds its uncommitted rows."""
    sq = _sqm().parse_query("new late night ordinance")
    sql, params = query.build_search_sql(sq, "birmingham", 500, 0)
    assert isinstance(params, dict) and params["limit"] == 500 and params["offset"] == 0

    with db() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [d[0] for d in cur.description]
        ids = [row[0] for row in cur.fetchall()]

    assert columns[0] == "id" and columns[-1] == "rank"
    assert ids == [it.id for it in query.search_agenda_items("new late night ordinance",
                                                             municipality_slug="birmingham", limit=500)]


def test_the_statement_orders_by_date_ahead_of_rank_only_for_a_recency_word():
    plain, _ = query.build_search_sql(_sqm().parse_query("late night ordinance"), "birmingham", 20, 0)
    recent, _ = query.build_search_sql(_sqm().parse_query("new late night ordinance"), "birmingham", 20, 0)
    order = query.SEARCH_ORDER_SQL
    assert "{recency}" in order
    assert order.format(recency="") in plain and order.format(recency=query.SEARCH_RECENCY_ORDER_SQL) not in plain
    assert order.format(recency=query.SEARCH_RECENCY_ORDER_SQL) in recent


def test_the_statement_names_the_city_only_when_one_is_given():
    sq = _sqm().parse_query("paving")
    scoped, scoped_params = query.build_search_sql(sq, "birmingham", 20, 0)
    everywhere, everywhere_params = query.build_search_sql(sq, None, 20, 0)
    assert scoped_params["slug"] == "birmingham" and "%(slug)s" in scoped
    assert "slug" not in everywhere_params and "%(slug)s" not in everywhere


# --- The copied stop list ---------------------------------------------------------------------------


def test_every_copied_stop_word_is_a_stop_word_on_this_server():
    """So the parser never drops a word the server would have searched for."""
    stop_words = sorted(_sqm().STOP_WORDS)
    assert len(stop_words) == 127
    with db_cursor() as cur:
        cur.execute("""SELECT w, numnode(plainto_tsquery('english', w)) AS nodes
                         FROM unnest(%s::text[]) AS w""", [stop_words])
        nodes = {r["w"]: r["nodes"] for r in cur.fetchall()}
    assert len(nodes) == 127
    assert [w for w, n in nodes.items() if n != 0] == []


def test_the_words_the_parser_keeps_are_searched_by_this_server():
    """The other direction, for the words the plan's examples rely on: none is silently a stop word."""
    words = ["rules", "new", "recent", "latest", "days", "30", "keeping", "late", "night"]
    assert not set(words) & _sqm().STOP_WORDS
    with db_cursor() as cur:
        cur.execute("SELECT w, numnode(plainto_tsquery('english', w)) AS nodes FROM unnest(%s::text[]) AS w", [words])
        assert {r["w"]: r["nodes"] for r in cur.fetchall()} == dict.fromkeys(words, 1)


# --- The route ----------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _page_items(client, url: str) -> list[int]:
    """The agenda item ids of a results page's cards, in order, read by the golden check's own parser."""
    spec = importlib.util.spec_from_file_location("golden_search", REPO / "scripts" / "golden_search.py")
    golden = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(golden)
    resp = client.get(url)
    assert resp.status_code == 200
    return golden.parse_results(resp.get_data(as_text=True))["items"]


def test_the_search_page_lists_the_carded_item_ahead_of_the_2013_item(carded, client):
    seeded_ids = {carded[k] for k in ROWS}
    items = [i for i in _page_items(client, "/search?q=new+late+night+ordinance&city=birmingham") if i in seeded_ids]
    assert items[:2] == [carded["felder"], carded["old"]]
    assert carded["hidden"] not in items


def test_the_route_searches_items_for_the_words_beside_a_speaker_token(carded, client):
    """`speaker:oquinn proclamation` searches items for "proclamation", not for "speaker" and "oquinn"."""
    items = _page_items(client, "/search?q=speaker:oquinn+proclamation&city=birmingham")
    assert carded["nno"] in items


def test_a_speaker_only_query_returns_no_items(carded, client):
    assert _page_items(client, "/search?q=speaker:ordinance&city=birmingham") == []
