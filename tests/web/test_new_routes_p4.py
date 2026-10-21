"""Route smoke tests for P4-2 — member_detail + source_health.

Verifies 200 OK, 404 behavior, and cross-city tamper guard. Heavy data
assertions live in the query-helper unit tests; these tests just confirm
the routes wire together end-to-end.
"""

from __future__ import annotations

import pytest
import psycopg2.extras

from docket.db import db


def _cleanup() -> None:
    with db() as conn:
        with conn.cursor() as cur:
            # Meetings first: votes and member votes cascade from meetings, but
            # meetings.municipality_id does not cascade from municipalities.
            cur.execute("DELETE FROM meetings WHERE title LIKE 'TEST_P4_%'")
            cur.execute("DELETE FROM council_members WHERE name LIKE 'TEST_P4_%'")
            cur.execute("DELETE FROM municipalities WHERE slug LIKE 'p4test_%'")
        conn.commit()


@pytest.fixture
def two_cities_with_members():
    """Create 2 test cities + 1 member each. Returns dict with ids/slugs."""
    _cleanup()
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO municipalities (slug, name, state, adapter_class, active)
                   VALUES ('p4test_alpha', 'Alpha', 'AL', 'docket.adapters.granicus.GranicusAdapter', TRUE),
                          ('p4test_beta',  'Beta',  'AL', 'docket.adapters.granicus.GranicusAdapter', TRUE)
                   RETURNING id, slug""",
            )
            cities = {r["slug"]: r["id"] for r in cur.fetchall()}
            cur.execute(
                """INSERT INTO council_members (municipality_id, name, active)
                   VALUES (%s, 'TEST_P4_Alpha Member', TRUE),
                          (%s, 'TEST_P4_Beta Member',  TRUE)
                   RETURNING id, municipality_id""",
                (cities["p4test_alpha"], cities["p4test_beta"]),
            )
            mrows = cur.fetchall()
        conn.commit()
    members = {r["municipality_id"]: r["id"] for r in mrows}
    yield {
        "alpha_slug": "p4test_alpha",
        "beta_slug":  "p4test_beta",
        "alpha_id":   cities["p4test_alpha"],
        "beta_id":    cities["p4test_beta"],
        "alpha_member_id": members[cities["p4test_alpha"]],
        "beta_member_id":  members[cities["p4test_beta"]],
    }
    _cleanup()


def _seed_one_vote(fx) -> int:
    """Insert into the alpha city one council meeting ``TEST_P4_meeting``
    (2099-01-01) holding one ``minutes_text`` vote that passed 1 to 0 and one
    member vote (``yea``) for the alpha member; return the meeting id."""
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   VALUES (%s, 'TEST_P4_meeting', '2099-01-01', 'council') RETURNING id""",
                (fx["alpha_id"],),
            )
            meeting_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions,
                                       confidence, needs_review)
                   VALUES (%s, 'minutes_text', 'passed', 1, 0, 0, 'high', FALSE) RETURNING id""",
                (meeting_id,),
            )
            vote_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO member_votes (vote_id, council_member_id, member_name, position)
                   VALUES (%s, %s, 'TEST_P4_Alpha Member', 'yea')""",
                (vote_id, fx["alpha_member_id"]),
            )
        conn.commit()
    return meeting_id


def test_member_detail_200(client, two_cities_with_members):
    fx = two_cities_with_members
    resp = client.get(f"/al/{fx['alpha_slug']}/council/{fx['alpha_member_id']}/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "TEST_P4_Alpha Member" in body


def test_member_detail_shows_source_column_and_count_note(client, two_cities_with_members):
    """Plan member-page-counts-one-source, M2: each vote row shows its source
    in its own column in the meeting page's words, the note under the stat
    strip states the counting rule, and the one minutes vote counts once."""
    fx = two_cities_with_members
    _seed_one_vote(fx)
    resp = client.get(f"/al/{fx['alpha_slug']}/council/{fx['alpha_member_id']}/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'class="member-history-source t-meta">official minutes<' in body
    assert (
        "Counted from the official minutes where a meeting has them "
        "and from video OCR otherwise"
    ) in body
    assert "1 roll calls" in body


def test_member_detail_404_unknown_member(client, two_cities_with_members):
    fx = two_cities_with_members
    resp = client.get(f"/al/{fx['alpha_slug']}/council/9999999/")
    assert resp.status_code == 404


def test_member_detail_404_unknown_city(client, two_cities_with_members):
    fx = two_cities_with_members
    resp = client.get(f"/al/no_such_city/council/{fx['alpha_member_id']}/")
    assert resp.status_code == 404


def test_member_detail_404_cross_city_tampering(client, two_cities_with_members):
    """Beta member URL'd under Alpha city slug must 404, not leak."""
    fx = two_cities_with_members
    resp = client.get(f"/al/{fx['alpha_slug']}/council/{fx['beta_member_id']}/")
    assert resp.status_code == 404


def test_member_detail_filter_dissent(client, two_cities_with_members):
    fx = two_cities_with_members
    resp = client.get(
        f"/al/{fx['alpha_slug']}/council/{fx['alpha_member_id']}/?filter=dissent"
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # filter chip should mark Dissent as active
    assert "is-active" in body


def test_member_detail_filter_sponsored(client, two_cities_with_members):
    fx = two_cities_with_members
    resp = client.get(
        f"/al/{fx['alpha_slug']}/council/{fx['alpha_member_id']}/?filter=sponsored"
    )
    assert resp.status_code == 200


def test_member_detail_invalid_filter_falls_back_to_all(client, two_cities_with_members):
    fx = two_cities_with_members
    resp = client.get(
        f"/al/{fx['alpha_slug']}/council/{fx['alpha_member_id']}/?filter=garbage"
    )
    assert resp.status_code == 200


def test_source_health_200(client, two_cities_with_members):
    fx = two_cities_with_members
    resp = client.get(f"/al/{fx['alpha_slug']}/source-health/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # 4-stage pipeline rendered
    assert "Source" in body
    assert "Adapter" in body
    assert "Parser" in body
    assert "Index" in body


def test_source_health_404_unknown_city(client):
    resp = client.get("/al/no_such_city_xyz/source-health/")
    assert resp.status_code == 404


def test_source_health_renders_adapter_class(client, two_cities_with_members):
    """The Alpha test city was inserted with GranicusAdapter — verify it surfaces."""
    fx = two_cities_with_members
    resp = client.get(f"/al/{fx['alpha_slug']}/source-health/")
    body = resp.get_data(as_text=True)
    assert "GranicusAdapter" in body
