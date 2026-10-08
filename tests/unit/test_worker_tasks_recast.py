"""Tests for the daily recast_post_meeting_ai cron task.

Spec: docs/superpowers/specs/2026-05-18-upcoming-meeting-forward-voice-design.md
§"Re-cascade trigger". Items written in forward voice while a meeting was
upcoming are re-queued once the meeting is in the past and left evidence
of having happened (video or minutes); the meeting summary is re-queued
with them so it is rebuilt from the completed-voice item text.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from docket.db import db
from docket.worker.tasks import _do_recast_post_meeting_ai


@pytest.fixture
def seed():
    created: list[tuple[str, int]] = []

    def add_meeting(*, days_ago=3, video_url="https://v", minutes_url=None,
                    summary="old summary", summary_voice="completed",
                    ai_metadata='{"phase": "adopted", "confidence": "high"}',
                    is_hidden=False):
        with db() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO municipalities (slug, name, state, adapter_class, active)
                VALUES ('test_recast', 'Test', 'AL', 'granicus', TRUE)
                ON CONFLICT (slug) DO UPDATE SET active = TRUE RETURNING id
            """)
            muni = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url, title,
                                      video_url, minutes_url, executive_summary, executive_summary_voice,
                                      ai_metadata, ai_prompt_version, is_hidden)
                VALUES (%s, 'council', CURRENT_DATE - %s, 'x', 'recast test', %s, %s, %s, %s,
                        %s::jsonb, 2, %s)
                RETURNING id
            """, (muni, days_ago, video_url, minutes_url, summary, summary_voice,
                  ai_metadata, is_hidden))
            mid = cur.fetchone()[0]
            conn.commit()
        created.append(("meeting", mid))
        return mid

    def add_item(meeting_id, *, voice="upcoming", version=100, status="completed"):
        with db() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO agenda_items (meeting_id, title, is_consent, ai_rewrite_voice,
                                          ai_rewrite_version, processing_status, headline)
                VALUES (%s, 'item', FALSE, %s, %s, %s::processing_status_enum, 'Council will consider')
                RETURNING id
            """, (meeting_id, voice, version, status))
            iid = cur.fetchone()[0]
            conn.commit()
        created.append(("item", iid))
        return iid

    def item(iid):
        with db() as conn, conn.cursor() as cur:
            cur.execute("SELECT ai_rewrite_voice, ai_rewrite_version, processing_status::text "
                        "FROM agenda_items WHERE id = %s", (iid,))
            return cur.fetchone()

    def meeting(mid):
        with db() as conn, conn.cursor() as cur:
            cur.execute("SELECT executive_summary, executive_summary_voice, ai_metadata, "
                        "ai_prompt_version FROM meetings WHERE id = %s", (mid,))
            return cur.fetchone()

    yield type("Seed", (), {"add_meeting": staticmethod(add_meeting),
                            "add_item": staticmethod(add_item),
                            "item": staticmethod(item),
                            "meeting": staticmethod(meeting)})
    with db() as conn, conn.cursor() as cur:
        for kind, rid in created:
            if kind == "item":
                cur.execute("DELETE FROM agenda_items WHERE id = %s", (rid,))
        for kind, rid in created:
            if kind == "meeting":
                cur.execute("DELETE FROM meetings WHERE id = %s", (rid,))
        conn.commit()


def test_recast_requeues_upcoming_items_on_past_meeting_with_video(seed):
    mid = seed.add_meeting()
    iid = seed.add_item(mid)

    result = _do_recast_post_meeting_ai()

    assert seed.item(iid) == (None, None, "pending")
    assert result["items"] >= 1


def test_recast_requeues_the_meeting_summary_but_keeps_its_text(seed):
    """The summary was built from forward-voice item text: drop the version
    and phase so both passes re-claim it once the items settle, but leave the
    completed-voice text on the page until the replacement lands."""
    mid = seed.add_meeting()
    seed.add_item(mid)

    _do_recast_post_meeting_ai()

    summary, voice, metadata, version = seed.meeting(mid)
    assert summary == "old summary"
    assert voice == "completed"
    assert version is None
    assert "phase" not in metadata
    assert "confidence" not in metadata


def test_recast_clears_a_forward_voice_summary(seed):
    """A summary still in upcoming voice on a past meeting is misleading; clear it."""
    mid = seed.add_meeting(summary="The council will consider…", summary_voice="upcoming")

    _do_recast_post_meeting_ai()

    summary, voice, metadata, version = seed.meeting(mid)
    assert summary is None
    assert voice is None
    assert version is None


def test_recast_accepts_minutes_as_evidence(seed):
    mid = seed.add_meeting(video_url=None, minutes_url="https://m")
    iid = seed.add_item(mid)

    _do_recast_post_meeting_ai()

    assert seed.item(iid)[2] == "pending"


def test_recast_skips_meeting_with_no_evidence_it_happened(seed):
    mid = seed.add_meeting(video_url=None, minutes_url=None)
    iid = seed.add_item(mid)

    _do_recast_post_meeting_ai()

    assert seed.item(iid) == ("upcoming", 100, "completed")
    assert seed.meeting(mid)[3] == 2


def test_recast_skips_future_meeting(seed):
    mid = seed.add_meeting(days_ago=-2)
    iid = seed.add_item(mid)

    _do_recast_post_meeting_ai()

    assert seed.item(iid)[0] == "upcoming"


def test_recast_skips_today_meeting(seed):
    """Forward voice stays accurate while the council is in the room."""
    mid = seed.add_meeting(days_ago=0)
    iid = seed.add_item(mid)

    _do_recast_post_meeting_ai()

    assert seed.item(iid)[0] == "upcoming"


def test_recast_leaves_completed_voice_items_alone(seed):
    mid = seed.add_meeting()
    iid = seed.add_item(mid, voice="completed", version=4)

    _do_recast_post_meeting_ai()

    assert seed.item(iid) == ("completed", 4, "completed")
    assert seed.meeting(mid)[3] == 2


def test_recast_skips_hidden_meetings(seed):
    mid = seed.add_meeting(is_hidden=True)
    iid = seed.add_item(mid)

    _do_recast_post_meeting_ai()

    assert seed.item(iid)[0] == "upcoming"
