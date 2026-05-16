# Umami Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Self-hosted Umami analytics on Railway, sharing the existing Postgres in a separate `umami` database. Three v1 custom events (rail_click, outbound_source_click, search_submit) plus pageviews / geo / referrers. Claude queries the data via stable read-only views.

**Architecture:** New `analytics` Railway service runs `umamisoftware/umami:postgresql-v2.20.2`, connects to a fresh `umami` database on the existing Postgres instance. A `db/umami_views.sql` file defines the stable read-only views consumers query (never raw Umami tables). One JS helper `track.js` wraps `umami.track()` with try/catch and a 40-char PII drop rule. Three event handlers wired in templates. One new `prune_analytics` task on the existing `worker` scheduler enforces 24-month retention.

**Tech Stack:** Umami v2 (Node, official Docker image), PostgreSQL 18.3 on Railway, Flask/Jinja2 templates, vanilla JS (no framework), APScheduler (existing worker), pytest.

**Spec:** `docs/superpowers/specs/2026-05-15-umami-analytics-design.md`

---

## Task 1: Operational runbook

Write the manual-setup runbook first so the operator (the user) has a clear procedure for the steps Railway can't automate (service provisioning, DNS, first-boot admin). Subsequent tasks reference it.

**Files:**
- Create: `docs/runbooks/analytics.md`

- [ ] **Step 1: Create the runbook file**

```markdown
# Analytics Runbook

Operational procedures for the `analytics` Railway service (self-hosted Umami) and the `umami` database on the existing Railway Postgres instance.

Spec: `docs/superpowers/specs/2026-05-15-umami-analytics-design.md`

## Initial Setup (one-time)

Prerequisites: `psql`, Railway CLI, registered SSH key (`railway ssh keys`), Namecheap DNS access for docket.pub.

### 1. Provision DB and roles

Generate two strong passwords (record in 1Password under "docket.pub / Umami"):

```bash
UMAMI_PW=$(openssl rand -base64 32)
UMAMI_READER_PW=$(openssl rand -base64 32)
```

Connect to the existing Railway Postgres via the public proxy:

```bash
/opt/homebrew/opt/postgresql@18/bin/psql "$DATABASE_PUBLIC_URL"
```

Run, substituting `<UMAMI_PW>` and `<UMAMI_READER_PW>`:

```sql
CREATE ROLE umami WITH LOGIN PASSWORD '<UMAMI_PW>' CONNECTION LIMIT 8;
CREATE DATABASE umami OWNER umami;
GRANT ALL PRIVILEGES ON DATABASE umami TO umami;

CREATE ROLE umami_reader WITH LOGIN PASSWORD '<UMAMI_READER_PW>';
GRANT CONNECT ON DATABASE umami TO umami_reader;
```

(The `GRANT SELECT` on views happens after the view layer is applied in step 5.)

### 2. Create the `analytics` Railway service

In the Railway dashboard for the docket.pub project:
1. New → Empty Service → name it `analytics`.
2. Settings → Source → Docker Image → `umamisoftware/umami:postgresql-v2.20.2`.
3. Settings → Environment → add:
   - `DATABASE_URL=postgres://umami:<UMAMI_PW>@<RAILWAY_PG_PUBLIC_HOST>:<PORT>/umami?connection_limit=5` (use the public host/port — internal hosts only resolve within Railway's VPC; the analytics service lives in the same project but uses the public URL pattern for consistency)
   - `APP_SECRET=$(openssl rand -base64 48)` (record in 1Password)
   - `HASH_SALT=$(openssl rand -base64 24)` (record in 1Password)
4. Settings → Networking → Generate Domain (note the `*.up.railway.app` URL temporarily).
5. Deploy. Tail logs until `> Ready` appears (~30 seconds).

### 3. Custom domain (`stats.docket.pub`)

In Railway Settings → Custom Domain for the `analytics` service:
1. Add `stats.docket.pub`. Railway provides a CNAME target.
2. In Namecheap (docket.pub DNS): add `CNAME stats → <railway-target>`. TTL 5 min for initial provisioning.
3. Wait for Let's Encrypt cert (typically 2–10 min). Refresh Railway domain page until "Active" appears.
4. Visit `https://stats.docket.pub` — should redirect to Umami's login page with valid cert.

### 4. First-boot admin

Default credentials are `admin / umami`. **Immediately:**
1. Log in.
2. Settings → Profile → change password (record in 1Password under "docket.pub / Umami admin").
3. Settings → Websites → Add Website → Name: "docket.pub", Domain: "docket.pub".
4. Copy the generated **Tracking Code** UUID. Record it in 1Password and as `UMAMI_WEBSITE_ID` for task 6.
5. Edit Website → Excluded URLs (one per line):
   ```
   /admin/*
   /healthz
   *.rss
   /al/*/data-debt.rss
   /al/*/upcoming-hearings.rss
   /coverage.rss
   ```
6. Settings → Websites → docket.pub → Share → enable public sharing. Copy the **Share URL** (looks like `https://stats.docket.pub/share/<token>/docket.pub`). Record for task 10.

### 5. Capture schema fixture and apply views

The fixture seeds the integration test; the view layer is the queryable surface.

```bash
# From the laptop. Captures only Umami's schema, no data.
/opt/homebrew/opt/postgresql@18/bin/pg_dump --schema-only --no-owner --no-privileges \
  "postgres://umami:<UMAMI_PW>@<RAILWAY_PG_PUBLIC_HOST>:<PORT>/umami" \
  > tests/fixtures/umami_schema_v2.sql

# Apply our view layer
/opt/homebrew/opt/postgresql@18/bin/psql \
  "postgres://umami:<UMAMI_PW>@<RAILWAY_PG_PUBLIC_HOST>:<PORT>/umami" \
  -f db/umami_views.sql
```

### 6. Worker env vars (for the retention task — task 4)

In Railway dashboard, `worker` service → Variables, add:
- `ANALYTICS_DATABASE_URL=postgres://umami:<UMAMI_PW>@<HOST>:<PORT>/umami?connection_limit=2`
- `HEALTHCHECK_PRUNE_ANALYTICS_UUID=<new-uuid-from-healthchecks.io>`

Create a new Healthchecks.io check (`prune_analytics`, monthly cron). Paste the UUID.

### 7. Reader credentials for ad-hoc Claude queries

Add to `~/.docket-pub.env.local` (not committed):

```bash
UMAMI_READER_URL="postgres://umami_reader:<UMAMI_READER_PW>@<HOST>:<PORT>/umami"
```

## Routine Operations

### Querying analytics

```bash
source ~/.docket-pub.env.local
/opt/homebrew/opt/postgresql@18/bin/psql "$UMAMI_READER_URL" \
  -c "SELECT normalized_path, SUM(pageviews) AS views FROM v_pageviews_daily WHERE day >= current_date - 7 GROUP BY 1 ORDER BY 2 DESC LIMIT 20;"
```

See `docs/analytics-queries.md` for the cheat sheet.

### Manual retention trigger

```bash
railway ssh --service worker
cd /app && python -m docket.worker.scheduler --run-once prune_analytics
```

### Umami version bump

1. Update the `analytics` service image tag in Railway dashboard.
2. After redeploy, re-capture the schema fixture (step 5 above).
3. Run the integration tests: `pytest tests/integration/test_analytics_views.py -v`.
4. If any view definition broke, fix `db/umami_views.sql` and re-apply.
5. Commit both the new fixture and any view changes.

## Failure Modes

- **Tracker JS blocked by adblocker**: `docketTrack()` no-ops. Expected. Pageviews still missing.
- **Prisma queue timeout under spike**: events drop, `docket-web` unaffected. See spec Risks.
- **`umami` role hits 8-connection cap**: Postgres rejects new Umami connections until existing ones close. Container does not crash thanks to `connection_limit=5` on the Prisma side.
- **stats.docket.pub cert expired**: Let's Encrypt auto-renews via Railway. If it lapses, regenerate via the Custom Domain panel.
```

- [ ] **Step 2: Commit the runbook**

```bash
cd ~/docket-pub
git add docs/runbooks/analytics.md
git commit -m "docs(analytics): runbook for umami service + db provisioning"
```

---

## Task 2: View layer SQL

The stable read-only surface consumers query. Lives in `db/umami_views.sql`. No test in this task — the integration test needs the schema fixture, which is produced during the manual phase (see Task 5).

**Files:**
- Create: `db/umami_views.sql`

- [ ] **Step 1: Create `db/` directory if missing**

```bash
cd ~/docket-pub
mkdir -p db
```

- [ ] **Step 2: Write the views file**

Create `db/umami_views.sql`:

```sql
-- Stable read-only views over Umami's raw schema.
-- All path normalization happens here, NOT at ingestion time.
-- When Umami upgrades and breaks a column, fix THIS file — never the consumers.
--
-- Apply with:
--   psql "postgres://umami:...@.../umami" -f db/umami_views.sql
--
-- The `umami_reader` role's GRANT lines at the bottom let read-only consumers
-- (Claude, ad-hoc analysis) hit the views without touching raw tables.

DROP VIEW IF EXISTS v_pageviews_daily CASCADE;
CREATE VIEW v_pageviews_daily AS
SELECT
  date_trunc('day', created_at)::date AS day,
  CASE
    WHEN url_path ~ '^/al/[^/]+/meetings/\d+' THEN
         regexp_replace(url_path, '/meetings/\d+', '/meetings/[id]')
    WHEN url_path ~ '^/al/[^/]+/items/\d+' THEN
         regexp_replace(url_path, '/items/\d+', '/items/[id]')
    WHEN url_path ~ '^/coverage/\d+' THEN '/coverage/[id]'
    WHEN url_path ~ '^/items/\d+/badges' THEN '/items/[id]/badges'
    ELSE url_path
  END AS normalized_path,
  COUNT(*) AS pageviews,
  COUNT(DISTINCT session_id) AS sessions
FROM website_event
WHERE event_type = 1  -- pageview
GROUP BY 1, 2;

DROP VIEW IF EXISTS v_event_counts_daily CASCADE;
CREATE VIEW v_event_counts_daily AS
SELECT
  date_trunc('day', created_at)::date AS day,
  event_name,
  COUNT(*) AS count,
  COUNT(DISTINCT session_id) AS sessions
FROM website_event
WHERE event_type = 2  -- custom event
GROUP BY 1, 2;

DROP VIEW IF EXISTS v_event_props_daily CASCADE;
CREATE VIEW v_event_props_daily AS
SELECT
  date_trunc('day', we.created_at)::date AS day,
  we.event_name,
  ed.data_key   AS prop_key,
  ed.string_value AS prop_value,
  COUNT(*) AS count
FROM website_event we
JOIN event_data ed ON ed.website_event_id = we.event_id
WHERE we.event_type = 2
GROUP BY 1, 2, 3, 4;

DROP VIEW IF EXISTS v_referrers_daily CASCADE;
CREATE VIEW v_referrers_daily AS
SELECT
  date_trunc('day', created_at)::date AS day,
  referrer_domain,
  COUNT(*) AS pageviews
FROM website_event
WHERE event_type = 1 AND referrer_domain IS NOT NULL
GROUP BY 1, 2;

DROP VIEW IF EXISTS v_geo_daily CASCADE;
CREATE VIEW v_geo_daily AS
SELECT
  date_trunc('day', created_at)::date AS day,
  country,
  city,
  COUNT(*) AS pageviews,
  COUNT(DISTINCT session_id) AS sessions
FROM website_event
WHERE event_type = 1
GROUP BY 1, 2, 3;

-- Grants for the read-only role. umami_reader gets NO access to raw tables.
GRANT USAGE ON SCHEMA public TO umami_reader;
GRANT SELECT ON
  v_pageviews_daily,
  v_event_counts_daily,
  v_event_props_daily,
  v_referrers_daily,
  v_geo_daily
TO umami_reader;
```

- [ ] **Step 3: Validate SQL syntax locally**

Spin up a throwaway Postgres container to lint the SQL syntactically (it won't apply because the underlying Umami tables don't exist locally — we're just checking parser-level validity):

```bash
docker run --rm -i postgres:18 sh -c '
  pg_ctl init -D /tmp/pgdata -s -o "-A trust" &&
  pg_ctl start -D /tmp/pgdata -s -l /tmp/pglog &&
  createdb -h /tmp test &&
  cat | psql -h /tmp test -v ON_ERROR_STOP=1 -c "CREATE TABLE website_event (event_id uuid, created_at timestamptz, url_path text, session_id uuid, event_type int, event_name text, referrer_domain text, country text, city text); CREATE TABLE event_data (website_event_id uuid, data_key text, string_value text); CREATE ROLE umami_reader;" -f -
' < db/umami_views.sql
```

Expected: no errors. If any view definition has a typo, fix it now.

- [ ] **Step 4: Commit**

```bash
git add db/umami_views.sql
git commit -m "feat(analytics): umami read-only view layer"
```

---

## Task 3: Event helper (`track.js`)

Single source of truth for custom event tracking. Wraps `umami.track()`, drops string props > 40 chars (PII guardrail), no-ops if tracker blocked.

**Files:**
- Create: `src/docket/web/static/js/track.js`

- [ ] **Step 1: Write the helper**

Create `src/docket/web/static/js/track.js`:

```javascript
/* docket.pub event tracker.
 *
 * Single source of truth for custom analytics events. Two responsibilities:
 *
 *   1. Wrap window.umami.track() with try/catch so a blocked or absent
 *      analytics script can NEVER break a click handler or other UX.
 *   2. Enforce the PII guardrail: drop any string-valued property longer
 *      than QUERY_MAX_LEN before sending. Most legitimate topic searches
 *      ("flock cameras", "zoning board") are short; addresses and PII
 *      run long. Drop rather than truncate — truncating still leaks the
 *      address prefix ("1234 Maple S…" identifies the house).
 *
 * Usage:
 *   docketTrack('rail_click', {
 *     rail_variant: 'meeting',
 *     source_page_type: 'city',
 *     target_type: 'item',
 *     target_id: 12345,
 *   });
 */
(function () {
  'use strict';

  var QUERY_MAX_LEN = 40;

  function sanitizeProps(props) {
    var out = {};
    if (!props) return out;
    var keys = Object.keys(props);
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i];
      var v = props[k];
      if (typeof v === 'string' && v.length > QUERY_MAX_LEN) continue;
      out[k] = v;
    }
    return out;
  }

  window.docketTrack = function (name, props) {
    try {
      if (window.umami && typeof window.umami.track === 'function') {
        window.umami.track(name, sanitizeProps(props));
      }
    } catch (e) {
      // Analytics blocked or failed — never break the page.
    }
  };

  // Exposed for unit-style verification in the browser console:
  //   window.__docketTrackInternals.sanitizeProps({q: 'x'.repeat(50)}) // → {}
  window.__docketTrackInternals = { sanitizeProps: sanitizeProps, QUERY_MAX_LEN: QUERY_MAX_LEN };
})();
```

- [ ] **Step 2: Manual verification checklist**

Add a verification block to the runbook so the operator can confirm `sanitizeProps` works before the script ships:

Open browser dev console on any docket.pub page (after task 6 lands `track.js`) and run:

```javascript
__docketTrackInternals.sanitizeProps({short: 'ok', long: 'x'.repeat(50), num: 42});
// Expected: {short: 'ok', num: 42}   (long is dropped)

docketTrack('test_event', {q: 'topic'});  // should not throw
docketTrack('test_event', {q: 'x'.repeat(100)});  // should not throw, prop dropped
```

This is logic simple enough that a manual smoke through `window.__docketTrackInternals` is sufficient; no JS test infra needed.

- [ ] **Step 3: Commit**

```bash
git add src/docket/web/static/js/track.js
git commit -m "feat(analytics): docketTrack helper with PII drop guardrail"
```

---

## Task 4: `prune_analytics` worker task

New task on the existing worker scheduler. Monthly cron, 24-month retention. Follows the existing `_do_<name>` / `task_<name>` / `TASKS` registry pattern.

**Files:**
- Modify: `src/docket/worker/tasks.py` (add `_do_prune_analytics`, `task_prune_analytics`, register in `TASKS`)
- Modify: `src/docket/worker/scheduler.py:104` (add job to `build_scheduler`)
- Create: `tests/unit/test_worker_tasks_prune_analytics.py`

- [ ] **Step 1: Write the failing unit test**

Create `tests/unit/test_worker_tasks_prune_analytics.py`:

```python
"""Unit tests for the prune_analytics worker task.

The task connects directly to the umami database via $ANALYTICS_DATABASE_URL
(separate from the editorial $DATABASE_URL) and issues a single bounded
DELETE. The connection is psycopg-based, not the docket.db.db() helper,
because the target DB is a different database on the same Postgres instance.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from docket.worker.tasks import _do_prune_analytics


@patch.dict("os.environ", {"ANALYTICS_DATABASE_URL": "postgres://u:p@h:5/umami"})
@patch("docket.worker.tasks.psycopg")
def test_prune_analytics_issues_bounded_delete(mock_psycopg):
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 17
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_psycopg.connect.return_value.__enter__.return_value = mock_conn

    result = _do_prune_analytics()

    mock_psycopg.connect.assert_called_once_with("postgres://u:p@h:5/umami")
    executed_sql = mock_cursor.execute.call_args[0][0]
    assert "DELETE FROM website_event" in executed_sql
    assert "24 months" in executed_sql
    mock_conn.commit.assert_called_once()
    assert result == {"deleted": 17}


@patch.dict("os.environ", {}, clear=True)
def test_prune_analytics_raises_without_env_var():
    with pytest.raises(KeyError):
        _do_prune_analytics()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ~/docket-pub
venv/bin/pytest tests/unit/test_worker_tasks_prune_analytics.py -v
```

Expected: FAIL with `ImportError: cannot import name '_do_prune_analytics'`.

- [ ] **Step 3: Implement the task in `tasks.py`**

Add to the top of `src/docket/worker/tasks.py` imports section:

```python
import os

import psycopg
```

Add this function block alongside the other `_do_*` functions in `src/docket/worker/tasks.py` (after `_do_refresh_backfill_ratio_mv`, before the `task_*` wrapper section):

```python
def _do_prune_analytics() -> dict[str, int]:
    """Delete Umami events older than 24 months.

    Connects to the umami database via $ANALYTICS_DATABASE_URL (a separate
    DSN from the editorial $DATABASE_URL — different role, different db).
    Idempotent; returns the deleted row count.
    """
    dsn = os.environ["ANALYTICS_DATABASE_URL"]
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM website_event "
            "WHERE created_at < NOW() - INTERVAL '24 months'"
        )
        deleted = cur.rowcount
        conn.commit()
    log.info("prune_analytics deleted=%d", deleted)
    return {"deleted": deleted}
```

Add the public wrapper near the other `task_*` functions:

```python
def task_prune_analytics() -> None:
    _safe_run("prune_analytics", _do_prune_analytics)
```

Register in the `TASKS` dict at the bottom of the file:

```python
TASKS: dict[str, Callable[[], None]] = {
    "repair_empty_agendas": task_repair_empty_agendas,
    "ingest_all": task_ingest_all,
    "ai_items": task_ai_items,
    "ai_meetings": task_ai_meetings,
    "vote_matching": task_vote_matching,
    "process_badges": task_process_badges,
    "calibration_report": task_calibration_report,
    "process_batches": task_process_batches,
    "refresh_backfill_ratio_mv": task_refresh_backfill_ratio_mv,
    "prune_analytics": task_prune_analytics,
}
```

- [ ] **Step 4: Run unit tests**

```bash
venv/bin/pytest tests/unit/test_worker_tasks_prune_analytics.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 5: Register the cron job in `scheduler.py`**

In `src/docket/worker/scheduler.py:104` (after the `refresh_backfill_ratio_mv` job, before `return sched`):

```python
    # Monthly retention: drop Umami events older than 24 months.
    # 1st of the month at 04:00 America/Chicago — before the morning task
    # cluster, when DB pressure is lowest.
    sched.add_job(
        TASKS["prune_analytics"],
        CronTrigger(day=1, hour=4, minute=0, timezone=timezone),
        id="prune_analytics",
        coalesce=True,
        max_instances=1,
    )
```

- [ ] **Step 6: Verify scheduler still imports cleanly**

```bash
venv/bin/python -c "from docket.worker.scheduler import build_scheduler; s = build_scheduler(); print(sorted(j.id for j in s.get_jobs()))"
```

Expected output:
```
['ai_items', 'ai_meetings', 'calibration_report', 'ingest_all', 'process_batches', 'process_badges', 'prune_analytics', 'refresh_backfill_ratio_mv', 'repair_empty_agendas', 'vote_matching']
```

- [ ] **Step 7: Commit**

```bash
git add src/docket/worker/tasks.py src/docket/worker/scheduler.py tests/unit/test_worker_tasks_prune_analytics.py
git commit -m "feat(worker): prune_analytics monthly retention task"
```

---

## 🛠 USER ACTION PHASE — Manual Setup (executed against the runbook)

**Before any subsequent tasks**, the operator follows `docs/runbooks/analytics.md` sections 1–7 to:

1. Create the `umami` and `umami_reader` Postgres roles and the `umami` database.
2. Create the `analytics` Railway service running `umamisoftware/umami:postgresql-v2.20.2`.
3. Configure `stats.docket.pub` custom domain + Let's Encrypt cert.
4. Boot the Umami container, complete first-boot admin, register the website, capture the **website ID UUID**.
5. Configure excluded URLs in Umami.
6. Enable share link, capture the **public share URL**.
7. `pg_dump --schema-only` Umami's first-boot schema → commit `tests/fixtures/umami_schema_v2.sql`.
8. Apply `db/umami_views.sql` to the `umami` database.
9. Add `ANALYTICS_DATABASE_URL` + `HEALTHCHECK_PRUNE_ANALYTICS_UUID` env vars to the `worker` service.
10. Save `umami_reader` credentials in `~/.docket-pub.env.local`.

The plan resumes at Task 5 with the **website ID UUID** and **public share URL** in hand, and `tests/fixtures/umami_schema_v2.sql` committed.

- [ ] **Step 1: Operator confirms manual phase complete**

Required artifacts before resuming:
- ✅ `tests/fixtures/umami_schema_v2.sql` committed to the repo.
- ✅ `UMAMI_WEBSITE_ID` recorded (will be hardcoded in `base.html` — public identifier, not a secret).
- ✅ `UMAMI_PUBLIC_SHARE_URL` recorded (used in Task 10 for the footer link).
- ✅ `ANALYTICS_DATABASE_URL` set on the `worker` service in Railway.
- ✅ `HEALTHCHECK_PRUNE_ANALYTICS_UUID` set on the `worker` service in Railway.

If any are missing, return to the runbook before continuing.

---

## Task 5: Integration test for the view layer

Now that the fixture exists, write the integration test. Loads `tests/fixtures/umami_schema_v2.sql` into a throwaway Postgres, applies `db/umami_views.sql`, inserts hand-crafted rows, asserts each view aggregates correctly.

**Files:**
- Create: `tests/integration/test_analytics_views.py`
- Reference: `tests/fixtures/umami_schema_v2.sql` (already committed in the manual phase)
- Reference: `db/umami_views.sql`

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_analytics_views.py`:

```python
"""Integration test for db/umami_views.sql.

Loads Umami's schema fixture into a throwaway Postgres, applies our view
layer, inserts hand-crafted rows, asserts each view returns the expected
aggregation.

Runs against a temporary database created from $DATABASE_URL (the local
docket_db connection). The test creates and drops a database called
docket_test_umami_views_{pid} so parallel runs don't collide.

Fixture is regenerated only on Umami version bumps — see the runbook.
"""

from __future__ import annotations

import os
import pathlib
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "umami_schema_v2.sql"
VIEWS = REPO_ROOT / "db" / "umami_views.sql"


@pytest.fixture
def umami_db():
    """Create a fresh database, load fixture + views, yield a DSN, drop on exit."""
    base_url = os.environ["DATABASE_URL"]
    test_db = f"docket_test_umami_{os.getpid()}_{uuid.uuid4().hex[:8]}"

    # Connect to a different db so we can CREATE/DROP the test db
    admin = psycopg.connect(base_url, autocommit=True)
    try:
        admin.execute(f'DROP DATABASE IF EXISTS "{test_db}"')
        admin.execute(f'CREATE DATABASE "{test_db}"')
    finally:
        admin.close()

    test_dsn = base_url.rsplit("/", 1)[0] + "/" + test_db

    # Strip umami_reader GRANT statements from the views file — the role
    # only exists in production, and the views test doesn't need it.
    views_sql = VIEWS.read_text()
    views_sql_no_grants = "\n".join(
        ln for ln in views_sql.splitlines() if not ln.strip().startswith("GRANT")
    )

    with psycopg.connect(test_dsn) as conn:
        conn.execute(FIXTURE.read_text())
        conn.execute(views_sql_no_grants)
        conn.commit()

    yield test_dsn

    admin = psycopg.connect(base_url, autocommit=True)
    try:
        admin.execute(f'DROP DATABASE IF EXISTS "{test_db}"')
    finally:
        admin.close()


def _insert_pageview(conn, *, day_offset: int, path: str, session: str = None):
    ts = datetime.now(timezone.utc) - timedelta(days=day_offset)
    conn.execute(
        "INSERT INTO website_event (event_id, website_id, session_id, created_at, "
        "url_path, event_type, referrer_domain, country, city) "
        "VALUES (gen_random_uuid(), gen_random_uuid(), %s, %s, %s, 1, NULL, NULL, NULL)",
        (session or str(uuid.uuid4()), ts, path),
    )


def _insert_custom_event(conn, *, day_offset: int, event_name: str, props: dict):
    """Insert a custom event row + one event_data row per prop."""
    ts = datetime.now(timezone.utc) - timedelta(days=day_offset)
    event_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO website_event (event_id, website_id, session_id, created_at, "
        "url_path, event_type, event_name) "
        "VALUES (%s, gen_random_uuid(), gen_random_uuid(), %s, '/', 2, %s)",
        (event_id, ts, event_name),
    )
    for k, v in props.items():
        conn.execute(
            "INSERT INTO event_data (website_event_id, data_key, string_value) "
            "VALUES (%s, %s, %s)",
            (event_id, k, str(v)),
        )


def test_v_pageviews_daily_normalizes_meeting_ids(umami_db):
    with psycopg.connect(umami_db) as conn:
        _insert_pageview(conn, day_offset=0, path="/al/birmingham/meetings/123")
        _insert_pageview(conn, day_offset=0, path="/al/birmingham/meetings/456")
        _insert_pageview(conn, day_offset=0, path="/al/birmingham/items/789")
        conn.commit()

        rows = conn.execute(
            "SELECT normalized_path, pageviews FROM v_pageviews_daily "
            "WHERE day = current_date ORDER BY normalized_path"
        ).fetchall()

    assert rows == [
        ("/al/birmingham/items/[id]", 1),
        ("/al/birmingham/meetings/[id]", 2),
    ]


def test_v_pageviews_daily_preserves_city_and_badge_slugs(umami_db):
    with psycopg.connect(umami_db) as conn:
        _insert_pageview(conn, day_offset=0, path="/al/birmingham/")
        _insert_pageview(conn, day_offset=0, path="/al/birmingham/blight/")
        _insert_pageview(conn, day_offset=0, path="/al/mobile/zoning/")
        conn.commit()

        rows = conn.execute(
            "SELECT normalized_path FROM v_pageviews_daily "
            "WHERE day = current_date ORDER BY normalized_path"
        ).fetchall()

    paths = [r[0] for r in rows]
    assert "/al/birmingham/" in paths
    assert "/al/birmingham/blight/" in paths
    assert "/al/mobile/zoning/" in paths


def test_v_event_counts_daily_aggregates_by_name(umami_db):
    with psycopg.connect(umami_db) as conn:
        _insert_custom_event(conn, day_offset=0, event_name="rail_click",
                              props={"rail_variant": "meeting"})
        _insert_custom_event(conn, day_offset=0, event_name="rail_click",
                              props={"rail_variant": "default"})
        _insert_custom_event(conn, day_offset=0, event_name="search_submit",
                              props={"query": "zoning"})
        conn.commit()

        rows = conn.execute(
            "SELECT event_name, count FROM v_event_counts_daily "
            "WHERE day = current_date ORDER BY event_name"
        ).fetchall()

    assert rows == [("rail_click", 2), ("search_submit", 1)]


def test_v_event_props_daily_breaks_down_property_values(umami_db):
    with psycopg.connect(umami_db) as conn:
        _insert_custom_event(conn, day_offset=0, event_name="rail_click",
                              props={"rail_variant": "meeting", "source_page_type": "city"})
        _insert_custom_event(conn, day_offset=0, event_name="rail_click",
                              props={"rail_variant": "meeting", "source_page_type": "home"})
        conn.commit()

        rows = conn.execute(
            "SELECT prop_key, prop_value, count FROM v_event_props_daily "
            "WHERE day = current_date AND event_name = 'rail_click' "
            "ORDER BY prop_key, prop_value"
        ).fetchall()

    assert ("rail_variant", "meeting", 2) in rows
    assert ("source_page_type", "city", 1) in rows
    assert ("source_page_type", "home", 1) in rows
```

- [ ] **Step 2: Run integration tests, expect them to pass**

```bash
cd ~/docket-pub
venv/bin/pytest tests/integration/test_analytics_views.py -v
```

Expected: 4 PASS.

If any test fails due to column name mismatches (e.g., the fixture uses `id` not `event_id`, or `name` not `event_name`), fix `db/umami_views.sql` to match the fixture's actual schema, re-apply to production (`psql $UMAMI_DATABASE_URL -f db/umami_views.sql`), and update the test inserts.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_analytics_views.py
git commit -m "test(analytics): integration tests for umami view layer"
```

---

## Task 6: Wire `track.js` and the Umami script into `base.html`

Add the two `<script>` tags to the app shell. The website-id UUID captured during the manual phase is hardcoded (it's a public identifier).

**Files:**
- Modify: `src/docket/web/templates/base.html`

- [ ] **Step 1: Find the `</head>` insertion point**

```bash
grep -n "</head>" ~/docket-pub/src/docket/web/templates/base.html
```

Note the line number for the next step.

- [ ] **Step 2: Add the tracking + helper script tags before `</head>`**

In `src/docket/web/templates/base.html`, immediately before `</head>`, insert (replacing `<UMAMI_WEBSITE_ID>` with the UUID captured during manual setup):

```html
  {# Privacy-first analytics. Cookieless, no consent banner. #}
  {# Spec: docs/superpowers/specs/2026-05-15-umami-analytics-design.md #}
  <script defer
          src="https://stats.docket.pub/script.js"
          data-website-id="<UMAMI_WEBSITE_ID>"
          data-do-not-track="true"
          data-exclude-search="true"></script>
  <script src="{{ url_for('static', filename='js/track.js') }}" defer></script>
```

- [ ] **Step 3: Visual smoke**

Start the local dev server:

```bash
cd ~/docket-pub
flask run
```

Visit `http://localhost:5000`. Open the dev tools Network tab. Refresh.

Expected:
- `script.js` request to `stats.docket.pub` (will likely 200 in prod, may CORS-error locally — fine).
- `track.js` served from `/static/js/track.js` with 200.
- In the dev console: `typeof docketTrack === 'function'` returns `true`.
- In the dev console: `__docketTrackInternals.sanitizeProps({a: 'ok', b: 'x'.repeat(50)})` returns `{a: 'ok'}`.

- [ ] **Step 4: Commit**

```bash
git add src/docket/web/templates/base.html
git commit -m "feat(analytics): wire umami tracker + docketTrack into base.html"
```

---

## Task 7: `rail_click` event wiring

Instrument the four rail partials with `data-*` attributes, add a delegated listener in `base.html`.

**Files:**
- Modify: `src/docket/web/templates/partials/rail_default.html`
- Modify: `src/docket/web/templates/partials/rail_meeting.html`
- Modify: `src/docket/web/templates/partials/rail_member.html`
- Modify: `src/docket/web/templates/partials/source_rail.html`
- Modify: `src/docket/web/templates/base.html`

- [ ] **Step 1: Inspect current rail partials to map the existing markup**

```bash
grep -nE "<a |<li " ~/docket-pub/src/docket/web/templates/partials/rail_default.html | head -10
grep -nE "<a |<li " ~/docket-pub/src/docket/web/templates/partials/rail_meeting.html | head -10
grep -nE "<a |<li " ~/docket-pub/src/docket/web/templates/partials/rail_member.html | head -10
grep -nE "<a |<li " ~/docket-pub/src/docket/web/templates/partials/source_rail.html | head -10
```

Read each file. Identify the anchor tags that link to meetings/items/members/categories.

- [ ] **Step 2: Parameterize the rail_variant value and add tracking attrs**

The `source_rail.html` partial composes `rail_default.html` + `kpi_explainer.html`. If we hardcode `data-track-rail="default"` inside `rail_default.html`, anchors rendered via `source_rail.html` will misreport their variant. Solution: parameterize the variant via a Jinja variable that defaults to the partial's own name but can be overridden by the including partial.

**In `rail_default.html`** — at the top of the file, after the docstring/comment block, add:

```jinja
{%- set _rail_variant = rail_variant|default('default') -%}
```

Then on every anchor that targets a meeting/item/member/source-doc inside this partial, add:

- `data-track-rail="{{ _rail_variant }}"`
- `data-target-type="<type>"` — one of `meeting`, `item`, `member`, `category`, `source_doc`.
- `data-target-id="{{ ... }}"` — the numeric ID or slug from the loop variable.

**In `rail_meeting.html`** — same pattern with `'meeting'` as the default:

```jinja
{%- set _rail_variant = rail_variant|default('meeting') -%}
```

**In `rail_member.html`** — same with `'member'` as the default.

**In `source_rail.html`** — find the `{% include 'partials/rail_default.html' %}` line. Replace with:

```jinja
{% include 'partials/rail_default.html' with context %}
```

…and right before it, set the override:

```jinja
{%- set rail_variant = 'source_rail' -%}
{% include 'partials/rail_default.html' with context %}
```

(If the existing include syntax is `{% include 'partials/rail_default.html' %}` without `with context`, Jinja still inherits the parent's context by default — keep the `{% set %}` line above and the bare include works. Confirm the rendered HTML shows `data-track-rail="source_rail"` on anchors when source_rail is the wrapper.)

Example final transformation inside `rail_meeting.html` — an anchor like:

```html
<a href="{{ url_for('public.item_detail', slug=city.slug, item_id=item.id) }}">{{ item.title }}</a>
```

Becomes:

```html
<a href="{{ url_for('public.item_detail', slug=city.slug, item_id=item.id) }}"
   data-track-rail="{{ _rail_variant }}"
   data-target-type="item"
   data-target-id="{{ item.id }}">{{ item.title }}</a>
```

- [ ] **Step 3: Add the delegated listener to `base.html`**

In `src/docket/web/templates/base.html`, find the existing `<script src="{{ url_for('static', filename='js/track.js') }}" defer></script>` (added in Task 6). Add a second inline script tag immediately after it:

```html
  <script defer>
    document.addEventListener('click', function (e) {
      var a = e.target.closest('a[data-track-rail]');
      if (!a) return;
      var pageType = document.body.dataset.pageType || 'unknown';
      docketTrack('rail_click', {
        rail_variant: a.dataset.trackRail,
        source_page_type: pageType,
        target_type: a.dataset.targetType || 'unknown',
        target_id: a.dataset.targetId || '',
      });
    });
  </script>
```

- [ ] **Step 4: Add `data-page-type` to `<body>` in `base.html`**

In `base.html`, find the `<body>` tag. Replace with:

```html
<body data-page-type="{{ page_type|default('unknown') }}">
```

This lets each rendered route declare its page type (e.g., `home`, `city`, `meeting`, `item`, `category_landing`). Add `page_type` to the Jinja render context in `src/docket/web/public.py` for each route, e.g.:

```python
return render_template("index.html", page_type="home", ...)
return render_template("city.html", page_type="city", ...)
return render_template("meeting_detail.html", page_type="meeting", ...)
return render_template("item_detail.html", page_type="item", ...)
return render_template("category_landing.html", page_type="category_landing", ...)
return render_template("coverage/listing.html", page_type="coverage", ...)
return render_template("topics.html", page_type="topic", ...)
return render_template("topic_detail.html", page_type="topic", ...)
return render_template("search.html", page_type="search", ...)
return render_template("councilors.html", page_type="councilor", ...)
return render_template("council.html", page_type="councilor", ...)
```

(Pages not enumerated above keep the `'unknown'` default — `about/`, `data-debt`, admin pages, etc. Acceptable; they're not the B-priority surfaces.)

- [ ] **Step 5: Local smoke test**

```bash
flask run
```

Visit `http://localhost:5000/`. Open the dev console. Click a rail link. Run in console:

```javascript
// Override umami.track temporarily to capture calls
window.umami = { track: function (name, props) { console.log('TRACK', name, props); } };
```

Then click another rail link. Expected console output:

```
TRACK rail_click {rail_variant: "default", source_page_type: "home", target_type: "meeting", target_id: "..."}
```

- [ ] **Step 6: Commit**

```bash
git add src/docket/web/templates/partials/rail_*.html src/docket/web/templates/partials/source_rail.html src/docket/web/templates/base.html src/docket/web/public.py
git commit -m "feat(analytics): rail_click event + per-route page_type"
```

---

## Task 8: `outbound_source_click` event wiring

Delegated listener on all `a[href]` that target external hosts. Classification by URL pattern lives in `track.js`.

**Files:**
- Modify: `src/docket/web/static/js/track.js`
- Modify: `src/docket/web/templates/base.html`

- [ ] **Step 1: Add the classifier to `track.js`**

Append to `src/docket/web/static/js/track.js`, inside the existing IIFE (before the closing `})();`):

```javascript
  /* Classify an outbound URL into a source_type.
   * Returns null when the URL is internal (same host) or unrecognized.
   * The four classifications match the spec's v1 outbound_source_click property.
   */
  function classifyOutbound(url) {
    var u;
    try {
      u = new URL(url, window.location.href);
    } catch (e) {
      return null;
    }
    if (u.hostname === window.location.hostname) return null;
    var host = u.hostname.toLowerCase();
    var path = u.pathname.toLowerCase();

    if (host.indexOf('granicus.com') !== -1) return 'granicus_video';
    if (path.endsWith('.pdf')) {
      if (path.indexOf('minute') !== -1) return 'minutes_pdf';
      if (path.indexOf('agenda') !== -1) return 'agenda_pdf';
      return 'agenda_pdf';  // PDFs on city sites default to agenda_pdf
    }
    // Known Alabama city/government hostnames map to city_site.
    var cityHosts = [
      'birminghamal.gov', 'cityofvestavia.com', 'cityofhomewood.com',
      'mobile.org', 'cityofmobile.org', 'hooveralabama.gov',
      'montgomeryal.gov',
    ];
    for (var i = 0; i < cityHosts.length; i++) {
      if (host === cityHosts[i] || host.endsWith('.' + cityHosts[i])) return 'city_site';
    }
    return 'other';
  }

  window.__docketTrackInternals.classifyOutbound = classifyOutbound;
```

- [ ] **Step 2: Add the delegated listener to `base.html`**

In `src/docket/web/templates/base.html`, append a third inline script after the rail_click listener:

```html
  <script defer>
    document.addEventListener('click', function (e) {
      var a = e.target.closest('a[href]');
      if (!a) return;
      var src = window.__docketTrackInternals.classifyOutbound(a.href);
      if (!src) return;
      var props = { source_type: src };
      try {
        props.target_domain = new URL(a.href, window.location.href).hostname;
      } catch (err) {}
      if (a.dataset.itemId) props.item_id = a.dataset.itemId;
      if (a.dataset.meetingId) props.meeting_id = a.dataset.meetingId;
      docketTrack('outbound_source_click', props);
    });
  </script>
```

- [ ] **Step 3: Ensure source-anchor templates carry `data-item-id` / `data-meeting-id`**

Open `src/docket/web/templates/partials/source_anchor_button.html`. For each `<a ... class="view-source"` anchor (lines 90, 95, 100, 107, 113, 119 per the current file), append `data-item-id="{{ item.id }}"` where `item` is in scope. If the partial is used in a meeting context (no `item`), pass `meeting_id` from the caller and emit `data-meeting-id="{{ meeting_id }}"` instead.

Confirm by re-grepping after the edit:

```bash
grep -nE 'class="view-source"' ~/docket-pub/src/docket/web/templates/partials/source_anchor_button.html
```

Every match should have either `data-item-id` or `data-meeting-id` on it.

- [ ] **Step 4: Local smoke test**

```bash
flask run
```

Visit a meeting page with a "View source" link. With the console-override pattern from Task 7 Step 5, click the link (use middle-click to prevent navigation). Expected console output:

```
TRACK outbound_source_click {source_type: "granicus_video", target_domain: "bhamal.granicus.com", item_id: "..."}
```

Sanity-check internal-link non-firing: click an in-app link (e.g., "Meetings" in the nav). Expected: no `outbound_source_click` call.

- [ ] **Step 5: Commit**

```bash
git add src/docket/web/static/js/track.js src/docket/web/templates/base.html src/docket/web/templates/partials/source_anchor_button.html
git commit -m "feat(analytics): outbound_source_click event with domain classifier"
```

---

## Task 9: `search_submit` event wiring

One-shot emit from the search-results page using server-rendered values.

**Files:**
- Modify: `src/docket/web/templates/search.html`
- Reference: `src/docket/web/public.py` search route

- [ ] **Step 1: Verify the search route's render context**

```bash
grep -nA 15 "def search" ~/docket-pub/src/docket/web/public.py | head -40
```

Confirm the route exposes `query` (string) and `results` (list) — or whatever names are used. Note the variable names for use in the template.

- [ ] **Step 2: Add the emit script to `search.html`**

In `src/docket/web/templates/search.html`, add at the very bottom of the file (or in a `{% block scripts %}` block if `base.html` defines one):

```html
{% if query %}
<script>
  // Fired on the server-rendered results page; values come from the request.
  (function () {
    if (typeof docketTrack !== 'function') return;
    var props = {
      query: {{ query | tojson }},
      result_count: {{ (results | length) if results is defined else 0 }},
    };
    {% if city is defined and city %}
    props.city = {{ city.slug | tojson }};
    {% endif %}
    docketTrack('search_submit', props);
  })();
</script>
{% endif %}
```

(Adjust `query`, `results`, and `city` variable names to match what the route actually passes — verified in Step 1.)

- [ ] **Step 3: Local smoke test**

```bash
flask run
```

Visit `http://localhost:5000/search?q=zoning`. With the console-override pattern:

```javascript
window.umami = { track: function (n, p) { console.log('TRACK', n, p); } };
location.reload();
```

Expected console output:

```
TRACK search_submit {query: "zoning", result_count: <N>}
```

Then test the PII drop:

```
http://localhost:5000/search?q=1234%20Maple%20Street%20Birmingham%20AL%2035203
```

Expected console output (note `query` is *dropped* by `sanitizeProps`, `result_count` still present):

```
TRACK search_submit {result_count: <N>}
```

- [ ] **Step 4: Commit**

```bash
git add src/docket/web/templates/search.html
git commit -m "feat(analytics): search_submit event from results page"
```

---

## Task 10: Public stats page link in footer

Surface the Umami public-share URL as an on-brand transparency artifact.

**Files:**
- Modify: `src/docket/web/templates/partials/footer.html`
- Modify: `src/docket/web/templates/about.html` (or `about/index.html` if that's the layout)

- [ ] **Step 1: Add the footer link**

Open `src/docket/web/templates/partials/footer.html`. Find the existing link list (whatever class/structure it uses). Add a new list item:

```html
<li><a href="<UMAMI_PUBLIC_SHARE_URL>" rel="external" target="_blank">Site usage</a></li>
```

Replace `<UMAMI_PUBLIC_SHARE_URL>` with the share URL captured during manual setup (looks like `https://stats.docket.pub/share/abc123def/docket.pub`).

- [ ] **Step 2: Add a longer-form paragraph to `about.html`**

Open `src/docket/web/templates/about.html`. Find a natural insertion point (e.g., after the methodology section, or in a sidebar). Add:

```html
<section>
  <h2>How we measure traffic</h2>
  <p>
    docket.pub uses a cookieless, self-hosted analytics tracker. We don't
    track you across sites and we don't set any cookies or localStorage IDs.
    The tracker stores only aggregated pageview counts and three custom
    interaction events (rail clicks, outbound source clicks, search
    submissions). The dashboard is
    <a href="<UMAMI_PUBLIC_SHARE_URL>" rel="external" target="_blank">publicly readable</a>
    — anyone can see what's read on docket.pub.
  </p>
</section>
```

- [ ] **Step 3: Local smoke**

```bash
flask run
```

Visit `http://localhost:5000/`. Confirm the footer "Site usage" link appears and opens the share URL in a new tab.

Visit `http://localhost:5000/about/`. Confirm the new paragraph renders cleanly.

- [ ] **Step 4: Commit**

```bash
git add src/docket/web/templates/partials/footer.html src/docket/web/templates/about.html
git commit -m "feat(analytics): public stats link in footer and about page"
```

---

## Task 11: Analytics queries cheat sheet

The reference doc for ad-hoc Claude-driven analytics queries.

**Files:**
- Create: `docs/analytics-queries.md`

- [ ] **Step 1: Write the cheat sheet**

Create `docs/analytics-queries.md`:

```markdown
# Analytics Query Cheat Sheet

Reference for querying the Umami analytics database. **Never query raw Umami tables (`website_event`, `event_data`, `session`) — only the views below.** The view layer absorbs Umami's schema evolution; raw tables can break between Umami releases.

## Connecting

Read-only credentials live in `~/.docket-pub.env.local`:

```bash
source ~/.docket-pub.env.local
/opt/homebrew/opt/postgresql@18/bin/psql "$UMAMI_READER_URL"
```

The `umami_reader` role has `SELECT` only on the five `v_*` views below — no raw-table access.

## Views

| View | Grain (one row per...) | Columns |
|---|---|---|
| `v_pageviews_daily` | `(day, normalized_path)` | `day date`, `normalized_path text`, `pageviews int`, `sessions int` |
| `v_event_counts_daily` | `(day, event_name)` | `day date`, `event_name text`, `count int`, `sessions int` |
| `v_event_props_daily` | `(day, event_name, prop_key, prop_value)` | `day date`, `event_name text`, `prop_key text`, `prop_value text`, `count int` |
| `v_referrers_daily` | `(day, referrer_domain)` | `day date`, `referrer_domain text`, `pageviews int` |
| `v_geo_daily` | `(day, country, city)` | `day date`, `country text`, `city text`, `pageviews int`, `sessions int` |

## Path normalization

Numeric IDs collapse (`/al/birmingham/meetings/123` → `/al/birmingham/meetings/[id]`). City slugs and badge slugs are preserved because they ARE the dimensions we care about. Full normalization rules are in `db/umami_views.sql`.

## Common patterns

### Top pages last 7 days

```sql
SELECT normalized_path, SUM(pageviews) AS views, SUM(sessions) AS sessions
FROM v_pageviews_daily
WHERE day >= current_date - 7
GROUP BY 1
ORDER BY 2 DESC
LIMIT 20;
```

### Rail variant performance (the B-priority question)

**Default aggregation grain is `rail_variant × source_page_type`.** `target_id` is high-cardinality — use it only when investigating a specific entity, not as a default grouping.

```sql
SELECT
  rv.prop_value AS rail_variant,
  sp.prop_value AS source_page_type,
  COUNT(*) AS clicks
FROM v_event_props_daily rv
JOIN v_event_props_daily sp USING (day, event_name)
WHERE rv.event_name = 'rail_click'
  AND rv.prop_key = 'rail_variant'
  AND sp.prop_key = 'source_page_type'
  AND rv.day >= current_date - 14
GROUP BY 1, 2
ORDER BY 3 DESC;
```

(For more precise per-click joining than this prop-by-prop summing, you'd need to widen the view layer to surface `event_id` — fine to add later; not needed for v1 rollup questions.)

### Zero-result searches (editorial roadmap)

```sql
SELECT q.prop_value AS query, COUNT(*) AS attempts
FROM v_event_props_daily q
JOIN v_event_props_daily r USING (day, event_name)
WHERE q.event_name = 'search_submit'
  AND q.prop_key = 'query'
  AND r.prop_key = 'result_count'
  AND r.prop_value = '0'
  AND q.day >= current_date - 30
GROUP BY 1
ORDER BY 2 DESC
LIMIT 30;
```

Note: queries longer than 40 characters are *dropped* at the client before sending (PII guardrail). `result_count` is still recorded, so the zero-result *rate* across all searches is queryable via `v_event_counts_daily` joined to the `result_count='0'` slice.

### Outbound source clicks (civic mission signal)

```sql
SELECT prop_value AS source_type, COUNT(*) AS clicks
FROM v_event_props_daily
WHERE event_name = 'outbound_source_click'
  AND prop_key = 'source_type'
  AND day >= current_date - 30
GROUP BY 1
ORDER BY 2 DESC;
```

### Civic geo signal (which cities are reading)

```sql
SELECT city, SUM(pageviews) AS views, SUM(sessions) AS sessions
FROM v_geo_daily
WHERE country = 'US'
  AND day >= current_date - 30
GROUP BY 1
ORDER BY 2 DESC
LIMIT 25;
```

### Referrer breakdown

```sql
SELECT referrer_domain, SUM(pageviews) AS views
FROM v_referrers_daily
WHERE day >= current_date - 14
GROUP BY 1
ORDER BY 2 DESC
LIMIT 20;
```

## Versioning

- View definitions live in `db/umami_views.sql` (single source of truth).
- Umami version is pinned in the `analytics` Railway service config.
- When Umami releases a breaking schema change, the integration test (`tests/integration/test_analytics_views.py`) catches it. Fix is one PR to `db/umami_views.sql`; consumers don't move.
```

- [ ] **Step 2: Commit**

```bash
git add docs/analytics-queries.md
git commit -m "docs(analytics): query cheat sheet for view layer"
```

---

## Task 12: `CLAUDE.md` agentic pointer

Tell Claude where the analytics data lives and how to query it.

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the pointer block**

Open `CLAUDE.md`. Find the "Workflow notes" or "Conventions" section. Add a new bullet block (location is judgment — pick the section that matches the rest of the cross-references to runbooks):

```markdown
- **Analytics (Umami)**: pageviews + 3 custom events live in the `umami` database on the existing Railway Postgres instance. Query via the read-only `umami_reader` role with credentials in `~/.docket-pub.env.local` (set `UMAMI_READER_URL`). See `docs/analytics-queries.md` for view schemas and common query patterns. **Never query raw Umami tables — only the `v_*` views.** Schema fixture lives at `tests/fixtures/umami_schema_v2.sql`; regenerate only on Umami version bumps (procedure in `docs/runbooks/analytics.md`).
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): point at umami analytics views and runbook"
```

---

## Final verification

After all 12 tasks are committed, run the full smoke-test sequence:

- [ ] **Step 1: Run the test suite**

```bash
cd ~/docket-pub
venv/bin/pytest tests/unit/test_worker_tasks_prune_analytics.py tests/integration/test_analytics_views.py -v
```

Expected: 6 tests pass (2 unit + 4 integration).

- [ ] **Step 2: Run the full test suite to catch regressions**

```bash
venv/bin/pytest -x --tb=short
```

Expected: pre-existing tests continue to pass. Stop on the first failure for diagnosis.

- [ ] **Step 3: Deploy to Railway**

```bash
cd ~/docket-pub
git status                # confirm clean
git log --oneline -15    # confirm the 12 task commits
railway up --detach      # deploys docket-web with migrations runner first
railway up --service worker --detach   # deploys worker with the new prune_analytics job
```

- [ ] **Step 4: Production smoke**

Hit `https://docket.pub/` in a browser. Open dev tools Network tab. Confirm:
- `script.js` from `stats.docket.pub` returns 200.
- `track.js` from `docket.pub/static/js/track.js` returns 200.
- Console: `typeof docketTrack === 'function'` returns `true`.

Click a rail link, then a "View source" link, then perform a search. After ~30 seconds (Umami's ingest delay):

```bash
source ~/.docket-pub.env.local
/opt/homebrew/opt/postgresql@18/bin/psql "$UMAMI_READER_URL" -c \
  "SELECT event_name, count FROM v_event_counts_daily WHERE day = current_date;"
```

Expected: rows for `rail_click`, `outbound_source_click`, `search_submit`.

- [ ] **Step 5: Worker dry-run for `prune_analytics`**

```bash
railway ssh --service worker
# inside container:
cd /app && python -m docket.worker.scheduler --run-once prune_analytics
```

Expected: log line `prune_analytics deleted=0` (no events older than 24 months yet). Healthchecks dashboard shows the start/success pings.

- [ ] **Step 6: Final memory update**

Save a project memory recording the ship: file `~/.claude-personal/projects/-Users-darrellnance/memory/project_umami_analytics_shipped.md` with the date, the website-id (if comfortable storing in memory; it's public anyway), and a one-line summary. Add to `MEMORY.md`.

---

## Plan Notes

**Why no migration:** Umami's tables live in their own database (`umami`). The docket schema is untouched. No `docket.migrations` work required.

**Why the integration test waits for the fixture:** the fixture is the captured output of Umami's first-boot schema initialization. We could try to extract it from the Prisma source, but that requires a Node toolchain at test time. A static fixture, regenerated only on deliberate Umami version bumps, is simpler and version-locks the test.

**Why `page_type` is set in Python, not detected from the URL:** route → page-type is one mapping; URL-pattern matching is two. Setting it explicitly in `render_template` is one trivially-greppable line per route and survives URL refactors.

**Manual phase isolation:** Tasks 1–4 ship code that doesn't *do* anything until manual phase happens. This is intentional — the operator can review and merge the foundation PRs at their pace, then book a focused window for the Railway/DNS/admin manual work, then continue with Tasks 5–12.

**Rollback:** removing the two `<script>` tags from `base.html` and redeploying disables all tracking cleanly (the prune task and view layer are independent, harmless if left in place). For a full teardown: drop the `analytics` Railway service, drop the `umami` database, remove the related env vars from `worker`.
