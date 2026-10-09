"""Tests for maintenance.correct_adoption_dates.

The pre-2026-10-02 adoption parser stamped some meetings with the date of an
agenda line that named other meetings. The repair re-derives, for every
meeting with a recorded adoption date, the set of agenda lines that name it;
when the recorded date matches none of them, it is replaced with the
earliest line whose meeting recorded a passed vote (the sweep's evidence
rule). Meetings whose recorded date matches a line are left alone.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from docket.db import db
from docket.services.maintenance import correct_adoption_dates


@pytest.fixture
def seed():
    created = {"meetings": [], "items": [], "votes": []}
    muni_box = {}

    def muni():
        if "id" not in muni_box:
            with db() as conn, conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO municipalities (slug, name, state, adapter_class, active)
                    VALUES ('test_adopt_fix', 'Test', 'AL', 'granicus', TRUE)
                    ON CONFLICT (slug) DO UPDATE SET active = TRUE RETURNING id
                """)
                muni_box["id"] = cur.fetchone()[0]
                conn.commit()
        return muni_box["id"]

    def target(meeting_date, *, recorded=None, minutes=True):
        with db() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url, title,
                                      minutes_url, minutes_adopted_at)
                VALUES (%s, 'council', %s, 'x', 'target', %s, %s) RETURNING id
            """, (muni(), meeting_date, "https://m" if minutes else None,
                  datetime.combine(recorded, datetime.min.time(), tzinfo=timezone.utc) if recorded else None))
            mid = cur.fetchone()[0]
            conn.commit()
        created["meetings"].append(mid)
        return mid

    def adopting(meeting_date, line, *, passed_vote=True):
        with db() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url, title)
                VALUES (%s, 'council', %s, 'x', 'adopting') RETURNING id
            """, (muni(), meeting_date))
            mid = cur.fetchone()[0]
            cur.execute("INSERT INTO agenda_items (meeting_id, title, is_consent) VALUES (%s, %s, FALSE) RETURNING id",
                        (mid, line))
            created["items"].append(cur.fetchone()[0])
            if passed_vote:
                cur.execute("""INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions, confidence, needs_review)
                               VALUES (%s, 'minutes_text', 'passed', 5, 0, 0, 'high', FALSE) RETURNING id""", (mid,))
                created["votes"].append(cur.fetchone()[0])
            conn.commit()
        created["meetings"].append(mid)
        return mid

    def recorded(mid):
        with db() as conn, conn.cursor() as cur:
            cur.execute("SELECT minutes_adopted_at::date FROM meetings WHERE id = %s", (mid,))
            return cur.fetchone()[0]

    yield type("Seed", (), {k: staticmethod(v) for k, v in
                            dict(muni=muni, target=target, adopting=adopting, recorded=recorded).items()})
    with db() as conn, conn.cursor() as cur:
        if created["votes"]:
            cur.execute("DELETE FROM votes WHERE id = ANY(%s)", (created["votes"],))
        if created["items"]:
            cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", (created["items"],))
        if created["meetings"]:
            cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", (created["meetings"],))
        cur.execute("DELETE FROM municipalities WHERE slug = 'test_adopt_fix'")
        conn.commit()


LINE = "APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: November 6 and 13, 2018"


def test_replaces_a_date_no_agenda_line_names(seed):
    """Nov 6 2018 was stamped 2019-03-26, but the only line naming it is on 2019-01-22."""
    t = seed.target(date(2018, 11, 6), recorded=date(2019, 3, 26))
    seed.adopting(date(2019, 1, 22), LINE)

    result = correct_adoption_dates(seed.muni())

    assert seed.recorded(t) == date(2019, 1, 22)
    assert result == [(t, date(2019, 3, 26), date(2019, 1, 22))]


def test_uses_the_earliest_line_with_a_passed_vote(seed):
    t = seed.target(date(2018, 11, 6), recorded=date(2019, 3, 26))
    seed.adopting(date(2019, 1, 22), LINE, passed_vote=False)   # no evidence
    seed.adopting(date(2019, 2, 5), LINE)

    correct_adoption_dates(seed.muni())

    assert seed.recorded(t) == date(2019, 2, 5)


def test_leaves_a_date_that_matches_a_line(seed):
    """Two agendas name the meeting; the recorded one is a real line, so it stands."""
    t = seed.target(date(2018, 11, 6), recorded=date(2019, 2, 5))
    seed.adopting(date(2019, 1, 22), LINE)
    seed.adopting(date(2019, 2, 5), LINE)

    assert correct_adoption_dates(seed.muni()) == []
    assert seed.recorded(t) == date(2019, 2, 5)


def test_leaves_a_wrong_date_when_no_line_has_a_vote(seed):
    t = seed.target(date(2018, 11, 6), recorded=date(2019, 3, 26))
    seed.adopting(date(2019, 1, 22), LINE, passed_vote=False)

    assert correct_adoption_dates(seed.muni()) == []
    assert seed.recorded(t) == date(2019, 3, 26)


def test_leaves_unrecorded_meetings_to_the_sweep(seed):
    t = seed.target(date(2018, 11, 6), recorded=None)
    seed.adopting(date(2019, 1, 22), LINE)

    assert correct_adoption_dates(seed.muni()) == []
    assert seed.recorded(t) is None


def test_range_line_counts_as_naming_the_meeting(seed):
    t = seed.target(date(2018, 11, 6), recorded=date(2019, 1, 22))
    seed.adopting(date(2019, 1, 22), "APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: November 6 – 27, 2018")

    assert correct_adoption_dates(seed.muni()) == []
    assert seed.recorded(t) == date(2019, 1, 22)


def test_dry_run_reports_without_writing(seed):
    t = seed.target(date(2018, 11, 6), recorded=date(2019, 3, 26))
    seed.adopting(date(2019, 1, 22), LINE)

    assert correct_adoption_dates(seed.muni(), dry_run=True) == [(t, date(2019, 3, 26), date(2019, 1, 22))]
    assert seed.recorded(t) == date(2019, 3, 26)


def test_is_idempotent(seed):
    seed.target(date(2018, 11, 6), recorded=date(2019, 3, 26))
    seed.adopting(date(2019, 1, 22), LINE)

    assert len(correct_adoption_dates(seed.muni())) == 1
    assert correct_adoption_dates(seed.muni()) == []
