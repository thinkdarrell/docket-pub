"""Tests for the calibration_report cron task wrapper and calibration module."""

from unittest.mock import patch, MagicMock, call

import pytest

from docket.worker import tasks
from docket.worker.tasks import _do_calibration_report, task_calibration_report, TASKS
from docket.ai.calibration import (
    run_calibration_queries,
    QUERY_A_DIVERGENCE,
    QUERY_B1_UNDERSCORING,
    QUERY_B2_OVERSCORING,
    QUERY_C_DRIFT,
)


def _make_cursor(query_results=None):
    """Return a mock context-manager cursor with configurable fetchall results."""
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)

    # fetchall returns are consumed in order: A, B1, B2, C
    if query_results is None:
        cur.fetchall.return_value = []
    elif isinstance(query_results, list):
        cur.fetchall.side_effect = query_results
    return cur


# ---------------------------------------------------------------------------
# run_calibration_queries — all 4 queries are executed
# ---------------------------------------------------------------------------

def test_do_calibration_report_runs_all_4_queries():
    """All 4 SQL constants must be passed to cur.execute."""
    cur = MagicMock()
    cur.fetchall.return_value = []

    run_calibration_queries(cur)

    executed_sqls = [c.args[0] for c in cur.execute.call_args_list]
    assert QUERY_A_DIVERGENCE in executed_sqls
    assert QUERY_B1_UNDERSCORING in executed_sqls
    assert QUERY_B2_OVERSCORING in executed_sqls
    assert QUERY_C_DRIFT in executed_sqls


def test_do_calibration_report_runs_exactly_4_queries():
    """No extra queries should be run."""
    cur = MagicMock()
    cur.fetchall.return_value = []

    run_calibration_queries(cur)

    assert cur.execute.call_count == 4


# ---------------------------------------------------------------------------
# run_calibration_queries — counts returned correctly
# ---------------------------------------------------------------------------

def test_do_calibration_report_handles_empty_results():
    """All queries return empty; counters are all zero, no errors raised."""
    cur = MagicMock()
    cur.fetchall.return_value = []

    counts = run_calibration_queries(cur)

    assert counts['divergence_count'] == 0
    assert counts['underscoring_categories'] == 0
    assert counts['overscoring_categories'] == 0
    assert counts['drift_alerts'] == 0


def test_run_calibration_queries_counts_divergence():
    """divergence_count matches row count from Query A."""
    cur = MagicMock()
    cur.fetchall.side_effect = [
        [{'id': 1}, {'id': 2}, {'id': 3}],  # Query A: 3 rows
        [],                                  # Query B1
        [],                                  # Query B2
        [],                                  # Query C
    ]

    counts = run_calibration_queries(cur)

    assert counts['divergence_count'] == 3
    assert counts['underscoring_categories'] == 0
    assert counts['overscoring_categories'] == 0


def test_run_calibration_queries_counts_drift_alerts_correctly():
    """Only rows meeting the threshold (sig_delta_wow < -1.0 AND |vol_delta| < n * 0.3) count."""
    drift_rows = [
        # Should count: sig_delta_wow < -1.0 and |volume_delta_wow| < n * 0.3
        {'sig_delta_wow': -1.5, 'volume_delta_wow': 2,  'n': 100},
        {'sig_delta_wow': -2.0, 'volume_delta_wow': -5, 'n': 50},
        # Should NOT count: sig_delta_wow not negative enough
        {'sig_delta_wow': -0.5, 'volume_delta_wow': 1,  'n': 100},
        # Should NOT count: volume change too large (|30| >= 100 * 0.3 = 30 — boundary, not < 30)
        {'sig_delta_wow': -2.0, 'volume_delta_wow': 30, 'n': 100},
        # Should NOT count: sig_delta_wow is positive
        {'sig_delta_wow':  1.0, 'volume_delta_wow': 1,  'n': 100},
    ]

    cur = MagicMock()
    cur.fetchall.side_effect = [
        [],          # Query A
        [],          # Query B1
        [],          # Query B2
        drift_rows,  # Query C
    ]

    counts = run_calibration_queries(cur)

    assert counts['drift_alerts'] == 2


def test_run_calibration_queries_skips_first_week_lag_nulls():
    """First row of each partition has sig_delta_wow=NULL; must NOT count as a drift alert."""
    drift_rows = [
        # First row of partition — LAG produces NULL
        {'sig_delta_wow': None, 'volume_delta_wow': None, 'n': 50},
        # Valid alert row
        {'sig_delta_wow': -2.0, 'volume_delta_wow': 3, 'n': 100},
    ]

    cur = MagicMock()
    cur.fetchall.side_effect = [
        [],          # Query A
        [],          # Query B1
        [],          # Query B2
        drift_rows,  # Query C
    ]

    counts = run_calibration_queries(cur)

    # Only the second row qualifies
    assert counts['drift_alerts'] == 1


# ---------------------------------------------------------------------------
# _do_calibration_report — calls cache_cleanup and logs
# ---------------------------------------------------------------------------

def test_do_calibration_report_calls_cache_cleanup():
    """cache_cleanup must be called with max_age_days=90."""
    cur = _make_cursor(query_results=[[], [], [], []])

    with patch("docket.worker.tasks.db_cursor", return_value=cur), \
         patch("docket.ai.cache.cache_cleanup", return_value=5) as mock_cleanup:
        _do_calibration_report()

    mock_cleanup.assert_called_once_with(max_age_days=90)


def test_do_calibration_report_logs_summary_line(caplog):
    """Log output must include all expected counter keys."""
    import logging
    cur = _make_cursor(query_results=[
        [{'id': 1}],  # divergence: 1
        [{'action_type': 'contract'}],  # underscoring: 1
        [],           # overscoring: 0
        [],           # drift: 0
    ])

    with patch("docket.worker.tasks.db_cursor", return_value=cur), \
         patch("docket.ai.cache.cache_cleanup", return_value=12):
        with caplog.at_level(logging.INFO, logger="docket.worker.tasks"):
            _do_calibration_report()

    assert any("calibration_report" in record.message for record in caplog.records)
    log_msg = next(r.message for r in caplog.records if "calibration_report" in r.message)
    assert "divergence=1" in log_msg
    assert "underscoring=1" in log_msg
    assert "overscoring=0" in log_msg
    assert "drift_alerts=0" in log_msg
    assert "cache_cleanup=12" in log_msg


# ---------------------------------------------------------------------------
# task_calibration_report — wraps _safe_run correctly
# ---------------------------------------------------------------------------

def test_task_calibration_report_uses_safe_run():
    """task_calibration_report must delegate to _safe_run with the right name and fn."""
    with patch("docket.worker.tasks._safe_run") as mock_safe_run:
        task_calibration_report()

    mock_safe_run.assert_called_once_with("calibration_report", _do_calibration_report)


# ---------------------------------------------------------------------------
# TASKS registry
# ---------------------------------------------------------------------------

def test_TASKS_registry_has_calibration_report():
    assert 'calibration_report' in TASKS
    assert TASKS['calibration_report'] is task_calibration_report
