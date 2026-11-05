"""The readers of a search card: the item excerpt and the spoken moments under a search result.

Plan: plans/completed/search-finds-what-was-said.md (M5). Cards are written by
hand through `write_cards`; nothing here calls a model.

`docket.services.search_query`, `docket.ai.transcripts.cards`, and the names
M5 adds to `docket.services.transcripts` are read inside the helpers and
tests, not at the top of this file, so the file collects before they exist.
"""
import dataclasses
import importlib
from datetime import date

import pytest

from docket.config import DATABASE_URL
from docket.db import db_cursor
from docket.services import transcripts as tsvc
from docket.web import create_app

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)

EXTERNAL_IDS = ["999961", "999962", "999963"]
MODEL = "test-model"
VERSION = 200

# (seq, text, cluster label, key of the item the segment is filed under or None).
# Item "a" is filed from segment 3 to 9; its card, when a test writes one,
# has the bounds 5 to 8. Segments 3 and 9 hold every word the tests search
# for and sit outside those bounds. Item "b" is filed from segment 10 on and
# never has a card. Segment 13 is a silence row.
MAIN_SEGMENTS = [
    (0, "good morning and welcome to the council meeting", "S0", None),
    (1, "the clerk will call the roll", "S1", None),
    (2, "we have a quorum", "S0", None),
    (3, "late night parade footage was an ordinance of joy", "S2", "a"),
    (4, "congratulations to the city on the parade", "S2", "a"),
    (5, "item fourteen an ordinance on late hours", "S1", "a"),
    (6, "late night establishments must keep camera footage", "S3", "a"),
    (7, "the footage is kept thirty days under the ordinance", "S3", "a"),
    (8, "the ordinance passes", "S0", "a"),
    (9, "late night ordinance footage aside we move on", "S0", "a"),
    (10, "item fifteen paving paving paving", "S1", "b"),
    (11, "paving late in the season costs more", "S3", "b"),
    (12, "the resolution passes", "S0", "b"),
    (13, "", None, "b"),
    (14, "the fee is <b>less</b> & <script>x</script> for paving", "S4", "b"),
]
# Cluster label -> (display name, confidence). S2 and S4 have no speaker row.
MAIN_SPEAKERS = {"S0": ("Madam President", None), "S1": ("Maybe Clerk", 0.3), "S3": ("Chief Pickett", 0.95)}

# A block of items read one after another and voted together. Item "p" is
# filed from segment 4 to 6, "q" from 7 to 9, and "r" at segment 10.
# Segments 6 and 7 are one speaker talking across the placement boundary.
BLOCK_SEGMENTS = [
    (0, "good evening", "S0", None),
    (1, "the clerk will call the roll", "S1", None),
    (2, "we have a quorum", "S0", None),
    (3, "thank you", "S0", None),
    (4, "we now take up the consent items", "S0", "p"),
    (5, "item one a parking ordinance for downtown", "S1", "p"),
    (6, "the parking ordinance covers the garage", "S3", "p"),
    (7, "item two a towing ordinance", "S3", "q"),
    (8, "all in favor of the parking and towing ordinances", "S0", "q"),
    (9, "the ordinances pass", "S0", "q"),
    (10, "next is the parking report", "S0", "r"),
]


def _cards():
    return importlib.import_module("docket.ai.transcripts.cards")


def _query(*words: str, phrases: tuple[str, ...] = (), identifiers: tuple[str, ...] = ()):
    """A parsed query built by hand; `parse_query` is M6's."""
    m = importlib.import_module("docket.services.search_query")
    units = (tuple(m.Unit("word", w) for w in words)
             + tuple(m.Unit("phrase", p) for p in phrases)
             + tuple(m.Unit("identifier", i) for i in identifiers))
    return m.SearchQuery(units=units, excluded=(), prefer_recent=False, raw=" ".join(words))


def _delete_all():
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE external_id = ANY(%s)", [EXTERNAL_IDS])


def _install(external_id: str, item_keys: list[str], segments: list[tuple], speakers: dict | None = None) -> dict:
    """A Birmingham meeting with one item per key, a public transcript, speakers, and filed segments.

    A segment's start is ten times its seq and it lasts nine seconds.
    """
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
        muni = cur.fetchone()["id"]
        cur.execute("""INSERT INTO meetings (municipality_id, title, meeting_date, external_id, video_url)
                       VALUES (%s, 'Moments test', %s, %s, 'https://x/v') RETURNING id""",
                    [muni, date(2026, 5, 5), external_id])
        mid = cur.fetchone()["id"]
        cur.execute("INSERT INTO processing_status (meeting_id) VALUES (%s)", [mid])
        items = {}
        for number, key in enumerate(item_keys, 1):
            cur.execute("""INSERT INTO agenda_items (meeting_id, item_number, title)
                           VALUES (%s, %s, %s) RETURNING id""",
                        [mid, str(number), f"Moments test item {key}"])
            items[key] = cur.fetchone()["id"]
        cur.execute("""INSERT INTO transcripts (meeting_id, status, uploaded_at)
                       VALUES (%s, 'events_extracted', now()) RETURNING id, uploaded_at""", [mid])
        tr = cur.fetchone()
        speaker_ids = {}
        for cluster, (name, confidence) in (speakers or {}).items():
            cur.execute("""INSERT INTO transcript_speakers (meeting_id, cluster_label, display_name, confidence)
                           VALUES (%s, %s, %s, %s) RETURNING id""", [mid, cluster, name, confidence])
            speaker_ids[cluster] = cur.fetchone()["id"]
        for seq, text, cluster, key in segments:
            cur.execute("""INSERT INTO transcript_segments (transcript_id, seq, start_s, end_s, text, cluster_label,
                                                            speaker_id, agenda_item_id, assignment_method, is_silence)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        [tr["id"], seq, seq * 10.0, seq * 10.0 + 9.0, text, cluster, speaker_ids.get(cluster),
                         items.get(key), "index_point" if key else None, text == ""])
    return {"meeting_id": mid, "transcript_id": tr["id"], "uploaded_at": tr["uploaded_at"], **items}


def _write_cards(inst: dict, bounds: dict[str, tuple[int, int] | None]) -> None:
    """Replace the transcript's cards: one per key, with the given bounds, or none when the value is None."""
    rows = []
    for key, pair in bounds.items():
        start, end = pair if pair else (None, None)
        rows.append({"item_id": inst[key], "discussed": True, "start_seq": start, "end_seq": end,
                     "start_s": None if start is None else start * 10.0,
                     "end_s": None if end is None else end * 10.0 + 9.0,
                     "card": {"aliases": []}, "search_b": "", "search_c": ""})
    written = _cards().write_cards(inst["transcript_id"], inst["uploaded_at"], rows,
                                   model=MODEL, prompt_version=VERSION)
    assert written == len(rows)


def _reupload(inst: dict) -> None:
    """What the producer's upload does to the row a card is tied to: a later `uploaded_at`."""
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET uploaded_at = now() WHERE id = %s RETURNING uploaded_at",
                    [inst["transcript_id"]])
        assert cur.fetchone()["uploaded_at"] != inst["uploaded_at"]


def _seqs(excerpt: dict) -> list[int]:
    return [seq for turn in excerpt["turns"] for seq in turn.seqs]


def _moment_seqs(moments: dict, item_id: int) -> list[int]:
    return [m["seq"] for m in moments.get(item_id, [])]


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def main():
    """Items a and b of one meeting; no card until a test writes one."""
    _delete_all()
    inst = _install("999961", ["a", "b"], MAIN_SEGMENTS, MAIN_SPEAKERS)
    yield inst
    _delete_all()


@pytest.fixture
def carded(main):
    """The main meeting with a current card for item a, bounds 5 to 8."""
    _write_cards(main, {"a": (5, 8)})
    return main


@pytest.fixture
def block():
    """Items p, q, and r of a second meeting, read as a block; no card until a test writes one."""
    _delete_all()
    inst = _install("999962", ["p", "q", "r"], BLOCK_SEGMENTS)
    yield inst
    _delete_all()


# ---------------------------------------------------------------------------
# item_ranges
# ---------------------------------------------------------------------------

def test_item_ranges_gives_the_bounds_of_a_current_card_and_nulls_without_one(carded):
    ranges = tsvc.item_ranges([carded["a"], carded["b"]])

    assert set(ranges) == {carded["a"], carded["b"]}
    a = ranges[carded["a"]]
    assert a["transcript_id"] == carded["transcript_id"]
    assert a["meeting_id"] == carded["meeting_id"]
    assert a["municipality_slug"] == "birmingham"
    assert (a["start_seq"], a["end_seq"]) == (5, 8)
    b = ranges[carded["b"]]
    assert b["transcript_id"] == carded["transcript_id"]
    assert (b["start_seq"], b["end_seq"]) == (None, None)


def test_item_ranges_ignores_the_bounds_of_a_card_that_is_not_current(carded):
    _reupload(carded)

    a = tsvc.item_ranges([carded["a"]])[carded["a"]]

    assert (a["start_seq"], a["end_seq"]) == (None, None)


def test_item_ranges_leaves_out_an_item_whose_meeting_has_no_public_transcript(carded):
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET status = 'low_speech' WHERE id = %s", [carded["transcript_id"]])

    assert tsvc.item_ranges([carded["a"], carded["b"]]) == {}


def test_item_ranges_of_no_items_is_empty_and_runs_no_query(monkeypatch):
    def _no_query(*args, **kwargs):
        raise AssertionError("item_ranges opened a cursor for an empty list")
    monkeypatch.setattr(tsvc, "db_cursor", _no_query)

    assert tsvc.item_ranges([]) == {}


# ---------------------------------------------------------------------------
# excerpt_for_item
# ---------------------------------------------------------------------------

def test_the_excerpt_starts_and_ends_at_the_snapped_bounds(carded):
    excerpt = tsvc.excerpt_for_item(carded["a"])

    assert excerpt["snapped"] is True
    assert excerpt["turns"][0].seqs == [5]
    assert excerpt["anchor"] == "t-5"
    assert _seqs(excerpt) == [5, 6, 7, 8], "nothing before the snapped start or after the snapped end"
    assert excerpt["truncated"] is False
    assert excerpt["meeting_id"] == carded["meeting_id"]
    assert excerpt["transcript_id"] == carded["transcript_id"]


def test_the_snapped_excerpt_groups_turns_and_labels_speakers_as_before(carded):
    turns = tsvc.excerpt_for_item(carded["a"])["turns"]

    assert [t.seqs for t in turns] == [[5], [6, 7], [8]]
    assert turns[1].speaker_label == "Chief Pickett"
    assert turns[1].text == ("late night establishments must keep camera footage "
                             "the footage is kept thirty days under the ordinance")
    assert turns[0].speaker_label.startswith("Speaker "), "a low-confidence name is not shown"
    assert turns[2].speaker_label == "Madam President"


def test_the_excerpt_keeps_max_turns_and_says_when_it_was_cut(carded):
    excerpt = tsvc.excerpt_for_item(carded["a"], max_turns=2)

    assert [t.seqs for t in excerpt["turns"]] == [[5], [6, 7]]
    assert excerpt["truncated"] is True
    assert excerpt["anchor"] == "t-5"


def test_after_a_reupload_the_excerpt_starts_at_the_placement_again(carded):
    _reupload(carded)

    excerpt = tsvc.excerpt_for_item(carded["a"])

    assert excerpt["snapped"] is False
    assert excerpt["turns"][0].seqs[0] == 3
    assert excerpt["anchor"] == "t-3"
    assert _seqs(excerpt) == [3, 4, 5, 6, 7, 8, 9]


def test_an_item_with_no_card_behaves_as_today(carded):
    excerpt = tsvc.excerpt_for_item(carded["b"])

    assert excerpt["snapped"] is False
    assert excerpt["anchor"] == "t-10"
    assert _seqs(excerpt) == [10, 11, 12, 14], "the filed segments, the silence row left out"
    assert [t.seqs for t in excerpt["turns"]] == [[10], [11], [12], [14]]
    assert excerpt["truncated"] is False


def test_a_current_card_without_bounds_falls_back_to_the_placement(main):
    _write_cards(main, {"a": None})

    excerpt = tsvc.excerpt_for_item(main["a"])

    assert excerpt["snapped"] is False
    assert excerpt["anchor"] == "t-3"


def test_a_snapped_range_with_no_spoken_segment_falls_back_to_the_placement(main):
    """The validator never stores such bounds; a reader must not lose the excerpt if one appears."""
    _write_cards(main, {"b": (13, 13)})

    excerpt = tsvc.excerpt_for_item(main["b"])

    assert excerpt["snapped"] is False
    assert excerpt["anchor"] == "t-10"


def test_a_low_speech_transcript_has_no_excerpt(carded):
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET status = 'low_speech' WHERE id = %s", [carded["transcript_id"]])

    assert tsvc.excerpt_for_item(carded["a"]) is None
    assert tsvc.excerpt_for_item(carded["b"]) is None


def test_an_item_with_nothing_filed_and_no_card_has_no_excerpt(block):
    with db_cursor() as cur:
        cur.execute("UPDATE transcript_segments SET agenda_item_id = NULL, assignment_method = NULL "
                    "WHERE agenda_item_id = %s", [block["r"]])

    assert tsvc.excerpt_for_item(block["r"]) is None


def test_a_turn_that_runs_past_the_placement_boundary_stays_one_turn(block):
    """Segments 6 and 7 are one speaker, filed under two items; inside p's snapped range they are one turn."""
    _write_cards(block, {"p": (5, 9)})

    excerpt = tsvc.excerpt_for_item(block["p"], max_turns=10)

    assert excerpt["snapped"] is True
    assert [t.seqs for t in excerpt["turns"]] == [[5], [6, 7], [8, 9]]
    assert all(t.agenda_item_id == block["p"] for t in excerpt["turns"])


def test_the_item_page_shows_the_snapped_excerpt(client, carded):
    html = client.get(f"/al/birmingham/items/{carded['a']}/").get_data(as_text=True)

    assert "From the video" in html
    assert f"/al/birmingham/meetings/{carded['meeting_id']}/transcript/#t-5" in html
    assert "item fourteen an ordinance on late hours" in html
    assert "congratulations to the city on the parade" not in html
    assert "late night parade footage" not in html


# ---------------------------------------------------------------------------
# A block of items voted together: a segment belongs to the item opened latest
# ---------------------------------------------------------------------------

def test_in_a_block_the_first_item_owns_only_what_precedes_the_second(block):
    _write_cards(block, {"p": (5, 9), "q": (7, 9)})

    first = tsvc.excerpt_for_item(block["p"], max_turns=10)
    second = tsvc.excerpt_for_item(block["q"], max_turns=10)

    assert _seqs(first) == [5, 6], "segments 7 to 9 belong to the item opened at 7"
    assert first["anchor"] == "t-5" and first["snapped"] is True
    assert _seqs(second) == [7, 8, 9]
    assert second["anchor"] == "t-7" and second["snapped"] is True


def test_in_a_block_the_first_items_moments_never_come_from_the_seconds_range(block):
    _write_cards(block, {"p": (5, 9), "q": (7, 9)})

    moments = tsvc.moments_for_items([block["p"], block["q"]], _query("parking", "ordinance"), per_item=10)

    assert _moment_seqs(moments, block["p"]) == [5, 6]
    assert _moment_seqs(moments, block["q"]) == [7, 8, 9], "the shared vote shows under the last item"


def test_of_three_overlapping_ranges_each_item_owns_up_to_the_next_start(block):
    _write_cards(block, {"p": (5, 9), "q": (7, 9), "r": (8, 9)})

    assert _seqs(tsvc.excerpt_for_item(block["p"], max_turns=10)) == [5, 6]
    assert _seqs(tsvc.excerpt_for_item(block["q"], max_turns=10)) == [7]
    assert _seqs(tsvc.excerpt_for_item(block["r"], max_turns=10)) == [8, 9]
    moments = tsvc.moments_for_items([block["p"], block["q"], block["r"]], _query("ordinance"), per_item=10)
    assert _moment_seqs(moments, block["p"]) == [5, 6]
    assert _moment_seqs(moments, block["q"]) == [7]
    assert _moment_seqs(moments, block["r"]) == [8, 9]


def test_two_items_whose_ranges_start_together_do_not_take_each_others_segments(block):
    """Only a later start takes a segment; an equal one leaves both ranges whole."""
    _write_cards(block, {"p": (5, 9), "q": (5, 9)})

    assert _seqs(tsvc.excerpt_for_item(block["p"], max_turns=10)) == [5, 6, 7, 8, 9]
    assert _seqs(tsvc.excerpt_for_item(block["q"], max_turns=10)) == [5, 6, 7, 8, 9]


def test_a_card_that_is_not_current_takes_no_segment_from_a_current_one(block):
    """Cards of one transcript are written together; if one is ever left behind, its range is ignored."""
    _write_cards(block, {"p": (5, 9), "q": (7, 9)})
    with db_cursor() as cur:
        cur.execute("UPDATE agenda_item_search_cards SET source_uploaded_at = source_uploaded_at - interval '1 day' "
                    "WHERE agenda_item_id = %s", [block["q"]])

    first = tsvc.excerpt_for_item(block["p"], max_turns=10)
    second = tsvc.excerpt_for_item(block["q"], max_turns=10)

    assert _seqs(first) == [5, 6, 7, 8, 9]
    assert second["snapped"] is False and _seqs(second) == [7, 8, 9], "q's filed segments"
    moments = tsvc.moments_for_items([block["p"]], _query("towing"), per_item=10)
    assert _moment_seqs(moments, block["p"]) == [7, 8]


# ---------------------------------------------------------------------------
# moments_for_items
# ---------------------------------------------------------------------------

def test_the_three_best_segments_inside_the_bounds_come_back_in_seq_order(carded):
    """Inside 5 to 8 the segments match two, three, two, and one of the four words; the one-word line is left out."""
    moments = tsvc.moments_for_items([carded["a"]], _query("late", "night", "footage", "ordinance"))

    assert _moment_seqs(moments, carded["a"]) == [5, 6, 7]
    by_seq = {m["seq"]: m for m in moments[carded["a"]]}
    assert "<mark>footage</mark>" in by_seq[6]["headline"]
    assert "<mark>late</mark>" in by_seq[6]["headline"] and "<mark>night</mark>" in by_seq[6]["headline"]
    assert "<mark>ordinance</mark>" in by_seq[5]["headline"]


def test_a_segment_outside_the_bounds_is_never_a_moment(carded):
    """Segments 3 and 9 are filed under the item and hold all four words."""
    moments = tsvc.moments_for_items([carded["a"]], _query("late", "night", "footage", "ordinance"), per_item=50)

    assert _moment_seqs(moments, carded["a"]) == [5, 6, 7, 8]


def test_a_moment_carries_what_the_page_needs(carded):
    moments = tsvc.moments_for_items([carded["a"]], _query("camera"))

    assert list(moments) == [carded["a"]]
    (m,) = moments[carded["a"]]
    assert set(m) == {"item_id", "meeting_id", "seq", "start_s", "speaker_label", "headline", "anchor_url"}
    assert m["item_id"] == carded["a"]
    assert m["meeting_id"] == carded["meeting_id"]
    assert m["seq"] == 6
    assert m["start_s"] == 60.0
    assert m["speaker_label"] == "Chief Pickett"
    assert m["anchor_url"] == f"/al/birmingham/meetings/{carded['meeting_id']}/transcript/#t-6"
    assert m["headline"] == "late night establishments must keep <mark>camera</mark> footage"
    assert hasattr(m["headline"], "__html__"), "the headline is Markup, so the template needs no safe filter"


def test_an_item_with_no_card_uses_its_filed_segments(carded):
    moments = tsvc.moments_for_items([carded["b"]], _query("paving"))

    assert _moment_seqs(moments, carded["b"]) == [10, 11, 14]


def test_after_a_reupload_moments_come_from_the_filed_segments(carded):
    _reupload(carded)

    moments = tsvc.moments_for_items([carded["a"]], _query("parade"))

    assert _moment_seqs(moments, carded["a"]) == [3, 4], "segments the snapped bounds left out"


def test_several_items_are_answered_in_one_call_each_with_its_own_lines(carded):
    moments = tsvc.moments_for_items([carded["a"], carded["b"]], _query("late"))

    assert _moment_seqs(moments, carded["a"]) == [5, 6]
    assert _moment_seqs(moments, carded["b"]) == [11]
    assert all(m["item_id"] == carded["b"] for m in moments[carded["b"]])


def test_an_item_with_no_matching_line_is_absent(carded):
    moments = tsvc.moments_for_items([carded["a"], carded["b"]], _query("paving"))

    assert carded["a"] not in moments
    assert carded["b"] in moments


def test_markup_in_a_segment_comes_back_escaped(carded):
    moments = tsvc.moments_for_items([carded["b"]], _query("fee"))

    (m,) = moments[carded["b"]]
    assert m["seq"] == 14
    assert "<script>" not in m["headline"] and "&lt;script&gt;" in m["headline"]
    assert "&lt;b&gt;less&lt;/b&gt;" in m["headline"] and "&amp;" in m["headline"]
    assert "<mark>fee</mark>" in m["headline"]


def test_a_speaker_is_named_only_when_the_site_is_confident(carded):
    moments = tsvc.moments_for_items([carded["a"], carded["b"]], _query("ordinance", "fee"), per_item=10)

    labels = {m["seq"]: m["speaker_label"] for item in moments.values() for m in item}
    assert labels == {
        5: None,                # "Maybe Clerk" at confidence 0.3
        7: "Chief Pickett",     # confidence 0.95
        8: "Madam President",   # no confidence recorded: a manual name
        14: None,               # no speaker row; the cluster label never reaches a page
    }


def test_the_speaker_filter_narrows_the_moments(carded):
    sq = _query("late", "night", "footage", "ordinance")

    everyone = tsvc.moments_for_items([carded["a"]], sq, per_item=10)
    pickett = tsvc.moments_for_items([carded["a"]], sq, speaker="pickett", per_item=10)
    nobody = tsvc.moments_for_items([carded["a"]], sq, speaker="zzyzx-no-such-speaker", per_item=10)

    assert _moment_seqs(everyone, carded["a"]) == [5, 6, 7, 8]
    assert _moment_seqs(pickett, carded["a"]) == [6, 7]
    assert nobody == {}


def test_a_line_matching_two_words_is_chosen_over_an_earlier_line_repeating_one(carded):
    """Segment 10 says "paving" three times; segment 11 says "paving" and "late" once each."""
    moments = tsvc.moments_for_items([carded["b"]], _query("paving", "late"), per_item=1)

    assert _moment_seqs(moments, carded["b"]) == [11]


def test_matched_words_lead_where_rank_alone_would_choose_the_other_line(carded):
    """A line repeating two of three words ten times each outranks a line holding all three once; the fuller line leads."""
    with db_cursor() as cur:
        cur.execute("""INSERT INTO transcript_segments (transcript_id, seq, start_s, end_s, text, cluster_label,
                                                        agenda_item_id, assignment_method)
                       VALUES (%s, 15, 150, 159, %s, 'S4', %s, 'index_point'),
                              (%s, 16, 160, 169, 'the sewer and the drain and the culvert', 'S4', %s, 'index_point')""",
                    [carded["transcript_id"], " ".join(["sewer drain"] * 10), carded["b"],
                     carded["transcript_id"], carded["b"]])
        cur.execute("""SELECT s.seq, ts_rank(s.search_vector, plainto_tsquery('english', 'sewer')
                                                              || plainto_tsquery('english', 'drain')
                                                              || plainto_tsquery('english', 'culvert')) AS rank
                         FROM transcript_segments s
                        WHERE s.transcript_id = %s AND s.seq IN (15, 16)""", [carded["transcript_id"]])
        rank = {r["seq"]: r["rank"] for r in cur.fetchall()}
    assert rank[15] > rank[16], "by rank alone the repeating line would lead"

    moments = tsvc.moments_for_items([carded["b"]], _query("sewer", "drain", "culvert"), per_item=1)

    assert _moment_seqs(moments, carded["b"]) == [16]


def test_a_phrase_unit_matches_only_the_words_side_by_side(carded):
    moments = tsvc.moments_for_items([carded["a"]], _query(phrases=("camera footage",)), per_item=10)
    apart = tsvc.moments_for_items([carded["a"]], _query(phrases=("footage camera",)), per_item=10)

    assert _moment_seqs(moments, carded["a"]) == [6]
    assert apart == {}


def test_a_low_speech_transcript_has_no_moments(carded):
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET status = 'low_speech' WHERE id = %s", [carded["transcript_id"]])

    assert tsvc.moments_for_items([carded["a"], carded["b"]], _query("late", "paving")) == {}


def test_no_units_or_no_items_is_empty_and_runs_no_query(carded, monkeypatch):
    sq = _query("late")
    empty = _query()

    def _no_query(*args, **kwargs):
        raise AssertionError("moments_for_items opened a cursor with nothing to look for")
    monkeypatch.setattr(tsvc, "db_cursor", _no_query)

    assert tsvc.moments_for_items([], sq) == {}
    assert tsvc.moments_for_items([carded["a"]], empty) == {}


# ---------------------------------------------------------------------------
# The two SQL builders M5 creates in docket.services.search_query
# ---------------------------------------------------------------------------

def _one(sql: str, params: dict):
    with db_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()["v"]


def test_the_or_query_matches_a_document_holding_any_unit():
    m = importlib.import_module("docket.services.search_query")
    sq = _query("zeppelin", phrases=("late night",), identifiers=("26-50",))

    sql, params = m.or_tsquery_sql(sq.units, "q")

    assert sorted(params) == ["q0", "q1", "q2"]
    assert params == {"q0": "zeppelin", "q1": "late night", "q2": "26-50"}
    probe = f"SELECT to_tsvector('english', %(doc)s) @@ {sql} AS v"
    assert _one(probe, {**params, "doc": "a zeppelin over the park"}) is True
    assert _one(probe, {**params, "doc": "open late at night"}) is False, "the phrase needs its words side by side"
    assert _one(probe, {**params, "doc": "the late night rules"}) is True
    assert _one(probe, {**params, "doc": "Ordinance No. 26-50 is recalled"}) is True
    assert _one(probe, {**params, "doc": "26 members and 50 guests"}) is False
    assert _one(probe, {**params, "doc": "nothing of the kind"}) is False


def test_coverage_counts_the_word_and_phrase_units_a_document_matches():
    m = importlib.import_module("docket.services.search_query")
    sq = _query("late", "night", "footage", phrases=("camera footage",), identifiers=("26-50",))

    sql, params = m.coverage_sql(sq.units, "d.v", "c")

    assert sorted(params) == ["c0", "c1", "c2", "c3"], "the identifier is not counted and takes no parameter"
    probe = f"SELECT {sql} AS v FROM (SELECT to_tsvector('english', %(doc)s) AS v) d"
    assert _one(probe, {**params, "doc": "late night establishments must keep camera footage"}) == 4
    assert _one(probe, {**params, "doc": "the footage of the camera, late late late"}) == 2
    assert _one(probe, {**params, "doc": "Ordinance No. 26-50"}) == 0
    assert _one(probe, {**params, "doc": "night night night"}) == 1, "a repeated word counts once"


def test_coverage_of_no_countable_unit_is_the_literal_zero():
    m = importlib.import_module("docket.services.search_query")

    assert m.coverage_sql((), "s.search_vector", "c") == ("0", {})
    assert m.coverage_sql(_query(identifiers=("26-50",)).units, "s.search_vector", "c") == ("0", {})


def test_the_two_builders_name_a_units_parameter_alike_under_one_prefix():
    """So one parameter dict serves a statement that uses both fragments."""
    m = importlib.import_module("docket.services.search_query")
    sq = _query("late", identifiers=("26-50",), phrases=("camera footage",))

    _, or_params = m.or_tsquery_sql(sq.units, "u")
    _, cov_params = m.coverage_sql(sq.units, "s.search_vector", "u")

    assert set(cov_params) < set(or_params)
    assert all(or_params[k] == v for k, v in cov_params.items())


def test_a_parsed_query_and_its_units_are_immutable_values():
    m = importlib.import_module("docket.services.search_query")
    sq = _query("late")

    assert sq.units == (m.Unit("word", "late"),)
    assert (sq.excluded, sq.prefer_recent, sq.raw) == ((), False, "late")
    with pytest.raises(dataclasses.FrozenInstanceError):
        sq.raw = "other"
    with pytest.raises(dataclasses.FrozenInstanceError):
        sq.units[0].text = "other"
