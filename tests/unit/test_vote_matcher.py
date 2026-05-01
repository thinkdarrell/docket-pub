"""Tests for the new vote matcher pipeline."""

import pytest
import psycopg2.extras

from docket.db import db
from docket.analysis.vote_matcher import _classify_vote, _upsert_link


@pytest.fixture
def sample_vote_and_item():
    """Create a vote and agenda item, yield their IDs, clean up after.

    Performs an idempotent sweep of TEST_FIXTURE rows on entry so a previously
    failed run cannot leave stale data in the dev DB. ON DELETE CASCADE on the
    meetings → votes/agenda_items chain handles transitive cleanup.
    """
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM meetings WHERE title = 'TEST_FIXTURE' AND meeting_date = '2099-01-01'"
            )
        conn.commit()

    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   SELECT id, 'TEST_FIXTURE', '2099-01-01', 'council'
                   FROM municipalities ORDER BY id LIMIT 1
                   RETURNING id""",
            )
            mid = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO agenda_items (meeting_id, title, item_number, is_consent)
                   VALUES (%s, 'Test Resolution', '1', FALSE) RETURNING id""",
                (mid,),
            )
            aid = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions,
                                       confidence, needs_review)
                   VALUES (%s, 'minutes_text', 'passed', 5, 0, 0, 'high', FALSE)
                   RETURNING id""",
                (mid,),
            )
            vid = cur.fetchone()["id"]
        conn.commit()

    yield {"vote_id": vid, "agenda_item_id": aid, "meeting_id": mid}

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vote_agenda_items WHERE vote_id = %s", (vid,))
            cur.execute("DELETE FROM member_votes WHERE vote_id = %s", (vid,))
            cur.execute("DELETE FROM votes WHERE id = %s", (vid,))
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (aid,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mid,))
        conn.commit()


def test_upsert_link_inserts_when_absent(sample_vote_and_item):
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            _upsert_link(
                cur,
                vote_id=sample_vote_and_item["vote_id"],
                agenda_item_id=sample_vote_and_item["agenda_item_id"],
                association_type="explicit",
                match_method="resolution_number",
                match_confidence=0.9,
                excerpt_context="snippet",
                provisional=False,
            )
            cur.execute(
                "SELECT * FROM vote_agenda_items WHERE vote_id = %s",
                (sample_vote_and_item["vote_id"],),
            )
            row = cur.fetchone()
        conn.commit()
    assert row["association_type"] == "explicit"
    assert row["match_method"] == "resolution_number"
    assert row["match_confidence"] == pytest.approx(0.9)
    assert row["provisional"] is False


def test_upsert_link_updates_on_conflict(sample_vote_and_item):
    """Re-running with different values updates the existing row, doesn't insert a duplicate."""
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            _upsert_link(cur, vote_id=sample_vote_and_item["vote_id"],
                         agenda_item_id=sample_vote_and_item["agenda_item_id"],
                         association_type="explicit", match_method="resolution_number",
                         match_confidence=0.9, excerpt_context="A", provisional=False)
            _upsert_link(cur, vote_id=sample_vote_and_item["vote_id"],
                         agenda_item_id=sample_vote_and_item["agenda_item_id"],
                         association_type="explicit", match_method="text_similarity",
                         match_confidence=0.6, excerpt_context="B", provisional=False)
            cur.execute(
                "SELECT match_method, match_confidence, excerpt_context FROM vote_agenda_items WHERE vote_id = %s",
                (sample_vote_and_item["vote_id"],),
            )
            row = cur.fetchone()
            cur.execute(
                "SELECT COUNT(*) AS c FROM vote_agenda_items WHERE vote_id = %s",
                (sample_vote_and_item["vote_id"],),
            )
            count = cur.fetchone()["c"]
        conn.commit()
    assert count == 1
    assert row["match_method"] == "text_similarity"
    assert row["match_confidence"] == pytest.approx(0.6)


def test_upsert_link_respects_manual_shield(sample_vote_and_item):
    """If is_manual=True, the upsert must not modify the row."""
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO vote_agenda_items
                    (vote_id, agenda_item_id, association_type, match_method,
                     match_confidence, provisional, is_manual, is_active)
                   VALUES (%s, %s, 'explicit', 'manual_correction', 1.0, FALSE, TRUE, TRUE)""",
                (sample_vote_and_item["vote_id"], sample_vote_and_item["agenda_item_id"]),
            )
            _upsert_link(cur, vote_id=sample_vote_and_item["vote_id"],
                         agenda_item_id=sample_vote_and_item["agenda_item_id"],
                         association_type="consent_implicit", match_method="consent_block_default",
                         match_confidence=0.8, excerpt_context=None, provisional=True)
            cur.execute(
                "SELECT match_method, match_confidence, is_manual FROM vote_agenda_items WHERE vote_id = %s",
                (sample_vote_and_item["vote_id"],),
            )
            row = cur.fetchone()
        conn.commit()
    assert row["is_manual"] is True
    assert row["match_method"] == "manual_correction"
    assert row["match_confidence"] == pytest.approx(1.0)


def test_upsert_link_db_shield_blocks_update_when_app_check_bypassed(sample_vote_and_item):
    """Belt-and-suspenders: if the app pre-check is ever skipped (race, refactor,
    direct caller), the DB-level WHERE on the UPDATE branch must still protect
    is_manual rows. Exercises the SQL directly to prove the WHERE clause works
    even without _upsert_link's pre-check.
    """
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO vote_agenda_items
                    (vote_id, agenda_item_id, association_type, match_method,
                     match_confidence, provisional, is_manual, is_active)
                   VALUES (%s, %s, 'explicit', 'manual_correction', 1.0, FALSE, TRUE, TRUE)""",
                (sample_vote_and_item["vote_id"], sample_vote_and_item["agenda_item_id"]),
            )
            cur.execute(
                """INSERT INTO vote_agenda_items
                    (vote_id, agenda_item_id, association_type, match_method,
                     match_confidence, excerpt_context, provisional)
                   VALUES (%s, %s, 'consent_implicit', 'consent_block_default',
                           0.8, NULL, TRUE)
                   ON CONFLICT (vote_id, agenda_item_id) DO UPDATE
                     SET association_type = EXCLUDED.association_type,
                         match_method = EXCLUDED.match_method,
                         match_confidence = EXCLUDED.match_confidence,
                         excerpt_context = EXCLUDED.excerpt_context,
                         updated_at = NOW()
                     WHERE vote_agenda_items.is_manual = FALSE""",
                (sample_vote_and_item["vote_id"], sample_vote_and_item["agenda_item_id"]),
            )
            cur.execute(
                "SELECT match_method, match_confidence FROM vote_agenda_items WHERE vote_id = %s",
                (sample_vote_and_item["vote_id"],),
            )
            row = cur.fetchone()
        conn.commit()
    assert row["match_method"] == "manual_correction"
    assert row["match_confidence"] == pytest.approx(1.0)


def test_classify_vote_substantive_when_no_phrase():
    vote = {"raw_text": "A standalone resolution. The resolution was read by the City Clerk.",
            "match_context": "A standalone resolution."}
    assert _classify_vote(vote) == "substantive"


def test_classify_vote_consent_when_phrase_in_raw_text():
    vote = {
        "raw_text": "...the resolutions and ordinances introduced as consent agenda matters were read by the City Clerk...",
        "match_context": "trailing only",
    }
    assert _classify_vote(vote) == "consent_block"


def test_classify_vote_consent_when_phrase_only_in_match_context():
    """Falls back to match_context for legacy votes with empty raw_text."""
    vote = {
        "raw_text": None,
        "match_context": "items on consent agenda matters were read by the City Clerk",
    }
    assert _classify_vote(vote) == "consent_block"


def test_classify_vote_substantive_when_both_empty():
    vote = {"raw_text": None, "match_context": None}
    assert _classify_vote(vote) == "substantive"


def test_match_substantive_inserts_explicit_link_with_resolution_match(sample_vote_and_item):
    """A substantive vote with a resolution number that appears in the agenda title
    should produce an 'explicit' link with method='resolution_number' and confidence=0.9."""
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Set up: agenda item title contains resolution 1854-25, vote has that resolution number
            cur.execute(
                "UPDATE agenda_items SET title = 'Resolution 1854-25 Test' WHERE id = %s",
                (sample_vote_and_item["agenda_item_id"],),
            )
            cur.execute(
                "UPDATE votes SET resolution_number = '1854-25', match_context = 'context' WHERE id = %s",
                (sample_vote_and_item["vote_id"],),
            )
        conn.commit()

    from docket.analysis.vote_matcher import match_votes_for_meeting
    match_votes_for_meeting(sample_vote_and_item["meeting_id"])

    from docket.db import db_cursor
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM vote_agenda_items WHERE vote_id = %s",
            (sample_vote_and_item["vote_id"],),
        )
        row = cur.fetchone()

    assert row is not None
    assert row["association_type"] == "explicit"
    assert row["match_method"] == "resolution_number"
    assert row["match_confidence"] == pytest.approx(0.9)
    assert row["provisional"] is False
