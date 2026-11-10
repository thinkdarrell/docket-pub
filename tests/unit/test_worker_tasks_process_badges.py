"""Tests for the process_badges cron task wrapper."""

from unittest.mock import patch, MagicMock, call

import pytest

from docket.worker import tasks
from docket.worker.tasks import _do_process_badges, task_process_badges, TASKS


def _make_cursor(advisory_lock_result=True):
    """Return a mock context-manager cursor with pg_try_advisory_lock configured."""
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)

    # fetchone() is called once to get the advisory lock result. db_cursor
    # yields a RealDictCursor, so the row is keyed by column name, not index.
    cur.fetchone.return_value = {"got_lock": advisory_lock_result}
    return cur


# ---------------------------------------------------------------------------
# _do_process_badges — against the real database (issue #154)
# ---------------------------------------------------------------------------

def test_do_process_badges_runs_against_the_real_schema():
    """The task runs end to end on the migrated schema: it recomputes the
    deterministic badges of a recently generated item, keeps a manual one,
    and writes the vote-derived badge. The mocked tests below cannot see a
    wrong column or a wrong row type; this one can.
    """
    from docket.db import db
    from tests.unit.test_badges_process import (
        _badge_exists, _cleanup, _setup_agenda_item, _setup_city, _setup_meeting,
    )

    with db() as conn:
        with conn.cursor() as cur:
            city_id = _setup_city(cur)
            mtg_id = _setup_meeting(cur, city_id, external_id='test-task-badges-mtg')
            item_id = _setup_agenda_item(cur, mtg_id, title='Task-level 8-1 item')
            cur.execute("UPDATE agenda_items SET ai_generated_at = NOW() WHERE id = %s", (item_id,))
            cur.execute(
                "INSERT INTO votes (meeting_id, result, source, confidence) "
                "VALUES (%s, 'passed', 'minutes_text', 'high') RETURNING id",
                (mtg_id,),
            )
            vote_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO member_votes (vote_id, member_name, position) "
                "VALUES (%s, 'Member A', 'yea'), (%s, 'Member B', 'nay')",
                (vote_id, vote_id),
            )
            cur.execute(
                "INSERT INTO vote_agenda_items (vote_id, agenda_item_id, association_type, "
                "match_confidence, is_active) VALUES (%s, %s, 'explicit', 1.0, TRUE)",
                (vote_id, item_id),
            )
            # A stale deterministic badge the recompute must clear, and a
            # manual one it must keep (decision #57).
            cur.execute(
                "INSERT INTO agenda_item_badges (agenda_item_id, city_id, badge_slug, kind, "
                "confidence, source, status) VALUES "
                "(%s, %s, 'sole_source', 'process', 1.0, 'deterministic', 'applied'), "
                "(%s, %s, 'legal_settlement', 'process', 1.0, 'manual', 'applied')",
                (item_id, city_id, item_id, city_id),
            )
    try:
        _do_process_badges()
        with db() as conn:
            with conn.cursor() as cur:
                assert _badge_exists(cur, item_id, 'split_vote')
                assert not _badge_exists(cur, item_id, 'sole_source')
                assert _badge_exists(cur, item_id, 'legal_settlement')
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                _cleanup(cur, city_id)


# ---------------------------------------------------------------------------
# _do_process_badges — advisory lock acquired
# ---------------------------------------------------------------------------

def test_do_process_badges_runs_all_queries():
    """All 6 PROCESS_BADGE_QUERIES must be executed when lock is acquired."""
    from docket.ai.badges_process import PROCESS_BADGE_QUERIES

    cur = _make_cursor(advisory_lock_result=True)

    with patch("docket.worker.tasks.db_cursor", return_value=cur):
        _do_process_badges()

    # Collect every SQL string passed to cur.execute
    executed_sqls = [c.args[0] for c in cur.execute.call_args_list]

    for query in PROCESS_BADGE_QUERIES:
        assert query in executed_sqls, f"Expected query not executed: {query[:80]!r}..."


def test_do_process_badges_creates_temp_table():
    """CREATE TEMP TABLE recent_items must run before any badge inserts."""
    cur = _make_cursor(advisory_lock_result=True)

    with patch("docket.worker.tasks.db_cursor", return_value=cur):
        _do_process_badges()

    executed_sqls = [c.args[0] for c in cur.execute.call_args_list]

    temp_table_calls = [s for s in executed_sqls if "CREATE TEMP TABLE recent_items" in s]
    assert len(temp_table_calls) == 1


def test_do_process_badges_deletes_existing_process_badges():
    """DELETE WHERE kind='process' AND source != 'manual' must run before inserts."""
    cur = _make_cursor(advisory_lock_result=True)

    with patch("docket.worker.tasks.db_cursor", return_value=cur):
        _do_process_badges()

    executed_sqls = [c.args[0] for c in cur.execute.call_args_list]

    delete_calls = [
        s for s in executed_sqls
        if "DELETE FROM agenda_item_badges" in s
        and "kind = 'process'" in s
        and "source != 'manual'" in s
    ]
    assert len(delete_calls) == 1


def test_do_process_badges_temp_table_before_badge_inserts():
    """CREATE TEMP TABLE must appear before the first badge INSERT in call order."""
    from docket.ai.badges_process import PROCESS_BADGE_QUERIES

    cur = _make_cursor(advisory_lock_result=True)

    with patch("docket.worker.tasks.db_cursor", return_value=cur):
        _do_process_badges()

    executed_sqls = [c.args[0] for c in cur.execute.call_args_list]

    temp_idx = next(
        i for i, s in enumerate(executed_sqls) if "CREATE TEMP TABLE recent_items" in s
    )
    first_badge_idx = next(
        i for i, s in enumerate(executed_sqls) if s in PROCESS_BADGE_QUERIES
    )
    assert temp_idx < first_badge_idx


# ---------------------------------------------------------------------------
# _do_process_badges — advisory lock NOT acquired
# ---------------------------------------------------------------------------

def test_do_process_badges_skips_when_lock_held():
    """When advisory lock is unavailable, no badge queries should run."""
    from docket.ai.badges_process import PROCESS_BADGE_QUERIES

    cur = _make_cursor(advisory_lock_result=False)

    with patch("docket.worker.tasks.db_cursor", return_value=cur), \
         patch("docket.worker.tasks.log") as mock_log:
        _do_process_badges()

    executed_sqls = [c.args[0] for c in cur.execute.call_args_list]
    for query in PROCESS_BADGE_QUERIES:
        assert query not in executed_sqls

    # Warning must be emitted
    mock_log.warning.assert_called_once()
    assert "already running" in mock_log.warning.call_args.args[0]


# ---------------------------------------------------------------------------
# _do_process_badges — advisory lock released on failure
# ---------------------------------------------------------------------------

def test_do_process_badges_releases_lock_on_failure():
    """pg_advisory_unlock must be called even when a badge query raises."""
    cur = _make_cursor(advisory_lock_result=True)

    call_count = {"n": 0}
    original_execute = cur.execute.side_effect

    def execute_with_failure(sql, params=None):
        call_count["n"] += 1
        # Blow up on the first badge INSERT (after temp table + delete = 3 calls + lock = 1)
        if "INSERT INTO agenda_item_badges" in sql and call_count["n"] > 4:
            raise RuntimeError("simulated DB failure")

    cur.execute.side_effect = execute_with_failure

    with patch("docket.worker.tasks.db_cursor", return_value=cur):
        with pytest.raises(RuntimeError, match="simulated DB failure"):
            _do_process_badges()

    # pg_advisory_unlock must have been called
    unlock_calls = [
        c for c in cur.execute.call_args_list
        if "pg_advisory_unlock" in c.args[0]
    ]
    assert len(unlock_calls) == 1


# ---------------------------------------------------------------------------
# task_process_badges — wraps _safe_run correctly
# ---------------------------------------------------------------------------

def test_task_process_badges_uses_safe_run():
    """task_process_badges must delegate to _safe_run with the right name and fn."""
    with patch("docket.worker.tasks._safe_run") as mock_safe_run:
        task_process_badges()

    mock_safe_run.assert_called_once_with("process_badges", _do_process_badges)


# ---------------------------------------------------------------------------
# TASKS registry
# ---------------------------------------------------------------------------

def test_TASKS_registry_has_process_badges():
    assert "process_badges" in TASKS
    assert TASKS["process_badges"] is task_process_badges
