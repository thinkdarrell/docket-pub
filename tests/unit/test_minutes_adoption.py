"""Tests for adoption-pattern detection."""

from datetime import date

import psycopg2.extras
import pytest

from docket.db import db, db_cursor
from docket.services.minutes_adoption import (
    AdoptionParseError,
    extract_adoption_target,
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


def test_extract_adoption_target_returns_date():
    target = extract_adoption_target(
        "Approval of Minutes from December 5, 2024",
        adoption_meeting_date=date(2026, 1, 7),
    )
    assert target == date(2024, 12, 5)


def test_extract_adoption_target_rejects_invalid_date():
    """Feb 31 is not a real date."""
    with pytest.raises(AdoptionParseError, match="invalid date"):
        extract_adoption_target(
            "Approval of Minutes from February 31, 2024",
            adoption_meeting_date=date(2026, 1, 7),
        )


def test_extract_adoption_target_rejects_future_date():
    with pytest.raises(AdoptionParseError, match="future"):
        extract_adoption_target(
            "Approval of Minutes from January 1, 2030",
            adoption_meeting_date=date(2026, 1, 7),
        )


def test_extract_adoption_target_rejects_too_old():
    """24-month window."""
    with pytest.raises(AdoptionParseError, match="window"):
        extract_adoption_target(
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
