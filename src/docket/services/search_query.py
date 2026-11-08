"""A parsed search query and the SQL fragments built from it. Pure: no database.

A query is a tuple of units. A unit is one word, one quoted phrase, or one
identifier (a number such as `26-50`). Coverage is how many of a query's
word and phrase units a text matches; identifiers are counted apart, by the
item search, which puts an item carrying a typed identifier first.

The fragments use named parameters, `%(<prefix><n>)s`, where `n` is the
unit's position in the tuple it was given. Two fragments built from the same
units under the same prefix therefore name each unit's parameter alike, and
one parameter dict serves a statement that uses both.

`parse_query` turns typed text into a `SearchQuery`. It decides nothing
about what a word means to the server: stemming, case, and what a hyphen or
an apostrophe splits are PostgreSQL's, applied when a fragment runs.

Plan `search-finds-what-was-said`: M5 created this module for the spoken
moments under a search result (`docket.services.transcripts.moments_for_items`);
M6 added the parser and `ident_sql` for the item search
(`docket.services.query.search_agenda_items`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# The unit kinds. A word goes to plainto_tsquery; a phrase and an identifier
# go to phraseto_tsquery, which requires their tokens side by side.
WORD, PHRASE, IDENTIFIER = "word", "phrase", "identifier"

# The most units a query keeps; the words typed after the twelfth are ignored.
MAX_UNITS = 12
# The most excluded words and phrases a query keeps, counted together; the
# `-word` and `-"phrase"` tokens typed after the twelfth are ignored. Each
# one is a predicate the item search evaluates for every candidate row, so
# without a cap the cost of one request would be bounded only by the length
# of its URL.
MAX_EXCLUDED = 12

# Typed outside quotes, these ask for newer meetings first and are not
# searched for, unless the query would otherwise have no unit.
RECENCY_WORDS = ("new", "recent", "latest")

# PostgreSQL's English stop words: the 127 lines of tsearch_data/english.stop
# under the directory `pg_config --sharedir` prints, copied here. The server
# owns the list and discards these words from every query, so dropping them
# first changes no result; it keeps them out of the MAX_UNITS slots.
# tests/integration/test_search_ranking.py asks the test server about every
# member, so a word the server would have searched for is never dropped here.
_ENGLISH_STOP = """
    i me my myself we our ours ourselves you your yours yourself yourselves he him his himself she
    her hers herself it its itself they them their theirs themselves what which who whom this that
    these those am is are was were be been being have has had having do does did doing a an the and
    but if or because as until while of at by for with about against between into through during
    before after above below to from up down in out on off over under again further then once here
    there when where why how all any both each few more most other some such no nor not only own
    same so than too very s t can will just don should now
"""
STOP_WORDS = frozenset(_ENGLISH_STOP.split())


@dataclass(frozen=True)
class Unit:
    kind: str   # "word" | "phrase" | "identifier"
    text: str


@dataclass(frozen=True)
class SearchQuery:
    units: tuple[Unit, ...]
    excluded: tuple[str, ...]            # excluded words: `-zoning`
    prefer_recent: bool
    raw: str
    excluded_phrases: tuple[str, ...] = ()   # excluded phrases: `-"late night"`


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


def ident_sql(units, vector: str, prefix: str) -> tuple[str, dict]:
    """An integer expression: how many identifier units `vector` carries, and its parameters.

    The counterpart of `coverage_sql` for the units it leaves out, with the
    same parameter names. With no identifier unit it is the literal `0`.
    """
    parts, params = [], {}
    for n, unit in enumerate(units):
        if unit.kind != IDENTIFIER:
            continue
        name = f"{prefix}{n}"
        parts.append(f"({vector} @@ {_unit_tsquery(unit, name)})::int")
        params[name] = unit.text
    if not parts:
        return "0", {}
    return "(" + " + ".join(parts) + ")", params


# A double-quoted run, with the hyphen that starts a token right before it if
# there is one, or a run of anything that is neither whitespace nor a quote.
# A quote that is never closed matches neither branch and is skipped. A
# hyphen that ends a word before a quote (`well-"known"`) belongs to the
# word, because the second branch has already taken it.
_TOKEN_RE = re.compile(r'(-?)"([^"]*)"|[^\s"]+')
# Sentence punctuation and brackets round a typed token are not part of it.
_EDGE_PUNCTUATION = ".,;:!?()[]{}"
_DIGIT_RE = re.compile(r"\d")


def _is_identifier(token: str) -> bool:
    """`26-50`, `12-10-46`, `ZAC2025-00012`: two or more hyphen-separated parts, a digit in each."""
    parts = token.split("-")
    return len(parts) >= 2 and all(_DIGIT_RE.search(part) for part in parts)


def parse_query(q: str) -> SearchQuery:
    """Turn typed text into units, excluded words, and a recency preference.

    The text is split on whitespace, and a double-quoted run is one phrase
    unit, or an excluded phrase when a hyphen comes right before its opening
    quote (`-"late night"`); an excluded phrase of stop words alone is
    dropped. Outside quotes, in this order: punctuation round a token is
    removed and a token with no letter or digit is dropped; a stop word is
    dropped; `-word` is an excluded word; a token whose hyphen-separated
    parts each hold a digit is an identifier; anything else is a word.
    `new`, `recent`, and `latest` are then taken out of the units and set
    `prefer_recent`, unless that would leave no unit, in which case they stay
    as ordinary words. Duplicates are dropped whatever their case, and the
    first MAX_UNITS units and the first MAX_EXCLUDED excluded words and
    phrases, counted together in the order typed, are kept. A unit's text is
    as typed.
    """
    units: list[Unit] = []
    excluded: list[tuple[str, str]] = []   # (WORD or PHRASE, text), in the order typed
    seen_units: set[tuple[str, str]] = set()
    seen_excluded: set[tuple[str, str]] = set()

    def add(kind: str, text: str) -> None:
        key = (kind, text.lower())
        if key not in seen_units:
            seen_units.add(key)
            units.append(Unit(kind, text))

    def exclude(kind: str, text: str) -> None:
        key = (kind, text.lower())
        if key not in seen_excluded and not all(w in STOP_WORDS for w in text.lower().split()):
            seen_excluded.add(key)
            excluded.append((kind, text))

    for match in _TOKEN_RE.finditer(q or ""):
        if match.group(2) is not None:
            phrase = " ".join(match.group(2).split())
            if phrase and match.group(1):
                exclude(PHRASE, phrase)
            elif phrase:
                add(PHRASE, phrase)
            continue
        token = match.group(0).strip(_EDGE_PUNCTUATION)
        if not any(ch.isalnum() for ch in token):
            continue
        if token.lower() in STOP_WORDS:
            continue
        if token[0] == "-" and token[1:2].isalpha():
            exclude(WORD, token[1:])
            continue
        add(IDENTIFIER if _is_identifier(token) else WORD, token)

    def is_recency(unit: Unit) -> bool:
        return unit.kind == WORD and unit.text.lower() in RECENCY_WORDS

    searched = [u for u in units if not is_recency(u)]
    prefer_recent = bool(searched) and len(searched) < len(units)
    if searched:
        units = searched
    kept = excluded[:MAX_EXCLUDED]
    return SearchQuery(units=tuple(units[:MAX_UNITS]),
                       excluded=tuple(text for kind, text in kept if kind == WORD),
                       prefer_recent=prefer_recent, raw=q,
                       excluded_phrases=tuple(text for kind, text in kept if kind == PHRASE))
