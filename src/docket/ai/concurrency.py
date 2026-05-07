from __future__ import annotations

import logging
import time
from collections import deque

log = logging.getLogger(__name__)


class AdaptiveWorkerPool:
    """Adjusts worker count based on observed 429 frequency.
    Shared between backfill driver and live ai_items task so backfill
    never monopolizes Anthropic rate-limit budget at the cost of
    new-meeting ingestion."""

    def __init__(self, max_workers: int = 5, min_workers: int = 1):
        self.max_workers = max_workers
        self.min_workers = min_workers
        self.current_workers = max_workers
        self._429_timestamps: deque[float] = deque(maxlen=20)
        self._last_scale_down: float | None = None

    def record_429(self) -> None:
        """Called after each rate-limit error. May scale workers down."""
        self._429_timestamps.append(time.time())
        if self._count_in_window(seconds=300) >= 5:
            new_count = max(self.min_workers, self.current_workers - 1)
            if new_count != self.current_workers:
                log.warning("scaling workers down: %d → %d (429 storm)",
                           self.current_workers, new_count)
                self.current_workers = new_count
                self._last_scale_down = time.time()

    def consider_scale_up(self) -> None:
        """Called periodically by the worker pool. Only scales up after
        a 10-minute cool-down with zero 429s."""
        if (self._last_scale_down
                and time.time() - self._last_scale_down < 600):
            return
        if self._count_in_window(seconds=600) == 0:
            new_count = min(self.max_workers, self.current_workers + 1)
            if new_count != self.current_workers:
                log.info("scaling workers up: %d → %d (cool-down clear)",
                        self.current_workers, new_count)
                self.current_workers = new_count

    def _count_in_window(self, seconds: int) -> int:
        cutoff = time.time() - seconds
        return sum(1 for t in self._429_timestamps if t > cutoff)
