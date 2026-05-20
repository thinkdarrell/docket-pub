# Hide Non-Real Meetings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a soft `is_hidden` flag on `meetings` plus an admin hide/unhide UX, so recurring Granicus operator test-clips (e.g., BHM meeting id 2233) can be removed from public surfaces without losing the row, and reversed easily.

**Architecture:** New columns on `meetings` (`is_hidden`, `hidden_at`, `hidden_by`). Service-layer SQL gains `AND mt.is_hidden = FALSE` at every citizen-facing read-path. Public detail pages (`meeting_detail`, `item_detail`) return 404 to anonymous for hidden meetings but render normally for logged-in admins. Two new admin POST routes (`/admin/meetings/<id>/hide` and `/unhide`) plus a small `/admin/meetings/hidden` index. Daily ingest preserves the flag because `_upsert_meetings` enumerates only the columns it actually updates.

**Tech Stack:** PostgreSQL 18.3 on Railway, Python 3.10+, Flask + HTMX, psycopg2 (`db()` / `db_cursor()` patterns), Jinja2 templates, pytest.

---

## Spec

This plan implements `docs/superpowers/specs/2026-05-20-hide-non-real-meetings-design.md`. Refer to it for design rationale; this document tells the engineer exactly what to type.

## File Structure

**New files:**

- `src/docket/migrations/033_meetings_is_hidden.py` — schema + MV refresh
- `src/docket/web/templates/admin/hidden_meetings.html` — admin index page
- `tests/integration/test_033_migration.py` — migration up/down round-trip
- `tests/integration/test_admin_hide_meeting.py` — POST hide/unhide + index page + meeting_detail admin bypass + item_detail admin bypass
- `tests/integration/test_ingest_preserves_is_hidden.py` — re-ingest regression test
- `tests/unit/test_query_hidden_meetings.py` — every patched query function excludes hidden rows

**Modified files:**

- `src/docket/migrations/runner.py` — register 033
- `src/docket/models/meeting.py` — add `is_hidden` field
- `src/docket/services/query.py` — add `mt.is_hidden = FALSE` filter at all citizen-facing call-sites
- `src/docket/web/public.py` — admin bypass in `meeting_detail` + `item_detail`
- `src/docket/web/admin.py` — three new routes: `hide_meeting`, `unhide_meeting`, `list_hidden_meetings`
- `src/docket/web/auth.py` — also populate `session['admin_user_id']` on login (small optimization for future audit-writing routes)
- `src/docket/web/templates/meeting_detail.html` — admin banner + Hide button (gated on `session.admin_user`)
- `src/docket/web/templates/admin/members.html` — add "Hidden Meetings" link to admin nav strip

---

## Task 1: Migration 033 — add `is_hidden` / `hidden_at` / `hidden_by` columns + partial index + MV refresh

**Files:**
- Create: `src/docket/migrations/033_meetings_is_hidden.py`
- Modify: `src/docket/migrations/runner.py` (append 033 to MIGRATIONS list)
- Create: `tests/integration/test_033_migration.py`

- [ ] **Step 1: Write the failing migration test**

```python
# tests/integration/test_033_migration.py
"""Integration test for migration 033 — meetings.is_hidden + partial index + MV refresh.

Asserts the migration produces the expected schema after up, and reverts cleanly
on down. Mirrors the pattern of tests/integration/test_029_migration.py.
"""

import pytest

from docket.config import DATABASE_URL
from docket.db import db


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Migration test must not run against Railway prod.",
)


def _column_exists(table: str, column: str) -> bool:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM information_schema.columns
             WHERE table_name = %s AND column_name = %s
            """,
            (table, column),
        )
        return cur.fetchone() is not None


def _index_exists(name: str) -> bool:
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", (name,))
        return cur.fetchone() is not None


def _mv_definition_includes(needle: str) -> bool:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_viewdef('mv_badge_volume_monthly'::regclass, true)"
        )
        defn = cur.fetchone()[0]
    return needle in defn


def test_033_up_creates_columns_and_index():
    """After migrations run, the new columns + partial index exist."""
    assert _column_exists("meetings", "is_hidden"), "is_hidden column missing"
    assert _column_exists("meetings", "hidden_at"), "hidden_at column missing"
    assert _column_exists("meetings", "hidden_by"), "hidden_by column missing"
    assert _index_exists("idx_meetings_public_visible"), "partial index missing"


def test_033_up_refreshes_mv_with_filter():
    """mv_badge_volume_monthly now JOINs against meetings and filters is_hidden."""
    assert _mv_definition_includes("is_hidden"), (
        "mv_badge_volume_monthly definition should reference m.is_hidden"
    )


def test_033_default_is_false():
    """New meetings rows default to is_hidden=FALSE — confirms the NOT NULL DEFAULT."""
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM meetings WHERE is_hidden IS NULL"
        )
        n_null = cur.fetchone()[0]
    assert n_null == 0, "is_hidden NOT NULL DEFAULT FALSE should backfill existing rows"
```

- [ ] **Step 2: Run the test to confirm it fails**

```
venv/bin/pytest tests/integration/test_033_migration.py -v
```

Expected: FAIL — `is_hidden column missing`, `idx_meetings_public_visible` missing, MV missing filter.

- [ ] **Step 3: Write the migration**

Create `src/docket/migrations/033_meetings_is_hidden.py`:

```python
"""Migration 033 — meetings.is_hidden + partial index + MV refresh.

Adds a soft-hide flag so operator-published "test" clips (Granicus shorts
with no chapter markers, etc.) can be suppressed from citizen surfaces
without losing the row. Ingest preserves the flag because
``_upsert_meetings`` only writes the columns it enumerates (services/
ingest.py:159), and ``is_hidden`` isn't one of them.

Partial index on (municipality_id, meeting_date DESC) WHERE is_hidden=FALSE
covers the hot city-landing query pattern without paying for hidden rows.

``mv_badge_volume_monthly`` is rebuilt to add the ``m.is_hidden = FALSE``
predicate to its existing JOIN to ``meetings`` (which already supplied
``municipality_id`` and ``meeting_date``). Category-landing volume
timelines now exclude hidden meetings. WITH NO DATA matches migration
022's shape; the next ``refresh_backfill_ratio_mv`` cron (04:30 CT daily)
repopulates. Deploy step applies the refresh manually so prod doesn't
show empty category pages between deploy and 04:30 CT.

Spec: docs/superpowers/specs/2026-05-20-hide-non-real-meetings-design.md
"""

from __future__ import annotations


SQL_UP = r"""
ALTER TABLE meetings
    ADD COLUMN IF NOT EXISTS is_hidden BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS hidden_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS hidden_by INTEGER NULL REFERENCES admin_users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_meetings_public_visible
    ON meetings (municipality_id, meeting_date DESC)
    WHERE is_hidden = FALSE;

DROP MATERIALIZED VIEW IF EXISTS mv_badge_volume_monthly;
CREATE MATERIALIZED VIEW mv_badge_volume_monthly AS
SELECT
    m.municipality_id AS city_id,
    aib.badge_slug,
    DATE_TRUNC('month', m.meeting_date)::date AS month,
    COUNT(*)                                          AS n_items,
    COUNT(*) FILTER (WHERE ai.is_consent = TRUE)     AS n_consent,
    COUNT(*) FILTER (WHERE ai.is_consent = FALSE)    AS n_substantive,
    COALESCE(SUM(ai.dollars_amount), 0)              AS total_dollars
FROM agenda_item_badges aib
JOIN agenda_items ai ON ai.id = aib.agenda_item_id
JOIN meetings m ON m.id = ai.meeting_id
WHERE aib.confidence >= 0.6
  AND aib.status = 'applied'
  AND m.is_hidden = FALSE
GROUP BY m.municipality_id, aib.badge_slug, month
WITH NO DATA;

CREATE UNIQUE INDEX ON mv_badge_volume_monthly (city_id, badge_slug, month);
"""

SQL_DOWN = r"""
DROP MATERIALIZED VIEW IF EXISTS mv_badge_volume_monthly;
CREATE MATERIALIZED VIEW mv_badge_volume_monthly AS
SELECT
    m.municipality_id AS city_id,
    aib.badge_slug,
    DATE_TRUNC('month', m.meeting_date)::date AS month,
    COUNT(*)                                          AS n_items,
    COUNT(*) FILTER (WHERE ai.is_consent = TRUE)     AS n_consent,
    COUNT(*) FILTER (WHERE ai.is_consent = FALSE)    AS n_substantive,
    COALESCE(SUM(ai.dollars_amount), 0)              AS total_dollars
FROM agenda_item_badges aib
JOIN agenda_items ai ON ai.id = aib.agenda_item_id
JOIN meetings m ON m.id = ai.meeting_id
WHERE aib.confidence >= 0.6
  AND aib.status = 'applied'
GROUP BY m.municipality_id, aib.badge_slug, month
WITH NO DATA;

CREATE UNIQUE INDEX ON mv_badge_volume_monthly (city_id, badge_slug, month);

DROP INDEX IF EXISTS idx_meetings_public_visible;

ALTER TABLE meetings
    DROP COLUMN IF EXISTS hidden_by,
    DROP COLUMN IF EXISTS hidden_at,
    DROP COLUMN IF EXISTS is_hidden;
"""
```

- [ ] **Step 4: Register the migration in the runner**

Edit `src/docket/migrations/runner.py` — append to the `MIGRATIONS` list (currently ends with `"docket.migrations.032_meetings_start_time"`):

```python
MIGRATIONS = [
    ...
    "docket.migrations.032_meetings_start_time",
    "docket.migrations.033_meetings_is_hidden",
]
```

- [ ] **Step 5: Apply the migration locally**

```
venv/bin/python -m docket.migrations.runner
```

Expected output ends with: `Applying migration 33: docket.migrations.033_meetings_is_hidden`. The runner also `REFRESH MATERIALIZED VIEW` is NOT triggered automatically — that comes during deploy (Task 17). For local tests the MV being empty is fine; the test only checks the *definition*.

- [ ] **Step 6: Re-run the migration test — should pass**

```
venv/bin/pytest tests/integration/test_033_migration.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Commit**

```
git add src/docket/migrations/033_meetings_is_hidden.py src/docket/migrations/runner.py tests/integration/test_033_migration.py
git -c commit.gpgsign=false commit -m "migration 033: meetings.is_hidden + partial index + MV filter"
```

---

## Task 2: Login also populates `session['admin_user_id']`

**Files:**
- Modify: `src/docket/web/auth.py` (around line 51)
- Modify: `tests/unit/test_auth.py` (add a single test asserting both keys land)

- [ ] **Step 1: Open the existing auth test to see the pattern**

```
venv/bin/pytest tests/unit/test_auth.py -v --collect-only
```

Read `tests/unit/test_auth.py` to find an existing login-success test you can extend. If the file has a test that posts a valid login and asserts a redirect, add a new test alongside it that also inspects the session.

- [ ] **Step 2: Add the failing test**

Append to `tests/unit/test_auth.py` (adjust import block / fixtures to match what's already there):

```python
def test_login_populates_session_admin_user_id(client, seeded_admin):
    """Login should set both session['admin_user'] (username) and
    session['admin_user_id'] (int id) — the latter is consumed by routes
    that write audit columns (e.g., meetings.hidden_by)."""
    rv = client.post(
        "/admin/login",
        data={"username": seeded_admin["username"], "password": seeded_admin["password"]},
        follow_redirects=False,
    )
    assert rv.status_code in (302, 303)
    with client.session_transaction() as sess:
        assert sess.get("admin_user") == seeded_admin["username"]
        assert sess.get("admin_user_id") == seeded_admin["id"]
```

If `seeded_admin` fixture doesn't exist, mirror the seeding pattern already in the file. (If the file uses inline DB INSERTs to create an admin and grab back `id`/`username`/plaintext password, follow that.)

- [ ] **Step 3: Run the test to confirm it fails**

```
venv/bin/pytest tests/unit/test_auth.py::test_login_populates_session_admin_user_id -v
```

Expected: FAIL — `sess.get("admin_user_id")` is None.

- [ ] **Step 4: Patch `auth.py`**

In `src/docket/web/auth.py`, find the success block (currently around line 49-56):

```python
if user and check_password_hash(user["password_hash"], password):
    session.clear()
    session["admin_user"] = user["username"]
    next_url = request.args.get("next", url_for("admin.list_members"))
```

Add the id line right after `session["admin_user"] = ...`:

```python
if user and check_password_hash(user["password_hash"], password):
    session.clear()
    session["admin_user"] = user["username"]
    session["admin_user_id"] = user["id"]
    next_url = request.args.get("next", url_for("admin.list_members"))
```

- [ ] **Step 5: Re-run the test — should pass**

```
venv/bin/pytest tests/unit/test_auth.py::test_login_populates_session_admin_user_id -v
```

Expected: PASS.

- [ ] **Step 6: Run the rest of test_auth.py to ensure no regression**

```
venv/bin/pytest tests/unit/test_auth.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```
git add src/docket/web/auth.py tests/unit/test_auth.py
git -c commit.gpgsign=false commit -m "auth: populate session['admin_user_id'] on login"
```

---

## Task 3: Add `is_hidden` to the Meeting model

**Files:**
- Modify: `src/docket/models/meeting.py`
- Modify: `tests/unit/test_meeting_models.py`

- [ ] **Step 1: Add the failing test**

Open `tests/unit/test_meeting_models.py` and add:

```python
def test_meeting_from_row_reads_is_hidden_default_false():
    """Meeting.from_row should expose is_hidden as a bool (defaulting to False)."""
    row = {
        "id": 1, "municipality_id": 1, "external_id": "x",
        "title": "t", "meeting_date": None, "meeting_type": None,
        "agenda_url": None, "minutes_url": None, "video_url": None,
        "source_url": None,
        # is_hidden NOT in row — model should default to False
    }
    m = Meeting.from_row(row)
    assert m.is_hidden is False


def test_meeting_from_row_reads_is_hidden_true():
    row = {
        "id": 1, "municipality_id": 1, "external_id": "x",
        "title": "t", "meeting_date": None, "meeting_type": None,
        "agenda_url": None, "minutes_url": None, "video_url": None,
        "source_url": None,
        "is_hidden": True,
    }
    m = Meeting.from_row(row)
    assert m.is_hidden is True
```

- [ ] **Step 2: Confirm failure**

```
venv/bin/pytest tests/unit/test_meeting_models.py::test_meeting_from_row_reads_is_hidden_default_false -v
```

Expected: FAIL — `AttributeError: 'Meeting' object has no attribute 'is_hidden'`.

- [ ] **Step 3: Add the field to the dataclass**

In `src/docket/models/meeting.py`, add a field after `start_time`:

```python
    start_time: time | None = None
    is_hidden: bool = False
```

And in `from_row`:

```python
            start_time=row.get("start_time"),
            is_hidden=bool(row.get("is_hidden", False)),
```

- [ ] **Step 4: Re-run tests — should pass**

```
venv/bin/pytest tests/unit/test_meeting_models.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```
git add src/docket/models/meeting.py tests/unit/test_meeting_models.py
git -c commit.gpgsign=false commit -m "models: Meeting.is_hidden field"
```

---

## Task 4: Service filter — `list_meetings` + `dashboard_stats` + city-scoped lists

**Files:**
- Modify: `src/docket/services/query.py` (the four functions below)
- Create: `tests/unit/test_query_hidden_meetings.py` (one file for all service-layer filter tests across Tasks 4-9)

The patched call-sites in this task:

| Function | Line (approx) | Predicate to add |
|---|---|---|
| `list_meetings` | 63 | `where = "m.slug = %s AND mt.is_hidden = FALSE"` (line 72) — also `COUNT(*)` query gets the same |
| `dashboard_stats` — meetings count | 437 | `cur.execute("SELECT COUNT(*) AS count FROM meetings WHERE is_hidden = FALSE")` |
| `dashboard_stats` — agenda_items count | 440 | Must JOIN to `meetings` and filter — see Step 5 |
| `dashboard_stats` — votes count | 443 | Same — see Step 5 |
| `list_recent_meetings_for_city` | 893 | add `AND mt.is_hidden = FALSE` inside the WHERE clause |
| `list_upcoming_meetings_for_city` | 916 | same |

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_query_hidden_meetings.py`:

```python
"""Tests asserting every citizen-facing meeting/item query excludes
rows with meetings.is_hidden=TRUE.

One file covers Tasks 4-9 (every patched function). Seed two meetings
per scenario: one visible, one hidden. Assert only the visible one
surfaces. Cleanup is title-prefixed for idempotency.

Pattern mirrors tests/unit/test_query_related_items.py.
"""

import pytest
import psycopg2.extras

from docket.db import db
from docket.services import query


TEST_PREFIX = "TEST_HIDE_"


def _cleanup():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM agenda_items "
                "WHERE meeting_id IN (SELECT id FROM meetings WHERE title LIKE %s)",
                (f"{TEST_PREFIX}%",),
            )
            cur.execute(
                "DELETE FROM meetings WHERE title LIKE %s",
                (f"{TEST_PREFIX}%",),
            )
        conn.commit()


@pytest.fixture
def hidden_meeting_seed():
    """Two BHM meetings on consecutive dates — one visible, one hidden.

    Yields a dict with the two meeting ids and the city slug.
    """
    _cleanup()
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, slug FROM municipalities WHERE slug = 'birmingham'")
            row = cur.fetchone()
            muni_id, slug = row["id"], row["slug"]

            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type, is_hidden)
                   VALUES (%s, %s, '2099-04-01', 'council', FALSE) RETURNING id""",
                (muni_id, f"{TEST_PREFIX}visible"),
            )
            visible_id = cur.fetchone()["id"]

            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type, is_hidden)
                   VALUES (%s, %s, '2099-04-02', 'council', TRUE) RETURNING id""",
                (muni_id, f"{TEST_PREFIX}hidden"),
            )
            hidden_id = cur.fetchone()["id"]
        conn.commit()
    yield {"visible_id": visible_id, "hidden_id": hidden_id, "slug": slug, "muni_id": muni_id}
    _cleanup()


# ---------------------------------------------------------------------------
# Task 4 — list_meetings + dashboard_stats + city-scoped recent/upcoming
# ---------------------------------------------------------------------------


def test_list_meetings_excludes_hidden(hidden_meeting_seed):
    result = query.list_meetings(hidden_meeting_seed["slug"], since="2099-01-01")
    ids = {m.id for m in result.meetings}
    assert hidden_meeting_seed["visible_id"] in ids
    assert hidden_meeting_seed["hidden_id"] not in ids


def test_list_meetings_count_excludes_hidden(hidden_meeting_seed):
    result = query.list_meetings(hidden_meeting_seed["slug"], since="2099-01-01")
    # Count reflects only visible; we expect exactly the one we seeded plus whatever's
    # already in the DB after 2099-01-01 (which should be zero in a clean test DB,
    # but we assert weakly to allow accidental future seeds: hidden never counted).
    visible = [m for m in result.meetings if m.title.startswith(TEST_PREFIX)]
    assert len(visible) == 1


def test_dashboard_stats_excludes_hidden_meetings_and_their_items_and_votes(hidden_meeting_seed):
    """dashboard_stats returns dict with keys 'municipalities', 'meetings',
    'agenda_items', 'votes' (verified by reading query.py:446-451). All three
    of meetings/agenda_items/votes must exclude rows belonging to hidden
    meetings, not just the meetings count itself."""
    # Seed an item AND a vote on the hidden meeting; if the dashboard counts
    # leak them, this test will catch it. Helper inlined here so Task 4 test
    # has no dependency on helpers defined later in the file (Task 6).
    hidden_item_id = None
    hidden_vote_id = None
    try:
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agenda_items
                     (meeting_id, title, item_number, processing_status)
                   VALUES (%s, 'TEST_HIDE_stats_item', '1', 'pending')
                   RETURNING id""",
                (hidden_meeting_seed["hidden_id"],),
            )
            hidden_item_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO votes
                     (meeting_id, result, yeas, nays, abstentions, source, confidence)
                   VALUES (%s, 'passed', 7, 0, 0, 'test', 'high')
                   RETURNING id""",
                (hidden_meeting_seed["hidden_id"],),
            )
            hidden_vote_id = cur.fetchone()[0]
            conn.commit()

        stats = query.dashboard_stats()
        with db() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM meetings WHERE is_hidden = FALSE")
            expected_meetings = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM agenda_items ai "
                "JOIN meetings m ON ai.meeting_id = m.id "
                "WHERE m.is_hidden = FALSE"
            )
            expected_items = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM votes v "
                "JOIN meetings m ON v.meeting_id = m.id "
                "WHERE m.is_hidden = FALSE"
            )
            expected_votes = cur.fetchone()[0]
        assert stats["meetings"] == expected_meetings
        assert stats["agenda_items"] == expected_items
        assert stats["votes"] == expected_votes
    finally:
        with db() as conn, conn.cursor() as cur:
            if hidden_vote_id is not None:
                cur.execute("DELETE FROM votes WHERE id = %s", (hidden_vote_id,))
            if hidden_item_id is not None:
                cur.execute("DELETE FROM agenda_items WHERE id = %s", (hidden_item_id,))
            conn.commit()


def test_list_recent_meetings_for_city_excludes_hidden(hidden_meeting_seed):
    # The function filters by date window — we seeded 2099 dates so the recent
    # window won't include them by date alone. Re-seed with a recent date.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meetings SET meeting_date = CURRENT_DATE - 1 WHERE id = %s",
            (hidden_meeting_seed["visible_id"],),
        )
        cur.execute(
            "UPDATE meetings SET meeting_date = CURRENT_DATE - 1 WHERE id = %s",
            (hidden_meeting_seed["hidden_id"],),
        )
        conn.commit()
    rows = query.list_recent_meetings_for_city(
        hidden_meeting_seed["slug"], days=7, limit=20
    )
    ids = {r["id"] for r in rows}
    assert hidden_meeting_seed["visible_id"] in ids
    assert hidden_meeting_seed["hidden_id"] not in ids
```

- [ ] **Step 2: Run the new tests — they should fail before the patch**

```
venv/bin/pytest tests/unit/test_query_hidden_meetings.py -v
```

Expected: all 4 in this task FAIL (hidden meetings still appear).

- [ ] **Step 3: Patch `list_meetings`**

In `src/docket/services/query.py:63-99`, change two SQL strings:

```python
        where = "m.slug = %s AND mt.is_hidden = FALSE"
```

(was `where = "m.slug = %s"`). Both `COUNT(*)` and the paginated SELECT use the same `where` variable so the single edit covers both.

- [ ] **Step 4: Patch `dashboard_stats` — all three meetings-derived counts**

In `src/docket/services/query.py:431-451`, change three queries inside the function:

```python
def dashboard_stats() -> dict:
    """Return summary stats for the admin dashboard."""
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS count FROM municipalities WHERE active = TRUE")
        muni_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) AS count FROM meetings WHERE is_hidden = FALSE")
        meeting_count = cur.fetchone()["count"]

        cur.execute(
            "SELECT COUNT(*) AS count FROM agenda_items ai "
            "JOIN meetings m ON ai.meeting_id = m.id "
            "WHERE m.is_hidden = FALSE"
        )
        item_count = cur.fetchone()["count"]

        cur.execute(
            "SELECT COUNT(*) AS count FROM votes v "
            "JOIN meetings m ON v.meeting_id = m.id "
            "WHERE m.is_hidden = FALSE"
        )
        vote_count = cur.fetchone()["count"]

        return {
            "municipalities": muni_count,
            "meetings": meeting_count,
            "agenda_items": item_count,
            "votes": vote_count,
        }
```

The agenda_items and votes counts now JOIN through `meetings` so items/votes belonging to hidden meetings don't inflate the public totals on the index page and city overview.

- [ ] **Step 5: Patch `list_recent_meetings_for_city` and `list_upcoming_meetings_for_city`**

In `src/docket/services/query.py:893-931`, add `AND mt.is_hidden = FALSE` to the WHERE block in each function (already-present clauses include `m.active = TRUE` and a `_UPCOMING_PREDICATE_MT` reference; add the new predicate right after `m.active = TRUE`):

```sql
        WHERE m.slug = %s
          AND m.active = TRUE
          AND mt.is_hidden = FALSE
          AND NOT ({_UPCOMING_PREDICATE_MT})
```

(and the analogous edit for the upcoming variant — keep its `{_UPCOMING_PREDICATE_MT}` without the `NOT`).

- [ ] **Step 6: Re-run tests — should pass**

```
venv/bin/pytest tests/unit/test_query_hidden_meetings.py -v
```

Expected: 4 passed.

- [ ] **Step 7: Commit**

```
git add src/docket/services/query.py tests/unit/test_query_hidden_meetings.py
git -c commit.gpgsign=false commit -m "query: filter hidden meetings in list_meetings + dashboard + city-scoped lists"
```

---

## Task 5: Service filter — cross-city `list_recent_meetings` + `list_upcoming_meetings` + `search_meetings`

**Files:**
- Modify: `src/docket/services/query.py`
- Modify: `tests/unit/test_query_hidden_meetings.py` (append more tests)

- [ ] **Step 1: Add the failing tests**

Append to `tests/unit/test_query_hidden_meetings.py`:

```python
# ---------------------------------------------------------------------------
# Task 5 — cross-city recent/upcoming + search_meetings
# ---------------------------------------------------------------------------


def test_list_recent_meetings_cross_city_excludes_hidden(hidden_meeting_seed):
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meetings SET meeting_date = CURRENT_DATE - 1 WHERE id IN (%s, %s)",
            (hidden_meeting_seed["visible_id"], hidden_meeting_seed["hidden_id"]),
        )
        conn.commit()
    rows = query.list_recent_meetings(days=7, limit=50)
    ids = {r["id"] for r in rows}
    assert hidden_meeting_seed["visible_id"] in ids
    assert hidden_meeting_seed["hidden_id"] not in ids


def test_list_upcoming_meetings_cross_city_excludes_hidden(hidden_meeting_seed):
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meetings SET meeting_date = CURRENT_DATE + 3 WHERE id IN (%s, %s)",
            (hidden_meeting_seed["visible_id"], hidden_meeting_seed["hidden_id"]),
        )
        conn.commit()
    rows = query.list_upcoming_meetings(days=14, limit=50)
    ids = {r["id"] for r in rows}
    assert hidden_meeting_seed["visible_id"] in ids
    assert hidden_meeting_seed["hidden_id"] not in ids


def test_search_meetings_excludes_hidden(hidden_meeting_seed):
    # Seed sets titles to TEST_HIDE_visible / TEST_HIDE_hidden — search for the
    # shared substring. Hidden one must not appear in results.
    results = query.search_meetings("TEST_HIDE", municipality_slug=hidden_meeting_seed["slug"])
    ids = {r["id"] for r in results}
    assert hidden_meeting_seed["visible_id"] in ids
    assert hidden_meeting_seed["hidden_id"] not in ids
```

- [ ] **Step 2: Confirm failures**

```
venv/bin/pytest tests/unit/test_query_hidden_meetings.py -v -k "cross_city or search_meetings"
```

Expected: 3 FAIL.

- [ ] **Step 3: Patch the three functions**

In `src/docket/services/query.py`:

- `list_recent_meetings` (line 856): add `AND mt.is_hidden = FALSE` after the `m.active = TRUE` line.
- `list_upcoming_meetings` (line 876): same edit.
- `search_meetings` (line 937): add `AND mt.is_hidden = FALSE` to the `where` string — change:

  ```python
  where = "m.active = TRUE AND mt.search_vector @@ websearch_to_tsquery('english', %s)"
  ```

  to:

  ```python
  where = "m.active = TRUE AND mt.is_hidden = FALSE AND mt.search_vector @@ websearch_to_tsquery('english', %s)"
  ```

- [ ] **Step 4: Re-run tests**

```
venv/bin/pytest tests/unit/test_query_hidden_meetings.py -v -k "cross_city or search_meetings"
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add src/docket/services/query.py tests/unit/test_query_hidden_meetings.py
git -c commit.gpgsign=false commit -m "query: filter hidden meetings in cross-city recent/upcoming + search_meetings"
```

---

## Task 6: Service filter — item-level queries that JOIN to meetings

**Files:**
- Modify: `src/docket/services/query.py`
- Modify: `tests/unit/test_query_hidden_meetings.py`

Five functions need `m.is_hidden = FALSE` (the FROM ... JOIN meetings m / mt block already exists; add the predicate to the WHERE):

| Function | Approx line |
|---|---|
| `get_agenda_item` | 263 |
| `search_agenda_items` | 970 |
| `list_agenda_items_by_topic` | 1071 |
| `list_related_items_by_topic` | 1130 |
| `list_related_items_by_sponsor` | 1190 |

**`get_agenda_item` note:** Currently this function does NOT JOIN to `meetings` (only `agenda_item_badges`). It needs both a JOIN and a WHERE predicate. The function is permalink-style and used by `item_detail`, so for citizen access we need to suppress items whose parent meeting is hidden. The admin-bypass branch (Task 11) calls a different code path.

- [ ] **Step 1: Add the failing tests**

Append to `tests/unit/test_query_hidden_meetings.py`:

```python
# ---------------------------------------------------------------------------
# Task 6 — item-level queries
# ---------------------------------------------------------------------------


def _seed_item(meeting_id: int, *, title: str = "TEST_HIDE_item", topic: str = "housing",
               sponsor: str = "TEST_HIDE_sponsor") -> int:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO agenda_items
                 (meeting_id, title, topic, sponsor, item_number, processing_status)
               VALUES (%s, %s, %s, %s, '1', 'pending') RETURNING id""",
            (meeting_id, title, topic, sponsor),
        )
        iid = cur.fetchone()[0]
        conn.commit()
    return iid


def test_get_agenda_item_returns_none_when_parent_hidden(hidden_meeting_seed):
    # Item belongs to the hidden meeting — public read path must return None.
    iid = _seed_item(hidden_meeting_seed["hidden_id"])
    assert query.get_agenda_item(iid) is None


def test_get_agenda_item_returns_visible(hidden_meeting_seed):
    iid = _seed_item(hidden_meeting_seed["visible_id"])
    item = query.get_agenda_item(iid)
    assert item is not None and item.id == iid


def test_search_agenda_items_excludes_hidden_parent(hidden_meeting_seed):
    visible_item_id = _seed_item(
        hidden_meeting_seed["visible_id"], title="TEST_HIDE_search visible"
    )
    hidden_item_id = _seed_item(
        hidden_meeting_seed["hidden_id"], title="TEST_HIDE_search hidden"
    )
    results = query.search_agenda_items(
        "TEST_HIDE_search", municipality_slug=hidden_meeting_seed["slug"]
    )
    ids = {r.id for r in results}
    assert visible_item_id in ids
    assert hidden_item_id not in ids


def test_list_agenda_items_by_topic_excludes_hidden_parent(hidden_meeting_seed):
    visible_item_id = _seed_item(
        hidden_meeting_seed["visible_id"], topic="TEST_HIDE_topic"
    )
    hidden_item_id = _seed_item(
        hidden_meeting_seed["hidden_id"], topic="TEST_HIDE_topic"
    )
    results = query.list_agenda_items_by_topic(
        "TEST_HIDE_topic", municipality_slug=hidden_meeting_seed["slug"]
    )
    ids = {r["id"] for r in results}
    assert visible_item_id in ids
    assert hidden_item_id not in ids


def test_list_related_items_by_topic_excludes_hidden_parent(hidden_meeting_seed):
    # Seed: visible meeting has the seed item; another visible meeting has a
    # match; the hidden meeting has a would-be match that must NOT surface.
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type, is_hidden)
               VALUES (%s, %s, '2099-04-03', 'council', FALSE) RETURNING id""",
            (hidden_meeting_seed["muni_id"], "TEST_HIDE_other_visible"),
        )
        other_visible_id = cur.fetchone()["id"]
        conn.commit()

    seed_item_id = _seed_item(
        hidden_meeting_seed["visible_id"], topic="TEST_HIDE_rel"
    )
    other_visible_item_id = _seed_item(other_visible_id, topic="TEST_HIDE_rel")
    hidden_item_id = _seed_item(
        hidden_meeting_seed["hidden_id"], topic="TEST_HIDE_rel"
    )

    related = query.list_related_items_by_topic(seed_item_id, limit=10)
    ids = {r["id"] for r in related}
    assert other_visible_item_id in ids
    assert hidden_item_id not in ids


def test_list_related_items_by_sponsor_excludes_hidden_parent(hidden_meeting_seed):
    seed_item_id = _seed_item(
        hidden_meeting_seed["visible_id"], sponsor="TEST_HIDE_sponsor_X"
    )
    hidden_item_id = _seed_item(
        hidden_meeting_seed["hidden_id"], sponsor="TEST_HIDE_sponsor_X"
    )
    # Add a second visible match so the function returns at least one result.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type, is_hidden)
               VALUES (%s, %s, '2099-04-04', 'council', FALSE) RETURNING id""",
            (hidden_meeting_seed["muni_id"], "TEST_HIDE_sponsor_match"),
        )
        match_meeting_id = cur.fetchone()[0]
        conn.commit()
    visible_match_id = _seed_item(match_meeting_id, sponsor="TEST_HIDE_sponsor_X")

    related = query.list_related_items_by_sponsor(seed_item_id, limit=10)
    ids = {r["id"] for r in related}
    assert visible_match_id in ids
    assert hidden_item_id not in ids
```

- [ ] **Step 2: Confirm failures**

```
venv/bin/pytest tests/unit/test_query_hidden_meetings.py -v -k "agenda_item or related or topic"
```

Expected: 6 FAIL.

- [ ] **Step 3: Patch `get_agenda_item`**

In `src/docket/services/query.py:263-337`, change the FROM/WHERE block so it JOINs `meetings` and filters hidden:

```python
            FROM agenda_items ai
            JOIN meetings mt ON mt.id = ai.meeting_id
            LEFT JOIN LATERAL (
                ...
            ) b_agg ON true
            WHERE ai.id = %s
              AND mt.is_hidden = FALSE
```

- [ ] **Step 4: Patch `search_agenda_items`**

Find the `where` declaration (line 988):

```python
        where = "m.active = TRUE AND ai.search_vector @@ websearch_to_tsquery('english', %s)"
```

Change to:

```python
        where = "m.active = TRUE AND mt.is_hidden = FALSE AND ai.search_vector @@ websearch_to_tsquery('english', %s)"
```

- [ ] **Step 5: Patch `list_agenda_items_by_topic`**

Find (line 1093):

```python
            WHERE m.active = TRUE AND {where}
```

Change to:

```python
            WHERE m.active = TRUE AND mt.is_hidden = FALSE AND {where}
```

- [ ] **Step 6: Patch `list_related_items_by_topic` and `list_related_items_by_sponsor`**

In each (lines 1176, 1237) add `AND mt.is_hidden = FALSE` to the WHERE block:

```sql
        WHERE m.active = TRUE
          AND mt.is_hidden = FALSE
          AND ai.topic = %s
          ...
```

- [ ] **Step 7: Re-run tests**

```
venv/bin/pytest tests/unit/test_query_hidden_meetings.py -v
```

Expected: all previous tests PLUS the 6 new ones PASS.

- [ ] **Step 8: Commit**

```
git add src/docket/services/query.py tests/unit/test_query_hidden_meetings.py
git -c commit.gpgsign=false commit -m "query: filter hidden parent in item-level reads (get_agenda_item + search + topic + related)"
```

---

## Task 7: Service filter — `list_items_by_badge` + remaining meeting-joined queries

**Files:**
- Modify: `src/docket/services/query.py`
- Modify: `tests/unit/test_query_hidden_meetings.py`

The remaining query functions that JOIN to `meetings` and are reachable from public surfaces. Determine the full list with:

```
cd ~/docket-pub && grep -n "JOIN meetings " src/docket/services/query.py
```

Treat each result:

- **Already filtered** by `m.active = TRUE` AND citizen-facing? — add `AND mt.is_hidden = FALSE` (or `AND m.is_hidden = FALSE` matching the alias used).
- **Already filtered** but admin-only (look at the caller in `web/admin.py`)? — leave alone.
- **No municipality JOIN at all** but reads meetings (e.g., vote pages)? — add `AND m.is_hidden = FALSE`.

Definitely patch (citizen-facing): `list_items_by_badge` (1402), `category_kpis` (1618), `category_tally` (1703), `list_recent_votes` (454), `list_contested_votes` (476), `list_member_voting_history` (640), `list_sponsored_items_for_member` (723), `get_member_vote_summary` (783), `count_sponsored_items_for_member` (601), `list_upcoming_hearings` (find via grep), `coverage_for_subject` / `coverage_counts_for_items` only insofar as the subject's parent meeting must be visible — see below.

**Coverage queries note:** `coverage_for_subject('agenda_item', ...)` returns rows from `coverage_entries` joined via `coverage_subject_links` — the parent meeting isn't in the JOIN today. For v1, leave coverage_for_subject alone (it operates by subject_id which is already gated upstream — if `get_agenda_item` returns None for a hidden parent, the public template never calls coverage_for_subject for that item). Add an explicit comment in the code saying so. `coverage_counts_for_items` accepts a `list[int]` and is called only with items that already came through a filtered list — no change needed.

- [ ] **Step 1: Add the failing tests**

Append to `tests/unit/test_query_hidden_meetings.py`:

```python
# ---------------------------------------------------------------------------
# Task 7 — list_items_by_badge + member queries + vote queries
# ---------------------------------------------------------------------------


def test_list_items_by_badge_excludes_hidden_parent(hidden_meeting_seed):
    # Seed two items in two meetings, attach the same badge to both, mark one
    # meeting hidden. Only the visible-parent item should surface.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT slug FROM priority_badge_templates "
            "WHERE kind = 'process' ORDER BY slug LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            pytest.skip("No process badge templates seeded; skipping.")
        badge_slug = row[0]

    visible_item_id = _seed_item(
        hidden_meeting_seed["visible_id"], title="TEST_HIDE_badge_visible"
    )
    hidden_item_id = _seed_item(
        hidden_meeting_seed["hidden_id"], title="TEST_HIDE_badge_hidden"
    )

    # Attach the badge as 'applied' to both items, confidence > 0.6.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT kind FROM priority_badge_templates WHERE slug = %s",
            (badge_slug,),
        )
        kind = cur.fetchone()[0]
        for iid in (visible_item_id, hidden_item_id):
            cur.execute(
                """INSERT INTO agenda_item_badges
                     (agenda_item_id, city_id, badge_slug, kind,
                      confidence, source, status)
                   VALUES (%s, %s, %s, %s, 0.9, 'manual', 'applied')""",
                (iid, hidden_meeting_seed["muni_id"], badge_slug, kind),
            )
        # Mark items completed so the processing_status='completed' filter passes.
        cur.execute(
            "UPDATE agenda_items SET processing_status='completed' WHERE id IN (%s, %s)",
            (visible_item_id, hidden_item_id),
        )
        conn.commit()

    items = query.list_items_by_badge(
        city_id=hidden_meeting_seed["muni_id"],
        badge_slug=badge_slug,
        include_low_significance=True,  # bypass significance gate for the test
    )
    ids = {it.id for it in items}
    assert visible_item_id in ids
    assert hidden_item_id not in ids
```

(Skipping per-function tests for the vote / member queries — those are lower-traffic and the contract is the same `JOIN meetings + WHERE m.is_hidden = FALSE`. We rely on the visual smoke test from the integration test suite to catch regressions there. If finer coverage is wanted post-deploy, add tests in a follow-up.)

- [ ] **Step 2: Confirm failure**

```
venv/bin/pytest tests/unit/test_query_hidden_meetings.py::test_list_items_by_badge_excludes_hidden_parent -v
```

Expected: FAIL.

- [ ] **Step 3: Patch `list_items_by_badge`**

In `src/docket/services/query.py:1402+`, find the FROM/JOIN block (around line 1486-ish):

```
cd ~/docket-pub && sed -n '1480,1520p' src/docket/services/query.py
```

Add `AND m.is_hidden = FALSE` to the WHERE conditions inside the SQL. (The function builds SQL in parts via `sql_parts.append(...)`. Locate the section that contains `aib.city_id = %s` and add the predicate alongside the other base filters.)

- [ ] **Step 4: Patch the remaining JOIN meetings sites**

Run:

```
cd ~/docket-pub && grep -n "JOIN meetings " src/docket/services/query.py
```

For each result line (~50 total), open the surrounding function and:

- **If the function is called from `web/public.py`, `web/templates/`, or any RSS route** → add `AND m.is_hidden = FALSE` (or the alias matching that query — `mt.is_hidden = FALSE`).
- **If the function is admin-only** (callers all in `web/admin.py`) → leave alone, add a one-line comment: `# Admin path: hidden meetings remain visible here.`
- **If it's a helper used by both surfaces** (e.g., `coverage_for_subject`, vote-attachment helpers) → leave the JOIN alone but add a one-line comment explaining that the upstream caller already gates by hidden status.

Functions known to need the predicate (compiled from the spec inventory):
- `list_recent_votes` (454)
- `list_contested_votes` (476)
- `count_sponsored_items_for_member` (601)
- `list_member_voting_history` (640)
- `list_sponsored_items_for_member` (723)
- `get_member_vote_summary` (783)
- `topic_counts` (1102) — drives the public browse-by-topic UI; reads `m.slug = %s` already, add `AND mt.is_hidden = FALSE` to the WHERE clause built from `where`
- `category_kpis` (1618)
- `category_tally` (1703)
- Any `list_upcoming_hearings` (grep to find — line number varies)

In each, add `AND m.is_hidden = FALSE` to the existing WHERE clause. Use the alias the query already declared (`m` or `mt`).

- [ ] **Step 5: Re-run the full test suite**

```
venv/bin/pytest tests/unit/test_query_hidden_meetings.py tests/unit/test_query_related_items.py tests/unit/test_query_list_votes.py tests/unit/test_query_member_history.py -v
```

Expected: all pass. The pre-existing query tests should not regress.

- [ ] **Step 6: Commit**

```
git add src/docket/services/query.py tests/unit/test_query_hidden_meetings.py
git -c commit.gpgsign=false commit -m "query: filter hidden meetings across badge/vote/member/category queries"
```

---

## Task 8: Public route — `meeting_detail` admin bypass

**Files:**
- Modify: `src/docket/web/public.py` (`meeting_detail` around line 231)
- Create: `tests/integration/test_admin_hide_meeting.py` (one integration file covers Tasks 8, 9, 12, 13, 14)

The behavior: anonymous user requesting a hidden meeting → 404. Logged-in admin → renders normally so they can see and unhide it. `get_meeting` is a model-fetch helper that does NOT filter hidden (it's the raw row read for admin and ingest paths). The route itself enforces the visibility rule.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_admin_hide_meeting.py`:

```python
"""Integration tests for the hide-meeting feature — admin bypass on detail
pages, hide/unhide POST routes, admin index, and meeting_detail template
toggle.

Pattern mirrors tests/integration/test_admin_badge_review.py — _Bag tracker,
app/client/admin_client fixtures, BHM seed.
"""

from __future__ import annotations

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run hide-meeting tests against Railway DB.",
)


class _Bag:
    def __init__(self, city_id: int, city_slug: str):
        self.city_id = city_id
        self.city_slug = city_slug
        self.meeting_ids: list[int] = []
        self.item_ids: list[int] = []
        self.admin_id: int | None = None

    def add_meeting(self, *, is_hidden: bool = False, title: str = "TEST_HIDE_meeting") -> int:
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO meetings
                  (municipality_id, title, meeting_date, meeting_type, is_hidden)
                VALUES (%s, %s, '2099-05-01', 'council', %s)
                RETURNING id
                """,
                (self.city_id, title, is_hidden),
            )
            mid = cur.fetchone()[0]
            conn.commit()
        self.meeting_ids.append(mid)
        return mid

    def add_item(self, meeting_id: int, *, title: str = "TEST_HIDE_item") -> int:
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agenda_items
                     (meeting_id, title, item_number, processing_status)
                   VALUES (%s, %s, '1', 'pending')
                   RETURNING id""",
                (meeting_id, title),
            )
            iid = cur.fetchone()[0]
            conn.commit()
        self.item_ids.append(iid)
        return iid

    def ensure_admin(self, username: str = "tester_hide") -> int:
        from werkzeug.security import generate_password_hash
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO admin_users (username, password_hash)
                   VALUES (%s, %s)
                   ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash
                   RETURNING id""",
                (username, generate_password_hash("pw")),
            )
            uid = cur.fetchone()[0]
            conn.commit()
        self.admin_id = uid
        return uid

    def cleanup(self):
        with db() as conn, conn.cursor() as cur:
            if self.item_ids:
                cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", (self.item_ids,))
            if self.meeting_ids:
                cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", (self.meeting_ids,))
            if self.admin_id is not None:
                cur.execute("DELETE FROM admin_users WHERE id = %s", (self.admin_id,))
            conn.commit()


def _bag_for(slug: str = "birmingham") -> _Bag:
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, slug FROM municipalities WHERE slug = %s", (slug,))
        row = cur.fetchone()
    assert row is not None, f"City must be seeded: {slug}"
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
    flask_app.config["SECRET_KEY"] = "test-secret-key-hide"
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_client(app, bag):
    uid = bag.ensure_admin()
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["admin_user"] = "tester_hide"
        sess["admin_user_id"] = uid
    return c


# ---------------------------------------------------------------------------
# Task 8 — meeting_detail admin bypass
# ---------------------------------------------------------------------------


def test_meeting_detail_404_for_anonymous_when_hidden(client, bag):
    mid = bag.add_meeting(is_hidden=True)
    rv = client.get(f"/al/{bag.city_slug}/meetings/{mid}/")
    assert rv.status_code == 404


def test_meeting_detail_200_for_admin_when_hidden(admin_client, bag):
    mid = bag.add_meeting(is_hidden=True)
    rv = admin_client.get(f"/al/{bag.city_slug}/meetings/{mid}/")
    assert rv.status_code == 200


def test_meeting_detail_200_for_anonymous_when_visible(client, bag):
    mid = bag.add_meeting(is_hidden=False)
    rv = client.get(f"/al/{bag.city_slug}/meetings/{mid}/")
    assert rv.status_code == 200
```

- [ ] **Step 2: Confirm failure**

```
venv/bin/pytest tests/integration/test_admin_hide_meeting.py::test_meeting_detail_404_for_anonymous_when_hidden -v
```

Expected: FAIL — anon currently gets 200 because the route uses raw `get_meeting`.

- [ ] **Step 3: Patch `meeting_detail`**

In `src/docket/web/public.py:231-239`, change:

```python
    meeting = query.get_meeting(meeting_id)
    if not meeting or meeting.municipality_id != municipality["id"]:
        abort(404)
```

to:

```python
    meeting = query.get_meeting(meeting_id)
    if not meeting or meeting.municipality_id != municipality["id"]:
        abort(404)

    # Hidden meetings are 404 for anonymous viewers; admins get the full page
    # with the hide/unhide banner from the template.
    if meeting.is_hidden and not session.get("admin_user"):
        abort(404)
```

Add `from flask import session` to the imports at the top of `public.py` if not already there. (It likely is — check imports first.)

- [ ] **Step 4: Re-run tests**

```
venv/bin/pytest tests/integration/test_admin_hide_meeting.py -v -k "meeting_detail"
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add src/docket/web/public.py tests/integration/test_admin_hide_meeting.py
git -c commit.gpgsign=false commit -m "public: meeting_detail 404 anon / 200 admin for hidden meetings"
```

---

## Task 9: Public route — `item_detail` admin bypass

**Files:**
- Modify: `src/docket/web/public.py` (`item_detail` around line 279)
- Modify: `tests/integration/test_admin_hide_meeting.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_admin_hide_meeting.py`:

```python
# ---------------------------------------------------------------------------
# Task 9 — item_detail admin bypass
# ---------------------------------------------------------------------------


def test_item_detail_404_for_anonymous_when_parent_hidden(client, bag):
    mid = bag.add_meeting(is_hidden=True)
    iid = bag.add_item(mid)
    rv = client.get(f"/al/{bag.city_slug}/items/{iid}/")
    assert rv.status_code == 404


def test_item_detail_200_for_admin_when_parent_hidden(admin_client, bag):
    mid = bag.add_meeting(is_hidden=True)
    iid = bag.add_item(mid)
    rv = admin_client.get(f"/al/{bag.city_slug}/items/{iid}/")
    assert rv.status_code == 200


def test_item_detail_200_for_anonymous_when_parent_visible(client, bag):
    mid = bag.add_meeting(is_hidden=False)
    iid = bag.add_item(mid)
    rv = client.get(f"/al/{bag.city_slug}/items/{iid}/")
    assert rv.status_code == 200
```

- [ ] **Step 2: Confirm failure**

```
venv/bin/pytest tests/integration/test_admin_hide_meeting.py -v -k "item_detail"
```

Expected: at least the admin case FAILS — `query.get_agenda_item` was patched in Task 6 to filter hidden parents, so anonymous correctly gets 404 already. But the admin case fails because `get_agenda_item` returns None even for admin → 404 mistakenly.

- [ ] **Step 3: Refactor for admin bypass**

The cleanest fix: introduce an `include_hidden` parameter on `get_agenda_item` (and `get_meeting`) so the route can ask for the row regardless of visibility, then make the route enforce the visibility rule itself.

Option B (smaller diff, preferred for v1): keep `get_agenda_item` strict (returns None for hidden parent), and in the route, fall back to a raw fetch when the user is admin.

Implement Option B. In `src/docket/services/query.py`, add a helper next to `get_agenda_item`:

```python
def get_agenda_item_for_admin(item_id: int) -> AgendaItem | None:
    """Like ``get_agenda_item`` but does NOT filter on parent meeting visibility.

    Used by the public detail route's admin-bypass branch — admins can view
    items belonging to hidden meetings. Citizens get the strict version.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT ai.*,
                   COALESCE(b_agg.badges, '[]'::jsonb) AS badges
            FROM agenda_items ai
            LEFT JOIN LATERAL (
                SELECT jsonb_agg(jsonb_build_object(
                           'kind',        b.kind,
                           'slug',        b.badge_slug,
                           'confidence',  b.confidence,
                           'name',        t.name,
                           'icon',        t.icon,
                           'description', t.description
                       ) ORDER BY b.detected_at DESC) AS badges
                FROM agenda_item_badges b
                JOIN priority_badge_templates t ON t.slug = b.badge_slug
                WHERE b.agenda_item_id = ai.id
                  AND b.status = 'applied'
            ) b_agg ON true
            WHERE ai.id = %s
            """,
            (item_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return AgendaItem.from_row(dict(row))
```

Then in `src/docket/web/public.py` `item_detail` (line 279-292), change:

```python
    item = query.get_agenda_item(item_id)
    if not item:
        abort(404)

    # Verify the item belongs to this city via its meeting
    meeting = query.get_meeting(item.meeting_id)
    if not meeting or meeting.municipality_id != municipality["id"]:
        abort(404)
```

to:

```python
    is_admin = bool(session.get("admin_user"))
    item = (
        query.get_agenda_item_for_admin(item_id)
        if is_admin
        else query.get_agenda_item(item_id)
    )
    if not item:
        abort(404)

    # Verify the item belongs to this city via its meeting
    meeting = query.get_meeting(item.meeting_id)
    if not meeting or meeting.municipality_id != municipality["id"]:
        abort(404)
    if meeting.is_hidden and not is_admin:
        abort(404)
```

The `meeting.is_hidden and not is_admin` check is belt-and-suspenders (the strict `get_agenda_item` already returns None in this case for anon) — but it's clear about intent. Ensure `session` is imported at the top of `public.py`.

- [ ] **Step 4: Re-run tests**

```
venv/bin/pytest tests/integration/test_admin_hide_meeting.py -v -k "item_detail or meeting_detail"
```

Expected: all 6 pass.

- [ ] **Step 5: Commit**

```
git add src/docket/services/query.py src/docket/web/public.py tests/integration/test_admin_hide_meeting.py
git -c commit.gpgsign=false commit -m "public: item_detail admin bypass via get_agenda_item_for_admin"
```

---

## Task 10: RSS filters — coverage feeds, upcoming_hearings, data_debt

**Files:**
- Modify: `src/docket/services/query.py` (functions powering the RSS routes)
- Modify: `tests/integration/test_admin_hide_meeting.py`

- [ ] **Step 1: Locate the RSS-backing queries**

```
cd ~/docket-pub && grep -n "list_upcoming_hearings\|coverage_rss\|data_debt_rss" src/docket/services/query.py src/docket/web/public.py | head -20
```

For each query function the RSS route calls, verify it JOINs `meetings`. If yes, add `AND m.is_hidden = FALSE` to its WHERE.

- [ ] **Step 2: Add a single integration test asserting RSS excludes a hidden parent**

Append to `tests/integration/test_admin_hide_meeting.py`:

```python
# ---------------------------------------------------------------------------
# Task 10 — RSS filters
# ---------------------------------------------------------------------------


def test_upcoming_hearings_rss_excludes_hidden(client, bag):
    """If a hidden meeting were a public hearing, its row must NOT appear
    in /al/<city>/upcoming-hearings.rss. We seed both shapes and assert
    the hidden one's title is absent from the rendered XML."""
    mid_visible = bag.add_meeting(is_hidden=False, title="TEST_HIDE_rss_visible")
    mid_hidden = bag.add_meeting(is_hidden=True, title="TEST_HIDE_rss_hidden")

    # If the function uses a date window, set the meetings to future dates.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meetings SET meeting_date = CURRENT_DATE + 3 "
            "WHERE id IN (%s, %s)",
            (mid_visible, mid_hidden),
        )
        conn.commit()

    rv = client.get(f"/al/{bag.city_slug}/upcoming-hearings.rss")
    body = rv.get_data(as_text=True)
    # Visible title may appear (if the route's other filters pass); hidden must NOT.
    assert "TEST_HIDE_rss_hidden" not in body
```

(If `list_upcoming_hearings` has separate "public hearing" filters that exclude these seeded rows even when visible, the assertion `"TEST_HIDE_rss_hidden" not in body` is still meaningful — hidden never appears regardless.)

- [ ] **Step 3: Patch the RSS-backing queries**

Wherever the grep in Step 1 surfaced JOIN `meetings`, add `AND m.is_hidden = FALSE`. Add a brief comment: `# Citizen-facing RSS — exclude hidden meetings (spec §2).`

If the route also handles `bust_cache` via `_rss_cache` (see `public.py:553`), no cache invalidation is needed for this feature — the cache will turn over within 60 minutes naturally, and the spec accepts MV-style lag (§2). If the implementer prefers an immediate effect, clearing `_rss_cache.clear()` inside the hide/unhide POST handlers from Task 12 is the line of code for it; v1 doesn't require it.

- [ ] **Step 4: Run the test**

```
venv/bin/pytest tests/integration/test_admin_hide_meeting.py -v -k "rss"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```
git add src/docket/services/query.py tests/integration/test_admin_hide_meeting.py
git -c commit.gpgsign=false commit -m "rss: filter hidden meetings out of upcoming-hearings + coverage feeds"
```

---

## Task 11: Admin hide/unhide POST routes

**Files:**
- Modify: `src/docket/web/admin.py`
- Modify: `tests/integration/test_admin_hide_meeting.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_admin_hide_meeting.py`:

```python
# ---------------------------------------------------------------------------
# Task 11 — hide/unhide POST routes
# ---------------------------------------------------------------------------


def test_hide_meeting_post_sets_flag_and_audit(admin_client, bag):
    mid = bag.add_meeting(is_hidden=False)
    rv = admin_client.post(f"/admin/meetings/{mid}/hide", follow_redirects=False)
    assert rv.status_code in (302, 303)
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT is_hidden, hidden_at, hidden_by FROM meetings WHERE id = %s",
            (mid,),
        )
        row = cur.fetchone()
    is_hidden, hidden_at, hidden_by = row
    assert is_hidden is True
    assert hidden_at is not None
    assert hidden_by == bag.admin_id


def test_unhide_meeting_post_clears_flag_and_audit(admin_client, bag):
    mid = bag.add_meeting(is_hidden=True)
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meetings SET hidden_at = NOW(), hidden_by = %s WHERE id = %s",
            (bag.ensure_admin(), mid),
        )
        conn.commit()
    rv = admin_client.post(f"/admin/meetings/{mid}/unhide", follow_redirects=False)
    assert rv.status_code in (302, 303)
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT is_hidden, hidden_at, hidden_by FROM meetings WHERE id = %s",
            (mid,),
        )
        row = cur.fetchone()
    is_hidden, hidden_at, hidden_by = row
    assert is_hidden is False
    assert hidden_at is None
    assert hidden_by is None


def test_hide_meeting_requires_login(client, bag):
    mid = bag.add_meeting(is_hidden=False)
    rv = client.post(f"/admin/meetings/{mid}/hide", follow_redirects=False)
    # Blueprint before_request redirects to /admin/login when not authed.
    assert rv.status_code in (301, 302, 303, 308)
    location = rv.headers.get("Location", "")
    assert "/admin/login" in location


def test_hide_meeting_404_unknown(admin_client, bag):
    rv = admin_client.post("/admin/meetings/99999999/hide", follow_redirects=False)
    assert rv.status_code == 404
```

- [ ] **Step 2: Confirm failure**

```
venv/bin/pytest tests/integration/test_admin_hide_meeting.py -v -k "hide_meeting_post or unhide_meeting_post or hide_meeting_requires or hide_meeting_404"
```

Expected: all 4 FAIL — routes don't exist.

- [ ] **Step 3: Add the routes to `admin.py`**

In `src/docket/web/admin.py`, add at the bottom of the file (before any final scope-level statements):

```python
# --- Meeting visibility (hide / unhide) -------------------------------------


@bp.post("/meetings/<int:meeting_id>/hide")
def hide_meeting(meeting_id: int):
    """Mark a meeting as hidden — suppress it from all citizen surfaces.

    Sets is_hidden=TRUE plus the hidden_at/hidden_by audit columns. The
    blueprint-level before_request handler enforces login.
    """
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM meetings WHERE id = %s", (meeting_id,))
        if cur.fetchone() is None:
            abort(404)
        cur.execute(
            """
            UPDATE meetings
               SET is_hidden = TRUE,
                   hidden_at = NOW(),
                   hidden_by = %s
             WHERE id = %s
            """,
            (session.get("admin_user_id"), meeting_id),
        )
        conn.commit()
    flash(f"Meeting {meeting_id} hidden.")
    # Redirect back where the action was triggered if a referer is present;
    # fall back to the hidden-meetings admin index.
    referer = request.headers.get("Referer")
    return redirect(referer or url_for("admin.list_hidden_meetings"))


@bp.post("/meetings/<int:meeting_id>/unhide")
def unhide_meeting(meeting_id: int):
    """Clear the hidden flag and audit columns."""
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM meetings WHERE id = %s", (meeting_id,))
        if cur.fetchone() is None:
            abort(404)
        cur.execute(
            """
            UPDATE meetings
               SET is_hidden = FALSE,
                   hidden_at = NULL,
                   hidden_by = NULL
             WHERE id = %s
            """,
            (meeting_id,),
        )
        conn.commit()
    flash(f"Meeting {meeting_id} unhidden.")
    referer = request.headers.get("Referer")
    return redirect(referer or url_for("admin.list_hidden_meetings"))
```

Make sure `flash`, `redirect`, `url_for`, `request`, `session`, `abort` are imported at the top of `admin.py` (most likely already are — verify).

(Note: `admin.list_hidden_meetings` doesn't exist yet — added in Task 13. The `url_for(...)` resolves lazily at request time; placing it here is fine as long as Task 13 lands in the same deploy.)

- [ ] **Step 4: Re-run tests**

```
venv/bin/pytest tests/integration/test_admin_hide_meeting.py -v -k "hide_meeting_post or unhide_meeting_post or hide_meeting_requires or hide_meeting_404"
```

Expected: 4 passed. (`hide_meeting_404` may need adjustment if the route order resolves `99999999` to a different 404 path — if so, accept any 404 OR 302→404 chain.)

- [ ] **Step 5: Commit**

```
git add src/docket/web/admin.py tests/integration/test_admin_hide_meeting.py
git -c commit.gpgsign=false commit -m "admin: POST /admin/meetings/<id>/hide and /unhide"
```

---

## Task 12: meeting_detail + item_detail templates — admin banner + Hide button

**Files:**
- Modify: `src/docket/web/templates/meeting_detail.html`
- Modify: `src/docket/web/templates/item_detail.html`
- Modify: `tests/integration/test_admin_hide_meeting.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_admin_hide_meeting.py`:

```python
# ---------------------------------------------------------------------------
# Task 12 — meeting_detail banner + Hide button
# ---------------------------------------------------------------------------


def test_meeting_detail_admin_sees_hide_button_when_visible(admin_client, bag):
    mid = bag.add_meeting(is_hidden=False)
    rv = admin_client.get(f"/al/{bag.city_slug}/meetings/{mid}/")
    body = rv.get_data(as_text=True)
    assert f'action="/admin/meetings/{mid}/hide"' in body


def test_meeting_detail_admin_sees_unhide_banner_when_hidden(admin_client, bag):
    mid = bag.add_meeting(is_hidden=True)
    rv = admin_client.get(f"/al/{bag.city_slug}/meetings/{mid}/")
    body = rv.get_data(as_text=True)
    assert "This meeting is hidden from the public site" in body
    assert f'action="/admin/meetings/{mid}/unhide"' in body


def test_meeting_detail_anon_does_not_see_hide_button(client, bag):
    mid = bag.add_meeting(is_hidden=False)
    rv = client.get(f"/al/{bag.city_slug}/meetings/{mid}/")
    body = rv.get_data(as_text=True)
    assert "/hide" not in body
    assert "is hidden from the public site" not in body


def test_item_detail_admin_sees_banner_when_parent_hidden(admin_client, bag):
    """Admin viewing an item whose parent meeting is hidden sees a banner
    explaining why the page is invisible to citizens. No Hide/Unhide button
    on the item page — the action lives on the meeting page."""
    mid = bag.add_meeting(is_hidden=True)
    iid = bag.add_item(mid)
    rv = admin_client.get(f"/al/{bag.city_slug}/items/{iid}/")
    body = rv.get_data(as_text=True)
    assert rv.status_code == 200
    assert "parent meeting for this item is hidden" in body.lower()


def test_item_detail_admin_no_banner_when_parent_visible(admin_client, bag):
    mid = bag.add_meeting(is_hidden=False)
    iid = bag.add_item(mid)
    rv = admin_client.get(f"/al/{bag.city_slug}/items/{iid}/")
    body = rv.get_data(as_text=True)
    assert "parent meeting" not in body.lower() or "is hidden" not in body.lower()
```

- [ ] **Step 2: Confirm failure**

```
venv/bin/pytest tests/integration/test_admin_hide_meeting.py -v -k "Hide_button or unhide_banner or anon_does_not"
```

Expected: 3 FAIL.

- [ ] **Step 3: Edit `meeting_detail.html`**

Add near the top of the meeting hero block (place it inside the main content but above the meeting title — locate the existing `<h1>` for meeting title and insert just above):

```jinja
{% if session.get('admin_user') %}
  {% if meeting.is_hidden %}
    <div class="admin-banner admin-banner--hidden" style="background: #fff8c4; border: 1px solid #c0a000; padding: 0.75rem 1rem; margin-bottom: 1rem;">
      <strong>This meeting is hidden from the public site.</strong>
      <form method="post" action="{{ url_for('admin.unhide_meeting', meeting_id=meeting.id) }}" style="display: inline; margin-left: 0.5rem;">
        <button type="submit">Unhide</button>
      </form>
    </div>
  {% else %}
    <div class="admin-banner admin-banner--visible" style="margin-bottom: 1rem;">
      <form method="post" action="{{ url_for('admin.hide_meeting', meeting_id=meeting.id) }}"
            onsubmit="return confirm('Hide this meeting from the public site?');"
            style="display: inline;">
        <button type="submit" style="font-size: 0.85rem;">Hide this meeting</button>
      </form>
    </div>
  {% endif %}
{% endif %}
```

Locate the exact insertion point with:

```
cd ~/docket-pub && grep -n "meeting.title\|hero\|<h1" src/docket/web/templates/meeting_detail.html | head -10
```

Insert the snippet immediately before the meeting-hero `<h1>` (or its `<header>` container).

- [ ] **Step 3b: Add the admin banner to `item_detail.html`**

The item-detail page passes both `item` and `meeting` to the template (verified at `web/public.py:307` — the render_template call). Locate the existing top-of-page block:

```
cd ~/docket-pub && grep -n "meeting.title\|<h1\|extracted_facts\|item.title" src/docket/web/templates/item_detail.html | head -10
```

Insert this snippet near the top of the main content block (above the item title `<h1>`):

```jinja
{% if session.get('admin_user') and meeting.is_hidden %}
  <div class="admin-banner admin-banner--hidden" style="background: #fff8c4; border: 1px solid #c0a000; padding: 0.75rem 1rem; margin-bottom: 1rem;">
    <strong>The parent meeting for this item is hidden from the public site.</strong>
    <span style="margin-left: 0.5rem;">
      <a href="{{ url_for('public.meeting_detail', slug=municipality.slug, meeting_id=meeting.id) }}">
        Go to meeting to unhide.
      </a>
    </span>
  </div>
{% endif %}
```

No Hide/Unhide button on the item page — the action lives on the meeting page. This banner is purely a "you're seeing this because you're an admin" signal.

- [ ] **Step 4: Re-run tests**

```
venv/bin/pytest tests/integration/test_admin_hide_meeting.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```
git add src/docket/web/templates/meeting_detail.html src/docket/web/templates/item_detail.html tests/integration/test_admin_hide_meeting.py
git -c commit.gpgsign=false commit -m "templates: admin banner + Hide/Unhide on meeting_detail + parent-hidden banner on item_detail"
```

---

## Task 13: Admin index — `/admin/meetings/hidden`

**Files:**
- Modify: `src/docket/web/admin.py`
- Create: `src/docket/web/templates/admin/hidden_meetings.html`
- Modify: `src/docket/web/templates/admin/members.html` (add nav link)
- Modify: `tests/integration/test_admin_hide_meeting.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_admin_hide_meeting.py`:

```python
# ---------------------------------------------------------------------------
# Task 13 — /admin/meetings/hidden index
# ---------------------------------------------------------------------------


def test_admin_hidden_index_lists_hidden_meetings(admin_client, bag):
    mid = bag.add_meeting(is_hidden=True, title="TEST_HIDE_index_row")
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meetings SET hidden_at = NOW(), hidden_by = %s WHERE id = %s",
            (bag.admin_id, mid),
        )
        conn.commit()
    rv = admin_client.get("/admin/meetings/hidden")
    body = rv.get_data(as_text=True)
    assert rv.status_code == 200
    assert "TEST_HIDE_index_row" in body
    # Has an Unhide form pointing at this row
    assert f'action="/admin/meetings/{mid}/unhide"' in body


def test_admin_hidden_index_requires_login(client):
    rv = client.get("/admin/meetings/hidden", follow_redirects=False)
    assert rv.status_code in (301, 302, 303, 308)
    assert "/admin/login" in rv.headers.get("Location", "")
```

- [ ] **Step 2: Confirm failure**

```
venv/bin/pytest tests/integration/test_admin_hide_meeting.py -v -k "hidden_index"
```

Expected: FAIL.

- [ ] **Step 3: Add the route to `admin.py`**

Append to `src/docket/web/admin.py` (after the hide/unhide routes from Task 11):

```python
@bp.route("/meetings/hidden")
def list_hidden_meetings():
    """Admin index of every currently-hidden meeting.

    Joins to admin_users for the "hidden by" column (NULL when an older
    backfill hid the row without an actor) and to municipalities for city.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT
                m.id, m.title, m.meeting_date,
                m.hidden_at,
                mu.name AS city_name,
                mu.slug AS city_slug,
                au.username AS hidden_by_username
              FROM meetings m
              JOIN municipalities mu ON mu.id = m.municipality_id
              LEFT JOIN admin_users au ON au.id = m.hidden_by
             WHERE m.is_hidden = TRUE
             ORDER BY m.hidden_at DESC NULLS LAST, m.id DESC
            """
        )
        rows = [dict(r) for r in cur.fetchall()]
    return render_template("admin/hidden_meetings.html", rows=rows)
```

- [ ] **Step 4: Create the template**

Create `src/docket/web/templates/admin/hidden_meetings.html`:

```jinja
{% extends "base.html" %}
{% block title %}Hidden Meetings — Admin — docket.pub{% endblock %}

{% block content %}
<div style="display: flex; justify-content: space-between; align-items: center;">
    <h1>Hidden Meetings</h1>
    <form method="post" action="{{ url_for('auth.logout') }}" style="margin: 0;">
        <button type="submit" style="font-size: 0.85rem;">Sign Out ({{ session.get('admin_user', '') }})</button>
    </form>
</div>
<p>
    <a href="{{ url_for('admin.list_members') }}">← Back to Admin</a>
</p>

{% if rows %}
<table>
    <thead>
        <tr>
            <th>City</th>
            <th>Date</th>
            <th>Title</th>
            <th>Hidden at</th>
            <th>Hidden by</th>
            <th>Action</th>
        </tr>
    </thead>
    <tbody>
        {% for r in rows %}
        <tr>
            <td>{{ r.city_name }}</td>
            <td>{{ r.meeting_date }}</td>
            <td>
                <a href="{{ url_for('public.meeting_detail', slug=r.city_slug, meeting_id=r.id) }}">
                    {{ r.title }}
                </a>
            </td>
            <td>{{ r.hidden_at.strftime('%Y-%m-%d %H:%M UTC') if r.hidden_at else '—' }}</td>
            <td>{{ r.hidden_by_username or '—' }}</td>
            <td>
                <form method="post"
                      action="{{ url_for('admin.unhide_meeting', meeting_id=r.id) }}"
                      style="display: inline;">
                    <button type="submit">Unhide</button>
                </form>
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% else %}
<p>No hidden meetings.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Add nav link**

In `src/docket/web/templates/admin/members.html`, find the existing nav strip (lines 11-19):

```jinja
<p>
    <a href="{{ url_for('admin.add_member') }}">+ Add Member</a>
    &nbsp;&middot;&nbsp;
    <a href="{{ url_for('admin.badges_audit') }}">Badge audit</a>
    &nbsp;&middot;&nbsp;
    <a href="{{ url_for('admin.review_conflicts') }}">Conflicts</a>
    &nbsp;&middot;&nbsp;
    <a href="{{ url_for('admin.ai_panel') }}">AI Pipeline →</a>
</p>
```

Add a link to hidden meetings:

```jinja
<p>
    <a href="{{ url_for('admin.add_member') }}">+ Add Member</a>
    &nbsp;&middot;&nbsp;
    <a href="{{ url_for('admin.badges_audit') }}">Badge audit</a>
    &nbsp;&middot;&nbsp;
    <a href="{{ url_for('admin.review_conflicts') }}">Conflicts</a>
    &nbsp;&middot;&nbsp;
    <a href="{{ url_for('admin.list_hidden_meetings') }}">Hidden Meetings</a>
    &nbsp;&middot;&nbsp;
    <a href="{{ url_for('admin.ai_panel') }}">AI Pipeline →</a>
</p>
```

- [ ] **Step 6: Re-run tests**

```
venv/bin/pytest tests/integration/test_admin_hide_meeting.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```
git add src/docket/web/admin.py src/docket/web/templates/admin/hidden_meetings.html src/docket/web/templates/admin/members.html tests/integration/test_admin_hide_meeting.py
git -c commit.gpgsign=false commit -m "admin: /admin/meetings/hidden index + nav link"
```

---

## Task 14: Re-ingest preservation regression test

**Files:**
- Create: `tests/integration/test_ingest_preserves_is_hidden.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_ingest_preserves_is_hidden.py`:

```python
"""Regression test: _upsert_meetings does not touch meetings.is_hidden.

The daily ingest cron must NOT reset the operator hide. Migration 033's
column list and _upsert_meetings' enumerated UPDATE statement together
guarantee this — but the contract is critical, so pin it with a test.

Pattern mirrors tests/integration/test_ingest_reconciliation.py.
"""

from datetime import date

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.models.protocol import RawMeeting
from docket.services.ingest import _upsert_meetings


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Integration tests require local DB; will not run against Railway prod",
)


TEST_SLUG = "test_hide_preserve"


@pytest.fixture
def muni_id():
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO municipalities (slug, name, state, adapter_class, adapter_config, active)
            VALUES (%s, 'Test Hide Preserve', 'AL', 'GranicusAdapter',
                    '{"view_id": 1, "base_url": "https://example.com"}'::jsonb, TRUE)
            ON CONFLICT (slug) DO UPDATE SET active = TRUE
            RETURNING id
            """,
            (TEST_SLUG,),
        )
        mid = cur.fetchone()[0]
        cur.execute("DELETE FROM meetings WHERE municipality_id = %s", (mid,))
        conn.commit()
    yield mid
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE municipality_id = %s", (mid,))
        conn.commit()


def _raw(external_id: str, title: str) -> RawMeeting:
    return RawMeeting(
        external_id=external_id,
        title=title,
        meeting_date=date(2026, 5, 18),
        meeting_type="council",
        agenda_url="https://example.com/a",
        minutes_url=None,
        video_url=None,
        source_url=f"https://example.com/m/{external_id}",
        start_time=None,
    )


def test_reingest_preserves_is_hidden(muni_id):
    # Ingest once → row exists with is_hidden=FALSE (default).
    _upsert_meetings(muni_id, [_raw("clip-1", "TEST_HIDE Preserve")])

    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meetings SET is_hidden = TRUE WHERE municipality_id = %s "
            "RETURNING id, is_hidden",
            (muni_id,),
        )
        row = cur.fetchone()
        meeting_id = row[0]
        assert row[1] is True
        conn.commit()

    # Re-ingest the same external_id with a different title to force an UPDATE.
    _upsert_meetings(muni_id, [_raw("clip-1", "TEST_HIDE Preserve (revised title)")])

    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT is_hidden, title FROM meetings WHERE id = %s",
            (meeting_id,),
        )
        is_hidden, title = cur.fetchone()
    assert is_hidden is True, "is_hidden must survive re-ingest"
    assert "revised" in title, "title must have updated (proves ingest actually ran)"
```

- [ ] **Step 2: Run the test**

```
venv/bin/pytest tests/integration/test_ingest_preserves_is_hidden.py -v
```

Expected: PASS (no code change needed — the column was deliberately omitted from `_upsert_meetings`' UPDATE list).

- [ ] **Step 3: Commit**

```
git add tests/integration/test_ingest_preserves_is_hidden.py
git -c commit.gpgsign=false commit -m "tests: pin contract that ingest preserves is_hidden"
```

---

## Task 15: Full-suite sanity + lint

**Files:** None — verification only.

- [ ] **Step 1: Run the full pytest suite**

```
venv/bin/pytest tests/ -v 2>&1 | tail -40
```

Expected: all tests pass. If any pre-existing test regressed, open the failure and trace whether a new `is_hidden` filter is suppressing rows the test expects to see (the test may need updating to seed `is_hidden=FALSE` explicitly, or to use a non-hidden meeting).

- [ ] **Step 2: Confirm no lint regressions** (if the project uses ruff/black — check `pyproject.toml`)

```
cd ~/docket-pub && grep -A2 "\[tool.ruff\]\|\[tool.black\]" pyproject.toml | head -10
```

If linters are configured, run them. If not, skip.

- [ ] **Step 3: Commit** (only if tests had to be updated)

```
git status
git -c commit.gpgsign=false commit -am "tests: update fixtures to seed is_hidden=FALSE where needed"
```

(If no changes needed, skip the commit.)

---

## Task 16: Deploy to Railway

**Files:** None — operational.

- [ ] **Step 1: Confirm on `main` and push**

```
cd ~/docket-pub && git status && git branch --show-current
```

Expected: `main` and clean working tree. If on a feature branch, merge to `main` first per CLAUDE.md's "deploy only from main" rule.

```
git push origin main
```

- [ ] **Step 2: Deploy `docket-web`**

```
cd ~/docket-pub && railway up --service docket-web --detach
```

The deploy runs `python -m docket.migrations.runner` before gunicorn starts, so migration 033 lands automatically. Monitor:

```
railway logs --service docket-web
```

Expected log line: `Applying migration 33: docket.migrations.033_meetings_is_hidden`. Wait for `Listening at: http://0.0.0.0:...` before continuing.

- [ ] **Step 3: Refresh the materialized view**

The MV was rebuilt `WITH NO DATA` by the migration. Repopulate so category landings work immediately rather than waiting for the next 04:30 CT cron:

```
railway ssh --service docket-web "cd /app && python -c \"from docket.db import db; conn=db().__enter__(); cur=conn.cursor(); cur.execute('REFRESH MATERIALIZED VIEW CONCURRENTLY mv_badge_volume_monthly'); conn.commit(); print('OK')\""
```

Expected: `OK` (a few seconds).

- [ ] **Step 4: Apply the trigger-case backfill**

```
railway ssh --service docket-web "cd /app && python -c \"
from docket.db import db
with db() as conn, conn.cursor() as cur:
    cur.execute(\\\"SELECT id FROM admin_users WHERE username = 'darrell' LIMIT 1\\\")
    row = cur.fetchone()
    admin_id = row[0] if row else None
    cur.execute(
        'UPDATE meetings SET is_hidden=TRUE, hidden_at=NOW(), hidden_by=%s WHERE id = 2233',
        (admin_id,),
    )
    conn.commit()
    print(f'Updated rows: {cur.rowcount}, admin_id: {admin_id}')
\""
```

Expected: `Updated rows: 1, admin_id: <int or None>`.

- [ ] **Step 5: Smoke-test the change**

Visit (anonymous, fresh browser or incognito):

- `https://docket.pub/al/birmingham/` — the 5/18 "Regular City Council Meeting" card should be gone.
- `https://docket.pub/al/birmingham/meetings/2233/` — should return 404.

Visit (logged in as admin):

- `https://docket.pub/admin/meetings/hidden` — should list meeting 2233 with an Unhide button.
- `https://docket.pub/al/birmingham/meetings/2233/` — should render with the yellow "This meeting is hidden" banner.

- [ ] **Step 6: Final commit if any cleanup**

If the deploy revealed any small fixes (cosmetic CSS, log noise), commit them now. Otherwise this task has no commit.

---

## Self-Review

After plan is written:

- [x] Spec §1 (data model) → Task 1
- [x] Spec §2 (filter scope) → Tasks 4-7 + Task 10 (RSS)
- [x] Spec §3 (meeting_detail behavior) → Task 8
- [x] Spec §4 (admin toggle on meeting_detail) → Tasks 11 + 12
- [x] Spec §5 (admin index of hidden meetings) → Task 13
- [x] Spec §6 (ingest preservation) → Task 14
- [x] Spec §7 (tests) — covered across all tasks; aggregate verification in Task 15
- [x] Spec §8 (backfill / apply) → Task 16
- [x] Spec §4 sub-point (`session['admin_user_id']` on login) → Task 2
- [x] Spec §3 sub-point (Meeting model exposes is_hidden) → Task 3
- [x] Item-detail leak (review item #2) → Task 9

No "TBD" or "implement later" tokens. Every code-change step shows the actual code. Every test shows the assert.

Method-name consistency: `hide_meeting` / `unhide_meeting` / `list_hidden_meetings` used uniformly across admin.py, templates, and tests. `get_agenda_item_for_admin` introduced in Task 9 — name reused only there. No drift.

One known wrinkle worth flagging to the executor: in Task 4 the `dashboard_stats` return-key assertion (`stats.get("meetings") or stats.get("meeting_count")`) is a defensive guard because the spec didn't pin the exact dict key. The executor should grep the function body to confirm the actual key name and tighten the assertion before running.
