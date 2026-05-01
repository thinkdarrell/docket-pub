"""Tests for query.list_votes — N:M join-table read path."""

import pytest
import psycopg2.extras

from docket.db import db
from docket.services.query import list_votes


@pytest.fixture
def vote_with_two_links():
    """A meeting with one vote linked to two is_consent agenda items.

    Idempotent: deletes any prior TEST_QUERY rows on entry; ON DELETE CASCADE
    handles teardown via the meetings → votes/agenda_items chain.
    """
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM meetings WHERE title = 'TEST_QUERY' AND meeting_date = '2099-01-03'"
            )
        conn.commit()

    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM municipalities ORDER BY id LIMIT 1")
            muni_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   VALUES (%s, 'TEST_QUERY', '2099-01-03', 'council') RETURNING id""",
                (muni_id,),
            )
            mid = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO agenda_items (meeting_id, title, item_number, is_consent)
                   VALUES (%s, 'Item A', '1', TRUE), (%s, 'Item B', '2', TRUE)
                   RETURNING id""",
                (mid, mid),
            )
            ai_ids = [r["id"] for r in cur.fetchall()]
            cur.execute(
                """INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions,
                                       confidence, needs_review)
                   VALUES (%s, 'minutes_text', 'passed', 5, 0, 0, 'high', FALSE) RETURNING id""",
                (mid,),
            )
            vid = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO vote_agenda_items
                    (vote_id, agenda_item_id, association_type, match_method,
                     match_confidence, excerpt_context, provisional)
                   VALUES
                    (%s, %s, 'consent_named', 'consent_block_named', 1.0, 'snip A', TRUE),
                    (%s, %s, 'consent_implicit', 'consent_block_default', 0.8, NULL, TRUE)""",
                (vid, ai_ids[0], vid, ai_ids[1]),
            )
        conn.commit()
    yield {"meeting_id": mid, "vote_id": vid, "agenda_item_ids": ai_ids}
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = %s", (mid,))
        conn.commit()


def test_list_votes_returns_vote_with_agenda_links(vote_with_two_links):
    votes = list_votes(vote_with_two_links["meeting_id"])
    assert len(votes) == 1
    vote = votes[0]
    assert len(vote.agenda_links) == 2
    assert vote.is_consent_block is True
    assert vote.has_provisional_links is True


def test_list_votes_excludes_excerpt_by_default(vote_with_two_links):
    votes = list_votes(vote_with_two_links["meeting_id"])
    for link in votes[0].agenda_links:
        assert link.excerpt_context is None


def test_list_votes_includes_excerpt_when_requested(vote_with_two_links):
    votes = list_votes(vote_with_two_links["meeting_id"], include_excerpts=True)
    excerpts = [link.excerpt_context for link in votes[0].agenda_links]
    assert "snip A" in excerpts
    assert None in excerpts  # the consent_implicit link has NULL excerpt


def test_list_votes_returns_empty_for_meeting_without_votes():
    """Edge case: meeting exists but has no votes."""
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("DELETE FROM meetings WHERE title = 'TEST_QUERY_EMPTY' AND meeting_date = '2099-01-04'")
            cur.execute("SELECT id FROM municipalities ORDER BY id LIMIT 1")
            muni_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   VALUES (%s, 'TEST_QUERY_EMPTY', '2099-01-04', 'council') RETURNING id""",
                (muni_id,),
            )
            mid = cur.fetchone()["id"]
        conn.commit()
    try:
        votes = list_votes(mid)
        assert votes == []
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM meetings WHERE id = %s", (mid,))
            conn.commit()
