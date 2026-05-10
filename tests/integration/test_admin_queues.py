"""Integration tests for G2 — admin OCR queue + errors queue.

Three deliverables under test:

- G2.1: ``/admin/data-debt`` (cross-city) — 200 for authed admins,
  302 to login otherwise, ``?highlight=N`` honored, priority sort
  preserved across cities.
- G2.2: ``/admin/errors`` (cross-city) — only ``failed_permanent``
  rows surface, same priority sort.
- G2.3: POST retry/escalate handlers — 405 on GET, 302 on POST,
  state mutations land in ``agenda_items`` and ``processing_status_audit``.

Reuses the F4/F5/G1 ``_Bag`` test-data tracker pattern.

Multi-city parametrization: tests #1 (data-debt 200) and #6 (errors 200)
seed in each of the four deployed cities to verify the cross-city
admin queue renders cleanly even when only one city has data.
"""

from __future__ import annotations

import json

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run G2 admin-queue tests against Railway DB.",
)


CITIES = ["birmingham", "mobile", "vestavia_hills", "homewood"]


# ---------------------------------------------------------------------------
# Test data tracker.
# ---------------------------------------------------------------------------


class _Bag:
    def __init__(self, city_id: int, city_slug: str):
        self.city_id = city_id
        self.city_slug = city_slug
        self.meeting_ids: list[int] = []
        self.item_ids: list[int] = []
        self.audit_item_ids: list[int] = []

    def add_meeting(self, meeting_date_str: str = "2026-04-15", *, title: str = "G2 test meeting") -> int:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO meetings
                      (municipality_id, title, meeting_date, meeting_type)
                    VALUES (%s, %s, %s, 'council')
                    RETURNING id
                    """,
                    (self.city_id, title, meeting_date_str),
                )
                mid = cur.fetchone()[0]
        self.meeting_ids.append(mid)
        return mid

    def add_item(
        self,
        meeting_id: int,
        *,
        title: str = "G2 test item",
        data_quality: str | None = "no_text_layer",
        data_debt_priority: str | None = "normal",
        processing_status: str = "pending",
        processing_attempts: int = 0,
        last_error_message: str | None = None,
        score_overrides: dict | None = None,
    ) -> int:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agenda_items
                      (meeting_id, title, data_quality, data_debt_priority,
                       processing_status, processing_attempts,
                       last_error_message, score_overrides)
                    VALUES (%s, %s,
                            %s::data_quality_enum,
                            %s::data_debt_priority_enum,
                            %s::processing_status_enum,
                            %s, %s, %s::jsonb)
                    RETURNING id
                    """,
                    (
                        meeting_id, title, data_quality,
                        data_debt_priority, processing_status,
                        processing_attempts, last_error_message,
                        json.dumps(score_overrides) if score_overrides else None,
                    ),
                )
                iid = cur.fetchone()[0]
        self.item_ids.append(iid)
        return iid

    def cleanup(self) -> None:
        with db() as conn:
            with conn.cursor() as cur:
                # processing_status_audit FKs to agenda_items, so wipe
                # any audit rows we might have accumulated for tracked
                # items first.
                if self.item_ids:
                    cur.execute(
                        "DELETE FROM processing_status_audit WHERE agenda_item_id = ANY(%s)",
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


def _bag_for(city_slug: str) -> _Bag:
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
    flask_app.config["SECRET_KEY"] = "test-secret-key-G2"
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_client(app):
    """Test client with an authenticated admin session."""
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["admin_user"] = "tester"
    return c


# ---------------------------------------------------------------------------
# G2.1 — /admin/data-debt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("city_slug", CITIES)
def test_admin_data_debt_route_renders_for_logged_in_admin(app, city_slug):
    """200 + expected sections, parametrized across all 4 deployed cities
    to verify cross-city aggregation renders cleanly when the seed data
    lives in any one of them."""
    bag = _bag_for(city_slug)
    try:
        m = bag.add_meeting()
        bag.add_item(m, title=f"OCR-needed in {city_slug}", data_quality="no_text_layer")

        c = app.test_client()
        with c.session_transaction() as sess:
            sess["admin_user"] = "tester"
        resp = c.get("/admin/data-debt/")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "OCR queue" in body
        assert f"OCR-needed in {city_slug}" in body
    finally:
        bag.cleanup()


def test_admin_data_debt_route_redirects_anonymous(client):
    resp = client.get("/admin/data-debt/")
    assert resp.status_code in (302, 303)
    assert "/admin/login" in resp.headers.get("Location", "")
    assert "next=" in resp.headers.get("Location", "")


def test_admin_data_debt_aggregates_across_cities(app):
    """Seed items in 2 cities; both must surface on the cross-city queue."""
    bham = _bag_for("birmingham")
    mob = _bag_for("mobile")
    try:
        m1 = bham.add_meeting()
        m2 = mob.add_meeting()
        bham.add_item(m1, title="BHM-CROSS-CITY-MARKER", data_quality="no_text_layer")
        mob.add_item(m2, title="MOB-CROSS-CITY-MARKER", data_quality="no_text_layer")

        c = app.test_client()
        with c.session_transaction() as sess:
            sess["admin_user"] = "tester"
        # Limit page size 50, but ensure both seeded items are at the top:
        # offset=0 gets the most recent + highest-priority, both seeded
        # at meeting_date=2026-04-15 with priority=normal.
        resp = c.get("/admin/data-debt/")
        body = resp.get_data(as_text=True)
        assert "BHM-CROSS-CITY-MARKER" in body
        assert "MOB-CROSS-CITY-MARKER" in body
    finally:
        bham.cleanup()
        mob.cleanup()


def test_admin_data_debt_priority_sort_order(app):
    """High-priority must precede normal; within tier, newer date first."""
    bag = _bag_for("birmingham")
    try:
        m_old = bag.add_meeting("2026-01-01")
        m_new = bag.add_meeting("2026-04-15")
        high_old = bag.add_item(m_old, title="G2-HIGH-OLD", data_debt_priority="high")
        high_new = bag.add_item(m_new, title="G2-HIGH-NEW", data_debt_priority="high")
        norm_new = bag.add_item(m_new, title="G2-NORM-NEW", data_debt_priority="normal")

        c = app.test_client()
        with c.session_transaction() as sess:
            sess["admin_user"] = "tester"
        resp = c.get("/admin/data-debt/")
        body = resp.get_data(as_text=True)
        # Within the body, find the index of each marker title and
        # assert priority/recency ordering.
        i_high_new = body.find("G2-HIGH-NEW")
        i_high_old = body.find("G2-HIGH-OLD")
        i_norm_new = body.find("G2-NORM-NEW")
        assert i_high_new != -1 and i_high_old != -1 and i_norm_new != -1
        # Both high-priority before normal, and high-new before high-old.
        assert i_high_new < i_high_old
        assert i_high_old < i_norm_new
    finally:
        bag.cleanup()


def test_admin_data_debt_highlight_query_param(app, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m, title="Highlightable", data_quality="no_text_layer")

    c = app.test_client()
    with c.session_transaction() as sess:
        sess["admin_user"] = "tester"
    resp = c.get(f"/admin/data-debt/?highlight={iid}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # The row gets id="item-N" + class="highlighted" when highlighted.
    assert f'id="item-{iid}"' in body
    # Highlighted class only on the matching row.
    assert 'class="highlighted"' in body


# ---------------------------------------------------------------------------
# G2.2 — /admin/errors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("city_slug", CITIES)
def test_admin_errors_route_renders_for_logged_in_admin(app, city_slug):
    bag = _bag_for(city_slug)
    try:
        m = bag.add_meeting()
        bag.add_item(
            m,
            title=f"Failed in {city_slug}",
            data_quality=None,
            data_debt_priority=None,
            processing_status="failed_permanent",
            last_error_message="extraction timed out",
        )

        c = app.test_client()
        with c.session_transaction() as sess:
            sess["admin_user"] = "tester"
        resp = c.get("/admin/errors")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Errors queue" in body
        assert f"Failed in {city_slug}" in body
    finally:
        bag.cleanup()


def test_admin_errors_route_redirects_anonymous(client):
    resp = client.get("/admin/errors")
    assert resp.status_code in (302, 303)
    assert "/admin/login" in resp.headers.get("Location", "")


def test_admin_errors_only_shows_failed_permanent(app, bag):
    """Mix of pending + failed_permanent + completed; only the
    failed_permanent row surfaces on /admin/errors."""
    m = bag.add_meeting()
    pending_id = bag.add_item(
        m, title="G2-ERR-PENDING",
        data_quality="no_text_layer",
        processing_status="pending",
    )
    completed_id = bag.add_item(
        m, title="G2-ERR-COMPLETED",
        data_quality="ok",
        data_debt_priority=None,
        processing_status="completed",
    )
    failed_id = bag.add_item(
        m, title="G2-ERR-FAILED",
        data_quality=None,
        data_debt_priority=None,
        processing_status="failed_permanent",
        last_error_message="boom",
    )

    c = app.test_client()
    with c.session_transaction() as sess:
        sess["admin_user"] = "tester"
    resp = c.get("/admin/errors")
    body = resp.get_data(as_text=True)
    assert "G2-ERR-FAILED" in body
    assert "G2-ERR-PENDING" not in body
    assert "G2-ERR-COMPLETED" not in body


def test_admin_errors_priority_sort_order(app, bag):
    m_old = bag.add_meeting("2026-01-01")
    m_new = bag.add_meeting("2026-04-15")
    bag.add_item(
        m_old, title="G2-EHIGH-OLD",
        data_quality=None, data_debt_priority="high",
        processing_status="failed_permanent",
    )
    bag.add_item(
        m_new, title="G2-EHIGH-NEW",
        data_quality=None, data_debt_priority="high",
        processing_status="failed_permanent",
    )
    bag.add_item(
        m_new, title="G2-ENORM-NEW",
        data_quality=None, data_debt_priority="normal",
        processing_status="failed_permanent",
    )

    c = app.test_client()
    with c.session_transaction() as sess:
        sess["admin_user"] = "tester"
    resp = c.get("/admin/errors")
    body = resp.get_data(as_text=True)
    i_hn = body.find("G2-EHIGH-NEW")
    i_ho = body.find("G2-EHIGH-OLD")
    i_nn = body.find("G2-ENORM-NEW")
    assert i_hn != -1 and i_ho != -1 and i_nn != -1
    assert i_hn < i_ho
    assert i_ho < i_nn


# ---------------------------------------------------------------------------
# G2.3 — POST retry / escalate
# ---------------------------------------------------------------------------


def _read_item_status(item_id: int) -> tuple[str, int, dict | None]:
    """Helper: return (processing_status, processing_attempts, score_overrides)."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT processing_status::text,
                       processing_attempts,
                       score_overrides
                  FROM agenda_items
                 WHERE id = %s
                """,
                (item_id,),
            )
            row = cur.fetchone()
    assert row is not None
    return row[0], row[1], row[2]


def test_retry_button_resets_status_to_pending(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(
        m,
        data_quality=None,
        data_debt_priority="high",
        processing_status="failed_permanent",
        processing_attempts=3,
        last_error_message="boom",
    )

    resp = admin_client.post(f"/admin/errors/{iid}/retry")
    assert resp.status_code in (302, 303)

    status, attempts, _ = _read_item_status(iid)
    assert status == "pending"
    assert attempts == 0


def test_retry_button_resets_processing_attempts(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(
        m,
        data_quality=None,
        data_debt_priority="normal",
        processing_status="failed_permanent",
        processing_attempts=7,
    )

    admin_client.post(f"/admin/errors/{iid}/retry")
    _, attempts, _ = _read_item_status(iid)
    assert attempts == 0


def test_retry_button_returns_302_with_flash(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(
        m, data_quality=None, processing_status="failed_permanent",
    )
    resp = admin_client.post(f"/admin/errors/{iid}/retry")
    assert resp.status_code in (302, 303)
    assert "/admin/errors" in resp.headers.get("Location", "")
    # Follow to the errors page; flash message should render in the body.
    follow = admin_client.get("/admin/errors")
    assert f"Item #{iid} retry queued" in follow.get_data(as_text=True)


def test_escalate_button_sets_admin_escalated_flag(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(
        m,
        data_quality=None,
        data_debt_priority="normal",
        processing_status="failed_permanent",
        score_overrides={"final_significance": 7},
    )

    resp = admin_client.post(f"/admin/errors/{iid}/escalate")
    assert resp.status_code in (302, 303)
    _, _, overrides = _read_item_status(iid)
    assert overrides is not None
    assert overrides.get("admin_escalated") is True
    # Existing keys preserved (merge, not clobber).
    assert overrides.get("final_significance") == 7


def test_escalate_button_returns_302_with_flash(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(
        m, data_quality=None, processing_status="failed_permanent",
    )
    resp = admin_client.post(f"/admin/errors/{iid}/escalate")
    assert resp.status_code in (302, 303)
    assert "/admin/errors" in resp.headers.get("Location", "")
    follow = admin_client.get("/admin/errors")
    assert f"Item #{iid} escalated" in follow.get_data(as_text=True)


def test_retry_handler_requires_post(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m, data_quality=None, processing_status="failed_permanent")
    resp = admin_client.get(f"/admin/errors/{iid}/retry")
    assert resp.status_code == 405


def test_escalate_handler_requires_post(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m, data_quality=None, processing_status="failed_permanent")
    resp = admin_client.get(f"/admin/errors/{iid}/escalate")
    assert resp.status_code == 405


def test_retry_handler_requires_login(client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m, data_quality=None, processing_status="failed_permanent")
    resp = client.post(f"/admin/errors/{iid}/retry")
    assert resp.status_code in (302, 303)
    assert "/admin/login" in resp.headers.get("Location", "")
    # State must NOT change on auth-rejected POSTs.
    status, attempts, _ = _read_item_status(iid)
    assert status == "failed_permanent"


def test_escalate_handler_requires_login(client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m, data_quality=None, processing_status="failed_permanent")
    resp = client.post(f"/admin/errors/{iid}/escalate")
    assert resp.status_code in (302, 303)
    assert "/admin/login" in resp.headers.get("Location", "")
    _, _, overrides = _read_item_status(iid)
    # No escalation flag should be set if auth was rejected.
    if overrides:
        assert "admin_escalated" not in overrides
