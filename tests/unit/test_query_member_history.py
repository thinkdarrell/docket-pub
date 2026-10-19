"""Tests for member detail query helpers.

Covers cursor round-trip + pagination behavior of list_member_voting_history.
DB-touching tests use TEST_MH_ prefixed rows with idempotent fixture cleanup.
"""

from __future__ import annotations

from datetime import date

import pytest
import psycopg2.extras

from docket.db import db
from docket.services.query import (
    _encode_cursor,
    _decode_cursor,
    list_member_voting_history,
    get_member_stats,
    count_sponsored_items_for_member,
)


def _cleanup() -> None:
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE title LIKE 'TEST_MH_%'")
            cur.execute("DELETE FROM council_members WHERE name LIKE 'TEST_MH_%'")
        conn.commit()


def test_cursor_round_trip():
    raw = _encode_cursor(date(2026, 5, 15), 42)
    decoded = _decode_cursor(raw)
    assert decoded == (date(2026, 5, 15), 42)


def test_cursor_malformed_returns_none():
    assert _decode_cursor("not-base64-not-valid!") is None
    assert _decode_cursor("") is None


@pytest.fixture
def member_with_history():
    """Create 1 member, 3 meetings, 3 votes — one yea/passed, one nay/failed,
    one absent. Lets us assert attendance, alignment, and dissent filtering."""
    _cleanup()
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM municipalities ORDER BY id LIMIT 1")
            muni_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO council_members (municipality_id, name, active)
                   VALUES (%s, 'TEST_MH_Pat', TRUE) RETURNING id""",
                (muni_id,),
            )
            mid = cur.fetchone()["id"]

            ids = []
            for label, mdate, result, pos in [
                ("A", "2099-01-01", "passed", "yea"),    # aligned
                ("B", "2099-02-01", "failed", "yea"),    # NOT aligned (dissent)
                ("C", "2099-03-01", "passed", "absent"), # absent
            ]:
                cur.execute(
                    """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                       VALUES (%s, %s, %s, 'council') RETURNING id""",
                    (muni_id, f"TEST_MH_{label}", mdate),
                )
                meeting_id = cur.fetchone()["id"]
                cur.execute(
                    """INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions,
                                           confidence, needs_review)
                       VALUES (%s, 'minutes_text', %s, 5, 0, 0, 'high', FALSE) RETURNING id""",
                    (meeting_id, result),
                )
                vote_id = cur.fetchone()["id"]
                cur.execute(
                    """INSERT INTO member_votes (vote_id, council_member_id, member_name, position)
                       VALUES (%s, %s, 'TEST_MH_Pat', %s)""",
                    (vote_id, mid, pos),
                )
                ids.append(vote_id)
        conn.commit()
    yield mid
    _cleanup()


def test_get_member_stats(member_with_history):
    stats = get_member_stats(member_with_history)
    assert stats["votes_total"] == 3
    # 2 of 3 not absent → 67% attendance
    assert stats["attendance_pct"] == round(100 * 2 / 3)
    # of 2 present, 1 aligned with majority → 50% alignment
    assert stats["alignment_pct"] == 50


def test_voting_history_orders_by_recent(member_with_history):
    page = list_member_voting_history(member_with_history, limit=10)
    assert len(page["rows"]) == 3
    # ORDER BY meeting_date DESC → C, B, A
    assert [r["meeting_title"] for r in page["rows"]] == ["TEST_MH_C", "TEST_MH_B", "TEST_MH_A"]
    assert page["next_cursor"] is None


def test_voting_history_dissent_filter(member_with_history):
    page = list_member_voting_history(member_with_history, limit=10, filter_mode="dissent")
    # Only B (yea on failed) is a dissent; A is aligned, C is absent
    assert [r["meeting_title"] for r in page["rows"]] == ["TEST_MH_B"]


def test_voting_history_pagination(member_with_history):
    page1 = list_member_voting_history(member_with_history, limit=2)
    assert len(page1["rows"]) == 2
    assert page1["next_cursor"] is not None
    assert [r["meeting_title"] for r in page1["rows"]] == ["TEST_MH_C", "TEST_MH_B"]

    page2 = list_member_voting_history(
        member_with_history, limit=2, cursor=page1["next_cursor"]
    )
    assert [r["meeting_title"] for r in page2["rows"]] == ["TEST_MH_A"]
    assert page2["next_cursor"] is None


def test_count_sponsored_items_empty_for_unknown_name():
    assert count_sponsored_items_for_member("Definitely-Not-A-Real-Sponsor-XYZ") == 0


def test_count_sponsored_items_handles_empty_name():
    assert count_sponsored_items_for_member("") == 0


@pytest.fixture
def member_with_two_sources():
    """One member, three meetings, with votes from more than one source.

    A (2099-01-01): a minutes vote, failed, yea — a dissent.
    B (2099-02-01): a minutes vote, passed, yea (aligned) and a video vote,
      failed, yea (a dissent the source rule hides, since the minutes win).
    C (2099-03-01): a video vote, failed, yea (a dissent the rule keeps: no
      minutes vote on the meeting) and a review-flagged minutes vote, failed,
      yea (excluded, and it does not make the minutes the chosen source).
    """
    _cleanup()
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM municipalities ORDER BY id LIMIT 1")
            muni_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO council_members (municipality_id, name, active)
                   VALUES (%s, 'TEST_MH_Sam', TRUE) RETURNING id""",
                (muni_id,),
            )
            mid = cur.fetchone()["id"]
            meetings = {}
            for label, mdate in (("A", "2099-01-01"), ("B", "2099-02-01"), ("C", "2099-03-01")):
                cur.execute(
                    """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                       VALUES (%s, %s, %s, 'council') RETURNING id""",
                    (muni_id, f"TEST_MH_{label}", mdate),
                )
                meetings[label] = cur.fetchone()["id"]
            for label, source, result, review in (
                ("A", "minutes_text", "failed", False),
                ("B", "minutes_text", "passed", False),
                ("B", "video_ocr", "failed", False),
                ("C", "video_ocr", "failed", False),
                ("C", "minutes_text", "failed", True),
            ):
                cur.execute(
                    """INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions,
                                           confidence, needs_review)
                       VALUES (%s, %s, %s, 5, 0, 0, 'high', %s) RETURNING id""",
                    (meetings[label], source, result, review),
                )
                vote_id = cur.fetchone()["id"]
                cur.execute(
                    """INSERT INTO member_votes (vote_id, council_member_id, member_name, position)
                       VALUES (%s, %s, 'TEST_MH_Sam', 'yea')""",
                    (vote_id, mid),
                )
        conn.commit()
    yield mid
    _cleanup()


def test_voting_history_since_filters_and_applies_source_rule(member_with_two_sources):
    mid = member_with_two_sources
    # Without ``since``: every vote, as the page always behaved (four dissents).
    page = list_member_voting_history(mid, limit=10, filter_mode="dissent")
    assert len(page["rows"]) == 4
    # With ``since``: the date filter drops A; the source rule keeps only B's
    # minutes vote (aligned, so not a dissent) and C's video vote, and drops
    # the review-flagged vote.
    page = list_member_voting_history(mid, limit=10, filter_mode="dissent", since=date(2099, 1, 15))
    assert [(r["meeting_title"], r["source"]) for r in page["rows"]] == [("TEST_MH_C", "video_ocr")]
    page = list_member_voting_history(mid, limit=10, since=date(2099, 1, 15))
    assert [(r["meeting_title"], r["source"]) for r in page["rows"]] == [
        ("TEST_MH_C", "video_ocr"), ("TEST_MH_B", "minutes_text"),
    ]
    # A ``since`` before every meeting keeps the date filter out of the way
    # and still applies the rule: A, B's minutes vote, C's video vote.
    page = list_member_voting_history(mid, limit=10, since=date(2098, 1, 1))
    assert [r["meeting_title"] for r in page["rows"]] == ["TEST_MH_C", "TEST_MH_B", "TEST_MH_A"]
    assert page["next_cursor"] is None


def test_voting_history_since_dissent_excludes_abstentions_and_tabled(member_with_two_sources):
    """The dated Dissent filter is ``AGAINST_OUTCOME_PREDICATE``: a yea on a
    tabled motion and an abstention are not votes against an outcome. The
    undated filter keeps its older definition (``D58``)."""
    mid = member_with_two_sources
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT municipality_id FROM meetings WHERE title = 'TEST_MH_A'")
            muni_id = cur.fetchone()["municipality_id"]
            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   VALUES (%s, 'TEST_MH_D', '2099-04-01', 'council') RETURNING id""",
                (muni_id,),
            )
            d = cur.fetchone()["id"]
            for result, yeas, nays, abstentions, position in (
                ("tabled", 5, 0, 0, "yea"),
                ("passed", 4, 0, 1, "abstain"),
            ):
                cur.execute(
                    """INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions,
                                           confidence, needs_review)
                       VALUES (%s, 'minutes_text', %s, %s, %s, %s, 'high', FALSE) RETURNING id""",
                    (d, result, yeas, nays, abstentions),
                )
                vote_id = cur.fetchone()["id"]
                cur.execute(
                    """INSERT INTO member_votes (vote_id, council_member_id, member_name, position)
                       VALUES (%s, %s, 'TEST_MH_Sam', %s)""",
                    (vote_id, mid, position),
                )
        conn.commit()
    # Dated and filtered: D's two votes are not against any outcome, so the rows are as before.
    page = list_member_voting_history(mid, limit=10, filter_mode="dissent", since=date(2099, 1, 15))
    assert [(r["meeting_title"], r["source"]) for r in page["rows"]] == [("TEST_MH_C", "video_ocr")]
    # Dated and unfiltered: D's two votes are in the history (they are roll calls attended).
    page = list_member_voting_history(mid, limit=10, since=date(2099, 1, 15))
    assert [r["meeting_title"] for r in page["rows"]] == ["TEST_MH_D", "TEST_MH_D", "TEST_MH_C", "TEST_MH_B"]
    # Undated Dissent: the older filter lists both of D's votes as dissent (D58).
    page = list_member_voting_history(mid, limit=10, filter_mode="dissent")
    assert len(page["rows"]) == 6
