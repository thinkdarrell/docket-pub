"""The "How it works" explainer's content, and the loader that reads it.

Plan `how-it-works-explainer`, M1. The first group reads the real Birmingham
content under `content/how-it-works/birmingham/`; the second builds small
explainers in a temporary directory to show what the loader refuses.

`docket.services.how_it_works` is imported inside each test, not at the top
of the module, so the file collects before the module exists.

M3 adds the journeys: the real parking-fines journey, and what the loader
refuses in a journey file.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
import yaml

BIRMINGHAM = Path(__file__).resolve().parents[2] / "content" / "how-it-works" / "birmingham"

MAIN_STOPS = ["submitted", "committee", "agenda", "first_reading", "final_vote", "mayor", "in_effect"]
SIDE_ROUTES = ["consent", "hearing", "held_over"]

SOURCE_TEXT = (
    "Sec. 1. Every ordinance shall be read aloud before the vote.\n"
    "The clerk shall keep a record of each vote.\n"
    "The mayor's “veto” must be in writing.\n"
)


def _write_city(
    tmp_path: Path,
    *,
    rules=None,
    stops=None,
    open_questions=None,
    sources_read: str = "2026-11-12",
    source_text: str = SOURCE_TEXT,
) -> Path:
    """A minimal, valid explainer in ``tmp_path``; pass ``rules`` or ``stops`` to break it."""
    city_dir = tmp_path / "testville"
    (city_dir / "sources").mkdir(parents=True)
    (city_dir / "sources" / "code.txt").write_text(source_text, encoding="utf-8")
    if rules is None:
        rules = [_rule()]
    if stops is None:
        stops = [
            {
                "key": "committee",
                "name": "Committee",
                "side_route_of": None,
                "description": "A committee looks at it.",
                "rules": rules,
            }
        ]
    doc = {
        "city": "testville",
        "sources_read": "SOURCES_READ",
        "stops": stops,
        "open_questions": (
            [{"heading": "One thing", "body": "Nobody knows."}] if open_questions is None else open_questions
        ),
    }
    text = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
    # Written unquoted, so a date reaches the loader as a YAML date.
    text = text.replace("SOURCES_READ", sources_read)
    (city_dir / "explainer.yaml").write_text(text, encoding="utf-8")
    return city_dir


def _rule(**overrides) -> dict:
    rule = {
        "statement": "Ordinances are read aloud.",
        "quote": "Every ordinance shall be read aloud before the vote.",
        "citation": "Code §1",
        "url": "https://example.org/code",
        "source_file": "code.txt",
    }
    rule.update(overrides)
    return {k: v for k, v in rule.items() if v is not None}


# --- the real Birmingham content -------------------------------------------


def test_birmingham_explainer_loads_with_the_path_in_order():
    from docket.services.how_it_works import load_explainer

    explainer = load_explainer(BIRMINGHAM)

    assert explainer.city == "birmingham"
    assert explainer.sources_read.isoformat() == "2026-11-12"
    assert [s.key for s in explainer.stops if s.side_route_of is None] == MAIN_STOPS
    assert [s.key for s in explainer.stops if s.side_route_of is not None] == SIDE_ROUTES
    hangs_under = {s.key: s.side_route_of for s in explainer.stops if s.side_route_of}
    assert hangs_under == {"consent": "agenda", "hearing": "agenda", "held_over": "first_reading"}
    assert explainer.journeys[0].key == "parking-fines"


def test_birmingham_every_stop_has_a_description_and_rules():
    from docket.services.how_it_works import load_explainer

    for stop in load_explainer(BIRMINGHAM).stops:
        assert stop.name.strip(), stop.key
        assert stop.description.strip(), stop.key
        assert len(stop.rules) >= 1, stop.key


def test_birmingham_every_rule_has_a_citation_and_an_https_link():
    from docket.services.how_it_works import load_explainer

    for stop in load_explainer(BIRMINGHAM).stops:
        for rule in stop.rules:
            assert rule.statement.strip(), (stop.key, rule)
            assert rule.citation.strip(), (stop.key, rule.statement)
            assert rule.url.startswith("https://"), (stop.key, rule.statement)


def test_birmingham_every_quote_is_found_in_its_source_file():
    """Checked here independently of the loader's own check, piece by piece."""
    from docket.services.how_it_works import load_explainer, normalise_for_quote_check

    checked = 0
    for stop in load_explainer(BIRMINGHAM).stops:
        for rule in stop.rules:
            if rule.quote is None:
                continue
            assert rule.source_file, (stop.key, rule.citation)
            source = normalise_for_quote_check(
                (BIRMINGHAM / "sources" / rule.source_file).read_text(encoding="utf-8")
            )
            position = 0
            for piece in re.split(r"…|\.\.\.", rule.quote):
                piece = normalise_for_quote_check(piece)
                found = source.find(piece, position)
                assert found >= 0, f"{stop.key} / {rule.citation}: not in {rule.source_file}: {piece!r}"
                position = found + len(piece)
            checked += 1
    assert checked >= 40


def test_birmingham_has_exactly_seven_open_questions():
    from docket.services.how_it_works import load_explainer

    questions = load_explainer(BIRMINGHAM).open_questions
    assert len(questions) == 7
    for heading, body in questions:
        assert heading.strip() and body.strip()


def test_how_it_works_root_is_configured():
    from docket import config

    assert config.HOW_IT_WORKS_ROOT == "content/how-it-works"


# --- what the normaliser does ----------------------------------------------


def test_normalise_collapses_whitespace_and_straightens_quote_marks():
    from docket.services.how_it_works import normalise_for_quote_check

    assert normalise_for_quote_check("  a\n\n b\t c  ") == "a b c"
    assert normalise_for_quote_check("“Consent” and the mayor’s ‘veto’") == (
        "\"Consent\" and the mayor's 'veto'"
    )
    assert normalise_for_quote_check("Where") != normalise_for_quote_check("where")


# --- what the loader accepts and refuses, on a temporary directory ----------


def test_a_valid_temporary_explainer_loads(tmp_path):
    from docket.services.how_it_works import load_explainer

    explainer = load_explainer(_write_city(tmp_path))

    assert explainer.city == "testville"
    assert explainer.stops[0].rules[0].source_file == "code.txt"
    assert explainer.open_questions == (("One thing", "Nobody knows."),)


def test_a_quotation_that_is_not_in_its_source_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    city_dir = _write_city(tmp_path, rules=[_rule(quote="Every ordinance shall be sung aloud before the vote.")])

    with pytest.raises(ExplainerError) as raised:
        load_explainer(city_dir)
    message = str(raised.value)
    assert "explainer.yaml" in message
    assert "stops[0].rules[0].quote" in message
    assert "Code §1" in message
    assert "code.txt" in message


def test_an_elided_quotation_with_its_pieces_in_order_loads(tmp_path):
    from docket.services.how_it_works import load_explainer

    quotes = (
        "Every ordinance shall be read aloud … The clerk shall keep a record",
        "Every ordinance shall be read aloud ... The clerk shall keep a record",
    )
    for n, quote in enumerate(quotes):
        explainer = load_explainer(_write_city(tmp_path / str(n), rules=[_rule(quote=quote)]))
        assert explainer.stops[0].rules[0].quote == quote


def test_an_elided_quotation_with_its_pieces_in_the_wrong_order_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    city_dir = _write_city(
        tmp_path,
        rules=[_rule(quote="The clerk shall keep a record … Every ordinance shall be read aloud")],
    )

    with pytest.raises(ExplainerError, match=r"stops\[0\]\.rules\[0\]\.quote"):
        load_explainer(city_dir)


def test_an_elided_quotation_with_one_piece_absent_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    city_dir = _write_city(
        tmp_path,
        rules=[_rule(quote="Every ordinance shall be read aloud … The clerk shall burn the record")],
    )

    with pytest.raises(ExplainerError, match=r"stops\[0\]\.rules\[0\]\.quote"):
        load_explainer(city_dir)


def test_a_piece_may_not_be_found_inside_the_piece_before_it(tmp_path):
    """Each piece is looked for after the END of the one before, not after its start."""
    from docket.services.how_it_works import ExplainerError, load_explainer

    city_dir = _write_city(
        tmp_path,
        rules=[_rule(quote="Every ordinance shall be read aloud … read aloud before the vote")],
    )

    with pytest.raises(ExplainerError, match=r"stops\[0\]\.rules\[0\]\.quote"):
        load_explainer(city_dir)


def test_a_quotation_matches_across_line_breaks_and_curly_quote_marks(tmp_path):
    from docket.services.how_it_works import load_explainer

    quote = "before the vote. The clerk shall keep a record of each vote. The mayor's \"veto\" must be in writing."
    explainer = load_explainer(_write_city(tmp_path, rules=[_rule(quote=quote)]))

    assert explainer.stops[0].rules[0].quote == quote


def test_a_quotation_is_compared_case_sensitively(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    city_dir = _write_city(tmp_path, rules=[_rule(quote="every ordinance shall be read aloud")])

    with pytest.raises(ExplainerError, match=r"stops\[0\]\.rules\[0\]\.quote"):
        load_explainer(city_dir)


def test_a_quotation_of_nothing_but_an_ellipsis_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"stops\[0\]\.rules\[0\]\.quote"):
        load_explainer(_write_city(tmp_path, rules=[_rule(quote="…")]))


def test_a_rule_without_a_quotation_needs_no_source_file(tmp_path):
    from docket.services.how_it_works import load_explainer

    explainer = load_explainer(_write_city(tmp_path, rules=[_rule(quote=None, source_file=None)]))

    rule = explainer.stops[0].rules[0]
    assert rule.quote is None and rule.source_file is None
    assert rule.citation == "Code §1"


def test_a_stop_with_no_rules_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"explainer\.yaml.*stops\[0\]\.rules"):
        load_explainer(_write_city(tmp_path, rules=[]))


def test_a_rule_with_no_citation_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"stops\[0\]\.rules\[0\]\.citation"):
        load_explainer(_write_city(tmp_path, rules=[_rule(citation=None)]))


def test_a_rule_with_no_link_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"stops\[0\]\.rules\[0\]\.url"):
        load_explainer(_write_city(tmp_path, rules=[_rule(url=None)]))


def test_a_rule_whose_link_is_not_https_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"stops\[0\]\.rules\[0\]\.url"):
        load_explainer(_write_city(tmp_path, rules=[_rule(url="http://example.org/code")]))


def test_a_quotation_with_no_source_file_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"stops\[0\]\.rules\[0\]\.source_file"):
        load_explainer(_write_city(tmp_path, rules=[_rule(source_file=None)]))


def test_a_source_file_that_does_not_exist_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"stops\[0\]\.rules\[0\]\.source_file.*missing\.txt"):
        load_explainer(_write_city(tmp_path, rules=[_rule(source_file="missing.txt")]))

    with pytest.raises(ExplainerError, match=r"stops\[0\]\.rules\[0\]\.source_file.*missing\.txt"):
        load_explainer(_write_city(tmp_path / "unquoted", rules=[_rule(quote=None, source_file="missing.txt")]))


def test_a_source_file_outside_the_sources_directory_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    city_dir = _write_city(tmp_path, rules=[_rule(source_file="../explainer.yaml", quote=None)])

    with pytest.raises(ExplainerError, match=r"stops\[0\]\.rules\[0\]\.source_file"):
        load_explainer(city_dir)


def test_a_side_route_hung_under_a_stop_that_is_not_on_the_path_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    stops = [
        {"key": "agenda", "name": "On the agenda", "side_route_of": None, "description": "d", "rules": [_rule()]},
        {"key": "consent", "name": "Consent", "side_route_of": "nowhere", "description": "d", "rules": [_rule()]},
    ]

    with pytest.raises(ExplainerError, match=r"stops\[1\]\.side_route_of.*nowhere"):
        load_explainer(_write_city(tmp_path, stops=stops))


def test_a_side_route_hung_under_another_side_route_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    stops = [
        {"key": "agenda", "name": "On the agenda", "side_route_of": None, "description": "d", "rules": [_rule()]},
        {"key": "consent", "name": "Consent", "side_route_of": "agenda", "description": "d", "rules": [_rule()]},
        {"key": "pulled", "name": "Pulled", "side_route_of": "consent", "description": "d", "rules": [_rule()]},
    ]

    with pytest.raises(ExplainerError, match=r"stops\[2\]\.side_route_of.*consent"):
        load_explainer(_write_city(tmp_path, stops=stops))


def test_two_stops_with_the_same_key_raise(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    stop = {"key": "agenda", "name": "On the agenda", "side_route_of": None, "description": "d", "rules": [_rule()]}

    with pytest.raises(ExplainerError, match=r"stops\[1\]\.key.*agenda"):
        load_explainer(_write_city(tmp_path, stops=[stop, dict(stop)]))


def test_a_missing_explainer_file_raises_naming_it(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"explainer\.yaml"):
        load_explainer(tmp_path / "nowhere")


def test_a_stop_with_no_description_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    stops = [{"key": "agenda", "name": "On the agenda", "side_route_of": None, "rules": [_rule()]}]

    with pytest.raises(ExplainerError, match=r"stops\[0\]\.description"):
        load_explainer(_write_city(tmp_path, stops=stops))


def test_an_open_question_needs_a_heading_and_a_body(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"open_questions\[0\]\.body"):
        load_explainer(_write_city(tmp_path / "a", open_questions=[{"heading": "One thing"}]))
    with pytest.raises(ExplainerError, match=r"open_questions\[0\]\.heading"):
        load_explainer(_write_city(tmp_path / "b", open_questions=[{"body": "Nobody knows."}]))


def test_the_date_the_sources_were_read_must_be_a_date(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"sources_read"):
        load_explainer(_write_city(tmp_path, sources_read="last Thursday"))


# --- journeys: the real one (plan how-it-works-explainer, M3) ---------------


def _parking_fines():
    from docket.services.how_it_works import load_explainer

    journeys = {j.key: j for j in load_explainer(BIRMINGHAM).journeys}
    return journeys["parking-fines"]


def test_the_parking_fines_journey_loads_with_eight_stops():
    journey = _parking_fines()

    assert journey.label == "Parking fines ordinance"
    assert "unanimous consent" in journey.note
    assert "Section 8" in journey.note
    assert journey.title.startswith("An Ordinance to amend Title 8, Chapter 3, Section 10")
    assert len(journey.stops) == 8
    assert [s.stops for s in journey.stops] == [
        ("submitted",),
        ("committee",),
        ("agenda", "first_reading"),
        ("first_reading",),
        ("held_over",),
        ("final_vote",),
        ("mayor",),
        ("in_effect",),
    ]


def test_the_parking_fines_stops_with_no_record_are_submitted_mayor_and_in_effect():
    journey = _parking_fines()

    without = [s for s in journey.stops if s.record == "none"]
    assert [s.stops for s in without] == [("submitted",), ("mayor",), ("in_effect",)]
    for stop in without:
        assert stop.gap
        assert stop.meeting_id is None and stop.date is None
    assert not [s for s in journey.stops if s.record == "not_on_route"]


def test_the_parking_fines_stops_carry_the_records_they_rest_on():
    journey = _parking_fines()
    by_date = {(s.date.isoformat(), s.stops): s for s in journey.stops if s.date}

    committee = by_date[("2026-05-11", ("committee",))]
    assert (committee.record, committee.meeting_id, committee.item_id) == ("committee_minutes", 3142, None)
    assert committee.source_file == "committee-transportation-minutes-2026-05-11.txt"
    assert committee.document_label == "Committee minutes"
    assert committee.document_url.startswith("https://")

    withdrawn = by_date[("2026-05-19", ("agenda", "first_reading"))]
    assert (withdrawn.record, withdrawn.meeting_id, withdrawn.item_id, withdrawn.seconds) == (
        "transcript", 2232, 58893, 2506)

    voted = by_date[("2026-05-26", ("first_reading",))]
    assert (voted.record, voted.meeting_id, voted.item_id, voted.seconds) == ("minutes", 2237, 58990, None)
    assert "Three ayes" in voted.text and "Six nays" in voted.text

    held = by_date[("2026-06-02", ("held_over",))]
    assert held.quote == "(Did Not Receive Unanimous Consent, Held Over from 5/26/2026 to 6/2/2026)"

    final = by_date[("2026-06-02", ("final_vote",))]
    assert (final.record, final.meeting_id, final.item_id, final.seconds) == ("minutes", 2238, 59026, 5313)
    assert "Ordinance No. 26-61" in final.text


def test_every_birmingham_journey_quotation_with_a_source_file_is_in_it():
    from docket.services.how_it_works import load_explainer, normalise_for_quote_check

    checked = 0
    for journey in load_explainer(BIRMINGHAM).journeys:
        for stop in journey.stops:
            if stop.source_file is None:
                continue
            source = normalise_for_quote_check((BIRMINGHAM / "sources" / stop.source_file).read_text(encoding="utf-8"))
            position = 0
            for piece in re.split(r"…|\.\.\.", stop.quote):
                piece = normalise_for_quote_check(piece)
                found = source.find(piece, position)
                assert found >= 0, (journey.key, stop.stops, piece)
                position = found + len(piece)
            checked += 1
    assert checked >= 1


# --- journeys: what the loader accepts and refuses --------------------------

PATH_STOPS = [
    {"key": "committee", "name": "Committee", "side_route_of": None, "description": "d", "rules": None},
    {"key": "agenda", "name": "On the agenda", "side_route_of": None, "description": "d", "rules": None},
    {"key": "consent", "name": "Consent", "side_route_of": "agenda", "description": "d", "rules": None},
]


def _recorded(**overrides) -> dict:
    stop = {
        "stops": ["committee"],
        "date": date(2026, 5, 11),
        "record": "minutes",
        "text": "The committee recommended it.",
        "meeting_id": 7,
    }
    stop.update(overrides)
    return {k: v for k, v in stop.items() if v is not None}


def _gap(**overrides) -> dict:
    stop = {"stops": ["agenda"], "record": "none", "text": "Nothing is published.", "gap": "The site holds no record."}
    stop.update(overrides)
    return {k: v for k, v in stop.items() if v is not None}


def _write_journeys(tmp_path: Path, *journeys, names=None) -> Path:
    """A two-stop path with one side route, and the given journeys beside it.

    Each journey is a list of journey stops, or a whole mapping. The files are
    named ``names[i]``, or ``<i>-<key>.yaml``.
    """
    stops = [dict(stop, rules=[_rule()]) for stop in PATH_STOPS]
    city_dir = _write_city(tmp_path, stops=stops)
    (city_dir / "journeys").mkdir()
    for i, journey in enumerate(journeys):
        if isinstance(journey, list):
            journey = {"key": f"journey-{i}", "label": "A journey", "note": "A note.", "title": "A title.",
                       "stops": journey}
        name = names[i] if names else f"{i}-{journey.get('key', 'x')}.yaml"
        (city_dir / "journeys" / name).write_text(
            yaml.safe_dump(journey, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return city_dir


def test_a_city_with_no_journeys_directory_has_no_journeys(tmp_path):
    from docket.services.how_it_works import load_explainer

    assert load_explainer(_write_city(tmp_path)).journeys == ()


def test_a_valid_journey_loads_with_every_field(tmp_path):
    from docket.services.how_it_works import Journey, JourneyStop, load_explainer

    full = _recorded(
        stops=["agenda", "consent"],
        record="committee_minutes",
        quote="Every ordinance shall be read aloud before the vote.",
        source_file="code.txt",
        item_id=9,
        seconds=120,
        document={"label": "Committee minutes", "url": "https://example.org/minutes.pdf"},
    )
    explainer = load_explainer(_write_journeys(tmp_path, [_recorded(), full]))

    assert len(explainer.journeys) == 1
    journey = explainer.journeys[0]
    assert isinstance(journey, Journey)
    assert (journey.key, journey.label, journey.note, journey.title) == (
        "journey-0", "A journey", "A note.", "A title.")
    plain, rich = journey.stops
    assert plain == JourneyStop(
        stops=("committee",), date=date(2026, 5, 11), record="minutes", text="The committee recommended it.",
        quote=None, source_file=None, meeting_id=7, item_id=None, seconds=None,
        document_label=None, document_url=None, gap=None)
    assert rich == JourneyStop(
        stops=("agenda", "consent"), date=date(2026, 5, 11), record="committee_minutes",
        text="The committee recommended it.", quote="Every ordinance shall be read aloud before the vote.",
        source_file="code.txt", meeting_id=7, item_id=9, seconds=120,
        document_label="Committee minutes", document_url="https://example.org/minutes.pdf", gap=None)


def test_a_stop_with_no_record_loads_with_its_reason(tmp_path):
    from docket.services.how_it_works import load_explainer

    explainer = load_explainer(_write_journeys(tmp_path, [_recorded(), _gap()]))

    gap = explainer.journeys[0].stops[1]
    assert (gap.record, gap.gap, gap.meeting_id, gap.date) == ("none", "The site holds no record.", None, None)


def test_journeys_load_in_file_name_order(tmp_path):
    from docket.services.how_it_works import load_explainer

    def journey(key):
        return {"key": key, "label": key, "note": "n", "title": "t", "stops": [_recorded(), _gap()]}

    city_dir = _write_journeys(
        tmp_path, journey("zebra"), journey("apple"), journey("mango"),
        names=["1-zebra.yaml", "3-apple.yaml", "2-mango.yaml"])
    (city_dir / "journeys" / "notes.txt").write_text("not a journey\n", encoding="utf-8")

    assert [j.key for j in load_explainer(city_dir).journeys] == ["zebra", "mango", "apple"]


def test_a_journey_stop_whose_key_is_not_on_the_path_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    city_dir = _write_journeys(tmp_path, [_recorded(), _gap(), _recorded(stops=["committee", "second_reading"])])

    with pytest.raises(ExplainerError) as raised:
        load_explainer(city_dir)
    message = str(raised.value)
    assert "0-journey-0.yaml" in message
    assert "stops[2].stops" in message
    assert "second_reading" in message


def test_a_journey_that_names_no_stop_for_a_main_stop_raises_naming_it(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"0-journey-0\.yaml: stops: .*'agenda'"):
        load_explainer(_write_journeys(tmp_path, [_recorded()]))


def test_a_side_route_does_not_stand_in_for_the_main_stop_it_hangs_under(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"stops: .*'agenda'"):
        load_explainer(_write_journeys(tmp_path, [_recorded(), _recorded(stops=["consent"])]))


def test_a_journey_need_not_name_a_side_route(tmp_path):
    from docket.services.how_it_works import load_explainer

    explainer = load_explainer(_write_journeys(tmp_path, [_recorded(), _gap()]))

    assert all("consent" not in stop.stops for stop in explainer.journeys[0].stops)


def test_a_journey_quotation_that_its_source_file_does_not_hold_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    stop = _recorded(quote="Every ordinance shall be sung aloud before the vote.", source_file="code.txt")

    with pytest.raises(ExplainerError) as raised:
        load_explainer(_write_journeys(tmp_path, [stop, _gap()]))
    message = str(raised.value)
    assert "stops[0].quote" in message
    assert "code.txt" in message


def test_a_journey_quotation_with_no_source_file_is_not_checked(tmp_path):
    from docket.services.how_it_works import load_explainer

    stop = _recorded(quote="Words copied by hand from a record that is not saved.")

    explainer = load_explainer(_write_journeys(tmp_path, [stop, _gap()]))
    assert explainer.journeys[0].stops[0].source_file is None


def test_a_journey_source_file_that_does_not_exist_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    stop = _recorded(quote="Every ordinance shall be read aloud before the vote.", source_file="absent.txt")
    with pytest.raises(ExplainerError, match=r"stops\[0\]\.source_file"):
        load_explainer(_write_journeys(tmp_path / "a", [stop, _gap()]))

    stop = _recorded(quote="city: testville", source_file="../explainer.yaml")
    with pytest.raises(ExplainerError, match=r"stops\[0\]\.source_file"):
        load_explainer(_write_journeys(tmp_path / "b", [stop, _gap()]))


def test_a_journey_source_file_with_no_quotation_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"stops\[0\]\.quote"):
        load_explainer(_write_journeys(tmp_path, [_recorded(source_file="code.txt"), _gap()]))


@pytest.mark.parametrize("record", ["none", "not_on_route"])
def test_a_stop_with_no_record_needs_a_reason(tmp_path, record):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"stops\[1\]\.gap"):
        load_explainer(_write_journeys(tmp_path, [_recorded(), _gap(record=record, gap=None)]))


@pytest.mark.parametrize("record", ["none", "not_on_route"])
def test_a_stop_with_no_record_may_not_name_a_meeting(tmp_path, record):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"stops\[1\]\.meeting_id"):
        load_explainer(_write_journeys(tmp_path, [_recorded(), _gap(record=record, meeting_id=7)]))


@pytest.mark.parametrize("record", ["none", "not_on_route"])
def test_a_stop_with_no_record_may_not_carry_a_date(tmp_path, record):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"stops\[1\]\.date"):
        load_explainer(_write_journeys(tmp_path, [_recorded(), _gap(record=record, date=date(2026, 6, 12))]))


def test_a_journey_stop_key_that_is_not_text_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"stops\[0\]\.stops"):
        load_explainer(_write_journeys(tmp_path, [_recorded(stops=[["committee"]]), _gap()]))


def test_a_stop_not_on_the_route_loads(tmp_path):
    from docket.services.how_it_works import load_explainer

    explainer = load_explainer(_write_journeys(tmp_path, [_recorded(), _gap(record="not_on_route")]))
    assert explainer.journeys[0].stops[1].record == "not_on_route"


def test_a_recorded_stop_needs_a_date_and_a_meeting(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"stops\[0\]\.meeting_id"):
        load_explainer(_write_journeys(tmp_path / "a", [_recorded(meeting_id=None), _gap()]))
    with pytest.raises(ExplainerError, match=r"stops\[0\]\.date"):
        load_explainer(_write_journeys(tmp_path / "b", [_recorded(date=None), _gap()]))
    with pytest.raises(ExplainerError, match=r"stops\[0\]\.date"):
        load_explainer(_write_journeys(tmp_path / "c", [_recorded(date="May 11"), _gap()]))


def test_a_record_that_is_not_one_of_the_seven_kinds_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"stops\[0\]\.record.*hearsay"):
        load_explainer(_write_journeys(tmp_path, [_recorded(record="hearsay"), _gap()]))


@pytest.mark.parametrize("record", ["minutes", "agenda", "video", "transcript", "committee_minutes"])
def test_each_kind_of_record_loads(tmp_path, record):
    from docket.services.how_it_works import load_explainer

    explainer = load_explainer(_write_journeys(tmp_path, [_recorded(record=record), _gap()]))
    assert explainer.journeys[0].stops[0].record == record


@pytest.mark.parametrize("field", ["meeting_id", "item_id", "seconds"])
def test_an_id_or_a_cue_must_be_a_whole_number(tmp_path, field):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=rf"stops\[0\]\.{field}"):
        load_explainer(_write_journeys(tmp_path / "a", [_recorded(**{field: "2238"}), _gap()]))
    with pytest.raises(ExplainerError, match=rf"stops\[0\]\.{field}"):
        load_explainer(_write_journeys(tmp_path / "b", [_recorded(**{field: True}), _gap()]))


def test_a_journey_stop_must_name_at_least_one_path_stop(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"stops\[2\]\.stops"):
        load_explainer(_write_journeys(tmp_path, [_recorded(), _gap(), _recorded(stops=[])]))


def test_a_journey_stop_needs_its_text(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    with pytest.raises(ExplainerError, match=r"stops\[0\]\.text"):
        load_explainer(_write_journeys(tmp_path, [_recorded(text=None), _gap()]))


def test_a_document_needs_a_label_and_an_https_address(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    cases = {
        "a": ({"url": "https://example.org/m.pdf"}, r"stops\[0\]\.document\.label"),
        "b": ({"label": "Committee minutes"}, r"stops\[0\]\.document\.url"),
        "c": ({"label": "Committee minutes", "url": "http://example.org/m.pdf"}, r"stops\[0\]\.document\.url"),
    }
    for name, (document, where) in cases.items():
        with pytest.raises(ExplainerError, match=where):
            load_explainer(_write_journeys(tmp_path / name, [_recorded(document=document), _gap()]))


def test_a_journey_needs_its_key_label_note_and_title(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    for field in ("key", "label", "note", "title"):
        journey = {"key": "k", "label": "l", "note": "n", "title": "t", "stops": [_recorded(), _gap()]}
        del journey[field]
        with pytest.raises(ExplainerError, match=rf"the file\.{field}"):
            load_explainer(_write_journeys(tmp_path / field, journey, names=["only.yaml"]))


def test_a_journey_with_no_stops_raises(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    journey = {"key": "k", "label": "l", "note": "n", "title": "t", "stops": []}
    with pytest.raises(ExplainerError, match=r"only\.yaml: stops"):
        load_explainer(_write_journeys(tmp_path, journey, names=["only.yaml"]))


def test_two_journeys_with_the_same_key_raise(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    def journey():
        return {"key": "twin", "label": "l", "note": "n", "title": "t", "stops": [_recorded(), _gap()]}

    with pytest.raises(ExplainerError, match=r"2-twin\.yaml: the file\.key.*twin.*1-twin\.yaml"):
        load_explainer(_write_journeys(tmp_path, journey(), journey(), names=["1-twin.yaml", "2-twin.yaml"]))


def test_a_journey_file_that_is_not_valid_yaml_raises_naming_it(tmp_path):
    from docket.services.how_it_works import ExplainerError, load_explainer

    city_dir = _write_journeys(tmp_path, [_recorded(), _gap()])
    (city_dir / "journeys" / "broken.yaml").write_text("key: [unclosed\n", encoding="utf-8")

    with pytest.raises(ExplainerError, match=r"broken\.yaml"):
        load_explainer(city_dir)


# --- journeys: the three further ones (plan how-it-works-explainer, M4) -----

NO_FIRST_READING = "The agenda does not mark this resolution as a first reading."


def _journeys_by_key():
    from docket.services.how_it_works import load_explainer

    return {j.key: j for j in load_explainer(BIRMINGHAM).journeys}


def _shape(journey):
    return [(s.stops, s.record) for s in journey.stops]


def _recorded_rows(journey):
    return [(s.date.isoformat(), s.meeting_id, s.item_id, s.seconds) for s in journey.stops if s.date]


def test_birmingham_has_four_journeys_in_the_pickers_order():
    from docket.services.how_it_works import load_explainer

    journeys = load_explainer(BIRMINGHAM).journeys

    assert [(j.key, j.label) for j in journeys] == [
        ("parking-fines", "Parking fines ordinance"),
        ("rezoning-huffman-road", "A rezoning with a split recommendation"),
        ("liquor-licence-legion-field", "A liquor licence with a hearing"),
        ("consent-avondale-park", "A routine contract on consent"),
    ]


def test_the_journey_files_are_numbered_one_to_four_and_their_keys_are_not():
    names = sorted(p.name for p in (BIRMINGHAM / "journeys").glob("*.yaml"))

    assert names == [
        "1-parking-fines.yaml",
        "2-rezoning-huffman-road.yaml",
        "3-liquor-licence-legion-field.yaml",
        "4-consent-avondale-park.yaml",
    ]


def test_the_rezoning_journey_has_six_stops_on_the_records_it_rests_on():
    journey = _journeys_by_key()["rezoning-huffman-road"]

    assert _shape(journey) == [
        (("submitted",), "none"),
        (("committee",), "none"),
        (("committee",), "committee_minutes"),
        (("agenda", "first_reading"), "agenda"),
        (("hearing", "final_vote"), "video"),
        (("mayor", "in_effect"), "none"),
    ]
    assert _recorded_rows(journey) == [
        ("2026-09-08", 3172, None, None),
        ("2026-09-15", 2487, 61883, 3320),
        ("2026-10-13", 2609, 62781, 2662),
    ]
    assert journey.stops[1].quote == "(NOT Recommended by the ZAC)"
    assert "Zoning Advisory Committee" in journey.stops[1].gap
    assert journey.stops[2].document_url.endswith("September%208%2C%202026.pdf")
    assert "8 to 0" in journey.stops[4].text and "read from the video" in journey.stops[4].text
    assert "ZAC2026-08007" in journey.note and "1259 Huffman Road" in journey.note


def test_the_liquor_licence_journey_has_five_stops_and_no_first_reading():
    journey = _journeys_by_key()["liquor-licence-legion-field"]

    assert _shape(journey) == [
        (("submitted",), "none"),
        (("committee",), "committee_minutes"),
        (("first_reading",), "not_on_route"),
        (("agenda", "hearing", "final_vote"), "video"),
        (("mayor", "in_effect"), "none"),
    ]
    assert _recorded_rows(journey) == [
        ("2026-09-22", 3179, None, None),
        ("2026-09-29", 2536, 62035, 872),
    ]
    assert "Councilor Tate, Chairman of the Public Safety Committee" in journey.stops[0].text
    assert "no submission date" in journey.stops[0].gap
    assert journey.stops[1].quote.endswith("By The Committee Chair – Lack of Quorum.")
    assert journey.stops[2].gap == NO_FIRST_READING
    assert "8 to 0" in journey.stops[3].text and "read from the video" in journey.stops[3].text
    assert journey.title.startswith("A Resolution relative to the application of Greenawalt Hospitality, LLC")


def test_the_consent_journey_has_six_stops_and_no_vote():
    journey = _journeys_by_key()["consent-avondale-park"]

    assert _shape(journey) == [
        (("submitted",), "none"),
        (("committee",), "committee_minutes"),
        (("first_reading",), "not_on_route"),
        (("agenda", "consent"), "agenda"),
        (("final_vote",), "none"),
        (("mayor", "in_effect"), "none"),
    ]
    assert _recorded_rows(journey) == [
        ("2026-10-12", 3183, None, None),
        ("2026-10-20", 2624, 62911, 1714),
    ]
    assert journey.stops[1].source_file == "committee-bf_min.txt"
    assert journey.stops[1].quote.endswith("Items Recommended to the City Council Consent Agenda.")
    assert journey.stops[2].gap == NO_FIRST_READING
    assert "Consent items pass on one motion for the group." in journey.stops[3].text
    assert "No vote is linked to this item" in journey.stops[4].text
    assert "not published" in journey.stops[4].gap


def test_the_consent_journeys_title_is_the_resolution_as_the_saved_committee_minutes_print_it():
    from docket.services.how_it_works import _missing_quote_piece, normalise_for_quote_check

    journey = _journeys_by_key()["consent-avondale-park"]
    source = normalise_for_quote_check((BIRMINGHAM / "sources" / "committee-bf_min.txt").read_text(encoding="utf-8"))

    assert "…" in journey.title
    assert _missing_quote_piece(journey.title, source) is None
    assert _missing_quote_piece(journey.title.replace("$4,000", "$5,000"), source) is not None


def test_no_journey_cites_the_second_copy_of_the_rezoning_item():
    for path in (BIRMINGHAM / "journeys").glob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        assert "62832" not in text, path.name
        assert "2613" not in text, path.name
    for journey in _journeys_by_key().values():
        for stop in journey.stops:
            assert stop.item_id != 62832 and stop.meeting_id != 2613, journey.key
