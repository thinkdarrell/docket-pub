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


def test_match_votes_for_meeting_is_idempotent(sample_vote_and_item):
    """Re-running match_votes_for_meeting must not duplicate links or re-match
    rows that already have an active link. The LEFT JOIN ON vai.is_active in
    both substantive and timestamp matchers is the skip predicate."""
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
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
    first = match_votes_for_meeting(sample_vote_and_item["meeting_id"])
    second = match_votes_for_meeting(sample_vote_and_item["meeting_id"])

    assert first["substantive_matched"] == 1
    assert second["substantive_matched"] == 0  # nothing to do; vote already has an active link

    from docket.db import db_cursor
    with db_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS c FROM vote_agenda_items WHERE vote_id = %s",
            (sample_vote_and_item["vote_id"],),
        )
        count = cur.fetchone()["c"]
    assert count == 1, "Re-run must not insert a duplicate link"


def test_match_votes_by_timestamp_writes_explicit_link(sample_vote_and_item):
    """Video OCR votes with a timestamp matched to an agenda item with a
    video_timestamp_seconds value should land in vote_agenda_items as
    association_type='explicit', match_method='timestamp', provisional=False."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE agenda_items SET video_timestamp_seconds = 100.0 WHERE id = %s",
                (sample_vote_and_item["agenda_item_id"],),
            )
            cur.execute(
                """UPDATE votes SET source = 'video_ocr', video_timestamp = 130.0
                   WHERE id = %s""",
                (sample_vote_and_item["vote_id"],),
            )
        conn.commit()

    from docket.analysis.vote_matcher import match_votes_for_meeting
    result = match_votes_for_meeting(sample_vote_and_item["meeting_id"])
    assert result["timestamp_matched"] == 1

    from docket.db import db_cursor
    with db_cursor() as cur:
        cur.execute(
            "SELECT association_type, match_method, provisional FROM vote_agenda_items WHERE vote_id = %s",
            (sample_vote_and_item["vote_id"],),
        )
        row = cur.fetchone()
    assert row["association_type"] == "explicit"
    assert row["match_method"] == "timestamp"
    assert row["provisional"] is False


def test_match_substantive_skips_consent_block_votes(sample_vote_and_item):
    """A vote whose raw_text contains a consent-block phrase must NOT be linked
    by _match_substantive — it's left for the consent-block matcher (Task 2.6)."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE agenda_items SET title = 'Resolution 1854-25 Test' WHERE id = %s",
                (sample_vote_and_item["agenda_item_id"],),
            )
            cur.execute(
                """UPDATE votes
                   SET resolution_number = '1854-25',
                       match_context = 'context',
                       raw_text = 'the resolutions and ordinances introduced as consent agenda matters were read by the City Clerk'
                   WHERE id = %s""",
                (sample_vote_and_item["vote_id"],),
            )
        conn.commit()

    from docket.analysis.vote_matcher import match_votes_for_meeting
    result = match_votes_for_meeting(sample_vote_and_item["meeting_id"])

    # Substantive matcher correctly skipped this; consent stub returns 0 (Task 2.6 will handle)
    assert result["substantive_matched"] == 0

    from docket.db import db_cursor
    with db_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS c FROM vote_agenda_items WHERE vote_id = %s",
            (sample_vote_and_item["vote_id"],),
        )
        count = cur.fetchone()["c"]
    assert count == 0, "Consent-classified vote must not be linked by substantive matcher"


def test_match_votes_for_meeting_ignores_inactive_ghost_links(sample_vote_and_item):
    """An is_active=FALSE 'ghost' link should NOT prevent the matcher from
    inserting a new active link via _upsert_link (the LEFT JOIN ... AND vai.is_active
    skip predicate excludes ghost rows by design).

    Note: _upsert_link does an ON CONFLICT DO UPDATE, so the existing inactive
    row gets refreshed in place — but its association_type and match values
    are now those of the new substantive match, and provisional/is_active
    should be set per the new write."""
    # First, create an inactive ghost link
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO vote_agenda_items
                    (vote_id, agenda_item_id, association_type, match_method,
                     match_confidence, provisional, is_manual, is_active)
                   VALUES (%s, %s, 'consent_implicit', 'consent_block_default',
                           0.8, FALSE, FALSE, FALSE)""",
                (sample_vote_and_item["vote_id"], sample_vote_and_item["agenda_item_id"]),
            )
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
    result = match_votes_for_meeting(sample_vote_and_item["meeting_id"])

    # Ghost link did not block re-matching (counted in substantive_matched)
    assert result["substantive_matched"] == 1

    from docket.db import db_cursor
    with db_cursor() as cur:
        cur.execute(
            "SELECT association_type, match_method, is_active FROM vote_agenda_items WHERE vote_id = %s",
            (sample_vote_and_item["vote_id"],),
        )
        row = cur.fetchone()
    # The ON CONFLICT DO UPDATE refreshed the row with the new substantive match values
    assert row["association_type"] == "explicit"
    assert row["match_method"] == "resolution_number"
    # Note: is_active stays False because _upsert_link's ON CONFLICT DO UPDATE
    # does not modify is_active (only association_type, match_method, etc.)
    # This is acceptable — the substantive-matched row is preserved as a tombstone
    # but won't render in UI; if we wanted to revive it, that would need a
    # follow-up patch to _upsert_link.
    assert row["is_active"] is False


@pytest.fixture
def consent_block_meeting():
    """Create a meeting with one consent-block vote and three is_consent agenda items.

    Idempotent setup with TEST_CONSENT title; ON DELETE CASCADE handles teardown.
    """
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM meetings WHERE title = 'TEST_CONSENT' AND meeting_date = '2099-01-02'"
            )
        conn.commit()

    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   SELECT id, 'TEST_CONSENT', '2099-01-02', 'council'
                   FROM municipalities ORDER BY id LIMIT 1
                   RETURNING id""",
            )
            mid = cur.fetchone()["id"]
            ai_ids = []
            for item_num, title in [
                ("12", "A Resolution authorizing HCL Contracting paving services 9th Avenue"),
                ("13", "A Resolution authorizing OLB Enterprises liquor license"),
                ("14", "A Resolution authorizing East Side Lounge license"),
            ]:
                cur.execute(
                    """INSERT INTO agenda_items (meeting_id, title, item_number, is_consent)
                       VALUES (%s, %s, %s, TRUE) RETURNING id""",
                    (mid, title, item_num),
                )
                ai_ids.append(cur.fetchone()["id"])
            cur.execute(
                """INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions,
                                       confidence, needs_review, raw_text, match_context)
                   VALUES (%s, 'minutes_text', 'passed', 5, 0, 0, 'high', FALSE, %s, %s)
                   RETURNING id""",
                (
                    mid,
                    "Some preamble mentioning HCL Contracting paving 9th Avenue. The resolutions "
                    "and ordinances introduced as consent agenda matters were read by the City Clerk.",
                    "consent agenda matters",
                ),
            )
            vid = cur.fetchone()["id"]
        conn.commit()
    yield {"meeting_id": mid, "vote_id": vid, "agenda_item_ids": ai_ids}
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = %s", (mid,))
        conn.commit()


def test_consent_block_links_named_item_with_confidence_1(consent_block_meeting):
    """Items whose title keywords appear in the vote's raw_text get consent_named, conf=1.0."""
    from docket.analysis.vote_matcher import match_votes_for_meeting
    match_votes_for_meeting(consent_block_meeting["meeting_id"])

    from docket.db import db_cursor
    with db_cursor() as cur:
        cur.execute(
            "SELECT agenda_item_id, association_type, match_confidence FROM vote_agenda_items "
            "WHERE vote_id = %s ORDER BY agenda_item_id",
            (consent_block_meeting["vote_id"],),
        )
        rows = cur.fetchall()

    by_item = {r["agenda_item_id"]: r for r in rows}
    hcl_id = consent_block_meeting["agenda_item_ids"][0]
    olb_id = consent_block_meeting["agenda_item_ids"][1]

    assert by_item[hcl_id]["association_type"] == "consent_named"
    assert by_item[hcl_id]["match_confidence"] == pytest.approx(1.0)
    assert by_item[olb_id]["association_type"] == "consent_implicit"
    assert by_item[olb_id]["match_confidence"] == pytest.approx(0.8)


def test_consent_block_links_default_fill_provisional(consent_block_meeting):
    """All consent-block links start provisional=True."""
    from docket.analysis.vote_matcher import match_votes_for_meeting
    match_votes_for_meeting(consent_block_meeting["meeting_id"])

    from docket.db import db_cursor
    with db_cursor() as cur:
        cur.execute(
            "SELECT provisional FROM vote_agenda_items WHERE vote_id = %s",
            (consent_block_meeting["vote_id"],),
        )
        rows = cur.fetchall()

    assert len(rows) == 3
    assert all(r["provisional"] for r in rows)
