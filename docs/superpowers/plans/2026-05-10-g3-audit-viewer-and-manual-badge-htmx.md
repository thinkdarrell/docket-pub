# G3 — Audit Log Viewer + Manual Badge HTMX Endpoints — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Phase 2 Track 3 §G3 — a filterable `agenda_item_badges_audit` viewer at `/admin/badges/audit`, plus the manual badge add/remove HTMX endpoints (writing badge + audit row in one transaction with `city_id`), plus the minimum admin manage UI to invoke them.

**Architecture:** Three canonical admin routes (`/admin/badges/audit`, `/admin/badges/items/<id>`, plus two HTMX POST handlers) wrapped by the existing `admin` blueprint `before_request` auth hook, plus one helper route — a thin `POST /admin/badges/<id>/add` 307 redirector that bridges HTML-form-shaped submissions (slug-in-body) to the spec-shaped slug-in-path canonical endpoint without JavaScript. One new query helper `list_badge_audit_log` with filterable signature (`badge_slug` / `actor` / `since` / `until_exclusive`) accepting **timezone-aware** `datetime` values; the route layer parses `YYYY-MM-DD` form inputs through `zoneinfo.ZoneInfo("America/Chicago")` so day boundaries match user expectations regardless of server TZ (decision #10). Two new templates extending `base.html` plus one HTMX-swap partial. Manual adds set `source='manual'`, `confidence=0.95`, `matching_metadata={"manual": true, "added_by": <actor>}`. Each HTMX endpoint runs a single explicit transaction (`with db() as conn` opens a tx) writing the badges row and the audit row in lockstep — INSERT/DELETE first, then INSERT INTO `agenda_item_badges_audit`. Tests follow the G2 `_Bag` fixture convention and live in `tests/integration/test_admin_badge_audit.py`.

**Tech Stack:** Flask + HTMX + Jinja2 + psycopg2 + PostgreSQL 16 (local) / 18 (Railway). pytest. Test client uses `session_transaction()` to set `admin_user`.

---

## Decisions baked into this plan

These were authored during plan-writing (not deferred to review). Override before dispatch if you disagree.

1. **Audit viewer scope: `agenda_item_badges_audit` only.** Spec §6.10 is explicit (`agenda_item_badges_audit log viewer, filterable by badge/actor/date`). The pickup memo's claim that G3 should also display G2's `processing_status_audit` rows is out of scope — that's an unrelated table covering retry/escalate. A unified audit viewer would be a separate task.
2. **Manual-add confidence: `0.95` (not `1.0`).** Confidence ≥ `1.0` triggers the AI-verified ✨ Verification Spark per decision #67 (`badge_chip.html:33`). Manual badges are not AI-verified; setting them at `0.95` keeps them in the high-confidence visual tier without misappropriating the spark. `source='manual'` distinguishes them from `'llm'`/`'deterministic'`/`'both'` programmatically.
3. **Manage UI surface: dedicated `/admin/badges/items/<int:item_id>` page.** Without a UI, the HTMX endpoints have no human-driven invocation surface. Putting admin controls inline on citizen-facing templates (e.g., `meeting_detail.html`) is invasive. A dedicated admin page is the smallest cohesive change.
4. **Add semantics: idempotent.** Re-adding a slug that already exists on the item is a no-op (no extra audit row). Implemented via `INSERT ... ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING RETURNING id` — only audit if the row was actually inserted.
5. **Remove semantics: hard DELETE (not soft-delete).** The badges table has no `is_active` column. Removing means `DELETE FROM agenda_item_badges WHERE agenda_item_id=? AND badge_slug=?`. The audit row is the historical record.
6. **Available-to-add list: `list_enabled_badges(city_id)` minus already-attached.** Mirrors the dropdown semantics F4 already established for the cross-filter dropdown — process badges first (alarm priority), then policy badges enabled for the city. Out of process+policy badges, subtract any slug already on the item.
7. **Filter form: `<form method="get">` with bookmark-friendly query params (`?badge_slug=&actor=&since=&until=&offset=`).** No JS. Date inputs use `<input type="date">` (returns `YYYY-MM-DD`).
8. **Pagination: same sentinel-pagination shape as F5/G2** — fetch `limit+1`, slice to `limit`, expose `next_offset` if the +1 row materialized. Page size 50.
9. **Reason field: not collected from the manage UI for v1.** The spec mentions `reason` on the audit table but G3 doesn't expose a form input for it. Reserved for future "remove with reason" UX. Stored as `NULL` for now.
10. **Date filter timezone: `America/Chicago` (CDT/CST), parsed in Python — not a raw `::timestamptz` cast.** Naively casting `'2026-04-01'::timestamptz` interprets the string in the **session timezone** (Railway runs UTC). For Alabama admins that's confusing (`since=2026-04-01` would skip events that occurred between midnight UTC and midnight CDT on April 1). Cleaner: parse the `YYYY-MM-DD` string in Python with `zoneinfo.ZoneInfo('America/Chicago')`, build timezone-aware datetimes, pass those to psycopg2. `since` is **inclusive lower bound** at start-of-day (00:00 local). `until` is **inclusive of the local day-end**, implemented as **exclusive upper bound at start-of-next-day** (00:00 local on day+1) so an event at 23:59 local on the requested day still matches without needing microsecond gymnastics.
11. **Add-form dispatch: thin `POST /admin/badges/<item_id>/add` redirector returning 307 to the canonical slug-in-path endpoint** — not the `onsubmit` DOM-mutation hack the earlier draft mentioned. The redirector reads `slug = request.form['slug']`, validates it's non-empty, then `redirect(url_for('admin.badge_add', item_id=..., slug=...), code=307)`. HTMX honors 307 (preserves method + body); zero JavaScript in the template; no race between the native `submit` event and HTMX's request construction.

---

## File structure

```
src/docket/web/admin.py                                  (+~180 lines)
src/docket/services/query.py                             (+1 helper, ~70 lines)
src/docket/web/templates/admin/badges_audit.html         (NEW)
src/docket/web/templates/admin/badges_manage.html        (NEW)
src/docket/web/templates/admin/_badges_manage_panel.html (NEW — HTMX swap target)
src/docket/web/static/tweaks.css                         (+~40 lines, .audit-table + .manage-panel rules)
tests/integration/test_admin_badge_audit.py              (NEW, ~25 tests)
```

Cross-template nav: add `Badge Audit` link to the `&middot;`-separated admin nav strip on `data_debt.html`, `errors.html`, `calibration.html`, `ai_panel.html`, `members.html`. (One-line edit each.)

---

## Conventions inherited from G1/G2

- **Auth:** blueprint-level `before_request` hook in `admin.py:25-33`. New routes get auth automatically — no `@login_required` decorator needed.
- **Cursor:** `db_cursor()` for dict-row reads, `db()` for tuple writes inside a transaction.
- **Test fixture: `_Bag`** in `tests/integration/test_admin_queues.py` — copy the pattern (don't import; tests should be self-contained).
- **Test pre-flight:** `pytest.mark.skipif("railway.internal" in DATABASE_URL ...)` to refuse against prod.
- **Admin client:** `c.session_transaction()` to set `sess["admin_user"] = "tester"`.
- **Audit table CHECK constraints (from migration 013:142-151):**
  - `action IN ('added', 'removed', 'modified')` — G3 uses `'added'` and `'removed'`
  - `actor_role IN ('admin', 'cron', 'on_write')` — G3 always writes `'admin'`
- **Badges table CHECK constraints (from migration 013:129-140):**
  - `kind IN ('process', 'policy')`
  - `source IN ('deterministic', 'llm', 'both', 'manual')`
  - `UNIQUE (agenda_item_id, badge_slug)` — drives idempotent ON CONFLICT
- **Multi-city test parametrization:** `CITIES = ["birmingham", "mobile", "vestavia_hills", "homewood"]` — apply to the entry-point 200 test only (G2 convention; full parametrization on every test bloats fixture time).

---

## Task 1: `list_badge_audit_log` query helper

**Files:**
- Modify: `src/docket/services/query.py` (add helper at end of file, before `list_upcoming_hearings` at line 1995)
- Test: `tests/integration/test_admin_badge_audit.py` (NEW)

- [ ] **Step 1.1: Sketch the test file shell with shared `_Bag` fixture**

Create `tests/integration/test_admin_badge_audit.py`:

```python
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
```

- [ ] **Step 1.2: Write the first failing test for the helper**

Append to `tests/integration/test_admin_badge_audit.py`:

```python
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
```

- [ ] **Step 1.3: Run the test and confirm it fails**

Run: `cd ~/docket-pub-pf2-track-3 && venv/bin/pytest tests/integration/test_admin_badge_audit.py::test_list_badge_audit_log_returns_recent_rows_first -xvs`

Expected: FAIL with `AttributeError: module 'docket.services.query' has no attribute 'list_badge_audit_log'`

- [ ] **Step 1.4: Implement the helper**

Insert into `src/docket/services/query.py`, just before `def list_upcoming_hearings(...)` (around line 1995). The helper should match every other reader in this module: `db_cursor()`, parameterized SQL, `dict(row)` projection, sentinel-pagination friendly:

```python
from datetime import datetime  # add at top of file if not already present


def list_badge_audit_log(
    *,
    badge_slug: str | None = None,
    actor: str | None = None,
    since: datetime | None = None,
    until_exclusive: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Return ``agenda_item_badges_audit`` rows joined to context for
    the G3 viewer at ``/admin/badges/audit``. Spec §6.10.

    Filters (all optional, all combinable):

    - ``badge_slug`` — exact match on ``aiba.badge_slug``.
    - ``actor`` — exact match on ``aiba.actor`` (case-sensitive; admin
      usernames are the existing convention).
    - ``since`` — **timezone-aware** ``datetime``; returns rows where
      ``occurred_at >= since``. Inclusive lower bound. Callers should
      build this from a YYYY-MM-DD form input by combining the date
      with start-of-day in ``America/Chicago`` (decision #10).
    - ``until_exclusive`` — **timezone-aware** ``datetime`` representing
      the **exclusive upper bound**. Returns rows where
      ``occurred_at < until_exclusive``. Callers translate
      ``until=YYYY-MM-DD`` (which the user understands as "include the
      whole day") into start-of-(day+1) in ``America/Chicago`` —
      that's why the parameter name explicitly says ``_exclusive``.
      Avoids end-of-day microsecond gymnastics.

    psycopg2 binds timezone-aware ``datetime`` values to ``timestamptz``
    natively; no ``::timestamptz`` cast in the SQL is needed when the
    Python value is already aware. Naive ``datetime`` would be an
    error here — the caller is responsible for tz-attachment.

    Sort: ``occurred_at DESC, id DESC`` — newest-first, with id as
    tiebreaker for same-second rows. Hits ``idx_badge_audit_recent``
    (migration 013:251-253) when ``actor_role='admin'`` is in the
    predicate; G3 doesn't restrict to admin actor_role at the helper
    level (the viewer surfaces all roles so cron and on-write actions
    are debuggable too), so this is a sequential scan over the audit
    table. That's acceptable for v1 — admin traffic is bounded by
    ``login_required`` and the table is small (one row per badge
    add/remove/modify, currently zero in production).

    Pagination: caller passes ``limit`` and ``offset``; sentinel
    pagination is the caller's responsibility (caller passes
    ``limit+1`` and slices). Same shape as
    :func:`list_data_debt_items`.

    Returns a list of dicts. Joined columns:

    - ``id``, ``agenda_item_id``, ``badge_slug``, ``action``,
      ``actor``, ``actor_role``, ``reason``, ``occurred_at`` — direct
      from ``agenda_item_badges_audit``.
    - ``item_title`` — from ``agenda_items.title``.
    - ``meeting_date`` — from ``meetings.meeting_date``.
    - ``municipality_slug``, ``municipality_name`` — from
      ``municipalities`` for cross-city display.

    NB: the audit table's ``agenda_item_id`` FK to ``agenda_items``
    has no ``ON DELETE CASCADE``, so audit rows live forever even if
    the item is deleted. Use a LEFT JOIN so old audit rows still
    surface (with NULL item_title / meeting_date / municipality_*).
    """
    where_clauses: list[str] = []
    params: list = []

    if badge_slug:
        where_clauses.append("aiba.badge_slug = %s")
        params.append(badge_slug)
    if actor:
        where_clauses.append("aiba.actor = %s")
        params.append(actor)
    if since is not None:
        if since.tzinfo is None:
            raise ValueError("list_badge_audit_log: 'since' must be timezone-aware")
        where_clauses.append("aiba.occurred_at >= %s")
        params.append(since)
    if until_exclusive is not None:
        if until_exclusive.tzinfo is None:
            raise ValueError(
                "list_badge_audit_log: 'until_exclusive' must be timezone-aware"
            )
        where_clauses.append("aiba.occurred_at < %s")
        params.append(until_exclusive)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    params.extend([limit, offset])

    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT
              aiba.id,
              aiba.agenda_item_id,
              aiba.badge_slug,
              aiba.action,
              aiba.actor,
              aiba.actor_role,
              aiba.reason,
              aiba.occurred_at,
              ai.title                 AS item_title,
              mt.meeting_date          AS meeting_date,
              m.slug                   AS municipality_slug,
              m.name                   AS municipality_name
            FROM agenda_item_badges_audit aiba
            LEFT JOIN agenda_items ai ON ai.id = aiba.agenda_item_id
            LEFT JOIN meetings mt ON mt.id = ai.meeting_id
            LEFT JOIN municipalities m ON m.id = mt.municipality_id
            {where_sql}
            ORDER BY aiba.occurred_at DESC, aiba.id DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params),
        )
        return [dict(row) for row in cur.fetchall()]
```

- [ ] **Step 1.5: Run the test and confirm it passes**

Run: `cd ~/docket-pub-pf2-track-3 && venv/bin/pytest tests/integration/test_admin_badge_audit.py::test_list_badge_audit_log_returns_recent_rows_first -xvs`

Expected: PASS

- [ ] **Step 1.6: Add the filter tests, run, confirm pass**

Tests use timezone-aware datetimes — `since` and `until_exclusive` are now `datetime` objects, not strings, so the helper signature is exercised end-to-end. Append:

```python
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
    """Audit FK has no CASCADE; deleted-item audit rows must still surface."""
    from docket.services import query

    m = bag.add_meeting()
    iid = bag.add_item(m)
    bag.add_audit(iid, "split_vote", "added", actor="ghost")

    # Manually delete the item; audit row remains.
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM agenda_items WHERE id = %s", (iid,))
    bag.item_ids.remove(iid)  # don't try to clean it again

    rows = query.list_badge_audit_log(actor="ghost", limit=10)
    ours = [r for r in rows if r["agenda_item_id"] == iid]
    assert len(ours) == 1
    assert ours[0]["item_title"] is None  # LEFT JOIN

    # Cleanup: orphan audit row.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM agenda_item_badges_audit WHERE agenda_item_id = %s",
            (iid,),
        )
```

Run: `venv/bin/pytest tests/integration/test_admin_badge_audit.py -k list_badge_audit_log -xvs`. Expected: 7 passes (5 filters + 1 boundary + 1 naive-rejection + 1 left-join).

- [ ] **Step 1.7: Commit**

```bash
cd ~/docket-pub-pf2-track-3
git add src/docket/services/query.py tests/integration/test_admin_badge_audit.py
git commit -m "feat(query): list_badge_audit_log helper for G3 audit viewer"
```

---

## Task 2: `/admin/badges/audit` viewer

**Files:**
- Modify: `src/docket/web/admin.py`
- Create: `src/docket/web/templates/admin/badges_audit.html`
- Modify: `src/docket/web/static/tweaks.css`
- Test: `tests/integration/test_admin_badge_audit.py` (extend)

- [ ] **Step 2.1: Write the failing route test**

Append to `tests/integration/test_admin_badge_audit.py`:

```python
# ---------------------------------------------------------------------------
# G3.2 — /admin/badges/audit viewer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("city_slug", CITIES)
def test_admin_badge_audit_route_renders_for_logged_in_admin(app, city_slug):
    bag = _bag_for(city_slug)
    try:
        m = bag.add_meeting()
        iid = bag.add_item(m, title=f"Audit row in {city_slug}")
        bag.add_audit(iid, "split_vote", "added", actor="alice")

        c = app.test_client()
        with c.session_transaction() as sess:
            sess["admin_user"] = "tester"
        resp = c.get("/admin/badges/audit")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Badge audit log" in body
        assert "split_vote" in body
        assert "alice" in body
    finally:
        bag.cleanup()


def test_admin_badge_audit_route_redirects_anonymous(client):
    resp = client.get("/admin/badges/audit")
    assert resp.status_code in (302, 303)
    assert "/admin/login" in resp.headers.get("Location", "")


def test_admin_badge_audit_filter_by_badge_slug_query_param(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m)
    bag.add_audit(iid, "split_vote", "added", actor="g3-test")
    bag.add_audit(iid, "contested", "added", actor="g3-test")

    resp = admin_client.get("/admin/badges/audit?badge_slug=contested")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    # split_vote audit row for this g3-test actor must be filtered out;
    # but other audit rows in the system may still mention "split_vote",
    # so the assertion checks that for OUR seeded actor, only contested
    # surfaces. Easiest: actor name ensures uniqueness.
    # Count occurrences of g3-test rows by counting actor cells.
    # Use a unique sentinel via the badge_slug column instead — every
    # G3 row has its slug printed; assert split_vote NOT in body for
    # this filtered query.
    # NOTE: a contested row from elsewhere may exist. So this assertion
    # is "the row I'd expect to see is here, and the one I'd expect to
    # be filtered isn't."
    # Strategy: render the response, scrape rows containing actor=g3-test,
    # confirm exactly one contains contested and zero contain split_vote.
    g3_rows = [line for line in body.splitlines() if "g3-test" in line]
    assert any("contested" in line for line in g3_rows)
    assert not any("split_vote" in line for line in g3_rows)


def test_admin_badge_audit_filter_by_actor_query_param(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m)
    bag.add_audit(iid, "split_vote", "added", actor="alice")
    bag.add_audit(iid, "split_vote", "removed", actor="bob")

    resp = admin_client.get("/admin/badges/audit?actor=alice")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    # row authored by alice surfaces; row authored by bob doesn't (for
    # this iid).
    assert f">added<" in body or "added" in body
    # Same scoping as previous test — restrict to rows that mention
    # our seeded actors.
    alice_rows = [l for l in body.splitlines() if "alice" in l]
    bob_rows = [l for l in body.splitlines() if ">bob<" in l]
    assert alice_rows
    assert not bob_rows


def test_admin_badge_audit_filter_by_date_range(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m)
    bag.add_audit(iid, "split_vote", "added", actor="g3-old",
                   occurred_at="2026-03-01T00:00:00Z")
    bag.add_audit(iid, "split_vote", "removed", actor="g3-new",
                   occurred_at="2026-04-15T00:00:00Z")

    resp = admin_client.get(
        "/admin/badges/audit?since=2026-04-01&until=2026-05-01"
    )
    body = resp.get_data(as_text=True)
    assert "g3-new" in body
    assert "g3-old" not in body


def test_admin_badge_audit_pagination_offset(admin_client, bag):
    """Sentinel pagination — page size is 50, but a 51st row triggers
    a 'next' link. Seed 51 rows to exercise the boundary."""
    m = bag.add_meeting()
    iid = bag.add_item(m)
    for i in range(51):
        bag.add_audit(iid, "split_vote", "added", actor=f"g3-page-{i:02d}",
                       occurred_at=f"2026-04-{1 + (i % 28):02d}T12:00:00Z")

    resp = admin_client.get("/admin/badges/audit")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    # 'Next' link present (sentinel-pagination contract: hint when
    # there's a 51st row).
    assert "offset=50" in body or "offset=" in body
```

- [ ] **Step 2.2: Run tests, confirm they fail with 404**

Run: `venv/bin/pytest tests/integration/test_admin_badge_audit.py -k admin_badge_audit -xvs`

Expected: routes return 404 (not yet wired).

- [ ] **Step 2.3: Add the route to `admin.py`**

Open `src/docket/web/admin.py`. Add `from datetime import datetime, timedelta` and `from zoneinfo import ZoneInfo` to the imports near the top. Just after the `errors_escalate` handler (around line 391), insert a new section:

```python
# --- Badge audit log viewer + manual badge management (G3) ------------------


_AUDIT_PAGE_SIZE = 50

# Decision #10: badge audit date filters are interpreted in
# America/Chicago — the project is single-state Alabama. A literal
# ::timestamptz cast against a UTC session would silently shift
# user-meaningful day boundaries by 5–6 hours.
_APP_TZ = ZoneInfo("America/Chicago")


def _parse_filter_str(raw: str | None) -> str | None:
    """Trim + treat empty as None — query-param hygiene."""
    if raw is None:
        return None
    s = raw.strip()
    return s or None


def _parse_audit_since(raw: str | None) -> datetime | None:
    """YYYY-MM-DD → start-of-day in America/Chicago (timezone-aware).

    Returns None if the raw string is empty / unparseable. Parse errors
    fall through to None rather than 400 — the viewer is forgiving for
    bookmark-mangled URLs; a user typing garbage just gets the unfiltered
    view back, not an error page.
    """
    s = _parse_filter_str(raw)
    if s is None:
        return None
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None
    return datetime(d.year, d.month, d.day, tzinfo=_APP_TZ)


def _parse_audit_until_exclusive(raw: str | None) -> datetime | None:
    """YYYY-MM-DD → start-of-(day+1) in America/Chicago.

    The viewer's UI promises 'include the whole day' for ``until``; the
    helper takes an exclusive upper bound, so this function adds one day
    to make the math line up. (Decision #10's exclusive-of-next-day
    convention.) An event at 23:59 local on the requested day still
    matches.
    """
    start = _parse_audit_since(raw)
    if start is None:
        return None
    return start + timedelta(days=1)


@bp.route("/badges/audit")
def badges_audit():
    """Filterable view of ``agenda_item_badges_audit`` (spec §6.10).

    Filters (all combinable, all bookmarkable):

    - ``badge_slug`` — exact match.
    - ``actor`` — exact match (admin usernames).
    - ``since`` / ``until`` — ``YYYY-MM-DD`` strings interpreted in
      America/Chicago. ``since`` is inclusive at start-of-day local;
      ``until`` is inclusive of the local day-end (translated to an
      exclusive upper bound at start-of-next-day, see decision #10 +
      ``_parse_audit_until_exclusive``).

    Pagination: ``offset`` query param + sentinel-pagination
    (limit+1 / slice / next_offset). Page size 50.

    Auth: blueprint-level ``before_request`` hook redirects
    unauthenticated callers to ``/admin/login``.

    Renders all actor_roles ('admin', 'cron', 'on_write') — admins
    debugging odd badge state need to see automated activity too. Only
    the manage UI restricts to admin-authored writes.
    """
    badge_slug = _parse_filter_str(request.args.get("badge_slug"))
    actor = _parse_filter_str(request.args.get("actor"))
    since_dt = _parse_audit_since(request.args.get("since"))
    until_excl_dt = _parse_audit_until_exclusive(request.args.get("until"))
    offset = _parse_offset(request.args.get("offset"))

    rows_plus_one = query.list_badge_audit_log(
        badge_slug=badge_slug,
        actor=actor,
        since=since_dt,
        until_exclusive=until_excl_dt,
        limit=_AUDIT_PAGE_SIZE + 1,
        offset=offset,
    )
    rows = rows_plus_one[:_AUDIT_PAGE_SIZE]
    next_offset = (
        offset + _AUDIT_PAGE_SIZE
        if len(rows_plus_one) > _AUDIT_PAGE_SIZE
        else None
    )

    return render_template(
        "admin/badges_audit.html",
        rows=rows,
        offset=offset,
        next_offset=next_offset,
        filter_badge_slug=badge_slug or "",
        filter_actor=actor or "",
        # Echo the raw user-supplied YYYY-MM-DD strings back into the
        # form fields so the date inputs stay populated on round-trip.
        filter_since=_parse_filter_str(request.args.get("since")) or "",
        filter_until=_parse_filter_str(request.args.get("until")) or "",
    )
```

- [ ] **Step 2.4: Create the viewer template**

Create `src/docket/web/templates/admin/badges_audit.html`:

```html
{% extends "base.html" %}
{% block title %}Badge audit log — Admin — docket.pub{% endblock %}

{#
  G3.1 — agenda_item_badges_audit viewer (spec §6.10).

  Filterable by badge_slug + actor + date range (since/until). All
  filters live in query params so URLs are bookmarkable; the form is
  GET-only and uses standard <input> elements (no JS).

  Sort order: occurred_at DESC, id DESC. Newest activity first.

  Renders ALL actor_roles ('admin', 'cron', 'on_write') so an admin
  debugging odd badge state can see automated activity. The manage UI
  at /admin/badges/items/<id> is the only surface that writes
  actor_role='admin'.

  NB: agenda_item_badges_audit's agenda_item_id FK has no ON DELETE
  CASCADE (migration 013:144). Deleted items still surface in the log
  with NULL item_title / meeting_date / municipality_slug — the
  helper LEFT JOINs accordingly.
#}

{% block content %}
<div style="display: flex; justify-content: space-between; align-items: center;">
  <h1>Badge audit log</h1>
  <form method="post" action="{{ url_for('auth.logout') }}" style="margin: 0;">
    <button type="submit" style="font-size: 0.85rem;">Sign Out ({{ session.get('admin_user', '') }})</button>
  </form>
</div>

<p><a href="{{ url_for('admin.list_members') }}">← Council Members</a> &middot;
   <a href="{{ url_for('admin.calibration') }}">Calibration</a> &middot;
   <a href="{{ url_for('admin.data_debt') }}">OCR queue</a> &middot;
   <a href="{{ url_for('admin.errors') }}">Errors queue</a> &middot;
   <a href="{{ url_for('admin.ai_panel') }}">AI Pipeline</a></p>

<form method="get" class="audit-filter">
  <label>Badge slug
    <input type="text" name="badge_slug" value="{{ filter_badge_slug }}"
           placeholder="e.g. split_vote">
  </label>
  <label>Actor
    <input type="text" name="actor" value="{{ filter_actor }}"
           placeholder="admin username">
  </label>
  <label>Since
    <input type="date" name="since" value="{{ filter_since[:10] if filter_since else '' }}">
  </label>
  <label>Until
    <input type="date" name="until" value="{{ filter_until[:10] if filter_until else '' }}">
  </label>
  <button type="submit">Filter</button>
  <a href="{{ url_for('admin.badges_audit') }}">Reset</a>
</form>

{% if not rows %}
  <p class="t-meta">No audit rows match these filters.</p>
{% else %}
<table class="audit-table">
  <thead>
    <tr>
      <th>When</th>
      <th>Action</th>
      <th>Slug</th>
      <th>Item</th>
      <th>City</th>
      <th>Actor</th>
      <th>Role</th>
      <th>Reason</th>
    </tr>
  </thead>
  <tbody>
    {% for r in rows %}
    <tr>
      <td><time datetime="{{ r.occurred_at.isoformat() }}">{{ r.occurred_at.strftime('%Y-%m-%d %H:%M') }}</time></td>
      <td><span class="badge-action badge-action-{{ r.action }}">{{ r.action }}</span></td>
      <td><code>{{ r.badge_slug }}</code></td>
      <td>
        {% if r.item_title %}
          <a href="{{ url_for('admin.badges_manage_item', item_id=r.agenda_item_id) }}">
            {{ r.item_title|truncate(60, true) }}
          </a>
        {% else %}
          <span class="t-meta">(item #{{ r.agenda_item_id }} deleted)</span>
        {% endif %}
      </td>
      <td>{{ r.municipality_slug or '—' }}</td>
      <td>{{ r.actor or '—' }}</td>
      <td><code>{{ r.actor_role }}</code></td>
      <td>{{ r.reason or '' }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>

<p class="audit-pager">
  {% if offset > 0 %}
    {% set prev_offset = (offset - 50) if (offset - 50) > 0 else 0 %}
    <a href="{{ url_for('admin.badges_audit', badge_slug=filter_badge_slug or none,
                         actor=filter_actor or none, since=filter_since or none,
                         until=filter_until or none,
                         offset=prev_offset if prev_offset > 0 else none) }}">← Previous</a>
  {% endif %}
  {% if next_offset %}
    <a href="{{ url_for('admin.badges_audit', badge_slug=filter_badge_slug or none,
                         actor=filter_actor or none, since=filter_since or none,
                         until=filter_until or none,
                         offset=next_offset) }}">Next →</a>
  {% endif %}
</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 2.5: Add CSS rules**

Append to `src/docket/web/static/tweaks.css`:

```css
/* G3 — admin badge audit viewer */
.audit-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem 1rem;
  align-items: end;
  margin: 1rem 0;
  padding: 0.75rem;
  background: var(--surface-2, #f6f6f4);
  border-radius: 4px;
}
.audit-filter label {
  display: flex;
  flex-direction: column;
  font-size: 0.85rem;
}
.audit-filter input { padding: 0.25rem 0.4rem; font-family: inherit; }
.audit-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.audit-table th, .audit-table td {
  text-align: left;
  padding: 0.4rem 0.6rem;
  border-bottom: 1px solid var(--border, #e6e6e0);
  vertical-align: top;
}
.badge-action { padding: 0.1rem 0.4rem; border-radius: 3px; font-size: 0.8rem; }
.badge-action-added    { background: #d4edda; color: #155724; }
.badge-action-removed  { background: #f8d7da; color: #721c24; }
.badge-action-modified { background: #fff3cd; color: #856404; }
.audit-pager { margin-top: 1rem; }
.audit-pager a { margin-right: 1rem; }
```

- [ ] **Step 2.6: Run all G3.2 tests, confirm pass**

Run: `venv/bin/pytest tests/integration/test_admin_badge_audit.py -k admin_badge_audit -xvs`

Expected: 8 passes (4-city parametrize + redirect + slug filter + actor filter + date range + pagination).

- [ ] **Step 2.7: Commit**

```bash
git add src/docket/web/admin.py \
        src/docket/web/templates/admin/badges_audit.html \
        src/docket/web/static/tweaks.css \
        tests/integration/test_admin_badge_audit.py
git commit -m "feat(admin): G3 badge audit log viewer with bookmarkable filters"
```

---

## Task 3: Manage UI page `/admin/badges/items/<int:item_id>`

**Files:**
- Modify: `src/docket/web/admin.py`
- Create: `src/docket/web/templates/admin/badges_manage.html`
- Create: `src/docket/web/templates/admin/_badges_manage_panel.html` (HTMX swap target)
- Modify: `src/docket/web/static/tweaks.css`
- Test: `tests/integration/test_admin_badge_audit.py` (extend)

The manage UI page lists current badges on a single item and offers two affordances per badge: a remove (X) button posting to the remove HTMX endpoint, plus a dropdown of available-to-add badges with an Add button posting to the add HTMX endpoint. The full page extends `base.html`; the post-mutation HTMX response renders only the panel partial (`_badges_manage_panel.html`).

- [ ] **Step 3.1: Write failing tests for the manage page**

Append to `tests/integration/test_admin_badge_audit.py`:

```python
# ---------------------------------------------------------------------------
# G3.3 — /admin/badges/items/<id> manage UI
# ---------------------------------------------------------------------------


def test_manage_page_renders_for_logged_in_admin(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m, title="Manage me")
    bag.add_badge(iid, "split_vote", kind="process")

    resp = admin_client.get(f"/admin/badges/items/{iid}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Manage me" in body
    assert "split_vote" in body


def test_manage_page_redirects_anonymous(client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m)
    resp = client.get(f"/admin/badges/items/{iid}")
    assert resp.status_code in (302, 303)
    assert "/admin/login" in resp.headers.get("Location", "")


def test_manage_page_returns_404_for_unknown_item(admin_client):
    resp = admin_client.get("/admin/badges/items/999999999")
    assert resp.status_code == 404


def test_manage_page_offers_addable_slugs_minus_attached(admin_client, bag):
    """Available-to-add list must exclude badges already on the item."""
    m = bag.add_meeting()
    iid = bag.add_item(m, title="x")
    bag.add_badge(iid, "split_vote", kind="process")

    resp = admin_client.get(f"/admin/badges/items/{iid}")
    body = resp.get_data(as_text=True)
    # The dropdown must contain at least one process badge that isn't
    # already on the item — process badges are uniform across cities so
    # 'contested' is always available unless explicitly attached.
    assert "contested" in body
    # And the already-attached slug should NOT appear in the <select>
    # options — it's only shown in the current-badges section.
    # Test by checking that the substring 'value="split_vote"' (the
    # form select option shape) is absent.
    assert 'value="split_vote"' not in body
```

- [ ] **Step 3.2: Run, confirm 404**

Run: `venv/bin/pytest tests/integration/test_admin_badge_audit.py -k manage_page -xvs`

Expected: 404s.

- [ ] **Step 3.3: Add a tiny query helper for "current badges on item"**

Existing `query.list_agenda_items` does this for many items at once but joins to `priority_badge_templates`. For a single item the simplest path is a focused helper. Insert into `src/docket/services/query.py` immediately after `list_badge_audit_log`:

```python
def list_badges_on_item(item_id: int) -> list[dict]:
    """Return active badges on a single agenda item, joined to template
    metadata for display. Used by the G3 manage UI.

    Returns dicts with: ``slug``, ``kind``, ``confidence``, ``source``,
    ``name``, ``description``, ``icon``. Empty list if no badges.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT aib.badge_slug AS slug,
                   aib.kind,
                   aib.confidence,
                   aib.source,
                   t.name,
                   t.description,
                   t.icon
              FROM agenda_item_badges aib
              JOIN priority_badge_templates t ON t.slug = aib.badge_slug
             WHERE aib.agenda_item_id = %s
             ORDER BY aib.kind, aib.badge_slug
            """,
            (item_id,),
        )
        return [dict(row) for row in cur.fetchall()]
```

- [ ] **Step 3.4: Add the manage route and helper for the city lookup**

Append to the G3 section in `src/docket/web/admin.py`:

```python
@bp.route("/badges/items/<int:item_id>")
def badges_manage_item(item_id: int):
    """Manage the badge set for a single item.

    Shows the item's current badges (with remove buttons) and a
    dropdown of badges available to add (process + city-policy). Each
    button is an HTMX form posting to the add/remove endpoints; the
    response swaps the panel back in.

    404 if the item doesn't exist. Auth via blueprint hook.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT ai.id, ai.title,
                   m.id   AS municipality_id,
                   m.slug AS municipality_slug,
                   m.name AS municipality_name,
                   mt.id  AS meeting_id,
                   mt.meeting_date
              FROM agenda_items ai
              JOIN meetings mt ON mt.id = ai.meeting_id
              JOIN municipalities m ON m.id = mt.municipality_id
             WHERE ai.id = %s
            """,
            (item_id,),
        )
        item = cur.fetchone()
        if item is None:
            abort(404)
        item = dict(item)

    current = query.list_badges_on_item(item_id)
    attached_slugs = {b["slug"] for b in current}
    addable = [
        b for b in query.list_enabled_badges(item["municipality_id"])
        if b["slug"] not in attached_slugs
    ]

    return render_template(
        "admin/badges_manage.html",
        item=item,
        current=current,
        addable=addable,
    )
```

- [ ] **Step 3.5: Create the manage page templates**

Create `src/docket/web/templates/admin/badges_manage.html`:

```html
{% extends "base.html" %}
{% block title %}Manage badges — Admin — docket.pub{% endblock %}

{#
  G3.3 — Manual badge management for a single agenda item.

  Renders the page chrome + the manage panel partial. The partial is
  re-rendered by the HTMX add/remove endpoints, so any markup that
  needs to be swappable lives in _badges_manage_panel.html.

  hx-target on each form points to #badges-manage-panel; hx-swap is
  outerHTML.
#}

{% block content %}
<h1>Manage badges</h1>

<p><a href="{{ url_for('admin.badges_audit') }}">← Audit log</a></p>

<section class="manage-meta">
  <p>
    <strong>{{ item.title }}</strong><br>
    <span class="t-meta">{{ item.municipality_name }} · {{ item.meeting_date }}</span>
  </p>
</section>

{% include "admin/_badges_manage_panel.html" %}
{% endblock %}
```

Create `src/docket/web/templates/admin/_badges_manage_panel.html`:

```html
{#
  HTMX swap target. Re-rendered by the add/remove POST endpoints.
  Caller must provide:
    - item.id, item.municipality_slug
    - current: list of dicts {slug, kind, name, icon, confidence, source}
    - addable: list of dicts {slug, kind, name, icon, description}
#}
<section id="badges-manage-panel" class="manage-panel">
  <h2>Current badges</h2>
  {% if not current %}
    <p class="t-meta">No badges attached to this item.</p>
  {% else %}
    <ul class="manage-current">
      {% for b in current %}
      <li>
        <span class="manage-chip badge-{{ b.kind }}">
          {{ b.icon }} {{ b.name }}
          <span class="manage-meta">({{ b.source }}{% if b.confidence is not none %}, conf {{ '%.2f'|format(b.confidence|float) }}{% endif %})</span>
        </span>
        <form hx-post="{{ url_for('admin.badge_remove', item_id=item.id, slug=b.slug) }}"
              hx-target="#badges-manage-panel"
              hx-swap="outerHTML"
              style="display: inline;">
          <button type="submit" class="manage-remove" aria-label="Remove {{ b.name }}">× Remove</button>
        </form>
      </li>
      {% endfor %}
    </ul>
  {% endif %}

  <h2>Add a badge</h2>
  {% if not addable %}
    <p class="t-meta">No additional badges available for this city.</p>
  {% else %}
  <form class="manage-add"
        hx-post="{{ url_for('admin.badge_add_via_form', item_id=item.id) }}"
        hx-target="#badges-manage-panel"
        hx-swap="outerHTML"
        method="post">
    <label>
      Badge
      <select name="slug" required>
        {% for b in addable %}
        <option value="{{ b.slug }}">{{ b.icon }} {{ b.name }} ({{ b.kind }})</option>
        {% endfor %}
      </select>
    </label>
    <button type="submit">Add</button>
  </form>
  {% endif %}
</section>
```

> **Slug-in-path vs slug-in-body:** the spec mandates `POST /admin/badges/<item_id>/add/<slug>` as the canonical write site. The HTML form posts the slug as a body field, so we route through a thin redirector at `POST /admin/badges/<item_id>/add` (defined in Task 4) that reads `slug = request.form['slug']` and **`307 Temporary Redirect`s** to the canonical endpoint. 307 preserves the method + body; HTMX honors it. Zero JavaScript in the template.

- [ ] **Step 3.6: Add CSS for manage panel**

Append to `src/docket/web/static/tweaks.css`:

```css
/* G3 — manage panel */
.manage-current { list-style: none; padding-left: 0; }
.manage-current li {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.4rem 0;
  border-bottom: 1px dotted var(--border, #e6e6e0);
}
.manage-chip { padding: 0.15rem 0.5rem; border-radius: 3px; font-size: 0.9rem; }
.manage-chip.badge-process { background: #fff3cd; }
.manage-chip.badge-policy  { background: #d1ecf1; }
.manage-meta { font-size: 0.8rem; color: var(--muted, #6a6a60); }
.manage-remove {
  background: none;
  border: 1px solid #c66;
  color: #c66;
  padding: 0.1rem 0.5rem;
  font-size: 0.8rem;
  cursor: pointer;
}
.manage-remove:hover { background: #f8d7da; }
.manage-add { display: flex; gap: 1rem; align-items: end; margin-top: 0.5rem; }
```

- [ ] **Step 3.7: Run, confirm pass**

Run: `venv/bin/pytest tests/integration/test_admin_badge_audit.py -k manage_page -xvs`

Expected: 4 passes.

- [ ] **Step 3.8: Commit**

```bash
git add src/docket/services/query.py src/docket/web/admin.py \
        src/docket/web/templates/admin/badges_manage.html \
        src/docket/web/templates/admin/_badges_manage_panel.html \
        src/docket/web/static/tweaks.css \
        tests/integration/test_admin_badge_audit.py
git commit -m "feat(admin): G3 manage page for per-item badges"
```

---

## Task 4: HTMX add endpoint `POST /admin/badges/<item_id>/add/<slug>`

**Files:**
- Modify: `src/docket/web/admin.py`
- Test: `tests/integration/test_admin_badge_audit.py` (extend)

- [ ] **Step 4.1: Write failing tests**

Append:

```python
# ---------------------------------------------------------------------------
# G3.3 — POST /admin/badges/<item_id>/add/<slug>
# ---------------------------------------------------------------------------


def _badge_row(item_id: int, slug: str) -> tuple | None:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, city_id, kind, confidence, source, matching_metadata
              FROM agenda_item_badges
             WHERE agenda_item_id = %s AND badge_slug = %s
            """,
            (item_id, slug),
        )
        return cur.fetchone()


def _audit_rows(item_id: int, slug: str) -> list[tuple]:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT action, actor, actor_role
              FROM agenda_item_badges_audit
             WHERE agenda_item_id = %s AND badge_slug = %s
             ORDER BY id ASC
            """,
            (item_id, slug),
        )
        return cur.fetchall()


def test_add_endpoint_inserts_badge_with_city_id(admin_client, bag):
    """Decision #92: city_id MUST be on every INSERT into agenda_item_badges."""
    m = bag.add_meeting()
    iid = bag.add_item(m)

    resp = admin_client.post(f"/admin/badges/{iid}/add/contested")
    assert resp.status_code == 200  # HTMX swap, not redirect

    row = _badge_row(iid, "contested")
    assert row is not None
    bid, city_id, kind, conf, source, metadata = row
    assert city_id == bag.city_id
    assert kind == "process"  # contested is a process badge
    assert source == "manual"
    assert conf == pytest.approx(0.95)
    assert metadata.get("manual") is True
    assert metadata.get("added_by") == "tester"


def test_add_endpoint_writes_audit_row(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m)

    admin_client.post(f"/admin/badges/{iid}/add/contested")

    audit = _audit_rows(iid, "contested")
    assert len(audit) == 1
    action, actor, role = audit[0]
    assert action == "added"
    assert actor == "tester"
    assert role == "admin"


def test_add_endpoint_is_idempotent(admin_client, bag):
    """Re-adding an already-attached slug is a no-op (no extra badge,
    no extra audit row)."""
    m = bag.add_meeting()
    iid = bag.add_item(m)

    admin_client.post(f"/admin/badges/{iid}/add/contested")
    admin_client.post(f"/admin/badges/{iid}/add/contested")

    # Still exactly one badge row.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM agenda_item_badges "
            "WHERE agenda_item_id = %s AND badge_slug = %s",
            (iid, "contested"),
        )
        assert cur.fetchone()[0] == 1

    # And exactly one audit row (idempotent: no duplicate).
    assert len(_audit_rows(iid, "contested")) == 1


def test_add_endpoint_returns_swapped_panel(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m, title="Swap target")

    resp = admin_client.post(f"/admin/badges/{iid}/add/contested")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    # Swap target id must be present.
    assert 'id="badges-manage-panel"' in body
    # Newly added slug appears in the rendered current-badges section.
    assert "contested" in body


def test_add_endpoint_404_for_unknown_item(admin_client):
    resp = admin_client.post("/admin/badges/999999999/add/contested")
    assert resp.status_code == 404


def test_add_endpoint_404_for_unknown_slug(admin_client, bag):
    """Unknown slugs aren't in priority_badge_templates → 404, no row inserted."""
    m = bag.add_meeting()
    iid = bag.add_item(m)
    resp = admin_client.post(f"/admin/badges/{iid}/add/this_slug_does_not_exist")
    assert resp.status_code == 404
    assert _badge_row(iid, "this_slug_does_not_exist") is None


def test_add_endpoint_requires_post(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m)
    resp = admin_client.get(f"/admin/badges/{iid}/add/contested")
    assert resp.status_code == 405


def test_add_endpoint_requires_login(client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m)
    resp = client.post(f"/admin/badges/{iid}/add/contested")
    assert resp.status_code in (302, 303)
    assert "/admin/login" in resp.headers.get("Location", "")
    # State must NOT have changed.
    assert _badge_row(iid, "contested") is None
```

- [ ] **Step 4.2: Run, confirm fail**

Run: `venv/bin/pytest tests/integration/test_admin_badge_audit.py -k add_endpoint -xvs`

Expected: 8 fails (404s; routes not yet wired).

- [ ] **Step 4.3: Implement the add handler**

Append to the G3 section in `src/docket/web/admin.py`:

```python
@bp.route("/badges/<int:item_id>/add/<slug>", methods=["POST"])
def badge_add(item_id: int, slug: str):
    """Manual add: write badge + audit row in one transaction.

    Decision #92: ``city_id`` is INSERT'd from the item's meeting's
    municipality.

    Idempotent: re-adding a slug that already exists is a no-op (the
    badges table's ``UNIQUE(agenda_item_id, badge_slug)`` constraint
    drives an ``ON CONFLICT DO NOTHING``; the audit row is only
    written if the row was actually inserted).

    Confidence is fixed at 0.95 — high but below the 1.0 threshold
    that triggers the AI-verified Verification Spark (decision #67).
    Source is ``'manual'`` (CHECK constraint accepts it). The actor
    name is recorded in ``matching_metadata`` AND in the audit row's
    ``actor`` column for redundancy.

    Slug must exist in ``priority_badge_templates`` (joined for
    ``kind`` and to validate the slug) — unknown slugs 404.

    Returns the re-rendered manage panel (HTMX swap target).
    """
    actor = session.get("admin_user", "unknown")

    with db() as conn:
        with conn.cursor() as cur:
            # Look up item + city + slug template in one round-trip.
            cur.execute(
                """
                SELECT m.id          AS city_id,
                       t.kind        AS kind
                  FROM agenda_items ai
                  JOIN meetings mt ON mt.id = ai.meeting_id
                  JOIN municipalities m ON m.id = mt.municipality_id
                  LEFT JOIN priority_badge_templates t ON t.slug = %s
                 WHERE ai.id = %s
                """,
                (slug, item_id),
            )
            row = cur.fetchone()
            if row is None:
                abort(404)
            city_id, kind = row
            if kind is None:
                # Slug not in templates → reject.
                abort(404)

            cur.execute(
                """
                INSERT INTO agenda_item_badges
                  (agenda_item_id, city_id, badge_slug, kind, confidence,
                   source, matching_metadata)
                VALUES (%s, %s, %s, %s, 0.95, 'manual', %s::jsonb)
                ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING
                RETURNING id
                """,
                (
                    item_id, city_id, slug, kind,
                    json.dumps({"manual": True, "added_by": actor}),
                ),
            )
            inserted = cur.fetchone()

            if inserted is not None:
                cur.execute(
                    """
                    INSERT INTO agenda_item_badges_audit
                      (agenda_item_id, badge_slug, action, actor, actor_role)
                    VALUES (%s, %s, 'added', %s, 'admin')
                    """,
                    (item_id, slug, actor),
                )

    current_app.logger.info(
        "admin badge add: item_id=%s slug=%s actor=%s inserted=%s",
        item_id, slug, actor, inserted is not None,
    )
    return _render_manage_panel(item_id)


def _render_manage_panel(item_id: int):
    """Re-fetch the manage state and render the swap-target partial.
    Shared by add/remove handlers."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT ai.id, ai.title,
                   m.id   AS municipality_id,
                   m.slug AS municipality_slug
              FROM agenda_items ai
              JOIN meetings mt ON mt.id = ai.meeting_id
              JOIN municipalities m ON m.id = mt.municipality_id
             WHERE ai.id = %s
            """,
            (item_id,),
        )
        item = cur.fetchone()
        if item is None:
            abort(404)
        item = dict(item)

    current = query.list_badges_on_item(item_id)
    attached_slugs = {b["slug"] for b in current}
    addable = [
        b for b in query.list_enabled_badges(item["municipality_id"])
        if b["slug"] not in attached_slugs
    ]

    return render_template(
        "admin/_badges_manage_panel.html",
        item=item,
        current=current,
        addable=addable,
    )
```

> **Note:** the manage page route (`badges_manage_item` in Task 3) and the HTMX endpoints share template state. The shared `_render_manage_panel` function above is consumed by add and remove. The full-page `badges_manage_item` route stays as-is (renders the wrapping page that `{% include %}`s the partial).

- [ ] **Step 4.4: Add the form-redirector route**

The manage UI's add form (Task 3) submits `slug` in the body; the canonical write endpoint takes it in the path. Bridge them with a 307 redirector. Append to the G3 section in `src/docket/web/admin.py`:

```python
@bp.route("/badges/<int:item_id>/add", methods=["POST"])
def badge_add_via_form(item_id: int):
    """307 redirector: the manage UI form posts ``slug`` as a body
    field; redirect (preserving method + body via 307) to the canonical
    slug-in-path endpoint. Spec mandates ``POST /admin/badges/<id>/add/<slug>``
    as the write site; this route only exists to bridge HTML form
    semantics without JavaScript in the template.

    HTMX honors 307 redirects natively.
    """
    slug = (request.form.get("slug") or "").strip()
    if not slug:
        abort(400)
    return redirect(
        url_for("admin.badge_add", item_id=item_id, slug=slug),
        code=307,
    )
```

Append the corresponding test:

```python
def test_add_via_form_redirector_307s_to_canonical_endpoint(admin_client, bag):
    """The form-shaped POST (slug in body) must 307 to the canonical
    POST (slug in path), and HTMX-style follow must result in the
    badge being created. Test client follows 307 by default."""
    m = bag.add_meeting()
    iid = bag.add_item(m)

    resp = admin_client.post(
        f"/admin/badges/{iid}/add",
        data={"slug": "contested"},
        follow_redirects=False,
    )
    # 307 preserves method + body.
    assert resp.status_code == 307
    assert f"/admin/badges/{iid}/add/contested" in resp.headers["Location"]

    # End-to-end: with redirect-following on, the badge lands.
    resp_followed = admin_client.post(
        f"/admin/badges/{iid}/add",
        data={"slug": "contested"},
        follow_redirects=True,
    )
    assert resp_followed.status_code == 200
    assert _badge_row(iid, "contested") is not None


def test_add_via_form_redirector_400_when_slug_missing(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m)

    # No 'slug' field in the body.
    resp = admin_client.post(f"/admin/badges/{iid}/add", data={})
    assert resp.status_code == 400
```

- [ ] **Step 4.5: Run, confirm all G3.3 add tests pass**

Run: `venv/bin/pytest tests/integration/test_admin_badge_audit.py -k "add_endpoint or add_via_form" -xvs`

Expected: 10 passes (8 canonical + 2 redirector).

- [ ] **Step 4.6: Commit**

```bash
git add src/docket/web/admin.py tests/integration/test_admin_badge_audit.py
git commit -m "feat(admin): G3 manual badge add HTMX endpoint (city_id, audit, idempotent)"
```

---

## Task 5: HTMX remove endpoint `POST /admin/badges/<item_id>/remove/<slug>`

**Files:**
- Modify: `src/docket/web/admin.py`
- Test: `tests/integration/test_admin_badge_audit.py` (extend)

- [ ] **Step 5.1: Write failing tests**

Append:

```python
# ---------------------------------------------------------------------------
# G3.3 — POST /admin/badges/<item_id>/remove/<slug>
# ---------------------------------------------------------------------------


def test_remove_endpoint_deletes_badge(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m)
    bag.add_badge(iid, "split_vote", kind="process")

    resp = admin_client.post(f"/admin/badges/{iid}/remove/split_vote")
    assert resp.status_code == 200

    assert _badge_row(iid, "split_vote") is None


def test_remove_endpoint_writes_audit_row(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m)
    bag.add_badge(iid, "split_vote", kind="process")

    admin_client.post(f"/admin/badges/{iid}/remove/split_vote")

    audit = _audit_rows(iid, "split_vote")
    assert len(audit) == 1
    action, actor, role = audit[0]
    assert action == "removed"
    assert actor == "tester"
    assert role == "admin"


def test_remove_endpoint_404_for_unattached_slug(admin_client, bag):
    """Removing a slug that isn't on the item: 404, no audit row written."""
    m = bag.add_meeting()
    iid = bag.add_item(m)

    resp = admin_client.post(f"/admin/badges/{iid}/remove/split_vote")
    assert resp.status_code == 404
    assert _audit_rows(iid, "split_vote") == []


def test_remove_endpoint_404_for_unknown_item(admin_client):
    resp = admin_client.post("/admin/badges/999999999/remove/split_vote")
    assert resp.status_code == 404


def test_remove_endpoint_returns_swapped_panel(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m, title="Swap target 2")
    bag.add_badge(iid, "split_vote", kind="process")

    resp = admin_client.post(f"/admin/badges/{iid}/remove/split_vote")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'id="badges-manage-panel"' in body
    # Removed slug must not appear in the rendered current-badges
    # section. (Could still appear in the addable dropdown, which is
    # expected — once removed, it becomes addable again.)
    assert "Current badges" in body


def test_remove_endpoint_requires_post(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m)
    bag.add_badge(iid, "split_vote", kind="process")
    resp = admin_client.get(f"/admin/badges/{iid}/remove/split_vote")
    assert resp.status_code == 405


def test_remove_endpoint_requires_login(client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m)
    bag.add_badge(iid, "split_vote", kind="process")
    resp = client.post(f"/admin/badges/{iid}/remove/split_vote")
    assert resp.status_code in (302, 303)
    assert "/admin/login" in resp.headers.get("Location", "")
    # Badge must still exist.
    assert _badge_row(iid, "split_vote") is not None


def test_add_then_remove_then_audit_log_shows_both_actions(admin_client, bag):
    """End-to-end: add then remove yields two audit rows, viewer
    surfaces them in newest-first order."""
    from docket.services import query

    m = bag.add_meeting()
    iid = bag.add_item(m)

    admin_client.post(f"/admin/badges/{iid}/add/contested")
    admin_client.post(f"/admin/badges/{iid}/remove/contested")

    rows = query.list_badge_audit_log(actor="tester", limit=10)
    ours = [r for r in rows if r["agenda_item_id"] == iid
            and r["badge_slug"] == "contested"]
    assert len(ours) == 2
    assert ours[0]["action"] == "removed"  # newest-first
    assert ours[1]["action"] == "added"


def test_psycopg2_delete_returning_zero_rows_returns_none():
    """Driver-contract pin: ``DELETE ... RETURNING id`` against a row
    that doesn't exist must yield ``cur.fetchone() is None`` so the
    remove handler's 'nothing was deleted → 404' branch is sound.

    psycopg2 has historically honored this contract, but pin it
    explicitly here so a future driver swap (psycopg3, async drivers)
    can't silently break the handler's correctness assumption.
    """
    sentinel_id = -987654321  # nonexistent
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM agenda_item_badges WHERE id = %s RETURNING id",
            (sentinel_id,),
        )
        result = cur.fetchone()
    assert result is None
```

- [ ] **Step 5.2: Run, confirm fail**

Run: `venv/bin/pytest tests/integration/test_admin_badge_audit.py -k remove_endpoint -xvs`

Expected: 7 fails.

- [ ] **Step 5.3: Implement the remove handler**

Append to the G3 section in `src/docket/web/admin.py`:

```python
@bp.route("/badges/<int:item_id>/remove/<slug>", methods=["POST"])
def badge_remove(item_id: int, slug: str):
    """Manual remove: hard-DELETE badge + write audit row in one tx.

    The badges table has no ``is_active`` column; remove is a real
    DELETE. The audit row is the historical record.

    404 if the badge isn't attached to the item — no audit row gets
    written for a no-op DELETE. The DELETE's ``RETURNING id`` arm is
    the source of truth for "was anything actually removed."

    Returns the re-rendered manage panel (HTMX swap target).
    """
    actor = session.get("admin_user", "unknown")

    with db() as conn:
        with conn.cursor() as cur:
            # First confirm the item exists at all (separate from the
            # badge presence — we want 404 in either of the two
            # not-found cases).
            cur.execute(
                "SELECT 1 FROM agenda_items WHERE id = %s",
                (item_id,),
            )
            if cur.fetchone() is None:
                abort(404)

            cur.execute(
                """
                DELETE FROM agenda_item_badges
                 WHERE agenda_item_id = %s AND badge_slug = %s
                RETURNING id
                """,
                (item_id, slug),
            )
            removed = cur.fetchone()
            if removed is None:
                abort(404)

            cur.execute(
                """
                INSERT INTO agenda_item_badges_audit
                  (agenda_item_id, badge_slug, action, actor, actor_role)
                VALUES (%s, %s, 'removed', %s, 'admin')
                """,
                (item_id, slug, actor),
            )

    current_app.logger.info(
        "admin badge remove: item_id=%s slug=%s actor=%s",
        item_id, slug, actor,
    )
    return _render_manage_panel(item_id)
```

- [ ] **Step 5.4: Run, confirm all G3.3 remove tests pass**

Run: `venv/bin/pytest tests/integration/test_admin_badge_audit.py -k "remove_endpoint or audit_log_shows_both or psycopg2_delete_returning" -xvs`

Expected: 9 passes (7 remove + 1 end-to-end + 1 psycopg2 driver-contract pin).

- [ ] **Step 5.5: Commit**

```bash
git add src/docket/web/admin.py tests/integration/test_admin_badge_audit.py
git commit -m "feat(admin): G3 manual badge remove HTMX endpoint (audit, hard-delete)"
```

---

## Task 6: Cross-template nav links

**Files:**
- Modify: `src/docket/web/templates/admin/data_debt.html`
- Modify: `src/docket/web/templates/admin/errors.html`
- Modify: `src/docket/web/templates/admin/calibration.html`
- Modify: `src/docket/web/templates/admin/ai_panel.html`
- Modify: `src/docket/web/templates/admin/members.html`

Add a `Badge audit` link to the `&middot;`-separated nav strip on each admin template. One-line edit each.

- [ ] **Step 6.1: Locate each existing nav strip**

```bash
cd ~/docket-pub-pf2-track-3
grep -n "Council Members" src/docket/web/templates/admin/*.html
```

Expected: each template has a `<p><a href="{{ url_for('admin.list_members') }}">← Council Members</a> &middot; ...</p>` line.

- [ ] **Step 6.2: Add the Badge audit link to each**

For each of the 5 templates, append `&middot; <a href="{{ url_for('admin.badges_audit') }}">Badge audit</a>` to the nav strip. Place it after the existing entries but before the close `</p>` and any trailing `&middot;`.

Example diff for `data_debt.html` (similar for the other four):

```diff
 <p><a href="{{ url_for('admin.list_members') }}">← Council Members</a> &middot;
+   <a href="{{ url_for('admin.badges_audit') }}">Badge audit</a> &middot;
    <a href="{{ url_for('admin.calibration') }}">Calibration</a> &middot;
```

- [ ] **Step 6.3: Run the existing G2/G1 admin-route tests as a smoke check**

Run: `venv/bin/pytest tests/integration/test_admin_queues.py tests/integration/test_calibration.py -x --deselect tests/integration/test_calibration.py::test_query_c_returns_weeks_of_data 2>&1 | tail -20`

Expected: PASS — adding nav links shouldn't break anything (Jinja `url_for` would 500 on a typo, hence the smoke check). The `--deselect` matches the G1 flaky-test workaround from the pickup memo.

- [ ] **Step 6.4: Commit**

```bash
git add src/docket/web/templates/admin/data_debt.html \
        src/docket/web/templates/admin/errors.html \
        src/docket/web/templates/admin/calibration.html \
        src/docket/web/templates/admin/ai_panel.html \
        src/docket/web/templates/admin/members.html
git commit -m "feat(admin): cross-link Badge audit from existing admin pages"
```

---

## Task 7: Final verification + summary

**Files:** none

- [ ] **Step 7.1: Run the full G3 test suite**

```bash
cd ~/docket-pub-pf2-track-3
venv/bin/pytest tests/integration/test_admin_badge_audit.py -v 2>&1 | tail -40
```

Expected: **~38 tests pass; no failures.** Breakdown:
- Task 1 helper: 7 (1 newest-first + 5 filters/boundary + 1 left-join, with naive-rejection counted under filters)
- Task 2 viewer: 8 (4-city parametrize + 1 anon-redirect + 1 slug filter + 1 actor filter + 1 date-range + 1 pagination)
- Task 3 manage page: 4
- Task 4 add: 10 (8 canonical + 2 form-redirector)
- Task 5 remove: 9 (7 remove + 1 end-to-end + 1 psycopg2 driver-contract pin)

- [ ] **Step 7.2: Run the full repository suite (with the same deselect the pickup memo flagged)**

```bash
venv/bin/pytest --deselect tests/integration/test_calibration.py::test_query_c_returns_weeks_of_data 2>&1 | tail -20
```

Expected: previous baseline (1082 passed + 4 xfailed) + ~38 new passes = ~1120 passed + 4 xfailed.

- [ ] **Step 7.3: Sanity-check the live page in dev**

```bash
cd ~/docket-pub-pf2-track-3
venv/bin/flask --app docket.web run --port 5005 &
sleep 2
# (manual) browse http://localhost:5005/admin/login, sign in,
# then visit /admin/badges/audit and /admin/badges/items/<some-id>.
```

Verify visually:
- Audit table renders with empty state when no rows match filters.
- Manage page lists current badges + addable badges; X button removes; dropdown adds.
- Filters round-trip via query string (bookmarkability check).

If you can't run the dev server in this environment, document this manual step as deferred and proceed to commit. Track 1 + 2 + earlier G-track tasks have been validated this way; G3's surface is small enough that the integration tests catch regressions reliably.

- [ ] **Step 7.4: No additional commit; write the dispatch summary**

After all 7 commits land, the worktree should have:
- Task 1 commit: `feat(query): list_badge_audit_log helper for G3 audit viewer`
- Task 2 commit: `feat(admin): G3 badge audit log viewer with bookmarkable filters`
- Task 3 commit: `feat(admin): G3 manage page for per-item badges`
- Task 4 commit: `feat(admin): G3 manual badge add HTMX endpoint (city_id, audit, idempotent)`
- Task 5 commit: `feat(admin): G3 manual badge remove HTMX endpoint (audit, hard-delete)`
- Task 6 commit: `feat(admin): cross-link Badge audit from existing admin pages`

Total: 6 commits. The implementer reports back with the test count, the commit SHAs, and any deviations from this plan.

---

## What the G2-style review chain will look at

After implementation lands, the standard 4-stage chain is:

1. **Two parallel Opus reviews** —
   - Opus #1: query helper + admin handlers + transaction semantics + spec-vs-code drift
   - Opus #2: templates + UX + auth + a11y + audit-table joins (LEFT vs INNER for the deleted-item case)
2. **Sonnet 4.6 second-look** — confirm REQUIRED findings, scout for cross-model convergence, look for documentation-correctness fixes the Opus pair noted but didn't classify (G2 auditor pattern).
3. **Final auditor Opus 4.7** — re-verify any REQUIRED findings from source; add documentation-correctness if any prior round flagged informationally.
4. **Synthesized user packet** — 4-bullet decisions for the human gate.

Reviewers should specifically check:
- **Decision #92 compliance:** every INSERT into `agenda_item_badges` carries `city_id`. The add handler does; verify no other write site was added by the implementer.
- **Transaction atomicity:** the badges write and the audit write share a single `with db() as conn:` block.
- **`source` CHECK constraint:** `'manual'` is a permitted value (migration 013:136); confirm no value drift.
- **`actor_role` CHECK constraint:** `'admin'` is the only role G3 emits; confirm no value drift.
- **LEFT JOIN on the audit query:** deleted-item audit rows surface (per the FK-without-CASCADE design).
- **Idempotent add semantics:** `ON CONFLICT DO NOTHING RETURNING id`; audit only on actual insert.
- **Hard DELETE on remove:** `RETURNING id`; 404 if nothing was deleted; audit only on actual delete.
- **Confidence 0.95 not 1.0:** Verification Spark stays AI-only.
- **Date-filter timezone handling (decision #10):** route parses `YYYY-MM-DD` via `zoneinfo("America/Chicago")` and passes timezone-aware `datetime` to the helper; helper rejects naive datetimes; `until_exclusive` is start-of-(day+1) so an event at 23:59 local on the requested day still matches.
- **307 redirector (decision #11):** form-shaped POST `/admin/badges/<id>/add` returns a 307 (not 302/303) so method + body are preserved; HTMX honors it.
- **psycopg2 contract pin:** `DELETE ... RETURNING id` against a nonexistent row yields `cur.fetchone() is None` — explicit test exists and protects the remove-handler 404 branch from a future driver swap.
- **Spec deviation log:** decisions 1–11 above. Reviewers confirm each is acceptable or escalate.

---

## Self-review (run against this plan)

1. **Spec coverage** — Spec §6.10 mandates: (a) `/admin/badges/audit` viewer filterable by badge/actor/date — Task 2. (b) HTMX endpoints writing both tables in one transaction with `city_id` — Tasks 4 + 5. (c) `agenda_item_badges_audit` is the only mentioned table for the viewer — Task 1's helper restricts to that table. ✅ All covered.

2. **Placeholder scan** — No "TBD"/"implement later"/"add error handling"/"similar to Task N" placeholders. Code blocks present in every code step. ✅

3. **Type consistency** — `query.list_badge_audit_log`, `query.list_badges_on_item`, `query.list_enabled_badges` (existing) used consistently. Route names: `admin.badges_audit`, `admin.badges_manage_item`, `admin.badge_add`, `admin.badge_remove`. The `_render_manage_panel(item_id)` helper is referenced in Tasks 4 and 5 and defined in Task 4. ✅

4. **One thing to double-check during execution:** the manage template's add-form `formaction` shape is one valid path; the alternative redirector route (mentioned inline) is the other. The implementer should pick whichever is cleaner under their hands and report the choice in the task summary.
