"""The search query parser: typed text becomes units, excluded words, and a recency preference.

Plan: plans/completed/search-finds-what-was-said.md (M6). Pure: no database.

The names M6 adds to `docket.services.search_query` (`parse_query`,
`ident_sql`, `MAX_UNITS`, `RECENCY_WORDS`, `STOP_WORDS`) are read off the
module inside the tests, not imported at the top of this file, so the file
collects before they exist. The server's view of `STOP_WORDS` is tested in
`tests/integration/test_search_ranking.py`, and what `or_tsquery_sql` and
`coverage_sql` match is tested on the server in
`tests/integration/test_search_moments.py`.
"""
import pytest

from docket.services import search_query as sqm


def _parse(q):
    return sqm.parse_query(q)


def _units(q):
    return [(u.kind, u.text) for u in _parse(q).units]


def _words(*texts):
    return [(sqm.WORD, t) for t in texts]


# --- The cases the plan lists ---------------------------------------------------------------


def test_new_late_night_ordinance_is_three_words_and_a_recency_preference():
    sq = _parse("new late night ordinance")
    assert _units("new late night ordinance") == _words("late", "night", "ordinance")
    assert sq.prefer_recent is True
    assert sq.excluded == ()
    assert sq.raw == "new late night ordinance"


def test_a_number_with_a_hyphen_is_one_identifier():
    sq = _parse("26-50")
    assert _units("26-50") == [(sqm.IDENTIFIER, "26-50")]
    assert sq.prefer_recent is False


def test_a_word_a_phrase_an_identifier_and_an_excluded_word():
    sq = _parse('recall "Kelvyn Felder" 26-50 -zoning')
    assert [(u.kind, u.text) for u in sq.units] == [
        (sqm.WORD, "recall"), (sqm.PHRASE, "Kelvyn Felder"), (sqm.IDENTIFIER, "26-50")]
    assert sq.excluded == ("zoning",)
    assert sq.prefer_recent is False


def test_new_alone_is_kept_as_a_word():
    sq = _parse("new")
    assert _units("new") == _words("new")
    assert sq.prefer_recent is False


def test_a_hyphenated_word_with_one_numeric_part_is_a_word():
    assert _units("24-hour") == _words("24-hour")


def test_thirteen_words_keep_the_first_twelve():
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
             "india", "juliet", "kilo", "lima", "mike"]
    assert not [w for w in words if w in sqm.STOP_WORDS]
    assert sqm.MAX_UNITS == 12
    assert _units(" ".join(words)) == _words(*words[:12])


def test_a_long_question_spends_no_slot_on_a_stop_word():
    q = "what are the new rules for clubs that are keeping the security camera footage for 30 days"
    sq = _parse(q)
    assert _units(q) == _words("rules", "clubs", "keeping", "security", "camera", "footage", "30", "days")
    assert len(sq.units) == 8
    assert sq.prefer_recent is True


def test_stop_words_alone_are_no_units():
    sq = _parse("the of")
    assert sq.units == ()
    assert sq.excluded == ()
    assert sq.prefer_recent is False


def test_stop_words_inside_quotes_are_one_phrase():
    assert _units('"the of"') == [(sqm.PHRASE, "the of")]


@pytest.mark.parametrize("q", ["", "   ", "\t\n"])
def test_nothing_typed_is_no_units(q):
    sq = _parse(q)
    assert sq.units == () and sq.excluded == () and sq.prefer_recent is False
    assert sq.raw == q


# --- The module's constants -----------------------------------------------------------------


def test_the_stop_list_is_the_servers_127_lowercase_words():
    assert isinstance(sqm.STOP_WORDS, frozenset)
    assert len(sqm.STOP_WORDS) == 127
    assert all(w == w.lower() and w.isalpha() for w in sqm.STOP_WORDS)
    assert {"what", "are", "the", "for", "of", "s", "t", "don"} <= sqm.STOP_WORDS


def test_the_recency_words_are_not_stop_words():
    assert sqm.RECENCY_WORDS == ("new", "recent", "latest")
    assert not set(sqm.RECENCY_WORDS) & sqm.STOP_WORDS


# --- Recency ---------------------------------------------------------------------------------


@pytest.mark.parametrize("word", ["new", "recent", "latest", "New", "LATEST", "Recent"])
def test_each_recency_word_in_any_case_is_a_preference_not_a_unit(word):
    sq = _parse(f"{word} paving contract")
    assert [(u.kind, u.text) for u in sq.units] == _words("paving", "contract")
    assert sq.prefer_recent is True


def test_recency_words_alone_stay_as_words():
    sq = _parse("new latest")
    assert [(u.kind, u.text) for u in sq.units] == _words("new", "latest")
    assert sq.prefer_recent is False


def test_a_recency_word_beside_only_an_excluded_word_stays_a_word():
    sq = _parse("new -zoning")
    assert [(u.kind, u.text) for u in sq.units] == _words("new")
    assert sq.excluded == ("zoning",)
    assert sq.prefer_recent is False


def test_a_recency_word_beside_an_identifier_is_a_preference():
    sq = _parse("latest 26-50")
    assert [(u.kind, u.text) for u in sq.units] == [(sqm.IDENTIFIER, "26-50")]
    assert sq.prefer_recent is True


def test_a_recency_word_inside_quotes_is_part_of_the_phrase():
    sq = _parse('"new hotel" permit')
    assert [(u.kind, u.text) for u in sq.units] == [(sqm.PHRASE, "new hotel"), (sqm.WORD, "permit")]
    assert sq.prefer_recent is False


# --- Identifiers -----------------------------------------------------------------------------


@pytest.mark.parametrize("token", ["26-50", "12-10-46", "ZAC2025-00012", "2025-1"])
def test_every_part_holding_a_digit_makes_an_identifier(token):
    assert _units(token) == [(sqm.IDENTIFIER, token)]


@pytest.mark.parametrize("token", ["24-hour", "late-night", "2025", "co-op", "26-", "-50"])
def test_a_token_that_is_not_an_identifier_is_a_word(token):
    assert _units(token) == _words(token)


# --- Stop words, excluded words, duplicates ---------------------------------------------------


def test_a_stop_word_is_dropped_in_any_case():
    assert _units("The Rules OF the road") == _words("Rules", "road")


def test_a_hyphen_before_a_letter_excludes_the_word():
    sq = _parse("ordinance -rezone -Zoning")
    assert [(u.kind, u.text) for u in sq.units] == _words("ordinance")
    assert sq.excluded == ("rezone", "Zoning")


def test_an_excluded_word_alone_is_no_units():
    sq = _parse("-zoning")
    assert sq.units == ()
    assert sq.excluded == ("zoning",)


def test_an_excluded_stop_word_excludes_nothing():
    sq = _parse("ordinance -the")
    assert sq.excluded == ()


def test_duplicates_are_dropped_whatever_their_case():
    sq = _parse("paving Paving PAVING contract -zoning -ZONING")
    assert [(u.kind, u.text) for u in sq.units] == _words("paving", "contract")
    assert sq.excluded == ("zoning",)


def test_excluded_words_keep_the_first_twelve():
    """Each excluded word is one more predicate on every candidate row, so they are capped like the units."""
    q = "ordinance " + " ".join(f"-zq{chr(97 + n)}" for n in range(15)) + " -ZQA -the"
    sq = _parse(q)
    assert sqm.MAX_EXCLUDED == 12
    assert sq.excluded == tuple(f"zq{chr(97 + n)}" for n in range(12))
    assert [(u.kind, u.text) for u in sq.units] == _words("ordinance")


def test_a_hyphen_before_a_quoted_phrase_excludes_the_phrase():
    sq = _parse('-"late night" ordinance')
    assert [(u.kind, u.text) for u in sq.units] == _words("ordinance")
    assert sq.excluded_phrases == ("late night",)
    assert sq.excluded == ()


def test_an_excluded_phrase_alone_is_no_units():
    sq = _parse('-"late  night"')
    assert sq.units == ()
    assert sq.excluded_phrases == ("late night",)


def test_a_hyphen_ending_a_word_before_a_quote_excludes_nothing():
    sq = _parse('well-"late night"')
    assert (sqm.PHRASE, "late night") in [(u.kind, u.text) for u in sq.units]
    assert sq.excluded_phrases == ()


def test_an_excluded_phrase_of_stop_words_or_of_nothing_excludes_nothing():
    sq = _parse('ordinance -"the of" -"" -" "')
    assert sq.excluded_phrases == () and sq.excluded == ()
    assert [(u.kind, u.text) for u in sq.units] == _words("ordinance")


def test_duplicate_excluded_phrases_are_dropped_whatever_their_case():
    assert _parse('paving -"Late Night" -"late night"').excluded_phrases == ("Late Night",)


def test_excluded_words_and_phrases_share_the_cap_in_the_order_typed():
    q = "ordinance " + " ".join(f"-zq{chr(97 + n)}" for n in range(10)) + ' -"one two" -"three four" -zqz -"five six"'
    sq = _parse(q)
    assert sq.excluded == tuple(f"zq{chr(97 + n)}" for n in range(10))
    assert sq.excluded_phrases == ("one two", "three four")
    assert len(sq.excluded) + len(sq.excluded_phrases) == sqm.MAX_EXCLUDED


def test_a_query_built_without_excluded_phrases_has_none():
    sq = sqm.SearchQuery(units=(), excluded=(), prefer_recent=False, raw="")
    assert sq.excluded_phrases == ()


def test_the_cap_counts_units_after_stop_words_and_duplicates_are_gone():
    q = "the alpha of alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike"
    units = _units(q)
    assert len(units) == 12
    assert units[0] == (sqm.WORD, "alpha") and units[-1] == (sqm.WORD, "lima")


# --- Quotes and punctuation -------------------------------------------------------------------


def test_a_quote_never_closed_is_ignored():
    assert _units('"late night') == _words("late", "night")
    assert _units('late" night') == _words("late", "night")


def test_empty_quotes_are_no_unit():
    assert _units('"" paving "  "') == _words("paving")


def test_whitespace_inside_a_phrase_is_one_space():
    assert _units('"Kelvyn    Felder"') == [(sqm.PHRASE, "Kelvyn Felder")]


def test_sentence_punctuation_round_a_token_is_not_part_of_it():
    sq = _parse("What are the new rules, for clubs? (26-50).")
    assert [(u.kind, u.text) for u in sq.units] == [
        (sqm.WORD, "rules"), (sqm.WORD, "clubs"), (sqm.IDENTIFIER, "26-50")]
    assert sq.prefer_recent is True


def test_a_token_with_no_letter_or_digit_is_dropped():
    sq = _parse("paving - -- & contract")
    assert [(u.kind, u.text) for u in sq.units] == _words("paving", "contract")
    assert sq.excluded == ()


def test_an_apostrophe_stays_inside_a_word():
    assert _units("mayor's budget") == _words("mayor's", "budget")


# --- The identifier fragment -------------------------------------------------------------------


def _U(kind, text):
    return sqm.Unit(kind=kind, text=text)


def test_ident_sql_counts_only_the_identifier_units():
    units = (_U(sqm.WORD, "recall"), _U(sqm.IDENTIFIER, "26-50"), _U(sqm.PHRASE, "Kelvyn Felder"),
             _U(sqm.IDENTIFIER, "12-10-46"))
    sql, params = sqm.ident_sql(units, "ai.search_vector", "u")
    assert sql == ("((ai.search_vector @@ phraseto_tsquery('english', %(u1)s))::int"
                   " + (ai.search_vector @@ phraseto_tsquery('english', %(u3)s))::int)")
    assert params == {"u1": "26-50", "u3": "12-10-46"}


def test_ident_sql_with_no_identifier_is_zero():
    assert sqm.ident_sql((_U(sqm.WORD, "paving"),), "ai.search_vector", "u") == ("0", {})
    assert sqm.ident_sql((), "ai.search_vector", "u") == ("0", {})


def test_the_three_fragments_name_a_units_parameter_alike():
    units = tuple(sqm.parse_query('recall "Kelvyn Felder" 26-50').units)
    _, any_params = sqm.or_tsquery_sql(units, "u")
    _, coverage_params = sqm.coverage_sql(units, "v", "u")
    _, ident_params = sqm.ident_sql(units, "v", "u")
    assert any_params == {"u0": "recall", "u1": "Kelvyn Felder", "u2": "26-50"}
    assert coverage_params == {"u0": "recall", "u1": "Kelvyn Felder"}
    assert ident_params == {"u2": "26-50"}
    assert {**coverage_params, **ident_params} == any_params
