"""Integration tests for G4 — cross-stage conflict resolution UI.

Three deliverables under test:

- G4.1: ``query.list_cross_stage_conflicts`` — listing helper.
- G4.2: ``/admin/review/conflicts`` — listing route + side-by-side template.
- G4.3: Four resolution actions (POST endpoints):
  - ``/admin/review/conflicts/<id>/accept-stage-1``
  - ``/admin/review/conflicts/<id>/accept-stage-2``
  - ``/admin/review/conflicts/<id>/re-prompt-stage-2``
  - ``/admin/review/conflicts/<id>/edit-stage-1-facts``

Plus 4 GET form-expander endpoints (HTMX-driven; they return the inline
form partial when the admin clicks the button).

LLM-touching paths (re_prompt_stage_2, edit_stage_1_facts) monkeypatch
``docket.ai.rewrite.rewrite_item`` so the suite stays offline.

Reuses the G2/G3 ``_Bag`` test-data tracker pattern (self-contained;
does NOT import from tests.integration.test_admin_queues or
test_admin_badge_audit).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run G4 conflict-resolution tests against Railway DB.",
)


CITIES = ["birmingham", "mobile", "vestavia_hills", "homewood"]


# Sample StructuredFacts payload shaped to pass Pydantic validation.
# Used by tests that need to seed agenda_items.extracted_facts.
SAMPLE_FACTS = {
    "funding_source": "general_fund",
    "counterparty": "Acme Corp",
    "procurement_method": "competitive",
    "location": None,
    "action_type": "contract_award",
    "next_steps": {
        "committee_referral": None,
        "public_hearing_date": None,
        "public_hearing_time": None,
        "comment_period_end": None,
        "implementation_date": None,
    },
    "parcels_affected": None,
    "acres_affected": None,
}


class _Bag:
    """Test-data tracker. Cleans up in FK order: audit -> items -> meetings."""

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
                (self.city_id, "G4 test meeting", meeting_date_str),
            )
            mid = cur.fetchone()[0]
        self.meeting_ids.append(mid)
        return mid

    def add_conflict_item(
        self,
        meeting_id: int,
        *,
        title: str = "G4 test item",
        description: str = "Some agenda item description for G4 testing.",
        dollars_amount: int | None = 75000,
        extracted_facts: dict | None = None,
        score_overrides: dict | None = None,
        data_debt_priority: str = "normal",
    ) -> int:
        """Seed an agenda_items row in cross_stage_conflict state with the
        Stage 1 facts already attached. Mirrors what reconcile_stages
        produces when both Stage 2 attempts fail."""
        facts = extracted_facts if extracted_facts is not None else SAMPLE_FACTS
        overrides = score_overrides if score_overrides is not None else {
            "conflicts": ["stage1_has_counterparty_but_stage2_procedural"],
            "original_ai_significance": None,
            "final_significance": None,
        }
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agenda_items
                  (meeting_id, title, description, dollars_amount,
                   extracted_facts, score_overrides,
                   data_debt_priority, processing_status)
                VALUES (%s, %s, %s, %s,
                        %s::jsonb, %s::jsonb,
                        %s::data_debt_priority_enum,
                        'cross_stage_conflict'::processing_status_enum)
                RETURNING id
                """,
                (meeting_id, title, description, dollars_amount,
                 json.dumps(facts), json.dumps(overrides),
                 data_debt_priority),
            )
            iid = cur.fetchone()[0]
        self.item_ids.append(iid)
        return iid

    def cleanup(self) -> None:
        with db() as conn, conn.cursor() as cur:
            if self.item_ids:
                cur.execute(
                    "DELETE FROM processing_status_audit "
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
    flask_app.config["SECRET_KEY"] = "test-secret-key-G4"
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


def _audit_rows(item_id: int) -> list[tuple]:
    """Helper: read processing_status_audit rows for an item, ordered by id."""
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT from_status::text, to_status::text, action, actor,
                   actor_role, reason, payload
              FROM processing_status_audit
             WHERE agenda_item_id = %s
             ORDER BY id ASC
            """,
            (item_id,),
        )
        return cur.fetchall()


def _read_item(item_id: int) -> dict:
    """Helper: read the post-action state of an agenda_items row."""
    from docket.db import db_cursor
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, headline, why_it_matters,
                   processing_status::text AS processing_status,
                   extracted_facts, score_overrides,
                   significance_score, consent_placement_score
              FROM agenda_items
             WHERE id = %s
            """,
            (item_id,),
        )
        return dict(cur.fetchone())


# ---------------------------------------------------------------------------
# G4.1 — query.list_cross_stage_conflicts
# ---------------------------------------------------------------------------


def test_list_cross_stage_conflicts_returns_only_conflicted_items(bag):
    from docket.services import query

    m = bag.add_meeting()
    iid_conflict = bag.add_conflict_item(m, title="In conflict")
    # Add an unrelated item NOT in conflict — must NOT surface.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agenda_items
              (meeting_id, title, processing_status)
            VALUES (%s, %s,
                    'completed'::processing_status_enum)
            RETURNING id
            """,
            (m, "Already completed"),
        )
        iid_other = cur.fetchone()[0]
    bag.item_ids.append(iid_other)

    rows = query.list_cross_stage_conflicts(limit=50, offset=0)
    ids = {r["id"] for r in rows}
    assert iid_conflict in ids
    assert iid_other not in ids


def test_list_cross_stage_conflicts_priority_sort_order(bag):
    from docket.services import query
    m = bag.add_meeting()
    iid_low = bag.add_conflict_item(m, title="LOW", data_debt_priority="low")
    iid_high = bag.add_conflict_item(m, title="HIGH", data_debt_priority="high")
    iid_normal = bag.add_conflict_item(m, title="NORMAL", data_debt_priority="normal")

    rows = query.list_cross_stage_conflicts(limit=100)
    titles_in_order = [r["title"] for r in rows
                       if r["id"] in {iid_low, iid_high, iid_normal}]
    # HIGH before NORMAL before LOW.
    assert titles_in_order.index("HIGH") < titles_in_order.index("NORMAL")
    assert titles_in_order.index("NORMAL") < titles_in_order.index("LOW")


def test_list_cross_stage_conflicts_pagination(bag):
    """Sentinel-pagination contract: helper accepts limit, caller does
    +1/slice. Verify the helper itself returns at most `limit` rows."""
    from docket.services import query
    m = bag.add_meeting()
    for i in range(5):
        bag.add_conflict_item(m, title=f"P{i}")

    rows = query.list_cross_stage_conflicts(limit=2, offset=0)
    assert len(rows) == 2
    rows_offset_2 = query.list_cross_stage_conflicts(limit=2, offset=2)
    # First two pages should be disjoint; ID intersect is empty.
    first_ids = {r["id"] for r in rows}
    next_ids = {r["id"] for r in rows_offset_2}
    assert first_ids.isdisjoint(next_ids)
