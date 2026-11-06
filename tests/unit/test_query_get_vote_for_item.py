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

from docket.db import db, db_cursor
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


# ── The video link (docket.services.video_links) ───────────────────────────
#
# A vote that has both a video_timestamp and a video_url carries a finished
# VideoLink; the template prints it and builds no URL of its own. Plan:
# plans/active/video-links-land-on-the-moment.md (M5).

_PLAYER = "https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id="


def _insert_clip_meeting(muni_id, title, meeting_date, clip):
    """A Granicus meeting: an all-digit external_id and its player page."""
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type,
                                     external_id, video_url, minutes_url)
               VALUES (%s, %s, %s, 'council', %s, %s, 'https://example.test/minutes.pdf')
               RETURNING id""",
            (muni_id, title, meeting_date, clip, _PLAYER + clip),
        )
        return cur.fetchone()["id"]


def _insert_cued_item(meeting_id, number, external_id, *, cue_s=None, is_consent=False):
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO agenda_items (meeting_id, title, item_number, external_id,
                                         is_consent, video_timestamp_seconds)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (meeting_id, "Item " + number, number, external_id, is_consent, cue_s),
        )
        return cur.fetchone()["id"]


def _insert_ocr_vote(meeting_id, video_timestamp, item_id=None):
    """A vote read off the video at ``video_timestamp``, linked to ``item_id`` when given."""
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions,
                                  confidence, needs_review, video_timestamp)
               VALUES (%s, 'video_ocr', 'passed', 9, 0, 0, 'high', FALSE, %s)
               RETURNING id""",
            (meeting_id, video_timestamp),
        )
        vote_id = cur.fetchone()["id"]
    if item_id is not None:
        _insert_link(vote_id, item_id)
    return vote_id


def _insert_recording(meeting_id, video_id, clip, *, status="passed", offset_s=635.48,
                      start_s=635.5, end_s=3935.5):
    """A YouTube recording of the meeting and, unless ``status`` is None, its measurement."""
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meeting_videos (meeting_id, provider, video_id, url, title,
                                           clean_title, duration_s, is_primary)
               VALUES (%s, 'youtube', %s, %s, 'TEST_GVFI recording', 'TEST_GVFI recording',
                       3443, FALSE) RETURNING id""",
            (meeting_id, video_id, "https://www.youtube.com/watch?v=" + video_id),
        )
        meeting_video_id = cur.fetchone()["id"]
        if status is not None:
            cur.execute(
                """INSERT INTO meeting_video_alignments
                     (meeting_video_id, granicus_clip_id, method_version, status, reason,
                      offset_s, granicus_start_s, granicus_end_s, score, runner_up,
                      windows, windows_confirmed)
                   VALUES (%s, %s, 1, %s, %s, %s, %s, %s, 23.6, 6.0, 12, 10)""",
                (meeting_video_id, clip, status, None if status == "passed" else "score",
                 offset_s, start_s, end_s),
            )


def _link(item_id, vote_id):
    """The video_link of ``vote_id`` among the votes get_vote_for_item returns for the item."""
    data = get_vote_for_item(item_id)
    entries = {e.vote_id: e for e in [data.prevailing, *data.history]}
    return entries[vote_id].video_link


def test_ocr_vote_without_a_measurement_gets_the_granicus_chapter_link(muni_id, cleanup_test_rows):
    """An OCR vote on the item's own meeting, the item's id a Granicus chapter
    id, and no measured recording: the link opens the Granicus player at the
    item's chapter."""
    clip = "99052026"
    meeting_id = _insert_clip_meeting(muni_id, "TEST_GVFI_link_granicus", "2099-01-05", clip)
    item_id = _insert_cued_item(meeting_id, "64", "371164", cue_s=2256.0)
    vote_id = _insert_ocr_vote(meeting_id, 2400.0, item_id)

    link = _link(item_id, vote_id)

    assert link.url == _PLAYER + clip + "&meta_id=371164"
    assert (link.site, link.label, link.seconds, link.timed) == ("granicus", "Granicus", None, True)

    # A recording that was never measured, and one whose match was rejected,
    # change nothing.
    _insert_recording(meeting_id, "gvfi-unmeasured", clip, status=None)
    _insert_recording(meeting_id, "gvfi-rejected", clip, status="rejected")
    assert _link(item_id, vote_id) == link

    # An item that kept the id it was given from the agenda PDF has no
    # chapter: the plain player, and the link does not claim to be timed.
    pdf_item = _insert_cued_item(meeting_id, "65", "event-2715-65", cue_s=2300.0)
    pdf_link = _link(pdf_item, _insert_ocr_vote(meeting_id, 2450.0, pdf_item))
    assert (pdf_link.url, pdf_link.site, pdf_link.timed) == (_PLAYER + clip, "granicus", False)

    # An item with a chapter id and no cue point still opens its chapter.
    uncued = _insert_cued_item(meeting_id, "66", "371166")
    uncued_link = _link(uncued, _insert_ocr_vote(meeting_id, 2500.0, uncued))
    assert (uncued_link.url, uncued_link.timed) == (_PLAYER + clip + "&meta_id=371166", True)

    # A vote on another meeting (the item reconsidered): the item's chapter
    # id names a chapter of the item's own clip, so the other meeting's
    # player opens with no chapter.
    other_clip = "99052036"
    other = _insert_clip_meeting(muni_id, "TEST_GVFI_link_granicus_later", "2099-02-05", other_clip)
    later_vote = _insert_ocr_vote(other, 500.0, item_id)
    later_link = _link(item_id, later_vote)
    assert (later_link.url, later_link.site, later_link.timed) == (_PLAYER + other_clip, "granicus", False)
    assert _link(item_id, vote_id) == link


def test_ocr_vote_with_a_passing_measurement_gets_youtube_at_the_converted_second(muni_id, cleanup_test_rows):
    """The same, with a passing measurement that covers the item's cue point:
    YouTube at the item's moment minus the offset. Meeting 3184's figures."""
    clip = "99052027"
    meeting_id = _insert_clip_meeting(muni_id, "TEST_GVFI_link_youtube", "2099-01-06", clip)
    _insert_recording(meeting_id, "gvfi-FR84h22", clip)     # offset 635.48, covers 635.5 to 3935.5
    watch = "https://www.youtube.com/watch?v=gvfi-FR84h22&t="

    # The item's moment, not the vote's own second (2,400 s would be t=1764s).
    item_id = _insert_cued_item(meeting_id, "64", "371164", cue_s=2256.0)
    link = _link(item_id, _insert_ocr_vote(meeting_id, 2400.0, item_id))
    assert link.url == watch + "1620s"
    assert (link.site, link.label, link.seconds, link.timed) == ("youtube", "YouTube", 1620, True)

    # The consent rule: an item read out in the consent run, and a consent
    # item with no cue point, open the start of the run (1,990 s); a consent
    # item whose cue point is outside the run opens its own moment.
    in_run = [_insert_cued_item(meeting_id, str(n), str(371100 + n), cue_s=cue, is_consent=True)
              for n, cue in ((1, 1990.0), (2, 2037.5), (3, 2085.0))]
    uncued_consent = _insert_cued_item(meeting_id, "7", "event-2715-7", is_consent=True)
    pulled = _insert_cued_item(meeting_id, "5", "371105", cue_s=3000.0, is_consent=True)
    assert _link(in_run[1], _insert_ocr_vote(meeting_id, 2300.0, in_run[1])).url == watch + "1354s"
    assert _link(uncued_consent, _insert_ocr_vote(meeting_id, 2301.0, uncued_consent)).url == watch + "1354s"
    assert _link(pulled, _insert_ocr_vote(meeting_id, 3100.0, pulled)).url == watch + "2364s"

    # An item whose moment is past the recording's coverage opens its
    # Granicus chapter, although the vote's own second is covered.
    past = _insert_cued_item(meeting_id, "90", "371190", cue_s=4000.0)
    past_link = _link(past, _insert_ocr_vote(meeting_id, 3900.0, past))
    assert (past_link.url, past_link.site) == (_PLAYER + clip + "&meta_id=371190", "granicus")

    # An item with no cue point has no second of its own, so the link opens
    # at the vote's own second. (2,401 s, not 2,400 again: two OCR votes of
    # one meeting cannot share a second, idx_votes_ocr_unique.)
    uncued = _insert_cued_item(meeting_id, "70", clip + "-70")
    assert _link(uncued, _insert_ocr_vote(meeting_id, 2401.0, uncued)).url == watch + "1765s"

    # A vote on another meeting opens that meeting's recording at the vote's
    # own second; and there, a consent item with no cue point in a meeting
    # with no consent run has no moment, so its vote's own second is used.
    other_clip = "99052037"
    other = _insert_clip_meeting(muni_id, "TEST_GVFI_link_youtube_later", "2099-02-06", other_clip)
    _insert_recording(other, "gvfi-later", other_clip, offset_s=100.0, start_s=100.0, end_s=5000.0)
    later_link = _link(item_id, _insert_ocr_vote(other, 500.0, item_id))
    assert (later_link.url, later_link.seconds) == ("https://www.youtube.com/watch?v=gvfi-later&t=400s", 400)
    no_moment = _insert_cued_item(other, "8", "event-2716-8", is_consent=True)
    assert _link(no_moment, _insert_ocr_vote(other, 700.0, no_moment)).url == \
        "https://www.youtube.com/watch?v=gvfi-later&t=600s"


def test_vote_without_a_video_timestamp_has_no_video_link(muni_id, cleanup_test_rows):
    """A vote read from the minutes has no moment in the video, so it carries
    no video link, whatever the meeting's recordings are."""
    clip = "99052028"
    meeting_id = _insert_clip_meeting(muni_id, "TEST_GVFI_link_none", "2099-01-07", clip)
    _insert_recording(meeting_id, "gvfi-none", clip)
    item_id = _insert_cued_item(meeting_id, "64", "371164", cue_s=2256.0)
    minutes_vote = _insert_vote(meeting_id)
    _insert_link(minutes_vote, item_id)

    result = get_vote_for_item(item_id)

    assert result.prevailing.video_timestamp is None
    assert result.prevailing.video_url == _PLAYER + clip
    assert result.prevailing.video_link is None

    # Beside an OCR vote of the same meeting, only the OCR vote gets one; a
    # timestamp of zero seconds is a timestamp.
    ocr_vote = _insert_ocr_vote(meeting_id, 0.0, item_id)
    assert _link(item_id, minutes_vote) is None
    assert _link(item_id, ocr_vote).url == "https://www.youtube.com/watch?v=gvfi-none&t=1620s"

    # A vote with a timestamp on a meeting that has no video has none either.
    bare = _insert_meeting(muni_id, "TEST_GVFI_link_no_video", "2099-01-08")
    bare_item = _insert_item(bare, "Item on a meeting without video")
    assert _link(bare_item, _insert_ocr_vote(bare, 123.5, bare_item)) is None
