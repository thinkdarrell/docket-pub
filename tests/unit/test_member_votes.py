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


def test_an_alias_resolves_within_the_members_term():
    """A fifth part of a roster row is the member's aliases: other names the source prints for them.

    Plan `mobile-votes-from-minutes`, M2: Mobile's minutes print "Scott" for Scott Jones.
    """
    index = index_from_rows([
        (61, "Scott Jones", date(2021, 11, 2), date(2023, 4, 11), ["Scott", "  S.  JONES-Smith "]),
        (62, "Josh Woods", date(2023, 8, 8), None, []),
        (63, "Cory Penn", date(2021, 11, 2), None, None),
    ])
    assert index.resolve("Scott", date(2021, 11, 2)) == 61
    assert index.resolve("Scott", date(2023, 4, 10)) == 61
    # The alias is under the member's own term: nobody the day it ends, nobody before it starts.
    assert index.resolve("Scott", date(2023, 4, 11)) is None
    assert index.resolve("Scott", date(2021, 11, 1)) is None
    # The surname still answers, to the same member, and an alias is compared as any name is.
    assert index.resolve("Jones", date(2022, 9, 13)) == 61
    assert index.resolve("SCOTT", date(2022, 9, 13)) == 61
    assert index.resolve("s. jones-smith", date(2022, 9, 13)) == 61
    # A member with no alias, or none stored, answers as before, and to nobody's first name.
    assert index.resolve("Woods", date(2023, 8, 8)) == 62
    assert index.resolve("Penn", date(2022, 1, 1)) == 63
    assert index.resolve("Josh", date(2024, 1, 1)) is None
    assert index.resolve("Cory", date(2024, 1, 1)) is None


def test_an_alias_two_seated_members_share_is_unresolved():
    index = index_from_rows([
        (61, "Scott Jones", date(2021, 11, 2), None, ["Scott"]),
        (64, "Dana Scott", date(2021, 11, 2), None, []),
    ])
    assert index.resolve("Scott", date(2022, 1, 1)) is None
    assert index.resolve("Jones", date(2022, 1, 1)) == 61


def test_a_four_part_row_has_no_alias():
    index = index_from_rows([(61, "Scott Jones", date(2021, 11, 2), date(2023, 4, 11))])
    assert index.resolve("Jones", date(2022, 9, 13)) == 61
    assert index.resolve("Scott", date(2022, 9, 13)) is None


def test_the_roster_read_carries_each_members_aliases():
    """`load_roster_index` reads the column: what `index_from_rows` is given comes from `_ROSTER_SQL`."""
    from docket.services import member_votes

    class Cursor:
        def execute(self, sql, params):
            self.sql, self.params = sql, params

        def fetchall(self):
            return [
                {"id": 61, "name": "Scott Jones", "term_start": date(2021, 11, 2),
                 "term_end": date(2023, 4, 11), "aliases": ["Scott"]},
                {"id": 62, "name": "Josh Woods", "term_start": date(2023, 8, 8), "term_end": None, "aliases": []},
            ]

    cur = Cursor()
    rows = member_votes._roster_rows(cur, 7)
    assert cur.params == (7,) and "aliases" in cur.sql
    assert rows == [
        (61, "Scott Jones", date(2021, 11, 2), date(2023, 4, 11), ["Scott"]),
        (62, "Josh Woods", date(2023, 8, 8), None, []),
    ]
    assert index_from_rows(rows).resolve("Scott", date(2022, 1, 1)) == 61
