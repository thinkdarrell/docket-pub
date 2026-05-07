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


def test_ai_meetings_swallows_budget_exceeded():
    """BudgetExceededError is expected behavior, not a failure for Healthchecks."""
    from docket.ai.worker import BudgetExceededError
    with patch("docket.worker.tasks.run_once",
               side_effect=BudgetExceededError("over cap")):
        tasks._do_ai_meetings()  # must not raise


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

def test_tasks_registry_has_all_six_jobs():
    expected = {
        "ingest_all", "ai_items", "ai_meetings", "vote_matching",
        "repair_empty_agendas", "process_badges",
    }
    assert set(tasks.TASKS.keys()) == expected
