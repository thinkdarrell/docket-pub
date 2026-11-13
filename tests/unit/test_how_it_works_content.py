"""The "How it works" explainer's content, and the loader that reads it.

Plan `how-it-works-explainer`, M1. The first group reads the real Birmingham
content under `content/how-it-works/birmingham/`; the second builds small
explainers in a temporary directory to show what the loader refuses.

`docket.services.how_it_works` is imported inside each test, not at the top
of the module, so the file collects before the module exists.
"""

from __future__ import annotations

import re
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
    assert explainer.journeys == ()


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
