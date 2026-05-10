"""Integration tests for G3 — agenda_item_badges_audit log viewer +
manual badge add/remove HTMX endpoints.

Three deliverables under test:

- G3.1: ``query.list_badge_audit_log`` — filterable read helper.
- G3.2: ``/admin/badges/audit`` — viewer page (filters via ?badge_slug=
  & ?actor= & ?since= & ?until=, pagination via ?offset=).
- G3.3: ``/admin/badges/items/<id>`` + ``POST /admin/badges/<id>/add/<slug>``
  + ``POST /admin/badges/<id>/remove/<slug>`` — HTMX endpoints writing
  badge + audit row in one transaction. Decision #92: city_id required
  on every INSERT into agenda_item_badges.

Reuses the G2 ``_Bag`` test-data tracker pattern (self-contained — does
NOT import from tests.integration.test_admin_queues).
"""

from __future__ import annotations

import json

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run G3 admin-badge-audit tests against Railway DB.",
)


CITIES = ["birmingham", "mobile", "vestavia_hills", "homewood"]


class _Bag:
    """Test-data tracker. Cleans up in FK order: audit → badges → items
    → meetings (audit_item_ids covers ad-hoc audit rows seeded by viewer
    tests; the per-item audit rows the HTMX endpoints write get caught
    by the ON DELETE CASCADE on items, but agenda_item_badges_audit's
    agenda_item_id FK has no CASCADE — see migration 013:144 — so we
    DELETE explicitly)."""

    def __init__(self, city_id: int, city_slug: str):
        self.city_id = city_id
        self.city_slug = city_slug
        self.meeting_ids: list[int] = []
        self.item_ids: list[int] = []

    def add_meeting(self, meeting_date_str: str = "2026-04-15") -> int:
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO meetings
                  (municipality_id, title, meeting_date, meeting_type)
                VALUES (%s, %s, %s, 'council')
                RETURNING id
                """,
                (self.city_id, "G3 test meeting", meeting_date_str),
            )
            mid = cur.fetchone()[0]
        self.meeting_ids.append(mid)
        return mid

    def add_item(self, meeting_id: int, *, title: str = "G3 test item") -> int:
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agenda_items (meeting_id, title)
                VALUES (%s, %s)
                RETURNING id
                """,
                (meeting_id, title),
            )
            iid = cur.fetchone()[0]
        self.item_ids.append(iid)
        return iid

    def add_badge(self, item_id: int, slug: str, *, kind: str = "policy",
                   source: str = "llm", confidence: float = 0.8) -> None:
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agenda_item_badges
                  (agenda_item_id, city_id, badge_slug, kind, confidence,
                   source, matching_metadata)
                VALUES (%s, %s, %s, %s, %s, %s, '{}'::jsonb)
                """,
                (item_id, self.city_id, slug, kind, confidence, source),
            )

    def add_audit(self, item_id: int, slug: str, action: str, *,
                   actor: str = "tester", actor_role: str = "admin",
                   reason: str | None = None,
                   occurred_at: str | None = None) -> None:
        """Seed an audit row directly (for viewer tests). occurred_at
        accepts an ISO string; NULL → DEFAULT NOW()."""
        with db() as conn, conn.cursor() as cur:
            if occurred_at is None:
                cur.execute(
                    """
                    INSERT INTO agenda_item_badges_audit
                      (agenda_item_id, badge_slug, action, actor,
                       actor_role, reason)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (item_id, slug, action, actor, actor_role, reason),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO agenda_item_badges_audit
                      (agenda_item_id, badge_slug, action, actor,
                       actor_role, reason, occurred_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::timestamptz)
                    """,
                    (item_id, slug, action, actor, actor_role, reason,
                     occurred_at),
                )

    def cleanup(self) -> None:
        with db() as conn, conn.cursor() as cur:
            if self.item_ids:
                # Audit rows have no CASCADE; clean explicitly.
                cur.execute(
                    "DELETE FROM agenda_item_badges_audit "
                    "WHERE agenda_item_id = ANY(%s)",
                    (self.item_ids,),
                )
                # Badges CASCADE on items, but be explicit anyway for
                # readers of the cleanup chain.
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


def _bag_for(city_slug: str) -> _Bag:
    with db() as conn, conn.cursor() as cur:
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
    flask_app.config["SECRET_KEY"] = "test-secret-key-G3"
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
# G3.1 — query.list_badge_audit_log
# ---------------------------------------------------------------------------


def test_list_badge_audit_log_returns_recent_rows_first(bag):
    """Newest occurred_at first — typical 'recent activity' view."""
    from docket.services import query

    m = bag.add_meeting()
    iid = bag.add_item(m)
    bag.add_audit(iid, "split_vote", "added",
                   occurred_at="2026-04-01T12:00:00Z")
    bag.add_audit(iid, "split_vote", "removed",
                   occurred_at="2026-04-15T12:00:00Z")

    rows = query.list_badge_audit_log(limit=10, offset=0)

    # We expect both rows in result; rows for our test item come back
    # newest-first.
    ours = [r for r in rows if r["agenda_item_id"] == iid]
    assert len(ours) == 2
    assert ours[0]["action"] == "removed"
    assert ours[1]["action"] == "added"


from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CDT = ZoneInfo("America/Chicago")


def _local_start_of_day(date_str: str) -> datetime:
    """YYYY-MM-DD → 00:00 CDT/CST on that date (timezone-aware)."""
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    return datetime(d.year, d.month, d.day, tzinfo=CDT)


def test_list_badge_audit_log_filters_by_badge_slug(bag):
    from docket.services import query
    m = bag.add_meeting()
    iid = bag.add_item(m)
    bag.add_audit(iid, "split_vote", "added")
    bag.add_audit(iid, "contested", "added")

    rows = query.list_badge_audit_log(badge_slug="contested", limit=10)
    ours = [r for r in rows if r["agenda_item_id"] == iid]
    assert len(ours) == 1
    assert ours[0]["badge_slug"] == "contested"


def test_list_badge_audit_log_filters_by_actor(bag):
    from docket.services import query
    m = bag.add_meeting()
    iid = bag.add_item(m)
    bag.add_audit(iid, "split_vote", "added", actor="alice")
    bag.add_audit(iid, "split_vote", "removed", actor="bob")

    rows = query.list_badge_audit_log(actor="alice", limit=10)
    ours = [r for r in rows if r["agenda_item_id"] == iid]
    assert len(ours) == 1
    assert ours[0]["actor"] == "alice"


def test_list_badge_audit_log_filters_by_since(bag):
    from docket.services import query
    m = bag.add_meeting()
    iid = bag.add_item(m)
    bag.add_audit(iid, "split_vote", "added",
                   occurred_at="2026-03-01T00:00:00Z")
    bag.add_audit(iid, "split_vote", "removed",
                   occurred_at="2026-04-15T00:00:00Z")

    rows = query.list_badge_audit_log(
        since=_local_start_of_day("2026-04-01"), limit=10,
    )
    ours = [r for r in rows if r["agenda_item_id"] == iid]
    assert len(ours) == 1
    assert ours[0]["action"] == "removed"


def test_list_badge_audit_log_filters_by_until_exclusive(bag):
    from docket.services import query
    m = bag.add_meeting()
    iid = bag.add_item(m)
    bag.add_audit(iid, "split_vote", "added",
                   occurred_at="2026-03-01T00:00:00Z")
    bag.add_audit(iid, "split_vote", "removed",
                   occurred_at="2026-04-15T00:00:00Z")

    # Caller treats until=2026-04-01 as "include the whole day", so
    # the exclusive boundary is start-of-2026-04-02 in CDT.
    rows = query.list_badge_audit_log(
        until_exclusive=_local_start_of_day("2026-04-01") + timedelta(days=1),
        limit=10,
    )
    ours = [r for r in rows if r["agenda_item_id"] == iid]
    assert len(ours) == 1
    assert ours[0]["action"] == "added"


def test_list_badge_audit_log_until_includes_late_local_evening(bag):
    """Decision #10 boundary case: an event at 23:30 CDT on April 1
    should still match ``until=2026-04-01`` (which the helper treats as
    'include the whole local day' via exclusive start-of-next-day).

    23:30 CDT on 2026-04-01 = 04:30 UTC on 2026-04-02. A naive
    ``occurred_at <= '2026-04-01'::timestamptz`` cast in a UTC session
    would have rejected this row; the timezone-aware helper accepts it.
    """
    from docket.services import query
    m = bag.add_meeting()
    iid = bag.add_item(m)
    bag.add_audit(iid, "split_vote", "added", actor="g3-late",
                   occurred_at="2026-04-02T04:30:00Z")  # 23:30 CDT on Apr 1

    rows = query.list_badge_audit_log(
        until_exclusive=_local_start_of_day("2026-04-01") + timedelta(days=1),
        limit=10,
    )
    ours = [r for r in rows if r["actor"] == "g3-late"]
    assert len(ours) == 1, (
        "An event at 23:30 CDT on 2026-04-01 must match until=2026-04-01"
    )


def test_list_badge_audit_log_rejects_naive_datetime(bag):
    """Caller contract: timezone-aware datetimes only. Naive datetimes
    are a programming error, not a runtime fallback to UTC."""
    from docket.services import query

    naive = datetime(2026, 4, 1)
    with pytest.raises(ValueError, match="timezone-aware"):
        query.list_badge_audit_log(since=naive, limit=10)


def test_list_badge_audit_log_left_joins_deleted_items(bag):
    """Audit FK has no CASCADE; deleted-item audit rows must still surface.

    NOTE: deviation from plan — migration 013:144 declares
    ``agenda_item_id INT NOT NULL REFERENCES agenda_items(id)`` with
    the default RESTRICT semantics, so we cannot DELETE the parent
    item while the audit row references it. To still verify the
    LEFT JOIN behavior, we temporarily drop & restore the FK around
    the orphaning step. The LEFT JOIN remains correct defensive code
    in case a future migration relaxes the FK.
    """
    from docket.services import query

    m = bag.add_meeting()
    iid = bag.add_item(m)
    bag.add_audit(iid, "split_vote", "added", actor="ghost")

    # Drop FK, delete item, re-add FK as NOT VALID so the now-orphan
    # row doesn't trip validation. Restore validation semantics at
    # the end of the test.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "ALTER TABLE agenda_item_badges_audit "
            "DROP CONSTRAINT agenda_item_badges_audit_agenda_item_id_fkey"
        )
        cur.execute("DELETE FROM agenda_items WHERE id = %s", (iid,))
    bag.item_ids.remove(iid)  # don't try to clean it again

    try:
        rows = query.list_badge_audit_log(actor="ghost", limit=10)
        ours = [r for r in rows if r["agenda_item_id"] == iid]
        assert len(ours) == 1
        assert ours[0]["item_title"] is None  # LEFT JOIN
    finally:
        # Cleanup: orphan audit row, then restore the FK constraint.
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM agenda_item_badges_audit WHERE agenda_item_id = %s",
                (iid,),
            )
            cur.execute(
                "ALTER TABLE agenda_item_badges_audit "
                "ADD CONSTRAINT agenda_item_badges_audit_agenda_item_id_fkey "
                "FOREIGN KEY (agenda_item_id) REFERENCES agenda_items(id)"
            )
