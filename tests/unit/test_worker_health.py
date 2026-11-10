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


def test_every_registered_task_has_a_uuid_env_entry():
    # _safe_run calls health.ping(task, "start") *before* its try/except, so a task
    # registered in TASKS but missing from TASK_UUID_ENV crashes apscheduler with
    # no fail-ping fired. Keep the two dicts in sync.
    from docket.worker.tasks import TASKS

    missing = set(TASKS) - set(health.TASK_UUID_ENV)
    assert not missing, f"tasks missing from TASK_UUID_ENV: {sorted(missing)}"


def test_unmonitored_tasks_lists_tasks_whose_variable_is_unset(monkeypatch):
    """A task with no UUID variable is unmonitored; one with it set is not."""
    for env_var in health.TASK_UUID_ENV.values():
        monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setenv("HEALTHCHECK_INGEST_UUID", "abc-123")

    unmonitored = health.unmonitored_tasks()

    assert "video_ocr" in unmonitored
    assert "ingest_all" not in unmonitored
    assert unmonitored == sorted(unmonitored)


def test_unmonitored_tasks_leaves_out_silent_by_design(monkeypatch):
    """Tasks the runbook leaves without a check on purpose are not reported."""
    for env_var in health.TASK_UUID_ENV.values():
        monkeypatch.delenv(env_var, raising=False)

    unmonitored = health.unmonitored_tasks()

    assert health.SILENT_BY_DESIGN
    assert health.SILENT_BY_DESIGN <= set(health.TASK_UUID_ENV)
    assert not health.SILENT_BY_DESIGN & set(unmonitored)


def test_unmonitored_tasks_is_empty_when_every_variable_is_set(monkeypatch):
    for env_var in health.TASK_UUID_ENV.values():
        monkeypatch.setenv(env_var, "abc-123")
    assert health.unmonitored_tasks() == []
