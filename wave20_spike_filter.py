"""
wave20_spike_filter.py
Wave 20: Correlation / Price-Spike Filter
==========================================
Prevents entering trades in the first N seconds after a sharp
price spike (sudden large move in a single tick).

Logic:
- Monitor each new tick's price change vs rolling avg change
- If spike_ratio >= threshold: set a cooldown, block signals
- Also blocks if 3+ large spikes happened in last 5 minutes

Usage:
    from wave20_spike_filter import spike_filter
    ok, reason = spike_filter.check(current_price, prev_price, closes)
"""

import time
import logging
from collections import deque

logger = logging.getLogger(__name__)


class SpikeFilter:
    """
    Detects and blocks trading after abnormal price spikes.
    """

    def __init__(
        self,
        spike_ratio_threshold: float = 4.0,   # spike > 4x avg move → block
        cooldown_sec: float = 90.0,            # block for 90s after spike
        lookback: int = 20,                    # avg over last 20 tick-changes
        cluster_window_sec: float = 300.0,     # 5-min spike cluster window
        cluster_count_limit: int = 3,          # block if ≥3 spikes in window
    ):
        self.spike_ratio_threshold = spike_ratio_threshold
        self.cooldown_sec = cooldown_sec
        self.lookback = lookback
        self.cluster_window_sec = cluster_window_sec
        self.cluster_count_limit = cluster_count_limit

        self._recent_changes: deque = deque(maxlen=lookback)
        self._spike_timestamps: deque = deque(maxlen=20)
        self._blocked_until: float = 0.0

    def check(self, current_price: float, prev_price: float, closes: list = None):
        """
        Returns (allowed: bool, reason: str).
        Call each tick before generating a signal.
        """
        try:
            now = time.time()
            tick_change = abs(current_price - prev_price)

            # Feed the rolling window
            if tick_change > 0:
                self._recent_changes.append(tick_change)

            # Check if currently in cooldown
            if now < self._blocked_until:
                remaining = int(self._blocked_until - now)
                return False, f"SPIKE_COOLDOWN:{remaining}s"

            # Need enough history to compute avg
            if len(self._recent_changes) < 5:
                return True, "OK"

            avg_change = sum(self._recent_changes) / len(self._recent_changes)
            if avg_change == 0:
                return True, "OK"

            spike_ratio = tick_change / avg_change

            if spike_ratio >= self.spike_ratio_threshold:
                # Record this spike
                self._spike_timestamps.append(now)
                self._blocked_until = now + self.cooldown_sec

                logger.debug(
                    f"[SPIKE FILTER] SPIKE detected ratio={spike_ratio:.1f}x avg "
                    f"(tick={tick_change:.4f} avg={avg_change:.4f}) — "
                    f"blocking {self.cooldown_sec}s"
                )
                return False, f"SPIKE_DETECTED:ratio={spike_ratio:.1f}x"

            # Cluster check: too many spikes in recent window
            recent_spikes = [t for t in self._spike_timestamps if now - t <= self.cluster_window_sec]
            if len(recent_spikes) >= self.cluster_count_limit:
                self._blocked_until = now + self.cooldown_sec
                logger.debug(
                    f"[SPIKE FILTER] CLUSTER detected: {len(recent_spikes)} spikes in "
                    f"{self.cluster_window_sec}s — blocking {self.cooldown_sec}s"
                )
                return False, f"SPIKE_CLUSTER:{len(recent_spikes)}_in_5min"

            return True, "OK"

        except Exception as e:
            logger.debug(f"[SPIKE FILTER] Error: {e}")
            return True, "OK"  # Fail-open: don't block on errors

    def is_blocked(self) -> bool:
        return time.time() < self._blocked_until

    def info(self) -> dict:
        now = time.time()
        recent_spikes = [t for t in self._spike_timestamps if now - t <= self.cluster_window_sec]
        return {
            "blocked": self.is_blocked(),
            "blocked_until_sec": max(0, int(self._blocked_until - now)),
            "spikes_in_5min": len(recent_spikes),
            "avg_tick_change": round(
                sum(self._recent_changes) / len(self._recent_changes), 5
            ) if self._recent_changes else 0.0,
        }


# Module-level singleton
spike_filter = SpikeFilter()
