"""The "How it works" explainer: checked-in content, read and validated.

One directory per city under ``config.HOW_IT_WORKS_ROOT`` holds an
``explainer.yaml`` (the path an item travels, the rules at each stop, and the
questions left open) and a ``sources/`` directory of plain-text copies of the
documents those rules quote. ``load_explainer`` parses the file, refuses
anything that would put an unsourced sentence on the page, and proves that
every quotation appears in the source file it names.

This module reads files only. It does not touch the database and it imports
nothing from ``docket.web``. No language model writes or alters any text it
returns (plan ``how-it-works-explainer``, Decision Log; ``docs/PRINCIPLES.md``,
"Source or silence").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

EXPLAINER_FILE = "explainer.yaml"
SOURCES_DIR = "sources"

_WHITESPACE_RE = re.compile(r"\s+")
_ELLIPSIS_RE = re.compile(r"…|\.\.\.")
_QUOTE_MARKS = str.maketrans(
    {
        "“": '"',  # left double quotation mark
        "”": '"',  # right double quotation mark
        "‘": "'",  # left single quotation mark
        "’": "'",  # right single quotation mark, the typographic apostrophe
    }
)


class ExplainerError(ValueError):
    """An explainer file is malformed, or quotes words its source does not hold.

    The message names the file and the key, so the fix is one edit away.
    """


@dataclass(frozen=True)
class Rule:
    statement: str
    quote: str | None
    citation: str
    url: str
    source_file: str | None


@dataclass(frozen=True)
class Stop:
    key: str
    name: str
    side_route_of: str | None
    description: str
    rules: tuple[Rule, ...]


@dataclass(frozen=True)
class JourneyStop:
    stops: tuple[str, ...]  # at least one
    date: date | None
    record: str
    text: str
    quote: str | None
    source_file: str | None
    meeting_id: int | None
    item_id: int | None
    seconds: int | None
    document_label: str | None
    document_url: str | None
    gap: str | None


@dataclass(frozen=True)
class Journey:
    key: str
    label: str
    note: str
    title: str
    stops: tuple[JourneyStop, ...]


@dataclass(frozen=True)
class Explainer:
    city: str
    sources_read: date
    stops: tuple[Stop, ...]
    open_questions: tuple[tuple[str, str], ...]
    journeys: tuple[Journey, ...]  # empty until journeys are loaded


def normalise_for_quote_check(text: str) -> str:
    """Make a quotation and its source comparable, and change nothing else.

    Every run of whitespace becomes one space (a saved PDF breaks lines where
    the page did), and curly quotation marks and apostrophes become straight
    ones. Case is kept: the comparison is case-sensitive.
    """
    return _WHITESPACE_RE.sub(" ", text.translate(_QUOTE_MARKS)).strip()


def _missing_quote_piece(quote: str, normalised_source: str) -> str | None:
    """The first piece of ``quote`` that the source does not hold, or None.

    A quotation may elide words with "…" or "...". Each piece between
    ellipses must appear in the source, each after the end of the one before.
    A quotation with no words in it at all is reported as missing.
    """
    pieces = [normalise_for_quote_check(p) for p in _ELLIPSIS_RE.split(quote)]
    pieces = [p for p in pieces if p]
    if not pieces:
        return quote
    position = 0
    for piece in pieces:
        found = normalised_source.find(piece, position)
        if found < 0:
            return piece
        position = found + len(piece)
    return None


class _Reader:
    """Typed reads from one parsed YAML file, failing with the file and key."""

    def __init__(self, path: Path):
        self.path = path

    def fail(self, where: str, problem: str) -> ExplainerError:
        return ExplainerError(f"{self.path}: {where}: {problem}")

    def mapping(self, value: Any, where: str) -> dict:
        if not isinstance(value, dict):
            raise self.fail(where, "expected a mapping")
        return value

    def sequence(self, value: Any, where: str) -> list:
        if not isinstance(value, list):
            raise self.fail(where, "expected a list")
        return value

    def text(self, mapping: dict, key: str, where: str) -> str:
        value = mapping.get(key)
        if not isinstance(value, str) or not value.strip():
            raise self.fail(f"{where}.{key}", "required, and must be text")
        return value.strip()

    def optional_text(self, mapping: dict, key: str, where: str) -> str | None:
        value = mapping.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise self.fail(f"{where}.{key}", "must be text when present")
        return value.strip()

    def day(self, mapping: dict, key: str, where: str) -> date:
        value = mapping.get(key)
        if isinstance(value, datetime) or not isinstance(value, date):
            raise self.fail(f"{where}.{key}", "required, and must be a date written YYYY-MM-DD")
        return value


def _load_rule(
    reader: _Reader, raw: Any, where: str, sources_dir: Path, source_cache: dict[str, str]
) -> Rule:
    raw = reader.mapping(raw, where)
    statement = reader.text(raw, "statement", where)
    citation = reader.text(raw, "citation", where)
    url = reader.text(raw, "url", where)
    if not url.startswith("https://"):
        raise reader.fail(f"{where}.url", f"must be an https:// address, got {url!r}")
    quote = reader.optional_text(raw, "quote", where)
    source_file = reader.optional_text(raw, "source_file", where)

    if quote is not None and source_file is None:
        raise reader.fail(
            f"{where}.source_file",
            f"required because the rule cited {citation!r} has a quote; name the file under "
            f"{SOURCES_DIR}/ that holds the quoted words",
        )
    if source_file is not None:
        source_path = sources_dir / source_file
        if Path(source_file).name != source_file or not source_path.is_file():
            raise reader.fail(
                f"{where}.source_file",
                f"{source_file!r} is not a file in {sources_dir} (rule cited {citation!r})",
            )
        if source_file not in source_cache:
            source_cache[source_file] = normalise_for_quote_check(source_path.read_text(encoding="utf-8"))
        if quote is not None:
            missing = _missing_quote_piece(quote, source_cache[source_file])
            if missing is not None:
                raise reader.fail(
                    f"{where}.quote",
                    f"the rule cited {citation!r} quotes words that are not in "
                    f"{SOURCES_DIR}/{source_file}, in this order: {missing!r}",
                )
    return Rule(statement=statement, quote=quote, citation=citation, url=url, source_file=source_file)


def load_explainer(city_dir: Path) -> Explainer:
    """Read and validate ``<city_dir>/explainer.yaml`` against ``<city_dir>/sources/``.

    Raises ``ExplainerError``, naming the file and the key, for: a stop with
    no rules; a rule with no citation or no ``https://`` link; a ``quote``
    with no ``source_file``; a ``source_file`` that does not exist; a
    quotation not found in its source; a repeated stop key; and a side route
    hung under a key that is not a main stop of the path.
    """
    city_dir = Path(city_dir)
    path = city_dir / EXPLAINER_FILE
    reader = _Reader(path)
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ExplainerError(f"{path}: cannot be read: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ExplainerError(f"{path}: is not valid YAML: {exc}") from exc

    document = reader.mapping(document, "the file")
    city = reader.text(document, "city", "the file")
    sources_read = reader.day(document, "sources_read", "the file")
    sources_dir = city_dir / SOURCES_DIR
    source_cache: dict[str, str] = {}

    raw_stops = reader.sequence(document.get("stops"), "stops")
    if not raw_stops:
        raise reader.fail("stops", "at least one stop is required")
    stops: list[Stop] = []
    seen_keys: set[str] = set()
    for i, raw_stop in enumerate(raw_stops):
        where = f"stops[{i}]"
        raw_stop = reader.mapping(raw_stop, where)
        key = reader.text(raw_stop, "key", where)
        if key in seen_keys:
            raise reader.fail(f"{where}.key", f"{key!r} is already the key of an earlier stop")
        seen_keys.add(key)
        raw_rules = reader.sequence(raw_stop.get("rules"), f"{where}.rules")
        if not raw_rules:
            raise reader.fail(f"{where}.rules", f"the stop {key!r} has no rules; every stop needs at least one")
        stops.append(
            Stop(
                key=key,
                name=reader.text(raw_stop, "name", where),
                side_route_of=reader.optional_text(raw_stop, "side_route_of", where),
                description=reader.text(raw_stop, "description", where),
                rules=tuple(
                    _load_rule(reader, raw_rule, f"{where}.rules[{j}]", sources_dir, source_cache)
                    for j, raw_rule in enumerate(raw_rules)
                ),
            )
        )

    main_keys = {stop.key for stop in stops if stop.side_route_of is None}
    for i, stop in enumerate(stops):
        if stop.side_route_of is not None and stop.side_route_of not in main_keys:
            raise reader.fail(
                f"stops[{i}].side_route_of",
                f"{stop.side_route_of!r} is not a main stop of the path (the main stops are "
                f"{', '.join(s.key for s in stops if s.side_route_of is None)})",
            )

    open_questions: list[tuple[str, str]] = []
    for i, raw_question in enumerate(reader.sequence(document.get("open_questions"), "open_questions")):
        where = f"open_questions[{i}]"
        raw_question = reader.mapping(raw_question, where)
        open_questions.append((reader.text(raw_question, "heading", where), reader.text(raw_question, "body", where)))

    return Explainer(
        city=city,
        sources_read=sources_read,
        stops=tuple(stops),
        open_questions=tuple(open_questions),
        journeys=(),
    )


def load_explainers(root: Path) -> dict[str, Explainer]:
    """Every city's explainer under ``root``, keyed by the directory's name.

    A directory is a city when it holds an ``explainer.yaml``; the directory's
    name is the city's slug. A root that does not exist holds no cities. An
    explainer that fails validation raises ``ExplainerError``: the caller is
    the application factory, and a broken explainer stops the application
    from starting, as a broken template would.
    """
    root = Path(root)
    if not root.is_dir():
        return {}
    return {
        city_dir.name: load_explainer(city_dir)
        for city_dir in sorted(root.iterdir())
        if (city_dir / EXPLAINER_FILE).is_file()
    }
