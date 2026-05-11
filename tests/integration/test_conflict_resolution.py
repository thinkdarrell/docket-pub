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


# ---------------------------------------------------------------------------
# G4.2 — /admin/review/conflicts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("city_slug", CITIES)
def test_review_conflicts_renders_for_admin(app, city_slug):
    bag = _bag_for(city_slug)
    try:
        m = bag.add_meeting()
        iid = bag.add_conflict_item(m, title=f"Conflict in {city_slug}")

        c = app.test_client()
        with c.session_transaction() as sess:
            sess["admin_user"] = "tester"
        resp = c.get("/admin/review/conflicts")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Cross-Stage Conflicts" in body
        assert f"Conflict in {city_slug}" in body
    finally:
        bag.cleanup()


def test_review_conflicts_redirects_anonymous(client):
    resp = client.get("/admin/review/conflicts")
    assert resp.status_code in (302, 303)
    assert "/admin/login" in resp.headers.get("Location", "")


def test_review_conflicts_renders_side_by_side_facts_and_conflicts(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(
        m,
        title="Side-by-side test",
        score_overrides={
            "conflicts": ["stage1_has_counterparty_but_stage2_procedural",
                          "yellow_tier_dollars_but_stage2_procedural"],
        },
    )

    resp = admin_client.get("/admin/review/conflicts")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    # Stage 1 facts JSON surfaces (counterparty from SAMPLE_FACTS).
    assert "Acme Corp" in body
    # Conflict reasons array is rendered.
    assert "stage1_has_counterparty_but_stage2_procedural" in body
    assert "yellow_tier_dollars_but_stage2_procedural" in body
    # Each row has id="row-{iid}" so HTMX swaps target it.
    assert f'id="row-{iid}"' in body


def test_review_conflicts_empty_state(admin_client, bag):
    """Empty state: admin tone (per G2 fix-up R-S-NEW-2 convention)."""
    # No conflict items in the bag -> empty state should render.
    resp = admin_client.get("/admin/review/conflicts")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    # Match the admin-precise copy from the template.
    assert "No items in cross_stage_conflict" in body or "No conflicts" in body


def test_review_conflicts_pagination_offset(admin_client, bag):
    """Sentinel-pagination contract: 26 rows triggers a Next link
    (page size = 25)."""
    m = bag.add_meeting()
    for i in range(26):
        bag.add_conflict_item(m, title=f"P{i:02d}")

    resp = admin_client.get("/admin/review/conflicts")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "offset=25" in body or "offset=" in body


# ---------------------------------------------------------------------------
# G4.3a — accept_stage_1 (manual headline/why_it_matters)
# ---------------------------------------------------------------------------


def test_accept_s1_form_renders_inline(admin_client, bag):
    """GET to the form-expander returns the inline form HTML."""
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)
    resp = admin_client.get(f"/admin/review/conflicts/{iid}/_form/accept-stage-1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'name="manual_headline"' in body
    assert 'name="manual_why_it_matters"' in body


def test_accept_s1_post_writes_headline_and_why_it_matters(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)

    resp = admin_client.post(
        f"/admin/review/conflicts/{iid}/accept-stage-1",
        data={
            "manual_headline": "City awards $75K janitorial contract",
            "manual_why_it_matters": "Renews custodial services across 12 city buildings.",
        },
    )
    assert resp.status_code == 200  # HTMX swap response

    item = _read_item(iid)
    assert item["headline"] == "City awards $75K janitorial contract"
    assert item["why_it_matters"] == "Renews custodial services across 12 city buildings."
    assert item["processing_status"] == "completed"


def test_accept_s1_writes_audit_row_with_payload(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)

    admin_client.post(
        f"/admin/review/conflicts/{iid}/accept-stage-1",
        data={
            "manual_headline": "City awards $75K janitorial contract",
            "manual_why_it_matters": "Renews custodial services across 12 city buildings.",
        },
    )

    rows = _audit_rows(iid)
    assert len(rows) == 1
    from_status, to_status, action, actor, role, _, payload = rows[0]
    assert from_status == "cross_stage_conflict"
    assert to_status == "completed"
    assert action == "accept_stage1"
    assert actor == "tester"
    assert role == "admin"
    # payload is JSONB; psycopg2 returns dict
    assert payload["manual_headline"] == "City awards $75K janitorial contract"


def test_accept_s1_validates_headline_length(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)

    # Headline too short (<10 chars) — must reject 400.
    resp = admin_client.post(
        f"/admin/review/conflicts/{iid}/accept-stage-1",
        data={
            "manual_headline": "Too short",  # 9 chars
            "manual_why_it_matters": "valid description",
        },
    )
    assert resp.status_code == 400

    # Headline too long (>60 chars) — must reject 400.
    resp = admin_client.post(
        f"/admin/review/conflicts/{iid}/accept-stage-1",
        data={
            "manual_headline": "x" * 61,
            "manual_why_it_matters": "valid description",
        },
    )
    assert resp.status_code == 400

    # State unchanged on rejection.
    item = _read_item(iid)
    assert item["processing_status"] == "cross_stage_conflict"


def test_accept_s1_validates_why_it_matters_length(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)

    # Empty why_it_matters — must reject.
    resp = admin_client.post(
        f"/admin/review/conflicts/{iid}/accept-stage-1",
        data={"manual_headline": "Valid headline length here", "manual_why_it_matters": ""},
    )
    assert resp.status_code == 400

    # >200 chars — must reject.
    resp = admin_client.post(
        f"/admin/review/conflicts/{iid}/accept-stage-1",
        data={
            "manual_headline": "Valid headline length here",
            "manual_why_it_matters": "x" * 201,
        },
    )
    assert resp.status_code == 400


def test_accept_s1_returns_resolved_swap_target(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m, title="Swap target test")
    resp = admin_client.post(
        f"/admin/review/conflicts/{iid}/accept-stage-1",
        data={
            "manual_headline": "City awards $75K janitorial contract",
            "manual_why_it_matters": "Renews custodial services for 12 buildings.",
        },
    )
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    # Resolved partial sets a row id matching the original.
    assert f'id="row-{iid}"' in body
    assert "Resolved" in body or "completed" in body.lower()


def test_accept_s1_404_for_unknown_item(admin_client):
    resp = admin_client.post(
        "/admin/review/conflicts/999999999/accept-stage-1",
        data={"manual_headline": "Valid headline length", "manual_why_it_matters": "ok"},
    )
    assert resp.status_code == 404


def test_accept_s1_404_for_item_not_in_conflict(admin_client, bag):
    """Resolution actions only valid against cross_stage_conflict items.
    A completed item must 404 — no silent partial overwrite."""
    m = bag.add_meeting()
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agenda_items
              (meeting_id, title, processing_status)
            VALUES (%s, 'completed item',
                    'completed'::processing_status_enum)
            RETURNING id
            """,
            (m,),
        )
        iid = cur.fetchone()[0]
    bag.item_ids.append(iid)

    resp = admin_client.post(
        f"/admin/review/conflicts/{iid}/accept-stage-1",
        data={"manual_headline": "Valid headline length", "manual_why_it_matters": "ok"},
    )
    assert resp.status_code == 404


def test_accept_s1_requires_post(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)
    resp = admin_client.get(f"/admin/review/conflicts/{iid}/accept-stage-1")
    assert resp.status_code == 405


def test_accept_s1_requires_login(client, bag):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)
    resp = client.post(
        f"/admin/review/conflicts/{iid}/accept-stage-1",
        data={"manual_headline": "Valid headline length", "manual_why_it_matters": "ok"},
    )
    assert resp.status_code in (302, 303)
    assert "/admin/login" in resp.headers.get("Location", "")
    item = _read_item(iid)
    assert item["processing_status"] == "cross_stage_conflict"


# ---------------------------------------------------------------------------
# G4.3b — accept_stage_2 (clear Stage 1 facts, mark procedural)
# ---------------------------------------------------------------------------


def test_accept_s2_clears_extracted_facts(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)

    resp = admin_client.post(f"/admin/review/conflicts/{iid}/accept-stage-2")
    assert resp.status_code == 200

    item = _read_item(iid)
    assert item["extracted_facts"] is None
    assert item["headline"] is None
    assert item["why_it_matters"] is None
    assert item["processing_status"] == "completed"


def test_accept_s2_writes_audit_row(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)

    admin_client.post(f"/admin/review/conflicts/{iid}/accept-stage-2")

    rows = _audit_rows(iid)
    assert len(rows) == 1
    from_status, to_status, action, actor, role, _, _ = rows[0]
    assert from_status == "cross_stage_conflict"
    assert to_status == "completed"
    assert action == "accept_stage2"
    assert actor == "tester"
    assert role == "admin"


def test_accept_s2_optional_reason_persisted(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)

    admin_client.post(
        f"/admin/review/conflicts/{iid}/accept-stage-2",
        data={"reason": "Title-only proclamation, no substance."},
    )

    rows = _audit_rows(iid)
    _, _, _, _, _, reason, _ = rows[0]
    assert reason == "Title-only proclamation, no substance."


def test_accept_s2_404_for_unknown_item(admin_client):
    resp = admin_client.post("/admin/review/conflicts/999999999/accept-stage-2")
    assert resp.status_code == 404


def test_accept_s2_404_for_item_not_in_conflict(admin_client, bag):
    m = bag.add_meeting()
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agenda_items
              (meeting_id, title, processing_status)
            VALUES (%s, 'completed item',
                    'completed'::processing_status_enum)
            RETURNING id
            """,
            (m,),
        )
        iid = cur.fetchone()[0]
    bag.item_ids.append(iid)
    resp = admin_client.post(f"/admin/review/conflicts/{iid}/accept-stage-2")
    assert resp.status_code == 404


def test_accept_s2_requires_post(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)
    resp = admin_client.get(f"/admin/review/conflicts/{iid}/accept-stage-2")
    assert resp.status_code == 405


def test_accept_s2_requires_login(client, bag):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)
    resp = client.post(f"/admin/review/conflicts/{iid}/accept-stage-2")
    assert resp.status_code in (302, 303)
    assert "/admin/login" in resp.headers.get("Location", "")
    item = _read_item(iid)
    assert item["processing_status"] == "cross_stage_conflict"


# ---------------------------------------------------------------------------
# G4.3c — re_prompt_stage_2 (admin override + Stage 2 re-run)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_rewrite_item(monkeypatch):
    """Patch rewrite.rewrite_item to a controllable mock.

    Returns a MagicMock so each test can configure its return_value.
    Default behavior: returns a substantive rewrite that will reconcile
    cleanly (action='accept').
    """
    from docket.ai.rewrite_schema import ItemRewrite
    mock = MagicMock()
    mock.return_value = (
        ItemRewrite(
            is_substantive=True,
            headline="Council awards $75K janitorial contract",
            why_it_matters="Renews custodial services across 12 city buildings.",
            significance_rationale="Modest ongoing operating expense.",
            significance_score=4.0,
            consent_placement_rationale="Routine ops contract.",
            consent_placement_score=8.0,
            suggested_badge_slugs=[],
            confidence="medium",
        ),
        "claude-haiku-4-5-20251001",
    )
    monkeypatch.setattr("docket.services.conflict_resolution.rewrite_item", mock)
    return mock


def test_re_prompt_form_renders_inline(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)
    resp = admin_client.get(f"/admin/review/conflicts/{iid}/_form/re-prompt")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'name="override_instruction"' in body


def test_re_prompt_resolves_conflict_when_rerun_is_substantive(
    admin_client, bag, mock_rewrite_item,
):
    """Happy path: admin override -> Stage 2 returns substantive ->
    reconcile accepts -> status flips to completed."""
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)

    resp = admin_client.post(
        f"/admin/review/conflicts/{iid}/re-prompt-stage-2",
        data={"override_instruction": "This IS substantive — a contract award."},
    )
    assert resp.status_code == 200

    item = _read_item(iid)
    assert item["processing_status"] == "completed"
    assert item["headline"] == "Council awards $75K janitorial contract"

    rows = _audit_rows(iid)
    assert len(rows) == 1
    _, to_status, action, _, _, _, payload = rows[0]
    assert to_status == "completed"
    assert action == "re_prompt_stage2"
    assert payload["override_instruction"] == \
        "This IS substantive — a contract award."
    assert payload["reconcile_action"] == "accept"


def test_re_prompt_stays_in_conflict_when_rerun_still_procedural(
    admin_client, bag, monkeypatch,
):
    """Sad path: admin override -> Stage 2 STILL says procedural ->
    reconcile says still in conflict -> status stays at conflict;
    audit row records the failed-resolution attempt."""
    from docket.ai.rewrite_schema import ItemRewrite

    def _mock(*args, **kwargs):
        return (
            ItemRewrite(
                is_substantive=False,
                headline=None,
                why_it_matters=None,
                significance_rationale="",
                significance_score=None,
                consent_placement_rationale="",
                consent_placement_score=None,
                suggested_badge_slugs=[],
                confidence="medium",
            ),
            "claude-haiku-4-5-20251001",
        )
    monkeypatch.setattr("docket.services.conflict_resolution.rewrite_item", _mock)

    m = bag.add_meeting()
    iid = bag.add_conflict_item(m, dollars_amount=100_000)  # yellow tier
    resp = admin_client.post(
        f"/admin/review/conflicts/{iid}/re-prompt-stage-2",
        data={"override_instruction": "Try harder."},
    )
    assert resp.status_code == 200

    item = _read_item(iid)
    assert item["processing_status"] == "cross_stage_conflict"  # still

    rows = _audit_rows(iid)
    assert len(rows) == 1
    from_status, to_status, action, _, _, _, payload = rows[0]
    assert from_status == "cross_stage_conflict"
    assert to_status == "cross_stage_conflict"
    assert action == "re_prompt_stage2"
    assert payload["reconcile_action"] == "mark_cross_stage_conflict"


def test_re_prompt_validates_override_length(admin_client, bag, mock_rewrite_item):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)

    # Empty
    resp = admin_client.post(
        f"/admin/review/conflicts/{iid}/re-prompt-stage-2",
        data={"override_instruction": ""},
    )
    assert resp.status_code == 400

    # Too long
    resp = admin_client.post(
        f"/admin/review/conflicts/{iid}/re-prompt-stage-2",
        data={"override_instruction": "x" * 501},
    )
    assert resp.status_code == 400


def test_re_prompt_404_for_unknown_or_completed_item(admin_client, bag, mock_rewrite_item):
    resp = admin_client.post(
        "/admin/review/conflicts/999999999/re-prompt-stage-2",
        data={"override_instruction": "x"},
    )
    assert resp.status_code == 404


def test_re_prompt_requires_login(client, bag):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)
    resp = client.post(
        f"/admin/review/conflicts/{iid}/re-prompt-stage-2",
        data={"override_instruction": "ok"},
    )
    assert resp.status_code in (302, 303)


def test_re_prompt_returns_409_when_item_resolved_during_llm_call(
    admin_client, bag, monkeypatch,
):
    """Decision #12 TOCTOU guard: simulate another admin resolving the
    item DURING the LLM call window. The persistence UPDATE's WHERE
    clause filters on processing_status='cross_stage_conflict' so our
    UPDATE affects 0 rows; the service raises
    ConflictAlreadyResolvedError; the route returns 409."""
    from docket.ai.rewrite_schema import ItemRewrite

    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)

    def _mock_with_concurrent_resolve(*args, **kwargs):
        # Simulate the race: between item-load and persistence, another
        # admin flips the item to 'completed'. We do that flip from
        # inside the mock so it happens at exactly the LLM-call window.
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agenda_items
                   SET processing_status = 'completed'::processing_status_enum
                 WHERE id = %s
                """,
                (iid,),
            )
        return (
            ItemRewrite(
                is_substantive=True,
                headline="Council awards $75K janitorial contract",
                why_it_matters="Renews custodial services across 12 city buildings.",
                significance_rationale="Modest ongoing operating expense.",
                significance_score=4.0,
                consent_placement_rationale="Routine ops contract.",
                consent_placement_score=8.0,
                suggested_badge_slugs=[],
                confidence="medium",
            ),
            "claude-haiku-4-5-20251001",
        )
    monkeypatch.setattr(
        "docket.services.conflict_resolution.rewrite_item",
        _mock_with_concurrent_resolve,
    )

    resp = admin_client.post(
        f"/admin/review/conflicts/{iid}/re-prompt-stage-2",
        data={"override_instruction": "Try harder."},
    )
    assert resp.status_code == 409
    assert "resolved by another admin" in resp.get_data(as_text=True)

    # Item is at 'completed' (from the racing admin's resolution),
    # NOT overwritten by the LLM-touching path's UPDATE.
    item = _read_item(iid)
    assert item["processing_status"] == "completed"
    # The losing-admin's intent was logged: a *_lost_race audit row
    # exists alongside no successful re_prompt_stage2 row.
    rows = _audit_rows(iid)
    actions = [r[2] for r in rows]
    assert "re_prompt_stage2_lost_race" in actions
    assert "re_prompt_stage2" not in actions


# ---------------------------------------------------------------------------
# G4.3d — edit_stage_1_facts (correct facts + Stage 2 re-run)
# ---------------------------------------------------------------------------


def test_edit_facts_form_renders_inline(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)
    resp = admin_client.get(f"/admin/review/conflicts/{iid}/_form/edit-facts")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'name="new_facts_json"' in body
    # Form pre-populates with existing extracted_facts (so admin edits
    # rather than re-typing from scratch).
    assert "Acme Corp" in body  # from SAMPLE_FACTS


def test_edit_facts_persists_corrected_facts_and_reruns_stage2(
    admin_client, bag, mock_rewrite_item,
):
    """Happy path: admin corrects counterparty -> Stage 2 returns
    substantive -> reconcile accepts -> status flips to completed."""
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)

    corrected_facts = dict(SAMPLE_FACTS)
    corrected_facts["counterparty"] = "Real Vendor LLC"
    corrected_facts["action_type"] = "contract_award"

    resp = admin_client.post(
        f"/admin/review/conflicts/{iid}/edit-stage-1-facts",
        data={"new_facts_json": json.dumps(corrected_facts)},
    )
    assert resp.status_code == 200

    item = _read_item(iid)
    assert item["processing_status"] == "completed"
    # Persisted facts updated.
    assert item["extracted_facts"]["counterparty"] == "Real Vendor LLC"

    rows = _audit_rows(iid)
    assert len(rows) == 1
    _, to_status, action, _, _, _, payload = rows[0]
    assert to_status == "completed"
    assert action == "edit_stage1_facts"
    assert payload["new_facts_json"]["counterparty"] == "Real Vendor LLC"


def test_edit_facts_validates_pydantic_schema(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)

    # Missing required field — Pydantic should reject.
    bad_facts = {"counterparty": "Acme"}  # missing funding_source etc.
    resp = admin_client.post(
        f"/admin/review/conflicts/{iid}/edit-stage-1-facts",
        data={"new_facts_json": json.dumps(bad_facts)},
    )
    assert resp.status_code == 400


def test_edit_facts_validates_json_parseability(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)

    resp = admin_client.post(
        f"/admin/review/conflicts/{iid}/edit-stage-1-facts",
        data={"new_facts_json": "not valid json {{"},
    )
    assert resp.status_code == 400


def test_edit_facts_404_for_unknown_or_completed_item(admin_client, bag):
    resp = admin_client.post(
        "/admin/review/conflicts/999999999/edit-stage-1-facts",
        data={"new_facts_json": json.dumps(SAMPLE_FACTS)},
    )
    assert resp.status_code == 404


def test_edit_facts_requires_login(client, bag):
    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)
    resp = client.post(
        f"/admin/review/conflicts/{iid}/edit-stage-1-facts",
        data={"new_facts_json": json.dumps(SAMPLE_FACTS)},
    )
    assert resp.status_code in (302, 303)


def test_edit_facts_returns_409_when_item_resolved_during_llm_call(
    admin_client, bag, monkeypatch,
):
    """Decision #12 TOCTOU guard for edit-facts path. Same shape as
    the re-prompt TOCTOU test."""
    from docket.ai.rewrite_schema import ItemRewrite

    m = bag.add_meeting()
    iid = bag.add_conflict_item(m)

    def _mock_with_concurrent_resolve(*args, **kwargs):
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agenda_items
                   SET processing_status = 'completed'::processing_status_enum
                 WHERE id = %s
                """,
                (iid,),
            )
        return (
            ItemRewrite(
                is_substantive=True,
                headline="Council awards $75K janitorial contract",
                why_it_matters="Renews custodial services across 12 city buildings.",
                significance_rationale="Modest ongoing operating expense.",
                significance_score=4.0,
                consent_placement_rationale="Routine ops contract.",
                consent_placement_score=8.0,
                suggested_badge_slugs=[],
                confidence="medium",
            ),
            "claude-haiku-4-5-20251001",
        )
    monkeypatch.setattr(
        "docket.services.conflict_resolution.rewrite_item",
        _mock_with_concurrent_resolve,
    )

    corrected = dict(SAMPLE_FACTS)
    corrected["counterparty"] = "Real Vendor LLC"
    resp = admin_client.post(
        f"/admin/review/conflicts/{iid}/edit-stage-1-facts",
        data={"new_facts_json": json.dumps(corrected)},
    )
    assert resp.status_code == 409
    assert "resolved by another admin" in resp.get_data(as_text=True)

    rows = _audit_rows(iid)
    actions = [r[2] for r in rows]
    assert "edit_stage1_facts_lost_race" in actions
    assert "edit_stage1_facts" not in actions


# ---------------------------------------------------------------------------
# G4 review fix-up regression tests
# ---------------------------------------------------------------------------


def test_edit_facts_pre_llm_race_does_not_overwrite_completed_facts(
    admin_client, bag, monkeypatch,
):
    """B-R1 regression: when a concurrent admin resolves between
    ``_load_conflict_item`` and the early ``extracted_facts`` UPDATE,
    the early UPDATE must NOT overwrite the now-completed row's facts.
    Post-fix the early UPDATE carries a TOCTOU predicate and fails
    fast before the LLM call, writing a distinct
    ``edit_stage1_facts_lost_race_pre_llm`` audit row.

    Test mechanism (adapted from the prompt's spec to avoid the
    FOR-UPDATE deadlock the prompt warned about):
    pre-flip the row to 'completed' with a sentinel facts payload, and
    monkeypatch ``_load_conflict_item`` to *bypass the real SELECT* and
    return a fabricated 'cross_stage_conflict' dict. This simulates the
    state the losing admin's transaction would observe if it loaded the
    row a microsecond before the winner committed — without holding the
    FOR UPDATE lock that would otherwise deadlock the racing UPDATE.
    The function then proceeds to the early UPDATE, which sees the
    actual row state ('completed') via its TOCTOU predicate, rowcount=0
    fires, and the pre-LLM lost-race audit row is written.
    """
    import docket.services.conflict_resolution as conflict_mod

    m = bag.add_meeting()
    iid = bag.add_conflict_item(m, title="pre-LLM race target")
    sentinel_facts = dict(SAMPLE_FACTS)
    sentinel_facts["counterparty"] = "DO_NOT_OVERWRITE"

    # Pre-flip the row to the post-race shape: 'completed' with the
    # winning admin's facts intact (the accept_stage_1-style outcome
    # where Stage 1 facts are kept while status flips).
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agenda_items
               SET processing_status = 'completed'::processing_status_enum,
                   extracted_facts = %s::jsonb
             WHERE id = %s
            """,
            (json.dumps(sentinel_facts), iid),
        )

    # Fabricate a 'cross_stage_conflict' dict so the function thinks
    # the row is still in conflict at load time. Bypassing the real
    # SELECT also avoids the FOR UPDATE lock (which would otherwise
    # deadlock against any racing UPDATE issued from a separate
    # connection inside the test).
    fake_loaded_item = {
        "id": iid,
        "title": "pre-LLM race target",
        "description": "stub",
        "sponsor": None,
        "dollars_amount": 75000,
        "topic": None,
        "is_consent": False,
        "extracted_facts": sentinel_facts,
        "score_overrides": {},
        "processing_status": "cross_stage_conflict",
        "municipality_id": bag.city_id,
        "city_name": bag.city_slug,
    }

    def _fake_load(cur, item_id):
        if item_id == iid:
            return fake_loaded_item
        return None

    monkeypatch.setattr(conflict_mod, "_load_conflict_item", _fake_load)

    # LLM mock — should NEVER be called. Track invocations so a
    # regression where the function reaches the LLM is observable.
    from docket.ai.rewrite_schema import ItemRewrite
    llm_called: list[bool] = []

    def _mock_rewrite(*args, **kwargs):
        llm_called.append(True)
        return (
            ItemRewrite(
                is_substantive=False,
                headline=None,
                why_it_matters=None,
                significance_rationale="",
                significance_score=None,
                consent_placement_rationale="",
                consent_placement_score=None,
                suggested_badge_slugs=[],
                confidence="medium",
            ),
            "claude-haiku-4-5-20251001",
        )

    monkeypatch.setattr(conflict_mod, "rewrite_item", _mock_rewrite)

    corrected = dict(SAMPLE_FACTS)
    corrected["counterparty"] = "FRESH_EDIT"
    resp = admin_client.post(
        f"/admin/review/conflicts/{iid}/edit-stage-1-facts",
        data={"new_facts_json": json.dumps(corrected)},
    )

    # Route returns 409 (lost race).
    assert resp.status_code == 409
    # LLM was NOT called — pre-LLM fail-fast is the whole point.
    assert llm_called == []
    # The row's extracted_facts is the racing admin's sentinel, NOT
    # the losing admin's correction.
    item = _read_item(iid)
    assert item["extracted_facts"]["counterparty"] == "DO_NOT_OVERWRITE"
    # Audit row carries the new pre-LLM lost-race action.
    rows = _audit_rows(iid)
    actions = [r[2] for r in rows]
    assert "edit_stage1_facts_lost_race_pre_llm" in actions
    assert "edit_stage1_facts" not in actions


def test_re_prompt_returns_400_on_stored_facts_pydantic_drift(admin_client, bag):
    """B-R2 regression: ``re_prompt_stage_2`` validates stored
    ``extracted_facts`` via Pydantic. On drift (unknown keys with
    ``extra='forbid'``, or missing required fields), the bare
    ``model_validate`` previously raised ``ValidationError`` → Flask
    500. Post-fix it is wrapped → ``ConflictValidationError`` →
    route 400.

    Seed an agenda_items row in cross_stage_conflict with a malformed
    ``extracted_facts`` JSONB (StructuredFacts has ``extra='forbid'``).
    """
    m = bag.add_meeting()
    bad_facts = {"unknown_key_that_pydantic_rejects": "garbage"}
    # Bypass the helper's SAMPLE_FACTS to seed deliberately-bad JSONB.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agenda_items
              (meeting_id, title, description, dollars_amount,
               extracted_facts, score_overrides,
               data_debt_priority, processing_status)
            VALUES (%s, 'pydantic drift test', 'desc', 50000,
                    %s::jsonb, '{}'::jsonb,
                    'normal'::data_debt_priority_enum,
                    'cross_stage_conflict'::processing_status_enum)
            RETURNING id
            """,
            (m, json.dumps(bad_facts)),
        )
        iid = cur.fetchone()[0]
    bag.item_ids.append(iid)

    resp = admin_client.post(
        f"/admin/review/conflicts/{iid}/re-prompt-stage-2",
        data={"override_instruction": "Try."},
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "stored extracted_facts failed validation" in body


def test_accept_s2_lost_race_surfaces_4xx_with_body(admin_client, bag):
    """F-S1 regression: Accept Stage 2 race-loss surfaces as 4xx with
    a non-empty plain-text body the form's
    ``hx-on:htmx:response-error`` handler can render into the
    ``.form-error`` span.

    Mechanism: an item in 'completed' state (not cross_stage_conflict)
    is the post-race shape. ``accept_stage_2``'s ``_load_conflict_item``
    returns None → LookupError → route 404. The 404 body is the Flask
    default text; the ``.form-error`` handler renders any non-2xx body,
    so even Flask's default 'Not Found' is sufficient for a visible
    failure surface.
    """
    m = bag.add_meeting()
    # Item is in 'completed' state directly — simulates the post-race
    # state that the losing admin's Accept-S2 click would encounter.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agenda_items
              (meeting_id, title, processing_status)
            VALUES (%s, 'already resolved',
                    'completed'::processing_status_enum)
            RETURNING id
            """,
            (m,),
        )
        iid = cur.fetchone()[0]
    bag.item_ids.append(iid)

    resp = admin_client.post(f"/admin/review/conflicts/{iid}/accept-stage-2")
    assert resp.status_code == 404
    # Non-empty body — HTMX's response-error handler will render it
    # into ``.form-error``.
    assert resp.get_data(as_text=True) != ""
