"""The "How it works" explainer: checked-in content, read and validated.

One directory per city under ``config.HOW_IT_WORKS_ROOT`` holds an
``explainer.yaml`` (the path an item travels, the rules at each stop, and the
questions left open), a ``sources/`` directory of plain-text copies of the
documents those rules quote, and a ``journeys/`` directory with one file per
journey: one real item followed across the path, with what the record shows
at each stop. ``load_explainer`` parses them, refuses anything that would put
an unsourced sentence on the page, and proves that every quotation that names
a source file appears in it.

A journey states its facts in its own file (dates, tallies, names,
quotations). ``resolve_journey`` reads the database for one thing only: which
links a stop may carry. A meeting that is missing, hidden, or another city's
costs a stop its links and never its text. It reads through other services
and writes nothing.

The loader reads files only. Nothing here imports from ``docket.web``, and no
language model writes or alters any text this module returns (plan
``how-it-works-explainer``, Decision Log; ``docs/PRINCIPLES.md``, "Source or
silence").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from docket.services import query, transcripts, video_links
from docket.services.video_links import VideoLink

EXPLAINER_FILE = "explainer.yaml"
SOURCES_DIR = "sources"
JOURNEYS_DIR = "journeys"

# What a journey stop's fact rests on. The last two are not records: the
# rules say the stop happens and no record shows it (RECORD_NONE), or this
# item's route does not pass through it (RECORD_NOT_ON_ROUTE).
RECORD_NONE = "none"
RECORD_NOT_ON_ROUTE = "not_on_route"
RECORDS = ("minutes", "agenda", "video", "transcript", "committee_minutes", RECORD_NONE, RECORD_NOT_ON_ROUTE)
_NO_RECORD = (RECORD_NONE, RECORD_NOT_ON_ROUTE)

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
    journeys: tuple[Journey, ...]  # in file-name order; empty for a city with none


@dataclass(frozen=True)
class StopLinks:
    meeting_url: str | None  # the site's meeting page
    item_url: str | None  # the site's item page
    recording: VideoLink | None
    transcript_url: str | None  # the site's transcript page
    minutes_url: str | None  # the city's document
    agenda_url: str | None  # the city's document


@dataclass(frozen=True)
class ResolvedStop:
    stop: JourneyStop
    links: StopLinks


@dataclass(frozen=True)
class ResolvedJourney:
    journey: Journey
    stops: tuple[ResolvedStop, ...]
    reached: frozenset[str]  # path stop keys with a recorded event
    not_in_record: frozenset[str]  # keys named by a record-none stop, less reached
    not_on_route: frozenset[str]  # keys named by a not_on_route stop, less the two above


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

    def optional_whole_number(self, mapping: dict, key: str, where: str) -> int | None:
        value = mapping.get(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise self.fail(f"{where}.{key}", f"must be a whole number when present, got {value!r}")
        return value


def _source_text(
    reader: _Reader, source_file: str, where: str, sources_dir: Path, source_cache: dict[str, str], cited: str
) -> str:
    """The normalised text of one saved source, which must be a bare file name under ``sources/``."""
    source_path = sources_dir / source_file
    if Path(source_file).name != source_file or not source_path.is_file():
        raise reader.fail(f"{where}.source_file", f"{source_file!r} is not a file in {sources_dir} ({cited})")
    if source_file not in source_cache:
        source_cache[source_file] = normalise_for_quote_check(source_path.read_text(encoding="utf-8"))
    return source_cache[source_file]


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
        source = _source_text(reader, source_file, where, sources_dir, source_cache, f"rule cited {citation!r}")
        if quote is not None:
            missing = _missing_quote_piece(quote, source)
            if missing is not None:
                raise reader.fail(
                    f"{where}.quote",
                    f"the rule cited {citation!r} quotes words that are not in "
                    f"{SOURCES_DIR}/{source_file}, in this order: {missing!r}",
                )
    return Rule(statement=statement, quote=quote, citation=citation, url=url, source_file=source_file)


def _load_journey_stop(
    reader: _Reader, raw: Any, where: str, path_keys: set[str], sources_dir: Path, source_cache: dict[str, str]
) -> JourneyStop:
    raw = reader.mapping(raw, where)

    keys = reader.sequence(raw.get("stops"), f"{where}.stops")
    if not keys:
        raise reader.fail(f"{where}.stops", "a journey stop names at least one stop of the path")
    for key in keys:
        if not isinstance(key, str) or key not in path_keys:
            raise reader.fail(
                f"{where}.stops",
                f"{key!r} is not a stop or side route of the path (they are {', '.join(sorted(path_keys))})",
            )

    record = reader.text(raw, "record", where)
    if record not in RECORDS:
        raise reader.fail(f"{where}.record", f"{record!r} is not one of {', '.join(RECORDS)}")
    text = reader.text(raw, "text", where)
    meeting_id = reader.optional_whole_number(raw, "meeting_id", where)
    item_id = reader.optional_whole_number(raw, "item_id", where)
    seconds = reader.optional_whole_number(raw, "seconds", where)
    gap = reader.optional_text(raw, "gap", where)

    if record in _NO_RECORD:
        # A stop with no record says why, and cannot rest on a meeting.
        if gap is None:
            raise reader.fail(f"{where}.gap", f"required when record is {record}: say why there is no record")
        if meeting_id is not None:
            raise reader.fail(f"{where}.meeting_id", f"a stop whose record is {record} names no meeting")
        if raw.get("date") is not None:
            raise reader.fail(f"{where}.date", f"a stop whose record is {record} has no date")
        day = None
    else:
        # A recorded stop names the day and the meeting its fact rests on.
        day = reader.day(raw, "date", where)
        if meeting_id is None:
            raise reader.fail(f"{where}.meeting_id", f"required when record is {record}")

    quote = reader.optional_text(raw, "quote", where)
    source_file = reader.optional_text(raw, "source_file", where)
    if source_file is not None:
        source = _source_text(reader, source_file, where, sources_dir, source_cache, "journey stop")
        if quote is None:
            raise reader.fail(f"{where}.quote", f"required because the stop names the source file {source_file!r}")
        missing = _missing_quote_piece(quote, source)
        if missing is not None:
            raise reader.fail(
                f"{where}.quote",
                f"the stop quotes words that are not in {SOURCES_DIR}/{source_file}, in this order: {missing!r}",
            )

    document_label = document_url = None
    if raw.get("document") is not None:
        document = reader.mapping(raw["document"], f"{where}.document")
        document_label = reader.text(document, "label", f"{where}.document")
        document_url = reader.text(document, "url", f"{where}.document")
        if not document_url.startswith("https://"):
            raise reader.fail(f"{where}.document.url", f"must be an https:// address, got {document_url!r}")

    return JourneyStop(
        stops=tuple(keys),
        date=day,
        record=record,
        text=text,
        quote=quote,
        source_file=source_file,
        meeting_id=meeting_id,
        item_id=item_id,
        seconds=seconds,
        document_label=document_label,
        document_url=document_url,
        gap=gap,
    )


def _load_journey(
    path: Path, path_keys: set[str], main_keys: list[str], sources_dir: Path, source_cache: dict[str, str]
) -> Journey:
    reader = _Reader(path)
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ExplainerError(f"{path}: cannot be read: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ExplainerError(f"{path}: is not valid YAML: {exc}") from exc

    document = reader.mapping(document, "the file")
    key = reader.text(document, "key", "the file")
    label = reader.text(document, "label", "the file")
    note = reader.text(document, "note", "the file")
    title = reader.text(document, "title", "the file")
    raw_stops = reader.sequence(document.get("stops"), "stops")
    stops = tuple(
        _load_journey_stop(reader, raw_stop, f"stops[{i}]", path_keys, sources_dir, source_cache)
        for i, raw_stop in enumerate(raw_stops)
    )

    # Every main stop is accounted for, so the path has the same shape for
    # every journey and each blank on it is a statement someone wrote.
    named = {stop_key for stop in stops for stop_key in stop.stops}
    for main_key in main_keys:
        if main_key not in named:
            raise reader.fail(
                "stops",
                f"no journey stop names the main stop {main_key!r}; give it a stop, with record "
                f"{RECORD_NONE} or {RECORD_NOT_ON_ROUTE} and the reason when there is no record",
            )
    return Journey(key=key, label=label, note=note, title=title, stops=stops)


def _load_journeys(
    city_dir: Path, stops: list[Stop], sources_dir: Path, source_cache: dict[str, str]
) -> tuple[Journey, ...]:
    """Every ``journeys/*.yaml`` beside the explainer, in file-name order.

    A city with no ``journeys/`` directory has no journeys.
    """
    journeys_dir = city_dir / JOURNEYS_DIR
    path_keys = {stop.key for stop in stops}
    main_keys = [stop.key for stop in stops if stop.side_route_of is None]
    journeys: list[Journey] = []
    first_file: dict[str, str] = {}
    for path in sorted(journeys_dir.glob("*.yaml")):
        journey = _load_journey(path, path_keys, main_keys, sources_dir, source_cache)
        if journey.key in first_file:
            raise ExplainerError(
                f"{path}: the file.key: {journey.key!r} is already the key of {first_file[journey.key]}"
            )
        first_file[journey.key] = path.name
        journeys.append(journey)
    return tuple(journeys)


def load_explainer(city_dir: Path) -> Explainer:
    """Read and validate ``<city_dir>/explainer.yaml`` and ``<city_dir>/journeys/*.yaml``.

    Quotations are checked against ``<city_dir>/sources/``. Raises
    ``ExplainerError``, naming the file and the key, for: a stop with no
    rules; a rule with no citation or no ``https://`` link; a ``quote`` with
    no ``source_file``; a ``source_file`` that does not exist; a quotation not
    found in its source; a repeated stop key; and a side route hung under a
    key that is not a main stop of the path. And in a journey file: a stop
    key that is not on the path; a record that is not one of ``RECORDS``; a
    stop with no record that gives no reason, or names a meeting or a date; a recorded
    stop with no date or no meeting; a quotation not found in the source file
    the stop names; a main stop no journey stop names; and a repeated journey
    key.
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
        journeys=_load_journeys(city_dir, stops, sources_dir, source_cache),
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


_NO_LINKS = StopLinks(
    meeting_url=None, item_url=None, recording=None, transcript_url=None, minutes_url=None, agenda_url=None
)


def _stop_links(stop: JourneyStop, municipality_id: int, city_slug: str) -> StopLinks:
    """The links one journey stop may carry, from the rows as they are now."""
    if stop.meeting_id is None:
        return _NO_LINKS
    meeting = query.get_meeting(stop.meeting_id)
    # Missing, hidden, or another city's: the site serves no page for it, so
    # the stop links nothing of it, the city's documents included.
    if meeting is None or meeting.is_hidden or meeting.municipality_id != municipality_id:
        return _NO_LINKS

    item = query.get_agenda_item(stop.item_id) if stop.item_id is not None else None
    if item is not None and item.meeting_id != meeting.id:
        item = None

    meeting_url = f"/al/{city_slug}/meetings/{meeting.id}/"
    return StopLinks(
        meeting_url=meeting_url,
        item_url=f"/al/{city_slug}/items/{item.id}/" if item is not None else None,
        # link_for ignores a chapter id that is not all digits, and builds no
        # link for a meeting with no video.
        recording=video_links.link_for(
            video_links.for_meeting(meeting.id),
            seconds=stop.seconds,
            chapter_id=item.external_id if item is not None else None,
        ),
        transcript_url=(
            f"{meeting_url}transcript/" if transcripts.get_public_transcript(meeting.id) is not None else None
        ),
        minutes_url=meeting.minutes_url or None,
        agenda_url=meeting.agenda_url or None,
    )


def resolve_journey(journey: Journey, municipality_id: int, city_slug: str) -> ResolvedJourney:
    """Give each stop of ``journey`` its links, and sort the path's stops into three sets.

    Site addresses are plain paths under ``/al/<city_slug>/``, so this module
    imports nothing from Flask. The sets come from the journey file alone and
    do not overlap: a stop the file records is reached whether or not its
    meeting row can still be linked.
    """
    reached = frozenset(key for stop in journey.stops if stop.record not in _NO_RECORD for key in stop.stops)
    not_in_record = frozenset(
        key for stop in journey.stops if stop.record == RECORD_NONE for key in stop.stops
    ) - reached
    not_on_route = (
        frozenset(key for stop in journey.stops if stop.record == RECORD_NOT_ON_ROUTE for key in stop.stops)
        - reached
        - not_in_record
    )
    return ResolvedJourney(
        journey=journey,
        stops=tuple(
            ResolvedStop(stop=stop, links=_stop_links(stop, municipality_id, city_slug)) for stop in journey.stops
        ),
        reached=reached,
        not_in_record=not_in_record,
        not_on_route=not_on_route,
    )
