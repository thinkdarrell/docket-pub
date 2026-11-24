"""docket.services.video_ocr.reset_for_rescan: the force-rescan of one meeting.

``reset_for_rescan`` holds the five statements the route
``POST /admin/meetings/<id>/rescan-ocr`` executed itself before plan
`admin-routes-call-services`, M4, in one transaction: the city slug, a count
of the meeting's ``video_ocr`` votes, the deletion of their member votes and
of the votes, and the reset of four ``processing_status`` columns.

One city is seeded whose slug begins ``ocrreset_test_``; the autouse fixture
deletes its meetings (votes, member votes and ``processing_status`` rows go
with them) and the city before and after every test. The service name is
imported inside the test, so the file collects before the function exists.
Runs in the services tier (DATABASE_URL names docket_test_*).
"""

from __future__ import annotations

import pytest

from docket.db import db_cursor

PREFIX = "ocrreset_test_"
SLUG = PREFIX + "city"
NO_SUCH_ID = 999999999

_FLAGS = "video_ocr_scanned, video_ocr_attempts, video_ocr_last_attempted_at, video_ocr_last_error, votes_scanned"


def _delete_seeded() -> None:
    like = (PREFIX + "%",)
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM meetings WHERE municipality_id IN "
            "(SELECT id FROM municipalities WHERE slug LIKE %s)",
            like,
        )
        cur.execute("DELETE FROM municipalities WHERE slug LIKE %s", like)


@pytest.fixture(autouse=True)
def _clean():
    _delete_seeded()
    yield
    _delete_seeded()


@pytest.fixture
def city() -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO municipalities (slug, name, adapter_class, adapter_config, active)
               VALUES (%s, 'Ocrreset Test City', 'GranicusAdapter', '{}', TRUE) RETURNING id""",
            (SLUG,),
        )
        return cur.fetchone()["id"]


def _meeting(city_id: int) -> int:
    """A meeting whose OCR pass has run, failed three times and left an error."""
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, title, meeting_date)
               VALUES (%s, 'Ocrreset test meeting', '2026-04-15') RETURNING id""",
            (city_id,),
        )
        meeting_id = cur.fetchone()["id"]
        cur.execute(
            """INSERT INTO processing_status
                 (meeting_id, votes_scanned, video_ocr_scanned, video_ocr_attempts,
                  video_ocr_last_attempted_at, video_ocr_last_error)
               VALUES (%s, TRUE, TRUE, 3, NOW(), 'ocrreset test error')""",
            (meeting_id,),
        )
        return meeting_id


def _vote(meeting_id: int, source: str, at: float | None, members: int = 2) -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO votes (meeting_id, video_timestamp, result, yeas, nays, abstentions,
                                  raw_text, confidence, source)
               VALUES (%s, %s, 'passed', 8, 0, 0, 'Ocrreset test vote', 'high', %s) RETURNING id""",
            (meeting_id, at, source),
        )
        vote_id = cur.fetchone()["id"]
        for n in range(members):
            cur.execute(
                """INSERT INTO member_votes (vote_id, council_member_id, member_name, position)
                   VALUES (%s, NULL, %s, 'yea')""",
                (vote_id, f"Ocrreset member {n}"),
            )
        return vote_id


def _votes(meeting_id: int) -> list[tuple[int, str, int]]:
    """(vote id, source, member votes under it) for every vote of the meeting, by id."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT v.id, v.source,
                      (SELECT COUNT(*) FROM member_votes mv WHERE mv.vote_id = v.id) AS members
                 FROM votes v WHERE v.meeting_id = %s ORDER BY v.id""",
            (meeting_id,),
        )
        return [(r["id"], r["source"], r["members"]) for r in cur.fetchall()]


def _flags(meeting_id: int) -> dict:
    with db_cursor() as cur:
        cur.execute(f"SELECT {_FLAGS} FROM processing_status WHERE meeting_id = %s", (meeting_id,))
        return dict(cur.fetchone())


RESET = {
    "video_ocr_scanned": False,
    "video_ocr_attempts": 0,
    "video_ocr_last_attempted_at": None,
    "video_ocr_last_error": None,
    "votes_scanned": True,  # not one of the four: the statement leaves it
}


def test_reset_for_rescan_returns_the_city_slug_and_the_number_of_video_ocr_votes(city):
    from docket.services.video_ocr import reset_for_rescan

    meeting_id = _meeting(city)
    _vote(meeting_id, "video_ocr", 100.0)
    _vote(meeting_id, "video_ocr", 200.0)
    _vote(meeting_id, "minutes_text", None)

    assert reset_for_rescan(meeting_id) == (SLUG, 2)


def test_reset_for_rescan_deletes_the_video_ocr_votes_and_leaves_a_vote_of_another_source(city):
    from docket.services.video_ocr import reset_for_rescan

    meeting_id = _meeting(city)
    _vote(meeting_id, "video_ocr", 100.0)
    _vote(meeting_id, "video_ocr", 200.0)
    kept = _vote(meeting_id, "minutes_text", None, members=3)

    reset_for_rescan(meeting_id)

    assert _votes(meeting_id) == [(kept, "minutes_text", 3)]


def test_reset_for_rescan_leaves_no_member_vote_of_a_deleted_vote(city):
    from docket.services.video_ocr import reset_for_rescan

    meeting_id = _meeting(city)
    gone = [_vote(meeting_id, "video_ocr", 100.0), _vote(meeting_id, "video_ocr", 200.0)]

    reset_for_rescan(meeting_id)

    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM member_votes WHERE vote_id = ANY(%s)", (gone,))
        assert cur.fetchone()["n"] == 0


def test_reset_for_rescan_resets_the_four_columns_and_no_other(city):
    from docket.services.video_ocr import reset_for_rescan

    meeting_id = _meeting(city)
    _vote(meeting_id, "video_ocr", 100.0)
    assert _flags(meeting_id)["video_ocr_scanned"] is True

    reset_for_rescan(meeting_id)

    assert _flags(meeting_id) == RESET


def test_reset_for_rescan_with_no_video_ocr_vote_returns_zero_and_still_resets(city):
    from docket.services.video_ocr import reset_for_rescan

    meeting_id = _meeting(city)
    kept = _vote(meeting_id, "minutes_text", None)

    assert reset_for_rescan(meeting_id) == (SLUG, 0)

    assert _votes(meeting_id) == [(kept, "minutes_text", 2)]
    assert _flags(meeting_id) == RESET


def test_reset_for_rescan_touches_that_meeting_only(city):
    from docket.services.video_ocr import reset_for_rescan

    meeting_id = _meeting(city)
    _vote(meeting_id, "video_ocr", 100.0)
    other = _meeting(city)
    other_vote = _vote(other, "video_ocr", 100.0)
    other_flags = _flags(other)

    assert reset_for_rescan(meeting_id) == (SLUG, 1)

    assert _votes(other) == [(other_vote, "video_ocr", 2)]
    assert _flags(other) == other_flags
    assert other_flags["video_ocr_scanned"] is True


def test_reset_for_rescan_for_an_unknown_meeting_is_none_and_changes_nothing(city):
    from docket.services.video_ocr import reset_for_rescan

    seeded = _meeting(city)
    vote_id = _vote(seeded, "video_ocr", 100.0)
    flags = _flags(seeded)

    assert reset_for_rescan(NO_SUCH_ID) is None

    assert _votes(seeded) == [(vote_id, "video_ocr", 2)]
    assert _flags(seeded) == flags
