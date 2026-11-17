"""The calendar text ``docket.web.ics.render_calendar`` writes from coming-up entries.

Pure: entries are built by hand, ``now`` is passed in, and ``absolute`` is a
stand-in that prefixes ``https://docket.test`` to a site path and returns a
full address unchanged, as the route's own function does. The module is
imported inside each test, so this file collects before the module exists.

Plan `birmingham-coming-up`, M8.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

CHICAGO = ZoneInfo("America/Chicago")
NOW = datetime(2026, 11, 16, 18, 5, 9, tzinfo=timezone.utc)
PAGE = "https://docket.test/al/birmingham/coming-up/"
CITY_DOC = "https://www.birminghamal.gov/events/council-meeting"


def _absolute(url: str) -> str:
    return (
        url if url.startswith(("http://", "https://")) else "https://docket.test" + url
    )


def _entry(**changes):
    from docket.services.coming_up import Entry

    fields = {
        "kind": "meeting",
        "uid": "calendar-120@docket.pub",
        "on": date(2026, 11, 17),
        "starts_at": datetime(2026, 11, 17, 9, 30, tzinfo=CHICAGO),
        "ends_at": datetime(2026, 11, 17, 12, 0, tzinfo=CHICAGO),
        "title": "City Council meeting",
        "detail": (),
        "links": (
            ("City calendar", CITY_DOC),
            ("Meeting on docket.pub", "/al/birmingham/meetings/3207/"),
        ),
        "source_url": CITY_DOC,
        "place": None,
        "badge": "meeting",
        "badge_label": "Meeting",
        "cancelled": False,
        "cancelled_by": (),
        "attend": (),
        "association": None,
    }
    fields.update(changes)
    return Entry(**fields)


def _render(*entries, name: str = "Birmingham coming up") -> str:
    from docket.web import ics

    return ics.render_calendar(
        list(entries), name=name, now=NOW, absolute=_absolute, page_url=PAGE
    )


def _unfold(text: str) -> list[str]:
    """The content lines, each continuation joined to the line it continues."""
    lines = text.split("\r\n")
    assert lines[-1] == ""  # the text ends with CR LF
    out: list[str] = []
    for line in lines[:-1]:
        if line.startswith(" "):
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _unescape(value: str) -> str:
    out, i = [], 0
    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value):
            out.append("\n" if value[i + 1] in "nN" else value[i + 1])
            i += 2
        else:
            out.append(value[i])
            i += 1
    return "".join(out)


def _events(text: str) -> list[list[str]]:
    events: list[list[str]] = []
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            events.append([])
        elif line == "END:VEVENT":
            events.append(
                None
            )  # a line after this and before the next BEGIN would fail below
        elif events and events[-1] is not None:
            events[-1].append(line)
    return [e for e in events if e is not None]


def _value(event: list[str], name: str) -> str:
    """The one line of the event whose name (before any parameter) is `name`, as its value."""
    found = [line for line in event if line.split(":", 1)[0].split(";", 1)[0] == name]
    assert len(found) == 1, f"{len(found)} {name} lines"
    return found[0].split(":", 1)[1]


def _names(event: list[str]) -> list[str]:
    return [line.split(":", 1)[0] for line in event]


# --- the envelope -----------------------------------------------------------


def test_the_calendar_opens_and_closes_as_the_format_requires():
    lines = _unfold(_render(_entry(), name="Birmingham coming up"))

    assert lines[:6] == [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//docket.pub//Coming up//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Birmingham coming up",
    ]
    assert lines[6] == "BEGIN:VEVENT"
    assert lines[-2:] == ["END:VEVENT", "END:VCALENDAR"]


def test_no_entry_is_a_calendar_with_no_event():
    assert _unfold(_render()) == [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//docket.pub//Coming up//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Birmingham coming up",
        "END:VCALENDAR",
    ]


def test_there_is_one_event_per_entry_in_the_order_given():
    first = _entry(uid="calendar-1@docket.pub")
    second = _entry(
        uid="hearing-2@docket.pub", kind="hearing", starts_at=None, ends_at=None
    )
    third = _entry(uid="na-acipco-finley-20261202@docket.pub", kind="neighborhood")
    text = _render(first, second, third)

    assert text.count("BEGIN:VEVENT\r\n") == 3
    assert text.count("END:VEVENT\r\n") == 3
    assert [_value(e, "UID") for e in _events(text)] == [
        first.uid,
        second.uid,
        third.uid,
    ]


def test_the_calendars_name_is_escaped_like_any_text():
    lines = _unfold(
        _render(name="Forest Park, South Avondale; Neighborhood Association")
    )

    assert (
        "X-WR-CALNAME:Forest Park\\, South Avondale\\; Neighborhood Association"
        in lines
    )


# --- times ------------------------------------------------------------------


def test_an_entry_with_a_start_and_an_end_has_both_in_utc():
    (event,) = _events(_render(_entry()))

    # 9:30 a.m. and noon in Chicago on November 17 are 15:30 and 18:00 UTC (standard time, UTC-6)
    assert "DTSTART:20261117T153000Z" in event
    assert "DTEND:20261117T180000Z" in event
    assert "DTSTAMP:20261116T180509Z" in event


def test_a_summer_start_is_converted_by_that_days_offset():
    start = datetime(2026, 7, 7, 18, 0, tzinfo=CHICAGO)  # daylight time, UTC-5
    (event,) = _events(
        _render(_entry(on=date(2026, 7, 7), starts_at=start, ends_at=None))
    )

    assert "DTSTART:20260707T230000Z" in event


def test_an_evening_start_falls_on_the_next_day_in_utc():
    start = datetime(2026, 12, 2, 18, 30, tzinfo=CHICAGO)
    (event,) = _events(
        _render(_entry(on=date(2026, 12, 2), starts_at=start, ends_at=None))
    )

    assert "DTSTART:20261203T003000Z" in event


def test_an_entry_with_a_start_alone_has_no_end():
    (event,) = _events(_render(_entry(ends_at=None)))

    assert "DTSTART:20261117T153000Z" in event
    assert not [name for name in _names(event) if name.startswith("DTEND")]


def test_an_entry_with_no_time_is_an_all_day_event_that_ends_the_next_day():
    (event,) = _events(
        _render(_entry(on=date(2026, 11, 30), starts_at=None, ends_at=None))
    )

    assert "DTSTART;VALUE=DATE:20261130" in event
    assert "DTEND;VALUE=DATE:20261201" in event  # the next day, across the month's end
    assert [name for name in _names(event) if name.startswith("DT")] == [
        "DTSTAMP",
        "DTSTART;VALUE=DATE",
        "DTEND;VALUE=DATE",
    ]


def test_the_stamp_is_now_in_utc_whatever_zone_now_is_given_in():
    from docket.web import ics

    chicago_now = datetime(2026, 11, 16, 12, 5, 9, tzinfo=CHICAGO)
    text = ics.render_calendar(
        [_entry()], name="x", now=chicago_now, absolute=_absolute, page_url=PAGE
    )

    assert "DTSTAMP:20261116T180509Z" in _events(text)[0]


# --- the event's properties ---------------------------------------------------


def test_an_events_properties_are_in_one_order():
    entry = _entry(place="Council Chambers", detail=("One line",))
    (event,) = _events(_render(entry))

    assert _names(event) == [
        "UID",
        "DTSTAMP",
        "DTSTART",
        "DTEND",
        "SUMMARY",
        "DESCRIPTION",
        "LOCATION",
        "URL",
        "CATEGORIES",
    ]
    assert _value(event, "UID") == "calendar-120@docket.pub"
    assert _value(event, "SUMMARY") == "City Council meeting"


def test_the_description_is_the_detail_then_the_links_then_the_page():
    entry = _entry(detail=("First line.", "Second line."))
    (event,) = _events(_render(entry))

    assert _unescape(_value(event, "DESCRIPTION")).split("\n") == [
        "First line.",
        "Second line.",
        f"City calendar: {CITY_DOC}",
        "Meeting on docket.pub: https://docket.test/al/birmingham/meetings/3207/",
        f"From docket.pub: {PAGE}",
    ]


def test_an_entry_with_no_detail_has_a_description_of_its_links_and_the_page():
    (event,) = _events(_render(_entry()))

    assert _unescape(_value(event, "DESCRIPTION")).split("\n") == [
        f"City calendar: {CITY_DOC}",
        "Meeting on docket.pub: https://docket.test/al/birmingham/meetings/3207/",
        f"From docket.pub: {PAGE}",
    ]


def test_a_city_documents_address_is_not_given_a_second_host():
    text = "\n".join(
        _unfold(_render(_entry()))
    )  # unfolded: a fold may fall inside the address

    assert "docket.test/http" not in text
    assert text.count(CITY_DOC) == 2  # once in the description, once as the URL


def test_the_attend_pairs_follow_the_detail_and_precede_the_first_link():
    entry = _entry(
        kind="neighborhood",
        detail=("In-Person/Conference Call",),
        attend=(
            ("Where", "Harrison Park Recreation Center"),
            ("Call-in", "Dial: 205-555-0100; code 12345"),
        ),
        place="Harrison Park Recreation Center",
        links=(("City schedule (PDF)", "https://example.org/schedule.pdf"),),
        source_url="https://example.org/schedule.pdf",
    )
    (event,) = _events(_render(entry))

    assert _unescape(_value(event, "DESCRIPTION")).split("\n") == [
        "In-Person/Conference Call",
        "Where: Harrison Park Recreation Center",
        "Call-in: Dial: 205-555-0100; code 12345",
        "City schedule (PDF): https://example.org/schedule.pdf",
        f"From docket.pub: {PAGE}",
    ]


def test_an_entry_with_a_place_has_a_location_and_one_without_has_none():
    with_place, without = _events(
        _render(
            _entry(place="Council Chambers, City Hall; 3rd floor"),
            _entry(uid="b@docket.pub"),
        )
    )

    assert (
        _value(with_place, "LOCATION") == "Council Chambers\\, City Hall\\; 3rd floor"
    )
    assert "LOCATION" not in _names(without)


def test_the_url_is_the_city_document_as_it_is_given():
    address = "https://bhamal.granicus.com/AgendaViewer.php?view_id=2&event_id=2718,x;y"
    (event,) = _events(
        _render(_entry(source_url=address, links=(("Agenda", address),)))
    )

    # a URL is not text: its comma and semicolon are not escaped
    assert _value(event, "URL") == address


def test_an_entry_with_no_city_document_has_its_first_link_made_absolute_as_its_url():
    entry = _entry(
        source_url=None,
        links=(
            ("Meeting on docket.pub", "/al/birmingham/meetings/9/"),
            ("Other", "/al/birmingham/"),
        ),
    )
    (event,) = _events(_render(entry))

    assert _value(event, "URL") == "https://docket.test/al/birmingham/meetings/9/"


def test_an_entry_with_no_link_at_all_has_no_url():
    (event,) = _events(_render(_entry(source_url=None, links=())))

    assert "URL" not in _names(event)
    assert _unescape(_value(event, "DESCRIPTION")) == f"From docket.pub: {PAGE}"


def test_the_category_is_the_entrys_kind_in_words():
    meeting, hearing, neighborhood = _events(
        _render(
            _entry(uid="a@docket.pub", kind="meeting"),
            _entry(
                uid="b@docket.pub", kind="hearing", badge="zoning", badge_label="Zoning"
            ),
            _entry(uid="c@docket.pub", kind="neighborhood"),
        )
    )

    assert _value(meeting, "CATEGORIES") == "Meeting"
    assert (
        _value(hearing, "CATEGORIES") == "Public hearing"
    )  # the kind, not the label "Zoning"
    assert _value(neighborhood, "CATEGORIES") == "Neighborhood association"


# --- a cancelled meeting ------------------------------------------------------


def test_a_cancelled_entrys_summary_begins_cancelled_and_its_description_opens_with_the_sentence():
    sentence = "Cancelled, according to the city calendar."
    off = _entry(
        uid="calendar-7@docket.pub",
        cancelled=True,
        cancelled_by=("the city calendar",),
        detail=(sentence, "The council's video site still lists it."),
    )
    on = _entry(uid="calendar-8@docket.pub")
    text = _render(off, on)
    cancelled, live = _events(text)

    assert _value(cancelled, "SUMMARY") == "Cancelled: City Council meeting"
    assert _unescape(_value(cancelled, "DESCRIPTION")).split("\n")[:2] == [
        sentence,
        "The council's video site still lists it.",
    ]
    assert _value(live, "SUMMARY") == "City Council meeting"
    assert not _value(live, "SUMMARY").startswith("Cancelled")
    # the operator's decision of 2026-11-16: the title says it, and no STATUS line does
    assert not [line for line in _unfold(text) if line.startswith("STATUS")]
    assert "STATUS" not in text


# --- escaping, folding, line ends ----------------------------------------------


def test_a_comma_a_semicolon_a_backslash_and_a_newline_are_escaped():
    title = "Budget, part 2; the C:\\path\nsecond line"
    (event,) = _events(_render(_entry(title=title)))

    assert (
        _value(event, "SUMMARY") == "Budget\\, part 2\\; the C:\\\\path\\nsecond line"
    )
    assert _unescape(_value(event, "SUMMARY")) == title


def test_a_carriage_return_never_reaches_a_value():
    text = _render(_entry(title="One\r\nTwo\rThree"))
    (event,) = _events(text)

    assert _value(event, "SUMMARY") == "One\\nTwo\\nThree"
    assert "\r" not in text.replace("\r\n", "")


def test_every_line_ends_cr_lf_and_there_is_no_bare_line_feed():
    text = _render(
        _entry(detail=("A line.", "Another.")),
        _entry(uid="b@docket.pub", starts_at=None, ends_at=None),
    )

    assert text.endswith("END:VCALENDAR\r\n")
    assert "\n" not in text.replace("\r\n", "")
    assert "\r" not in text.replace("\r\n", "")
    assert "\r\n\r\n" not in text  # no empty line


def test_no_line_is_longer_than_75_bytes_and_a_long_summary_unfolds_to_itself():
    # "SUMMARY:" is 8 bytes; 66 letters bring the line to 74 bytes, so the two-byte "é" straddles byte 75.
    title = "a" * 66 + "é" + "b" * 133
    assert len(title) == 200
    text = _render(_entry(title=title, detail=("x" * 400,)))

    for line in text.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75, line
    (event,) = _events(text)
    assert _value(event, "SUMMARY") == title
    # the fold came before the character, not inside it: the first physical line is 74 bytes
    first = next(line for line in text.split("\r\n") if line.startswith("SUMMARY:"))
    assert first == "SUMMARY:" + "a" * 66
    assert len(first.encode("utf-8")) == 74


def test_a_line_is_folded_at_75_bytes_and_not_before():
    title = "a" * 200
    text = _render(_entry(title=title))
    physical = text.split("\r\n")
    start = next(i for i, line in enumerate(physical) if line.startswith("SUMMARY:"))

    assert physical[start] == "SUMMARY:" + "a" * 67  # 75 bytes
    assert physical[start + 1] == " " + "a" * 74  # a space and 74: 75 bytes
    assert physical[start + 2] == " " + "a" * 59  # the rest
    assert not physical[start + 3].startswith(" ")


def test_a_line_of_exactly_75_bytes_is_not_folded():
    title = "a" * 67  # with "SUMMARY:" exactly 75 bytes
    text = _render(_entry(title=title))

    assert "SUMMARY:" + title + "\r\nDESCRIPTION" in text


def test_a_run_of_multi_byte_characters_is_never_split():
    title = "é" * 120 + "—" * 60 + "𝄞" * 30  # two-, three- and four-byte characters
    text = _render(_entry(title=title))

    for line in text.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75
    assert _value(_events(text)[0], "SUMMARY") == title
    # every physical line decodes on its own, which a split character would not
    for raw in text.encode("utf-8").split(b"\r\n"):
        raw.decode("utf-8")


def test_the_module_executes_no_sql_and_imports_no_service_that_does():
    """`ics.py` turns entries into text; the route is what asks the service for them."""
    import ast
    from pathlib import Path

    from docket.web import ics

    tree = ast.parse(Path(ics.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")

    assert not [name for name in imported if name.startswith("docket")]
    assert not [name for name in imported if name.startswith("flask")]


# --- rules pinned after the removal check -------------------------------------


def test_the_url_is_the_entrys_source_and_not_whatever_link_comes_first():
    """No entry of the service lists a link before its city document today; the rule is `source_url` first."""
    entry = _entry(
        source_url=CITY_DOC,
        links=(
            ("Meeting on docket.pub", "/al/birmingham/meetings/3207/"),
            ("City calendar", CITY_DOC),
        ),
    )
    (event,) = _events(_render(entry))

    assert _value(event, "URL") == CITY_DOC
