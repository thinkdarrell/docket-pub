"""Shared pytest fixtures for integration tests.

No global transaction rollback — tests that insert rows own their cleanup.
This mirrors the pattern used throughout tests/integration/ (e.g. _Bag.cleanup()
in test_admin_hide_meeting.py).  Fixtures that insert rows are responsible for
cleaning up after themselves via try/finally.
"""

import pytest
from datetime import date, timedelta

from docket.db import db_cursor
from docket.analysis.ocr.rosters import build_roster_for_meeting


# ---------------------------------------------------------------------------
# Municipality + meeting helper
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded_birmingham():
    """Birmingham is already seeded by migration 002. Return its id."""
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
        row = cur.fetchone()
        if row is None:
            pytest.fail("Birmingham municipality not seeded — run migrations first.")
        return row["id"]


def _insert_meeting(muni_id: int, *, meeting_date, external_id: str = "9999",
                    title: str = "Test Meeting", is_hidden: bool = False) -> int:
    """Insert one meeting + processing_status row, return meeting id."""
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, title, meeting_date,
                                     external_id, is_hidden)
                 VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            [muni_id, title, meeting_date, external_id, is_hidden],
        )
        meeting_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO processing_status (meeting_id) VALUES (%s)",
            [meeting_id],
        )
        return meeting_id


@pytest.fixture
def seeded_bham_meeting_2024(seeded_birmingham):
    meeting_id = _insert_meeting(seeded_birmingham, meeting_date="2024-06-01",
                                 external_id="test-roster-2024")
    try:
        yield meeting_id
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = %s", [meeting_id])


@pytest.fixture
def seeded_bham_meeting_2026(seeded_birmingham):
    meeting_id = _insert_meeting(seeded_birmingham, meeting_date="2026-05-19",
                                 external_id="test-roster-2026")
    try:
        yield meeting_id
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = %s", [meeting_id])


@pytest.fixture
def seeded_term_end_boundary(seeded_birmingham):
    """Outgoing member's term_end == incoming member's term_start == meeting date.
    The half-open predicate must include incoming, exclude outgoing.

    Returns (outgoing_id, incoming_id, meeting_id).
    """
    boundary = date(2025, 10, 28)
    member_ids = []
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO council_members (municipality_id, name, term_start, term_end, active)
                 VALUES (%s, 'Outgoing Test', '2020-01-01', %s, FALSE) RETURNING id""",
            [seeded_birmingham, boundary],
        )
        outgoing_id = cur.fetchone()["id"]
        member_ids.append(outgoing_id)
        cur.execute(
            """INSERT INTO council_members (municipality_id, name, term_start, term_end, active)
                 VALUES (%s, 'Incoming Test', %s, NULL, TRUE) RETURNING id""",
            [seeded_birmingham, boundary],
        )
        incoming_id = cur.fetchone()["id"]
        member_ids.append(incoming_id)
    meeting_id = _insert_meeting(seeded_birmingham, meeting_date=boundary,
                                 external_id="test-roster-boundary")
    try:
        yield outgoing_id, incoming_id, meeting_id
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = %s", [meeting_id])
            cur.execute("DELETE FROM council_members WHERE id = ANY(%s)", [member_ids])


@pytest.fixture
def seeded_duplicate_surname(seeded_birmingham):
    """Two members sharing 'Smitherman' on the same date."""
    md = date(2024, 6, 1)
    member_ids = []
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO council_members (municipality_id, name, term_start, active)
                 VALUES (%s, 'Carole Smitherman', '2020-01-01', TRUE)
                 RETURNING id""",
            [seeded_birmingham],
        )
        member_ids.append(cur.fetchone()["id"])
        cur.execute(
            """INSERT INTO council_members (municipality_id, name, term_start, active)
                 VALUES (%s, 'Brian Smitherman', '2020-01-01', TRUE)
                 RETURNING id""",
            [seeded_birmingham],
        )
        member_ids.append(cur.fetchone()["id"])
    meeting_id = _insert_meeting(seeded_birmingham, meeting_date=md, external_id="test-roster-dupe-surname")

    class _NS:
        pass

    ns = _NS()
    ns.meeting_id = meeting_id
    try:
        yield ns
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = %s", [meeting_id])
            cur.execute("DELETE FROM council_members WHERE id = ANY(%s)", [member_ids])


@pytest.fixture
def seeded_empty_meeting(seeded_birmingham):
    """Meeting in a year with no active council_members."""
    meeting_id = _insert_meeting(seeded_birmingham, meeting_date="1990-01-01",
                                 external_id="test-roster-empty")
    try:
        yield meeting_id
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = %s", [meeting_id])


@pytest.fixture
def bham_roster_2026(seeded_bham_meeting_2026):
    return build_roster_for_meeting(seeded_bham_meeting_2026)


# ---------------------------------------------------------------------------
# OCR claim test helpers
# ---------------------------------------------------------------------------

# Numeric external_ids well above the highest real BHM clip_id (~2000).
# Using the 99900-series as a reserved test namespace so they pass the
# CTE's '^[0-9]+$' regex without colliding with production data.
_OCR_TEST_EXT_PENDING_1 = "99901"
_OCR_TEST_EXT_PENDING_2A = "99902"
_OCR_TEST_EXT_PENDING_2B = "99903"


def _park_preexisting_claimable_meetings(cursor) -> list[int]:
    """Temporarily mark all pre-existing BHM meetings as attempts=3 so they
    can't be claimed during the test.  Returns list of (meeting_id, original
    attempts) pairs for restoration."""
    cursor.execute(
        """
        SELECT ps.meeting_id, ps.video_ocr_attempts
          FROM processing_status ps
          JOIN meetings m        ON m.id  = ps.meeting_id
          JOIN municipalities mu ON mu.id = m.municipality_id
         WHERE mu.slug = 'birmingham'
           AND m.external_id ~ '^[0-9]+$'
           AND m.is_hidden = FALSE
           AND m.meeting_date >= now() - interval '60 days'
           AND ps.video_ocr_scanned = FALSE
           AND ps.video_ocr_attempts < 3
           AND (
                ps.video_ocr_last_attempted_at IS NULL
                OR ps.video_ocr_last_attempted_at < now() - interval '24 hours'
           )
        """
    )
    rows = cursor.fetchall()
    if rows:
        ids = [r["meeting_id"] for r in rows]
        cursor.execute(
            "UPDATE processing_status SET video_ocr_attempts = 3 WHERE meeting_id = ANY(%s)",
            [ids],
        )
    return [(r["meeting_id"], r["video_ocr_attempts"]) for r in rows]


def _restore_parked_meetings(cursor, parked: list[tuple[int, int]]) -> None:
    """Undo the parking: restore original attempts values."""
    for meeting_id, original_attempts in parked:
        cursor.execute(
            "UPDATE processing_status SET video_ocr_attempts = %s WHERE meeting_id = %s",
            [original_attempts, meeting_id],
        )


@pytest.fixture
def seeded_one_ocr_pending(seeded_birmingham):
    """Single claimable BHM meeting (numeric ext_id; pre-existing parked)."""
    parked: list[tuple[int, int]] = []
    with db_cursor() as cur:
        parked = _park_preexisting_claimable_meetings(cur)
    meeting_id = _insert_meeting(seeded_birmingham,
                                 meeting_date=date.today() - timedelta(days=2),
                                 external_id=_OCR_TEST_EXT_PENDING_1)
    try:
        yield meeting_id
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = %s", [meeting_id])
            _restore_parked_meetings(cur, parked)


@pytest.fixture
def seeded_two_ocr_pending(seeded_birmingham):
    """Two claimable BHM meetings (numeric ext_ids; pre-existing parked)."""
    parked: list[tuple[int, int]] = []
    with db_cursor() as cur:
        parked = _park_preexisting_claimable_meetings(cur)
    m1 = _insert_meeting(seeded_birmingham,
                         meeting_date=date.today() - timedelta(days=3),
                         external_id=_OCR_TEST_EXT_PENDING_2A)
    m2 = _insert_meeting(seeded_birmingham,
                         meeting_date=date.today() - timedelta(days=2),
                         external_id=_OCR_TEST_EXT_PENDING_2B)
    try:
        yield m1, m2
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", [[m1, m2]])
            _restore_parked_meetings(cur, parked)


@pytest.fixture
def seeded_one_ocr_pending_hidden(seeded_birmingham):
    """Hidden BHM meeting (numeric ext_id; pre-existing parked so None is
    guaranteed to mean 'hidden filter works', not 'no real meetings left')."""
    parked: list[tuple[int, int]] = []
    with db_cursor() as cur:
        parked = _park_preexisting_claimable_meetings(cur)
    meeting_id = _insert_meeting(seeded_birmingham,
                                 meeting_date=date.today() - timedelta(days=1),
                                 external_id="99910",
                                 is_hidden=True)
    try:
        yield meeting_id
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = %s", [meeting_id])
            _restore_parked_meetings(cur, parked)


@pytest.fixture
def seeded_one_ocr_pending_old(seeded_birmingham):
    """BHM meeting 61 days old (numeric ext_id; pre-existing parked)."""
    parked: list[tuple[int, int]] = []
    with db_cursor() as cur:
        parked = _park_preexisting_claimable_meetings(cur)
    meeting_id = _insert_meeting(seeded_birmingham,
                                 meeting_date=date.today() - timedelta(days=61),
                                 external_id="99911")
    try:
        yield meeting_id
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = %s", [meeting_id])
            _restore_parked_meetings(cur, parked)


@pytest.fixture
def seeded_one_ocr_pending_event_id(seeded_birmingham):
    """BHM meeting with event-N external_id (pre-existing parked)."""
    parked: list[tuple[int, int]] = []
    with db_cursor() as cur:
        parked = _park_preexisting_claimable_meetings(cur)
    meeting_id = _insert_meeting(seeded_birmingham,
                                 meeting_date=date.today() - timedelta(days=1),
                                 external_id="event-12345")
    try:
        yield meeting_id
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = %s", [meeting_id])
            _restore_parked_meetings(cur, parked)


@pytest.fixture
def seeded_meeting_with_mixed_votes(seeded_bham_meeting_2026):
    """Meeting carrying one video_ocr vote (+ member_votes row) and one
    minutes_text vote."""
    vote_ids = []
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO votes
                 (meeting_id, video_timestamp, result, yeas, nays, abstentions,
                  raw_text, confidence, source)
                 VALUES (%s, 100.0, 'passed', 8, 0, 0, 'OCR vote', 'high', 'video_ocr')
                 RETURNING id""",
            [seeded_bham_meeting_2026],
        )
        ocr_vote_id = cur.fetchone()["id"]
        vote_ids.append(ocr_vote_id)
        cur.execute(
            """INSERT INTO member_votes (vote_id, council_member_id, member_name, position)
                 VALUES (%s, NULL, 'C. Smitherman', 'yea')""",
            [ocr_vote_id],
        )
        cur.execute(
            """INSERT INTO votes
                 (meeting_id, result, yeas, nays, abstentions, raw_text, confidence, source)
                 VALUES (%s, 'passed', 8, 0, 0, 'Minutes vote', 'high', 'minutes_text')
                 RETURNING id""",
            [seeded_bham_meeting_2026],
        )
        vote_ids.append(cur.fetchone()["id"])
    try:
        yield seeded_bham_meeting_2026
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM votes WHERE id = ANY(%s)", [vote_ids])


@pytest.fixture
def client():
    from docket.web import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def authed_admin_client(client):
    """Flask test client with admin_user session key set."""
    with client.session_transaction() as sess:
        sess["admin_user"] = "test-admin"
    return client
