"""Integration test for refactor #2, Section E — backfill script.

The one-shot ``scripts/backfill_flag_llm_only_badges.py`` reclassifies
existing policy-badge rows that landed under the old auto-apply rules:
``source='llm' AND status='applied'`` → ``status='flagged'``. Other rows
(deterministic, both, manual) are left alone.

Assertions:
- Only the (kind=policy, source=llm, status=applied) rows flip
- Each flipped row gets an audit row with action='flagged'
- Deterministic / both / manual rows untouched
- Already-flagged rows untouched (idempotent — re-run is a no-op)
- Process badges untouched (they never have source='llm')
"""

from __future__ import annotations

import pytest

from docket.config import DATABASE_URL
from docket.db import db


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run backfill test against Railway DB.",
)


class _Bag:
    def __init__(self, city_id: int):
        self.city_id = city_id
        self.meeting_ids: list[int] = []
        self.item_ids: list[int] = []

    def add_meeting(self) -> int:
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO meetings
                  (municipality_id, title, meeting_date, meeting_type)
                VALUES (%s, 'E backfill test', '2026-04-15', 'council')
                RETURNING id
                """,
                (self.city_id,),
            )
            mid = cur.fetchone()[0]
        self.meeting_ids.append(mid)
        return mid

    def add_item(self, meeting_id: int, *, title: str) -> int:
        with db() as conn, conn.cursor() as cur:
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

    def add_badge(self, item_id: int, badge_slug: str, *,
                  kind: str, source: str, status: str,
                  confidence: float = 0.6) -> int:
        with db() as conn, conn.cursor() as cur:
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
            return cur.fetchone()[0]

    def cleanup(self):
        with db() as conn, conn.cursor() as cur:
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


@pytest.fixture
def bag():
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
        row = cur.fetchone()
    assert row is not None
    b = _Bag(row[0])
    try:
        yield b
    finally:
        b.cleanup()


def _read_status(badge_id: int) -> str:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM agenda_item_badges WHERE id = %s",
            (badge_id,),
        )
        return cur.fetchone()[0]


def _audit_count(item_id: int, badge_slug: str, action: str) -> int:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) FROM agenda_item_badges_audit
                WHERE agenda_item_id = %s AND badge_slug = %s AND action = %s""",
            (item_id, badge_slug, action),
        )
        return cur.fetchone()[0]


def test_backfill_reclassifies_llm_only_to_flagged(bag):
    """The whole-point assertion: source='llm' AND status='applied' AND
    kind='policy' rows get status='flagged'. Untouched: deterministic,
    both, manual, and already-flagged."""
    from scripts.backfill_flag_llm_only_badges import run_backfill

    m = bag.add_meeting()
    iid = bag.add_item(m, title="Backfill target item")

    llm_applied = bag.add_badge(iid, "blight_accountability",
                                kind="policy", source="llm", status="applied")
    det_applied = bag.add_badge(iid, "housing_stability",
                                kind="policy", source="deterministic",
                                status="applied")
    both_applied = bag.add_badge(iid, "public_safety_tech_privacy",
                                 kind="policy", source="both", status="applied")
    process = bag.add_badge(iid, "legal_settlement",
                            kind="process", source="deterministic",
                            status="applied")

    iid2 = bag.add_item(m, title="Already-flagged sibling")
    already_flagged = bag.add_badge(iid2, "blight_accountability",
                                    kind="policy", source="llm",
                                    status="flagged")

    summary = run_backfill()

    assert _read_status(llm_applied) == "flagged"
    assert _read_status(det_applied) == "applied"
    assert _read_status(both_applied) == "applied"
    assert _read_status(process) == "applied"
    assert _read_status(already_flagged) == "flagged"

    assert summary["flagged_count"] == 1
    assert _audit_count(iid, "blight_accountability", "flagged") == 1
    assert _audit_count(iid, "housing_stability", "flagged") == 0


def test_backfill_is_idempotent(bag):
    """Second run is a no-op — every llm/applied row is now flagged."""
    from scripts.backfill_flag_llm_only_badges import run_backfill

    m = bag.add_meeting()
    iid = bag.add_item(m, title="Idempotent target")
    bag.add_badge(iid, "blight_accountability",
                  kind="policy", source="llm", status="applied")

    first = run_backfill()
    second = run_backfill()

    assert first["flagged_count"] == 1
    assert second["flagged_count"] == 0
