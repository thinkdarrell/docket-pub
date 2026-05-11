"""Tests for AdaptiveWorkerPool (docket.ai.concurrency).

Coverage:
- 429 storm scales down
- Cool-down period blocks scale-up
- Scale-up after clean window
- min/max bounds
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from docket.ai.concurrency import AdaptiveWorkerPool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_TIME = 1_000_000.0  # arbitrary frozen epoch for tests


# ---------------------------------------------------------------------------
# TestRecord429Scaling
# ---------------------------------------------------------------------------


class TestRecord429Scaling:
    def test_429_storm_scales_down(self):
        """5+ 429s in 300s window causes workers to decrement."""
        pool = AdaptiveWorkerPool(max_workers=5, min_workers=1)
        assert pool.current_workers == 5

        with patch("docket.ai.concurrency.time.time") as mock_time:
            # All calls return the same frozen time — all timestamps are "recent"
            mock_time.return_value = BASE_TIME

            # Trigger 5 rate-limit errors (threshold is >= 5)
            for _ in range(5):
                pool.record_429()

        assert pool.current_workers == 4

    def test_429_below_threshold_no_scale_down(self):
        """4 429s in 300s window — below threshold, no scale-down."""
        pool = AdaptiveWorkerPool(max_workers=5, min_workers=1)

        with patch("docket.ai.concurrency.time.time") as mock_time:
            mock_time.return_value = BASE_TIME

            for _ in range(4):
                pool.record_429()

        assert pool.current_workers == 5

    def test_min_workers_floor(self):
        """Pool at min_workers stays at min even under heavy 429 storm."""
        pool = AdaptiveWorkerPool(max_workers=3, min_workers=1)
        pool.current_workers = 1  # already at floor

        with patch("docket.ai.concurrency.time.time") as mock_time:
            mock_time.return_value = BASE_TIME

            for _ in range(10):
                pool.record_429()

        assert pool.current_workers == 1

    def test_records_timestamp(self):
        """Each record_429 appends a timestamp to the internal deque."""
        pool = AdaptiveWorkerPool(max_workers=5, min_workers=1)

        with patch("docket.ai.concurrency.time.time") as mock_time:
            mock_time.return_value = BASE_TIME

            pool.record_429()
            pool.record_429()

        assert len(pool._429_timestamps) == 2

    def test_deque_capped_at_20(self):
        """Deque is bounded at maxlen=20; oldest entries are dropped."""
        pool = AdaptiveWorkerPool(max_workers=25, min_workers=1)
        pool.current_workers = 25  # give lots of room so scale-down doesn't interfere

        with patch("docket.ai.concurrency.time.time") as mock_time:
            mock_time.return_value = BASE_TIME

            for _ in range(25):
                pool.record_429()

        assert len(pool._429_timestamps) == 20


# ---------------------------------------------------------------------------
# TestConsiderScaleUp
# ---------------------------------------------------------------------------


class TestConsiderScaleUp:
    def test_scale_up_after_cool_down(self):
        """After 600s cool-down with no recent 429s, workers increment."""
        pool = AdaptiveWorkerPool(max_workers=5, min_workers=1)
        pool.current_workers = 3

        with patch("docket.ai.concurrency.time.time") as mock_time:
            # Simulate a prior scale-down 601 seconds ago (past the 600s gate)
            scale_down_time = BASE_TIME
            mock_time.return_value = scale_down_time
            pool._last_scale_down = scale_down_time

            # Now advance to 601s later — cool-down window has expired
            now = BASE_TIME + 601
            mock_time.return_value = now

            pool.consider_scale_up()

        assert pool.current_workers == 4

    def test_cool_down_blocks_scale_up(self):
        """Within 600s of last scale-down, consider_scale_up is a no-op."""
        pool = AdaptiveWorkerPool(max_workers=5, min_workers=1)
        pool.current_workers = 3

        with patch("docket.ai.concurrency.time.time") as mock_time:
            scale_down_time = BASE_TIME
            pool._last_scale_down = scale_down_time

            # Only 100s elapsed — still in cool-down
            mock_time.return_value = BASE_TIME + 100

            pool.consider_scale_up()

        assert pool.current_workers == 3

    def test_recent_429s_block_scale_up(self):
        """Even after cool-down, a 429 within the last 600s prevents scale-up."""
        pool = AdaptiveWorkerPool(max_workers=5, min_workers=1)
        pool.current_workers = 3

        with patch("docket.ai.concurrency.time.time") as mock_time:
            # Record a 429 at BASE_TIME
            mock_time.return_value = BASE_TIME
            pool._429_timestamps.append(BASE_TIME)
            pool._last_scale_down = BASE_TIME - 700  # cool-down already expired

            # Now it's 200s later — the 429 is 200s old, well within the 600s window
            mock_time.return_value = BASE_TIME + 200

            pool.consider_scale_up()

        assert pool.current_workers == 3

    def test_max_workers_ceiling(self):
        """consider_scale_up doesn't push current_workers above max_workers."""
        pool = AdaptiveWorkerPool(max_workers=5, min_workers=1)
        pool.current_workers = 5  # already at max

        with patch("docket.ai.concurrency.time.time") as mock_time:
            pool._last_scale_down = BASE_TIME - 700
            mock_time.return_value = BASE_TIME

            pool.consider_scale_up()

        assert pool.current_workers == 5

    def test_no_prior_scale_down_allows_scale_up(self):
        """Fresh pool (never scaled down) with current < max and no 429s scales up."""
        pool = AdaptiveWorkerPool(max_workers=5, min_workers=1)
        # Manually lower current_workers to simulate a pool that somehow fell
        # below max without a scale-down event (edge-case sanity check)
        pool.current_workers = 3
        assert pool._last_scale_down is None

        with patch("docket.ai.concurrency.time.time") as mock_time:
            mock_time.return_value = BASE_TIME

            pool.consider_scale_up()

        assert pool.current_workers == 4

    def test_fresh_pool_at_max_is_noop(self):
        """Fresh pool starting at max_workers — consider_scale_up is a no-op."""
        pool = AdaptiveWorkerPool(max_workers=5, min_workers=1)
        assert pool.current_workers == 5

        with patch("docket.ai.concurrency.time.time") as mock_time:
            mock_time.return_value = BASE_TIME

            pool.consider_scale_up()

        assert pool.current_workers == 5


# ---------------------------------------------------------------------------
# TestCountInWindow
# ---------------------------------------------------------------------------


class TestCountInWindow:
    def test_count_in_window_filters_old_timestamps(self):
        """Only timestamps within the window are counted."""
        pool = AdaptiveWorkerPool()

        now = BASE_TIME
        # 5 old timestamps (> 300s ago)
        for offset in range(5):
            pool._429_timestamps.append(now - 400 - offset)
        # 3 recent timestamps (within last 300s)
        for offset in range(3):
            pool._429_timestamps.append(now - 100 + offset)

        with patch("docket.ai.concurrency.time.time") as mock_time:
            mock_time.return_value = now
            count = pool._count_in_window(seconds=300)

        assert count == 3

    def test_count_in_window_empty(self):
        """Returns 0 when no timestamps have been recorded."""
        pool = AdaptiveWorkerPool()

        with patch("docket.ai.concurrency.time.time") as mock_time:
            mock_time.return_value = BASE_TIME
            count = pool._count_in_window(seconds=300)

        assert count == 0
