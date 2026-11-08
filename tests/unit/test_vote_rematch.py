"""Tests for docket.services.vote_rematch: the listing of timestamp links
with their gaps and candidate items, the transcript window, and the
re-match that moves stored attachments to where the near-cue rule puts them.

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


def _link(vote_id, item_id, *, method="timestamp", confidence=1.0, provisional=False,
          is_manual=False, is_active=True):
    """Insert one more link for an existing vote. Returns the link id."""
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO vote_agenda_items
                       (vote_id, agenda_item_id, association_type, match_method,
                        match_confidence, provisional, is_manual, is_active)
                   VALUES (%s, %s, 'explicit', %s, %s, %s, %s, %s) RETURNING id""",
                (vote_id, item_id, method, confidence, provisional, is_manual, is_active),
            )
            link_id = cur.fetchone()["id"]
        conn.commit()
    return link_id


def _rows(vote_id):
    """Every vote_agenda_items row of the vote, oldest id first."""
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, agenda_item_id, association_type, match_method, match_confidence,
                          provisional, is_manual, is_active, updated_at
                     FROM vote_agenda_items WHERE vote_id = %s ORDER BY id""",
                (vote_id,),
            )
            return cur.fetchall()


def _moves(slug, meeting_id, **kwargs):
    from docket.services.vote_rematch import rematch_near_cue_links
    return [m for m in rematch_near_cue_links(slug, **kwargs) if m.link.meeting_id == meeting_id]


def test_rematch_dry_run_lists_the_near_cue_move_and_writes_nothing(near_cue_meeting):
    mid = near_cue_meeting["meeting_id"]
    items = near_cue_meeting["items"]
    # An item cued between 63 and 3 but inserted last, so the meeting's items
    # are not in cue order on the heap and the rule depends on its ORDER BY.
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agenda_items (meeting_id, title, item_number, is_consent,
                                             video_timestamp_seconds)
                   VALUES (%s, 'A Resolution read between the two', '2', FALSE, 2100.0)""",
                (mid,),
            )
        conn.commit()
    # Listed first by time, returned last: its stored item 63 is no longer the
    # latest cue at or before it (item 3 at 2145 is), so it is left alone.
    stale = _vote(mid, 2146.0, link_to=items["63"])
    vid = _vote(mid, 2256.0, link_to=items["64"])
    flagged = _vote(mid, 2257.0, link_to=items["64"], needs_review=True)

    moves = _moves("birmingham", mid, dry_run=True)

    assert [(m.reason, m.link.vote_id) for m in moves] == [
        ("near_cue", vid), ("near_cue", flagged), ("cue_changed", stale),
    ]
    move = moves[0]
    assert move.link.item_id == items["64"]
    assert move.new_item_id == items["3"] == move.link.earlier_item_id
    assert move.new_item_number == "3"
    assert move.new_cue == pytest.approx(2145.0)
    assert move.new_gap == pytest.approx(111.0)
    assert move.new_confidence == pytest.approx(1.0)
    # A flagged vote's confidence is halved, as the matcher halves it.
    assert moves[1].new_item_id == items["3"]
    assert moves[1].new_gap == pytest.approx(112.0)
    assert moves[1].new_confidence == pytest.approx(0.5)
    for v, item in ((vid, items["64"]), (flagged, items["64"]), (stale, items["63"])):
        (row,) = _rows(v)
        assert row["agenda_item_id"] == item and row["is_active"] is True


def test_rematch_moves_the_near_cue_link_and_leaves_the_far_one(near_cue_meeting):
    mid = near_cue_meeting["meeting_id"]
    items = near_cue_meeting["items"]
    near = _vote(mid, 2256.0, link_to=items["64"])
    far = _vote(mid, 2300.0, link_to=items["64"])
    (near_before,) = _rows(near)
    (far_before,) = _rows(far)

    moves = _moves("birmingham", mid)

    assert [(m.reason, m.link.vote_id) for m in moves] == [("near_cue", near)]
    old, new = _rows(near)
    assert old["agenda_item_id"] == items["64"] and old["is_active"] is False
    assert old["updated_at"] > near_before["updated_at"]
    assert new["agenda_item_id"] == items["3"] and new["is_active"] is True
    assert new["association_type"] == "explicit"
    assert new["match_method"] == "timestamp"
    assert new["match_confidence"] == pytest.approx(1.0)
    assert new["provisional"] is False and new["is_manual"] is False
    (far_after,) = _rows(far)
    assert far_after == far_before


def test_rematch_leaves_a_manual_link_alone(near_cue_meeting):
    mid = near_cue_meeting["meeting_id"]
    items = near_cue_meeting["items"]
    vid = _vote(mid, 2256.0, link_to=items["64"], is_manual=True)
    # A second near-cue vote whose target already holds a manual tombstone: a
    # human said "not item 3", so the upsert leaves that row as it is and the
    # vote ends with no active link rather than one a human ruled out.
    other = _vote(mid, 2257.0, link_to=items["64"])
    _link(other, items["3"], confidence=0.5, is_manual=True, is_active=False)
    (_, tombstone_before) = _rows(other)

    moves = _moves("birmingham", mid)

    assert [(m.reason, m.link.vote_id) for m in moves] == [("near_cue", other)]
    (row,) = _rows(vid)
    assert row["agenda_item_id"] == items["64"]
    assert row["is_active"] is True and row["is_manual"] is True
    old, tombstone = _rows(other)
    assert old["agenda_item_id"] == items["64"] and old["is_active"] is False
    assert tombstone == tombstone_before


def test_rematch_second_run_moves_nothing(near_cue_meeting):
    mid = near_cue_meeting["meeting_id"]
    items = near_cue_meeting["items"]
    vid = _vote(mid, 2256.0, link_to=items["64"])

    first = _moves("birmingham", mid)
    rows_after_first = _rows(vid)
    second = _moves("birmingham", mid)

    assert [m.reason for m in first] == ["near_cue"]
    assert second == []
    assert _rows(vid) == rows_after_first


def test_rematch_reactivates_an_existing_tombstone_for_the_target(near_cue_meeting):
    mid = near_cue_meeting["meeting_id"]
    items = near_cue_meeting["items"]
    vid = _vote(mid, 2256.0, link_to=items["64"])
    ghost = _link(vid, items["3"], confidence=0.5, provisional=True, is_active=False)

    moves = _moves("birmingham", mid)

    assert [m.reason for m in moves] == ["near_cue"]
    rows = _rows(vid)
    assert len(rows) == 2
    by_item = {r["agenda_item_id"]: r for r in rows}
    assert by_item[items["64"]]["is_active"] is False
    revived = by_item[items["3"]]
    assert revived["id"] == ghost
    assert revived["is_active"] is True
    assert revived["match_confidence"] == pytest.approx(1.0)
    assert revived["provisional"] is False
    assert revived["match_method"] == "timestamp" and revived["association_type"] == "explicit"


def test_rematch_lists_a_cue_changed_link_and_does_not_move_it(near_cue_meeting):
    mid = near_cue_meeting["meeting_id"]
    items = near_cue_meeting["items"]
    vid = _vote(mid, 2300.0, link_to=items["3"])

    moves = _moves("birmingham", mid)

    assert len(moves) == 1
    move = moves[0]
    assert move.reason == "cue_changed"
    assert move.link.vote_id == vid and move.link.is_latest_cue is False
    assert (move.new_item_id, move.new_item_number, move.new_cue, move.new_gap,
            move.new_confidence) == (None, None, None, None, None)
    (row,) = _rows(vid)
    assert row["agenda_item_id"] == items["3"] and row["is_active"] is True


def test_rematch_leaves_a_near_cue_vote_on_the_first_cued_item(near_cue_meeting):
    mid = near_cue_meeting["meeting_id"]
    items = near_cue_meeting["items"]
    vid = _vote(mid, 2086.0, link_to=items["63"])

    moves = _moves("birmingham", mid)

    assert moves == []
    (row,) = _rows(vid)
    assert row["agenda_item_id"] == items["63"] and row["is_active"] is True
