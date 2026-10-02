"""Tests for adoption-pattern detection."""

from datetime import date

import psycopg2.extras
import pytest

from docket.db import db, db_cursor
from docket.services.minutes_adoption import (
    AdoptionParseError,
    DateSpan,
    extract_adoption_targets,
    is_adoption_title,
    sweep_adoptions,
)


def test_is_adoption_title_matches_canonical_patterns():
    assert is_adoption_title("Approval of Minutes from January 7, 2026")
    assert is_adoption_title("Adoption of the Minutes from December 5, 2024")
    assert is_adoption_title("Approval of the December 5, 2024 Minutes")
    assert is_adoption_title("Minutes from the Council Meeting of December 5, 2024")
    assert is_adoption_title("Minutes from the Regular Meeting of December 5, 2024")


def test_is_adoption_title_rejects_unrelated():
    assert not is_adoption_title("A Resolution authorizing HCL Contracting")
    assert not is_adoption_title("Approval of Contract with Acme Corp")


def test_extract_adoption_targets_returns_single_date():
    targets = extract_adoption_targets(
        "Approval of Minutes from December 5, 2024",
        adoption_meeting_date=date(2026, 1, 7),
    )
    assert targets == [DateSpan(date(2024, 12, 5), date(2024, 12, 5))]


def test_extract_adoption_targets_rejects_invalid_date():
    """Feb 31 is not a real date."""
    with pytest.raises(AdoptionParseError, match="invalid date"):
        extract_adoption_targets(
            "Approval of Minutes from February 31, 2024",
            adoption_meeting_date=date(2026, 1, 7),
        )


def test_extract_adoption_targets_rejects_future_date():
    with pytest.raises(AdoptionParseError, match="future"):
        extract_adoption_targets(
            "Approval of Minutes from January 1, 2030",
            adoption_meeting_date=date(2026, 1, 7),
        )


def test_extract_adoption_targets_rejects_too_old():
    """24-month window."""
    with pytest.raises(AdoptionParseError, match="window"):
        extract_adoption_targets(
            "Approval of Minutes from January 1, 2020",
            adoption_meeting_date=date(2026, 1, 7),
        )


@pytest.fixture
def adoption_scenario():
    """Adoption meeting on 2026-01-07 has an agenda item adopting minutes from 2024-12-05.
    The 2024-12-05 meeting also exists in the DB. Idempotent setup; ON DELETE CASCADE teardown.
    """
    with db() as conn:
        with conn.cursor() as cur:
            # Idempotent cleanup of any leaked test fixture rows
            cur.execute(
                "DELETE FROM meetings WHERE meeting_date IN ('2024-12-05', '2026-01-07') "
                "AND title IN ('Council Meeting', 'TEST_ADOPTION_TARGET', 'TEST_ADOPTION_SOURCE')"
            )
        conn.commit()

    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM municipalities ORDER BY id LIMIT 1")
            muni_id = cur.fetchone()["id"]

            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   VALUES (%s, 'Council Meeting', '2024-12-05', 'council') RETURNING id""",
                (muni_id,),
            )
            target_id = cur.fetchone()["id"]

            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   VALUES (%s, 'Council Meeting', '2026-01-07', 'council') RETURNING id""",
                (muni_id,),
            )
            adoption_id = cur.fetchone()["id"]

            cur.execute(
                """INSERT INTO agenda_items (meeting_id, title, item_number, is_consent)
                   VALUES (%s, 'Approval of Minutes from December 5, 2024', '5', FALSE)
                   RETURNING id""",
                (adoption_id,),
            )
            agenda_id = cur.fetchone()["id"]

            cur.execute(
                """INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions,
                                       confidence, needs_review)
                   VALUES (%s, 'minutes_text', 'passed', 5, 0, 0, 'high', FALSE) RETURNING id""",
                (adoption_id,),
            )
            vote_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO vote_agenda_items
                    (vote_id, agenda_item_id, association_type, match_method,
                     match_confidence, provisional)
                   VALUES (%s, %s, 'explicit', 'manual_test', 1.0, FALSE)""",
                (vote_id, agenda_id),
            )
        conn.commit()

    yield {"municipality_id": muni_id, "target_id": target_id, "adoption_id": adoption_id,
           "agenda_id": agenda_id, "vote_id": vote_id}

    with db() as conn:
        with conn.cursor() as cur:
            # Cascading deletes via meetings → votes/agenda_items/vote_agenda_items
            cur.execute("DELETE FROM meetings WHERE id IN (%s, %s)", (target_id, adoption_id))
        conn.commit()


def test_sweep_adoptions_sets_minutes_adopted_at_on_target(adoption_scenario):
    flipped = sweep_adoptions(adoption_scenario["municipality_id"])
    assert adoption_scenario["target_id"] in flipped

    with db_cursor() as cur:
        cur.execute(
            "SELECT minutes_adopted_at FROM meetings WHERE id = %s",
            (adoption_scenario["target_id"],),
        )
        row = cur.fetchone()
    assert row["minutes_adopted_at"] is not None


def test_sweep_adoptions_idempotent(adoption_scenario):
    """Re-running doesn't overwrite or duplicate."""
    sweep_adoptions(adoption_scenario["municipality_id"])
    with db_cursor() as cur:
        cur.execute(
            "SELECT minutes_adopted_at FROM meetings WHERE id = %s",
            (adoption_scenario["target_id"],),
        )
        first_ts = cur.fetchone()["minutes_adopted_at"]

    flipped_second = sweep_adoptions(adoption_scenario["municipality_id"])
    assert adoption_scenario["target_id"] not in flipped_second  # already adopted

    with db_cursor() as cur:
        cur.execute(
            "SELECT minutes_adopted_at FROM meetings WHERE id = %s",
            (adoption_scenario["target_id"],),
        )
        second_ts = cur.fetchone()["minutes_adopted_at"]
    assert first_ts == second_ts


# --- Birmingham batch-approval formats (lists and ranges of dates) -----------


@pytest.mark.parametrize("title", [
    "APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: January 6 - 27, 2026",
    "APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 3 – 24, 2026",
    "APPROVAL MINUTES FROM PREVIOUS MEETINGS: May 5, 12, 19 and 26, 2026",
    "APPROVAL OF MINUTES FROM A PREVIOUS MEETING:  October 7, 14, 21 & 28, 2025",
    "APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: Nov. 4, 11, 18 & 25, 2025",
])
def test_is_adoption_title_matches_batch_formats(title):
    assert is_adoption_title(title)


def test_is_adoption_title_matches_previous_minutes_wording():
    """Real 2025-07-08 agenda wording."""
    assert is_adoption_title("APPROVAL OF PREVIOUS MINUTES: March 4, 11, 18 and 25, 2025")


def test_is_adoption_title_rejects_adoption_wording_inside_a_resolution():
    """Only a title that opens with the approval is a minutes adoption."""
    assert not is_adoption_title(
        "A Resolution authorizing the adoption of the 15 minutes parking limit "
        "effective March 3, 2026"
    )


def test_is_adoption_title_rejects_minutes_not_ready():
    assert not is_adoption_title("MINUTES NOT READY:  February 3, 2026 – April  28, 2026")


_ADOPTED_ON = date(2026, 9, 1)


def _NO_REPARSE(meeting_id):
    return {"promoted": 0, "deactivated": 0}


def _d(month: int, day: int, year: int = 2026) -> DateSpan:
    return DateSpan(date(year, month, day), date(year, month, day))


@pytest.mark.parametrize("title, expected", [
    # Single date — the original canonical shape
    ("Approval of Minutes from December 5, 2025", [_d(12, 5, 2025)]),
    # Day range within one month: hyphen, en dash, and the "7 -28" typo spacing
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: January 6 - 27, 2026",
     [DateSpan(date(2026, 1, 6), date(2026, 1, 27))]),
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 3 – 24, 2026",
     [DateSpan(date(2026, 2, 3), date(2026, 2, 24))]),
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: April 7 -28, 2026",
     [DateSpan(date(2026, 4, 7), date(2026, 4, 28))]),
    # Range that crosses a month boundary
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: March 31 – April 28, 2026",
     [DateSpan(date(2026, 3, 31), date(2026, 4, 28))]),
    # Day lists with every separator the clerk has used
    ("APPROVAL MINUTES FROM PREVIOUS MEETINGS: May 5, 12, 19 and 26, 2026",
     [_d(5, 5), _d(5, 12), _d(5, 19), _d(5, 26)]),
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: June 2, 9, 16, 23 & 30, 2026",
     [_d(6, 2), _d(6, 9), _d(6, 16), _d(6, 23), _d(6, 30)]),
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: April 1 and 8, 2025",
     [_d(4, 1, 2025), _d(4, 8, 2025)]),
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: May 6, 8, 13, 20, 27, 2025",
     [_d(5, 6, 2025), _d(5, 8, 2025), _d(5, 13, 2025), _d(5, 20, 2025), _d(5, 27, 2025)]),
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: June 3, 4, 10, 17, & 24, 2025",
     [_d(6, 3, 2025), _d(6, 4, 2025), _d(6, 10, 2025), _d(6, 17, 2025), _d(6, 24, 2025)]),
    # Abbreviated month with a period
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: Dec. 2, 9, 16, 23 & 30, 2025",
     [_d(12, 2, 2025), _d(12, 9, 2025), _d(12, 16, 2025), _d(12, 23, 2025), _d(12, 30, 2025)]),
    # Two months in one list
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: July 28 and August 4, 2026",
     [_d(7, 28), _d(8, 4)]),
    # A hyphen or "to" elsewhere in the title is not a range separator: it only
    # counts when it sits directly between two date parts.
    ("Approval of Minutes from the February 3, 2026 Pre-Council Meeting and "
     "February 24, 2026 Regular Meeting",
     [_d(2, 3), _d(2, 24)]),
    ("Approval of Minutes from January 6, 2026, as amended to include remarks; "
     "and February 3, 2026",
     [_d(1, 6), _d(2, 3)]),
    # A batch spanning New Year with one trailing year
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: December 16, 23, 30 and January 6, 2026",
     [_d(12, 16, 2025), _d(12, 23, 2025), _d(12, 30, 2025), _d(1, 6)]),
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: December 16 – January 27, 2026",
     [DateSpan(date(2025, 12, 16), date(2026, 1, 27))]),
    # A list that is not in calendar order is not a New Year wrap: the earlier
    # months only move back a year when they would otherwise fall after the
    # adopting meeting.
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: August 5 – 26 and July 31, 2025",
     [DateSpan(date(2025, 8, 5), date(2025, 8, 26)), _d(7, 31, 2025)]),
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: April 1 and March 4, 11, 18 & 25, 2025",
     [_d(4, 1, 2025), _d(3, 4, 2025), _d(3, 11, 2025), _d(3, 18, 2025), _d(3, 25, 2025)]),
    # Ordinal day suffixes
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 3rd and 10th, 2026",
     [_d(2, 3), _d(2, 10)]),
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 3 – 24th, 2026",
     [DateSpan(date(2026, 2, 3), date(2026, 2, 24))]),
    # Dash look-alikes PDFs produce: non-breaking hyphen, hyphen, minus sign
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 3 \u2011 24, 2026",
     [DateSpan(date(2026, 2, 3), date(2026, 2, 24))]),
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 3 \u2010 24, 2026",
     [DateSpan(date(2026, 2, 3), date(2026, 2, 24))]),
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 3 \u2212 24, 2026",
     [DateSpan(date(2026, 2, 3), date(2026, 2, 24))]),
    # The not-ready list is never part of what was approved
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 3 – 24, 2026 "
     "MINUTES NOT READY: March 3 – April 21, 2026",
     [DateSpan(date(2026, 2, 3), date(2026, 2, 24))]),
    # Two years in one list
    ("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: Dec. 2, 9, 16, 23 & 30, 2025, "
     "January 6, 13, 20 & 27, 2026",
     [_d(12, 2, 2025), _d(12, 9, 2025), _d(12, 16, 2025), _d(12, 23, 2025),
      _d(12, 30, 2025), _d(1, 6), _d(1, 13), _d(1, 20), _d(1, 27)]),
])
def test_extract_adoption_targets_parses_batch_formats(title, expected):
    assert extract_adoption_targets(title, adoption_meeting_date=_ADOPTED_ON) == expected


def test_extract_adoption_targets_rejects_list_with_invalid_day():
    with pytest.raises(AdoptionParseError, match="invalid date"):
        extract_adoption_targets(
            "APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: June 2, 9 & 31, 2026",
            adoption_meeting_date=_ADOPTED_ON,
        )


def test_extract_adoption_targets_rejects_unrecognized_word_inside_a_date_list():
    """A misspelled month must not silently inherit the previous month
    ("Febuary 3" read as January 3) — reject the whole title instead."""
    with pytest.raises(AdoptionParseError, match="unrecognized"):
        extract_adoption_targets(
            "APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: January 27, Febuary 3 and 10, 2026",
            adoption_meeting_date=_ADOPTED_ON,
        )


def test_extract_adoption_targets_rejects_the_adopting_meetings_own_date():
    with pytest.raises(AdoptionParseError, match="not before"):
        extract_adoption_targets(
            "APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: September 1, 2026",
            adoption_meeting_date=_ADOPTED_ON,
        )


def test_extract_adoption_targets_rejects_dates_without_a_year():
    """No guessing: dateutil used to fill a missing month/year from today's date."""
    with pytest.raises(AdoptionParseError, match="no date"):
        extract_adoption_targets(
            "APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: June 2, 9 & 16",
            adoption_meeting_date=_ADOPTED_ON,
        )


@pytest.fixture
def batch_adoption_scenario():
    """Adoption meeting 2098-03-10 plus four earlier meetings:
    2098-02-03 and 2098-02-17 have minutes; 2098-02-16 does not; 2098-02-24 has minutes.
    Far-future year keeps the fixture clear of real ingested meetings.
    """
    dates = ["2098-02-03", "2098-02-16", "2098-02-17", "2098-02-24", "2098-03-10"]
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM meetings WHERE title = 'TEST_BATCH_ADOPTION' "
                "AND meeting_date = ANY(%s::date[])", (dates,),
            )
        conn.commit()

    ids: dict[str, int] = {}
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM municipalities ORDER BY id LIMIT 1")
            muni_id = cur.fetchone()["id"]
            for d in dates:
                minutes_url = None if d == "2098-02-16" else f"https://example.test/minutes/{d}"
                cur.execute(
                    """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type,
                                             minutes_url)
                       VALUES (%s, 'TEST_BATCH_ADOPTION', %s, 'council', %s) RETURNING id""",
                    (muni_id, d, minutes_url),
                )
                ids[d] = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions,
                                       confidence, needs_review)
                   VALUES (%s, 'minutes_text', 'passed', 5, 0, 0, 'high', FALSE)""",
                (ids["2098-03-10"],),
            )
        conn.commit()

    def add_adoption_item(title: str) -> None:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO agenda_items (meeting_id, title, is_consent) VALUES (%s, %s, FALSE)",
                    (ids["2098-03-10"], title),
                )
            conn.commit()

    yield {"municipality_id": muni_id, "ids": ids, "add_adoption_item": add_adoption_item}

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", (list(ids.values()),))
        conn.commit()


def _adopted_dates(ids: dict[str, int]) -> dict[str, date | None]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT meeting_date, minutes_adopted_at FROM meetings WHERE id = ANY(%s)",
            (list(ids.values()),),
        )
        return {
            r["meeting_date"].isoformat(): r["minutes_adopted_at"].date() if r["minutes_adopted_at"] else None
            for r in cur.fetchall()
        }


def test_sweep_adoptions_flips_every_date_in_a_list(batch_adoption_scenario, monkeypatch):
    monkeypatch.setattr("docket.analysis.vote_matcher.strict_reparse_meeting", _NO_REPARSE)
    s = batch_adoption_scenario
    s["add_adoption_item"]("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 3, 17 & 24, 2098")

    flipped = sweep_adoptions(s["municipality_id"])

    assert {s["ids"]["2098-02-03"], s["ids"]["2098-02-17"], s["ids"]["2098-02-24"]} <= set(flipped)
    adopted = _adopted_dates(s["ids"])
    assert adopted["2098-02-03"] == date(2098, 3, 10)
    assert adopted["2098-02-17"] == date(2098, 3, 10)
    assert adopted["2098-02-24"] == date(2098, 3, 10)
    assert adopted["2098-02-16"] is None


def test_sweep_adoptions_range_flips_only_meetings_with_minutes(batch_adoption_scenario, monkeypatch):
    """A range names a window, not specific meetings. Rows in the window that have no
    minutes document (placeholder / cancelled rows) can't have had minutes adopted."""
    monkeypatch.setattr("docket.analysis.vote_matcher.strict_reparse_meeting", _NO_REPARSE)
    s = batch_adoption_scenario
    s["add_adoption_item"]("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 3 – 24, 2098")

    flipped = sweep_adoptions(s["municipality_id"])

    assert {s["ids"]["2098-02-03"], s["ids"]["2098-02-17"], s["ids"]["2098-02-24"]} <= set(flipped)
    assert s["ids"]["2098-02-16"] not in flipped
    adopted = _adopted_dates(s["ids"])
    assert adopted["2098-02-17"] == date(2098, 3, 10)
    assert adopted["2098-02-16"] is None
    assert adopted["2098-03-10"] is None


def test_sweep_adoptions_prefers_the_row_with_minutes_when_a_date_has_duplicates(
    batch_adoption_scenario, monkeypatch
):
    """Granicus sometimes lists a second, empty clip for the same date (real case:
    2024-01-09, ids 143 and 144). The one with a minutes document is the meeting
    whose minutes were adopted."""
    monkeypatch.setattr("docket.analysis.vote_matcher.strict_reparse_meeting", _NO_REPARSE)
    s = batch_adoption_scenario
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   VALUES (%s, 'TEST_BATCH_ADOPTION', '2098-02-17', 'council') RETURNING id""",
                (s["municipality_id"],),
            )
            empty_dup_id = cur.fetchone()[0]
        conn.commit()
    s["ids"]["2098-02-17-dup"] = empty_dup_id  # fixture teardown deletes it
    s["add_adoption_item"]("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 17, 2098")

    flipped = sweep_adoptions(s["municipality_id"])

    assert s["ids"]["2098-02-17"] in flipped
    assert empty_dup_id not in flipped


def test_sweep_adoptions_range_skips_hidden_meetings(batch_adoption_scenario, monkeypatch):
    """Rows an admin hid as not-real meetings are not swept up by a date range."""
    monkeypatch.setattr("docket.analysis.vote_matcher.strict_reparse_meeting", _NO_REPARSE)
    s = batch_adoption_scenario
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE meetings SET is_hidden = TRUE WHERE id = %s", (s["ids"]["2098-02-17"],))
        conn.commit()
    s["add_adoption_item"]("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 3 – 24, 2098")

    flipped = sweep_adoptions(s["municipality_id"])

    assert s["ids"]["2098-02-03"] in flipped
    assert s["ids"]["2098-02-17"] not in flipped


def test_sweep_adoptions_rerun_does_not_warn_about_its_own_adoptions(
    batch_adoption_scenario, monkeypatch, caplog
):
    """The sweep re-reads every approval item daily. Finding the adoption it
    recorded yesterday is normal; only a conflicting adoption date is worth a warning."""
    monkeypatch.setattr("docket.analysis.vote_matcher.strict_reparse_meeting", _NO_REPARSE)
    s = batch_adoption_scenario
    s["add_adoption_item"]("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 3, 17 & 24, 2098")
    sweep_adoptions(s["municipality_id"])

    fixture_ids = {str(i) for i in s["ids"].values()}
    with caplog.at_level("WARNING", logger="docket.services.minutes_adoption"):
        sweep_adoptions(s["municipality_id"])

    ours = [
        r for r in caplog.records
        if "adoption_already_recorded" in r.getMessage()
        and any(f"target_meeting_id={i} " in r.getMessage() for i in fixture_ids)
    ]
    assert ours == []


def _insert_meeting(municipality_id, meeting_date, *, minutes=False, hidden=False) -> int:
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type,
                                         minutes_url, is_hidden)
                   VALUES (%s, 'TEST_BATCH_ADOPTION', %s, 'council', %s, %s) RETURNING id""",
                (municipality_id, meeting_date,
                 "https://example.test/minutes/extra" if minutes else None, hidden),
            )
            new_id = cur.fetchone()[0]
        conn.commit()
    return new_id


def test_sweep_adoptions_list_date_skips_hidden_meeting(batch_adoption_scenario, monkeypatch):
    monkeypatch.setattr("docket.analysis.vote_matcher.strict_reparse_meeting", _NO_REPARSE)
    s = batch_adoption_scenario
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE meetings SET is_hidden = TRUE WHERE id = %s", (s["ids"]["2098-02-17"],))
        conn.commit()
    s["add_adoption_item"]("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 3 and 17, 2098")

    flipped = sweep_adoptions(s["municipality_id"])

    assert s["ids"]["2098-02-03"] in flipped
    assert s["ids"]["2098-02-17"] not in flipped


def test_sweep_adoptions_list_date_adopts_every_row_with_minutes(batch_adoption_scenario, monkeypatch):
    """Real case: 2020-04-07 was held as Part I and Part II, each with its own
    minutes. A title naming the date adopts both, as a range would."""
    monkeypatch.setattr("docket.analysis.vote_matcher.strict_reparse_meeting", _NO_REPARSE)
    s = batch_adoption_scenario
    part_two = _insert_meeting(s["municipality_id"], "2098-02-17", minutes=True)
    s["ids"]["2098-02-17-part-two"] = part_two
    s["add_adoption_item"]("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 17, 2098")

    flipped = sweep_adoptions(s["municipality_id"])

    assert {s["ids"]["2098-02-17"], part_two} <= set(flipped)


def test_sweep_adoptions_earliest_adopting_meeting_wins(batch_adoption_scenario, monkeypatch):
    """If two agendas name the same date, the recorded adoption date must not
    depend on row order."""
    monkeypatch.setattr("docket.analysis.vote_matcher.strict_reparse_meeting", _NO_REPARSE)
    s = batch_adoption_scenario
    later = _insert_meeting(s["municipality_id"], "2098-03-17")
    s["ids"]["2098-03-17"] = later
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions,
                                       confidence, needs_review)
                   VALUES (%s, 'minutes_text', 'passed', 5, 0, 0, 'high', FALSE)""",
                (later,),
            )
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title, is_consent) VALUES (%s, %s, FALSE)",
                (later, "APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 3, 2098"),
            )
        conn.commit()
    s["add_adoption_item"]("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 3, 2098")

    sweep_adoptions(s["municipality_id"])

    assert _adopted_dates(s["ids"])["2098-02-03"] == date(2098, 3, 10)


def test_sweep_adoptions_matches_votes_before_promoting(batch_adoption_scenario, monkeypatch):
    """A flipped meeting whose votes were ingested in the same run has no links
    yet. Re-parsing first would link the consent vote to the confirmed items only
    and the default fill would never happen, so the sweep goes through the
    matcher, which links and then promotes."""
    calls = []
    monkeypatch.setattr(
        "docket.analysis.vote_matcher.match_votes_for_meeting", lambda mid: calls.append(mid) or {}
    )
    s = batch_adoption_scenario
    s["add_adoption_item"]("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 17, 2098")

    sweep_adoptions(s["municipality_id"])

    assert s["ids"]["2098-02-17"] in calls
