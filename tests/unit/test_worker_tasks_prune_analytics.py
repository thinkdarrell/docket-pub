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
