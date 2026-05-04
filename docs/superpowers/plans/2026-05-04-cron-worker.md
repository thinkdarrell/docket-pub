# Cron Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a Railway `worker` service that runs APScheduler with five scheduled tasks (ingest, AI items, AI meetings, vote matching, weekly empty-agenda repair), monitored via Healthchecks.io heartbeats.

**Architecture:** A new `src/docket/worker/` package containing a `BlockingScheduler` entry point (`scheduler.py`), task wrappers that call existing services (`tasks.py`), and a Healthchecks.io ping helper (`health.py`). One new service module (`src/docket/services/maintenance.py`) implements the empty-agenda repair logic. The worker has zero new business logic — it is a scheduler that calls existing entry points (`ingest_municipality`, `docket.ai.worker.run_once`, `match_all_unmatched`).

**Tech Stack:** Python 3.10+, APScheduler 3.10+, Healthchecks.io (free tier), Railway (Procfile-driven worker process), pytest.

**Spec:** `docs/superpowers/specs/2026-05-04-cron-worker-design.md`

---

## File Structure

**Create:**
- `src/docket/worker/__init__.py` — package marker (empty)
- `src/docket/worker/health.py` — Healthchecks.io ping helper (~40 LOC)
- `src/docket/worker/tasks.py` — five task functions + `_safe_run` wrapper (~80 LOC)
- `src/docket/worker/scheduler.py` — `build_scheduler()`, `run_once_task()`, `main()` (~80 LOC)
- `src/docket/services/maintenance.py` — `repair_empty_agendas()` (~25 LOC)
- `tests/unit/test_worker_health.py` — health helper tests
- `tests/unit/test_worker_tasks.py` — task wrapper tests with mocks
- `tests/unit/test_worker_scheduler.py` — scheduler construction + dispatch tests
- `tests/integration/test_maintenance_repair.py` — end-to-end DB test for `repair_empty_agendas`

**Modify:**
- `requirements.txt` — add `apscheduler>=3.10`
- `Procfile` — add `worker:` line

**Touch:** none (no existing source modified)

---

## Task 1: Add APScheduler Dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1.1: Add the dependency**

Append to `requirements.txt`:

```
apscheduler>=3.10
```

- [ ] **Step 1.2: Install into the venv**

Run: `cd ~/docket-pub && venv/bin/pip install -r requirements.txt`
Expected: `Successfully installed APScheduler-3.x.y` (or "already satisfied")

- [ ] **Step 1.3: Verify import works**

Run: `venv/bin/python -c "from apscheduler.schedulers.blocking import BlockingScheduler; print('ok')"`
Expected: `ok`

- [ ] **Step 1.4: Commit**

```bash
git add requirements.txt
git commit -m "chore(deps): add apscheduler for cron worker"
```

---

## Task 2: Healthchecks Ping Helper

**Files:**
- Create: `src/docket/worker/__init__.py`
- Create: `src/docket/worker/health.py`
- Create: `tests/unit/test_worker_health.py`

- [ ] **Step 2.1: Create the package marker**

`src/docket/worker/__init__.py`:

```python
"""Scheduled cron worker — APScheduler-driven tasks that wrap existing services."""
```

- [ ] **Step 2.2: Write failing tests for `ping()`**

Create `tests/unit/test_worker_health.py`:

```python
"""Tests for the Healthchecks.io ping helper."""

from unittest.mock import patch

import pytest

from docket.worker import health


def test_ping_no_uuid_is_noop(monkeypatch):
    """ping() must return silently when the UUID env var is unset."""
    monkeypatch.delenv("HEALTHCHECK_INGEST_UUID", raising=False)
    with patch("docket.worker.health.requests.post") as mock_post:
        health.ping("ingest_all", "success")
    mock_post.assert_not_called()


def test_ping_unknown_task_raises_keyerror():
    """An unknown task name is a programmer error, not a runtime input."""
    with pytest.raises(KeyError):
        health.ping("not_a_real_task", "success")


@pytest.mark.parametrize("status,suffix", [
    ("start",   "/start"),
    ("success", ""),
    ("fail",    "/fail"),
])
def test_ping_builds_correct_url(monkeypatch, status, suffix):
    monkeypatch.setenv("HEALTHCHECK_INGEST_UUID", "abc-123")
    with patch("docket.worker.health.requests.post") as mock_post:
        health.ping("ingest_all", status)
    expected = f"https://hc-ping.com/abc-123{suffix}"
    mock_post.assert_called_once()
    assert mock_post.call_args.args[0] == expected


def test_ping_includes_body(monkeypatch):
    monkeypatch.setenv("HEALTHCHECK_INGEST_UUID", "abc-123")
    with patch("docket.worker.health.requests.post") as mock_post:
        health.ping("ingest_all", "fail", body="traceback here")
    assert mock_post.call_args.kwargs["data"] == b"traceback here"


def test_ping_swallows_network_errors(monkeypatch, caplog):
    """A network blip must not crash the worker, but should log a warning."""
    monkeypatch.setenv("HEALTHCHECK_INGEST_UUID", "abc-123")
    with patch("docket.worker.health.requests.post",
               side_effect=ConnectionError("nope")):
        health.ping("ingest_all", "success")  # must not raise
    assert any("healthcheck ping failed" in r.message for r in caplog.records)
```

- [ ] **Step 2.3: Run tests to confirm they fail**

Run: `cd ~/docket-pub && venv/bin/pytest tests/unit/test_worker_health.py -v`
Expected: All 5 tests FAIL with `ModuleNotFoundError: No module named 'docket.worker.health'`

- [ ] **Step 2.4: Implement `health.py`**

Create `src/docket/worker/health.py`:

```python
"""Healthchecks.io ping helper for the cron worker.

One UUID per task lives in env vars; the helper is a no-op when the
corresponding UUID is missing, so dev/local runs don't need any setup.
"""

from __future__ import annotations

import logging
import os
from typing import Literal

import requests

log = logging.getLogger(__name__)

HEALTHCHECK_BASE = "https://hc-ping.com"

# Task name → env var name. Unknown task names are a programmer error.
TASK_UUID_ENV: dict[str, str] = {
    "ingest_all":           "HEALTHCHECK_INGEST_UUID",
    "ai_items":             "HEALTHCHECK_AI_ITEMS_UUID",
    "ai_meetings":          "HEALTHCHECK_AI_MEETINGS_UUID",
    "vote_matching":        "HEALTHCHECK_VOTE_MATCH_UUID",
    "repair_empty_agendas": "HEALTHCHECK_REPAIR_UUID",
}

PingStatus = Literal["start", "success", "fail"]


def ping(task: str, status: PingStatus, body: str | None = None) -> None:
    """Ping Healthchecks.io for a task lifecycle event.

    No-ops when the task's UUID env var is unset (e.g., local dev).
    Network errors are logged at WARNING and swallowed — the worker must
    never crash because the monitoring endpoint is unreachable.
    """
    env_var = TASK_UUID_ENV[task]  # KeyError on unknown task — intentional
    uuid = os.environ.get(env_var)
    if not uuid:
        return

    url = f"{HEALTHCHECK_BASE}/{uuid}"
    if status == "start":
        url += "/start"
    elif status == "fail":
        url += "/fail"

    try:
        requests.post(url, data=(body or "").encode("utf-8"), timeout=10)
    except Exception as e:
        # A network blip to Healthchecks.io shouldn't crash the worker, but it
        # should be visible in Railway logs so an operator doesn't mistake
        # "no ping arrived" for "the job didn't run."
        log.warning("healthcheck ping failed task=%s status=%s err=%s", task, status, e)
```

- [ ] **Step 2.5: Run tests to confirm they pass**

Run: `venv/bin/pytest tests/unit/test_worker_health.py -v`
Expected: 5 passed

- [ ] **Step 2.6: Commit**

```bash
git add src/docket/worker/__init__.py src/docket/worker/health.py tests/unit/test_worker_health.py
git commit -m "feat(worker): healthchecks.io ping helper"
```

---

## Task 3: `repair_empty_agendas` Maintenance Service

**Files:**
- Create: `src/docket/services/maintenance.py`
- Create: `tests/integration/test_maintenance_repair.py`

- [ ] **Step 3.1: Write failing integration test**

Create `tests/integration/test_maintenance_repair.py`:

```python
"""Integration tests for repair_empty_agendas.

These tests seed real municipality + meeting + processing_status rows,
run the repair service, and assert state — same pattern as the existing
test_ai_pipeline_e2e.py fixtures.
"""

from datetime import date, timedelta

import pytest

from docket.db import db
from docket.services.maintenance import repair_empty_agendas


@pytest.fixture
def seeded_repair():
    """Seed a test municipality and a mix of meetings exercising every branch."""
    state: dict = {}
    with db() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO municipalities (slug, name, state, adapter_class, active)
            VALUES ('test_repair', 'Test Repair', 'AL', 'granicus', TRUE)
            ON CONFLICT (slug) DO UPDATE SET active = TRUE
            RETURNING id
        """)
        muni_id = cur.fetchone()[0]
        state["muni_id"] = muni_id

        # Helper to insert a meeting + processing_status in one go.
        def mk(title: str, *, days_ago: int, has_agenda_url: bool,
               agenda_scraped: bool, with_items: int) -> int:
            cur.execute("""
                INSERT INTO meetings (municipality_id, meeting_type, meeting_date,
                                       source_url, title, agenda_url)
                VALUES (%s, 'Council', %s, 'x', %s, %s) RETURNING id
            """, (muni_id, date.today() - timedelta(days=days_ago),
                   title, "http://x" if has_agenda_url else None))
            m_id = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO processing_status (meeting_id, agenda_items_scraped, last_processed)
                VALUES (%s, %s, NOW())
            """, (m_id, agenda_scraped))
            for i in range(with_items):
                cur.execute("""
                    INSERT INTO agenda_items (meeting_id, title)
                    VALUES (%s, %s)
                """, (m_id, f"item {i}"))
            return m_id

        state["repair_target"]      = mk("Regular Meeting",          days_ago=10,    has_agenda_url=True,  agenda_scraped=True,  with_items=0)
        state["cancelled"]          = mk("Regular Meeting Cancelled", days_ago=12,    has_agenda_url=True,  agenda_scraped=True,  with_items=0)
        state["has_items"]          = mk("Regular Meeting",          days_ago=14,    has_agenda_url=True,  agenda_scraped=True,  with_items=3)
        state["no_agenda_url"]      = mk("Special Meeting",          days_ago=16,    has_agenda_url=False, agenda_scraped=True,  with_items=0)
        state["outside_window"]     = mk("Old Meeting",              days_ago=600,   has_agenda_url=True,  agenda_scraped=True,  with_items=0)
        state["already_unscraped"]  = mk("Pending Meeting",          days_ago=18,    has_agenda_url=True,  agenda_scraped=False, with_items=0)
        conn.commit()

    yield state

    # Teardown — relies on FK CASCADE from municipalities → meetings → ...
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM municipalities WHERE id = %s", (state["muni_id"],))
        conn.commit()


def _scraped_flag(meeting_id: int) -> bool:
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT agenda_items_scraped FROM processing_status WHERE meeting_id = %s",
                    (meeting_id,))
        return cur.fetchone()[0]


def test_repair_clears_target_meeting(seeded_repair):
    """A meeting with agenda_url, no items, scraped=TRUE, in window → cleared."""
    cleared = repair_empty_agendas()
    assert cleared >= 1  # other test data may exist; we only assert ours
    assert _scraped_flag(seeded_repair["repair_target"]) is False


def test_repair_skips_cancelled_meetings(seeded_repair):
    repair_empty_agendas()
    assert _scraped_flag(seeded_repair["cancelled"]) is True


def test_repair_skips_meetings_with_items(seeded_repair):
    repair_empty_agendas()
    assert _scraped_flag(seeded_repair["has_items"]) is True


def test_repair_skips_meetings_without_agenda_url(seeded_repair):
    repair_empty_agendas()
    assert _scraped_flag(seeded_repair["no_agenda_url"]) is True


def test_repair_only_within_18_month_window(seeded_repair):
    repair_empty_agendas()
    assert _scraped_flag(seeded_repair["outside_window"]) is True


def test_repair_leaves_already_unscraped_alone(seeded_repair):
    """Idempotent: meetings whose flag is already FALSE shouldn't be 'cleared' again."""
    repair_empty_agendas()
    assert _scraped_flag(seeded_repair["already_unscraped"]) is False
```

- [ ] **Step 3.2: Run tests to confirm they fail**

Run: `venv/bin/pytest tests/integration/test_maintenance_repair.py -v`
Expected: All tests FAIL with `ModuleNotFoundError: No module named 'docket.services.maintenance'`

- [ ] **Step 3.3: Implement `maintenance.py`**

Create `src/docket/services/maintenance.py`:

```python
"""Periodic maintenance / repair operations called from the cron worker."""

from __future__ import annotations

import logging

from docket.db import db

log = logging.getLogger(__name__)


def repair_empty_agendas() -> int:
    """Reset agenda_items_scraped for meetings that ended up with zero items.

    Targets meetings within the last 18 months that have an agenda_url, were
    flagged scraped, but have no agenda_items rows. Skips cancelled meetings
    (title matches /cancell?ed/i) since those legitimately have no agenda.

    The next ingest run will re-fetch whatever this clears.

    Returns:
        Number of meetings whose flag was cleared.
    """
    with db() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE processing_status ps
               SET agenda_items_scraped = FALSE
              FROM meetings m
             WHERE ps.meeting_id = m.id
               AND m.agenda_url IS NOT NULL
               AND m.meeting_date >= CURRENT_DATE - INTERVAL '18 months'
               AND ps.agenda_items_scraped = TRUE
               AND m.title !~* 'cancell?ed'
               AND NOT EXISTS (
                   SELECT 1 FROM agenda_items ai WHERE ai.meeting_id = m.id
               )
        """)
        cleared = cur.rowcount
        conn.commit()
    log.info("repair_empty_agendas cleared=%d", cleared)
    return cleared
```

- [ ] **Step 3.4: Run tests to confirm they pass**

Run: `venv/bin/pytest tests/integration/test_maintenance_repair.py -v`
Expected: 6 passed

- [ ] **Step 3.5: Commit**

```bash
git add src/docket/services/maintenance.py tests/integration/test_maintenance_repair.py
git commit -m "feat(services): repair_empty_agendas maintenance helper"
```

---

## Task 4: Task Wrappers (`tasks.py`)

**Files:**
- Create: `src/docket/worker/tasks.py`
- Create: `tests/unit/test_worker_tasks.py`

- [ ] **Step 4.1: Write failing tests**

Create `tests/unit/test_worker_tasks.py`:

```python
"""Tests for the cron worker task wrappers."""

from unittest.mock import patch, MagicMock

import pytest

from docket.worker import tasks


# --- _safe_run ---------------------------------------------------------------

def test_safe_run_pings_start_then_success_on_clean_run():
    inner = MagicMock()
    with patch("docket.worker.tasks.health.ping") as mock_ping:
        tasks._safe_run("ingest_all", inner)
    inner.assert_called_once_with()
    statuses = [c.args[1] for c in mock_ping.call_args_list]
    assert statuses == ["start", "success"]


def test_safe_run_pings_fail_with_traceback_on_exception():
    def boom():
        raise ValueError("kaboom")

    with patch("docket.worker.tasks.health.ping") as mock_ping:
        tasks._safe_run("ingest_all", boom)  # must not raise

    statuses = [c.args[1] for c in mock_ping.call_args_list]
    assert statuses == ["start", "fail"]
    fail_call = mock_ping.call_args_list[-1]
    assert "ValueError" in fail_call.kwargs["body"]
    assert "kaboom" in fail_call.kwargs["body"]


def test_safe_run_does_not_re_raise():
    """APScheduler's default error logging is noisy; we own error reporting via Healthchecks."""
    def boom():
        raise RuntimeError("nope")

    with patch("docket.worker.tasks.health.ping"):
        # The assertion is "this line returns" — i.e. no exception escapes _safe_run.
        result = tasks._safe_run("ingest_all", boom)
    assert result is None


# --- task_ingest_all ---------------------------------------------------------

def test_ingest_all_loops_active_municipalities():
    fake_rows = [{"slug": "birmingham"}, {"slug": "mobile"}]
    fake_cursor = MagicMock()
    fake_cursor.__enter__ = MagicMock(return_value=fake_cursor)
    fake_cursor.__exit__ = MagicMock(return_value=False)
    fake_cursor.fetchall.return_value = fake_rows

    with patch("docket.worker.tasks.db_cursor", return_value=fake_cursor), \
         patch("docket.worker.tasks.ingest_municipality") as mock_ingest:
        tasks._do_ingest_all()

    assert mock_ingest.call_args_list[0].args == ("birmingham",)
    assert mock_ingest.call_args_list[1].args == ("mobile",)


def test_ingest_all_continues_on_per_city_failure():
    """If Birmingham fails, Mobile should still get a chance."""
    fake_cursor = MagicMock()
    fake_cursor.__enter__ = MagicMock(return_value=fake_cursor)
    fake_cursor.__exit__ = MagicMock(return_value=False)
    fake_cursor.fetchall.return_value = [{"slug": "birmingham"}, {"slug": "mobile"}]

    def maybe_fail(slug):
        if slug == "birmingham":
            raise RuntimeError("bham broke")

    with patch("docket.worker.tasks.db_cursor", return_value=fake_cursor), \
         patch("docket.worker.tasks.ingest_municipality", side_effect=maybe_fail) as mock_ingest:
        tasks._do_ingest_all()  # must not raise

    assert mock_ingest.call_count == 2


# --- task wrappers call into the right service -------------------------------

def test_ai_items_invokes_run_once_with_items_stage():
    with patch("docket.worker.tasks.run_once") as mock_run:
        tasks._do_ai_items()
    assert mock_run.call_args.kwargs["stage"] == "items"
    assert mock_run.call_args.kwargs["limit"] == 200
    assert mock_run.call_args.kwargs["notes"] == "cron_items"


def test_ai_meetings_invokes_run_once_with_meetings_stage():
    with patch("docket.worker.tasks.run_once") as mock_run:
        tasks._do_ai_meetings()
    assert mock_run.call_args.kwargs["stage"] == "meetings"
    assert mock_run.call_args.kwargs["limit"] == 50
    assert mock_run.call_args.kwargs["notes"] == "cron_meetings"


def test_ai_items_swallows_budget_exceeded():
    """BudgetExceededError is expected behavior, not a failure for Healthchecks."""
    from docket.ai.worker import BudgetExceededError
    with patch("docket.worker.tasks.run_once",
               side_effect=BudgetExceededError("over cap")):
        tasks._do_ai_items()  # must not raise


def test_vote_matching_invokes_match_all_unmatched():
    with patch("docket.worker.tasks.match_all_unmatched") as mock_match:
        mock_match.return_value = {
            "meetings": 1, "timestamp_matched": 0,
            "substantive_matched": 2, "consent_matched": 5,
        }
        tasks._do_vote_matching()
    mock_match.assert_called_once()


def test_repair_invokes_repair_empty_agendas():
    with patch("docket.worker.tasks.repair_empty_agendas") as mock_repair:
        mock_repair.return_value = 3
        tasks._do_repair_empty_agendas()
    mock_repair.assert_called_once()


# --- TASKS registry ----------------------------------------------------------

def test_tasks_registry_has_all_five_jobs():
    expected = {"ingest_all", "ai_items", "ai_meetings", "vote_matching", "repair_empty_agendas"}
    assert set(tasks.TASKS.keys()) == expected
```

- [ ] **Step 4.2: Run tests to confirm they fail**

Run: `venv/bin/pytest tests/unit/test_worker_tasks.py -v`
Expected: All FAIL with `ModuleNotFoundError: No module named 'docket.worker.tasks'`

- [ ] **Step 4.3: Implement `tasks.py`**

Create `src/docket/worker/tasks.py`:

```python
"""Task functions for the cron worker.

Each public task entry point is wrapped via _safe_run, which handles
Healthchecks pings and exception swallowing. The internal _do_* helpers
contain the actual work and are unit-tested directly.

Tasks intentionally call existing services and keep no business logic
of their own. The worker is a scheduler; ingest, AI, and matching
modules do the work.
"""

from __future__ import annotations

import logging
import traceback
from typing import Callable

from docket.ai.worker import BudgetExceededError, run_once
from docket.analysis.vote_matcher import match_all_unmatched
from docket.db import db_cursor
from docket.services.ingest import ingest_municipality
from docket.services.maintenance import repair_empty_agendas
from docket.worker import health

log = logging.getLogger(__name__)


def _safe_run(task_name: str, fn: Callable[[], None]) -> None:
    """Run a task with Healthchecks pings, catching exceptions.

    Does not re-raise. APScheduler's built-in error logging is noisy and
    duplicative — we own error reporting through Healthchecks instead.
    """
    health.ping(task_name, "start")
    try:
        fn()
        health.ping(task_name, "success")
    except Exception:
        tb = traceback.format_exc()
        log.exception("task=%s failed", task_name)
        health.ping(task_name, "fail", body=tb)


# --- internal task implementations -------------------------------------------

def _do_ingest_all() -> None:
    """Loop over every active municipality and run the ingest pipeline.

    A failure for one city is logged but does not block the others.
    """
    with db_cursor() as cur:
        cur.execute("SELECT slug FROM municipalities WHERE active = TRUE ORDER BY slug")
        rows = cur.fetchall()

    for row in rows:
        slug = row["slug"]
        try:
            ingest_municipality(slug)
        except Exception:
            log.exception("ingest failed for %s", slug)


def _do_ai_items() -> None:
    try:
        run_once(stage="items", limit=200, notes="cron_items")
    except BudgetExceededError as e:
        # Hitting the daily cap is expected behavior, not a failure.
        log.info("ai_items skipped: %s", e)


def _do_ai_meetings() -> None:
    try:
        run_once(stage="meetings", limit=50, notes="cron_meetings")
    except BudgetExceededError as e:
        log.info("ai_meetings skipped: %s", e)


def _do_vote_matching() -> None:
    result = match_all_unmatched()
    log.info(
        "vote_matching meetings=%d ts=%d sub=%d consent=%d",
        result.get("meetings", 0),
        result.get("timestamp_matched", 0),
        result.get("substantive_matched", 0),
        result.get("consent_matched", 0),
    )


def _do_repair_empty_agendas() -> None:
    repair_empty_agendas()


# --- public, _safe_run-wrapped entry points ----------------------------------

def task_ingest_all() -> None:
    _safe_run("ingest_all", _do_ingest_all)


def task_ai_items() -> None:
    _safe_run("ai_items", _do_ai_items)


def task_ai_meetings() -> None:
    _safe_run("ai_meetings", _do_ai_meetings)


def task_vote_matching() -> None:
    _safe_run("vote_matching", _do_vote_matching)


def task_repair_empty_agendas() -> None:
    _safe_run("repair_empty_agendas", _do_repair_empty_agendas)


# --- registry — used by scheduler.py and the --run-once flag -----------------

TASKS: dict[str, Callable[[], None]] = {
    "ingest_all":           task_ingest_all,
    "ai_items":             task_ai_items,
    "ai_meetings":          task_ai_meetings,
    "vote_matching":        task_vote_matching,
    "repair_empty_agendas": task_repair_empty_agendas,
}
```

- [ ] **Step 4.4: Run tests to confirm they pass**

Run: `venv/bin/pytest tests/unit/test_worker_tasks.py -v`
Expected: 11 passed

- [ ] **Step 4.5: Commit**

```bash
git add src/docket/worker/tasks.py tests/unit/test_worker_tasks.py
git commit -m "feat(worker): task wrappers calling existing services"
```

---

## Task 5: Scheduler Entry Point

**Files:**
- Create: `src/docket/worker/scheduler.py`
- Create: `tests/unit/test_worker_scheduler.py`

- [ ] **Step 5.1: Write failing tests**

Create `tests/unit/test_worker_scheduler.py`:

```python
"""Tests for the worker scheduler entry point."""

import sys
from unittest.mock import patch

import pytest

from docket.worker import scheduler


def test_build_scheduler_registers_five_jobs():
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job_ids = {job.id for job in sched.get_jobs()}
    assert job_ids == {
        "ingest_all", "ai_items", "ai_meetings", "vote_matching", "repair_empty_agendas",
    }
    sched.shutdown(wait=False)


def test_build_scheduler_uses_supplied_timezone():
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job = sched.get_job("ingest_all")
    assert str(job.trigger.timezone) == "America/Chicago"
    sched.shutdown(wait=False)


@pytest.mark.parametrize("job_id,expected_hour", [
    ("repair_empty_agendas", 5),
    ("ingest_all",           6),
    ("ai_items",             7),
    ("ai_meetings",          8),
    ("vote_matching",        9),
])
def test_build_scheduler_job_hours(job_id, expected_hour):
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job = sched.get_job(job_id)
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == str(expected_hour)
    sched.shutdown(wait=False)


def test_build_scheduler_repair_runs_only_on_monday():
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job = sched.get_job("repair_empty_agendas")
    fields = {f.name: str(f) for f in job.trigger.fields}
    # APScheduler day_of_week is 0=mon..6=sun
    assert fields["day_of_week"] == "0"
    sched.shutdown(wait=False)


def test_run_once_task_invokes_named_task():
    with patch.dict("docket.worker.scheduler.TASKS",
                    {"ingest_all": lambda: setattr(test_run_once_task_invokes_named_task, "_called", True)},
                    clear=True):
        scheduler.run_once_task("ingest_all")
    assert getattr(test_run_once_task_invokes_named_task, "_called", False) is True


def test_run_once_task_unknown_name_exits():
    with pytest.raises(SystemExit) as exc_info:
        scheduler.run_once_task("not_a_real_task")
    assert exc_info.value.code != 0


def test_main_with_run_once_dispatches_and_exits(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["scheduler.py", "--run-once", "ingest_all"])
    called = {"v": False}
    monkeypatch.setattr(scheduler, "run_once_task",
                        lambda name: called.__setitem__("v", name))
    scheduler.main()
    assert called["v"] == "ingest_all"
```

- [ ] **Step 5.2: Run tests to confirm they fail**

Run: `venv/bin/pytest tests/unit/test_worker_scheduler.py -v`
Expected: All FAIL with `ModuleNotFoundError: No module named 'docket.worker.scheduler'`

- [ ] **Step 5.3: Implement `scheduler.py`**

Create `src/docket/worker/scheduler.py`:

```python
"""APScheduler entry point for the docket.pub cron worker.

Two modes:

  python -m docket.worker.scheduler                   # daemon mode (Railway worker)
  python -m docket.worker.scheduler --run-once <task> # foreground one-shot

The daemon registers all five jobs with the timezone in $WORKER_TIMEZONE
(default America/Chicago) and calls scheduler.start(), which blocks.

The one-shot mode runs a single named task in the foreground using the same
_safe_run wrapper as scheduled runs, ensuring environmental parity for
manual triggers and verification.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from docket.worker.tasks import TASKS

log = logging.getLogger(__name__)


def build_scheduler(timezone: str = "America/Chicago") -> BlockingScheduler:
    """Build a scheduler with all five jobs registered. Does not start it."""
    sched = BlockingScheduler(timezone=timezone)

    sched.add_job(
        TASKS["repair_empty_agendas"],
        CronTrigger(day_of_week="mon", hour=5, minute=0, timezone=timezone),
        id="repair_empty_agendas",
        coalesce=True,
        max_instances=1,
    )
    sched.add_job(
        TASKS["ingest_all"],
        CronTrigger(hour=6, minute=0, timezone=timezone),
        id="ingest_all",
        coalesce=True,
        max_instances=1,
    )
    sched.add_job(
        TASKS["ai_items"],
        CronTrigger(hour=7, minute=0, timezone=timezone),
        id="ai_items",
        coalesce=True,
        max_instances=1,
    )
    sched.add_job(
        TASKS["ai_meetings"],
        CronTrigger(hour=8, minute=0, timezone=timezone),
        id="ai_meetings",
        coalesce=True,
        max_instances=1,
    )
    sched.add_job(
        TASKS["vote_matching"],
        CronTrigger(hour=9, minute=0, timezone=timezone),
        id="vote_matching",
        coalesce=True,
        max_instances=1,
    )
    return sched


def run_once_task(name: str) -> None:
    """Foreground execution of a single named task. Exits non-zero on unknown name."""
    if name not in TASKS:
        sys.exit(f"unknown task: {name!r} (known: {sorted(TASKS)})")
    TASKS[name]()


def main() -> None:
    parser = argparse.ArgumentParser(description="docket.pub cron worker")
    parser.add_argument(
        "--run-once",
        metavar="TASK",
        help="Run a single task in the foreground and exit (e.g. --run-once ingest_all)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.run_once:
        run_once_task(args.run_once)
        return

    tz = os.environ.get("WORKER_TIMEZONE", "America/Chicago")
    sched = build_scheduler(timezone=tz)
    log.info("docket.pub worker starting timezone=%s jobs=%d", tz, len(sched.get_jobs()))
    for job in sched.get_jobs():
        log.info("  job=%s next_run=%s", job.id, job.next_run_time)
    sched.start()  # blocks


if __name__ == "__main__":
    main()
```

- [ ] **Step 5.4: Run tests to confirm they pass**

Run: `venv/bin/pytest tests/unit/test_worker_scheduler.py -v`
Expected: 9 passed

- [ ] **Step 5.5: Verify the package as a whole still imports cleanly**

Run: `venv/bin/python -c "from docket.worker import scheduler, tasks, health; print('ok')"`
Expected: `ok`

- [ ] **Step 5.6: Commit**

```bash
git add src/docket/worker/scheduler.py tests/unit/test_worker_scheduler.py
git commit -m "feat(worker): apscheduler entry point + --run-once flag"
```

---

## Task 6: Procfile Worker Line

**Files:**
- Modify: `Procfile`

- [ ] **Step 6.1: Add the worker line**

Edit `Procfile`. Final contents:

```
web: python -m docket.migrations.runner && gunicorn "docket.web:create_app()" --bind 0.0.0.0:${PORT:-5000} --timeout 120
worker: python -m docket.worker.scheduler
```

- [ ] **Step 6.2: Verify the file is well-formed**

Run: `cat Procfile`
Expected: Both `web:` and `worker:` lines visible.

- [ ] **Step 6.3: Smoke test the worker locally (foreground, single task)**

Run: `cd ~/docket-pub && venv/bin/python -m docket.worker.scheduler --run-once repair_empty_agendas`
Expected: Logs include `repair_empty_agendas cleared=N` (where N may be 0 against a clean local DB) and the process exits 0.

- [ ] **Step 6.4: Smoke test the daemon mode briefly (Ctrl+C after startup logs)**

Run (in a terminal you can interrupt): `venv/bin/python -m docket.worker.scheduler`
Expected: Within ~1 second, logs show:

```
docket.pub worker starting timezone=America/Chicago jobs=5
  job=repair_empty_agendas next_run=...
  job=ingest_all           next_run=...
  job=ai_items             next_run=...
  job=ai_meetings          next_run=...
  job=vote_matching        next_run=...
```

Press Ctrl+C to stop. The process should exit cleanly.

- [ ] **Step 6.5: Run the full test suite to confirm no regressions**

Run: `venv/bin/pytest -x`
Expected: All tests pass (existing + new).

- [ ] **Step 6.6: Commit**

```bash
git add Procfile
git commit -m "feat(infra): add worker process to Procfile"
```

---

## Task 7: Healthchecks.io Provisioning Note

**Files:**
- Create: `docs/runbooks/cron-worker.md`

- [ ] **Step 7.1: Write the runbook**

Create `docs/runbooks/cron-worker.md`:

````markdown
# Cron Worker Runbook

The Railway `worker` service runs `python -m docket.worker.scheduler` and fires
five scheduled tasks (see the design spec at
`docs/superpowers/specs/2026-05-04-cron-worker-design.md`).

## Healthchecks.io setup (do this BEFORE merging to main)

1. Sign up at https://healthchecks.io (free tier covers this entirely).
2. Create five checks. For each, copy the UUID from the ping URL
   (`https://hc-ping.com/<UUID>`).

   | Check name           | Schedule    | Grace |
   |----------------------|-------------|-------|
   | docket-ingest        | Daily 06:00 | 2h    |
   | docket-ai-items      | Daily 07:00 | 2h    |
   | docket-ai-meetings   | Daily 08:00 | 2h    |
   | docket-vote-matching | Daily 09:00 | 2h    |
   | docket-repair        | Mon 05:00   | 24h   |

3. Set Railway env vars (use `railway variables --set` with the actual UUIDs):

   ```bash
   railway variables --service worker --set HEALTHCHECK_INGEST_UUID=<uuid>
   railway variables --service worker --set HEALTHCHECK_AI_ITEMS_UUID=<uuid>
   railway variables --service worker --set HEALTHCHECK_AI_MEETINGS_UUID=<uuid>
   railway variables --service worker --set HEALTHCHECK_VOTE_MATCH_UUID=<uuid>
   railway variables --service worker --set HEALTHCHECK_REPAIR_UUID=<uuid>
   ```

4. (Optional) Configure notification channels in Healthchecks.io
   (email, Slack, etc.).

## Deploy

```bash
railway up --detach
```

Confirm a `worker` service appears in the Railway dashboard alongside `web`.

## Verify each task end-to-end via --run-once

After deploy, run each task once in the foreground via Railway's shell:

```bash
railway run --service worker venv/bin/python -m docket.worker.scheduler --run-once repair_empty_agendas
railway run --service worker venv/bin/python -m docket.worker.scheduler --run-once ingest_all
railway run --service worker venv/bin/python -m docket.worker.scheduler --run-once ai_items
railway run --service worker venv/bin/python -m docket.worker.scheduler --run-once ai_meetings
railway run --service worker venv/bin/python -m docket.worker.scheduler --run-once vote_matching
```

Each should emit a Healthchecks ping (visible on the dashboard within seconds)
and complete successfully.

## Manual one-off triggers

The same `--run-once` invocation works for ad-hoc runs in production. Prefer it
over calling the underlying CLIs directly — `--run-once` runs through the same
logging and Healthchecks pipeline as scheduled runs, so manual triggers don't
silently bypass observability.

## When a Healthchecks alert fires

1. Check Railway logs for the worker service for the relevant time window.
2. The `health.ping(task, "fail", body=traceback)` line sends the traceback
   to Healthchecks, so the alert email/notification will include it.
3. Reproduce locally:
   ```bash
   DATABASE_URL=$DATABASE_PUBLIC_URL venv/bin/python -m docket.worker.scheduler --run-once <task>
   ```
4. Once fixed, re-trigger the task with `--run-once` from Railway to clear the
   "down" state on the corresponding Healthcheck.

## 18-month AI backfill (one-shot, separate from the worker)

The worker handles steady-state. To populate AI summaries/scoring for the
existing ~4,500 unprocessed items in the 18-month window, run from a laptop:

```bash
DATABASE_URL=$DATABASE_PUBLIC_URL ANTHROPIC_API_KEY=... \
  venv/bin/python -m docket.ai.cli --items --force-budget
DATABASE_URL=$DATABASE_PUBLIC_URL ANTHROPIC_API_KEY=... \
  venv/bin/python -m docket.ai.cli --meetings --force-budget
```

Estimated cost ~$12. Watch for tracebacks in real-time; if a corrupted PDF
trips the parser, you'll see it immediately rather than buried in Railway logs.
````

- [ ] **Step 7.2: Verify the file**

Run: `wc -l docs/runbooks/cron-worker.md`
Expected: roughly 80–90 lines.

- [ ] **Step 7.3: Commit**

```bash
mkdir -p docs/runbooks
git add docs/runbooks/cron-worker.md
git commit -m "docs(runbook): cron worker provisioning + verification steps"
```

---

## Final Verification

- [ ] **Step F.1: Full test suite**

Run: `venv/bin/pytest`
Expected: All tests pass.

- [ ] **Step F.2: Confirm worker is importable end-to-end**

Run: `venv/bin/python -m docket.worker.scheduler --help`
Expected: argparse usage output showing the `--run-once` flag.

- [ ] **Step F.3: Confirm `--run-once` for each task works locally**

Run, one at a time:

```bash
venv/bin/python -m docket.worker.scheduler --run-once repair_empty_agendas
venv/bin/python -m docket.worker.scheduler --run-once vote_matching
```

(Skip `ingest_all`, `ai_items`, `ai_meetings` locally unless you want to actually
hit Granicus / spend Anthropic credits — those are meant to be smoke-tested
post-deploy via `railway run`.)

Expected: Each exits 0 with informational log output.

- [ ] **Step F.4: Push branch and open PR**

```bash
git push -u origin <branch-name>
gh pr create --title "feat: cron worker (T27)" --body "$(cat <<'EOF'
## Summary
- Adds Railway `worker` process running APScheduler with 5 scheduled tasks
- Closes T27 (cron jobs for AI pipeline)
- Spec: `docs/superpowers/specs/2026-05-04-cron-worker-design.md`
- Runbook: `docs/runbooks/cron-worker.md`

## Test plan
- [ ] Provision Healthchecks.io project and 5 checks
- [ ] `railway variables --service worker --set HEALTHCHECK_*_UUID=...` (×5)
- [ ] Merge + `railway up --detach`
- [ ] Verify `worker` service appears in Railway dashboard
- [ ] `--run-once` each task on Railway, confirm Healthchecks pings
- [ ] Watch Healthchecks dashboard for 48h to confirm cadence

## Out of scope (manual one-shot from laptop, not part of this PR)
- 18-month AI backfill via `--force-budget` — see runbook for command

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review Checklist (read after writing, before handing off)

- ✅ **Spec coverage:** Every section of the spec maps to at least one task. Architecture → Tasks 2/4/5; `repair_empty_agendas` → Task 3; cron schedule → Task 5; Procfile → Task 6; Healthchecks.io setup → Task 7; rollout → Task 7 + final verification.
- ✅ **No placeholders:** No "TBD", no "add error handling here", no "tests for the above" without code.
- ✅ **Type/name consistency:** `_safe_run`, `TASKS`, `task_*`, `_do_*`, `health.ping` are consistent across tasks.py and scheduler.py and their tests. Healthcheck env var names match across health.py, runbook, and spec.
- ✅ **APScheduler day_of_week test** uses `"0"` (Monday) since the registration uses `day_of_week="mon"` which APScheduler normalizes to integer 0.
