"""
Wave 42: TickVolumeFilter
Requires minimum tick velocity before allowing entries.
If fewer than MIN_TICKS ticks arrive per WINDOW_SEC seconds → dead market → block entries.
"""
import time
import logging
from collections import deque

logger = logging.getLogger(__name__)

_WINDOW_SEC = 10.0     # rolling window
_MIN_TICKS  = 4        # minimum ticks required in that window (dead-market if below)


class TickVolumeFilter:
    """
    Tracks tick arrival rate. If tick velocity is below the minimum threshold
    in a rolling window, the market is considered dead and entries are blocked.
    """

    def __init__(self, window_sec: float = _WINDOW_SEC, min_ticks: int = _MIN_TICKS) -> None:
        self._window_sec = window_sec
        self._min_ticks = min_ticks
        self._tick_times: deque = deque(maxlen=500)
        self._blocked_count: int = 0

    # ------------------------------------------------------------------
    def update(self) -> None:
        """Call once per tick to record arrival time."""
        self._tick_times.append(time.time())

    # ------------------------------------------------------------------
    def is_entry_blocked(self) -> bool:
        """Return True if tick velocity is below minimum (dead market)."""
        now = time.time()
        cutoff = now - self._window_sec
        # Count ticks in the rolling window
        recent = sum(1 for t in self._tick_times if t >= cutoff)

        if recent < self._min_ticks:
            self._blocked_count += 1
            logger.debug(
                f"[TICK VOLUME FILTER] Dead market — only {recent} ticks "
                f"in last {self._window_sec:.0f}s (min={self._min_ticks})"
            )
            return True
        return False

    # ------------------------------------------------------------------
    def get_tick_rate(self) -> float:
        """Returns ticks-per-second rate over the rolling window."""
        now = time.time()
        cutoff = now - self._window_sec
        recent = sum(1 for t in self._tick_times if t >= cutoff)
        return round(recent / self._window_sec, 2)

    # ------------------------------------------------------------------
    def info(self) -> dict:
        return {
            "tick_rate_per_sec": self.get_tick_rate(),
            "window_sec": self._window_sec,
            "min_ticks_required": self._min_ticks,
            "total_ticks_tracked": len(self._tick_times),
            "blocked_count_total": self._blocked_count,
        }


# Module-level singleton
tick_volume_filter = TickVolumeFilter()
