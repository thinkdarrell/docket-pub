"""Member vote resolution — which council member a stored member name refers to.

A ``member_votes`` row carries the name the source printed (``Woods``,
``O’Quinn``, ``C. Woods``) and, when it is known, the ``council_member_id``
of the person it refers to. This module owns the one rule that turns the
first into the second: variants derived from the roster's full names,
compared after normalisation, scoped to the municipality and to the
half-open term window of decision ``0004`` (``term_start <= meeting_date <
term_end``). Both producers use it — ``docket.services.ingest._ingest_votes``
at insert, and the daily sweep ``resolve_unresolved_member_votes`` for rows
already stored with a NULL id from any source.

Normalisation folds the curly apostrophes U+2019, U+2018, and U+02BC to the
straight one, collapses whitespace runs to one space, trims, and lowercases.
A name that matches more than one seated member is left unresolved and
logged; a vote on a meeting with no date is left unresolved; a NULL term
date is unbounded on that side. Nothing here deletes a row: an unresolved
name is logged by name and count, and is a parser or roster question.

Only ``load_roster_index`` and ``resolve_unresolved_member_votes`` open a
database connection, each through ``docket.db.db_cursor``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from docket.db import db_cursor

logger = logging.getLogger(__name__)

APOSTROPHES: dict[int, str] = {0x2019: "'", 0x2018: "'", 0x02BC: "'"}
SUFFIXES: frozenset[str] = frozenset({"ii", "iii", "iv", "jr", "jr.", "sr", "sr."})
PREFIXES: tuple[str, ...] = ("O'", "Mc", "Mac")

# How many unresolved names the sweep logs one line each for before it
# collapses the rest into a single count.
_LOGGED_UNRESOLVED_NAMES = 30

_ROSTER_SQL = """
    SELECT id, name, term_start, term_end
      FROM council_members
     WHERE municipality_id = %s
     ORDER BY id
"""

_UNRESOLVED_GROUPS_SQL = """
    SELECT m.municipality_id, mv.member_name, m.meeting_date, count(*) AS n
      FROM member_votes mv
      JOIN votes v ON v.id = mv.vote_id
      JOIN meetings m ON m.id = v.meeting_id
     WHERE mv.council_member_id IS NULL
     GROUP BY m.municipality_id, mv.member_name, m.meeting_date
"""

_RESOLVE_BUCKET_SQL = """
    UPDATE member_votes mv
       SET council_member_id = %(member_id)s
      FROM votes v
      JOIN meetings m ON m.id = v.meeting_id
     WHERE mv.vote_id = v.id
       AND mv.council_member_id IS NULL
       AND m.municipality_id = %(municipality_id)s
       AND mv.member_name = %(member_name)s
       AND m.meeting_date = ANY(%(dates)s)
"""


def normalize_name(name: str) -> str:
    """Fold curly apostrophes, collapse whitespace, trim, lowercase."""
    return " ".join(name.translate(APOSTROPHES).split()).lower()


def name_variants(full_name: str) -> frozenset[str]:
    """The normalised short forms a roster full name can take in a source.

    ``Darrell O'Quinn`` gives ``o'quinn``, ``d. o'quinn``, ``oquinn``,
    ``d. oquinn``, and ``quinn``; ``Clinton P. Woods`` gives ``woods`` and
    ``c. woods``; a trailing generational suffix (``II``, ``Jr.``) is dropped.
    """
    tokens = full_name.translate(APOSTROPHES).split()
    while len(tokens) > 1 and tokens[-1].lower() in SUFFIXES:
        tokens.pop()
    if not tokens:
        return frozenset()
    surname = tokens[-1]
    initial = tokens[0][0]
    variants = {surname, f"{initial}. {surname}"}
    if "'" in surname or "-" in surname:
        stripped = surname.replace("'", "").replace("-", "")
        variants.add(stripped)
        variants.add(f"{initial}. {stripped}")
        for prefix in PREFIXES:
            if surname.startswith(prefix) and len(surname) > len(prefix):
                variants.add(surname[len(prefix):])
    return frozenset(normalize_name(v) for v in variants)


@dataclass(frozen=True)
class RosterVariant:
    """One normalised variant of one member's name, with that member's term."""

    variant: str  # already normalised
    member_id: int
    term_start: date | None
    term_end: date | None

    def seated_on(self, meeting_date: date) -> bool:
        """Half-open term window; a NULL term date is unbounded on that side."""
        return (self.term_start is None or self.term_start <= meeting_date) and (
            self.term_end is None or meeting_date < self.term_end
        )


class RosterIndex:
    """Every variant of every member of one municipality, keyed by variant."""

    def __init__(self, variants: Iterable[RosterVariant]) -> None:
        self._by_variant: dict[str, list[RosterVariant]] = defaultdict(list)
        for entry in variants:
            self._by_variant[entry.variant].append(entry)

    def resolve(self, member_name: str, meeting_date: date | None) -> int | None:
        """The one member id the stored name refers to on that date, or None."""
        if meeting_date is None:
            return None
        key = normalize_name(member_name)
        member_ids = {
            entry.member_id
            for entry in self._by_variant.get(key, ())
            if entry.seated_on(meeting_date)
        }
        if len(member_ids) == 1:
            return next(iter(member_ids))
        if len(member_ids) > 1:
            logger.warning(
                "member_votes: ambiguous name=%r date=%s members=%s",
                member_name, meeting_date, sorted(member_ids),
            )
        return None


def index_from_rows(
    rows: Iterable[tuple[int, str, date | None, date | None]],
) -> RosterIndex:
    """Build an index from ``(id, name, term_start, term_end)`` roster rows."""
    entries: list[RosterVariant] = []
    for member_id, name, term_start, term_end in rows:
        for variant in name_variants(name):
            entries.append(RosterVariant(variant, member_id, term_start, term_end))
    return RosterIndex(entries)


def _roster_rows(cur, municipality_id: int) -> list[tuple[int, str, date | None, date | None]]:
    cur.execute(_ROSTER_SQL, (municipality_id,))
    return [(r["id"], r["name"], r["term_start"], r["term_end"]) for r in cur.fetchall()]


def load_roster_index(municipality_id: int) -> RosterIndex:
    """Read one municipality's roster and build its index (one short read)."""
    with db_cursor() as cur:
        rows = _roster_rows(cur, municipality_id)
    return index_from_rows(rows)


@dataclass
class ResolveResult:
    resolved: int  # rows given an id by this run
    unresolved: int  # rows still NULL after this run
    unresolved_names: dict[str, int] = field(default_factory=dict)  # stored name -> row count


def resolve_unresolved_member_votes() -> ResolveResult:
    """Give every ``member_votes`` row with a NULL ``council_member_id`` its member.

    Groups the NULL rows by municipality, stored name, and meeting date,
    resolves each group in Python against that municipality's roster, and
    writes one UPDATE per (municipality, stored name, member id) bucket scoped
    by the bucket's dates, all in one transaction. Rows that do not resolve
    are left as they are and logged by name and count; nothing is deleted.
    """
    resolved = 0
    unresolved = 0
    unresolved_names: dict[str, int] = defaultdict(int)
    unresolved_by_muni: dict[tuple[int, str], int] = defaultdict(int)
    buckets: dict[tuple[int, str, int], list[date]] = defaultdict(list)
    indexes: dict[int, RosterIndex] = {}

    with db_cursor() as cur:
        cur.execute(_UNRESOLVED_GROUPS_SQL)
        groups = cur.fetchall()

        for group in groups:
            municipality_id = group["municipality_id"]
            member_name = group["member_name"]
            meeting_date = group["meeting_date"]
            count = group["n"]
            if municipality_id not in indexes:
                indexes[municipality_id] = index_from_rows(_roster_rows(cur, municipality_id))
            member_id = indexes[municipality_id].resolve(member_name, meeting_date)
            if member_id is None:
                unresolved += count
                unresolved_names[member_name] += count
                unresolved_by_muni[(municipality_id, member_name)] += count
            else:
                buckets[(municipality_id, member_name, member_id)].append(meeting_date)

        for (municipality_id, member_name, member_id), dates in buckets.items():
            cur.execute(
                _RESOLVE_BUCKET_SQL,
                {
                    "member_id": member_id,
                    "municipality_id": municipality_id,
                    "member_name": member_name,
                    "dates": dates,
                },
            )
            resolved += cur.rowcount

    ranked = sorted(unresolved_by_muni.items(), key=lambda item: (-item[1], item[0][1]))
    for (municipality_id, member_name), count in ranked[:_LOGGED_UNRESOLVED_NAMES]:
        logger.warning(
            "member_votes: unresolved name=%r municipality_id=%s rows=%d",
            member_name, municipality_id, count,
        )
    if len(ranked) > _LOGGED_UNRESOLVED_NAMES:
        logger.warning(
            "member_votes: and %d more unresolved names",
            len(ranked) - _LOGGED_UNRESOLVED_NAMES,
        )

    return ResolveResult(resolved, unresolved, dict(unresolved_names))
