"""Tests for docket.services.vote_rematch: the listing of timestamp links
with their gaps and candidate items, and the transcript window.

The fixture is meeting 3184 of issue #142 in miniature: items cued at 2085
(number 63, the last consent item), 2145 (item 3), 2256 (items 64 and 65,
one click), and one item with no cue (item 7)."""

import pytest
import psycopg2.extras

from docket.db import db


@pytest.fixture
def near_cue_meeting():
    """Insert a meeting with four cued items and one uncued one under the
    municipality with slug 'birmingham'; yield the ids; delete the meeting
    on teardown (the cascade removes items, votes, links, and transcript).
    Sweeps any earlier TEST_NEAR_CUE meeting on entry."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM meetings WHERE title = 'TEST_NEAR_CUE' AND meeting_date = '2099-01-03'"
            )
        conn.commit()

    items: dict[str, int] = {}
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   SELECT id, 'TEST_NEAR_CUE', '2099-01-03', 'council'
                   FROM municipalities WHERE slug = 'birmingham'
                   RETURNING id""",
            )
            mid = cur.fetchone()["id"]
            for number, cue, title in (
                ("63", 2085.0, "A Resolution authorizing the Mayor to execute a consent item"),
                ("3", 2145.0, "An Ordinance approving an interlocal agreement with Adamsville"),
                ("64", 2256.0, "A Resolution setting a public hearing November 24, 2026"),
                ("65", 2256.0, "A Resolution setting a public hearing December 1, 2026"),
                ("7", None, "An item ingested before the recording existed"),
            ):
                cur.execute(
                    """INSERT INTO agenda_items (meeting_id, title, item_number, is_consent,
                                                 video_timestamp_seconds)
                       VALUES (%s, %s, %s, FALSE, %s) RETURNING id""",
                    (mid, title, number, cue),
                )
                items[number] = cur.fetchone()["id"]
        conn.commit()

    yield {"meeting_id": mid, "items": items}

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = %s", (mid,))
        conn.commit()


def _vote(meeting_id, at, *, source="video_ocr", link_to=None, method="timestamp",
          is_manual=False, is_active=True, needs_review=False):
    """Insert a 9-0 passed vote at second `at` and, when `link_to` is given,
    a link to that item. Returns the vote id."""
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions,
                                      confidence, needs_review, video_timestamp)
                   VALUES (%s, %s, 'passed', 9, 0, 0, 'high', %s, %s) RETURNING id""",
                (meeting_id, source, needs_review, at),
            )
            vid = cur.fetchone()["id"]
            if link_to is not None:
                cur.execute(
                    """INSERT INTO vote_agenda_items
                           (vote_id, agenda_item_id, association_type, match_method,
                            match_confidence, provisional, is_manual, is_active)
                       VALUES (%s, %s, 'explicit', %s, 1.0, FALSE, %s, %s)""",
                    (vid, link_to, method, is_manual, is_active),
                )
        conn.commit()
    return vid


def test_lists_an_active_timestamp_link_with_its_gap_and_the_earlier_item(near_cue_meeting):
    from docket.services.vote_rematch import list_timestamp_links
    items = near_cue_meeting["items"]
    vid = _vote(near_cue_meeting["meeting_id"], 2256.0, link_to=items["64"])

    links = [l for l in list_timestamp_links("birmingham") if l.meeting_id == near_cue_meeting["meeting_id"]]

    assert len(links) == 1
    link = links[0]
    assert link.vote_id == vid
    assert link.vote_timestamp == pytest.approx(2256.0)
    assert link.result == "passed" and link.yeas == 9 and link.nays == 0
    assert link.needs_review is False
    assert link.item_id == items["64"]
    assert link.item_number == "64"
    assert link.item_cue == pytest.approx(2256.0)
    assert link.gap == pytest.approx(0.0)
    assert link.is_latest_cue is True
    assert link.earlier_item_id == items["3"]
    assert link.earlier_item_number == "3"
    assert link.earlier_cue == pytest.approx(2145.0)
    assert "Adamsville" in link.earlier_item_title
    assert link.item_active_video_votes == 1
    assert link.earlier_active_video_votes == 0
    assert link.has_transcript is False
    # Another city's listing does not carry this meeting's link.
    assert all(l.meeting_id != near_cue_meeting["meeting_id"] for l in list_timestamp_links("homewood"))


def test_counts_active_video_votes_on_each_candidate_item(near_cue_meeting):
    from docket.services.vote_rematch import list_timestamp_links
    mid = near_cue_meeting["meeting_id"]
    items = near_cue_meeting["items"]
    _vote(mid, 2256.0, link_to=items["64"])
    _vote(mid, 2325.5, link_to=items["64"])
    _vote(mid, None, source="minutes_text", link_to=items["64"], method="resolution_number")
    _vote(mid, None, source="minutes_text", link_to=items["3"], method="resolution_number")
    _vote(mid, 2200.0, link_to=items["3"], is_active=False)
    _vote(mid, 2258.0, link_to=items["64"], is_active=False)

    links = [l for l in list_timestamp_links("birmingham") if l.meeting_id == mid]

    assert [l.vote_timestamp for l in links] == pytest.approx([2256.0, 2325.5])
    assert [l.item_active_video_votes for l in links] == [2, 2]
    assert [l.earlier_active_video_votes for l in links] == [0, 0]


def test_earlier_item_is_the_latest_with_a_strictly_earlier_cue_second(near_cue_meeting):
    from docket.services.vote_rematch import list_timestamp_links
    items = near_cue_meeting["items"]
    _vote(near_cue_meeting["meeting_id"], 2257.0, link_to=items["65"])

    (link,) = [l for l in list_timestamp_links("birmingham") if l.meeting_id == near_cue_meeting["meeting_id"]]

    assert link.item_id == items["65"]
    assert link.gap == pytest.approx(1.0)
    assert link.earlier_item_id == items["3"]
    assert link.earlier_item_number == "3"
    assert link.earlier_cue == pytest.approx(2145.0)

    # When the earlier candidates share a second, the highest id wins.
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO agenda_items (meeting_id, title, item_number, is_consent,
                                             video_timestamp_seconds)
                   VALUES (%s, 'A Resolution after the pair', '66', FALSE, 2400.0) RETURNING id""",
                (near_cue_meeting["meeting_id"],),
            )
            item_66 = cur.fetchone()["id"]
        conn.commit()
    later = _vote(near_cue_meeting["meeting_id"], 2401.0, link_to=item_66)
    (link_66,) = [l for l in list_timestamp_links("birmingham") if l.vote_id == later]
    assert link_66.earlier_item_id == items["65"]
    assert link_66.earlier_cue == pytest.approx(2256.0)


def test_first_cued_item_has_no_earlier_item(near_cue_meeting):
    from docket.services.vote_rematch import list_timestamp_links
    items = near_cue_meeting["items"]
    _vote(near_cue_meeting["meeting_id"], 2086.0, link_to=items["63"])

    (link,) = [l for l in list_timestamp_links("birmingham") if l.meeting_id == near_cue_meeting["meeting_id"]]

    assert link.item_id == items["63"]
    assert link.gap == pytest.approx(1.0)
    assert link.earlier_item_id is None
    assert link.earlier_item_number is None
    assert link.earlier_item_title is None
    assert link.earlier_cue is None
    assert link.earlier_active_video_votes is None
    assert link.item_active_video_votes == 1


def test_within_filters_by_gap(near_cue_meeting):
    from docket.services.vote_rematch import list_timestamp_links
    mid = near_cue_meeting["meeting_id"]
    items = near_cue_meeting["items"]
    far = _vote(mid, 2300.0, link_to=items["64"])  # inserted first, listed second
    near = _vote(mid, 2256.0, link_to=items["64"])

    within = [l for l in list_timestamp_links("birmingham", within_s=10) if l.meeting_id == mid]
    every = [l for l in list_timestamp_links("birmingham") if l.meeting_id == mid]

    assert [l.vote_id for l in within] == [near]
    assert [l.vote_id for l in every] == [near, far]  # ordered by vote timestamp, not insertion
    assert [l.gap for l in every] == pytest.approx([0.0, 44.0])


def test_manual_inactive_and_non_timestamp_links_are_not_listed(near_cue_meeting):
    from docket.services.vote_rematch import list_timestamp_links
    mid = near_cue_meeting["meeting_id"]
    items = near_cue_meeting["items"]
    _vote(mid, 2256.0, link_to=items["64"], is_manual=True)
    _vote(mid, 2257.0, link_to=items["64"], is_active=False)
    _vote(mid, None, source="minutes_text", link_to=items["64"], method="resolution_number")
    # A video vote linked by another method; a minutes vote with a timestamp
    # linked by timestamp; a video vote with no timestamp; a timestamp link
    # to an item with no cue point.
    _vote(mid, 2258.0, link_to=items["64"], method="resolution_number")
    _vote(mid, 2259.0, source="minutes_text", link_to=items["64"])
    _vote(mid, None, link_to=items["64"])
    _vote(mid, 2260.0, link_to=items["7"])

    links = [l for l in list_timestamp_links("birmingham") if l.meeting_id == mid]

    assert links == []


def test_is_latest_cue_is_false_when_a_later_cue_sits_before_the_vote(near_cue_meeting):
    from docket.services.vote_rematch import list_timestamp_links
    items = near_cue_meeting["items"]
    _vote(near_cue_meeting["meeting_id"], 2300.0, link_to=items["3"])
    before_every_cue = _vote(near_cue_meeting["meeting_id"], 2000.0, link_to=items["63"])

    links = [l for l in list_timestamp_links("birmingham") if l.meeting_id == near_cue_meeting["meeting_id"]]

    assert [l.vote_id for l in links][-1] != before_every_cue  # ordered by vote timestamp
    link = links[-1]
    assert link.item_id == items["3"]
    assert link.gap == pytest.approx(155.0)
    assert link.is_latest_cue is False
    assert link.earlier_item_id == items["63"]
    # A vote before every cue has no latest cue at all; the flag is False, not None.
    first = links[0]
    assert first.vote_id == before_every_cue
    assert first.gap == pytest.approx(-85.0)
    assert first.is_latest_cue is False


def test_transcript_window_returns_overlapping_segments_in_order(near_cue_meeting):
    from docket.services.vote_rematch import list_timestamp_links, transcript_window
    mid = near_cue_meeting["meeting_id"]
    items = near_cue_meeting["items"]
    _vote(mid, 2256.0, link_to=items["64"])
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO transcripts (meeting_id, status) VALUES (%s, 'uploaded') RETURNING id",
                (mid,),
            )
            tid = cur.fetchone()["id"]
            for seq, start, end, text, silence in (
                (0, 2100.0, 2110.0, "the consent agenda is before the council", False),
                (1, 2130.0, 2140.0, "that vote is unanimous on the consent agenda", False),
                (2, 2140.0, 2150.0, "", True),
                (3, 2150.0, 2160.0, "Item three, an ordinance approving an interlocal agreement", False),
                (4, 2300.0, 2310.0, "Item sixty-four, a resolution setting a public hearing", False),
            ):
                cur.execute(
                    """INSERT INTO transcript_segments
                           (transcript_id, seq, start_s, end_s, text, is_silence)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (tid, seq, start, end, text, silence),
                )
        conn.commit()

    window = transcript_window(mid, 2136.0, 2271.0)
    (link,) = [l for l in list_timestamp_links("birmingham") if l.meeting_id == mid]

    assert [s for s, _ in window] == pytest.approx([2130.0, 2150.0])
    assert [t for _, t in window] == [
        "that vote is unanimous on the consent agenda",
        "Item three, an ordinance approving an interlocal agreement",
    ]
    assert link.has_transcript is True


def test_unknown_city_raises():
    from docket.services.vote_rematch import list_timestamp_links
    with pytest.raises(ValueError, match="no-such-city"):
        list_timestamp_links("no-such-city")
