"""The search card without the model: the prompt, the response schema, the meeting renderer, and the validator.

Plan: plans/active/search-finds-what-was-said.md (M3). No database and no
model call: replies are written by hand and segments are plain dicts.

The symbols under test are imported inside the helpers and tests, not at the
top of this file, so the file collects before they exist and the before
state reads as these tests failing, not as one collection error.
"""
import json

import pytest
from pydantic import ValidationError

from tests.support.transcript_fixtures import load_bundle

ITEM_A = 100   # placed on segments 2 to 6 of the small meeting
ITEM_B = 200   # placed on segments 7 to 9
UNPLACED = 300

ROW_KEYS = {"item_id", "discussed", "start_seq", "end_seq", "start_s", "end_s", "card", "search_b", "search_c"}
COUNT_KEYS = {"placed", "cards", "missing", "extra", "discussed", "details_kept", "details_repointed",
              "details_dropped", "bounds_kept", "bounds_dropped", "starts_moved"}


def _cards():
    from docket.ai.transcripts import cards
    return cards


def _schemas():
    from docket.ai.transcripts import schemas
    return schemas


def _seg(seq, text, *, start_s=None, end_s=None, silence=False, **extra):
    start = seq * 10.0 if start_s is None else start_s
    return {"seq": seq, "start_s": start, "end_s": start + 10.0 if end_s is None else end_s, "text": text,
            "is_silence": silence, "cluster_label": "S1", **extra}


def _meeting_segments():
    """Twelve segments, ten seconds each. Segments 0 and 10 are silence."""
    return [
        _seg(0, "", silence=True),
        _seg(1, "Good morning everyone and welcome to the regular meeting of the council."),
        _seg(2, "Item 14, an ordinance to amend the Kelvin Felder ordinance on safety plans."),
        _seg(3, "Establishments must have cameras in place, with footage retained for up to 30 days."),
        _seg(4, "The security plan has to be filed with the police department before"),
        _seg(5, "the first of July each year, and we will check that it was."),
        _seg(6, "All in favor say aye. The item passes."),
        _seg(7, "Item 15, a resolution accepting a used Ford Explorer from the 911 agency."),
        _seg(8, "We would like to delay this vote for two weeks."),
        _seg(9, "Without objection the item is delayed."),
        _seg(10, "", silence=True),
        _seg(11, "The balloon was flown at the height of the proposed hotel building last spring."),
    ]


def _items():
    return [
        {"id": ITEM_A, "item_number": "14", "title": "An Ordinance to amend the Kelvyn Felder Ordinance",
         "description": None, "headline": None, "why_it_matters": None,
         "first_seq": 2, "placed_start_s": 20.0, "placed_end_s": 70.0},
        {"id": ITEM_B, "item_number": "15", "title": "A Resolution accepting one vehicle",
         "description": None, "headline": None, "why_it_matters": None,
         "first_seq": 7, "placed_start_s": 70.0, "placed_end_s": 100.0},
    ]


def _card(item_id, **over):
    base = {"item_id": item_id, "discussed": True, "start_seq": None, "end_seq": None, "aliases": [],
            "spoken_details": [], "identifiers": [], "names": [],
            "outcome": {"result": "unclear", "seq": None}, "refers_to": {"text": "", "seq": None}}
    base.update(over)
    return base


def _detail(text, seq, quote):
    return {"text": text, "seq": seq, "quote": quote}


def _validate(*cards, items=None, segments=None):
    parsed = _schemas().CardList.model_validate({"cards": list(cards)})
    return _cards().validate_cards(parsed, items=_items() if items is None else items,
                                   segments=_meeting_segments() if segments is None else segments)


def _row(rows, item_id):
    (row,) = [r for r in rows if r["item_id"] == item_id]
    return row


# --- which cards become rows ------------------------------------------------

def test_a_valid_reply_becomes_rows_write_cards_accepts_with_every_count_key():
    rows, counts = _validate(
        _card(ITEM_A, start_seq=2, end_seq=6, aliases=["club safety plan rules"],
              outcome={"result": "passed", "seq": 6}),
        _card(ITEM_B, discussed=False),
    )
    assert [r["item_id"] for r in rows] == [ITEM_A, ITEM_B]
    for r in rows:
        assert set(r) == ROW_KEYS
        assert set(r["card"]) == {"aliases", "spoken_details", "identifiers", "names", "outcome", "refers_to"}
        json.dumps(r["card"])   # the store writes it as JSONB
    assert set(counts) == COUNT_KEYS
    assert counts == {"placed": 2, "cards": 2, "missing": 0, "extra": 0, "discussed": 1, "details_kept": 0,
                      "details_repointed": 0, "details_dropped": 0, "bounds_kept": 1, "bounds_dropped": 0,
                      "starts_moved": 0}


def test_a_card_for_an_unplaced_item_is_dropped_and_counted_extra():
    rows, counts = _validate(_card(ITEM_A), _card(UNPLACED, aliases=["something else entirely"]), _card(ITEM_B))
    assert [r["item_id"] for r in rows] == [ITEM_A, ITEM_B]
    assert counts["extra"] == 1 and counts["cards"] == 2 and counts["missing"] == 0


def test_a_second_card_for_the_same_item_is_dropped_and_the_first_kept():
    rows, counts = _validate(_card(ITEM_A, aliases=["first card"]), _card(ITEM_A, aliases=["second card"]),
                             _card(ITEM_B))
    assert [r["item_id"] for r in rows] == [ITEM_A, ITEM_B]
    assert _row(rows, ITEM_A)["card"]["aliases"] == ["first card"]
    assert counts["cards"] == 2 and counts["extra"] == 1


def test_a_placed_item_with_no_card_is_counted_missing_and_gets_no_row():
    rows, counts = _validate(_card(ITEM_A))
    assert [r["item_id"] for r in rows] == [ITEM_A]
    assert counts["placed"] == 2 and counts["cards"] == 1 and counts["missing"] == 1


def test_an_empty_reply_yields_no_rows_and_every_placed_item_missing():
    rows, counts = _validate()
    assert rows == []
    assert counts["placed"] == 2 and counts["cards"] == 0 and counts["missing"] == 2


# --- aliases ------------------------------------------------------------------

def test_aliases_are_stripped_lowercased_deduplicated_and_limited_to_eight_words():
    rows, _ = _validate(_card(ITEM_A, aliases=[
        "  Late Night   Establishment Rules ", "late night establishment rules", "", "   ",
        "one two three four five six seven eight", "one two three four five six seven eight nine", "Clubs",
    ]), _card(ITEM_B))
    assert _row(rows, ITEM_A)["card"]["aliases"] == [
        "late night establishment rules", "one two three four five six seven eight", "clubs"]


def test_at_most_eight_aliases_are_kept():
    rows, _ = _validate(_card(ITEM_A, aliases=[f"alias number {n}" for n in range(11)]), _card(ITEM_B))
    assert _row(rows, ITEM_A)["card"]["aliases"] == [f"alias number {n}" for n in range(8)]


# --- spoken details and the citation guard -------------------------------------

def test_a_quote_copied_with_different_capitalisation_and_punctuation_is_kept():
    rows, counts = _validate(_card(ITEM_A, spoken_details=[
        _detail("Establishments must keep camera footage for up to 30 days.", 3,
                "CAMERAS IN PLACE with footage retained for up to 30 days")]), _card(ITEM_B))
    assert _row(rows, ITEM_A)["card"]["spoken_details"] == [
        {"text": "Establishments must keep camera footage for up to 30 days.", "seq": 3,
         "quote": "CAMERAS IN PLACE with footage retained for up to 30 days"}]
    assert (counts["details_kept"], counts["details_repointed"], counts["details_dropped"]) == (1, 0, 0)


def test_a_quote_that_straddles_two_segments_is_repointed_to_the_first():
    # The model cited segment 5, where the quote ends; it starts in segment 4.
    rows, counts = _validate(_card(ITEM_A, spoken_details=[
        _detail("The security plan is due before July 1 each year.", 5,
                "police department before the first of July each year")]), _card(ITEM_B))
    (detail,) = _row(rows, ITEM_A)["card"]["spoken_details"]
    assert detail["seq"] == 4
    assert (counts["details_kept"], counts["details_repointed"], counts["details_dropped"]) == (1, 1, 0)


def test_a_straddling_quote_cited_at_its_first_segment_keeps_its_seq_and_is_not_counted_repointed():
    rows, counts = _validate(_card(ITEM_A, spoken_details=[
        _detail("The security plan is due before July 1 each year.", 4,
                "police department before the first of July each year")]), _card(ITEM_B))
    (detail,) = _row(rows, ITEM_A)["card"]["spoken_details"]
    assert detail["seq"] == 4
    assert (counts["details_kept"], counts["details_repointed"], counts["details_dropped"]) == (1, 0, 0)


def test_a_quote_found_two_segments_from_its_cited_segment_is_repointed_there():
    rows, counts = _validate(_card(ITEM_A, spoken_details=[
        _detail("Camera footage is kept up to 30 days.", 5, "footage retained for up to 30 days"),
        _detail("The item passed on a voice vote.", 4, "All in favor say aye")]), _card(ITEM_B))
    assert [d["seq"] for d in _row(rows, ITEM_A)["card"]["spoken_details"]] == [3, 6]
    assert (counts["details_kept"], counts["details_repointed"], counts["details_dropped"]) == (2, 2, 0)


def test_a_quote_from_another_part_of_the_meeting_is_dropped():
    # Segment 11 holds the words; the detail cites segment 3, eight segments away.
    rows, counts = _validate(_card(ITEM_A, aliases=["club safety plan rules"], spoken_details=[
        _detail("A balloon was flown at the building's height.", 3,
                "balloon was flown at the height of the proposed hotel")]), _card(ITEM_B))
    row = _row(rows, ITEM_A)
    assert row["card"]["spoken_details"] == []
    assert row["card"]["aliases"] == ["club safety plan rules"]   # the rest of the card survives
    assert (counts["details_kept"], counts["details_repointed"], counts["details_dropped"]) == (0, 0, 1)


def test_the_window_counts_segments_the_model_saw_so_silence_does_not_use_a_place():
    # Segment 9 is cited; segment 10 is silence, so segment 11 is the second neighbour after it.
    rows, counts = _validate(_card(ITEM_A), _card(ITEM_B, spoken_details=[
        _detail("A balloon was flown at the building's height.", 8,
                "balloon was flown at the height of the proposed hotel")]))
    (detail,) = _row(rows, ITEM_B)["card"]["spoken_details"]
    assert detail["seq"] == 11 and counts["details_repointed"] == 1


def test_a_quote_the_transcript_does_not_hold_is_dropped():
    rows, counts = _validate(_card(ITEM_A, spoken_details=[
        _detail("Clubs must close at two in the morning.", 3, "every club must close at two in the morning")]),
        _card(ITEM_B))
    assert _row(rows, ITEM_A)["card"]["spoken_details"] == []
    assert counts["details_dropped"] == 1


@pytest.mark.parametrize("detail", [
    _detail("   ", 3, "cameras in place, with footage retained"),              # no sentence
    _detail("Cameras are required.", 99, "cameras in place, with footage"),    # not a segment
    _detail("Cameras are required.", 0, "cameras in place, with footage"),     # a silence segment
    _detail("Cameras are required.", 3, "   "),                                # no quote
])
def test_a_detail_without_text_a_real_segment_or_a_quote_is_dropped(detail):
    rows, counts = _validate(_card(ITEM_A, spoken_details=[detail]), _card(ITEM_B))
    assert _row(rows, ITEM_A)["card"]["spoken_details"] == []
    assert (counts["details_kept"], counts["details_dropped"]) == (0, 1)


def test_at_most_eight_details_are_kept_and_the_rest_counted_dropped():
    details = [_detail(f"Detail number {n}.", 3, "cameras in place, with footage retained") for n in range(10)]
    rows, counts = _validate(_card(ITEM_A, spoken_details=details), _card(ITEM_B))
    kept = _row(rows, ITEM_A)["card"]["spoken_details"]
    assert [d["text"] for d in kept] == [f"Detail number {n}." for n in range(8)]
    assert (counts["details_kept"], counts["details_dropped"]) == (8, 2)


def test_every_stored_quote_is_found_by_the_guard_at_its_segment_or_the_two_on_either_side():
    from docket.ai.transcripts.guard import find_citation

    segments = _meeting_segments()
    rows, _ = _validate(_card(ITEM_A, spoken_details=[
        _detail("Footage is kept up to 30 days.", 3, "footage retained for up to 30 days"),
        _detail("The plan is due before July 1.", 5, "police department before the first of July each year"),
        _detail("The item passed.", 4, "All in favor say aye")]), _card(ITEM_B), segments=segments)
    spoken = [s for s in segments if not s["is_silence"]]
    details = _row(rows, ITEM_A)["card"]["spoken_details"]
    assert len(details) == 3
    for d in details:
        at = [s["seq"] for s in spoken].index(d["seq"])
        joined = " ".join(s["text"] for s in spoken[max(0, at - 2):at + 3])
        assert find_citation(d["quote"], joined).kind != "missing"


# --- identifiers, names, outcome, refers_to -------------------------------------

def test_identifier_values_are_stripped_and_a_seq_that_is_not_a_segment_becomes_null():
    rows, _ = _validate(_card(ITEM_A, identifiers=[
        {"kind": "ordinance", "value": "  26-50 ", "seq": 2},
        {"kind": "case", "value": "ZAC2025-00012", "seq": 99},
        {"kind": "other", "value": "   ", "seq": None},
        {"kind": "contract", "value": "x" * 41, "seq": None},
        {"kind": "resolution", "value": "y" * 40, "seq": 10},
    ]), _card(ITEM_B))
    assert _row(rows, ITEM_A)["card"]["identifiers"] == [
        {"kind": "ordinance", "value": "26-50", "seq": 2},
        {"kind": "case", "value": "ZAC2025-00012", "seq": None},
        {"kind": "resolution", "value": "y" * 40, "seq": None},
    ]


def test_at_most_twelve_identifiers_are_kept():
    rows, _ = _validate(_card(ITEM_A, identifiers=[
        {"kind": "other", "value": f"file-{n}", "seq": None} for n in range(15)]), _card(ITEM_B))
    assert [i["value"] for i in _row(rows, ITEM_A)["card"]["identifiers"]] == [f"file-{n}" for n in range(12)]


def test_names_need_a_name_and_variants_are_deduplicated_and_exclude_the_name():
    rows, _ = _validate(_card(ITEM_A, names=[
        {"name": " Kelvyn Felder Ordinance ", "variants": ["Kelvin Felder Ordinance", "kelvyn felder ordinance",
                                                           "Felder Ordinance", "Kelvin Felder Ordinance", "  "]},
        {"name": "   ", "variants": ["Nobody"]},
        {"name": "Phil Morton", "variants": []},
    ]), _card(ITEM_B))
    assert _row(rows, ITEM_A)["card"]["names"] == [
        {"name": "Kelvyn Felder Ordinance", "variants": ["Kelvin Felder Ordinance", "Felder Ordinance"]},
        {"name": "Phil Morton", "variants": []},
    ]


def test_at_most_twelve_names_and_six_variants_each_are_kept():
    rows, _ = _validate(_card(ITEM_A, names=[
        {"name": f"Person {n}", "variants": [f"Persun {n} spelling {v}" for v in range(8)]} for n in range(14)]),
        _card(ITEM_B))
    names = _row(rows, ITEM_A)["card"]["names"]
    assert [n["name"] for n in names] == [f"Person {n}" for n in range(12)]
    assert all(len(n["variants"]) == 6 for n in names)


def test_an_outcome_seq_that_is_not_a_segment_becomes_null_and_the_result_is_kept():
    rows, _ = _validate(_card(ITEM_A, outcome={"result": "passed", "seq": 6}),
                        _card(ITEM_B, outcome={"result": "delayed", "seq": 400}))
    assert _row(rows, ITEM_A)["card"]["outcome"] == {"result": "passed", "seq": 6}
    assert _row(rows, ITEM_B)["card"]["outcome"] == {"result": "delayed", "seq": None}


def test_refers_to_with_empty_text_is_stored_as_null():
    rows, _ = _validate(_card(ITEM_A, refers_to={"text": "", "seq": 3}),
                        _card(ITEM_B, refers_to={"text": "   ", "seq": None}))
    assert _row(rows, ITEM_A)["card"]["refers_to"] is None
    assert _row(rows, ITEM_B)["card"]["refers_to"] is None


def test_refers_to_keeps_its_text_and_a_seq_that_is_not_a_segment_becomes_null():
    rows, _ = _validate(
        _card(ITEM_A, refers_to={"text": " The Public Safety Committee had recommended this item. ", "seq": 6}),
        _card(ITEM_B, refers_to={"text": "The vote was put off from the last meeting.", "seq": 10}))
    assert _row(rows, ITEM_A)["card"]["refers_to"] == {
        "text": "The Public Safety Committee had recommended this item.", "seq": 6}
    assert _row(rows, ITEM_B)["card"]["refers_to"] == {
        "text": "The vote was put off from the last meeting.", "seq": None}


# --- snapped bounds -------------------------------------------------------------

def _far_segments():
    """A meeting spread over half an hour, to test bounds far from the placement.

    The item is placed on segments 4 and 5, from 1000 s to 1100 s.
    """
    return [
        _seg(0, "A long way before the item.", start_s=300.0, end_s=310.0),          # 700 s before the placement
        _seg(1, "Nearer the item but still before it.", start_s=450.0, end_s=460.0),  # 550 s before
        _seg(2, "", start_s=900.0, end_s=910.0, silence=True),
        _seg(3, "The clerk reads the item aloud.", start_s=980.0, end_s=990.0),
        _seg(4, "The item is discussed at some length.", start_s=1000.0, end_s=1050.0),
        _seg(5, "The item passes.", start_s=1050.0, end_s=1100.0),
        _seg(6, "A later matter is discussed.", start_s=1640.0, end_s=1650.0),         # ends 550 s after
        _seg(7, "A much later matter is discussed.", start_s=1790.0, end_s=1800.0),    # ends 700 s after
    ]


def _far_items():
    return [{"id": ITEM_A, "item_number": "1", "title": "An item", "description": None, "headline": None,
             "why_it_matters": None, "first_seq": 4, "placed_start_s": 1000.0, "placed_end_s": 1100.0}]


def _far(start_seq, end_seq, **over):
    return _validate(_card(ITEM_A, start_seq=start_seq, end_seq=end_seq, aliases=["an item people remember"],
                           **over), items=_far_items(), segments=_far_segments())


def test_kept_bounds_carry_the_start_segments_start_and_the_end_segments_end():
    rows, counts = _far(3, 5)
    row = rows[0]
    assert (row["start_seq"], row["end_seq"], row["start_s"], row["end_s"]) == (3, 5, 980.0, 1100.0)
    assert (counts["bounds_kept"], counts["bounds_dropped"]) == (1, 0)


def test_bounds_700_seconds_before_the_placement_are_dropped_and_the_cards_text_kept():
    rows, counts = _far(0, 5)
    row = rows[0]
    assert (row["start_seq"], row["end_seq"], row["start_s"], row["end_s"]) == (None, None, None, None)
    assert row["discussed"] is True and row["card"]["aliases"] == ["an item people remember"]
    assert "an item people remember" in row["search_b"]
    assert (counts["bounds_kept"], counts["bounds_dropped"], counts["discussed"]) == (0, 1, 1)


def test_bounds_starting_550_seconds_before_the_placement_are_kept():
    rows, counts = _far(1, 5)
    assert (rows[0]["start_seq"], rows[0]["start_s"]) == (1, 450.0)
    assert counts["bounds_kept"] == 1


def test_bounds_whose_end_segment_ends_700_seconds_after_the_placement_are_dropped_and_the_text_kept():
    rows, counts = _far(4, 7)
    row = rows[0]
    assert (row["start_seq"], row["end_seq"], row["start_s"], row["end_s"]) == (None, None, None, None)
    assert row["card"]["aliases"] == ["an item people remember"] and "an item people remember" in row["search_b"]
    assert (counts["bounds_kept"], counts["bounds_dropped"]) == (0, 1)


def test_bounds_whose_end_segment_ends_550_seconds_after_the_placement_are_kept():
    rows, counts = _far(4, 6)
    assert (rows[0]["end_seq"], rows[0]["end_s"]) == (6, 1650.0)
    assert counts["bounds_kept"] == 1


def test_bounds_starting_700_seconds_after_the_placements_end_are_dropped():
    rows, counts = _far(7, 7)
    assert rows[0]["start_seq"] is None and rows[0]["end_seq"] is None
    assert counts["bounds_dropped"] == 1


@pytest.mark.parametrize("start_seq, end_seq", [
    (5, 4),        # the end before the start
    (2, 5),        # a silence segment
    (4, 99),       # not a segment
    (None, None),  # the card said discussed and gave no bounds
    (4, None),     # half a pair
])
def test_bounds_that_are_not_an_ordered_pair_of_spoken_segments_are_dropped(start_seq, end_seq):
    rows, counts = _far(start_seq, end_seq)
    assert rows[0]["start_seq"] is None and rows[0]["end_seq"] is None
    assert rows[0]["start_s"] is None and rows[0]["end_s"] is None
    assert (counts["bounds_kept"], counts["bounds_dropped"]) == (0, 1)


def test_a_card_that_says_not_discussed_has_no_bounds_and_is_not_counted_as_dropped():
    rows, counts = _far(4, 5, discussed=False)
    assert rows[0]["discussed"] is False
    assert rows[0]["start_seq"] is None and rows[0]["end_seq"] is None
    assert (counts["discussed"], counts["bounds_kept"], counts["bounds_dropped"]) == (0, 0, 0)


def test_two_cards_with_overlapping_ranges_both_keep_their_bounds():
    # Two items read one after the other and voted together at segment 6.
    items = _items()
    items[1].update(first_seq=4, placed_start_s=40.0, placed_end_s=70.0)
    rows, counts = _validate(_card(ITEM_A, start_seq=2, end_seq=6), _card(ITEM_B, start_seq=4, end_seq=6),
                             items=items)
    assert (_row(rows, ITEM_A)["start_seq"], _row(rows, ITEM_A)["end_seq"]) == (2, 6)
    assert (_row(rows, ITEM_B)["start_seq"], _row(rows, ITEM_B)["end_seq"]) == (4, 6)
    assert (counts["bounds_kept"], counts["bounds_dropped"]) == (2, 0)


def test_starts_moved_counts_kept_starts_twenty_seconds_or_more_from_the_placement():
    items = _items()
    items[0].update(first_seq=4, placed_start_s=40.0)   # placed at 40 s; the card starts at 20 s
    items[1].update(placed_start_s=70.0)                # placed at 70 s; the card starts at 80 s
    rows, counts = _validate(_card(ITEM_A, start_seq=2, end_seq=6), _card(ITEM_B, start_seq=8, end_seq=9),
                             items=items)
    assert (_row(rows, ITEM_A)["start_s"], _row(rows, ITEM_B)["start_s"]) == (20.0, 80.0)
    assert counts["bounds_kept"] == 2 and counts["starts_moved"] == 1


# --- the two search texts -------------------------------------------------------

def _card_58824():
    """The spike's card for item 58824 as the plan's Artifacts and Notes shows it, abridged."""
    return {
        "aliases": ["nightclub safety plan ordinance", "club safety plan rules", "late night establishment rules",
                    "felder ordinance changes", "bar security camera requirement"],
        "spoken_details": [{"text": "Establishments must have cameras with footage kept for up to 30 days.",
                            "seq": 309, "quote": "cameras in place with footage retained for up to 30 days"}],
        "identifiers": [],
        "names": [{"name": "Kelvyn Felder Ordinance", "variants": ["Kelvin Felder Ordinance", "Felder Ordinance"]},
                  {"name": "Phil Morton", "variants": []}, {"name": "Chief Pickett", "variants": []}],
        "outcome": {"result": "passed", "seq": 322},
        "refers_to": {"text": "The Public Safety Committee had recommended this item.", "seq": 324},
    }


def test_search_texts_of_the_item_58824_card():
    search_b, search_c = _cards().search_texts(_card_58824())
    assert "late night establishment rules" in search_b
    assert "Kelvin Felder Ordinance" in search_b and "Phil Morton" in search_b
    assert "footage" in search_c and "footage" not in search_b
    assert "Public Safety Committee" in search_c and "passed" in search_c
    assert "late night" not in search_c
    assert search_b.split(" . ")[:2] == ["nightclub safety plan ordinance", "club safety plan rules"]


def test_search_texts_hold_identifier_values_and_leave_out_an_unclear_outcome_and_a_null_refers_to():
    card = {"aliases": ["recall of the club ordinance"],
            "spoken_details": [],
            "identifiers": [{"kind": "ordinance", "value": "26-50", "seq": None}],
            "names": [], "outcome": {"result": "unclear", "seq": None}, "refers_to": None}
    assert _cards().search_texts(card) == ("recall of the club ordinance . 26-50", "")
    card["outcome"] = {"result": "recalled", "seq": None}
    assert _cards().search_texts(card) == ("recall of the club ordinance . 26-50", "recalled")


def test_validated_rows_carry_the_search_texts_of_their_card():
    rows, _ = _validate(
        _card(ITEM_A, aliases=["Late Night Establishment Rules"],
              identifiers=[{"kind": "ordinance", "value": "26-50", "seq": None}],
              names=[{"name": "Kelvyn Felder Ordinance", "variants": ["Kelvin Felder Ordinance"]}],
              spoken_details=[_detail("Camera footage is kept up to 30 days.", 3,
                                      "footage retained for up to 30 days")],
              outcome={"result": "passed", "seq": 6},
              refers_to={"text": "The committee recommended it.", "seq": None}),
        _card(ITEM_B, discussed=False))
    a, b = _row(rows, ITEM_A), _row(rows, ITEM_B)
    assert (a["search_b"], a["search_c"]) == _cards().search_texts(a["card"])
    assert a["search_b"] == "late night establishment rules . 26-50 . Kelvyn Felder Ordinance . Kelvin Felder Ordinance"
    assert a["search_c"] == "Camera footage is kept up to 30 days. . The committee recommended it. . passed"
    assert (b["search_b"], b["search_c"]) == ("", "")


# --- the meeting renderer --------------------------------------------------------

def test_render_puts_each_marker_before_its_items_first_segment():
    cards = _cards()
    items = _items()
    items[0].update(description="First line.\nSecond   line.", headline="Club safety plans change",
                    why_it_matters="Clubs must file a plan.")
    text = cards.render_cards_input({"title": "Regular City Council Meeting", "meeting_date": "2026-05-05"},
                                    _meeting_segments(), items, {"S1": 1})
    lines = text.split("\n")
    assert lines[0] == "Meeting: Regular City Council Meeting on 2026-05-05"
    at = lines.index(f"=== ITEM MARKER item_id={ITEM_A} (Item 14) ===")
    assert lines[at + 1:at + 6] == [
        "agenda text: An Ordinance to amend the Kelvyn Felder Ordinance",
        "description: First line. Second line.",
        "site headline: Club safety plans change",
        "site summary: Clubs must file a plan.",
        "[seq=2 t=00:00:20 Speaker 1] Item 14, an ordinance to amend the Kelvin Felder ordinance on safety plans.",
    ]
    at = lines.index(f"=== ITEM MARKER item_id={ITEM_B} (Item 15) ===")
    assert lines[at + 1:at + 5] == ["agenda text: A Resolution accepting one vehicle", "description: none",
                                    "site headline: none", "site summary: none"]
    assert lines[at + 5].startswith("[seq=7 t=00:01:10 Speaker 1] Item 15,")
    assert text.count("=== ITEM MARKER") == 2


def test_render_leaves_out_silence_and_empty_segments_and_keeps_seq_order():
    segments = _meeting_segments() + [_seg(12, "   ")]
    text = _cards().render_cards_input({"title": "T", "meeting_date": "2026-05-05"}, list(reversed(segments)),
                                       _items(), {"S1": 1})
    seqs = [int(line.split(" ")[0][len("[seq="):]) for line in text.split("\n") if line.startswith("[seq=")]
    assert seqs == [1, 2, 3, 4, 5, 6, 7, 8, 9, 11]


def test_render_labels_a_speaker_by_the_events_stages_rule():
    segments = [
        _seg(1, "Named with no confidence recorded.", speaker_name="Darrell O'Quinn", speaker_confidence=None),
        _seg(2, "Named confidently.", speaker_name="Valerie Abbott", speaker_confidence=0.9),
        _seg(3, "Named below the floor.", speaker_name="Hunter Williams", speaker_confidence=0.4,
             cluster_label="S7"),
        _seg(4, "No cluster at all.", cluster_label=None),
    ]
    text = _cards().render_cards_input({"title": "T", "meeting_date": "2026-05-05"}, segments, [], {"S7": 3})
    assert "[seq=1 t=00:00:10 Darrell O'Quinn] " in text
    assert "[seq=2 t=00:00:20 Valerie Abbott] " in text
    assert "[seq=3 t=00:00:30 Speaker 3] " in text and "Hunter Williams" not in text
    assert "[seq=4 t=00:00:40 Unknown speaker] " in text


def test_render_cuts_the_description_at_1500_characters_and_keeps_the_title_whole():
    items = _items()[:1]
    items[0].update(title="T" * 2000, description="d" * 1600, item_number=None)
    text = _cards().render_cards_input({"title": "T", "meeting_date": "2026-05-05"}, _meeting_segments(), items,
                                       {"S1": 1})
    lines = text.split("\n")
    assert f"=== ITEM MARKER item_id={ITEM_A} (Item ?) ===" in lines
    assert "agenda text: " + "T" * 2000 in lines
    assert "description: " + "d" * 1500 in lines


def test_render_emits_a_marker_for_an_item_whose_first_segment_is_not_rendered():
    # Every placed item needs a marker, or its card would be missing on every run.
    items = _items()
    items[1].update(first_seq=10)                       # a silence segment: the marker goes before the next line
    items.append({"id": 400, "item_number": "16", "title": "Filed after the last spoken segment",
                  "description": None, "headline": None, "why_it_matters": None,
                  "first_seq": 50, "placed_start_s": 500.0, "placed_end_s": 510.0})
    lines = _cards().render_cards_input({"title": "T", "meeting_date": "2026-05-05"}, _meeting_segments(), items,
                                        {"S1": 1}).split("\n")
    at = lines.index(f"=== ITEM MARKER item_id={ITEM_B} (Item 15) ===")
    assert lines[at + 5].startswith("[seq=11 ")
    assert lines[-5] == "=== ITEM MARKER item_id=400 (Item 16) ==="


def _index_point_items(bundle):
    """Meeting 2543's items as `load_card_items` would return them, placed by a pure index-point pass:
    a non-silence segment is filed under the item whose index point is the latest at or before its start."""
    points = sorted((a["video_timestamp_seconds"], -a["id"], a) for a in bundle.agenda_items
                    if a.get("video_timestamp_seconds") is not None)
    filed: dict[int, list[dict]] = {}
    by_id = {}
    for s in bundle.segments:
        if s["is_silence"]:
            continue
        under = [a for t, _, a in points if t <= s["start_s"]]
        if under:
            filed.setdefault(under[-1]["id"], []).append(s)
            by_id[under[-1]["id"]] = under[-1]
    items = [{"id": item_id, "item_number": by_id[item_id].get("item_number"), "title": by_id[item_id]["title"],
              "description": None, "headline": None, "why_it_matters": None,
              "first_seq": min(s["seq"] for s in segs), "placed_start_s": min(s["start_s"] for s in segs),
              "placed_end_s": max(s["end_s"] for s in segs)} for item_id, segs in filed.items()]
    return sorted(items, key=lambda i: i["first_seq"])


def test_render_of_the_real_meeting_2543_has_one_marker_per_placed_item_before_its_first_segment():
    bundle = load_bundle("transcript_2543")
    items = _index_point_items(bundle)
    assert len(items) == 9   # the nine items the index points place (plan, Context and Orientation)
    ordinals: dict[str, int] = {}
    for s in bundle.segments:
        if not s["is_silence"] and s["cluster_label"]:
            ordinals.setdefault(s["cluster_label"], len(ordinals) + 1)
    text = _cards().render_cards_input(bundle.meeting, bundle.segments, items, ordinals)
    lines = text.split("\n")
    assert lines[0] == "Meeting: Regular City Council Meeting on 2026-10-06"
    markers = [i for i, line in enumerate(lines) if line.startswith("=== ITEM MARKER ")]
    assert len(markers) == 9
    for item, at in zip(items, markers):
        assert lines[at] == f"=== ITEM MARKER item_id={item['id']} (Item {item['item_number']}) ==="
        assert lines[at + 1] == "agenda text: " + " ".join(item["title"].split())
        assert lines[at + 2:at + 5] == ["description: none", "site headline: none", "site summary: none"]
        assert lines[at + 5].startswith(f"[seq={item['first_seq']} t=")
    spoken = [s for s in bundle.segments if not s["is_silence"] and s["text"].strip()]
    assert sum(1 for line in lines if line.startswith("[seq=")) == len(spoken)
    assert "Speaker 1]" in text   # the fixture's speakers are unresolved


# --- the response schema and its models ------------------------------------------

def _objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for v in node.values():
            yield from _objects(v)
    elif isinstance(node, list):
        for v in node:
            yield from _objects(v)


def _nodes(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _nodes(v)


def _is_nullable(node: dict) -> bool:
    return isinstance(node.get("type"), list) or "anyOf" in node


def test_cards_schema_objects_list_every_property_as_required_and_are_closed():
    objects = list(_objects(_schemas().CARDS_SCHEMA))
    assert len(objects) == 7   # the reply, a card, and the five nested shapes
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert obj["required"] == list(obj["properties"])


def test_cards_schema_has_five_nullable_types_and_no_enum_beside_one():
    nodes = list(_nodes(_schemas().CARDS_SCHEMA))
    nullable = [n for n in nodes if _is_nullable(n)]
    assert len(nullable) == 5 and len(nullable) <= 16   # decision 0031: the API caps nullable fields at 16
    assert all("enum" not in n for n in nullable)
    assert all(None not in n["enum"] for n in nodes if "enum" in n)


def test_cards_schema_names_the_fields_the_plan_names():
    S = _schemas()
    card = S.CARDS_SCHEMA["properties"]["cards"]["items"]["properties"]
    assert list(card) == ["item_id", "discussed", "start_seq", "end_seq", "aliases", "spoken_details",
                          "identifiers", "names", "outcome", "refers_to"]
    assert list(card["spoken_details"]["items"]["properties"]) == ["text", "seq", "quote"]
    assert card["spoken_details"]["items"]["properties"]["seq"] == {"type": "integer"}
    assert card["identifiers"]["items"]["properties"]["kind"]["enum"] == list(S.IDENTIFIER_KINDS)
    assert card["outcome"]["properties"]["result"]["enum"] == list(S.CARD_OUTCOMES)
    assert list(card["names"]["items"]["properties"]) == ["name", "variants"]
    assert list(card["refers_to"]["properties"]) == ["text", "seq"]
    assert S.CARD_OUTCOMES == ("passed", "failed", "delayed", "withdrawn", "recalled", "referred", "no_action",
                               "unclear")
    assert S.IDENTIFIER_KINDS == ("ordinance", "resolution", "case", "contract", "agenda_number", "other")


def test_card_models_accept_what_the_schema_allows_and_refuse_an_unknown_outcome_or_kind():
    S = _schemas()
    card = S.SearchCard.model_validate(_card(
        ITEM_A, start_seq=2, end_seq=6, aliases=["club safety plan rules"],
        spoken_details=[_detail("Footage is kept 30 days.", 3, "footage retained for up to 30 days")],
        identifiers=[{"kind": "ordinance", "value": "26-50", "seq": None}],
        names=[{"name": "Kelvyn Felder Ordinance", "variants": ["Kelvin Felder Ordinance"]}],
        outcome={"result": "recalled", "seq": 6}, refers_to={"text": "", "seq": None}))
    assert card.outcome.result == "recalled" and card.identifiers[0].seq is None and card.refers_to.text == ""
    assert isinstance(card.spoken_details[0], S.SpokenDetail) and isinstance(card.names[0], S.CardName)
    with pytest.raises(ValidationError):
        S.SearchCard.model_validate(_card(ITEM_A, outcome={"result": "tabled", "seq": None}))
    with pytest.raises(ValidationError):
        S.SearchCard.model_validate(_card(ITEM_A, identifiers=[{"kind": "permit", "value": "1", "seq": None}]))
    with pytest.raises(ValidationError):
        S.CardList.model_validate({"cards": [{"item_id": ITEM_A}]})


def test_card_models_allow_exactly_the_outcomes_and_kinds_the_schema_lists():
    from typing import get_args

    S = _schemas()
    assert get_args(S.CardOutcome.model_fields["result"].annotation) == S.CARD_OUTCOMES
    assert get_args(S.CardIdentifier.model_fields["kind"].annotation) == S.IDENTIFIER_KINDS


# --- the prompt -------------------------------------------------------------------

def test_cards_prompt_is_version_200_and_carries_the_quote_rule_and_the_marker_format():
    from docket.ai.transcripts import prompts as P

    assert P.CARDS_PROMPT_VERSION == 200
    assert P._QUOTE_RULE in P.CARDS_SYSTEM and "{_QUOTE_RULE}" not in P.CARDS_SYSTEM
    assert "=== ITEM MARKER item_id=N (Item <number>) ===" in P.CARDS_SYSTEM
    assert "[seq=N t=HH:MM:SS Speaker] text" in P.CARDS_SYSTEM
    assert "Return one card for every ITEM MARKER" in P.CARDS_SYSTEM
    assert "A card is never shown to readers." in P.CARDS_SYSTEM
    assert 'Otherwise text is "" and seq is null.' in P.CARDS_SYSTEM
    assert P.CARDS_SYSTEM.rstrip().endswith("Return JSON only.")


def test_cards_prompt_names_every_outcome_and_identifier_kind_the_schema_allows():
    from docket.ai.transcripts import prompts as P

    S = _schemas()
    assert "result is one of " + ", ".join(S.CARD_OUTCOMES) in P.CARDS_SYSTEM
    assert "kind is one of " + ", ".join(S.IDENTIFIER_KINDS) in P.CARDS_SYSTEM


def test_the_markers_the_renderer_writes_are_the_markers_the_prompt_describes():
    text = _cards().render_cards_input({"title": "T", "meeting_date": "2026-05-05"}, _meeting_segments(), _items(),
                                       {"S1": 1})
    marker = next(line for line in text.split("\n") if line.startswith("==="))
    assert marker.startswith("=== ITEM MARKER item_id=") and marker.endswith(" (Item 14) ===")
