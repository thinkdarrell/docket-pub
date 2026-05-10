# G4 — Cross-Stage Conflict Resolution UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Phase 2 Track 3 §G4 — cross-stage conflict resolution UI per spec decision #93. New admin route `/admin/review/conflicts` lists items at `processing_status='cross_stage_conflict'` with side-by-side display of original raw text + Stage 1 facts + Stage 2 verdict + conflict reasons. Four HTMX-powered resolution actions: (1) Accept Stage 1 with manual headline/why_it_matters; (2) Accept Stage 2 (clear Stage 1 confusion); (3) Re-prompt Stage 2 with admin override instruction; (4) Edit Stage 1 facts and re-run Stage 2. All actions write to `processing_status_audit`. Required before `IMPACT_FIRST_ENABLED=true` flips the worker to v3 (FINAL-3).

**Architecture:** New service module `src/docket/services/conflict_resolution.py` with the 4 resolution functions + a private `_rerun_stage2(item, facts, override_instruction=None)` helper that calls `rewrite.rewrite_item` + `floors.apply_score_floors` + `reconcile.reconcile_stages` and returns a structured result. The helper is a minimal Stage 2 re-run path — B5 (the cross-track convergence task) will later subsume it into a full per-item orchestrator; G4 ships before B5 because decision #93 is required before `IMPACT_FIRST_ENABLED=true`. Admin route + 4 HTMX endpoints in `admin.py`, all gated by the existing blueprint `before_request` auth hook. Listing template + 1 swap-target partial + 3 inline action-form partials. Tests in `tests/integration/test_conflict_resolution.py` follow the G2/G3 `_Bag` fixture pattern; the 2 LLM-touching paths mock `rewrite.rewrite_item` to avoid network calls.

**Tech Stack:** Flask + HTMX + Jinja2 + psycopg2 + PostgreSQL 16/18 + Pydantic. Existing `ai/extraction_schema.py:StructuredFacts` and `ai/rewrite_schema.py:ItemRewrite` are the validation primitives; `ai/reconcile.py:reconcile_stages` is the conflict gate; `ai/floors.py:apply_score_floors` is the deterministic post-pass.

---

## Decisions baked into this plan

These were authored during plan-writing. Override before dispatch if you disagree.

1. **Resolution-action verbs match the spec** (decision #93): `accept_stage_1`, `accept_stage_2`, `re_prompt_stage_2`, `edit_stage_1_facts`. Audit-row `action` column uses snake_case forms. Side-step the temptation to abbreviate.
2. **Stage 2 re-run helper lives in G4, not in `ai/`.** The cross-track per-item orchestrator (`process_item()`) is B5's territory — it will integrate Stage 1 + Stage 2 + reconcile + persistence into a single transactional unit. G4 ships before B5, so G4 defines a minimal `_rerun_stage2` that calls `rewrite_item → apply_score_floors → reconcile_stages` synchronously inside the resolution handler. B5 will refactor; until then this duplication is intentional and documented.
3. **No new migration.** All required schema is already in migration 013: `processing_status_audit`, `processing_status_enum.cross_stage_conflict`, `agenda_items.extracted_facts/headline/why_it_matters/score_overrides`. G4 is pure code.
4. **LLM mocking in tests.** The two LLM-touching paths (`re_prompt_stage_2`, `edit_stage_1_facts`) mock `docket.ai.rewrite.rewrite_item` via `monkeypatch` so the integration suite stays offline. A separate live smoke test (`tests/live/test_g4_re_prompt_live.py`) is gated on `ANTHROPIC_API_KEY` per the existing `tests/live/` convention. The unit-level `tests/unit/test_reconcile.py` already covers `reconcile_stages` directly.
5. **Form length validation matches Pydantic schema caps** (`rewrite_schema.py`):
   - `manual_headline`: 10-60 chars (matches `ItemRewrite.headline` Field constraint + density rule from decision #87)
   - `manual_why_it_matters`: 1-200 chars (matches `ItemRewrite.why_it_matters` Field constraint)
   - `override_instruction`: 1-500 chars (no schema field; reasonable bound for an admin one-liner)
   - `reason`: 0-500 chars (audit-row metadata)
6. **HTMX response contract — success vs validation error.** Successful resolutions return the rendered `_conflict_resolved.html` partial (`hx-swap="outerHTML"` replaces the `<tr>`). Validation errors return **400 + plain-text body**; each form template includes a `<span class="form-error" role="alert">` and an `hx-on:htmx:response-error` handler that routes `event.detail.xhr.responseText` into the span. Form stays visible, message appears, no row swap, semantically correct status. (HTMX 1.x default does NOT swap on 4xx — without the per-form handler the admin would see nothing on invalid input. Returning 200 + replacing the row would lose the form context on validation error, which is worse UX.) Sentinel pagination matches G3 (limit+1 / slice / next_offset; page size 25 — heavier rows with side-by-side content).
7. **Budget gating on re-prompt + edit-facts:** rely on the existing `AI_DAILY_BUDGET_USD` umbrella. If the worker's daily cap is exceeded, the API client throws `AIBudgetExceeded` (defined in `ai/exceptions.py`) which the route maps to a 503 + flash. Per-item retry caps **not** added in v1 — admins are trusted users; spec didn't ask for it.
8. **Listing sort order:** `data_debt_priority DESC, updated_at DESC` (matches the plan §G4.2 SQL sketch). High-priority conflicts surface first; within a priority tier the most recently flipped to `cross_stage_conflict` rises.
9. **Auth via blueprint `before_request` hook** (existing pattern from G2/G3). All 4 resolution endpoints are POST-only; the listing route + form-expander routes are GET. Anonymous → 302 to /admin/login.
10. **`processing_status_audit` writes use the same shape G2 established** — `(agenda_item_id, from_status, to_status, action, actor, actor_role='admin', reason, payload::jsonb)`. The `payload` JSONB carries action-specific metadata (manual_headline, override_instruction, new_facts_json, etc.).
11. **Stage-2 re-run reconcile path:** if `reconcile_stages(..., already_retried=True)` returns `accept`, the resolution lands; if it returns `mark_cross_stage_conflict` (still conflicts), `processing_status` stays at `cross_stage_conflict` and the audit row records the failed-resolution attempt. The admin can try a different action. **NOT silently retried again** — admin re-runs are explicit.
12. **TOCTOU concurrency guard on LLM-touching paths.** `re_prompt_stage_2` and `edit_stage_1_facts` run an LLM call (~3-5s) between the initial item-load read and the persistence UPDATE. Two admins on the same item — one accepts Stage 2 quickly while the other is mid-LLM — would race; the slow LLM's UPDATE would silently overwrite the fast resolution. Guard: every persistence UPDATE in these two paths includes `AND processing_status = 'cross_stage_conflict'` in its WHERE. If the UPDATE affects 0 rows (`cur.rowcount == 0`), raise `ConflictAlreadyResolvedError` and the route maps it to a 409 + plain-text "this item was resolved by another admin during your LLM call." **G4 review fix-up (2026-05-10):** `edit_stage_1_facts` has a fifth UPDATE — the early `extracted_facts` write — which is also guarded by the same predicate and fails fast on lost race before the LLM call (saves spend; writes a distinct `edit_stage1_facts_lost_race_pre_llm` audit row). **`accept_stage_*` serialize via `FOR UPDATE OF ai` in `_load_conflict_item`**; concurrent admins block at the SELECT, the second admin sees the post-resolution state and `_load_conflict_item` returns None → route 404. (Earlier prose claimed plain SELECT was sufficient because the transactions are short — under READ COMMITTED that left a microsecond-wide silent-overwrite window for dual-`accept_stage_1` calls with different manual headlines; the `FOR UPDATE OF ai` change closes it.)
13. **Audit row on race-loss.** When the TOCTOU guard fires (LLM-touching UPDATE affects 0 rows), still write a `processing_status_audit` row with `from_status=to_status=<whatever the row is now>`, `action='re_prompt_stage2_lost_race'` (or `'edit_stage1_facts_lost_race'`), and a payload capturing the input that the admin attempted. This preserves the trail of "admin tried X but lost the race to admin Y" for auditability.
14. **Score-overrides preservation:** `accept_stage_1` and `accept_stage_2` write `processing_status='completed'` directly without recomputing scores via floors — the admin's manual headline/why_it_matters is the source of truth; downstream floors don't apply. `re_prompt_stage_2` and `edit_stage_1_facts` DO recompute floors (the LLM output deserves its deterministic post-pass).

---

## File structure

```
src/docket/services/conflict_resolution.py                  (NEW, ~280 lines)
src/docket/services/query.py                                (+1 helper, ~50 lines)
src/docket/web/admin.py                                     (+~220 lines)
src/docket/web/templates/admin/review_conflicts.html        (NEW, ~140 lines)
src/docket/web/templates/admin/_conflict_resolved.html      (NEW, ~30 lines)
src/docket/web/templates/admin/_conflict_form_accept_s1.html (NEW, ~25 lines)
src/docket/web/templates/admin/_conflict_form_re_prompt.html (NEW, ~20 lines)
src/docket/web/templates/admin/_conflict_form_edit_facts.html (NEW, ~30 lines)
src/docket/web/static/tweaks.css                            (+~70 lines)
tests/integration/test_conflict_resolution.py               (NEW, ~30-35 tests)
```

Plus a one-line nav-link addition to 5 admin templates (same pattern as G3's "Badge audit" link).

---

## Conventions inherited from G1/G2/G3

- **Auth:** blueprint-level `before_request` hook in `admin.py:25-33`. New routes get auth automatically.
- **Cursor:** `db_cursor()` for dict-row reads, `db()` for tuple writes inside a transaction.
- **Test fixture: `_Bag`** — copy the G2/G3 pattern. Self-contained, doesn't import from sibling test files.
- **Test pre-flight:** `pytest.mark.skipif("railway.internal" in DATABASE_URL ...)`.
- **Admin client:** `c.session_transaction()` to set `sess["admin_user"] = "tester"`.
- **Multi-city parametrization:** apply to the entry-point 200 test only; full parametrization is bloat.
- **CHECK constraints (migration 013):**
  - `processing_status_enum` includes `'cross_stage_conflict'`, `'completed'`
  - `actor_role` includes `'admin'`
  - `processing_status_audit.action` is free TEXT (no CHECK) — use snake_case forms

---

## Task 1: `list_cross_stage_conflicts` query helper

**Files:**
- Modify: `src/docket/services/query.py` (add helper near `list_data_debt_items`)
- Test: `tests/integration/test_conflict_resolution.py` (NEW)

- [ ] **Step 1.1: Sketch the test file shell with shared `_Bag` fixture**

Create `tests/integration/test_conflict_resolution.py`:

```python
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
    """Test-data tracker. Cleans up in FK order: audit → items → meetings."""

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
```

- [ ] **Step 1.2: Write the first failing test for the helper**

Append:

```python
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
```

- [ ] **Step 1.3: Run, confirm fail with AttributeError**

Run: `cd ~/docket-pub-pf2-track-3 && venv/bin/pytest tests/integration/test_conflict_resolution.py::test_list_cross_stage_conflicts_returns_only_conflicted_items -xvs`

Expected: FAIL with `AttributeError: module 'docket.services.query' has no attribute 'list_cross_stage_conflicts'`.

- [ ] **Step 1.4: Implement the helper**

Insert into `src/docket/services/query.py`, just after `list_failed_permanent_items_all_cities` (around line 1995). Match the dict-row + sentinel-pagination shape:

```python
def list_cross_stage_conflicts(
    *,
    limit: int = 25,
    offset: int = 0,
) -> list[dict]:
    """Return items at ``processing_status='cross_stage_conflict'`` for
    the G4 admin viewer. Spec decision #93.

    Sort: ``data_debt_priority DESC, updated_at DESC`` — high-priority
    conflicts surface first; within a priority tier the most recently
    flipped to conflict state rises. Same priority sort as F5 / G2 /
    G3 admin queues for consistency.

    Pagination: caller passes ``limit`` (sentinel-pagination compatible
    — caller passes ``limit+1`` and slices). Page size 25 in the route
    handler — these rows are heavy (full Stage 1 facts JSON + Stage 2
    rationale + raw description rendered side-by-side).

    Returns dicts, not :class:`AgendaItem` objects, because the admin
    queue template needs a flatter projection (joined city + meeting
    context) than the v3 Smart Brevity Card surface.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT
              ai.id,
              ai.title,
              ai.description,
              ai.dollars_amount,
              ai.extracted_facts,
              ai.headline,
              ai.why_it_matters,
              ai.score_overrides,
              ai.data_debt_priority::text AS data_debt_priority,
              ai.processing_status::text  AS processing_status,
              ai.updated_at,
              mt.id            AS meeting_id,
              mt.meeting_date,
              mt.title         AS meeting_title,
              m.id             AS municipality_id,
              m.slug           AS municipality_slug,
              m.name           AS municipality_name
            FROM agenda_items ai
            JOIN meetings mt ON mt.id = ai.meeting_id
            JOIN municipalities m ON m.id = mt.municipality_id
            WHERE ai.processing_status = 'cross_stage_conflict'
            ORDER BY
                CASE ai.data_debt_priority::text
                    WHEN 'high'   THEN 3
                    WHEN 'normal' THEN 2
                    WHEN 'low'    THEN 1
                    ELSE 0
                END DESC,
                ai.updated_at DESC NULLS LAST,
                ai.id DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        return [dict(row) for row in cur.fetchall()]
```

- [ ] **Step 1.5: Run, confirm pass**

Run: `venv/bin/pytest tests/integration/test_conflict_resolution.py::test_list_cross_stage_conflicts_returns_only_conflicted_items -xvs`. Expected: PASS.

- [ ] **Step 1.6: Add sort + pagination tests**

Append:

```python
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
```

Run: `venv/bin/pytest tests/integration/test_conflict_resolution.py -k list_cross_stage_conflicts -xvs`. Expected: 3 passes.

- [ ] **Step 1.7: Commit**

```bash
cd ~/docket-pub-pf2-track-3
git add src/docket/services/query.py tests/integration/test_conflict_resolution.py
git commit -m "feat(query): list_cross_stage_conflicts helper for G4 admin viewer"
```

---

## Task 2: `/admin/review/conflicts` listing route + template

**Files:**
- Modify: `src/docket/web/admin.py`
- Create: `src/docket/web/templates/admin/review_conflicts.html`
- Modify: `src/docket/web/static/tweaks.css`
- Test: `tests/integration/test_conflict_resolution.py` (extend)

- [ ] **Step 2.1: Write failing route tests**

Append:

```python
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
    # No conflict items in the bag → empty state should render.
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
```

- [ ] **Step 2.2: Run, confirm 404**

Run: `venv/bin/pytest tests/integration/test_conflict_resolution.py -k review_conflicts -xvs`. Expected: 404s.

- [ ] **Step 2.3: Add the listing route to `admin.py`**

Append to `admin.py` (after the G3 section). Add the import at the top of the section:

```python
# --- Cross-Stage Conflict Resolution UI (G4 — decision #93) -----------------


_CONFLICTS_PAGE_SIZE = 25  # heavier rows than G3; smaller page


@bp.route("/review/conflicts")
def review_conflicts():
    """List items in ``processing_status='cross_stage_conflict'`` for
    admin resolution. Spec decision #93.

    Side-by-side display per row: original title + description + Stage 1
    structured facts (extracted_facts JSONB) + Stage 2 verdict (procedural)
    + conflict reasons array (score_overrides->'conflicts'). Four
    HTMX-powered resolution actions per row, each routing to a service
    function in :mod:`docket.services.conflict_resolution`.

    Sort matches G2/G3 admin queues: priority DESC, updated_at DESC.
    Page size 25 (smaller than F5/G2/G3 50 because rows render
    side-by-side, much heavier per-row).

    Auth: blueprint-level ``before_request`` hook redirects unauthed.
    """
    offset = _parse_offset(request.args.get("offset"))

    rows_plus_one = query.list_cross_stage_conflicts(
        limit=_CONFLICTS_PAGE_SIZE + 1,
        offset=offset,
    )
    rows = rows_plus_one[:_CONFLICTS_PAGE_SIZE]
    next_offset = (
        offset + _CONFLICTS_PAGE_SIZE
        if len(rows_plus_one) > _CONFLICTS_PAGE_SIZE
        else None
    )

    return render_template(
        "admin/review_conflicts.html",
        rows=rows,
        offset=offset,
        next_offset=next_offset,
    )
```

- [ ] **Step 2.4: Create the listing template**

Create `src/docket/web/templates/admin/review_conflicts.html`:

```html
{% extends "base.html" %}
{% block title %}Cross-Stage Conflicts — Admin — docket.pub{% endblock %}

{#
  G4 — Cross-Stage Conflict Resolution UI (spec decision #93).

  Lists items at processing_status='cross_stage_conflict'. Each row
  renders side-by-side: original title + description + Stage 1 facts
  (extracted_facts JSONB) + Stage 2 verdict (procedural; rendered
  implicitly by the absence of headline/why_it_matters) + conflict
  reasons (from score_overrides.conflicts).

  Resolution actions per row (HTMX-driven):
    1. Accept Stage 1 — admin authors manual headline + why_it_matters
    2. Accept Stage 2 — clears Stage 1 facts that confused things
    3. Re-prompt Stage 2 — admin writes a one-liner override; system
       re-runs Stage 2 with that instruction injected into the prompt
    4. Edit Stage 1 facts — admin corrects misclassified facts;
       system re-runs Stage 2 with corrected facts

  Each row's <tr> has id="row-{{ item.id }}" so HTMX swaps target it.

  Once a v3 pipeline orchestrator (B5) lands, automatic conflict
  generation flips on (FINAL-3 IMPACT_FIRST_ENABLED=true). Until then
  this surface is exercisable but won't see organic traffic.
#}

{% block content %}
<div style="display: flex; justify-content: space-between; align-items: center;">
  <h1>Cross-Stage Conflicts</h1>
  <form method="post" action="{{ url_for('auth.logout') }}" style="margin: 0;">
    <button type="submit" style="font-size: 0.85rem;">Sign Out ({{ session.get('admin_user', '') }})</button>
  </form>
</div>

<p><a href="{{ url_for('admin.list_members') }}">← Council Members</a> &middot;
   <a href="{{ url_for('admin.badges_audit') }}">Badge audit</a> &middot;
   <a href="{{ url_for('admin.calibration') }}">Calibration</a> &middot;
   <a href="{{ url_for('admin.data_debt') }}">OCR queue</a> &middot;
   <a href="{{ url_for('admin.errors') }}">Errors queue</a> &middot;
   <a href="{{ url_for('admin.ai_panel') }}">AI Pipeline</a></p>

<p class="t-meta">
  Items where Stage 1 (extracted facts) and Stage 2 (Smart Brevity verdict)
  disagreed on whether the item is substantive. Resolve to clear the
  ⚠️ "Verification in progress" pill on citizen-facing cards (decision #72).
</p>

{% if not rows %}
  <p class="t-meta">No items in cross_stage_conflict state. The v3 pipeline
  has not produced any conflicts (or all have been resolved).</p>
{% else %}
<table class="conflict-queue">
{% for item in rows %}
  <tr id="row-{{ item.id }}">
    <td class="raw">
      <h3>{{ item.title }}</h3>
      <p class="t-meta">
        {{ item.municipality_name }} ·
        {{ item.meeting_date.strftime('%Y-%m-%d') if item.meeting_date else '—' }} ·
        priority: <code>{{ item.data_debt_priority }}</code>
      </p>
      <details><summary>Original description</summary>
        <pre class="raw-text">{{ item.description or '(empty)' }}</pre>
      </details>
      {% if item.dollars_amount %}
        <p class="t-meta">Dollars: ${{ '{:,}'.format(item.dollars_amount|int) }}</p>
      {% endif %}
    </td>

    <td class="stage-1">
      <h4>Stage 1 — Extracted facts</h4>
      <pre class="facts-json">{{ item.extracted_facts | tojson(indent=2) if item.extracted_facts else '(no facts)' }}</pre>
    </td>

    <td class="stage-2">
      <h4>Stage 2 — Verdict: PROCEDURAL</h4>
      <p>(no headline / why_it_matters generated)</p>
      {% set conflicts = (item.score_overrides or {}).get('conflicts', []) %}
      {% if conflicts %}
        <p class="t-meta">Conflict reasons:</p>
        <ul class="conflict-reasons">
          {% for reason in conflicts %}
            <li><code>{{ reason }}</code></li>
          {% endfor %}
        </ul>
      {% endif %}
    </td>

    <td class="actions">
      <button class="btn-accept-s1"
              hx-get="{{ url_for('admin.conflict_form_accept_s1', item_id=item.id) }}"
              hx-target="#row-{{ item.id }} .actions"
              hx-swap="innerHTML">
        ✅ Accept Stage 1
      </button>
      <form hx-post="{{ url_for('admin.conflict_accept_stage_2', item_id=item.id) }}"
            hx-target="#row-{{ item.id }}"
            hx-swap="outerHTML"
            style="display: block;">
        <button type="submit" class="btn-accept-s2">
          ❌ Accept Stage 2 (clear facts)
        </button>
      </form>
      <button class="btn-re-prompt"
              hx-get="{{ url_for('admin.conflict_form_re_prompt', item_id=item.id) }}"
              hx-target="#row-{{ item.id }} .actions"
              hx-swap="innerHTML">
        🔁 Re-prompt Stage 2
      </button>
      <button class="btn-edit-facts"
              hx-get="{{ url_for('admin.conflict_form_edit_facts', item_id=item.id) }}"
              hx-target="#row-{{ item.id }} .actions"
              hx-swap="innerHTML">
        📝 Edit Stage 1 facts
      </button>
    </td>
  </tr>
{% endfor %}
</table>

<p class="conflict-pager">
  {% if offset > 0 %}
    {% set prev_offset = (offset - 25) if (offset - 25) > 0 else 0 %}
    <a href="{{ url_for('admin.review_conflicts', offset=prev_offset if prev_offset > 0 else none) }}">← Previous</a>
  {% endif %}
  {% if next_offset %}
    <a href="{{ url_for('admin.review_conflicts', offset=next_offset) }}">Next →</a>
  {% endif %}
</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 2.5: Add CSS rules**

Append to `src/docket/web/static/tweaks.css`:

```css
/* G4 — cross-stage conflict resolution */
.conflict-queue { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.conflict-queue tr { border-bottom: 1px solid var(--rule, #e6e6e0); }
.conflict-queue td {
  vertical-align: top;
  padding: 0.6rem;
  width: 25%;
}
.conflict-queue .raw h3 { margin: 0 0 0.25rem 0; font-size: 1rem; }
.conflict-queue .stage-1 .facts-json,
.conflict-queue .raw .raw-text {
  font-family: var(--mono, ui-monospace, "JetBrains Mono", monospace);
  font-size: 0.8rem;
  background: var(--paper-2, #f6f6f4);
  padding: 0.4rem;
  border-radius: 3px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 18rem;
  overflow: auto;
}
.conflict-reasons {
  margin: 0.25rem 0;
  padding-left: 1.25rem;
  font-size: 0.8rem;
}
.conflict-reasons code {
  font-size: 0.75rem;
  background: #fff3cd;
  padding: 0.05rem 0.25rem;
  border-radius: 2px;
}
.conflict-queue .actions button,
.conflict-queue .actions form button {
  display: block;
  width: 100%;
  margin-bottom: 0.4rem;
  padding: 0.4rem 0.6rem;
  text-align: left;
  font-size: 0.85rem;
  cursor: pointer;
}
.conflict-queue .actions .btn-accept-s1 {
  background: #d4edda; border: 1px solid #155724; color: #155724;
}
.conflict-queue .actions .btn-accept-s2 {
  background: #f8d7da; border: 1px solid #721c24; color: #721c24;
}
.conflict-queue .actions .btn-re-prompt {
  background: #fff3cd; border: 1px solid #856404; color: #856404;
}
.conflict-queue .actions .btn-edit-facts {
  background: #d1ecf1; border: 1px solid #0c5460; color: #0c5460;
}
.conflict-form { padding: 0.4rem; }
.conflict-form label { display: block; font-size: 0.85rem; margin-bottom: 0.3rem; }
.conflict-form input, .conflict-form textarea {
  width: 100%; padding: 0.25rem 0.4rem; font-family: inherit;
}
.conflict-form .btn-submit {
  background: var(--paper-2, #f6f6f4); border: 1px solid var(--rule, #ccc);
  padding: 0.3rem 0.6rem; font-size: 0.85rem; cursor: pointer;
}
.conflict-pager { margin-top: 1rem; }
.conflict-pager a { margin-right: 1rem; }
.conflict-resolved {
  padding: 0.6rem;
  background: #d4edda;
  border-left: 3px solid #155724;
  font-size: 0.9rem;
}
.conflict-resolved.failed {
  background: #fff3cd;
  border-left-color: #856404;
}
```

- [ ] **Step 2.6: Run listing tests + confirm pass**

The form-expander route names referenced in the template (`conflict_form_accept_s1`, `conflict_form_re_prompt`, `conflict_form_edit_facts`) don't exist yet — Tasks 3, 5, 6 land them. **Forward-declaration stubs** are needed so Jinja `url_for` resolves. Add stubs at the bottom of the G4 section in `admin.py`:

```python
# Forward-declaration stubs (replaced by real handlers in Tasks 3, 5, 6).
# Without these the Task 2 listing template can't render — Jinja chokes
# on unknown url_for endpoints at template-render time.
@bp.route("/review/conflicts/<int:item_id>/_form/accept-stage-1")
def conflict_form_accept_s1(item_id: int):
    abort(501)


@bp.route("/review/conflicts/<int:item_id>/_form/re-prompt")
def conflict_form_re_prompt(item_id: int):
    abort(501)


@bp.route("/review/conflicts/<int:item_id>/_form/edit-facts")
def conflict_form_edit_facts(item_id: int):
    abort(501)


@bp.route("/review/conflicts/<int:item_id>/accept-stage-2", methods=["POST"])
def conflict_accept_stage_2(item_id: int):
    abort(501)
```

(Task 4 lands the real `conflict_accept_stage_2` handler; the stub keeps Task 2 passable.)

Run: `venv/bin/pytest tests/integration/test_conflict_resolution.py -k review_conflicts -xvs`. Expected: 7 passes (4 city parametrize + redirect + side-by-side + empty state + pagination).

- [ ] **Step 2.7: Commit**

```bash
git add src/docket/web/admin.py \
        src/docket/web/templates/admin/review_conflicts.html \
        src/docket/web/static/tweaks.css \
        tests/integration/test_conflict_resolution.py
git commit -m "feat(admin): G4 cross-stage conflict listing with side-by-side facts/verdict"
```

---

## Task 3: `accept_stage_1` — manual headline/why_it_matters

**Files:**
- Create: `src/docket/services/conflict_resolution.py`
- Modify: `src/docket/web/admin.py`
- Create: `src/docket/web/templates/admin/_conflict_form_accept_s1.html`
- Create: `src/docket/web/templates/admin/_conflict_resolved.html`
- Test: `tests/integration/test_conflict_resolution.py` (extend)

- [ ] **Step 3.1: Write failing tests**

Append:

```python
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
```

- [ ] **Step 3.2: Run, confirm fail**

Run: `venv/bin/pytest tests/integration/test_conflict_resolution.py -k accept_s1 -xvs`. Expected: 10 fails.

- [ ] **Step 3.3: Create the service module**

Create `src/docket/services/conflict_resolution.py`:

```python
"""Cross-stage conflict resolution actions (G4 — spec decision #93).

Each resolution action:
- Validates inputs (length caps + Pydantic for fact edits).
- Updates ``agenda_items`` (clearing/setting fields per the action).
- Records an audit row in ``processing_status_audit`` with the
  from/to status, action verb, actor, and action-specific payload.
- Returns a result dict the route handler renders into the swap-target
  partial.

Two of the four actions (``re_prompt_stage_2``, ``edit_stage_1_facts``)
re-run Stage 2 of the v3 pipeline. They use a private helper
``_rerun_stage2`` that calls ``rewrite.rewrite_item`` →
``floors.apply_score_floors`` → ``reconcile.reconcile_stages``. This
helper is a minimal Stage 2 re-run path; B5 (the cross-track
convergence task) will later subsume it into a full per-item
orchestrator. G4 ships before B5 because decision #93 is required
before ``IMPACT_FIRST_ENABLED=true`` flips the worker.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md
decisions #45, #72, #93.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal

from docket.ai.extraction_schema import StructuredFacts
from docket.ai.floors import apply_score_floors
from docket.ai.reconcile import reconcile_stages
from docket.ai.rewrite import rewrite_item
from docket.db import db
from docket.services.badges import get_enabled_policy_slugs

log = logging.getLogger(__name__)


# Length caps mirror ItemRewrite Pydantic constraints (rewrite_schema.py).
HEADLINE_MIN = 10
HEADLINE_MAX = 60
WHY_IT_MATTERS_MIN = 1
WHY_IT_MATTERS_MAX = 200
OVERRIDE_INSTRUCTION_MAX = 500
REASON_MAX = 500


class ConflictValidationError(ValueError):
    """Raised when admin input fails length/format validation."""


class ConflictAlreadyResolvedError(RuntimeError):
    """Raised when a TOCTOU race fires: between the load-conflict-item read
    and the persistence UPDATE, another admin (or the worker) flipped the
    item out of cross_stage_conflict state. The route maps this to 409 +
    a plain-text "this item was resolved during your LLM call" message
    rendered into the form's .form-error span via the htmx:response-error
    handler. Decision #12.
    """


@dataclass
class ResolutionResult:
    """Returned by every resolution function. Route maps to swap-target."""
    item_id: int
    new_status: str  # 'completed' or 'cross_stage_conflict' (re-prompt may stay)
    action: str
    success: bool  # False only when re-prompt/edit-facts still conflicts
    detail: str | None = None  # human-readable note for the swap target


def _audit(cur, item_id: int, from_status: str, to_status: str,
            action: str, actor: str, *,
            reason: str | None = None,
            payload: dict | None = None) -> None:
    """Write a single processing_status_audit row.

    Mirrors the G2 retry/escalate pattern (admin.py:300-311) for shape
    consistency."""
    cur.execute(
        """
        INSERT INTO processing_status_audit
          (agenda_item_id, from_status, to_status, action,
           actor, actor_role, reason, payload)
        VALUES
          (%s,
           %s::processing_status_enum,
           %s::processing_status_enum,
           %s, %s, 'admin', %s, %s::jsonb)
        """,
        (item_id, from_status, to_status, action, actor, reason,
         json.dumps(payload) if payload else None),
    )


def _load_conflict_item(cur, item_id: int) -> dict | None:
    """Fetch the item + meeting context for a resolution action.

    Returns None if the item doesn't exist OR isn't in cross_stage_conflict.
    Both 'not found' and 'wrong state' map to 404 at the route layer
    so admins can't silently overwrite a completed item.
    """
    cur.execute(
        """
        SELECT ai.id, ai.title, ai.description, ai.sponsor,
               ai.dollars_amount, ai.topic, ai.is_consent,
               ai.extracted_facts, ai.score_overrides,
               ai.processing_status::text AS processing_status,
               m.id   AS municipality_id,
               m.name AS city_name
          FROM agenda_items ai
          JOIN meetings mt ON mt.id = ai.meeting_id
          JOIN municipalities m ON m.id = mt.municipality_id
         WHERE ai.id = %s
        """,
        (item_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    item = dict(zip([
        "id", "title", "description", "sponsor", "dollars_amount",
        "topic", "is_consent", "extracted_facts", "score_overrides",
        "processing_status", "municipality_id", "city_name",
    ], row))
    if item["processing_status"] != "cross_stage_conflict":
        return None
    return item


# ---------------------------------------------------------------------------
# Action 1 — Accept Stage 1 (manual headline/why_it_matters)
# ---------------------------------------------------------------------------


def accept_stage_1(item_id: int, *,
                    manual_headline: str,
                    manual_why_it_matters: str,
                    actor: str) -> ResolutionResult:
    """Admin says: 'this IS substantive — here's what it should say.'

    Persists manual headline + why_it_matters; flips
    ``processing_status`` to 'completed'. Stage 1 facts kept intact
    (Stage 1 was correct, decision #93 path 1).

    Length caps mirror ItemRewrite Pydantic constraints to ensure
    consistency with LLM-generated outputs (decision #87).

    Raises ConflictValidationError if input fails validation.
    Raises LookupError if the item isn't in cross_stage_conflict.
    """
    headline = manual_headline.strip()
    why = manual_why_it_matters.strip()

    if len(headline) < HEADLINE_MIN or len(headline) > HEADLINE_MAX:
        raise ConflictValidationError(
            f"manual_headline must be {HEADLINE_MIN}-{HEADLINE_MAX} chars"
        )
    if len(why) < WHY_IT_MATTERS_MIN or len(why) > WHY_IT_MATTERS_MAX:
        raise ConflictValidationError(
            f"manual_why_it_matters must be {WHY_IT_MATTERS_MIN}-"
            f"{WHY_IT_MATTERS_MAX} chars"
        )

    with db() as conn, conn.cursor() as cur:
        item = _load_conflict_item(cur, item_id)
        if item is None:
            raise LookupError(f"item {item_id} not in cross_stage_conflict")

        cur.execute(
            """
            UPDATE agenda_items
               SET headline = %s,
                   why_it_matters = %s,
                   processing_status = 'completed'::processing_status_enum,
                   updated_at = NOW()
             WHERE id = %s
            """,
            (headline, why, item_id),
        )
        _audit(
            cur, item_id,
            from_status="cross_stage_conflict",
            to_status="completed",
            action="accept_stage1",
            actor=actor,
            payload={
                "manual_headline": headline,
                "manual_why_it_matters": why,
            },
        )

    log.info("admin accept_stage1: item_id=%s actor=%s", item_id, actor)
    return ResolutionResult(
        item_id=item_id,
        new_status="completed",
        action="accept_stage1",
        success=True,
        detail="Stage 1 accepted; manual headline + why_it_matters applied.",
    )
```

- [ ] **Step 3.4: Add the routes to `admin.py`**

Replace the `accept_stage_1` and `conflict_form_accept_s1` stubs (only Task 3's stubs; leave the other forward-decl stubs for now). Append to the G4 section:

```python
from docket.services import conflict_resolution as conflict_svc


@bp.route("/review/conflicts/<int:item_id>/_form/accept-stage-1")
def conflict_form_accept_s1(item_id: int):
    """GET-only HTMX form expander — renders the inline accept-Stage-1 form
    for a single item (manual_headline + manual_why_it_matters inputs).

    Pre-conditional: the item must exist and be in cross_stage_conflict;
    otherwise 404 to avoid leaking the form for a completed item."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, title, processing_status::text "
            "FROM agenda_items WHERE id = %s",
            (item_id,),
        )
        row = cur.fetchone()
    if row is None or row["processing_status"] != "cross_stage_conflict":
        abort(404)

    return render_template(
        "admin/_conflict_form_accept_s1.html",
        item_id=item_id,
    )


@bp.route("/review/conflicts/<int:item_id>/accept-stage-1", methods=["POST"])
def conflict_accept_stage_1(item_id: int):
    """POST-only: persist manual_headline + manual_why_it_matters,
    flip status to completed, write audit row.

    Returns the rendered ``_conflict_resolved.html`` partial as the
    HTMX swap target. Validation errors return 400 + plain-text body
    (HTMX will render in-place; no full re-render of the row).
    """
    actor = session.get("admin_user", "unknown")
    headline = request.form.get("manual_headline", "")
    why = request.form.get("manual_why_it_matters", "")

    try:
        result = conflict_svc.accept_stage_1(
            item_id,
            manual_headline=headline,
            manual_why_it_matters=why,
            actor=actor,
        )
    except conflict_svc.ConflictValidationError as e:
        return (str(e), 400)
    except LookupError:
        abort(404)

    return render_template(
        "admin/_conflict_resolved.html",
        result=result,
    )
```

(Note: replace the Task 2 stub for `conflict_form_accept_s1` with the real handler. Leave the other stubs for now.)

- [ ] **Step 3.5: Create the form + resolved partials**

Create `src/docket/web/templates/admin/_conflict_form_accept_s1.html`:

```html
{#
  G4 inline form — Accept Stage 1 (manual headline + why_it_matters).
  Loaded into #row-N .actions cell on hx-get; on submit, swaps the
  whole #row-N <tr> with the _conflict_resolved.html partial.

  Length validation: headline 10-60 chars; why_it_matters 1-200 chars.
  Server-side enforcement is authoritative; client-side maxlength is
  a UX hint only.

  Decision #6 — validation errors return 400 + plain-text body. The
  hx-on:htmx:response-error handler routes the response text into the
  .form-error span without swapping the row, so the admin keeps the
  form open and sees what's wrong.
#}
<form class="conflict-form"
      hx-post="{{ url_for('admin.conflict_accept_stage_1', item_id=item_id) }}"
      hx-target="#row-{{ item_id }}"
      hx-swap="outerHTML"
      hx-on:htmx:response-error="this.querySelector('.form-error').textContent = event.detail.xhr.responseText">
  <label>
    Headline (10–60 chars)
    <input type="text" name="manual_headline"
           minlength="10" maxlength="60" required
           placeholder="e.g. City awards $4.2M HVAC contract">
  </label>
  <label>
    Why it matters (1–200 chars)
    <input type="text" name="manual_why_it_matters"
           minlength="1" maxlength="200" required
           placeholder="Direct consequence for residents.">
  </label>
  <button type="submit" class="btn-submit">✅ Confirm Accept Stage 1</button>
  <span class="form-error" role="alert"></span>
</form>
```

Create `src/docket/web/templates/admin/_conflict_resolved.html`:

```html
{#
  G4 HTMX swap target after a resolution action.
  outerHTML-swapped into #row-N <tr>. Renders a one-line confirmation
  row with the action verb + new status. The original conflict row is
  gone from the DOM; once the page is refreshed, the item won't appear
  in the list anymore (filtered out by the cross_stage_conflict
  predicate in list_cross_stage_conflicts).

  For re_prompt_stage_2 / edit_stage_1_facts where the resolution may
  itself fail to converge (still in conflict), success=False renders
  the .failed variant — the row remains but flagged as needing
  another attempt.
#}
<tr id="row-{{ result.item_id }}">
  <td colspan="4" class="conflict-resolved {% if not result.success %}failed{% endif %}">
    <strong>
      {% if result.success %}
        ✅ Resolved
      {% else %}
        ⚠️ Still in conflict
      {% endif %}
    </strong>
    via <code>{{ result.action }}</code> ·
    new status: <code>{{ result.new_status }}</code>
    {% if result.detail %} · {{ result.detail }}{% endif %}
  </td>
</tr>
```

- [ ] **Step 3.6: Run, confirm pass**

Run: `venv/bin/pytest tests/integration/test_conflict_resolution.py -k accept_s1 -xvs`. Expected: 10 passes.

- [ ] **Step 3.7: Commit**

```bash
git add src/docket/services/conflict_resolution.py \
        src/docket/web/admin.py \
        src/docket/web/templates/admin/_conflict_form_accept_s1.html \
        src/docket/web/templates/admin/_conflict_resolved.html \
        tests/integration/test_conflict_resolution.py
git commit -m "feat(admin): G4 accept_stage_1 — manual headline+why_it_matters resolution"
```

---

## Task 4: `accept_stage_2` — clear Stage 1 facts

**Files:**
- Modify: `src/docket/services/conflict_resolution.py`
- Modify: `src/docket/web/admin.py`
- Test: `tests/integration/test_conflict_resolution.py` (extend)

`accept_stage_2` is the simplest action — admin says Stage 2's "procedural" verdict was right; clear the Stage 1 facts that confused the reconcile gate; flip status to completed (as procedural — no headline/why_it_matters). No LLM call, no form (the listing template's button is a single-click form posting directly).

- [ ] **Step 4.1: Write failing tests**

Append:

```python
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
```

- [ ] **Step 4.2: Run, confirm fail (501 from stub)**

Run: `venv/bin/pytest tests/integration/test_conflict_resolution.py -k accept_s2 -xvs`. Expected: fails on the 200/405/etc assertions because stub returns 501 for everything.

- [ ] **Step 4.3: Implement the service function**

Append to `src/docket/services/conflict_resolution.py`:

```python
def accept_stage_2(item_id: int, *,
                    actor: str,
                    reason: str | None = None) -> ResolutionResult:
    """Admin says: 'Stage 2 was right — this IS procedural.'

    Clears Stage 1 facts that confused the reconcile gate; clears
    headline/why_it_matters; flips status to 'completed'. The item
    will render via the procedural Smart Brevity Card variant
    (just title, no headline/why_it_matters) — same as any other
    procedural item.

    No LLM call.

    Raises LookupError if item not in cross_stage_conflict.
    """
    if reason is not None:
        reason = reason.strip()
        if len(reason) > REASON_MAX:
            raise ConflictValidationError(
                f"reason must be at most {REASON_MAX} chars"
            )
        reason = reason or None

    with db() as conn, conn.cursor() as cur:
        item = _load_conflict_item(cur, item_id)
        if item is None:
            raise LookupError(f"item {item_id} not in cross_stage_conflict")

        cur.execute(
            """
            UPDATE agenda_items
               SET extracted_facts = NULL,
                   headline = NULL,
                   why_it_matters = NULL,
                   processing_status = 'completed'::processing_status_enum,
                   updated_at = NOW()
             WHERE id = %s
            """,
            (item_id,),
        )
        _audit(
            cur, item_id,
            from_status="cross_stage_conflict",
            to_status="completed",
            action="accept_stage2",
            actor=actor,
            reason=reason,
        )

    log.info("admin accept_stage2: item_id=%s actor=%s", item_id, actor)
    return ResolutionResult(
        item_id=item_id,
        new_status="completed",
        action="accept_stage2",
        success=True,
        detail="Stage 1 facts cleared; item marked procedural.",
    )
```

- [ ] **Step 4.4: Replace the stub route in `admin.py`**

Replace the `conflict_accept_stage_2` stub with the real handler:

```python
@bp.route("/review/conflicts/<int:item_id>/accept-stage-2", methods=["POST"])
def conflict_accept_stage_2(item_id: int):
    """POST-only: clear Stage 1 facts + flip status to completed.

    No form expander — the listing template's button posts directly.
    Optional ``reason`` field in the body is persisted to
    ``processing_status_audit.reason``.
    """
    actor = session.get("admin_user", "unknown")
    reason = request.form.get("reason")

    try:
        result = conflict_svc.accept_stage_2(
            item_id, actor=actor, reason=reason,
        )
    except conflict_svc.ConflictValidationError as e:
        return (str(e), 400)
    except LookupError:
        abort(404)

    return render_template("admin/_conflict_resolved.html", result=result)
```

- [ ] **Step 4.5: Run, confirm all G4.3b tests pass**

Run: `venv/bin/pytest tests/integration/test_conflict_resolution.py -k accept_s2 -xvs`. Expected: 7 passes.

- [ ] **Step 4.6: Commit**

```bash
git add src/docket/services/conflict_resolution.py \
        src/docket/web/admin.py \
        tests/integration/test_conflict_resolution.py
git commit -m "feat(admin): G4 accept_stage_2 — clear Stage 1 facts, mark procedural"
```

---

## Task 5: `re_prompt_stage_2` — admin override + Stage 2 re-run

**Files:**
- Modify: `src/docket/services/conflict_resolution.py` (add `_rerun_stage2` + `re_prompt_stage_2`)
- Modify: `src/docket/web/admin.py`
- Create: `src/docket/web/templates/admin/_conflict_form_re_prompt.html`
- Test: `tests/integration/test_conflict_resolution.py` (extend, with LLM mock)

This task introduces the `_rerun_stage2` helper that two actions share. It calls the existing `rewrite_item → apply_score_floors → reconcile_stages` chain.

- [ ] **Step 5.1: Write failing tests with LLM mock**

Append:

```python
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
    """Happy path: admin override → Stage 2 returns substantive →
    reconcile accepts → status flips to completed."""
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
    """Sad path: admin override → Stage 2 STILL says procedural →
    reconcile says still in conflict → status stays at conflict;
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
```

- [ ] **Step 5.2: Run, confirm fail**

Run: `venv/bin/pytest tests/integration/test_conflict_resolution.py -k re_prompt -xvs`. Expected: fails.

- [ ] **Step 5.3: Implement `_rerun_stage2` + `re_prompt_stage_2` in the service**

Append to `src/docket/services/conflict_resolution.py`:

```python
@dataclass
class _RerunOutcome:
    rewrite: Any  # ItemRewrite
    score_overrides_obj: Any  # ScoreOverrides from floors
    reconcile_action: str  # 'accept' | 'mark_cross_stage_conflict'
    conflicts: list[str]
    served_model: str


class _ItemView:
    """Lightweight item view for the v3 pipeline.

    rewrite.rewrite_item expects an object exposing: title, description,
    sponsor, dollars_amount, topic, is_consent, city_name. This wrapper
    converts a DB row dict into that shape.
    """
    def __init__(self, item: dict):
        self.id = item.get("id")
        self.title = item.get("title")
        self.description = item.get("description")
        self.sponsor = item.get("sponsor")
        self.dollars_amount = item.get("dollars_amount")
        self.topic = item.get("topic")
        self.is_consent = item.get("is_consent")
        self.city_name = item.get("city_name")


def _rerun_stage2(
    item: dict,
    facts: StructuredFacts,
    *,
    override_instruction: str | None = None,
) -> _RerunOutcome:
    """Run Stage 2 of the v3 pipeline against an item with optional override.

    Calls rewrite.rewrite_item → floors.apply_score_floors →
    reconcile.reconcile_stages. Returns the structured outcome the
    caller persists.

    This is a minimal Stage 2 re-run helper — B5 will subsume it when
    the cross-track per-item orchestrator lands. Until then this
    duplication is intentional (the orchestrator doesn't exist yet,
    and G4 must ship before FINAL-3 IMPACT_FIRST_ENABLED=true).
    """
    enabled_policy_slugs = get_enabled_policy_slugs(item["municipality_id"])
    item_view = _ItemView(item)

    rewrite, served_model = rewrite_item(
        item_view,
        facts,
        enabled_policy_slugs,
        extra_instruction=override_instruction,
    )
    score_overrides_obj = apply_score_floors(facts, item_view, rewrite)

    # Pass already_retried=True — admin re-runs are explicit, not the
    # auto-retry path. If reconcile still finds conflicts, mark and stop.
    result = reconcile_stages(facts, rewrite, item_view, already_retried=True)

    return _RerunOutcome(
        rewrite=rewrite,
        score_overrides_obj=score_overrides_obj,
        reconcile_action=result.action,
        conflicts=result.conflicts,
        served_model=served_model,
    )


def re_prompt_stage_2(item_id: int, *,
                       override_instruction: str,
                       actor: str) -> ResolutionResult:
    """Admin writes a one-liner override; system re-runs Stage 2.

    If the new Stage 2 rewrite reconciles cleanly (action='accept'),
    persist the new headline/why_it_matters/scores and flip status to
    completed.

    If reconcile still finds conflicts, leave status at
    cross_stage_conflict but record the failed-resolution attempt in
    the audit log. Admin can try a different action.

    Raises ConflictValidationError on input issues.
    Raises LookupError if item not in cross_stage_conflict.
    Bubbles up AIBudgetExceeded / AITransientError from the API call.
    """
    override = override_instruction.strip()
    if len(override) < 1 or len(override) > OVERRIDE_INSTRUCTION_MAX:
        raise ConflictValidationError(
            f"override_instruction must be 1-{OVERRIDE_INSTRUCTION_MAX} chars"
        )

    with db() as conn, conn.cursor() as cur:
        item = _load_conflict_item(cur, item_id)
        if item is None:
            raise LookupError(f"item {item_id} not in cross_stage_conflict")

        # Validate stored extracted_facts via Pydantic before re-running.
        # If the JSONB drifted, this surfaces it cleanly.
        if item["extracted_facts"] is None:
            raise ConflictValidationError(
                "item has no extracted_facts — re_prompt_stage_2 needs Stage 1 facts"
            )
        facts = StructuredFacts.model_validate(item["extracted_facts"])

    # Run Stage 2 OUTSIDE the transaction so the LLM call doesn't hold
    # the DB connection. The persist + audit happen in a fresh
    # transaction below.
    outcome = _rerun_stage2(item, facts, override_instruction=override)

    success = outcome.reconcile_action == "accept"
    new_status = "completed" if success else "cross_stage_conflict"

    score_overrides_payload = {
        "conflicts": outcome.conflicts,
        "original_ai_significance": outcome.score_overrides_obj.original_ai_significance,
        "final_significance": outcome.score_overrides_obj.final_significance,
        "original_ai_consent": outcome.score_overrides_obj.original_ai_consent,
        "final_consent": outcome.score_overrides_obj.final_consent,
        "triggers": outcome.score_overrides_obj.triggers,
        "admin_override_used": True,
    }

    # Decision #12 — TOCTOU guard. Both UPDATE branches scope the WHERE
    # to ``processing_status = 'cross_stage_conflict'`` so a concurrent
    # admin who resolved the row during our LLM call wins; ours becomes
    # a 0-row UPDATE and we raise ConflictAlreadyResolvedError. We still
    # write a race-loss audit row (decision #13) so the trail of "admin
    # tried X but lost the race" is preserved.
    with db() as conn, conn.cursor() as cur:
        if success:
            cur.execute(
                """
                UPDATE agenda_items
                   SET headline = %s,
                       why_it_matters = %s,
                       significance_score = %s,
                       consent_placement_score = %s,
                       score_overrides = %s::jsonb,
                       processing_status = 'completed'::processing_status_enum,
                       updated_at = NOW()
                 WHERE id = %s
                   AND processing_status = 'cross_stage_conflict'::processing_status_enum
                """,
                (
                    outcome.rewrite.headline,
                    outcome.rewrite.why_it_matters,
                    outcome.score_overrides_obj.final_significance,
                    outcome.score_overrides_obj.final_consent,
                    json.dumps(score_overrides_payload),
                    item_id,
                ),
            )
        else:
            # Still conflicting; just refresh score_overrides with the
            # new conflict list. Same TOCTOU guard.
            cur.execute(
                """
                UPDATE agenda_items
                   SET score_overrides = %s::jsonb,
                       updated_at = NOW()
                 WHERE id = %s
                   AND processing_status = 'cross_stage_conflict'::processing_status_enum
                """,
                (json.dumps(score_overrides_payload), item_id),
            )

        if cur.rowcount == 0:
            # Race lost — another admin resolved the row during our LLM
            # call. Read the current status so the audit row's
            # to_status reflects reality (not what we expected).
            cur.execute(
                "SELECT processing_status::text FROM agenda_items WHERE id = %s",
                (item_id,),
            )
            current = cur.fetchone()
            current_status = current[0] if current else "unknown"
            _audit(
                cur, item_id,
                from_status=current_status,
                to_status=current_status,
                action="re_prompt_stage2_lost_race",
                actor=actor,
                payload={
                    "override_instruction": override,
                    "would_have_set_status": new_status,
                    "served_model": outcome.served_model,
                    "is_substantive": outcome.rewrite.is_substantive,
                },
            )
            log.info(
                "admin re_prompt_stage2 lost race: item_id=%s actor=%s "
                "current_status=%s",
                item_id, actor, current_status,
            )
            raise ConflictAlreadyResolvedError(
                f"item {item_id} was resolved by another admin during the "
                "LLM call (current status: " + current_status + ")"
            )

        _audit(
            cur, item_id,
            from_status="cross_stage_conflict",
            to_status=new_status,
            action="re_prompt_stage2",
            actor=actor,
            payload={
                "override_instruction": override,
                "reconcile_action": outcome.reconcile_action,
                "conflicts": outcome.conflicts,
                "served_model": outcome.served_model,
                "is_substantive": outcome.rewrite.is_substantive,
            },
        )

    log.info(
        "admin re_prompt_stage2: item_id=%s actor=%s reconcile=%s",
        item_id, actor, outcome.reconcile_action,
    )
    return ResolutionResult(
        item_id=item_id,
        new_status=new_status,
        action="re_prompt_stage2",
        success=success,
        detail=(
            "Stage 2 re-ran with override; reconcile accepted."
            if success else
            "Stage 2 re-ran but reconcile still found conflicts. "
            "Try Edit Stage 1 facts or Accept Stage 2."
        ),
    )
```

- [ ] **Step 5.4: Replace the form-expander stub + add the action route**

In `admin.py`, replace the `conflict_form_re_prompt` stub:

```python
@bp.route("/review/conflicts/<int:item_id>/_form/re-prompt")
def conflict_form_re_prompt(item_id: int):
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, processing_status::text "
            "FROM agenda_items WHERE id = %s",
            (item_id,),
        )
        row = cur.fetchone()
    if row is None or row["processing_status"] != "cross_stage_conflict":
        abort(404)
    return render_template(
        "admin/_conflict_form_re_prompt.html",
        item_id=item_id,
    )


@bp.route("/review/conflicts/<int:item_id>/re-prompt-stage-2", methods=["POST"])
def conflict_re_prompt_stage_2(item_id: int):
    actor = session.get("admin_user", "unknown")
    override = request.form.get("override_instruction", "")

    try:
        result = conflict_svc.re_prompt_stage_2(
            item_id, override_instruction=override, actor=actor,
        )
    except conflict_svc.ConflictValidationError as e:
        return (str(e), 400)
    except conflict_svc.ConflictAlreadyResolvedError as e:
        # Decision #12 — TOCTOU race lost. 409 + plain-text body so the
        # form's hx-on:htmx:response-error handler renders the message
        # in-place; the form stays open.
        return (str(e), 409)
    except LookupError:
        abort(404)

    return render_template("admin/_conflict_resolved.html", result=result)
```

- [ ] **Step 5.5: Create the form partial**

Create `src/docket/web/templates/admin/_conflict_form_re_prompt.html`:

```html
{#
  G4 inline form — Re-prompt Stage 2 with admin override instruction.
  Server cap: 500 chars. Decision #6 — 4xx error rendering via
  hx-on:htmx:response-error. Decision #12 — TOCTOU race-loss returns
  409 with a clear message; the same handler renders it.
#}
<form class="conflict-form"
      hx-post="{{ url_for('admin.conflict_re_prompt_stage_2', item_id=item_id) }}"
      hx-target="#row-{{ item_id }}"
      hx-swap="outerHTML"
      hx-on:htmx:response-error="this.querySelector('.form-error').textContent = event.detail.xhr.responseText">
  <label>
    Override instruction (1–500 chars)
    <textarea name="override_instruction"
              minlength="1" maxlength="500" rows="3" required
              placeholder="e.g. The previous attempt missed that this IS a contract award..."></textarea>
  </label>
  <button type="submit" class="btn-submit">🔁 Re-run Stage 2</button>
  <span class="form-error" role="alert"></span>
</form>
```

- [ ] **Step 5.6: Run, confirm pass**

Run: `venv/bin/pytest tests/integration/test_conflict_resolution.py -k re_prompt -xvs`. Expected: 6 passes.

- [ ] **Step 5.7: Commit**

```bash
git add src/docket/services/conflict_resolution.py \
        src/docket/web/admin.py \
        src/docket/web/templates/admin/_conflict_form_re_prompt.html \
        tests/integration/test_conflict_resolution.py
git commit -m "feat(admin): G4 re_prompt_stage_2 — admin override + Stage 2 re-run"
```

---

## Task 6: `edit_stage_1_facts` — admin corrects facts + Stage 2 re-run

**Files:**
- Modify: `src/docket/services/conflict_resolution.py`
- Modify: `src/docket/web/admin.py`
- Create: `src/docket/web/templates/admin/_conflict_form_edit_facts.html`
- Test: `tests/integration/test_conflict_resolution.py` (extend)

`edit_stage_1_facts` is similar to `re_prompt_stage_2` but the admin edits the JSON facts directly instead of writing an override instruction. The corrected facts re-feed the v3 pipeline.

- [ ] **Step 6.1: Write failing tests**

Append:

```python
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
    """Happy path: admin corrects counterparty → Stage 2 returns
    substantive → reconcile accepts → status flips to completed."""
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
```

- [ ] **Step 6.2: Run, confirm fail**

Run: `venv/bin/pytest tests/integration/test_conflict_resolution.py -k edit_facts -xvs`. Expected: fails.

- [ ] **Step 6.3: Implement service function**

Append to `src/docket/services/conflict_resolution.py`:

```python
def edit_stage_1_facts(item_id: int, *,
                        new_facts_json: dict,
                        actor: str,
                        reason: str | None = None) -> ResolutionResult:
    """Admin corrects misclassified Stage 1 facts; system re-runs Stage 2
    with the corrected facts.

    new_facts_json is validated via the StructuredFacts Pydantic model.
    On validation failure raises ConflictValidationError.

    Persistence + reconciliation matches re_prompt_stage_2: if reconcile
    accepts → completed; if reconcile still conflicts → status stays at
    cross_stage_conflict.

    Raises LookupError if item not in cross_stage_conflict.
    """
    if reason is not None:
        reason = reason.strip()[:REASON_MAX] or None

    # Validate via Pydantic before any DB write.
    try:
        facts = StructuredFacts.model_validate(new_facts_json)
    except Exception as e:  # pydantic.ValidationError or otherwise
        raise ConflictValidationError(f"new_facts_json failed validation: {e}")

    # Persist the corrected facts in the SAME transaction that loads + audits.
    with db() as conn, conn.cursor() as cur:
        item = _load_conflict_item(cur, item_id)
        if item is None:
            raise LookupError(f"item {item_id} not in cross_stage_conflict")

        # Replace extracted_facts before the LLM call so the audit row's
        # payload references the canonicalized JSON the model_dump emits.
        canon_facts = facts.model_dump(mode="json")
        cur.execute(
            "UPDATE agenda_items SET extracted_facts = %s::jsonb WHERE id = %s",
            (json.dumps(canon_facts), item_id),
        )

    # Run Stage 2 outside the transaction (LLM I/O); refetch the item with
    # the now-current facts JSON for the rerun helper.
    outcome = _rerun_stage2(item, facts, override_instruction=None)

    success = outcome.reconcile_action == "accept"
    new_status = "completed" if success else "cross_stage_conflict"

    score_overrides_payload = {
        "conflicts": outcome.conflicts,
        "original_ai_significance": outcome.score_overrides_obj.original_ai_significance,
        "final_significance": outcome.score_overrides_obj.final_significance,
        "original_ai_consent": outcome.score_overrides_obj.original_ai_consent,
        "final_consent": outcome.score_overrides_obj.final_consent,
        "triggers": outcome.score_overrides_obj.triggers,
        "admin_facts_edit": True,
    }

    # Decision #12 — TOCTOU guard, same shape as re_prompt_stage_2. The
    # initial extracted_facts UPDATE earlier in this function is also at
    # risk; if a concurrent admin flipped the row to 'completed' between
    # _load_conflict_item and that UPDATE, the early UPDATE silently
    # affected 0 rows but the LLM call still ran. We still detect the
    # race here at persistence time and audit it. (Hardening the early
    # facts UPDATE the same way is possible but adds a transaction round
    # trip; the cost of running an extra LLM call on a lost race is the
    # tradeoff we accept for v1.)
    with db() as conn, conn.cursor() as cur:
        if success:
            cur.execute(
                """
                UPDATE agenda_items
                   SET headline = %s,
                       why_it_matters = %s,
                       significance_score = %s,
                       consent_placement_score = %s,
                       score_overrides = %s::jsonb,
                       processing_status = 'completed'::processing_status_enum,
                       updated_at = NOW()
                 WHERE id = %s
                   AND processing_status = 'cross_stage_conflict'::processing_status_enum
                """,
                (
                    outcome.rewrite.headline,
                    outcome.rewrite.why_it_matters,
                    outcome.score_overrides_obj.final_significance,
                    outcome.score_overrides_obj.final_consent,
                    json.dumps(score_overrides_payload),
                    item_id,
                ),
            )
        else:
            cur.execute(
                """
                UPDATE agenda_items
                   SET score_overrides = %s::jsonb,
                       updated_at = NOW()
                 WHERE id = %s
                   AND processing_status = 'cross_stage_conflict'::processing_status_enum
                """,
                (json.dumps(score_overrides_payload), item_id),
            )

        if cur.rowcount == 0:
            cur.execute(
                "SELECT processing_status::text FROM agenda_items WHERE id = %s",
                (item_id,),
            )
            current = cur.fetchone()
            current_status = current[0] if current else "unknown"
            _audit(
                cur, item_id,
                from_status=current_status,
                to_status=current_status,
                action="edit_stage1_facts_lost_race",
                actor=actor,
                reason=reason,
                payload={
                    "new_facts_json": canon_facts,
                    "would_have_set_status": new_status,
                    "served_model": outcome.served_model,
                    "is_substantive": outcome.rewrite.is_substantive,
                },
            )
            log.info(
                "admin edit_stage1_facts lost race: item_id=%s actor=%s "
                "current_status=%s",
                item_id, actor, current_status,
            )
            raise ConflictAlreadyResolvedError(
                f"item {item_id} was resolved by another admin during the "
                "LLM call (current status: " + current_status + ")"
            )

        _audit(
            cur, item_id,
            from_status="cross_stage_conflict",
            to_status=new_status,
            action="edit_stage1_facts",
            actor=actor,
            reason=reason,
            payload={
                "new_facts_json": canon_facts,
                "reconcile_action": outcome.reconcile_action,
                "conflicts": outcome.conflicts,
                "served_model": outcome.served_model,
                "is_substantive": outcome.rewrite.is_substantive,
            },
        )

    log.info(
        "admin edit_stage1_facts: item_id=%s actor=%s reconcile=%s",
        item_id, actor, outcome.reconcile_action,
    )
    return ResolutionResult(
        item_id=item_id,
        new_status=new_status,
        action="edit_stage1_facts",
        success=success,
        detail=(
            "Facts corrected; Stage 2 re-ran and reconcile accepted."
            if success else
            "Facts corrected and Stage 2 re-ran, but reconcile still "
            "found conflicts. Review the updated reasons."
        ),
    )
```

- [ ] **Step 6.4: Replace the form-expander stub + add the action route**

In `admin.py`, replace the `conflict_form_edit_facts` stub:

```python
@bp.route("/review/conflicts/<int:item_id>/_form/edit-facts")
def conflict_form_edit_facts(item_id: int):
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, extracted_facts, processing_status::text
              FROM agenda_items WHERE id = %s
            """,
            (item_id,),
        )
        row = cur.fetchone()
    if row is None or row["processing_status"] != "cross_stage_conflict":
        abort(404)

    return render_template(
        "admin/_conflict_form_edit_facts.html",
        item_id=item_id,
        existing_facts=row["extracted_facts"] or {},
    )


@bp.route("/review/conflicts/<int:item_id>/edit-stage-1-facts", methods=["POST"])
def conflict_edit_stage_1_facts(item_id: int):
    actor = session.get("admin_user", "unknown")
    raw = request.form.get("new_facts_json", "")
    try:
        new_facts = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ("new_facts_json must be valid JSON", 400)

    reason = request.form.get("reason")
    try:
        result = conflict_svc.edit_stage_1_facts(
            item_id,
            new_facts_json=new_facts,
            actor=actor,
            reason=reason,
        )
    except conflict_svc.ConflictValidationError as e:
        return (str(e), 400)
    except conflict_svc.ConflictAlreadyResolvedError as e:
        return (str(e), 409)
    except LookupError:
        abort(404)

    return render_template("admin/_conflict_resolved.html", result=result)
```

- [ ] **Step 6.5: Create the form partial**

Create `src/docket/web/templates/admin/_conflict_form_edit_facts.html`:

```html
{#
  G4 inline form — Edit Stage 1 facts.
  Pre-populates the textarea with the existing extracted_facts JSON
  for the admin to edit. Server validates via StructuredFacts Pydantic
  schema. Decision #6 — 4xx error rendering via
  hx-on:htmx:response-error. Decision #12 — TOCTOU race-loss returns
  409 with a clear message; same handler renders it.
#}
<form class="conflict-form"
      hx-post="{{ url_for('admin.conflict_edit_stage_1_facts', item_id=item_id) }}"
      hx-target="#row-{{ item_id }}"
      hx-swap="outerHTML"
      hx-on:htmx:response-error="this.querySelector('.form-error').textContent = event.detail.xhr.responseText">
  <label>
    Corrected facts JSON
    <textarea name="new_facts_json" rows="12" required
              style="font-family: var(--mono, ui-monospace, monospace); font-size: 0.8rem;"
              spellcheck="false">{{ existing_facts | tojson(indent=2) }}</textarea>
  </label>
  <p class="t-meta">
    Schema: docket/ai/extraction_schema.py StructuredFacts. All required
    fields must be present; Pydantic validates server-side.
  </p>
  <button type="submit" class="btn-submit">📝 Save facts &amp; re-run Stage 2</button>
  <span class="form-error" role="alert"></span>
</form>
```

- [ ] **Step 6.6: Run, confirm pass**

Run: `venv/bin/pytest tests/integration/test_conflict_resolution.py -k edit_facts -xvs`. Expected: 6 passes.

- [ ] **Step 6.7: Commit**

```bash
git add src/docket/services/conflict_resolution.py \
        src/docket/web/admin.py \
        src/docket/web/templates/admin/_conflict_form_edit_facts.html \
        tests/integration/test_conflict_resolution.py
git commit -m "feat(admin): G4 edit_stage_1_facts — admin facts edit + Stage 2 re-run"
```

---

## Task 7: Cross-template nav link

**Files:**
- Modify: 5 admin templates (`data_debt.html`, `errors.html`, `calibration.html`, `ai_panel.html`, `members.html`, plus `badges_audit.html`)

Add `Conflicts` link to the `&middot;`-separated nav strip on each admin template. Same pattern as G3's "Badge audit" addition.

- [ ] **Step 7.1: Locate nav strips**

```bash
cd ~/docket-pub-pf2-track-3
grep -n "Council Members" src/docket/web/templates/admin/*.html
```

- [ ] **Step 7.2: Add the Conflicts link to each**

Add `&middot; <a href="{{ url_for('admin.review_conflicts') }}">Conflicts</a>` to each template's nav strip, after `Badge audit` and before `Calibration` for consistency with the listing template's own nav.

- [ ] **Step 7.3: Smoke check**

Run: `venv/bin/pytest tests/integration/test_admin_queues.py tests/integration/test_admin_badge_audit.py --deselect tests/integration/test_calibration.py::test_query_c_returns_weeks_of_data 2>&1 | tail -15`. Expected: PASS.

- [ ] **Step 7.4: Commit**

```bash
git add src/docket/web/templates/admin/*.html
git commit -m "feat(admin): cross-link Conflicts queue from existing admin pages"
```

---

## Task 8: Final verification

- [ ] **Step 8.1: Run G4 file alone**

```bash
cd ~/docket-pub-pf2-track-3
venv/bin/pytest tests/integration/test_conflict_resolution.py -v 2>&1 | tail -50
```

Expected: ~41 tests pass; no failures. Breakdown:
- Task 1 helper: 3
- Task 2 listing: 7 (4-city parametrize + redirect + side-by-side + empty state + pagination)
- Task 3 accept_s1: 10
- Task 4 accept_s2: 7
- Task 5 re_prompt: 7 (6 base + 1 TOCTOU race)
- Task 6 edit_facts: 7 (6 base + 1 TOCTOU race)
- Total: ~41

(Numbers approximate — some tests may fold together or split based on implementer judgment.)

- [ ] **Step 8.2: Run full suite (with the same deselect the pickup memo flagged)**

```bash
venv/bin/pytest --deselect tests/integration/test_calibration.py::test_query_c_returns_weeks_of_data 2>&1 | tail -15
```

Expected: previous baseline (1122 passed + 4 xfailed) + ~41 new passes ≈ 1163 passed + 4 xfailed.

- [ ] **Step 8.3: Sanity-check the live page in dev**

```bash
venv/bin/flask --app docket.web run --port 5005 &
sleep 2
# (manual) browse http://localhost:5005/admin/login, sign in,
# then visit /admin/review/conflicts. Use SAMPLE_FACTS to seed a
# conflict item directly and exercise each of the 4 actions.
```

If you can't run the dev server in this environment, document the manual step as deferred and proceed.

- [ ] **Step 8.4: No additional commit; write the dispatch summary**

After all 7 commits land, the worktree should have:
- Task 1: `feat(query): list_cross_stage_conflicts helper for G4 admin viewer`
- Task 2: `feat(admin): G4 cross-stage conflict listing with side-by-side facts/verdict`
- Task 3: `feat(admin): G4 accept_stage_1 — manual headline+why_it_matters resolution`
- Task 4: `feat(admin): G4 accept_stage_2 — clear Stage 1 facts, mark procedural`
- Task 5: `feat(admin): G4 re_prompt_stage_2 — admin override + Stage 2 re-run`
- Task 6: `feat(admin): G4 edit_stage_1_facts — admin facts edit + Stage 2 re-run`
- Task 7: `feat(admin): cross-link Conflicts queue from existing admin pages`

Total: 7 commits.

---

## What the technical-report variant will look at

After implementation lands, the technical-report variant of the protocol fires:

1. **Two parallel Opus reviews** —
   - Backend: service layer + 4 resolution paths + Stage 2 re-run integration + transaction semantics + Pydantic validation + spec/code drift
   - Frontend: 4 HTMX endpoints + side-by-side listing UX + form validation + auth coverage + a11y
2. **Comprehensive technical report (~600 lines)** — synthesizes both reviews + spec/code drift + architectural concerns. **Replaces** Sonnet second-look + final auditor + 4-bullet packet. Written so the user can author a remediation plan directly rather than picking from bullets.
3. **User authors remediation plan** — free-form, not constrained to per-bullet decisions.
4. **Fix-up loop** — single commit applying the user's remediation.
5. **Memory update + push.**

Reviewers should specifically check:
- **The Stage 2 re-run helper (`_rerun_stage2`):** is it correctly minimal (no scope creep into B5's territory)? Does it call `rewrite_item → apply_score_floors → reconcile_stages` in the right order? Is the LLM call outside the DB transaction (avoiding connection-hold during network I/O)?
- **`already_retried=True` on reconcile:** admin re-runs are explicit, not the auto-retry path. Confirm the implementer passed True so a still-conflicting outcome marks (not auto-retries again).
- **Pydantic validation gates:** `StructuredFacts.model_validate` on stored JSON before re-run; same on `new_facts_json` for edit-facts. Confirm both paths fail-closed on bad data.
- **Length-cap consistency:** `manual_headline` (10-60), `manual_why_it_matters` (1-200), `override_instruction` (1-500), `reason` (0-500). Match `rewrite_schema.ItemRewrite` Field constraints + decision #87 density rule.
- **Audit-row payload completeness:** every action records the action verb + actor + the action-specific input (manual_headline, override_instruction, new_facts_json) + the reconcile outcome (when applicable) + served_model.
- **Transaction boundaries:** read+write in the same `with db() as conn` block where possible. The LLM-touching paths split (read tx → LLM → persist tx) for connection-hold reasons; confirm this is the correct split.
- **Item-not-in-conflict guard:** every action 404s when the item is missing OR not in `cross_stage_conflict`. No silent partial overwrite of a completed item.
- **Auth on all routes:** form-expander GETs + 4 action POSTs all gated by the blueprint hook.
- **Spec drift:** spec decision #93 calls the route `/admin/review/conflicts` (singular, with `/admin` prefix). Confirm. The 4 action verbs match snake_case.
- **HTMX 4xx UX (decision #6):** every form template has both `hx-on:htmx:response-error` AND a `<span class="form-error" role="alert">` element. Without both halves the validation-error message vanishes silently. Confirm both present in all three form templates (accept-s1, re-prompt, edit-facts).
- **TOCTOU guard (decision #12):** every persistence UPDATE in `re_prompt_stage_2` and `edit_stage_1_facts` includes `AND processing_status = 'cross_stage_conflict'::processing_status_enum` in the WHERE; rowcount==0 raises `ConflictAlreadyResolvedError`; route returns 409. Confirm both branches (success + still-conflict) of both functions are guarded — that's 4 separate UPDATE statements that all need the predicate.
- **Race-loss audit row (decision #13):** even on TOCTOU race-loss the service writes a `*_lost_race` audit row capturing what the admin attempted. Trail of "admin tried X but lost the race" is preserved. Confirm both code paths write the audit row before raising.

---

## Self-review (run against this plan)

1. **Spec coverage** — spec decision #93 mandates: (a) listing route at `/admin/review/conflicts` — Task 2 ✓; (b) side-by-side display — Task 2 template ✓; (c) 4 HTMX resolution actions — Tasks 3, 4, 5, 6 ✓; (d) audit-trail via processing_status_audit — every service function writes one ✓.
2. **Placeholder scan** — no "TBD"/"TODO"/"similar to Task N" placeholders. Every code block is complete; every test has actual code.
3. **Type consistency** — `query.list_cross_stage_conflicts` (helper), `conflict_svc.{accept_stage_1, accept_stage_2, re_prompt_stage_2, edit_stage_1_facts}` (service functions), route names match the action verbs in snake_case-with-hyphens form. `_rerun_stage2` private helper used by Tasks 5 + 6.
4. **Things to double-check during execution:**
   - `get_enabled_policy_slugs` is imported from `docket.services.badges` — verify this module + function exist before Task 5 lands. If it doesn't (legacy name was `list_enabled_badges` in `query.py`), update the import.
   - The Pydantic model_validate on stored JSON may fail if the JSON drifted from schema. The `re_prompt_stage_2` path raises `ConflictValidationError` — that's the right behavior. Confirm the test for "stored facts already pass schema" implicitly via SAMPLE_FACTS being a valid shape.
   - The `admin.py` import `from docket.services import conflict_resolution as conflict_svc` is referenced in the route handlers — make sure it's added at the top of the G4 section before any handler uses it.

---

## What's NOT in this plan

- **Migration changes:** none. All schema is from migration 013. G4 is pure code.
- **B5 cross-track convergence:** explicit non-goal. The `_rerun_stage2` helper is intentionally minimal; B5 will subsume it.
- **Additional resolution actions beyond the 4:** spec decision #93 names exactly 4. Stay scoped.
- **A "snooze" or "defer" action:** not in spec. Don't add.
- **Spec text patches:** if the implementation deviates from spec wording (e.g., URL path shape, action-verb naming), document in the commit message and defer the spec patch to a separate doc commit, same as G2/G3 convention.
