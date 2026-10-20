"""Unit tests for docket.services.member_votes — the pure resolver.

No database: the index is built from rows with ``index_from_rows``. The
rule under test is the one ``docs/specs/votes.md`` describes: roster
variants compared after apostrophe folding, scoped to a half-open term
window, with ambiguity, a NULL meeting date, and NULL term dates each
handled the way the plan ``member-votes-name-their-member`` decided.
"""

from datetime import date

from docket.services.member_votes import (
    index_from_rows,
    name_variants,
    normalize_name,
)


def test_normalize_name_folds_curly_apostrophes_and_case():
    assert normalize_name("O’Quinn") == "o'quinn"  # right single quote
    assert normalize_name("O‘Quinn") == "o'quinn"  # left single quote
    assert normalize_name("OʼQuinn") == "o'quinn"  # modifier letter apostrophe


def test_normalize_name_collapses_whitespace():
    assert normalize_name("  D.   OQuinn ") == "d. oquinn"


def test_name_variants_plain_surname():
    assert name_variants("Clinton P. Woods") == {"woods", "c. woods"}


def test_name_variants_apostrophe_surname():
    assert name_variants("Darrell O'Quinn") == {
        "o'quinn", "d. o'quinn", "oquinn", "d. oquinn", "quinn",
    }


def test_name_variants_drops_generational_suffix():
    assert name_variants("Paul S. Simmons II") == {"simmons", "p. simmons"}


def _two_term_index():
    return index_from_rows([
        (5, "Darrell O'Quinn", date(2025, 10, 28), None),
        (27, "Valerie A. Abbott", date(2017, 11, 14), date(2025, 10, 28)),
    ])


def test_resolve_inside_term_window():
    index = _two_term_index()
    assert index.resolve("O’Quinn", date(2026, 5, 19)) == 5
    assert index.resolve("Abbott", date(2024, 6, 1)) == 27


def test_resolve_term_window_is_half_open():
    index = _two_term_index()
    transition = date(2025, 10, 28)
    assert index.resolve("Abbott", transition) is None
    assert index.resolve("O’Quinn", transition) == 5


def test_resolve_ambiguous_surname_is_unresolved():
    index = index_from_rows([
        (41, "Carole Smitherman", date(2020, 1, 1), None),
        (42, "Brian Smitherman", date(2020, 1, 1), None),
    ])
    assert index.resolve("Smitherman", date(2024, 6, 1)) is None
    assert index.resolve("C. Smitherman", date(2024, 6, 1)) == 41


def test_resolve_null_meeting_date_is_unresolved():
    index = _two_term_index()
    assert index.resolve("O’Quinn", None) is None


def test_resolve_null_terms_match_any_date():
    index = index_from_rows([(7, "Ashley Curry", None, None)])
    assert index.resolve("Curry", date(1999, 1, 1)) == 7
