"""Read a scheduled public hearing out of an agenda item's title.

A council resolution that sets a public hearing says so in one sentence:
"A Resolution setting a public hearing November 17, 2026, to consider ...".
`read_hearing` reads that sentence by fixed rules: the trigger phrase, the
hearing's date, its kind, a property count for a weed-lot resolution, and
the subject, with a key by which two items that set one hearing are told
from two that set different ones (`same_hearing`).

Deterministic, standard library only, no language model. It reads the title
alone, as stored: a date the stored title does not hold is `None`, never
guessed (plan `birmingham-coming-up`, M1, whose Decision Log says why each
rule is what it is).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

# Bumped when a rule below changes what a title reads as.
RULE_VERSION = 1

# The vocabulary of `HearingReading.kind`, in the order the kinds are tested.
KINDS = ("zoning", "weed_lots", "vacation", "budget", "other")

KIND_LABELS = {
    "zoning": "Zoning",
    "weed_lots": "Overgrown lots",
    "vacation": "Streets",
    "budget": "Budget",
    "other": "Other",
}

# What a reader sees as a hearing's title, in plain words. `vacation` covers
# both a street's closure and the city giving up ("vacating") a right-of-way,
# so its title names both.
KIND_TITLES = {
    "zoning": "Zoning hearing",
    "weed_lots": "Hearing on overgrown lots",
    "vacation": "Hearing on closing a street or giving up a right-of-way",
    "budget": "Budget hearing",
    "other": "Public hearing",
}

# A key that opens another names the same hearing only when it is at least
# this long. The words every zoning hearing shares reduce to 82 characters.
PREFIX_MIN = 90


@dataclass(frozen=True)
class HearingReading:
    hearing_date: date | None
    kind: str
    subject: str
    subject_key: str
    property_count: int | None


_MONTHS = (
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
)
_MONTH_NUMBER = {name.lower(): number for number, name in enumerate(_MONTHS, start=1)}
_MONTH = "(?:" + "|".join(_MONTHS) + ")"

# "November 17, 2026" or "July 15, 2025": groups are month, day, year.
_DATE = rf"\b({_MONTH}) (\d{{1,2}}),? (\d{{4}})(?!\d)"

_TRIGGER = re.compile(
    r"\b(?:setting|to set|providing for) (?:a|the) public (?:show cause )?hearing\b",
    re.IGNORECASE,
)
# First form: the date follows the trigger at once (a comma, spaces, "on").
_DATE_AT_ONCE = re.compile(rf"[, ]*(?:on\b[, ]*)?{_DATE}", re.IGNORECASE)
# Second form: "on the 7th day of April, 2026"; groups are day, month, year.
_DATE_DAY_OF = re.compile(
    rf"\bon the (\d{{1,2}})(?:st|nd|rd|th) day of ({_MONTH}),? (\d{{4}})(?!\d)",
    re.IGNORECASE,
)
# Third form: "to be held ... on March 3, 2026", no full stop or semicolon between.
_DATE_TO_BE_HELD = re.compile(rf"\bto be held\b[^.;]*?\bon {_DATE}", re.IGNORECASE)
_DATE_CHANGE = re.compile(
    rf"CHANGE HEARING DATE FROM {_DATE} TO {_DATE}", re.IGNORECASE
)

_KIND_TESTS = (
    ("weed_lots", re.compile(r"noxious or dangerous weeds", re.IGNORECASE)),
    ("zoning", re.compile(r"zoning|zone district|rezon", re.IGNORECASE)),
    ("vacation", re.compile(r"vacation of|closure of|right[- ]of[- ]way", re.IGNORECASE)),
    ("budget", re.compile(r"budget", re.IGNORECASE)),
)

_PROPERTY_COUNT = re.compile(r"\((\d+)\) properties", re.IGNORECASE)
_BRACKET_GROUP = re.compile(r"\[[^\]]*\]")
_SUBMITTED = re.compile(r"\((?:Submitted|Recommended) by", re.IGNORECASE)
_NOT_KEY_CHARACTER = re.compile(r"[^a-z0-9]")


def _real_date(month: str, day: str, year: str) -> date | None:
    try:
        return date(int(year), _MONTH_NUMBER[month.lower()], int(day))
    except ValueError:
        return None


def _subject_key(subject: str) -> str:
    text = _BRACKET_GROUP.sub("", subject)
    cut = _SUBMITTED.search(text)
    if cut:
        text = text[: cut.start()]
    return _NOT_KEY_CHARACTER.sub("", text.lower())


def read_hearing(title: str | None) -> HearingReading | None:
    """What a title says about a hearing it sets, or None when it sets none."""
    if not title:
        return None
    text = re.sub(r"\s+", " ", title)
    trigger = _TRIGGER.search(text)
    if trigger is None:
        return None
    after_trigger = trigger.end()

    hearing_date = None
    subject_start = after_trigger
    at_once = _DATE_AT_ONCE.match(text, after_trigger)
    if at_once:
        hearing_date = _real_date(*at_once.groups())
        if hearing_date is not None:
            subject_start = at_once.end()
    if hearing_date is None:
        day_of = _DATE_DAY_OF.search(text, after_trigger)
        if day_of:
            day, month, year = day_of.groups()
            hearing_date = _real_date(month, day, year)
    if hearing_date is None:
        held = _DATE_TO_BE_HELD.search(text, after_trigger)
        if held:
            hearing_date = _real_date(*held.groups())

    if hearing_date is not None:
        change = _DATE_CHANGE.search(text)
        if change:
            groups = change.groups()
            moved_from = _real_date(*groups[:3])
            moved_to = _real_date(*groups[3:])
            if moved_to is not None and moved_from == hearing_date:
                hearing_date = moved_to

    kind = "other"
    for name, pattern in _KIND_TESTS:
        if pattern.search(text):
            kind = name
            break

    count_match = _PROPERTY_COUNT.search(text)
    property_count = int(count_match.group(1)) if count_match else None

    subject = text[subject_start:].lstrip(", ").rstrip()
    if kind == "weed_lots" and property_count is not None:
        subject_key = f"weeds:{property_count}"
    else:
        subject_key = _subject_key(subject)

    return HearingReading(
        hearing_date=hearing_date,
        kind=kind,
        subject=subject,
        subject_key=subject_key,
        property_count=property_count,
    )


def same_hearing(key_a: str, key_b: str) -> bool:
    """Do two subject keys name one hearing? Dates and kinds are the caller's."""
    if key_a == key_b:
        return True
    shorter, longer = sorted((key_a, key_b), key=len)
    return len(shorter) >= PREFIX_MIN and longer.startswith(shorter)
