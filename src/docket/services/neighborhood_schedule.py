"""The neighborhood association meeting schedule: checked-in content, read and validated.

One directory per city under ``config.COMING_UP_ROOT`` may hold a
``neighborhood-schedule.yaml``: a hand transcription of the schedule the city
publishes as a PDF, one entry per association, with the PDF itself saved
beside it under ``sources/``. ``load_schedule`` parses the file and refuses
anything a later reader would have to guess at: a key it does not know, a
value outside its vocabulary, a rule with half a date, and a saved PDF that
is not the one the file says it was transcribed from.

``name``, ``rule_text`` and ``type_text`` are the city's cells as printed.
``ordinal``, ``weekday``, ``months`` and ``time`` are what a person read out
of ``rule_text``; an association the schedule gives no usable rule has no
``ordinal`` and says why in ``undated_reason`` (``docs/PRINCIPLES.md``,
"Source or silence"). ``place`` and ``remote`` are parts of the city's
information cell, each as printed.

``occurrences`` turns each rule into the dates it gives in the schedule's
year: the ordinal weekday of each of the association's months, and nothing
else. No date is moved for a holiday, and no date is produced for a year the
schedule was not published for.

The module reads files only. Nothing here imports from the web layer or opens
the database (plan ``birmingham-coming-up``, M4 and M5).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from docket import config

SCHEDULE_FILE = "neighborhood-schedule.yaml"

ORDINALS = ("first", "second", "third", "fourth")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MODES = ("in_person", "phone", "video")

_TOP_KEYS = ("source", "checked", "associations")
_SOURCE_KEYS = ("title", "revised", "url", "file", "sha256", "read", "year")
_CHECK_KEYS = ("by", "on", "how")
_ASSOCIATION_KEYS = (
    "name",
    "rule_text",
    "ordinal",
    "weekday",
    "time",
    "type_text",
    "modes",
    "place",
    "remote",
)
_ASSOCIATION_OPTIONAL = ("months", "undated_reason")

_TIME_RE = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")


class ScheduleError(ValueError):
    """A schedule file is malformed, or its saved source is not the one it names.

    The message names the file and, for an association's entry, the
    association, so the fix is one edit away.
    """


@dataclass(frozen=True)
class Check:
    """One reading of the transcription against the source: who, when, how."""

    by: str
    on: date
    how: str


@dataclass(frozen=True)
class Association:
    name: str
    rule_text: str
    ordinal: str | None
    weekday: str | None
    months: tuple[int, ...] | None
    time: str | None
    type_text: str
    modes: tuple[str, ...]
    place: str | None
    remote: str | None
    undated_reason: str | None


@dataclass(frozen=True)
class Schedule:
    title: str
    revised: date
    url: str
    file: str
    sha256: str
    read: date
    year: int
    checked: tuple[Check, ...]
    associations: tuple[Association, ...]


@dataclass(frozen=True)
class Occurrence:
    """One dated meeting a schedule rule gives: the association, and the day."""

    association: Association
    on: date


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_date(value: Any) -> bool:
    return isinstance(value, date) and not isinstance(value, datetime)


def _keys(mapping: Any, required: tuple[str, ...], optional: tuple[str, ...], fail, what: str) -> None:
    """Refuse ``mapping`` unless it is a mapping with every required key and no unknown one."""
    if not isinstance(mapping, dict):
        fail(f"{what} must be a mapping of keys to values")
    for key in required:
        if key not in mapping:
            fail(f"{what} is missing the key `{key}`")
    for key in mapping:
        if key not in required and key not in optional:
            fail(f"{what} has the unknown key `{key}`")


def _association(raw: Any, index: int, fail) -> Association:
    def bad(message: str):
        name = raw.get("name") if isinstance(raw, dict) else None
        who = f"association {name!r}" if _is_text(name) else f"associations[{index}]"
        fail(f"{who}: {message}")

    if not isinstance(raw, dict):
        bad("must be a mapping of keys to values")
    if not _is_text(raw.get("name")):
        bad("`name` must be the association's name as the schedule prints it")
    _keys(raw, _ASSOCIATION_KEYS, _ASSOCIATION_OPTIONAL, bad, "the entry")

    for key in ("rule_text", "type_text"):
        if not _is_text(raw[key]):
            bad(f"`{key}` must be the schedule's cell as printed, and is empty or not text")
    for key in ("place", "remote"):
        if raw[key] is not None and not _is_text(raw[key]):
            bad(f"`{key}` must be text copied from the schedule, or null")

    ordinal, weekday = raw["ordinal"], raw["weekday"]
    if ordinal is not None and ordinal not in ORDINALS:
        bad(f"`ordinal` is {ordinal!r}; it must be one of {', '.join(ORDINALS)}, or null")
    if weekday is not None and weekday not in WEEKDAYS:
        bad(f"`weekday` is {weekday!r}; it must be one of {', '.join(WEEKDAYS)}, or null")
    if (ordinal is None) != (weekday is None):
        bad("`ordinal` and `weekday` must both be given or both be null")

    months = raw.get("months")
    if months is not None:
        if not isinstance(months, list) or not months:
            bad("`months` must be a list of month numbers, or be left out for every month")
        for month in months:
            if isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12:
                bad(f"`months` holds {month!r}; a month is a number from 1 to 12")

    time = raw["time"]
    if time is not None and not (isinstance(time, str) and _TIME_RE.fullmatch(time)):
        bad(f'`time` is {time!r}; it must be 24-hour "HH:MM" in quotes, or null')

    modes = raw["modes"]
    if not isinstance(modes, list):
        bad(f"`modes` must be a list drawn from {', '.join(MODES)}")
    for mode in modes:
        if mode not in MODES:
            bad(f"`modes` holds {mode!r}; a mode is one of {', '.join(MODES)}")

    reason = raw.get("undated_reason")
    if ordinal is None and not _is_text(reason):
        bad("has no `ordinal`, so `undated_reason` must say why it is given no dates")
    if ordinal is not None and "undated_reason" in raw:
        bad("has an `ordinal`, so it must not carry `undated_reason`")

    return Association(
        name=raw["name"],
        rule_text=raw["rule_text"],
        ordinal=ordinal,
        weekday=weekday,
        months=tuple(months) if months is not None else None,
        time=time,
        type_text=raw["type_text"],
        modes=tuple(modes),
        place=raw["place"],
        remote=raw["remote"],
        undated_reason=reason,
    )


def load_schedule(city_dir: Path) -> Schedule:
    """Read and validate ``city_dir``'s schedule; raise ``ScheduleError`` on any defect."""
    city_dir = Path(city_dir)
    path = city_dir / SCHEDULE_FILE

    def fail(message: str):
        raise ScheduleError(f"{path}: {message}")

    if not path.is_file():
        fail("the schedule file does not exist")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ScheduleError(f"{path}: not valid YAML: {e}") from e

    _keys(doc, _TOP_KEYS, (), fail, "the file")

    source = doc["source"]
    _keys(source, _SOURCE_KEYS, (), fail, "`source`")
    for key in ("title", "url", "file", "sha256"):
        if not _is_text(source[key]):
            fail(f"`source.{key}` must be text, and is empty or not text")
    for key in ("revised", "read"):
        if not _is_date(source[key]):
            fail(f"`source.{key}` is {source[key]!r}; it must be a date written YYYY-MM-DD")
    if isinstance(source["year"], bool) or not isinstance(source["year"], int):
        fail(f"`source.year` is {source['year']!r}; it must be the schedule's year as a number")

    checked = doc["checked"]
    if not isinstance(checked, list) or not checked:
        fail("`checked` must list at least one reading of the transcription against the source")
    checks = []
    for i, raw in enumerate(checked):
        # YAML 1.1, which PyYAML reads, takes a bare `on` for the boolean
        # true, so the key a person writes as `on: 2026-11-17` arrives as
        # True. It is read as the key it was written as; `"on":` in quotes
        # arrives as text and is the same key.
        if isinstance(raw, dict) and True in raw and "on" not in raw:
            raw = {("on" if key is True else key): value for key, value in raw.items()}
        _keys(raw, _CHECK_KEYS, (), fail, f"`checked[{i}]`")
        for key in ("by", "how"):
            if not _is_text(raw[key]):
                fail(f"`checked[{i}].{key}` must be text, and is empty or not text")
        if not _is_date(raw["on"]):
            fail(f"`checked[{i}].on` is {raw['on']!r}; it must be a date written YYYY-MM-DD")
        checks.append(Check(by=raw["by"], on=raw["on"], how=raw["how"]))

    if not isinstance(doc["associations"], list):
        fail("`associations` must be a list, one entry per association")
    associations = []
    seen: set[str] = set()
    for i, raw in enumerate(doc["associations"]):
        association = _association(raw, i, fail)
        if association.name in seen:
            fail(f"association {association.name!r} is listed more than once")
        seen.add(association.name)
        associations.append(association)

    # The saved source: inside the city's directory, present, and the very
    # bytes the transcription was read from.
    saved = (city_dir / source["file"]).resolve()
    if not saved.is_relative_to(city_dir.resolve()):
        fail(f"`source.file` is {source['file']!r}, which is outside {city_dir}")
    if not saved.is_file():
        fail(f"`source.file` is {source['file']!r}, which does not exist under {city_dir}")
    digest = hashlib.sha256(saved.read_bytes()).hexdigest()
    if digest != source["sha256"]:
        fail(
            f"the saved {source['file']} has SHA-256 {digest}, and `source.sha256` says "
            f"{source['sha256']}: the file was replaced or the transcription names another revision"
        )

    return Schedule(
        title=source["title"],
        revised=source["revised"],
        url=source["url"],
        file=source["file"],
        sha256=source["sha256"],
        read=source["read"],
        year=source["year"],
        checked=tuple(checks),
        associations=tuple(associations),
    )


_cache: dict[str, Schedule] = {}


def get_schedule(slug: str) -> Schedule | None:
    """The city's schedule, or ``None`` when it has no schedule file.

    Loaded on first use and kept for the life of the process: the file
    changes only by a deploy. A malformed file raises ``ScheduleError``.
    """
    if slug in _cache:
        return _cache[slug]
    city_dir = Path(config.COMING_UP_ROOT) / slug
    if not (city_dir / SCHEDULE_FILE).is_file():
        return None
    schedule = load_schedule(city_dir)
    _cache[slug] = schedule
    return schedule


def _ordinal_weekday(year: int, month: int, ordinal: str, weekday: str) -> date:
    """The first, second, third or fourth ``weekday`` of a month. Every month has four of each."""
    first = date(year, month, 1)
    to_first = (WEEKDAYS.index(weekday) - first.weekday()) % 7
    return date(year, month, 1 + to_first + 7 * ORDINALS.index(ordinal))


def occurrences(schedule: Schedule, start: date, end: date) -> list[Occurrence]:
    """Every dated meeting the schedule's rules give from ``start`` to ``end``, both included.

    Dates are computed for ``schedule.year`` alone, so a range outside that
    year is empty. An association with no ``ordinal`` gives none. Ordered by
    date, then time with no time last, then name.
    """
    found = []
    for association in schedule.associations:
        if association.ordinal is None:
            continue
        months = association.months if association.months is not None else range(1, 13)
        for month in months:
            on = _ordinal_weekday(schedule.year, month, association.ordinal, association.weekday)
            if start <= on <= end:
                found.append(Occurrence(association=association, on=on))
    found.sort(key=lambda o: (o.on, o.association.time is None, o.association.time or "", o.association.name))
    return found


def undated(schedule: Schedule) -> list[Association]:
    """The associations the schedule gives no usable rule, in the file's order."""
    return [a for a in schedule.associations if a.ordinal is None]
