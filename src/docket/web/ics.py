"""Coming-up entries as iCalendar text (the ``.ics`` a calendar program subscribes to).

``render_calendar`` writes one VEVENT per entry it is given, in the order
given, and nothing else: it asks no service and reads no clock, so the feed
holds exactly what the page built from the same entries holds. A value an
entry does not carry is absent here too. An entry with no start is an
all-day event; a start with no end has no ``DTEND``, since the source gave
none and this module invents none (``docs/PRINCIPLES.md``, "Source or
silence").

A cancelled meeting is told by its ``SUMMARY``, which begins "Cancelled: ",
and by the sentences that open its ``DESCRIPTION``. No event carries a
``STATUS`` line: some calendar programs may hide an event marked cancelled,
and the point is that a subscriber sees the meeting is off.

The format's three mechanical rules live here: text values escape
backslash, semicolon, comma and newline; every line ends CR LF; and a line
longer than 75 bytes of UTF-8 is folded, never inside a character.

Plan `birmingham-coming-up`, M8, whose Decision Log says why each rule is
what it is.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

_PRODID = "-//docket.pub//Coming up//EN"
_MAX_LINE_BYTES = 75

# An entry's kind, in the words a calendar program shows as its category.
_CATEGORIES = {
    "meeting": "Meeting",
    "hearing": "Public hearing",
    "neighborhood": "Neighborhood association",
}


def _escape(text: str) -> str:
    """A text value: backslash, semicolon and comma behind a backslash, a line break as ``\\n``."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> list[str]:
    """The line as physical lines of at most 75 bytes, each after the first opening with one space."""
    if len(line.encode("utf-8")) <= _MAX_LINE_BYTES:
        return [line]
    out: list[str] = []
    current, size = "", 0
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > _MAX_LINE_BYTES:
            out.append(current)
            current, size = " ", 1
        current += char
        size += width
    out.append(current)
    return out


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _description(entry, absolute, page_url: str) -> str:
    lines = list(entry.detail)
    lines += [f"{label}: {text}" for label, text in entry.attend]
    lines += [f"{label}: {absolute(url)}" for label, url in entry.links]
    lines.append(f"From docket.pub: {page_url}")
    return "\n".join(lines)


def _event(entry, *, stamp: str, absolute, page_url: str) -> list[str]:
    lines = ["BEGIN:VEVENT", f"UID:{entry.uid}", f"DTSTAMP:{stamp}"]
    if entry.starts_at is not None:
        lines.append(f"DTSTART:{_utc(entry.starts_at)}")
        if entry.ends_at is not None:
            lines.append(f"DTEND:{_utc(entry.ends_at)}")
    else:
        lines.append(f"DTSTART;VALUE=DATE:{entry.on:%Y%m%d}")
        lines.append(f"DTEND;VALUE=DATE:{entry.on + timedelta(days=1):%Y%m%d}")
    summary = f"Cancelled: {entry.title}" if entry.cancelled else entry.title
    lines.append(f"SUMMARY:{_escape(summary)}")
    lines.append(f"DESCRIPTION:{_escape(_description(entry, absolute, page_url))}")
    if entry.place:
        lines.append(f"LOCATION:{_escape(entry.place)}")
    url = entry.source_url or (absolute(entry.links[0][1]) if entry.links else None)
    if url:
        lines.append(f"URL:{url}")
    lines.append(f"CATEGORIES:{_escape(_CATEGORIES[entry.kind])}")
    lines.append("END:VEVENT")
    return lines


def render_calendar(
    entries, *, name: str, now: datetime, absolute, page_url: str
) -> str:
    """The entries as one VCALENDAR, one VEVENT each, in the order given.

    ``name`` is the calendar's display name. ``now`` (timezone-aware) is
    every event's ``DTSTAMP``. ``absolute`` turns a site path into an
    absolute address and returns a full address unchanged; it is applied to
    every link an event prints. ``page_url`` is the absolute address of the
    coming-up page, which closes every ``DESCRIPTION``.
    """
    stamp = _utc(now)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{_PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
    ]
    for entry in entries:
        lines += _event(entry, stamp=stamp, absolute=absolute, page_url=page_url)
    lines.append("END:VCALENDAR")
    return "".join(physical + "\r\n" for line in lines for physical in _fold(line))
