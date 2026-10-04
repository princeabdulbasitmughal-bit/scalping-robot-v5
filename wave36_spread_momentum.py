"""
Wave 36: SpreadMomentumGuard
If the spread widens 3x or more over the last 5 ticks (liquidity thinning fast),
block new entries for 60 seconds to avoid entering during illiquid spikes.
"""

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
        self._spread_history = deque(maxlen=self.WINDOW + 5)
        self._block_until = 0.0
        self.total_spikes_detected = 0
        self.total_blocks = 0
        self.last_spike_ratio = 0.0
        self.last_spread = 0.0

    def update(self, spread_pips: float):
        """Feed current spread. Call every tick."""
        if spread_pips > 0:
            self._spread_history.append(spread_pips)
            self.last_spread = spread_pips

        if len(self._spread_history) >= self.MIN_TICKS:
            self._check_spike()

    def _check_spike(self):
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
            now = time.time()
            if now >= self._block_until:
                # New spike - extend block
                self._block_until = now + self.BLOCK_SECONDS
                self.total_spikes_detected += 1
                self.total_blocks += 1

    def is_entry_blocked(self) -> bool:
        """Returns True if spread spike block is active."""
        return time.time() < self._block_until

    def seconds_remaining(self) -> float:
        """Seconds until spread block expires."""
        return max(0.0, self._block_until - time.time())

    def info(self) -> dict:
        return {
            "spike_ratio_threshold": self.SPIKE_RATIO,
            "window_ticks": self.WINDOW,
            "block_seconds": self.BLOCK_SECONDS,
            "currently_blocked": self.is_entry_blocked(),
            "seconds_remaining": round(self.seconds_remaining(), 1),
            "last_spread_pips": round(self.last_spread, 2),
            "last_spike_ratio": round(self.last_spike_ratio, 2),
            "total_spikes_detected": self.total_spikes_detected,
            "total_blocks": self.total_blocks,
        }


# Module-level singleton
spread_momentum_guard = SpreadMomentumGuard()
