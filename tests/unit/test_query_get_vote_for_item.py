"""Tests for query.get_vote_for_item — single-item vote resolution.

Resolution rule (highest priority first):
  1. is_manual=TRUE  (admin override always wins)
  2. meeting_date DESC  (most recent)
  3. association_type ASC, mapped via CASE so substantive ('explicit')
     sorts before consent variants
  4. votes.id DESC  (final tiebreaker — newer DB insertion wins)

Filters: is_active=TRUE only (ghost links from pulled-from-consent items
are excluded).

Returns: (prevailing, history) shape so the item_detail template can show
one banner plus a "View vote history (N)" disclosure for re-votes.
Returns None when no active links exist for the item.
"""

from __future__ import annotations

import pytest
import psycopg2.extras

from docket.db import db
from docket.services.query import get_vote_for_item


# ── Fixture helpers ────────────────────────────────────────────────────────


@pytest.fixture
def muni_id():
    """Reuse the first municipality (Birmingham in test DB)."""
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM municipalities ORDER BY id LIMIT 1")
            return cur.fetchone()["id"]


@pytest.fixture
def cleanup_test_rows():
    """Remove any leftover TEST_GVFI meetings before AND after each test."""
    def _cleanup():
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM meetings WHERE title LIKE 'TEST_GVFI%'"
                )
            conn.commit()
    _cleanup()
    yield
    _cleanup()


def _insert_meeting(muni_id, title, meeting_date):
    """Insert a meeting and return its id."""
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   VALUES (%s, %s, %s, 'council') RETURNING id""",
                (muni_id, title, meeting_date),
            )
            return cur.fetchone()["id"]
        conn.commit()


def _insert_item(meeting_id, title, *, item_number="1", is_consent=False):
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO agenda_items (meeting_id, title, item_number, is_consent)
                   VALUES (%s, %s, %s, %s) RETURNING id""",
                (meeting_id, title, item_number, is_consent),
            )
            return cur.fetchone()["id"]
        conn.commit()


def _insert_vote(meeting_id, *, result="passed", yeas=5, nays=0,
                 abstentions=0, source="minutes_text"):
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO votes (meeting_id, source, result, yeas, nays,
                                       abstentions, confidence, needs_review)
                   VALUES (%s, %s, %s, %s, %s, %s, 'high', FALSE)
                   RETURNING id""",
                (meeting_id, source, result, yeas, nays, abstentions),
            )
            return cur.fetchone()["id"]
        conn.commit()


def _insert_link(vote_id, item_id, *, association_type="explicit",
                 match_method="explicit", match_confidence=1.0,
                 provisional=False, is_manual=False, is_active=True):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO vote_agenda_items
                    (vote_id, agenda_item_id, association_type, match_method,
                     match_confidence, provisional, is_manual, is_active)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (vote_id, item_id, association_type, match_method,
                 match_confidence, provisional, is_manual, is_active),
            )
        conn.commit()


# ── Tests ──────────────────────────────────────────────────────────────────


def test_returns_none_when_no_vote_links_exist(muni_id, cleanup_test_rows):
    """Item with no rows in vote_agenda_items → returns None."""
    meeting_id = _insert_meeting(muni_id, "TEST_GVFI_no_votes", "2099-01-01")
    item_id = _insert_item(meeting_id, "Lonely item")

    result = get_vote_for_item(item_id)

    assert result is None


def test_single_substantive_vote_returns_prevailing_with_empty_history(
    muni_id, cleanup_test_rows
):
    """One substantive vote on an item → prevailing populated, history is []."""
    meeting_id = _insert_meeting(muni_id, "TEST_GVFI_single_sub", "2099-02-01")
    item_id = _insert_item(meeting_id, "Item with one substantive vote")
    vote_id = _insert_vote(meeting_id, result="passed", yeas=9, nays=0)
    _insert_link(vote_id, item_id, association_type="explicit")

    result = get_vote_for_item(item_id)

    assert result is not None
    assert result.prevailing.vote_id == vote_id
    assert result.prevailing.result == "passed"
    assert result.prevailing.yeas == 9
    assert result.prevailing.nays == 0
    assert result.prevailing.association_type == "explicit"
    assert result.prevailing.is_consent_block is False
    assert result.prevailing.provisional is False
    assert result.prevailing.is_manual is False
    assert result.history == []


def test_consent_vote_provisional_flag_carries_through(muni_id, cleanup_test_rows):
    """A provisional consent_named link surfaces as is_consent_block=True
    and provisional=True so the template can render the provisional pill."""
    meeting_id = _insert_meeting(muni_id, "TEST_GVFI_provisional", "2099-03-01")
    item_id = _insert_item(meeting_id, "Item on provisional consent", is_consent=True)
    vote_id = _insert_vote(meeting_id)
    _insert_link(vote_id, item_id, association_type="consent_named", provisional=True)

    result = get_vote_for_item(item_id)

    assert result is not None
    assert result.prevailing.is_consent_block is True
    assert result.prevailing.provisional is True


def test_consent_vote_adopted_flag_carries_through(muni_id, cleanup_test_rows):
    """A non-provisional (adopted) consent link surfaces with provisional=False."""
    meeting_id = _insert_meeting(muni_id, "TEST_GVFI_adopted", "2099-03-02")
    item_id = _insert_item(meeting_id, "Item on adopted consent", is_consent=True)
    vote_id = _insert_vote(meeting_id)
    _insert_link(vote_id, item_id, association_type="consent_named", provisional=False)

    result = get_vote_for_item(item_id)

    assert result is not None
    assert result.prevailing.is_consent_block is True
    assert result.prevailing.provisional is False


def test_substantive_wins_over_consent_at_same_date(muni_id, cleanup_test_rows):
    """Item linked to both substantive and consent votes in the same meeting
    → substantive (explicit) is prevailing; consent is in history."""
    meeting_id = _insert_meeting(muni_id, "TEST_GVFI_sub_v_consent", "2099-04-01")
    item_id = _insert_item(meeting_id, "Item with two votes in same meeting")
    consent_vote_id = _insert_vote(meeting_id, result="passed", yeas=9, nays=0)
    substantive_vote_id = _insert_vote(meeting_id, result="passed", yeas=8, nays=1)
    _insert_link(consent_vote_id, item_id, association_type="consent_named")
    _insert_link(substantive_vote_id, item_id, association_type="explicit")

    result = get_vote_for_item(item_id)

    assert result is not None
    assert result.prevailing.vote_id == substantive_vote_id
    assert result.prevailing.association_type == "explicit"
    assert len(result.history) == 1
    assert result.history[0].vote_id == consent_vote_id
    assert result.history[0].association_type == "consent_named"


def test_manual_shield_wins_over_more_recent_vote(muni_id, cleanup_test_rows):
    """is_manual=TRUE always wins, even when a more recent automated link
    exists. Reflects the manual-shield contract: admin judgment overrides
    automated matchers."""
    old_meeting = _insert_meeting(muni_id, "TEST_GVFI_manual_old", "2099-05-01")
    new_meeting = _insert_meeting(muni_id, "TEST_GVFI_manual_new", "2099-06-01")
    item_id = _insert_item(old_meeting, "Item with manual + later auto link")
    manual_vote = _insert_vote(old_meeting, result="passed", yeas=5, nays=4)
    auto_vote = _insert_vote(new_meeting, result="failed", yeas=4, nays=5)
    _insert_link(manual_vote, item_id, is_manual=True, association_type="explicit")
    _insert_link(auto_vote, item_id, is_manual=False, association_type="explicit")

    result = get_vote_for_item(item_id)

    assert result is not None
    assert result.prevailing.vote_id == manual_vote
    assert result.prevailing.is_manual is True
    assert len(result.history) == 1
    assert result.history[0].vote_id == auto_vote


def test_reconsideration_most_recent_wins(muni_id, cleanup_test_rows):
    """Two substantive votes on different dates (reconsideration) → most
    recent is prevailing, earlier is in history."""
    early_meeting = _insert_meeting(muni_id, "TEST_GVFI_recon_early", "2099-07-01")
    late_meeting = _insert_meeting(muni_id, "TEST_GVFI_recon_late", "2099-08-01")
    item_id = _insert_item(early_meeting, "Item reconsidered later")
    early_vote = _insert_vote(early_meeting, result="passed", yeas=5, nays=4)
    late_vote = _insert_vote(late_meeting, result="failed", yeas=4, nays=5)
    _insert_link(early_vote, item_id, association_type="explicit")
    _insert_link(late_vote, item_id, association_type="explicit")

    result = get_vote_for_item(item_id)

    assert result is not None
    assert result.prevailing.vote_id == late_vote
    assert result.prevailing.result == "failed"
    assert len(result.history) == 1
    assert result.history[0].vote_id == early_vote
    assert result.history[0].result == "passed"


def test_same_date_same_type_higher_id_wins(muni_id, cleanup_test_rows):
    """Two substantive votes same meeting same type (motion-to-amend +
    main motion) → higher votes.id wins as final tiebreaker."""
    meeting_id = _insert_meeting(muni_id, "TEST_GVFI_amend_plus_main", "2099-09-01")
    item_id = _insert_item(meeting_id, "Item with amend + main motion")
    amend_vote = _insert_vote(meeting_id, result="passed", yeas=6, nays=3)
    main_vote = _insert_vote(meeting_id, result="passed", yeas=9, nays=0)
    _insert_link(amend_vote, item_id, association_type="explicit")
    _insert_link(main_vote, item_id, association_type="explicit")

    result = get_vote_for_item(item_id)

    assert result is not None
    assert result.prevailing.vote_id == main_vote  # higher id wins
    assert len(result.history) == 1
    assert result.history[0].vote_id == amend_vote


def test_inactive_links_excluded(muni_id, cleanup_test_rows):
    """is_active=FALSE rows (ghost links from pulled-from-consent items)
    must be excluded from both prevailing AND history."""
    meeting_id = _insert_meeting(muni_id, "TEST_GVFI_ghost", "2099-10-01")
    item_id = _insert_item(meeting_id, "Item with one active + one ghost link")
    active_vote = _insert_vote(meeting_id, result="passed")
    ghost_vote = _insert_vote(meeting_id, result="passed")
    _insert_link(active_vote, item_id, is_active=True, association_type="explicit")
    _insert_link(ghost_vote, item_id, is_active=False, association_type="consent_named")

    result = get_vote_for_item(item_id)

    assert result is not None
    assert result.prevailing.vote_id == active_vote
    assert result.history == []


def test_inactive_only_links_returns_none(muni_id, cleanup_test_rows):
    """If ALL links to the item are is_active=FALSE, return None — same
    as having no links at all."""
    meeting_id = _insert_meeting(muni_id, "TEST_GVFI_all_ghost", "2099-11-01")
    item_id = _insert_item(meeting_id, "Item with only ghost links")
    vote_id = _insert_vote(meeting_id)
    _insert_link(vote_id, item_id, is_active=False, association_type="consent_named")

    result = get_vote_for_item(item_id)

    assert result is None


def test_source_link_fields_surface_for_template(muni_id, cleanup_test_rows):
    """The template needs meeting_id, video_timestamp, video_url, and
    minutes_url to construct the per-vote source link. Verify those are
    threaded through the service."""
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO meetings
                    (municipality_id, title, meeting_date, meeting_type,
                     video_url, minutes_url)
                   VALUES (%s, %s, %s, 'council',
                           'https://example.test/video.mp4',
                           'https://example.test/minutes.pdf')
                   RETURNING id""",
                (muni_id, "TEST_GVFI_sources", "2099-12-01"),
            )
            meeting_id = cur.fetchone()["id"]
        conn.commit()
    item_id = _insert_item(meeting_id, "Item with video+minutes source")
    # Insert vote with a video_timestamp directly so we can check plumbing.
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO votes (meeting_id, source, result, yeas, nays,
                                       abstentions, confidence, needs_review,
                                       video_timestamp)
                   VALUES (%s, 'video_ocr', 'passed', 9, 0, 0, 'high', FALSE,
                           123.5)
                   RETURNING id""",
                (meeting_id,),
            )
            vote_id = cur.fetchone()["id"]
        conn.commit()
    _insert_link(vote_id, item_id, association_type="explicit")

    result = get_vote_for_item(item_id)

    assert result is not None
    assert result.prevailing.meeting_id == meeting_id
    assert result.prevailing.video_timestamp == pytest.approx(123.5)
    assert result.prevailing.video_url == "https://example.test/video.mp4"
    assert result.prevailing.minutes_url == "https://example.test/minutes.pdf"
