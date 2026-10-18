"""
Wave 36: SpreadMomentumGuard
If the spread widens 3x or more over the last 5 ticks (liquidity thinning fast),
block new entries for 60 seconds to avoid entering during illiquid spikes.
"""

import math
import threading
import time
from collections import deque


class SpreadMomentumGuard:
    """
    Monitors spread momentum. If spread expands >= 3x in last 5 ticks,
    blocks new entries for 60 seconds (configurable).
    """

    SPIKE_RATIO = 3.0          # 3x spread widening triggers block
    WINDOW = 5                 # Number of recent spreads to compare
    BLOCK_SECONDS = 60         # How long to block after spike
    MIN_TICKS = 3              # Minimum ticks before we start checking

    def __init__(self):
        self._lock = threading.RLock()
        self._spread_history = deque(maxlen=self.WINDOW + 5)
        self._block_until = 0.0
        self.total_spikes_detected = 0
        self.total_blocks = 0
        self.last_spike_ratio = 0.0
        self.last_spread = 0.0

    def reset(self) -> None:
        """Reset internal metrics, spread history, and blocks."""
        with self._lock:
            self._spread_history.clear()
            self._block_until = 0.0
            self.total_spikes_detected = 0
            self.total_blocks = 0
            self.last_spike_ratio = 0.0
            self.last_spread = 0.0

    def update(self, spread_pips: float, now_ts: float = None):
        """Feed current spread. Call every tick."""
        if (
            spread_pips is None
            or isinstance(spread_pips, bool)
            or not isinstance(spread_pips, (int, float))
            or not math.isfinite(spread_pips)
            or spread_pips <= 0
        ):
            return

        with self._lock:
            self._spread_history.append(float(spread_pips))
            self.last_spread = float(spread_pips)

            if len(self._spread_history) >= self.MIN_TICKS:
                self._check_spike(now_ts)

    def _check_spike(self, now_ts: float = None):
        spreads = list(self._spread_history)
        # Baseline = average of all but last tick
        if len(spreads) < 2:
            return
        baseline = sum(spreads[:-1]) / len(spreads[:-1])
        current = spreads[-1]
        if baseline <= 0:
            return
        ratio = current / baseline
        self.last_spike_ratio = ratio
        if ratio >= self.SPIKE_RATIO:
            now = now_ts if now_ts is not None else time.time()
            if now >= self._block_until:
                # New spike - count new event
                self.total_spikes_detected += 1
                self.total_blocks += 1
            # Extend block window to protect against prolonged illiquidity
            self._block_until = max(self._block_until, now + self.BLOCK_SECONDS)

    def is_entry_blocked(self, now_ts: float = None) -> bool:
        """Returns True if spread spike block is active."""
        now = now_ts if now_ts is not None else time.time()
        with self._lock:
            return now < self._block_until

    def is_blocked(self, now_ts: float = None) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked(now_ts=now_ts)

    def seconds_remaining(self, now_ts: float = None) -> float:
        """Seconds until spread block expires."""
        now = now_ts if now_ts is not None else time.time()
        with self._lock:
            return max(0.0, self._block_until - now)

    def info(self, now_ts: float = None) -> dict:
        now = now_ts if now_ts is not None else time.time()
        with self._lock:
            return {
                "spike_ratio_threshold": self.SPIKE_RATIO,
                "window_ticks": self.WINDOW,
                "block_seconds": self.BLOCK_SECONDS,
                "currently_blocked": now < self._block_until,
                "seconds_remaining": round(max(0.0, self._block_until - now), 1),
                "last_spread_pips": round(self.last_spread, 2),
                "last_spike_ratio": round(self.last_spike_ratio, 2),
                "total_spikes_detected": self.total_spikes_detected,
                "total_blocks": self.total_blocks,
            }


# Module-level singleton
spread_momentum_guard = SpreadMomentumGuard()


def is_entry_blocked(now_ts: float = None) -> bool:
    """Module-level risk interface check."""
    return spread_momentum_guard.is_entry_blocked(now_ts=now_ts)


def is_blocked(now_ts: float = None) -> bool:
    """Module-level alias for is_entry_blocked."""
    return spread_momentum_guard.is_blocked(now_ts=now_ts)


def update(spread_pips: float, now_ts: float = None) -> None:
    """Module-level alias for update."""
    return spread_momentum_guard.update(spread_pips=spread_pips, now_ts=now_ts)

