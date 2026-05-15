# Visual Refactor — Phase 3 (City Overview Rebuild) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Each task is dispatched to a **fresh sonnet implementer subagent**, then reviewed by a **fresh sonnet spec reviewer**, then by a **fresh sonnet code-quality reviewer**, before marking the task complete. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Model floor: sonnet.** Per memory `feedback_haiku_verification_hallucination.md`.
>
> **🛑 HUMAN VISUAL REVIEW GATES** apply to Tasks 5, 6, 9, 13 (the user-facing changes). Final visual sweep is Task 13.

**Goal:** Rebuild the city overview's top of page (CityLead + 3-card YTD strip), split the KPI explainer stack off overview onto interior pages, slim footer.html colophon, and migrate `.hero-title` to the `--type-hero` token. Backed by a new `municipalities.metadata` JSONB column.

**Architecture:** Single PR. New migration (029) + 5 query helpers + 2 new partials (`city_lead`, `kpi_strip`) + 1 city.html top-section rewrite + 6 interior view function updates + footer.html slim + 1 token-migration line in layout.css + mobile reflow CSS. Cache reuses existing `_overview_cache`; interior pages currently have no cache and add 4 KPI queries — verified <50ms each via EXPLAIN before merge.

**Tech Stack:** Python 3.10+ / Flask / Jinja2 / PostgreSQL 18 (Railway) / pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-15-visual-refactor-phase-3-design.md`
**Predecessor:** P2b shipped 2026-05-15 (PR #54 / squash `d6dab01`); P3 plan commit (when this lands) will be on top of `9e92b86` (P3 spec commit).

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/docket/migrations/029_municipalities_metadata.py` | Create | Add `metadata JSONB NOT NULL DEFAULT '{}'` to `municipalities`; seed 6 cities. |
| `src/docket/migrations/runner.py` | Modify | Register migration 029 in the `MIGRATIONS` list. |
| `src/docket/services/query.py` | Modify | +3 YTD helpers, +2 freshness helpers, +1 kpi-stats consolidator. |
| `src/docket/web/public.py` | Modify | Update `city_overview` (drop kpi_stats, add city_stats + freshness); add kpi_stats to 6 interior view functions. |
| `src/docket/web/templates/city.html` | Modify | Rewrite top section; delete hero narrative + 4-card KPI grid + 2 standalone KPIs + badge legend; insert `city_lead` + `kpi_strip` partials. |
| `src/docket/web/templates/partials/city_lead.html` | Create | New partial: eyebrow + h1 + freshness chip. |
| `src/docket/web/templates/partials/kpi_strip.html` | Create | New partial: 3-card horizontal strip wrapping 3 `num_stat` partials. |
| `src/docket/web/templates/partials/footer.html` | Modify | Remove Adapter tile from colophon (keep Schema + Source + Updated). |
| `src/docket/web/static/styles.css` | Modify | Migrate `.hero-title` to `font-size: var(--type-hero)`. |
| `src/docket/web/static/layout.css` | Modify | New `.city-lead*` rules; new `.kpi-strip` rules. |
| `src/docket/web/static/mobile.css` | Modify | Mobile reflow for `.city-lead*` + `.kpi-strip`. |
| `tests/web/test_partials_visual_refactor.py` | Modify | Snapshot tests for city_lead + kpi_strip. |
| `tests/web/test_city_overview_render.py` | Create | Render tests for the new top section + KPI section split. |
| `tests/integration/test_029_migration.py` | Create | Apply + rollback + seed-data test for migration 029. |
| `tests/services/test_query_kpi_helpers.py` | Create | Unit tests for the 6 new query helpers. |

---

## Task 1: Worktree setup + own venv + baseline pytest

**Files:** none (environment).

### Step 1: Controller creates worktree

- [ ] From canonical (`/Users/darrellnance/docket-pub`, on `main`):
```bash
git checkout main && git pull --ff-only origin main
```
- [ ] Use `EnterWorktree` with `name: "worktree-visual-refactor-p3"`.

### Step 2: Implementer sets up worktree's own venv

- [ ] Inside the worktree (NOT a symlink — per memory `feedback_haiku_verification_hallucination.md`):
```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/worktree-worktree-visual-refactor-p3
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
pip install -r <(/Users/darrellnance/docket-pub/venv/bin/pip freeze | grep -v "^-e git")
ln -s /Users/darrellnance/docket-pub/.env .env
```

### Step 3: Baseline pytest

- [ ] Run:
```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/worktree-worktree-visual-refactor-p3
venv/bin/pytest --ignore=tests/live -q 2>&1 | tail -3
```
Expected: `1595 passed` (or higher if commits landed on main since this plan was written).

### Step 4: Confirm Flask boots + Railway DB reachable

- [ ] Run:
```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/worktree-worktree-visual-refactor-p3
DBURL=$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)
DATABASE_URL="$DBURL" PORT=5001 venv/bin/flask --app docket.web run --port 5001 &
sleep 3
curl -sf -o /dev/null -w "%{http_code}\n" http://localhost:5001/al/birmingham/
kill %1 2>/dev/null
```
Expected: `200`.

### Step 5: No commit (env setup only)

Task 1 has no code change. Report baseline pytest count and Flask status.

---

## Task 2: Migration 029 — `municipalities.metadata` JSONB column + seed

**Files:**
- Create: `src/docket/migrations/029_municipalities_metadata.py`
- Modify: `src/docket/migrations/runner.py` (register 029)
- Create: `tests/integration/test_029_migration.py`

### Step 1: Write failing test

- [ ] Create `tests/integration/test_029_migration.py`:

```python
"""Apply + rollback + seed verification for migration 029
(municipalities.metadata JSONB column)."""
import pytest
from docket.db import db_cursor


@pytest.fixture
def migration_module():
    from docket.migrations import _029_municipalities_metadata as m
    return m


def test_029_apply_adds_metadata_column(migration_module):
    """After apply, municipalities table has a metadata JSONB column."""
    # Confirm the column exists after migration has been applied (the test
    # DB is set up with all migrations applied by conftest fixtures).
    with db_cursor() as cur:
        cur.execute("""
            SELECT data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'municipalities' AND column_name = 'metadata'
        """)
        row = cur.fetchone()
    assert row is not None, "metadata column missing"
    assert row["data_type"] == "jsonb"
    assert row["is_nullable"] == "NO"
    assert "{}" in row["column_default"]


def test_029_seed_birmingham_metadata():
    """Birmingham should have council_type / county / population seeded."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT metadata FROM municipalities WHERE slug = 'birmingham'
        """)
        row = cur.fetchone()
    assert row is not None
    md = row["metadata"]
    assert md.get("council_type") == "Mayor-council"
    assert md.get("county") == "Jefferson County"
    assert md.get("population") == 196910
    assert md.get("population_year") == 2020


def test_029_seed_all_six_cities():
    """All 6 existing cities should have non-empty metadata seeded."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT slug, metadata FROM municipalities
            WHERE slug IN ('birmingham', 'mobile', 'montgomery',
                           'hoover', 'homewood', 'vestavia-hills')
            ORDER BY slug
        """)
        rows = cur.fetchall()
    assert len(rows) == 6, f"expected 6 cities, got {len(rows)}"
    for r in rows:
        md = r["metadata"]
        assert "council_type" in md, f"{r['slug']} missing council_type"
        assert "county" in md, f"{r['slug']} missing county"
        assert "population" in md, f"{r['slug']} missing population"


def test_029_rollback_drops_metadata_column(migration_module):
    """SQL_DOWN should drop the metadata column."""
    # Inspect the SQL_DOWN string for the DROP statement (don't actually
    # run rollback during the test — that would break later test runs).
    sql_down = migration_module.SQL_DOWN
    assert "DROP COLUMN" in sql_down.upper()
    assert "metadata" in sql_down.lower()
```

### Step 2: Run; verify import-error fail

- [ ] Run:
```bash
venv/bin/pytest tests/integration/test_029_migration.py -v 2>&1 | tail -15
```
Expected: errors importing `docket.migrations._029_municipalities_metadata` (file doesn't exist yet).

### Step 3: Create the migration file

- [ ] Create `src/docket/migrations/029_municipalities_metadata.py`:

```python
"""Migration 029 — add metadata JSONB column to municipalities + seed 6 cities.

Powers the new CityLead eyebrow (council type · county · population).
Future cities INSERT with their metadata payload at onboarding — no
schema or code change needed per city.

Population figures are 2020 US Census estimates.
"""
from __future__ import annotations


SQL_UP = r"""
ALTER TABLE municipalities
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE municipalities SET metadata = '{
  "council_type": "Mayor-council",
  "county": "Jefferson County",
  "population": 196910,
  "population_year": 2020
}'::jsonb WHERE slug = 'birmingham';

UPDATE municipalities SET metadata = '{
  "council_type": "Mayor-council",
  "county": "Mobile County",
  "population": 187041,
  "population_year": 2020
}'::jsonb WHERE slug = 'mobile';

UPDATE municipalities SET metadata = '{
  "council_type": "Mayor-council",
  "county": "Montgomery County",
  "population": 200603,
  "population_year": 2020
}'::jsonb WHERE slug = 'montgomery';

UPDATE municipalities SET metadata = '{
  "council_type": "Mayor-council",
  "county": "Jefferson County",
  "population": 92606,
  "population_year": 2020
}'::jsonb WHERE slug = 'hoover';

UPDATE municipalities SET metadata = '{
  "council_type": "Mayor-council",
  "county": "Jefferson County",
  "population": 26414,
  "population_year": 2020
}'::jsonb WHERE slug = 'homewood';

UPDATE municipalities SET metadata = '{
  "council_type": "Mayor-council",
  "county": "Jefferson County",
  "population": 39102,
  "population_year": 2020
}'::jsonb WHERE slug = 'vestavia-hills';
"""

SQL_DOWN = r"""
ALTER TABLE municipalities DROP COLUMN IF EXISTS metadata;
"""
```

Note: file is named `029_municipalities_metadata.py` (with underscore prefix `_029_` accessor via the leading-digit `from foo.bar import _029_*` form — that's how the test imports it; matches the existing pattern in the codebase where migration filenames start with digits).

### Step 4: Register in runner.py

- [ ] Modify `src/docket/migrations/runner.py` MIGRATIONS list. Add at the end (after line 40):

```python
    "docket.migrations.028_coverage_links_unique_nulls",
    "docket.migrations.029_municipalities_metadata",
]
```

### Step 5: Apply migration locally

- [ ] Run:
```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/worktree-worktree-visual-refactor-p3
venv/bin/python -m docket.migrations.runner 2>&1 | tail -10
```
Expected output includes: `Applying docket.migrations.029_municipalities_metadata`.

- [ ] Verify the column + seed via psql:
```bash
psql "$(grep DATABASE_URL .env | cut -d= -f2-)" -c "SELECT slug, metadata FROM municipalities ORDER BY slug;"
```
Expected: 6 rows with `metadata` containing council_type/county/population.

### Step 6: Run the migration tests

- [ ] Run:
```bash
venv/bin/pytest tests/integration/test_029_migration.py -v 2>&1 | tail -10
```
Expected: 4 PASS.

### Step 7: Full pytest

- [ ] Run:
```bash
venv/bin/pytest --ignore=tests/live -q 2>&1 | tail -3
```
Expected: 1599 passed (1595 + 4 new).

### Step 8: Commit

```bash
git add src/docket/migrations/029_municipalities_metadata.py \
        src/docket/migrations/runner.py \
        tests/integration/test_029_migration.py
git commit -m "feat(migrations): 029 — municipalities.metadata JSONB + seed 6 cities

Powers CityLead eyebrow (council type · county · population). Future
cities populate via INSERT with metadata payload — no schema change
per city. Population figures are 2020 US Census estimates."
```

---

## Task 3: YTD + freshness query helpers in `query.py`

**Files:**
- Modify: `src/docket/services/query.py`
- Create: `tests/services/test_query_kpi_helpers.py`

### Step 1: Write failing tests

- [ ] Create `tests/services/test_query_kpi_helpers.py`:

```python
"""Unit tests for P3 KPI + freshness query helpers."""
from datetime import datetime, timedelta, timezone

import pytest

from docket.services import query


BHM_ID = 1  # Birmingham — first municipality, stable across test DB.


def test_count_meetings_ytd_returns_int():
    n = query.count_meetings_ytd(BHM_ID)
    assert isinstance(n, int)
    assert n >= 0


def test_count_meetings_ytd_scoped_to_year():
    """Should only count meetings with date >= jan 1 of current year."""
    n = query.count_meetings_ytd(BHM_ID)
    # cross-check by raw SQL
    from docket.db import db_cursor
    with db_cursor() as cur:
        cur.execute("""
            SELECT count(*) AS n FROM meetings
            WHERE municipality_id = %s
              AND meeting_date >= date_trunc('year', now())::date
        """, (BHM_ID,))
        expected = cur.fetchone()["n"]
    assert n == expected


def test_sum_dollars_ytd_returns_decimal():
    from decimal import Decimal
    total = query.sum_dollars_ytd(BHM_ID)
    assert isinstance(total, Decimal)
    assert total >= 0


def test_count_contested_votes_ytd_returns_int():
    n = query.count_contested_votes_ytd(BHM_ID)
    assert isinstance(n, int)
    assert n >= 0


def test_most_recent_ingest_at_returns_datetime_or_none():
    ts = query.most_recent_ingest_at(BHM_ID)
    # Birmingham has meetings, so should be a datetime
    assert ts is not None
    assert isinstance(ts, datetime)


def test_most_recent_ingest_at_none_for_nonexistent_city():
    """City with no meetings returns None."""
    # Use a high ID unlikely to match
    ts = query.most_recent_ingest_at(999999)
    assert ts is None


def test_freshness_state_good():
    now = datetime.now(timezone.utc)
    state = query._freshness_state(now - timedelta(hours=4))
    assert state["state"] == "good"
    assert "Live" in state["label"] or "Fresh" in state["label"]


def test_freshness_state_warn():
    now = datetime.now(timezone.utc)
    state = query._freshness_state(now - timedelta(days=2))
    assert state["state"] == "warn"


def test_freshness_state_bad():
    now = datetime.now(timezone.utc)
    state = query._freshness_state(now - timedelta(days=10))
    assert state["state"] == "bad"


def test_freshness_state_unknown_for_none():
    state = query._freshness_state(None)
    assert state["state"] == "unknown"


def test_kpi_stats_for_municipality_returns_four_dicts():
    municipality = query.get_municipality("birmingham")
    stats = query._kpi_stats_for_municipality(municipality)
    assert isinstance(stats, list)
    assert len(stats) == 4
    for stat in stats:
        assert "label" in stat
        assert "value" in stat
        assert "sql_display" in stat
        # `sub` is optional but key may be present (None allowed)


def test_kpi_stats_first_card_is_meetings_lifetime():
    municipality = query.get_municipality("birmingham")
    stats = query._kpi_stats_for_municipality(municipality)
    assert "Meetings" in stats[0]["label"]
    assert "lifetime" in stats[0]["label"].lower()
```

### Step 2: Run; verify failure

- [ ] Run:
```bash
venv/bin/pytest tests/services/test_query_kpi_helpers.py -v 2>&1 | tail -20
```
Expected: 11 FAIL with `AttributeError: module 'docket.services.query' has no attribute 'count_meetings_ytd'` etc.

### Step 3: Add the YTD helpers + freshness helpers to `query.py`

- [ ] In `src/docket/services/query.py`, append after the existing `dollars_pending_vs_settled` helper (which P2b added):

```python
def count_meetings_ytd(municipality_id: int) -> int:
    """Count meetings with meeting_date in the current calendar year."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT count(*) AS n FROM meetings
            WHERE municipality_id = %s
              AND meeting_date >= date_trunc('year', now())::date
            """,
            (municipality_id,),
        )
        row = cur.fetchone()
        return int(row["n"] or 0)


def sum_dollars_ytd(municipality_id: int):
    """Sum of agenda_items.dollars_amount in this city's meetings YTD.

    Returns a Decimal (may be 0 if no items / no dollar amounts)."""
    from decimal import Decimal
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT coalesce(sum(ai.dollars_amount), 0) AS total
            FROM agenda_items ai
            JOIN meetings m ON m.id = ai.meeting_id
            WHERE m.municipality_id = %s
              AND m.meeting_date >= date_trunc('year', now())::date
            """,
            (municipality_id,),
        )
        row = cur.fetchone()
        return Decimal(row["total"] or 0)


def count_contested_votes_ytd(municipality_id: int) -> int:
    """Count votes recorded YTD where members split (>=1 dissent).

    A 'contested' vote is one where at least one member_vote.vote = 'no'
    or 'abstain'. Pure unanimous votes don't count."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT count(DISTINCT v.id) AS n
            FROM votes v
            JOIN meetings m ON m.id = v.meeting_id
            JOIN member_votes mv ON mv.vote_id = v.id
            WHERE m.municipality_id = %s
              AND m.meeting_date >= date_trunc('year', now())::date
              AND mv.vote IN ('no', 'abstain')
            """,
            (municipality_id,),
        )
        row = cur.fetchone()
        return int(row["n"] or 0)


def most_recent_ingest_at(municipality_id: int):
    """Returns datetime of the most recently created meeting for this city,
    or None if no meetings exist. Powers the freshness chip."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT MAX(created_at) AS most_recent FROM meetings
            WHERE municipality_id = %s
            """,
            (municipality_id,),
        )
        row = cur.fetchone()
        return row["most_recent"] if row and row["most_recent"] else None


def _freshness_state(last_ingest):
    """Maps a most-recent-ingest timestamp to a freshness state dict.

    Thresholds: good < 24h, warn < 7d, bad >= 7d.
    None input (no meetings) → unknown state.

    Returns: {'state': str, 'label': str, 'last_synced': datetime | None}
    """
    from datetime import datetime, timedelta, timezone

    if last_ingest is None:
        return {"state": "unknown", "label": "No data yet", "last_synced": None}

    now = datetime.now(timezone.utc)
    # Make last_ingest tz-aware if not already
    if last_ingest.tzinfo is None:
        last_ingest = last_ingest.replace(tzinfo=timezone.utc)
    age = now - last_ingest

    if age < timedelta(hours=24):
        return {"state": "good", "label": "Live", "last_synced": last_ingest}
    if age < timedelta(days=7):
        return {"state": "warn", "label": "Recent", "last_synced": last_ingest}
    return {"state": "bad", "label": "Stale", "last_synced": last_ingest}


def _kpi_stats_for_municipality(municipality: dict) -> list[dict]:
    """Builds the 4-card KPI explainer stack for page_sources.html.

    Reuses the P2b helpers (count_meetings_lifetime, count_agenda_items_ytd,
    count_votes_ytd, dollars_pending_vs_settled, min_meeting_year)."""
    mid = municipality["id"]
    min_year = min_meeting_year(mid)
    dollars = dollars_pending_vs_settled(mid)
    return [
        {
            "label": "Meetings (lifetime)",
            "value": f"{count_meetings_lifetime(mid):,}",
            "sub": f"Since {min_year}" if min_year else None,
            "sql_display": (
                f"SELECT count(*) FROM meetings WHERE municipality_id = {mid}"
            ),
        },
        {
            "label": "Agenda items YTD",
            "value": f"{count_agenda_items_ytd(mid):,}",
            "sub": None,
            "sql_display": (
                f"SELECT count(*) FROM agenda_items ai\n"
                f"JOIN meetings m ON m.id = ai.meeting_id\n"
                f"WHERE m.municipality_id = {mid}\n"
                f"AND m.meeting_date >= date_trunc('year', now())"
            ),
        },
        {
            "label": "Votes YTD",
            "value": f"{count_votes_ytd(mid):,}",
            "sub": None,
            "sql_display": (
                f"SELECT count(*) FROM votes v\n"
                f"JOIN meetings m ON m.id = v.meeting_id\n"
                f"WHERE m.municipality_id = {mid}\n"
                f"AND m.meeting_date >= date_trunc('year', now())"
            ),
        },
        {
            "label": "Dollars (pending / settled)",
            "value": (
                f"${(dollars['pending']/1_000_000):.1f}M / "
                f"${(dollars['settled']/1_000_000):.1f}M"
            ),
            "sub": None,
            "sql_display": (
                f"SELECT sum(dollars_amount) FILTER (WHERE minutes_adopted_at IS NULL),\n"
                f"       sum(dollars_amount) FILTER (WHERE minutes_adopted_at IS NOT NULL)\n"
                f"FROM agenda_items ai\n"
                f"JOIN meetings m ON m.id = ai.meeting_id\n"
                f"WHERE m.municipality_id = {mid}"
            ),
        },
    ]
```

### Step 4: Run helper tests; verify pass

- [ ] Run:
```bash
venv/bin/pytest tests/services/test_query_kpi_helpers.py -v 2>&1 | tail -15
```
Expected: 11 PASS.

### Step 5: Full pytest

- [ ] Run:
```bash
venv/bin/pytest --ignore=tests/live -q 2>&1 | tail -3
```
Expected: 1610 passed (1599 + 11).

### Step 6: Commit

```bash
git add src/docket/services/query.py tests/services/test_query_kpi_helpers.py
git commit -m "feat(query): YTD + freshness + kpi_stats helpers for P3 city overview

- count_meetings_ytd / sum_dollars_ytd / count_contested_votes_ytd
  power the new 3-card YTD strip at the top of city overview.
- most_recent_ingest_at + _freshness_state power the freshness chip
  in CityLead (no last_sync_at column exists; MAX(meetings.created_at)
  is the proxy).
- _kpi_stats_for_municipality consolidates the 4 P2b helpers into a
  single call for interior view functions to pass into page_sources."
```

---

## Task 4: New partial `partials/city_lead.html` + CSS

**Files:**
- Create: `src/docket/web/templates/partials/city_lead.html`
- Modify: `src/docket/web/static/layout.css` (new `.city-lead*` rules)
- Modify: `tests/web/test_partials_visual_refactor.py` (snapshot tests)

### Step 1: Write failing tests

- [ ] Append to `tests/web/test_partials_visual_refactor.py`:

```python
def test_city_lead_renders_full_metadata(render_partial):
    """CityLead with all 3 metadata fields renders eyebrow + h1 + chip."""
    municipality = {
        "id": 1, "slug": "birmingham", "name": "Birmingham", "state": "AL",
        "adapter_class": "GranicusAdapter",
        "metadata": {
            "council_type": "Mayor-council",
            "county": "Jefferson County",
            "population": 196910,
            "population_year": 2020,
        },
    }
    freshness = {"state": "good", "label": "Live", "last_synced": None}
    html = render_partial("city_lead", municipality=municipality, freshness=freshness)
    assert 'class="city-lead' in html
    assert "Mayor-council" in html
    assert "Jefferson County" in html
    assert "196,910" in html  # comma-formatted
    assert "Birmingham, AL" in html
    assert 'class="city-lead-chip' in html or 'freshness-chip' in html


def test_city_lead_eyebrow_collapses_when_metadata_empty(render_partial):
    """No metadata → eyebrow row renders nothing visible."""
    municipality = {
        "id": 99, "slug": "newcity", "name": "New City", "state": "AL",
        "adapter_class": "GranicusAdapter",
        "metadata": {},
    }
    freshness = {"state": "unknown", "label": "No data yet", "last_synced": None}
    html = render_partial("city_lead", municipality=municipality, freshness=freshness)
    assert "New City, AL" in html  # h1 still renders
    # Eyebrow content absent
    assert "Council-manager" not in html
    assert "Mayor-council" not in html
    # No empty wrapper artifacts
    assert "city-lead-eyebrow" in html  # class may still be in HTML
    # but no actual content fields rendered
    assert "·" not in html.split("city-lead-eyebrow")[1].split("</div>")[0]


def test_city_lead_partial_metadata_renders_partial_eyebrow(render_partial):
    """Some metadata present → renders what's available, joined by ·."""
    municipality = {
        "id": 99, "slug": "partial", "name": "Partial City", "state": "AL",
        "adapter_class": "GranicusAdapter",
        "metadata": {"county": "Some County"},
    }
    freshness = {"state": "good", "label": "Live", "last_synced": None}
    html = render_partial("city_lead", municipality=municipality, freshness=freshness)
    assert "Some County" in html
    # Population missing — not rendered
    assert "pop." not in html


def test_city_lead_freshness_chip_renders_state_dot(render_partial):
    """Freshness chip's state attribute reflects the freshness state."""
    municipality = {
        "id": 1, "slug": "birmingham", "name": "Birmingham", "state": "AL",
        "adapter_class": "GranicusAdapter", "metadata": {},
    }
    for state in ("good", "warn", "bad", "unknown"):
        freshness = {"state": state, "label": state.title(), "last_synced": None}
        html = render_partial("city_lead", municipality=municipality, freshness=freshness)
        assert f"is-{state}" in html or f'data-state="{state}"' in html, (
            f"freshness chip missing state hook for {state}"
        )
```

### Step 2: Run; verify failure

- [ ] Run:
```bash
venv/bin/pytest tests/web/test_partials_visual_refactor.py -k "city_lead" -v 2>&1 | tail -10
```
Expected: 4 FAIL (`TemplateNotFound: partials/city_lead.html`).

### Step 3: Create the partial

- [ ] Create `src/docket/web/templates/partials/city_lead.html`:

```jinja
{# CityLead — eyebrow (council type · county · population) + h1 (city, state)
   + freshness chip. P3 top-of-overview block. Renders gracefully when
   municipality.metadata is partially or fully empty (newly-onboarded
   cities will lack fields until populated).

   Args:
     municipality (dict) — required. Must include name, state, slug,
                          adapter_class. metadata may be empty.
     freshness (dict, optional) — {state, label, last_synced}. Defaults
                                  to neutral "unknown" if absent.

   The freshness chip is STATIC in P3 (no link, no click). P4 wires
   the source-health route and makes it clickable.
#}
{%- set md = municipality.get('metadata', {}) if municipality is mapping else (municipality.metadata if municipality.metadata is defined else {}) -%}
{%- set parts = [] -%}
{%- if md.get('council_type') -%}{%- set _ = parts.append(md.get('council_type')) -%}{%- endif -%}
{%- if md.get('county') -%}{%- set _ = parts.append(md.get('county')) -%}{%- endif -%}
{%- if md.get('population') -%}{%- set _ = parts.append("{:,} pop.".format(md.get('population'))) -%}{%- endif -%}

<section class="city-lead">
  <div class="city-lead-eyebrow t-mono">
    {%- if parts %}{{ parts | join(' · ') }}{% endif -%}
  </div>
  <div class="city-lead-row">
    <h1 class="city-lead-h1">{{ municipality.name }}, {{ municipality.state }}</h1>
    <div class="city-lead-chip is-{{ (freshness or {}).get('state', 'unknown') }}"
         data-state="{{ (freshness or {}).get('state', 'unknown') }}"
         aria-label="Data freshness: {{ (freshness or {}).get('label', 'Unknown') }}">
      <span class="city-lead-chip-dot" aria-hidden="true"></span>
      <span class="city-lead-chip-label">{{ (freshness or {}).get('label', 'Unknown') }}</span>
      {% if (freshness or {}).get('last_synced') %}
        <span class="city-lead-chip-meta t-mono">
          synced {{ (freshness or {}).get('last_synced').strftime('%b %d') }}
        </span>
      {% endif %}
    </div>
  </div>
</section>
```

### Step 4: Add CSS for `.city-lead*` to `layout.css`

- [ ] Append to `src/docket/web/static/layout.css`:

```css
/* ── CityLead (P3) ─────────────────────────────────────────── */
.city-lead { padding: var(--space-8) 0 var(--space-4); }
.city-lead-eyebrow {
  font-size: var(--type-eyebrow);
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--ink-3);
  min-height: 1.2em;  /* prevents collapse jump when empty */
  margin-bottom: var(--space-3);
}
.city-lead-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: var(--space-4);
  flex-wrap: wrap;
}
.city-lead-h1 {
  font-family: var(--font-display);
  font-size: var(--type-hero);
  font-weight: 500;
  letter-spacing: -0.02em;
  line-height: 1.05;
  margin: 0;
  color: var(--ink);
}
.city-lead-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--rule);
  border-radius: 999px;
  background: var(--paper);
  font-size: 13px;
  color: var(--ink);
  white-space: nowrap;
}
.city-lead-chip-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--ink-3);  /* default = unknown */
}
.city-lead-chip.is-good .city-lead-chip-dot {
  background: var(--good, #5a8a4e);
  box-shadow: 0 0 0 3px color-mix(in oklab, var(--good, #5a8a4e) 24%, transparent);
}
.city-lead-chip.is-warn .city-lead-chip-dot { background: var(--warn, #b8860b); }
.city-lead-chip.is-bad .city-lead-chip-dot { background: var(--bad, #b03a3a); }
.city-lead-chip-label { font-weight: 500; }
.city-lead-chip-meta { color: var(--ink-3); font-size: 11px; }
```

### Step 5: Run tests

- [ ] Run:
```bash
venv/bin/pytest tests/web/test_partials_visual_refactor.py -k "city_lead" -v 2>&1 | tail -10
```
Expected: 4 PASS.

### Step 6: Render visual preview for review

- [ ] Run:
```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/worktree-worktree-visual-refactor-p3
venv/bin/python -c "
from docket.web import create_app
from datetime import datetime, timezone, timedelta
app = create_app()
variants = [
    ('Full metadata + good freshness', {'council_type':'Mayor-council','county':'Jefferson County','population':196910}, {'state':'good','label':'Live','last_synced':datetime.now(timezone.utc) - timedelta(minutes=4)}),
    ('Partial metadata + warn freshness', {'county':'Some County'}, {'state':'warn','label':'Recent','last_synced':datetime.now(timezone.utc) - timedelta(days=3)}),
    ('No metadata + unknown freshness', {}, {'state':'unknown','label':'No data yet','last_synced':None}),
]
out = []
with app.test_request_context():
    from flask import render_template
    for label, md, fr in variants:
        m = {'id':1,'slug':'birmingham','name':'Birmingham','state':'AL','adapter_class':'GranicusAdapter','metadata':md}
        rendered = render_template('partials/city_lead.html', municipality=m, freshness=fr)
        out.append(f'<div style=\"margin:32px 0;border:1px dashed #ccc;padding:8px\"><div style=\"font-family:monospace;font-size:11px;color:#777;margin-bottom:8px\">{label}</div>{rendered}</div>')
open('/tmp/p3-task4-city-lead.html','w').write(
    '<link rel=\"stylesheet\" href=\"http://localhost:5001/static/styles.css\"><link rel=\"stylesheet\" href=\"http://localhost:5001/static/layout.css\"><body style=\"background:#fafaf7;padding:40px\">' + ''.join(out) + '</body>'
)
"
DBURL=$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)
DATABASE_URL="$DBURL" PORT=5001 venv/bin/flask --app docket.web run --port 5001 > /tmp/p3-task4-flask.log 2>&1 &
echo $! > /tmp/p3-task4-flask.pid
sleep 3
```
Then controller opens `/tmp/p3-task4-city-lead.html` for **🛑 HUMAN VISUAL REVIEW**.

### Step 7: Commit

```bash
git add src/docket/web/templates/partials/city_lead.html \
        src/docket/web/static/layout.css \
        tests/web/test_partials_visual_refactor.py
git commit -m "feat(partials): city_lead — eyebrow + h1 + freshness chip

CityLead block for P3 top-of-overview. Eyebrow renders gracefully when
municipality.metadata is partial or empty. Freshness chip is static in
P3 (P4 wires the source-health route + clickability)."
```

---

## Task 5: New partial `partials/kpi_strip.html` + CSS

**Files:**
- Create: `src/docket/web/templates/partials/kpi_strip.html`
- Modify: `src/docket/web/static/layout.css` (new `.kpi-strip` rules)
- Modify: `tests/web/test_partials_visual_refactor.py`

### Step 1: Write failing test

- [ ] Append to `tests/web/test_partials_visual_refactor.py`:

```python
def test_kpi_strip_renders_three_cards(render_partial):
    """kpi_strip wraps 3 num_stat partials in a single .kpi-strip row."""
    city_stats = {
        "meetings_ytd": 38,
        "dollars_ytd_formatted": "$1.4B",
        "flagged_count": 12,
    }
    html = render_partial("kpi_strip", city_stats=city_stats)
    assert 'class="kpi-strip' in html
    # All three values present
    assert "38" in html
    assert "1.4B" in html
    assert "12" in html
    # All three labels present
    assert "Meetings YTD" in html
    assert "Dollars YTD" in html
    assert "Flagged" in html  # "Flagged items" or similar
```

### Step 2: Run; verify failure

- [ ] Run:
```bash
venv/bin/pytest tests/web/test_partials_visual_refactor.py -k "kpi_strip" -v 2>&1 | tail -5
```
Expected: FAIL — TemplateNotFound.

### Step 3: Create the partial

- [ ] Create `src/docket/web/templates/partials/kpi_strip.html`:

```jinja
{# 3-card YTD KPI strip for P3 city overview top.

   Args:
     city_stats (dict) — required. Must include:
       - meetings_ytd (int)
       - dollars_ytd_formatted (str, e.g. "$1.4B" — pre-formatted by view)
       - flagged_count (int)

   Wraps 3 num_stat partials. On desktop 3 equal columns; on mobile
   becomes horizontal scroll-snap (mobile.css).
#}
<div class="kpi-strip">
  {% with label="Meetings YTD", value="{:,}".format(city_stats.meetings_ytd) %}
    {% include 'partials/num_stat.html' with context %}
  {% endwith %}
  {% with label="Dollars YTD", value=city_stats.dollars_ytd_formatted %}
    {% include 'partials/num_stat.html' with context %}
  {% endwith %}
  {% with label="Flagged items", value="{:,}".format(city_stats.flagged_count), sub="contested votes YTD" %}
    {% include 'partials/num_stat.html' with context %}
  {% endwith %}
</div>
```

### Step 4: Add CSS to `layout.css`

- [ ] Append after the `.city-lead*` rules:

```css
/* ── KPI strip (P3 top-of-overview) ─────────────────────────── */
.kpi-strip {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-4);
  margin: var(--space-4) 0 var(--space-8);
}
```

### Step 5: Run tests

- [ ] Run:
```bash
venv/bin/pytest tests/web/test_partials_visual_refactor.py -k "kpi_strip" -v
```
Expected: PASS.

### Step 6: Commit

```bash
git add src/docket/web/templates/partials/kpi_strip.html \
        src/docket/web/static/layout.css \
        tests/web/test_partials_visual_refactor.py
git commit -m "feat(partials): kpi_strip — 3-card YTD KPI row for city overview"
```

---

## Task 6: Update `city_overview()` view function

**Files:**
- Modify: `src/docket/web/public.py` (`_city_overview_render` function around line 103-174)

### Step 1: Write integration test

- [ ] Create `tests/web/test_city_overview_render.py`:

```python
"""Render tests for the P3 city overview rebuild."""


def test_overview_renders_city_lead(client):
    resp = client.get("/al/birmingham/")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'class="city-lead' in html
    assert "Birmingham, AL" in html


def test_overview_renders_kpi_strip(client):
    resp = client.get("/al/birmingham/")
    html = resp.data.decode()
    assert 'class="kpi-strip' in html
    assert "Meetings YTD" in html
    assert "Dollars YTD" in html
    assert "Flagged" in html


def test_overview_has_no_kpi_explainer_stack(client):
    """KPI explainer stack (page_sources kpi_stats) is OFF overview in P3."""
    resp = client.get("/al/birmingham/")
    html = resp.data.decode()
    # page_sources still renders (provenance), but no kpi_stats data
    assert 'class="page-sources"' in html
    assert 'page-sources-kpis' not in html


def test_overview_no_longer_renders_old_hero_or_kpi_grid(client):
    """The old 4-card KPI grid + hero narrative are deleted."""
    resp = client.get("/al/birmingham/")
    html = resp.data.decode()
    assert 'class="kpi-grid"' not in html
    assert 'class="hero"' not in html or 'class="hero-title"' not in html
```

### Step 2: Run; verify failure (city_lead/kpi_strip not yet in template)

- [ ] Run:
```bash
venv/bin/pytest tests/web/test_city_overview_render.py -v 2>&1 | tail -10
```
Expected: tests FAIL because `city.html` doesn't yet include the new partials.

### Step 3: Update `_city_overview_render` in `public.py`

- [ ] Modify `src/docket/web/public.py`. In `_city_overview_render` (~line 103-174):
  - REMOVE the `kpi_stats = [...]` block (the 4-item list from P2b).
  - REMOVE `kpi_stats=kpi_stats` from the render_template call.
  - ADD: compute `city_stats` (3-card data) + `freshness` (from helpers).
  - ADD: pass `city_stats=city_stats, freshness=freshness` to render_template.

Concrete code to insert before `rendered = render_template(...)`:

```python
# P3 — city_stats for the new 3-card YTD strip at the top of overview.
mid = municipality["id"]
ytd_dollars = query.sum_dollars_ytd(mid)
if ytd_dollars >= 1_000_000_000:
    dollars_formatted = f"${ytd_dollars / 1_000_000_000:.1f}B"
elif ytd_dollars >= 1_000_000:
    dollars_formatted = f"${ytd_dollars / 1_000_000:.1f}M"
else:
    dollars_formatted = f"${int(ytd_dollars):,}"
city_stats = {
    "meetings_ytd": query.count_meetings_ytd(mid),
    "dollars_ytd_formatted": dollars_formatted,
    "flagged_count": query.count_contested_votes_ytd(mid),
}
freshness = query._freshness_state(query.most_recent_ingest_at(mid))
```

Then in the `render_template` call: REPLACE `kpi_stats=kpi_stats,` with `city_stats=city_stats, freshness=freshness,`.

(Don't add `kpi_stats=...` — overview no longer renders the explainer stack at bottom.)

### Step 4: Run integration tests; expect PARTIAL pass

- [ ] Run:
```bash
venv/bin/pytest tests/web/test_city_overview_render.py -v 2>&1 | tail -10
```
- The "no kpi_explainer" test should PASS (overview no longer passes kpi_stats).
- The "renders city_lead / kpi_strip" tests still FAIL (templates aren't included in city.html yet — Task 8).

### Step 5: Commit (partial — full integration in Task 8)

```bash
git add src/docket/web/public.py tests/web/test_city_overview_render.py
git commit -m "feat(public): city_overview builds city_stats + freshness; drops kpi_stats

KPI section split (P3): overview owns the top YTD strip; the explainer
stack moves to interior pages (Task 7 wires those view functions)."
```

---

## Task 7: Add `kpi_stats` to interior view functions

**Files:**
- Modify: `src/docket/web/public.py` — `city_meetings`, `city_council`, `search`, `topic_detail`, `meeting_detail`, `category_landing`

### Step 1: Write failing tests

- [ ] Append to `tests/web/test_city_overview_render.py`:

```python
def test_meetings_list_renders_kpi_explainer_stack(client):
    """Interior pages get the 4-card KPI explainer stack in page_sources."""
    resp = client.get("/al/birmingham/meetings/")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'class="page-sources"' in html
    assert 'page-sources-kpis' in html


def test_council_renders_kpi_explainer_stack(client):
    resp = client.get("/al/birmingham/council/")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'page-sources-kpis' in html


def test_search_renders_kpi_explainer_stack(client):
    resp = client.get("/search?q=demolition")
    assert resp.status_code == 200
    html = resp.data.decode()
    # Search may not be city-scoped — kpi_stats only renders when
    # municipality is in context. If search is global, this test
    # changes to assert page_sources renders without kpi_stats.
    # Check first what the search route returns:
    if 'class="page-sources"' in html and "Birmingham" in html:
        assert 'page-sources-kpis' in html


def test_topic_detail_renders_kpi_explainer_stack(client):
    # topic_detail route uses a topic slug; pick a known topic
    resp = client.get("/al/birmingham/topics/public_safety")
    if resp.status_code == 200:
        html = resp.data.decode()
        assert 'page-sources-kpis' in html
```

### Step 2: Run; verify failure

- [ ] Run:
```bash
venv/bin/pytest tests/web/test_city_overview_render.py -k "kpi_explainer_stack" -v 2>&1 | tail -10
```
Expected: 2-4 FAIL (interior pages don't pass kpi_stats yet).

### Step 3: Add `kpi_stats` to each interior view function

- [ ] For each of `city_meetings`, `city_council`, `meeting_detail`, `category_landing`, `topic_detail`:
  - Find the `render_template(...)` call inside the function
  - Add `kpi_stats=query._kpi_stats_for_municipality(municipality),` to the kwargs

For `search()`: check whether `municipality` is in scope. Search may be global (no city scope) or city-scoped depending on URL params. If it's sometimes scoped, conditionally pass kpi_stats only when scoped:

```python
# For city-scoped pages:
kpi_stats = query._kpi_stats_for_municipality(municipality)

# In render_template:
return render_template(
    "city_meetings.html",
    municipality=municipality,
    # ...existing kwargs...
    kpi_stats=kpi_stats,
)
```

For each view function, the change is one new line of data prep + one new kwarg in render_template. Total: 6 small edits.

### Step 4: Run tests

- [ ] Run:
```bash
venv/bin/pytest tests/web/ -q 2>&1 | tail -3
```
Expected: green. Interior page tests should now PASS.

### Step 5: Commit

```bash
git add src/docket/web/public.py tests/web/test_city_overview_render.py
git commit -m "feat(public): interior pages now render KPI explainer stack

city_meetings, city_council, search (when city-scoped), topic_detail,
meeting_detail, and category_landing now pass kpi_stats to page_sources.
The 4-card explainer block (Meetings lifetime / Agenda items YTD /
Votes YTD / Dollars pending vs settled) appears at the bottom of
interior pages, giving city-wide context to deep-linked visitors."
```

---

## Task 8: Rewrite `city.html` top section

**Files:**
- Modify: `src/docket/web/templates/city.html`

### Step 1: Read existing city.html

- [ ] Read `src/docket/web/templates/city.html` end-to-end. Identify the hero block, 4-card KPI grid, 2 standalone KPI cards (Council members / Topics tracked), and badge legend paragraph.

### Step 2: Delete the old top section + insert new partials

- [ ] At the top of `{% block content %}` (or wherever the hero currently begins), REPLACE:

```jinja
{# OLD: <section class="hero">...</section> #}
{# OLD: <section class="kpi-grid">...4 KPI cards...</section> #}
{# OLD: standalone Council members / Topics tracked cards #}
{# OLD: badge legend paragraph #}
```

WITH:

```jinja
{% include 'partials/city_lead.html' %}
{% include 'partials/kpi_strip.html' %}
```

The Browse by Priority grid + below-the-fold sections stay AS-IS.

### Step 3: Run city overview integration tests

- [ ] Run:
```bash
venv/bin/pytest tests/web/test_city_overview_render.py -v 2>&1 | tail -10
```
Expected: all PASS (city_lead, kpi_strip, no kpi_explainer on overview, no hero/kpi_grid leftovers).

### Step 4: Visual smoke against Railway DB

- [ ] Run:
```bash
DBURL=$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)
DATABASE_URL="$DBURL" PORT=5001 venv/bin/flask --app docket.web run --port 5001 > /tmp/p3-task8-flask.log 2>&1 &
echo $! > /tmp/p3-task8-flask.pid
sleep 3
curl -sf -o /dev/null -w "%{http_code}\n" http://localhost:5001/al/birmingham/
```
Expected: 200.

🛑 **HUMAN VISUAL REVIEW** — controller opens `http://localhost:5001/al/birmingham/` to confirm:
- CityLead renders (eyebrow + h1 + freshness chip)
- 3-card YTD strip below
- Browse by Priority renders unchanged
- Below-the-fold sections all render
- No hero narrative, no 4-card KPI grid, no Council/Topics standalone cards, no badge legend
- Bottom page_sources shows provenance ONLY (no KPI explainer stack)

### Step 5: Commit

```bash
git add src/docket/web/templates/city.html
git commit -m "feat(city.html): rewrite top section to CityLead + kpi_strip

Deletes hero narrative + 4-card KPI grid + Council/Topics standalone
cards + badge legend paragraph. New top: city_lead partial (eyebrow +
h1 + freshness chip) + kpi_strip partial (3-card YTD row). Below-the-
fold unchanged."
```

---

## Task 9: Footer colophon slim — remove Adapter tile

**Files:**
- Modify: `src/docket/web/templates/partials/footer.html`
- Modify: `tests/web/test_card_navigation.py` (or create new test file) — assert Adapter tile gone

### Step 1: Write failing test

- [ ] Append to `tests/web/test_city_overview_render.py`:

```python
def test_footer_colophon_has_no_adapter_tile(client):
    """P3: footer colophon drops the Adapter tile (page_sources owns
    per-city Adapter; footer is 'about the project')."""
    resp = client.get("/al/birmingham/")
    html = resp.data.decode()
    # The Adapter tile in footer was a <div><span class="t-label">Adapter</span>...
    # in the footnote-grid block. Find footer section and assert no Adapter tile.
    # Heuristic: search for the colophon adapter pattern.
    footer_start = html.find("footnote-colophon")
    footer_end = html.find("footnote-bottom", footer_start)
    footer_html = html[footer_start:footer_end]
    # Footer should NOT contain "Adapter" as a label (page_sources may).
    assert "Adapter</span>" not in footer_html, (
        "footer colophon still has Adapter tile"
    )
```

### Step 2: Run; verify failure

- [ ] Run:
```bash
venv/bin/pytest tests/web/test_city_overview_render.py -k "footer_colophon" -v
```
Expected: FAIL.

### Step 3: Remove the Adapter tile from footer.html

- [ ] In `src/docket/web/templates/partials/footer.html`, find the `<div class="footnote-grid t-mono">` block (around lines 28-35). Remove ONLY the Adapter `<div>`:

```jinja
{# REMOVE this entire <div>: #}
<div><span class="t-label">Adapter</span><div>{{ municipality.adapter_class }} · {{ municipality.adapter_class | replace('Adapter', '') }}</div></div>
```

Keep the Schema, Source, Updated tiles. The grid still renders 3 cells; CSS may reflow gracefully.

### Step 4: Run test; verify pass

- [ ] Run:
```bash
venv/bin/pytest tests/web/test_city_overview_render.py -k "footer_colophon" -v
```
Expected: PASS.

### Step 5: Commit

```bash
git add src/docket/web/templates/partials/footer.html tests/web/test_city_overview_render.py
git commit -m "refactor(footer): drop Adapter tile from colophon (P3)

page_sources.html (P2b) already shows per-city Adapter info on every
page. Footer colophon was duplicating it. Footer now reads as 'about
the project' (Schema · Source · Updated + data-honesty paragraph)."
```

---

## Task 10: `.hero-title` → `var(--type-hero)` token migration

**Files:**
- Modify: `src/docket/web/static/layout.css` (line ~146)

### Step 1: Write a regression test

- [ ] Append to `tests/web/test_partials_visual_refactor.py`:

```python
def test_hero_title_uses_type_hero_token():
    """P3 token migration: .hero-title consumes var(--type-hero), not a literal."""
    css = (PROJECT_ROOT / "src/docket/web/static/layout.css").read_text()
    # Find the .hero-title rule
    import re
    match = re.search(r"\.hero-title\s*\{[^}]*\}", css)
    assert match, ".hero-title rule missing from layout.css"
    rule_body = match.group(0)
    assert "var(--type-hero)" in rule_body, ".hero-title not consuming --type-hero token"
    assert "font-size: 72px" not in rule_body, ".hero-title still has 72px literal"
```

### Step 2: Run; verify failure

- [ ] Run:
```bash
venv/bin/pytest tests/web/test_partials_visual_refactor.py -k "hero_title_uses_type_hero" -v
```
Expected: FAIL.

### Step 3: Update the rule

- [ ] In `src/docket/web/static/layout.css` line ~146:
```css
/* OLD: */
.hero-title { font-size: 72px; margin: 12px 0 16px; }

/* NEW: */
.hero-title { font-size: var(--type-hero); margin: 12px 0 16px; }
```

The `--type-hero` token is `64px` per `styles.css:52`. Visual delta on site: hero shrinks from 72px to 64px.

### Step 4: Run test; verify pass

- [ ] Run:
```bash
venv/bin/pytest tests/web/test_partials_visual_refactor.py -k "hero_title_uses_type_hero" -v
```
Expected: PASS.

### Step 5: Commit

```bash
git add src/docket/web/static/layout.css tests/web/test_partials_visual_refactor.py
git commit -m "style(typography): .hero-title consumes --type-hero token (resolves P2a follow-up #1)

P2a defined --type-hero at 64px but .hero-title kept the legacy 72px
literal. CityLead in P3 consumes --type-hero directly, so this resolves
the token/literal divergence. Visual delta: hero shrinks from 72px to
64px, matching the spec's 'compress top of page' framing."
```

---

## Task 11: Mobile reflow CSS for CityLead + KPI strip

**Files:**
- Modify: `src/docket/web/static/mobile.css`

### Step 1: Append mobile rules

- [ ] At the end of `src/docket/web/static/mobile.css`, append:

```css
/* ── CityLead + KPI strip (P3, <768px) ─────────────────────── */
@media (max-width: 768px) {
  .city-lead { padding: var(--space-6) 0 var(--space-3); }
  .city-lead-h1 { font-size: 44px; line-height: 1.05; }
  .city-lead-row {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-2);
  }
  .city-lead-chip { font-size: 12px; padding: 4px 10px; }

  .kpi-strip {
    grid-template-columns: none;
    grid-auto-flow: column;
    grid-auto-columns: 130px;
    overflow-x: auto;
    scroll-snap-type: x mandatory;
    padding-bottom: var(--space-2);
    margin: var(--space-3) calc(-1 * var(--space-4)) var(--space-6);
    padding-left: var(--space-4);
    padding-right: var(--space-4);
  }
  .kpi-strip > * { scroll-snap-align: start; flex-shrink: 0; }
}
```

### Step 2: Visual smoke on mobile width

- [ ] Boot Flask (Railway DB), open `http://localhost:5001/al/birmingham/` and resize the viewport to 375px wide. Confirm CityLead reflows cleanly + KPI strip becomes horizontal-scrollable.

### Step 3: Commit

```bash
git add src/docket/web/static/mobile.css
git commit -m "style(mobile): CityLead reflow + KPI strip horizontal scroll-snap

At <768px: CityLead h1 drops to 44px, freshness chip flows below the
h1, KPI strip becomes a horizontal scroll-snap container (3 × 130px
cards). bottom_tabs unchanged from P2b."
```

---

## Task 12: Run EXPLAIN on Railway for the new queries

**Files:** none (verification only)

### Step 1: Run EXPLAIN for each new query

- [ ] Per memory `feedback_explain_at_scale.md`:

```bash
DBURL=$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)
/opt/homebrew/opt/postgresql@18/bin/psql "$DBURL" <<'SQL'
BEGIN;
\timing on
EXPLAIN (ANALYZE, BUFFERS)
  SELECT count(*) FROM meetings
  WHERE municipality_id = 1
    AND meeting_date >= date_trunc('year', now())::date;
EXPLAIN (ANALYZE, BUFFERS)
  SELECT coalesce(sum(ai.dollars_amount), 0) FROM agenda_items ai
  JOIN meetings m ON m.id = ai.meeting_id
  WHERE m.municipality_id = 1
    AND m.meeting_date >= date_trunc('year', now())::date;
EXPLAIN (ANALYZE, BUFFERS)
  SELECT count(DISTINCT v.id) FROM votes v
  JOIN meetings m ON m.id = v.meeting_id
  JOIN member_votes mv ON mv.vote_id = v.id
  WHERE m.municipality_id = 1
    AND m.meeting_date >= date_trunc('year', now())::date
    AND mv.vote IN ('no', 'abstain');
EXPLAIN (ANALYZE, BUFFERS)
  SELECT MAX(created_at) FROM meetings WHERE municipality_id = 1;
ROLLBACK;
SQL
```

Expected: each query under 50ms. If `count_contested_votes_ytd` exceeds 200ms (3-way join on member_votes), evaluate adding a covering index — but try caching first.

### Step 2: Report timings

Each query's Execution Time:
- `count_meetings_ytd`: ___ ms
- `sum_dollars_ytd`: ___ ms
- `count_contested_votes_ytd`: ___ ms
- `most_recent_ingest_at`: ___ ms

If any exceeds 200ms, STOP and decide on caching or indexing before merge.

### Step 3: No commit (verification only)

---

## Task 13: Final verification + visual sweep + open PR

**Files:** none (verification + PR open)

### Step 1: Cold-start full pytest

- [ ] Run:
```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/worktree-worktree-visual-refactor-p3
venv/bin/pytest --ignore=tests/live -q 2>&1 | tail -3
```
Expected: ~1620+ passed (1610 baseline after Task 3 + Tasks 4-11 added ~10 more tests).

### Step 2: Multi-page visual sweep (Railway DB)

- [ ] Boot Flask + walk surfaces:
```bash
DBURL=$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)
DATABASE_URL="$DBURL" PORT=5001 venv/bin/flask --app docket.web run --port 5001 > /tmp/p3-final-flask.log 2>&1 &
echo $! > /tmp/p3-final-flask.pid
sleep 4
for path in /al/birmingham/ /al/birmingham/meetings/ /al/birmingham/council/ /al/birmingham/meetings/100/ /al/birmingham/property_recovery "/search?q=demolition" /; do
  code=$(curl -sf -o /dev/null -w "%{http_code}" "http://localhost:5001$path")
  echo "$path: $code"
done
```
Expected: all 200.

🛑 **HUMAN VISUAL SWEEP** — controller opens each page:
- Overview: CityLead + KPI strip; no KPI explainer at bottom; provenance only
- Meetings list: KPI explainer stack visible at bottom
- Council: KPI explainer stack visible at bottom
- Meeting detail: KPI explainer stack visible at bottom
- Category landing: KPI explainer stack visible at bottom
- Search: depends on city-scoping; if city-scoped, KPI stack visible
- All pages: footer colophon has Schema · Source · Updated (3 tiles, NOT 4)
- Resize to 375px: CityLead reflows, KPI strip horizontal-scrolls, bottom_tabs visible

### Step 3: Push branch + open PR

- [ ] From the worktree (NOT canonical):
```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/worktree-worktree-visual-refactor-p3
git push -u origin worktree-worktree-visual-refactor-p3
gh pr create --title "Visual refactor — Phase 3 (city overview rebuild)" --body "$(cat <<'EOF'
## Summary

P3 rebuilds the city overview's top of page and splits KPI placement.

**CityLead** (new partial): replaces hero narrative + 4-card KPI grid + 2 standalone KPI cards + badge legend with eyebrow (council type · county · population from new metadata column) + h1 (city, state) + freshness chip (static in P3; P4 wires source-health route).

**3-card YTD strip** (new partial): Meetings YTD / Dollars YTD / Flagged items (contested votes YTD). 3 new query helpers in `query.py`.

**KPI section split**: 4-card explainer stack moves from overview's bottom (via page_sources) to interior pages (meetings list, council, search, topic detail, meeting detail, category landing). Overview's bottom is provenance-only.

**Migration 029**: `municipalities.metadata` JSONB column. Seeded for 6 existing cities (council_type / county / population / population_year). Future cities INSERT with their payload — no schema change per city.

## P2b follow-ups resolved
- #1 `--type-hero` token mismatch (`.hero-title` now consumes `var(--type-hero)` = 64px)
- #4 top 4-card KPI grid replacement (now 3-card YTD strip)
- #5 page_sources / footer.html colophon Adapter overlap (footer Adapter tile dropped)

## Out of scope (deferred)
- ~110 lines of orphan rail CSS in layout.css/mobile.css
- sheet.js dead source-rail branches
- Lifetime-dollar UX honesty
- Source health page (P4)
- Member detail page (P4)
- Breadcrumbs partial (P4 detail pages will introduce)

## Test plan
- [x] 1620+ pytest passed
- [x] Migration 029 apply + rollback verified
- [x] EXPLAIN on Railway for 4 new queries — all under 50ms
- [x] Visual sweep: 7 page surfaces, desktop + mobile (375px)
- [ ] After merge: `git checkout main && git pull && railway up --service docket-web --detach`
- [ ] Verify on production: CityLead renders + KPI explainer stack on interior pages

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

### Step 4: Update memory

- [ ] After PR opens, update `/Users/darrellnance/.claude-personal/projects/-Users-darrellnance/memory/project_visual_refactor_2026_05_14.md` to reflect P3 PR open.

---

## Self-review checklist

**1. Spec coverage:**
- ✅ CityLead block (Task 4)
- ✅ 3-card YTD strip (Task 5)
- ✅ Browse by Priority — kept structurally, no task needed (uses restyled badge_chip from P2b automatically)
- ✅ Below-the-fold sections — kept structurally, no task needed
- ✅ Deleted from city.html — hero, 4-card KPI grid, 2 standalone KPIs, badge legend (Task 8)
- ✅ page_sources/footer overlap — Adapter tile removed (Task 9)
- ✅ `--type-hero` migration (Task 10)
- ✅ Mobile reflow (Task 11)
- ✅ Migration 029 (Task 2)
- ✅ 6 query helpers (Task 3)
- ✅ city_overview view function update (Task 6)
- ✅ Interior view functions add kpi_stats (Task 7)
- ✅ Performance / EXPLAIN (Task 12)
- ✅ Visual sweep + PR (Task 13)

**2. Placeholder scan:**
- No "TBD" / "fill in details" entries.
- Task 7's `search()` route has a conditional check (city-scoped vs global) — the implementer handles this by inspecting the actual route; not a placeholder.

**3. Type consistency:**
- `kpi_stats` shape (list of dicts with `label`/`value`/`sub`/`sql_display`) matches what `page_sources.html` already consumes (from P2b).
- `freshness` shape (`{state, label, last_synced}`) — defined in `_freshness_state` (Task 3), consumed by `city_lead.html` (Task 4).
- `city_stats` shape (`{meetings_ytd, dollars_ytd_formatted, flagged_count}`) — built in `city_overview` (Task 6), consumed by `kpi_strip.html` (Task 5). Naming consistent.
- Migration filename `029_municipalities_metadata.py` — Python module path used in runner.py registration matches.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-15-visual-refactor-phase-3.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Controller dispatches a fresh sonnet subagent per task with the per-task review gates baked in. P3 has 13 substantive tasks; expect ~4-5 hours of wall time with the human visual reviews at Tasks 4, 8, 11, 13.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`. Batch execution with checkpoints at the human-review gates.

Which approach?
