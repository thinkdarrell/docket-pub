"""Integration tests for member-vote resolution against the migration-seeded
Birmingham roster.

The throwaway database ``./tools/verify`` builds seeds twelve dated
Birmingham council members: the nine sitting members (``term_start``
2025-10-28, ``term_end`` NULL) and the three who left that day (Abbott,
Clarke, Moore; 2017-11-14 to 2025-10-28). The five continuing members have
no prior-term row, so ``Woods`` on a 2024 meeting stays unresolved; that is
the roster's gap (``docs/DEBT.md``), not the resolver's.

Tests that insert rows own their cleanup; the meeting fixtures delete the
meeting, and votes and member votes cascade.
"""

import logging
import os
from datetime import date
from unittest.mock import MagicMock

import pytest

from docket.db import db_cursor
from docket.models.protocol import RawMeeting, RawVote
from docket.services.ingest import _ingest_votes
from docket.services.member_votes import (
    load_roster_index,
    resolve_unresolved_member_votes,
)

pytestmark = pytest.mark.skipif(
    "railway.internal" in os.environ.get("DATABASE_URL", "")
    or "railway.app" in os.environ.get("DATABASE_URL", ""),
    reason="Resolution test mutates DB; must not run against Railway prod.",
)

OQUINN = "O’Quinn"  # the curly right quote the minutes print

# Stored surname -> full roster name, as migration 005 seeds the sitting council.
SITTING = {
    OQUINN: "Darrell O'Quinn",
    "Woods": "Clinton P. Woods",
    "Alexander": "Wardine T. Alexander",
    "Smitherman": "Crystal N. Smitherman",
    "Gunn": "Brian Gunn",
    "Tate": "LaTonya A. Tate",
    "Vasa": "Josh Vasa",
    "Williams": "Hunter Williams",
    "Smith": "Sonja Q. Smith",
}


def _ids_by_name(municipality_id: int) -> dict[str, int]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, name FROM council_members WHERE municipality_id = %s",
            [municipality_id],
        )
        return {row["name"]: row["id"] for row in cur.fetchall()}


def test_sitting_members_resolve_on_2026_meeting(seeded_birmingham):
    index = load_roster_index(seeded_birmingham)
    ids_by_name = _ids_by_name(seeded_birmingham)
    on = date(2026, 5, 19)
    for surname, full_name in SITTING.items():
        assert index.resolve(surname, on) == ids_by_name[full_name], surname
    assert index.resolve("Abbott", on) is None


def test_prior_term_members_resolve_on_2024_meeting(seeded_birmingham):
    index = load_roster_index(seeded_birmingham)
    ids_by_name = _ids_by_name(seeded_birmingham)
    on = date(2024, 6, 1)
    assert index.resolve("Abbott", on) == ids_by_name["Valerie A. Abbott"]
    assert index.resolve("Clarke", on) == ids_by_name["Lashunda Scales Clarke"]
    assert index.resolve("Moore", on) == ids_by_name["Darrell W. Moore"]
    assert index.resolve("Woods", on) is None


def test_transition_day_resolves_incoming_not_outgoing(seeded_birmingham):
    index = load_roster_index(seeded_birmingham)
    ids_by_name = _ids_by_name(seeded_birmingham)
    on = date(2025, 10, 28)
    assert index.resolve("Gunn", on) == ids_by_name["Brian Gunn"]
    assert index.resolve("Abbott", on) is None


def _raw_meeting_2026() -> RawMeeting:
    return RawMeeting(
        external_id="test-roster-2026",
        municipality_slug="birmingham",
        title="Test Meeting",
        meeting_date=date(2026, 5, 19),
        meeting_type="council",
        agenda_url=None,
        minutes_url="https://example.invalid/minutes.pdf",
        video_url=None,
        source_url="https://example.invalid/meeting",
    )


def test_ingest_votes_stores_member_ids(seeded_birmingham, seeded_bham_meeting_2026):
    adapter = MagicMock()
    adapter.fetch_votes.return_value = [
        RawVote(
            external_id="test-roster-2026-vote-1",
            meeting_external_id="test-roster-2026",
            agenda_item_external_id=None,
            result="passed",
            yeas=2,
            nays=0,
            abstentions=0,
            member_votes=[
                {"member": OQUINN, "vote": "yea"},
                {"member": "Woods", "vote": "yea"},
                {"member": "Georgia", "vote": "absent"},
            ],
            source="minutes_text",
        )
    ]

    assert _ingest_votes(seeded_birmingham, adapter, _raw_meeting_2026()) == 1

    ids_by_name = _ids_by_name(seeded_birmingham)
    with db_cursor() as cur:
        cur.execute(
            """SELECT mv.member_name, mv.council_member_id
                 FROM member_votes mv JOIN votes v ON v.id = mv.vote_id
                WHERE v.meeting_id = %s ORDER BY mv.id""",
            [seeded_bham_meeting_2026],
        )
        rows = {r["member_name"]: r["council_member_id"] for r in cur.fetchall()}
    assert rows == {
        OQUINN: ids_by_name["Darrell O'Quinn"],
        "Woods": ids_by_name["Clinton P. Woods"],
        "Georgia": None,
    }


def test_sweep_resolves_null_rows_and_keeps_noise(
    seeded_birmingham, seeded_bham_meeting_2026, caplog
):
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO votes (meeting_id, result, yeas, nays, abstentions,
                                  raw_text, confidence, source)
                 VALUES (%s, 'passed', 2, 0, 0, 'Minutes vote', 'high', 'minutes_text')
                 RETURNING id""",
            [seeded_bham_meeting_2026],
        )
        vote_id = cur.fetchone()["id"]
        for name, position in ((OQUINN, "yea"), ("Woods", "yea"), ("Georgia", "absent")):
            cur.execute(
                """INSERT INTO member_votes (vote_id, council_member_id, member_name, position)
                     VALUES (%s, NULL, %s, %s)""",
                [vote_id, name, position],
            )

    caplog.set_level(logging.INFO, logger="docket.services.member_votes")
    result = resolve_unresolved_member_votes()

    assert result.resolved == 2
    assert result.unresolved == 1
    assert result.unresolved_names == {"Georgia": 1}

    ids_by_name = _ids_by_name(seeded_birmingham)
    with db_cursor() as cur:
        cur.execute(
            "SELECT member_name, council_member_id FROM member_votes WHERE vote_id = %s",
            [vote_id],
        )
        rows = {r["member_name"]: r["council_member_id"] for r in cur.fetchall()}
    assert rows == {
        OQUINN: ids_by_name["Darrell O'Quinn"],
        "Woods": ids_by_name["Clinton P. Woods"],
        "Georgia": None,
    }
    assert any("unresolved name='Georgia'" in record.getMessage() for record in caplog.records)
