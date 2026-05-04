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
