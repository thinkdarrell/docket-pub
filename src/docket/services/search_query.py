"""A parsed search query and the SQL fragments built from it. Pure: no database.

A query is a tuple of units. A unit is one word, one quoted phrase, or one
identifier (a number such as `26-50`). Coverage is how many of a query's
word and phrase units a text matches; identifiers are counted apart, by the
item search, which puts an item carrying a typed identifier first.

The fragments use named parameters, `%(<prefix><n>)s`, where `n` is the
unit's position in the tuple it was given. Two fragments built from the same
units under the same prefix therefore name each unit's parameter alike, and
one parameter dict serves a statement that uses both.

Plan `search-finds-what-was-said`: M5 created this module for the spoken
moments under a search result (`docket.services.transcripts.moments_for_items`);
the parser that turns typed text into a `SearchQuery` is added by M6.
"""
from __future__ import annotations

from dataclasses import dataclass

# The unit kinds. A word goes to plainto_tsquery; a phrase and an identifier
# go to phraseto_tsquery, which requires their tokens side by side.
WORD, PHRASE, IDENTIFIER = "word", "phrase", "identifier"


@dataclass(frozen=True)
class Unit:
    kind: str   # "word" | "phrase" | "identifier"
    text: str


@dataclass(frozen=True)
class SearchQuery:
    units: tuple[Unit, ...]
    excluded: tuple[str, ...]
    prefer_recent: bool
    raw: str


def _unit_tsquery(unit: Unit, name: str) -> str:
    function = "plainto_tsquery" if unit.kind == WORD else "phraseto_tsquery"
    return f"{function}('english', %({name})s)"


def or_tsquery_sql(units, prefix: str) -> tuple[str, dict]:
    """A tsquery expression that matches a text holding any of `units`, and its parameters.

    The expression is parenthesised, so it can follow `@@` as it is. With no
    units it is the empty tsquery, which matches nothing.
    """
    if not units:
        return "''::tsquery", {}
    parts, params = [], {}
    for n, unit in enumerate(units):
        name = f"{prefix}{n}"
        parts.append(_unit_tsquery(unit, name))
        params[name] = unit.text
    return "(" + " || ".join(parts) + ")", params


def coverage_sql(units, vector: str, prefix: str) -> tuple[str, dict]:
    """An integer expression: how many word and phrase units `vector` matches, and its parameters.

    `vector` is the SQL of a tsvector, such as `s.search_vector`. A unit
    counts once however often its words occur. Identifier units are not
    counted and take no parameter. With nothing to count it is the literal
    `0`.
    """
    parts, params = [], {}
    for n, unit in enumerate(units):
        if unit.kind == IDENTIFIER:
            continue
        name = f"{prefix}{n}"
        parts.append(f"({vector} @@ {_unit_tsquery(unit, name)})::int")
        params[name] = unit.text
    if not parts:
        return "0", {}
    return "(" + " + ".join(parts) + ")", params
