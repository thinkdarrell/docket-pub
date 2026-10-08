"""Tests for maintenance.reactivate_consent_links_without_pull_evidence.

Before PR #95 the strict re-parse hid every consent link whose item it could
not find in the minutes' enumerated list. The current rule hides a link only
when the minutes also record a separate vote on the item. This repair brings
back the links the old rule hid without that evidence.
"""

from __future__ import annotations

import pytest

from docket.db import db
from docket.services.maintenance import reactivate_consent_links_without_pull_evidence


@pytest.fixture
def seed():
    created = {"meetings": [], "items": [], "votes": []}

    def meeting(*, adopted=True):
        with db() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO municipalities (slug, name, state, adapter_class, active)
                VALUES ('test_react', 'Test', 'AL', 'granicus', TRUE)
                ON CONFLICT (slug) DO UPDATE SET active = TRUE RETURNING id
            """)
            muni = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url, title,
                                      minutes_adopted_at)
                VALUES (%s, 'council', DATE '2024-03-05', 'x', 'react test',
                        CASE WHEN %s THEN NOW() ELSE NULL END)
                RETURNING id
            """, (muni, adopted))
            mid = cur.fetchone()[0]
            conn.commit()
        created["meetings"].append(mid)
        return muni, mid

    def item(mid):
        with db() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO agenda_items (meeting_id, title, is_consent) "
                        "VALUES (%s, 'consent item', TRUE) RETURNING id", (mid,))
            iid = cur.fetchone()[0]
            conn.commit()
        created["items"].append(iid)
        return iid

    def vote(mid, source="minutes_text"):
        with db() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions,
                                              confidence, needs_review)
                           VALUES (%s, %s, 'passed', 5, 0, 0, 'high', FALSE) RETURNING id""",
                        (mid, source))
            vid = cur.fetchone()[0]
            conn.commit()
        created["votes"].append(vid)
        return vid

    def link(vid, iid, *, association="consent_named", active=False, provisional=True,
             manual=False):
        with db() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO vote_agenda_items
                               (vote_id, agenda_item_id, association_type, match_method,
                                match_confidence, provisional, is_manual, is_active)
                           VALUES (%s, %s, %s, 'consent_block_named', 0.8, %s, %s, %s)
                           RETURNING id""",
                        (vid, iid, association, provisional, manual, active))
            lid = cur.fetchone()[0]
            conn.commit()
        return lid

    def state(lid):
        with db() as conn, conn.cursor() as cur:
            cur.execute("SELECT is_active, provisional FROM vote_agenda_items WHERE id = %s", (lid,))
            return cur.fetchone()

    yield type("Seed", (), {k: staticmethod(v) for k, v in
                            dict(meeting=meeting, item=item, vote=vote, link=link, state=state).items()})
    with db() as conn, conn.cursor() as cur:
        if created["votes"]:
            cur.execute("DELETE FROM vote_agenda_items WHERE vote_id = ANY(%s)", (created["votes"],))
            cur.execute("DELETE FROM votes WHERE id = ANY(%s)", (created["votes"],))
        if created["items"]:
            cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", (created["items"],))
        if created["meetings"]:
            cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", (created["meetings"],))
        cur.execute("DELETE FROM municipalities WHERE slug = 'test_react'")
        conn.commit()


def test_reactivates_hidden_consent_link_without_separate_vote(seed):
    muni, mid = seed.meeting()
    iid = seed.item(mid)
    lid = seed.link(seed.vote(mid), iid)

    result = reactivate_consent_links_without_pull_evidence(muni)

    assert seed.state(lid) == (True, False)   # back, and official (minutes adopted)
    assert result == [(mid, 1)]


def test_keeps_link_hidden_when_minutes_record_a_separate_vote(seed):
    muni, mid = seed.meeting()
    iid = seed.item(mid)
    lid = seed.link(seed.vote(mid), iid)
    seed.link(seed.vote(mid), iid, association="explicit", active=True, provisional=False)

    assert reactivate_consent_links_without_pull_evidence(muni) == []
    assert seed.state(lid) == (False, True)


def test_ocr_vote_is_not_pull_evidence(seed):
    muni, mid = seed.meeting()
    iid = seed.item(mid)
    lid = seed.link(seed.vote(mid), iid)
    seed.link(seed.vote(mid, source="video_ocr"), iid, association="explicit",
              active=True, provisional=False)

    reactivate_consent_links_without_pull_evidence(muni)

    assert seed.state(lid) == (True, False)


def test_skips_manual_links(seed):
    muni, mid = seed.meeting()
    lid = seed.link(seed.vote(mid), seed.item(mid), manual=True)

    assert reactivate_consent_links_without_pull_evidence(muni) == []
    assert seed.state(lid)[0] is False


def test_skips_meetings_whose_minutes_are_not_adopted(seed):
    muni, mid = seed.meeting(adopted=False)
    lid = seed.link(seed.vote(mid), seed.item(mid))

    assert reactivate_consent_links_without_pull_evidence(muni) == []
    assert seed.state(lid)[0] is False


def test_dry_run_reports_without_writing(seed):
    muni, mid = seed.meeting()
    lid = seed.link(seed.vote(mid), seed.item(mid))

    assert reactivate_consent_links_without_pull_evidence(muni, dry_run=True) == [(mid, 1)]
    assert seed.state(lid) == (False, True)


def test_is_idempotent(seed):
    muni, mid = seed.meeting()
    seed.link(seed.vote(mid), seed.item(mid))

    reactivate_consent_links_without_pull_evidence(muni)

    assert reactivate_consent_links_without_pull_evidence(muni) == []
