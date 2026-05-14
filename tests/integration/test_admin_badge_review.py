"""Integration tests for refactor #2, Section D — /admin/badge-review queue.

The queue lists ``agenda_item_badges`` rows with ``status='flagged'`` —
badges Haiku suggested but no deterministic signal backed. Admins
approve (→ ``status='applied'``, citizen-visible) or reject (→
``status='rejected'``, archived).

Pattern mirrors test_admin_queues.py — _Bag tracker, app/client/
admin_client fixtures, Birmingham seed.
"""

from __future__ import annotations

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run D admin-badge-review tests against Railway DB.",
)


class _Bag:
    def __init__(self, city_id: int, city_slug: str):
        self.city_id = city_id
        self.city_slug = city_slug
        self.meeting_ids: list[int] = []
        self.item_ids: list[int] = []
        self.badge_ids: list[int] = []

    def add_meeting(self, meeting_date_str: str = "2026-04-15") -> int:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO meetings
                      (municipality_id, title, meeting_date, meeting_type)
                    VALUES (%s, 'D admin badge review test', %s, 'council')
                    RETURNING id
                    """,
                    (self.city_id, meeting_date_str),
                )
                mid = cur.fetchone()[0]
        self.meeting_ids.append(mid)
        return mid

    def add_item(self, meeting_id: int, *, title: str = "Flagged badge item") -> int:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agenda_items
                      (meeting_id, title, processing_status)
                    VALUES (%s, %s, 'completed'::processing_status_enum)
                    RETURNING id
                    """,
                    (meeting_id, title),
                )
                iid = cur.fetchone()[0]
        self.item_ids.append(iid)
        return iid

    def add_badge(
        self,
        item_id: int,
        badge_slug: str,
        *,
        status: str = "flagged",
        source: str = "llm",
        confidence: float = 0.4,
    ) -> int:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT kind FROM priority_badge_templates WHERE slug = %s",
                    (badge_slug,),
                )
                kind = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO agenda_item_badges
                      (agenda_item_id, city_id, badge_slug, kind,
                       confidence, source, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (item_id, self.city_id, badge_slug, kind,
                     confidence, source, status),
                )
                bid = cur.fetchone()[0]
        self.badge_ids.append(bid)
        return bid

    def cleanup(self) -> None:
        with db() as conn:
            with conn.cursor() as cur:
                if self.item_ids:
                    cur.execute(
                        "DELETE FROM agenda_item_badges_audit "
                        "WHERE agenda_item_id = ANY(%s)",
                        (self.item_ids,),
                    )
                    cur.execute(
                        "DELETE FROM agenda_item_badges "
                        "WHERE agenda_item_id = ANY(%s)",
                        (self.item_ids,),
                    )
                    cur.execute(
                        "DELETE FROM agenda_items WHERE id = ANY(%s)",
                        (self.item_ids,),
                    )
                if self.meeting_ids:
                    cur.execute(
                        "DELETE FROM meetings WHERE id = ANY(%s)",
                        (self.meeting_ids,),
                    )


def _bag_for(city_slug: str = "birmingham") -> _Bag:
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, slug FROM municipalities WHERE slug = %s",
                (city_slug,),
            )
            row = cur.fetchone()
    assert row is not None, f"City must be seeded: {city_slug}"
    return _Bag(row[0], row[1])


@pytest.fixture
def bag():
    b = _bag_for("birmingham")
    try:
        yield b
    finally:
        b.cleanup()


@pytest.fixture(scope="module")
def app():
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["SECRET_KEY"] = "test-secret-key-D"
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_client(app):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["admin_user"] = "tester"
    return c


# ---------------------------------------------------------------------------
# D.1 — list view: auth gate + table render
# ---------------------------------------------------------------------------


def test_review_view_requires_login(client):
    """Anonymous request → 302/303 redirect to /admin/login with next=."""
    rv = client.get("/admin/badge-review")
    assert rv.status_code in (301, 302, 303, 308)
    location = rv.headers.get("Location", "")
    assert "/admin/login" in location
    assert "next=" in location


def test_review_view_lists_flagged_badges(admin_client, bag):
    """Logged-in admin GETs /admin/badge-review; queue lists flagged
    rows with the badge slug + item title + city."""
    m = bag.add_meeting("2026-04-15")
    iid = bag.add_item(m, title="Mis-tagged blight item")
    bag.add_badge(iid, "blight_accountability", status="flagged",
                  source="llm", confidence=0.4)

    rv = admin_client.get("/admin/badge-review")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "blight_accountability" in body
    assert "Mis-tagged blight item" in body


def test_review_view_excludes_applied_badges(admin_client, bag):
    """status='applied' badges must NOT appear in the review queue —
    they're already citizen-visible, no triage needed."""
    m = bag.add_meeting("2026-04-15")
    iid = bag.add_item(m, title="Real blight item")
    bag.add_badge(iid, "blight_accountability", status="applied",
                  source="deterministic", confidence=1.0)

    rv = admin_client.get("/admin/badge-review")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Real blight item" not in body


def test_review_view_excludes_rejected_badges(admin_client, bag):
    """status='rejected' badges are archived for audit and don't render."""
    m = bag.add_meeting("2026-04-15")
    iid = bag.add_item(m, title="Already-rejected item")
    bag.add_badge(iid, "blight_accountability", status="rejected",
                  source="llm", confidence=0.4)

    rv = admin_client.get("/admin/badge-review")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Already-rejected item" not in body


# ---------------------------------------------------------------------------
# D.2 — approve / reject actions
# ---------------------------------------------------------------------------


def test_approve_promotes_badge_to_applied(admin_client, bag):
    """POST /admin/badge-review/<id>/approve flips status to 'applied'
    and writes an audit row with action='approved'."""
    m = bag.add_meeting("2026-04-15")
    iid = bag.add_item(m, title="Pending approval item")
    badge_id = bag.add_badge(iid, "blight_accountability",
                             status="flagged", source="llm", confidence=0.4)

    rv = admin_client.post(f"/admin/badge-review/{badge_id}/approve")
    assert rv.status_code == 200

    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM agenda_item_badges WHERE id = %s",
            (badge_id,),
        )
        assert cur.fetchone()[0] == "applied"
        cur.execute(
            """SELECT action, actor, actor_role FROM agenda_item_badges_audit
                WHERE agenda_item_id = %s AND badge_slug = 'blight_accountability'""",
            (iid,),
        )
        audit = cur.fetchone()
    assert audit is not None
    assert audit[0] == "approved"
    assert audit[1] == "tester"
    assert audit[2] == "admin"


def test_reject_marks_badge_rejected(admin_client, bag):
    """POST /admin/badge-review/<id>/reject flips status to 'rejected'
    and writes an audit row."""
    m = bag.add_meeting("2026-04-15")
    iid = bag.add_item(m, title="Pending rejection item")
    badge_id = bag.add_badge(iid, "blight_accountability",
                             status="flagged", source="llm", confidence=0.4)

    rv = admin_client.post(f"/admin/badge-review/{badge_id}/reject")
    assert rv.status_code == 200

    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM agenda_item_badges WHERE id = %s",
            (badge_id,),
        )
        assert cur.fetchone()[0] == "rejected"
        cur.execute(
            """SELECT action FROM agenda_item_badges_audit
                WHERE agenda_item_id = %s AND badge_slug = 'blight_accountability'""",
            (iid,),
        )
        assert cur.fetchone()[0] == "rejected"


def test_approve_returns_empty_body_for_htmx_swap(admin_client, bag):
    """HTMX swap removes the row from the queue via outerHTML swap, so
    the approve/reject endpoints return an empty body."""
    m = bag.add_meeting("2026-04-15")
    iid = bag.add_item(m, title="HTMX swap target")
    badge_id = bag.add_badge(iid, "blight_accountability",
                             status="flagged", source="llm", confidence=0.4)

    rv = admin_client.post(f"/admin/badge-review/{badge_id}/approve")
    assert rv.status_code == 200
    assert rv.get_data(as_text=True) == ""


def test_approve_404_for_unknown_badge(admin_client):
    """POST against a badge id that doesn't exist → 404."""
    rv = admin_client.post("/admin/badge-review/99999999/approve")
    assert rv.status_code == 404


# ---------------------------------------------------------------------------
# D.3 — concurrency guard (refactor #2 retro [MEDIUM #3])
#
# Two admins acting on the same flagged badge must not both succeed: the
# second action must see 409 Conflict and write no audit row. The fix is
# a status='flagged' predicate on the UPDATE; we simulate the race by
# pre-seeding a badge in the post-action state and posting against it.
# ---------------------------------------------------------------------------


def test_approve_returns_409_when_badge_already_applied(admin_client, bag):
    """Race: admin A already approved this badge (status='applied').
    Admin B's approve must 409 and not write a duplicate audit row."""
    m = bag.add_meeting("2026-04-15")
    iid = bag.add_item(m, title="Already-approved race target")
    badge_id = bag.add_badge(iid, "blight_accountability",
                             status="applied", source="llm", confidence=0.4)

    rv = admin_client.post(f"/admin/badge-review/{badge_id}/approve")
    assert rv.status_code == 409

    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM agenda_item_badges WHERE id = %s",
            (badge_id,),
        )
        assert cur.fetchone()[0] == "applied"  # unchanged
        cur.execute(
            """SELECT count(*) FROM agenda_item_badges_audit
                WHERE agenda_item_id = %s""",
            (iid,),
        )
        assert cur.fetchone()[0] == 0, \
            "409 path must not write an audit row"


def test_approve_returns_409_when_badge_already_rejected(admin_client, bag):
    """Race: admin A rejected; admin B's approve must 409 (you can't
    silently un-reject — needs a deliberate re-flag flow if ever wanted)."""
    m = bag.add_meeting("2026-04-15")
    iid = bag.add_item(m, title="Already-rejected race target")
    badge_id = bag.add_badge(iid, "blight_accountability",
                             status="rejected", source="llm", confidence=0.4)

    rv = admin_client.post(f"/admin/badge-review/{badge_id}/approve")
    assert rv.status_code == 409

    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM agenda_item_badges WHERE id = %s",
            (badge_id,),
        )
        assert cur.fetchone()[0] == "rejected"
        cur.execute(
            """SELECT count(*) FROM agenda_item_badges_audit
                WHERE agenda_item_id = %s""",
            (iid,),
        )
        assert cur.fetchone()[0] == 0


def test_reject_returns_409_when_badge_already_rejected(admin_client, bag):
    """Race: admin A rejected; admin B's reject must 409."""
    m = bag.add_meeting("2026-04-15")
    iid = bag.add_item(m, title="Double-reject race target")
    badge_id = bag.add_badge(iid, "blight_accountability",
                             status="rejected", source="llm", confidence=0.4)

    rv = admin_client.post(f"/admin/badge-review/{badge_id}/reject")
    assert rv.status_code == 409

    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT count(*) FROM agenda_item_badges_audit
                WHERE agenda_item_id = %s""",
            (iid,),
        )
        assert cur.fetchone()[0] == 0


def test_reject_returns_409_when_badge_already_applied(admin_client, bag):
    """Race: admin A approved; admin B's reject must 409 (won't quietly
    flip an applied badge back to rejected — needs explicit re-flag)."""
    m = bag.add_meeting("2026-04-15")
    iid = bag.add_item(m, title="Applied-then-reject race target")
    badge_id = bag.add_badge(iid, "blight_accountability",
                             status="applied", source="llm", confidence=0.4)

    rv = admin_client.post(f"/admin/badge-review/{badge_id}/reject")
    assert rv.status_code == 409

    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM agenda_item_badges WHERE id = %s",
            (badge_id,),
        )
        assert cur.fetchone()[0] == "applied"


def test_approve_requires_login(client, bag):
    """Anonymous POST → redirect to login."""
    m = bag.add_meeting("2026-04-15")
    iid = bag.add_item(m, title="Login-required item")
    badge_id = bag.add_badge(iid, "blight_accountability",
                             status="flagged", source="llm", confidence=0.4)

    rv = client.post(f"/admin/badge-review/{badge_id}/approve")
    assert rv.status_code in (301, 302, 303, 308)
    assert "/admin/login" in rv.headers.get("Location", "")
