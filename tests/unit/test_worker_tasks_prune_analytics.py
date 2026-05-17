"""Unit tests for the prune_analytics worker task.

The task connects directly to the umami database via $ANALYTICS_DATABASE_URL
(separate from the editorial $DATABASE_URL) and issues batched DELETEs against
three Umami tables (event_data, session, website_event). The connection is
psycopg2-based, not the docket.db.db() helper, because the target DB is a
different database on the same Postgres instance.
"""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from docket.worker.tasks import (
    PRUNE_ANALYTICS_BATCH_SIZE,
    _do_prune_analytics,
    _PRUNE_TABLES,
)


@patch.dict("os.environ", {"ANALYTICS_DATABASE_URL": "postgres://u:p@h:5/umami"})
@patch("docket.worker.tasks.psycopg")
def test_prune_analytics_deletes_from_all_three_tables(mock_psycopg):
    """Umami v3 dropped FK constraints — we must delete from event_data + session
    + website_event explicitly. Verify all three tables are touched."""
    mock_cursor = MagicMock()
    # rowcount=0 on first probe per table → each table's batch loop exits
    # after one execute. Total: 3 execute calls (one per table).
    mock_cursor.rowcount = 0
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_psycopg.connect.return_value.__enter__.return_value = mock_conn

    result = _do_prune_analytics()

    mock_psycopg.connect.assert_called_once_with("postgres://u:p@h:5/umami")

    # Combine all executed SQL strings into one blob for substring checks
    executed_sqls = [c.args[0] for c in mock_cursor.execute.call_args_list]
    assert len(executed_sqls) == 3, f"expected one DELETE per table, got {executed_sqls}"
    combined = " ".join(executed_sqls)

    # All three Umami tables targeted, none missed (the v3 FK-drop fix)
    assert "DELETE FROM event_data" in combined
    assert "DELETE FROM session" in combined
    assert "DELETE FROM website_event" in combined

    # Retention window applied uniformly
    assert combined.count("24 months") == 3

    # Each statement uses ctid-batched form to bound transaction size
    assert combined.count("ctid IN") == 3
    assert combined.count("LIMIT") == 3

    # Return shape
    assert result["deleted"] == 0
    assert set(result["by_table"]) == set(_PRUNE_TABLES)
    assert all(v == 0 for v in result["by_table"].values())


@patch.dict("os.environ", {"ANALYTICS_DATABASE_URL": "postgres://u:p@h:5/umami"})
@patch("docket.worker.tasks.psycopg")
def test_prune_analytics_batches_and_terminates(mock_psycopg):
    """Verify the batch loop: when rowcount returns PRUNE_ANALYTICS_BATCH_SIZE,
    another iteration runs; when it returns less, the loop exits for that table."""
    mock_cursor = MagicMock()
    # event_data: 2 full batches + 1 partial; session: 1 partial; website_event: 0
    type(mock_cursor).rowcount = PropertyMock(side_effect=[
        PRUNE_ANALYTICS_BATCH_SIZE,    # event_data batch 1 (loop continues)
        PRUNE_ANALYTICS_BATCH_SIZE,    # event_data batch 2 (loop continues)
        500,                            # event_data batch 3 (loop exits — partial)
        0,                              # session batch 1 (loop exits — 0 deleted)
        0,                              # website_event batch 1 (loop exits — 0 deleted)
    ])
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_psycopg.connect.return_value.__enter__.return_value = mock_conn

    result = _do_prune_analytics()

    expected_event_data = 2 * PRUNE_ANALYTICS_BATCH_SIZE + 500
    assert result["by_table"]["event_data"] == expected_event_data
    assert result["by_table"]["session"] == 0
    assert result["by_table"]["website_event"] == 0
    assert result["deleted"] == expected_event_data

    # 5 batches across 3 tables → 5 execute calls + 5 commits (commit per batch
    # to release WAL — important for bounded transactions on Railway Postgres).
    assert mock_cursor.execute.call_count == 5
    assert mock_conn.commit.call_count == 5


@patch.dict("os.environ", {}, clear=True)
def test_prune_analytics_raises_without_env_var():
    with pytest.raises(KeyError):
        _do_prune_analytics()
