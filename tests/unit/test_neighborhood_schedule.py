"""The neighborhood association schedule: the checked-in file, and its loader.

Plan `birmingham-coming-up`, M4. Three groups. The first reads the real
Birmingham file under `content/coming-up/birmingham/`. The second builds a
three-association schedule in a temporary directory to show what the loader
refuses. The third opens the saved PDF and holds every transcribed row to
the row the city printed.

`docket.services.neighborhood_schedule` is imported inside each test, not at
the top of the module, so the file collects before the module exists.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import os
import re
import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
BIRMINGHAM = REPO / "content" / "coming-up" / "birmingham"
SCHEDULE_FILE = "neighborhood-schedule.yaml"
PDF_NAME = "2026_NA_Meeting_Schedule_rev._2-3-2026.pdf"
PDF_SHA256 = "f9987d63389a280b5333fb9675d090bcf76c3069ccce7f05ea1052fabda7333e"

# Rows where pdfplumber's table reading is itself wrong, name to reason. For
# these the place and the remote are held to the page's text instead of the
# row's fourth cell. Each entry is recorded in the plan's Decision Log.
TABLE_MISREADS = {
    "Highland Park": (
        "extract_tables() returns this row's fourth cell empty; the page prints "
        '"Visit highland-park.org for in-person meeting location / MI: 819 7094 5731"'
    ),
}


def _load(city_dir: Path):
    from docket.services.neighborhood_schedule import load_schedule

    return load_schedule(city_dir)


def _by_name(schedule) -> dict:
    return {a.name: a for a in schedule.associations}


# ---------------------------------------------------------------------------
# The checked-in Birmingham file
# ---------------------------------------------------------------------------


def test_the_checked_in_file_loads_and_holds_99_associations():
    schedule = _load(BIRMINGHAM)
    assert len(schedule.associations) == 99
    assert len({a.name for a in schedule.associations}) == 99


def test_the_source_block_is_the_citys_document():
    schedule = _load(BIRMINGHAM)
    assert schedule.title == (
        "City of Birmingham Community Resource Services Division Neighborhood Association Meeting Schedule"
    )
    assert schedule.revised == date(2026, 2, 3)
    assert schedule.url == (
        "https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/s3fs-public/2026-02/" + PDF_NAME
    )
    assert schedule.file == "sources/" + PDF_NAME
    assert schedule.sha256 == PDF_SHA256
    assert schedule.read == date(2026, 11, 17)
    assert schedule.year == 2026


def test_the_saved_pdf_has_the_digest_the_yaml_and_the_readme_record():
    digest = hashlib.sha256((BIRMINGHAM / "sources" / PDF_NAME).read_bytes()).hexdigest()
    assert digest == PDF_SHA256
    assert _load(BIRMINGHAM).sha256 == digest
    readme = (BIRMINGHAM / "sources" / "README.md").read_text(encoding="utf-8")
    assert digest in readme
    assert PDF_NAME in readme


def test_the_first_check_is_the_sessions_own():
    schedule = _load(BIRMINGHAM)
    first = schedule.checked[0]
    assert first.by == "Claude, plan birmingham-coming-up M4"
    assert first.on == date(2026, 11, 17)
    assert first.how == "each row compared with the saved PDF's page"


def test_acipco_finley_is_the_row_the_plan_gives():
    a = _by_name(_load(BIRMINGHAM))["Acipco-Finley"]
    assert a.rule_text == "First Wednesday of each month @ 5:30 p.m."
    assert (a.ordinal, a.weekday, a.months, a.time) == ("first", "wednesday", None, "17:30")
    assert a.type_text == "In-Person"
    assert a.modes == ("in_person",)
    assert a.place == "Acipco Finley Community Room, 453 38th Ave W, Birmingham, AL 35207"
    assert a.remote is None
    assert a.undated_reason is None


def test_the_two_undated_rows_and_their_reasons():
    schedule = _load(BIRMINGHAM)
    undated = {a.name: a for a in schedule.associations if a.ordinal is None}
    assert sorted(undated) == ["Bridlewood", "Glen Iris"]
    assert undated["Bridlewood"].undated_reason == "The schedule says: No Meetings"
    assert undated["Bridlewood"].modes == ()
    assert undated["Bridlewood"].place is None and undated["Bridlewood"].remote is None
    assert undated["Glen Iris"].undated_reason == "The schedule says: First Monday of this month @ 6:30 pm"
    assert undated["Glen Iris"].rule_text == "First Monday of this month @ 6:30 pm"
    assert all(a.weekday is None for a in undated.values())


def test_overton_alone_names_its_months():
    schedule = _load(BIRMINGHAM)
    with_months = {a.name: a.months for a in schedule.associations if a.months is not None}
    assert with_months == {"Overton": (2, 4, 6, 8, 10, 12)}
    overton = _by_name(schedule)["Overton"]
    assert (overton.ordinal, overton.weekday, overton.time) == ("first", "tuesday", "18:00")


@pytest.mark.parametrize(
    "name, ordinal, weekday, time",
    [
        ("Brown Springs", "third", "thursday", "18:00"),
        ("Huffman", "fourth", "monday", "19:00"),
        ("Gate City", "second", "monday", "16:00"),
        ("Jones Valley", "first", "friday", "16:00"),
        ("East Birmingham", "fourth", "monday", "18:00"),
        ("West Brownsville", "second", "thursday", "10:00"),
        ("Dolomite", "fourth", "tuesday", "18:00"),
        ("Smithfield Estates", "third", "saturday", "14:00"),
        ("Brummit Heights", "first", "thursday", "13:00"),
    ],
)
def test_rules_the_plan_works_by_hand_are_transcribed_so(name, ordinal, weekday, time):
    a = _by_name(_load(BIRMINGHAM))[name]
    assert (a.ordinal, a.weekday, a.time) == (ordinal, weekday, time)


def test_misspellings_stay_as_the_city_printed_them():
    by_name = _by_name(_load(BIRMINGHAM))
    assert by_name["Brummit Heights"].type_text == "In-Persopn"
    assert by_name["Maple Grove"].type_text == "Coference Call"
    assert by_name["Zion City"].type_text == "Teleconfernce"
    assert by_name["Eastwood"].type_text == "Confernce Call/ In Person"


def test_modes_follow_the_order_of_the_type_cell():
    by_name = _by_name(_load(BIRMINGHAM))
    assert by_name["College Hills"].modes == ("in_person", "phone")
    assert by_name["East Brownsville"].modes == ("phone", "in_person")
    assert by_name["Enon Ridge"].modes == ("video", "in_person")
    assert by_name["Highland Park"].modes == ("in_person", "video")
    assert by_name["Maple Grove"].modes == ("phone",)
    assert by_name["Norwood"].modes == ("video",)


def test_gate_citys_call_is_to_be_determined_so_it_has_no_remote():
    gate_city = _by_name(_load(BIRMINGHAM))["Gate City"]
    assert gate_city.modes == ("phone", "in_person")
    assert gate_city.place == "Marks Village Campus of Hope 7527 66th Street South, 35212"
    assert gate_city.remote is None


def test_highland_parks_information_is_taken_from_the_page():
    highland_park = _by_name(_load(BIRMINGHAM))["Highland Park"]
    assert highland_park.place == "Visit highland-park.org for in-person meeting location"
    assert highland_park.remote == "MI: 819 7094 5731"


def test_a_cell_with_both_parts_is_divided_and_each_part_is_as_printed():
    by_name = _by_name(_load(BIRMINGHAM))
    assert by_name["East Brownsville"].place == "(May-Nov) Mary Dorsey Center 4560 Park Ave SW, 35221"
    assert by_name["East Brownsville"].remote == "(Jan-Apr) Dial: 605-313-4198/ Access Code: 461297"
    assert by_name["Hooper City"].place == "Hooper City Rec. Center 3901 4th Street West"
    assert by_name["Hooper City"].remote == "952 206 4918 Code: 223418"
    assert by_name["Brown Springs"].place is None
    assert by_name["Brown Springs"].remote == "Dial: 712-832-8330 / Access Code: 5102692"


def test_every_row_prints_a_time():
    assert [a.name for a in _load(BIRMINGHAM).associations if a.time is None] == []


def test_get_schedule_returns_birminghams_and_keeps_it():
    from docket.services import neighborhood_schedule

    first = neighborhood_schedule.get_schedule("birmingham")
    assert first is not None and len(first.associations) == 99
    assert neighborhood_schedule.get_schedule("birmingham") is first


def test_get_schedule_is_none_for_a_city_with_no_file():
    from docket.services import neighborhood_schedule

    assert neighborhood_schedule.get_schedule("mobile") is None


def test_get_schedule_reads_under_coming_up_root_and_caches_per_slug(tmp_path, monkeypatch):
    from docket import config
    from docket.services import neighborhood_schedule

    monkeypatch.setattr(config, "COMING_UP_ROOT", str(tmp_path))
    monkeypatch.setattr(neighborhood_schedule, "_cache", {})
    assert neighborhood_schedule.get_schedule("testville") is None

    city_dir = _write_city(tmp_path, _doc())
    loaded = neighborhood_schedule.get_schedule("testville")
    assert [a.name for a in loaded.associations] == ["Alder Park", "Birch Hill", "Cedar Grove"]
    # Birmingham's real file is not what this root holds.
    assert neighborhood_schedule.get_schedule("birmingham") is None

    # Cached for the life of the process: the file going away changes nothing.
    (city_dir / SCHEDULE_FILE).unlink()
    assert neighborhood_schedule.get_schedule("testville") is loaded


def test_the_root_is_configuration_with_the_checked_in_directory_as_its_default():
    from docket import config

    assert config.COMING_UP_ROOT == os.environ.get("COMING_UP_ROOT", "content/coming-up")
    if "COMING_UP_ROOT" not in os.environ:
        assert config.COMING_UP_ROOT == "content/coming-up"


def test_the_loader_imports_nothing_from_the_web_layer():
    source = (REPO / "src" / "docket" / "services" / "neighborhood_schedule.py").read_text(encoding="utf-8")
    assert "docket.web" not in source
    assert "from docket import web" not in source


# ---------------------------------------------------------------------------
# What the loader refuses, on a three-association file in tmp_path
# ---------------------------------------------------------------------------

FAKE_PDF = b"%PDF-1.4\nnot a real schedule, only bytes with a digest\n"


def _doc() -> dict:
    return {
        "source": {
            "title": "Testville Neighborhood Schedule",
            "revised": date(2026, 2, 3),
            "url": "https://example.org/schedule.pdf",
            "file": "sources/schedule.pdf",
            "sha256": hashlib.sha256(FAKE_PDF).hexdigest(),
            "read": date(2026, 11, 17),
            "year": 2026,
        },
        "checked": [{"by": "A reader", "on": date(2026, 11, 17), "how": "each row read against the page"}],
        "associations": [
            {
                "name": "Alder Park",
                "rule_text": "First Wednesday of each month @ 5:30 p.m.",
                "ordinal": "first",
                "weekday": "wednesday",
                "time": "17:30",
                "type_text": "In-Person",
                "modes": ["in_person"],
                "place": "Alder Park Hall, 1 Alder Street",
                "remote": None,
            },
            {
                "name": "Birch Hill",
                "rule_text": "Meeting months: Second Monday on Feb & Aug @ 6:00 p.m.",
                "ordinal": "second",
                "weekday": "monday",
                "months": [2, 8],
                "time": "18:00",
                "type_text": "Zoom/ Conference Call",
                "modes": ["video", "phone"],
                "place": None,
                "remote": "Dial: 555-0100 / Access Code: 1234",
            },
            {
                "name": "Cedar Grove",
                "rule_text": "First Tuesday of each month @ 6:00 p.m.",
                "ordinal": None,
                "weekday": None,
                "time": None,
                "type_text": "No Meetings",
                "modes": [],
                "place": None,
                "remote": None,
                "undated_reason": "The schedule says: No Meetings",
            },
        ],
    }


def _write_city(tmp_path: Path, doc: dict, *, pdf: bytes | None = FAKE_PDF) -> Path:
    """Write ``doc`` as testville's schedule under ``tmp_path``; ``pdf=None`` saves no source file."""
    city_dir = tmp_path / "testville"
    (city_dir / "sources").mkdir(parents=True, exist_ok=True)
    if pdf is not None:
        (city_dir / "sources" / "schedule.pdf").write_bytes(pdf)
    (city_dir / SCHEDULE_FILE).write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return city_dir


def _refused(tmp_path: Path, doc: dict, **kwargs) -> str:
    from docket.services.neighborhood_schedule import ScheduleError

    city_dir = _write_city(tmp_path, doc, **kwargs)
    with pytest.raises(ScheduleError) as excinfo:
        _load(city_dir)
    message = str(excinfo.value)
    assert str(city_dir / SCHEDULE_FILE) in message, message
    return message


def test_schedule_error_is_a_value_error():
    from docket.services.neighborhood_schedule import ScheduleError

    assert issubclass(ScheduleError, ValueError)


def test_the_three_association_file_loads(tmp_path):
    schedule = _load(_write_city(tmp_path, _doc()))
    alder, birch, cedar = schedule.associations
    assert (alder.name, alder.ordinal, alder.weekday, alder.months, alder.time) == (
        "Alder Park",
        "first",
        "wednesday",
        None,
        "17:30",
    )
    assert alder.modes == ("in_person",)
    assert alder.place == "Alder Park Hall, 1 Alder Street" and alder.remote is None
    assert alder.undated_reason is None
    assert birch.months == (2, 8)
    assert birch.modes == ("video", "phone")
    assert birch.place is None and birch.remote == "Dial: 555-0100 / Access Code: 1234"
    assert (cedar.ordinal, cedar.weekday, cedar.time, cedar.modes) == (None, None, None, ())
    assert cedar.undated_reason == "The schedule says: No Meetings"
    assert cedar.type_text == "No Meetings"
    assert schedule.title == "Testville Neighborhood Schedule"
    assert schedule.revised == date(2026, 2, 3)
    assert schedule.url == "https://example.org/schedule.pdf"
    assert schedule.file == "sources/schedule.pdf"
    assert schedule.sha256 == hashlib.sha256(FAKE_PDF).hexdigest()
    assert schedule.read == date(2026, 11, 17)
    assert schedule.year == 2026
    assert len(schedule.checked) == 1
    assert (schedule.checked[0].by, schedule.checked[0].on) == ("A reader", date(2026, 11, 17))
    assert schedule.checked[0].how == "each row read against the page"


def test_what_is_loaded_cannot_be_changed(tmp_path):
    schedule = _load(_write_city(tmp_path, _doc()))
    with pytest.raises(dataclasses.FrozenInstanceError):
        schedule.year = 2027
    with pytest.raises(dataclasses.FrozenInstanceError):
        schedule.associations[0].time = "09:00"
    assert isinstance(schedule.associations, tuple)
    assert isinstance(schedule.checked, tuple)


def _drop(section: str | None, key: str):
    def mutate(doc):
        target = doc if section is None else doc[section]
        del target[key]

    return mutate


def _add(section: str | None, key: str):
    def mutate(doc):
        target = doc if section is None else doc[section]
        target[key] = "x"

    return mutate


def _assoc(index: int, **changes):
    """Change keys of one association; a value of ``...`` deletes the key."""

    def mutate(doc):
        for key, value in changes.items():
            if value is ...:
                del doc["associations"][index][key]
            else:
                doc["associations"][index][key] = value

    return mutate


def _check(**changes):
    def mutate(doc):
        for key, value in changes.items():
            if value is ...:
                del doc["checked"][0][key]
            else:
                doc["checked"][0][key] = value

    return mutate


def _source(**changes):
    def mutate(doc):
        doc["source"].update(changes)

    return mutate


def _set(key, value):
    def mutate(doc):
        doc[key] = value

    return mutate


def _second_named_like_first(doc):
    doc["associations"][1]["name"] = doc["associations"][0]["name"]


REFUSALS = [
    # a missing or unknown key, at each level
    ("top-level key missing", _drop(None, "checked"), ["checked"]),
    ("top-level key unknown", _add(None, "notes"), ["notes"]),
    ("source key missing", _drop("source", "sha256"), ["source", "sha256"]),
    ("source key unknown", _add("source", "publisher"), ["source", "publisher"]),
    ("check key missing", _check(how=...), ["checked", "how"]),
    ("check key unknown", _check(mood="x"), ["checked", "mood"]),
    ("association key missing", _assoc(0, remote=...), ["Alder Park", "remote"]),
    ("association key unknown", _assoc(0, venue="x"), ["Alder Park", "venue"]),
    ("association name missing", _assoc(1, name=...), ["associations[1]", "name"]),
    # a value outside its vocabulary
    ("ordinal outside", _assoc(0, ordinal="fifth"), ["Alder Park", "ordinal", "fifth"]),
    ("ordinal last", _assoc(0, ordinal="last"), ["Alder Park", "ordinal", "last"]),
    ("weekday capitalised", _assoc(0, weekday="Wednesday"), ["Alder Park", "weekday", "Wednesday"]),
    ("mode outside", _assoc(1, modes=["video", "zoom"]), ["Birch Hill", "modes", "zoom"]),
    ("modes not a list", _assoc(0, modes="in_person"), ["Alder Park", "modes"]),
    ("month thirteen", _assoc(1, months=[2, 13]), ["Birch Hill", "months", "13"]),
    ("month zero", _assoc(1, months=[0, 2]), ["Birch Hill", "months", "0"]),
    ("month as text", _assoc(1, months=["2"]), ["Birch Hill", "months"]),
    ("months empty", _assoc(1, months=[]), ["Birch Hill", "months"]),
    ("months not a list", _assoc(1, months=2), ["Birch Hill", "months"]),
    # one of ordinal and weekday null and the other not
    (
        "ordinal null, weekday not",
        _assoc(0, ordinal=None, undated_reason="The schedule says: x"),
        ["Alder Park", "ordinal", "weekday"],
    ),
    ("weekday null, ordinal not", _assoc(0, weekday=None), ["Alder Park", "ordinal", "weekday"]),
    # a time that is not HH:MM
    ("time without a leading zero", _assoc(0, time="5:30"), ["Alder Park", "time", "5:30"]),
    ("time past the day", _assoc(0, time="24:00"), ["Alder Park", "time", "24:00"]),
    ("time past the hour", _assoc(0, time="17:60"), ["Alder Park", "time", "17:60"]),
    ("time with seconds", _assoc(0, time="17:30:00"), ["Alder Park", "time", "17:30:00"]),
    ("time in words", _assoc(0, time="5:30 p.m."), ["Alder Park", "time"]),
    ("time as a number", _assoc(0, time=1050), ["Alder Park", "time", "1050"]),
    # names
    ("duplicate name", _second_named_like_first, ["Alder Park", "more than once"]),
    ("empty name", _assoc(0, name=""), ["associations[0]", "name"]),
    # empty texts
    ("empty rule_text", _assoc(0, rule_text=""), ["Alder Park", "rule_text"]),
    ("blank rule_text", _assoc(0, rule_text="   "), ["Alder Park", "rule_text"]),
    ("empty type_text", _assoc(0, type_text=""), ["Alder Park", "type_text"]),
    ("rule_text not text", _assoc(0, rule_text=None), ["Alder Park", "rule_text"]),
    # place and remote are text or null
    ("place not text", _assoc(0, place=453), ["Alder Park", "place"]),
    ("remote not text", _assoc(1, remote=["555-0100"]), ["Birch Hill", "remote"]),
    ("place empty", _assoc(0, place=""), ["Alder Park", "place"]),
    # undated_reason exactly when there is no ordinal
    (
        "undated_reason with an ordinal",
        _assoc(0, undated_reason="The schedule says: x"),
        ["Alder Park", "undated_reason"],
    ),
    ("undated_reason absent without one", _assoc(2, undated_reason=...), ["Cedar Grove", "undated_reason"]),
    ("undated_reason empty", _assoc(2, undated_reason=""), ["Cedar Grove", "undated_reason"]),
    # the checks
    ("checked empty", _set("checked", []), ["checked"]),
    ("checked not a list", _set("checked", "Claude"), ["checked"]),
    ("check date not a date", _check(on="yesterday"), ["checked", "on"]),
    ("check by empty", _check(by=""), ["checked", "by"]),
    # the source block's own values
    ("revised not a date", _source(revised="February 3, 2026"), ["source", "revised"]),
    ("read not a date", _source(read="today"), ["source", "read"]),
    ("year not a number", _source(year="2026"), ["source", "year"]),
    ("title empty", _source(title=""), ["source", "title"]),
    # shapes
    ("associations not a list", _set("associations", {"name": "x"}), ["associations"]),
    ("an association not a mapping", _set("associations", ["Alder Park"]), ["associations[0]"]),
    ("source not a mapping", _set("source", "the PDF"), ["source"]),
]


@pytest.mark.parametrize("mutate, expected", [r[1:] for r in REFUSALS], ids=[r[0] for r in REFUSALS])
def test_the_loader_refuses(tmp_path, mutate, expected):
    doc = _doc()
    mutate(doc)
    message = _refused(tmp_path, doc)
    for words in expected:
        assert words in message, message


def test_each_valid_file_change_still_loads(tmp_path):
    """The refusals above are not refusals of everything: the neighbours of each rule load."""
    doc = _doc()
    doc["associations"][0]["time"] = None
    doc["associations"][0]["ordinal"] = "fourth"
    doc["associations"][0]["weekday"] = "sunday"
    doc["associations"][1]["months"] = [1, 12]
    doc["associations"][1]["time"] = "00:00"
    doc["associations"][2]["time"] = "23:59"
    schedule = _load(_write_city(tmp_path, doc))
    assert schedule.associations[0].time is None
    assert (schedule.associations[0].ordinal, schedule.associations[0].weekday) == ("fourth", "sunday")
    assert schedule.associations[1].months == (1, 12)
    assert schedule.associations[1].time == "00:00"
    assert schedule.associations[2].time == "23:59"


@pytest.mark.parametrize("ordinal", ["first", "second", "third", "fourth"])
def test_each_ordinal_of_the_vocabulary_loads(tmp_path, ordinal):
    doc = _doc()
    doc["associations"][0]["ordinal"] = ordinal
    assert _load(_write_city(tmp_path, doc)).associations[0].ordinal == ordinal


@pytest.mark.parametrize(
    "weekday", ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
)
def test_each_weekday_of_the_vocabulary_loads(tmp_path, weekday):
    doc = _doc()
    doc["associations"][0]["weekday"] = weekday
    assert _load(_write_city(tmp_path, doc)).associations[0].weekday == weekday


@pytest.mark.parametrize("mode", ["in_person", "phone", "video"])
def test_each_mode_of_the_vocabulary_loads(tmp_path, mode):
    doc = _doc()
    doc["associations"][0]["modes"] = [mode]
    assert _load(_write_city(tmp_path, doc)).associations[0].modes == (mode,)


@pytest.mark.parametrize("key", ["on", '"on"'])
def test_a_checks_date_is_read_whether_or_not_its_key_is_quoted(tmp_path, key):
    """YAML 1.1 reads a bare `on` as the boolean true; the loader reads it as the key."""
    city_dir = _write_city(tmp_path, _doc())
    path = city_dir / SCHEDULE_FILE
    text = path.read_text(encoding="utf-8")
    assert text.count("'on': 2026-11-17") == 1
    path.write_text(text.replace("'on': 2026-11-17", f"{key}: 2026-11-17"), encoding="utf-8")
    assert _load(city_dir).checked[0].on == date(2026, 11, 17)


def test_a_check_that_writes_its_date_twice_is_refused(tmp_path):
    from docket.services.neighborhood_schedule import ScheduleError

    city_dir = _write_city(tmp_path, _doc())
    path = city_dir / SCHEDULE_FILE
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("'on': 2026-11-17", "'on': 2026-11-17\n  on: 2026-11-18"), encoding="utf-8")
    with pytest.raises(ScheduleError) as excinfo:
        _load(city_dir)
    assert "checked[0]" in str(excinfo.value)


def test_the_checked_in_file_writes_its_checks_date_under_a_bare_key():
    text = (BIRMINGHAM / SCHEDULE_FILE).read_text(encoding="utf-8")
    assert "\n    on: 2026-11-17\n" in text


def test_a_missing_schedule_file_is_refused(tmp_path):
    from docket.services.neighborhood_schedule import ScheduleError

    city_dir = tmp_path / "testville"
    city_dir.mkdir()
    with pytest.raises(ScheduleError) as excinfo:
        _load(city_dir)
    assert str(city_dir / SCHEDULE_FILE) in str(excinfo.value)


def test_a_file_that_is_not_yaml_is_refused(tmp_path):
    from docket.services.neighborhood_schedule import ScheduleError

    city_dir = _write_city(tmp_path, _doc())
    (city_dir / SCHEDULE_FILE).write_text("source: [unclosed\n", encoding="utf-8")
    with pytest.raises(ScheduleError) as excinfo:
        _load(city_dir)
    assert str(city_dir / SCHEDULE_FILE) in str(excinfo.value)


def test_a_file_that_is_not_a_mapping_is_refused(tmp_path):
    from docket.services.neighborhood_schedule import ScheduleError

    city_dir = _write_city(tmp_path, _doc())
    (city_dir / SCHEDULE_FILE).write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ScheduleError):
        _load(city_dir)


def test_a_source_file_that_does_not_exist_is_refused(tmp_path):
    message = _refused(tmp_path, _doc(), pdf=None)
    assert "sources/schedule.pdf" in message
    assert "does not exist" in message


def test_a_saved_file_with_another_digest_is_refused(tmp_path):
    message = _refused(tmp_path, _doc(), pdf=FAKE_PDF + b"one more byte")
    assert "sources/schedule.pdf" in message
    assert hashlib.sha256(FAKE_PDF).hexdigest() in message
    assert hashlib.sha256(FAKE_PDF + b"one more byte").hexdigest() in message


def test_the_source_file_is_looked_for_inside_the_city_directory(tmp_path):
    """A `file` that climbs out of the city's directory is refused, whatever it points at."""
    outside = tmp_path / "elsewhere.pdf"
    outside.write_bytes(FAKE_PDF)
    doc = _doc()
    doc["source"]["file"] = "../elsewhere.pdf"
    message = _refused(tmp_path, doc)
    assert "../elsewhere.pdf" in message


def test_changing_the_checked_in_digest_by_a_digit_is_refused(tmp_path):
    from docket.services.neighborhood_schedule import ScheduleError

    city_dir = tmp_path / "birmingham"
    shutil.copytree(BIRMINGHAM, city_dir)
    path = city_dir / SCHEDULE_FILE
    text = path.read_text(encoding="utf-8")
    assert text.count(PDF_SHA256) == 1
    path.write_text(text.replace(PDF_SHA256, PDF_SHA256[:-1] + "f"), encoding="utf-8")
    assert PDF_SHA256[-1] != "f"
    with pytest.raises(ScheduleError) as excinfo:
        _load(city_dir)
    assert PDF_SHA256 in str(excinfo.value)


# ---------------------------------------------------------------------------
# The cross-check against the saved PDF
# ---------------------------------------------------------------------------


def _norm(text: str | None) -> str:
    """Lower-cased letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _pdf_rows_and_text(pdf_path: Path) -> tuple[list[list], str]:
    import pdfplumber

    rows: list[list] = []
    texts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                rows.extend(table)
            texts.append(page.extract_text() or "")
    return rows, "\n".join(texts)


def _is_header(row: list) -> bool:
    return row[0] is None or _norm(row[0]) == "neighborhoodassociation"


def cross_check(city_dir: Path) -> list[str]:
    """Every way the transcription in ``city_dir`` disagrees with its saved PDF's table."""
    doc = yaml.safe_load((city_dir / SCHEDULE_FILE).read_text(encoding="utf-8"))
    rows, page_text = _pdf_rows_and_text(city_dir / doc["source"]["file"])
    page_text = _norm(page_text)
    problems: list[str] = []
    matched: set[int] = set()
    for a in doc["associations"]:
        name = a["name"]
        want = (_norm(name), _norm(a["rule_text"]), _norm(a["type_text"]))
        hits = [i for i, row in enumerate(rows) if tuple(_norm(cell) for cell in row[:3]) == want]
        if len(hits) != 1:
            problems.append(f"{name}: name, rule_text and type_text equal {len(hits)} table rows, not one")
            continue
        matched.add(hits[0])
        fourth = _norm(rows[hits[0]][3])
        misread = name in TABLE_MISREADS
        parts = [(key, a[key]) for key in ("place", "remote") if a[key] is not None]
        for key, value in parts:
            if _norm(value) not in (page_text if misread else fourth):
                where = "the page's text" if misread else "the row's fourth cell"
                problems.append(f"{name}: {key} {value!r} is not in {where}")
        if misread and parts and all(_norm(value) in fourth for _, value in parts):
            problems.append(f"{name}: listed as a table misreading, but the table holds its place and remote")
    for i, row in enumerate(rows):
        if i not in matched and not _is_header(row):
            problems.append(f"table row {row[0]!r} is transcribed by no association")
    for name in TABLE_MISREADS:
        if name not in {a["name"] for a in doc["associations"]}:
            problems.append(f"{name}: listed as a table misreading, but is no association")
    return problems


def test_every_association_is_one_row_of_the_saved_pdfs_table():
    assert cross_check(BIRMINGHAM) == []


def test_the_saved_pdfs_table_has_two_header_rows_and_99_associations():
    rows, _ = _pdf_rows_and_text(BIRMINGHAM / "sources" / PDF_NAME)
    assert len(rows) == 101
    assert sum(1 for row in rows if _is_header(row)) == 2


def test_highland_park_is_the_one_row_the_table_reading_gets_wrong():
    rows, page_text = _pdf_rows_and_text(BIRMINGHAM / "sources" / PDF_NAME)
    empty_fourth = [row[0] for row in rows if not _is_header(row) and not (row[3] or "").strip()]
    assert empty_fourth == ["Highland Park"]
    assert sorted(TABLE_MISREADS) == ["Highland Park"]
    assert "Visit highland-park.org for in-person meeting location / MI: 819 7094 5731" in page_text


def _copy_with(tmp_path: Path, change) -> Path:
    """A copy of Birmingham's directory whose parsed YAML ``change`` has altered."""
    city_dir = tmp_path / "birmingham"
    shutil.copytree(BIRMINGHAM, city_dir)
    path = city_dir / SCHEDULE_FILE
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    change({a["name"]: a for a in doc["associations"]}, doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return city_dir


def test_an_untouched_copy_passes_the_cross_check(tmp_path):
    assert cross_check(_copy_with(tmp_path, lambda by_name, doc: None)) == []


def test_one_letter_changed_in_a_rule_text_fails_the_cross_check(tmp_path):
    def change(by_name, doc):
        assert by_name["Acipco-Finley"]["rule_text"] == "First Wednesday of each month @ 5:30 p.m."
        by_name["Acipco-Finley"]["rule_text"] = "First Wednesdoy of each month @ 5:30 p.m."

    problems = cross_check(_copy_with(tmp_path, change))
    assert problems == [
        "Acipco-Finley: name, rule_text and type_text equal 0 table rows, not one",
        "table row 'Acipco-Finley' is transcribed by no association",
    ]


@pytest.mark.parametrize(
    "name, key, value, fragment",
    [
        ("Huffman", "name", "Hufman", "Hufman: name, rule_text and type_text equal 0 table rows"),
        ("Huffman", "type_text", "In Person & Zoom", "Huffman: name, rule_text and type_text equal 0 table rows"),
        ("Huffman", "rule_text", "Fourth Monday of each month @ 7:30 p.m.", "Huffman: name, rule_text"),
        ("Huffman", "place", "Huffman Baptist Church, 701 Huffman Road, 35215", "Huffman: place"),
        ("Brown Springs", "remote", "Dial: 712-832-8330 / Access Code: 5102693", "Brown Springs: remote"),
        # a place that another row prints, and this row does not
        ("Huffman", "place", "Mary Dorsey Center 4560 Park Avenue SW, 35221", "Huffman: place"),
        # Highland Park is held to the page's text, not let off
        ("Highland Park", "remote", "MI: 819 7094 5732", "Highland Park: remote"),
        ("Highland Park", "place", "Visit highland-park.com for in-person meeting location", "Highland Park: place"),
    ],
)
def test_a_changed_cell_fails_the_cross_check(tmp_path, name, key, value, fragment):
    def change(by_name, doc):
        assert by_name[name][key] != value
        by_name[name][key] = value

    problems = cross_check(_copy_with(tmp_path, change))
    assert any(fragment in problem for problem in problems), problems


def test_a_row_left_out_fails_the_cross_check(tmp_path):
    def change(by_name, doc):
        doc["associations"] = [a for a in doc["associations"] if a["name"] != "Zion City"]

    assert cross_check(_copy_with(tmp_path, change)) == ["table row 'Zion City' is transcribed by no association"]


def test_a_row_transcribed_twice_under_two_names_fails_the_cross_check(tmp_path):
    def change(by_name, doc):
        twin = copy.deepcopy(by_name["Hillman"])
        twin["name"] = "Hillman Heights"
        doc["associations"].append(twin)

    problems = cross_check(_copy_with(tmp_path, change))
    assert problems == ["Hillman Heights: name, rule_text and type_text equal 0 table rows, not one"]
