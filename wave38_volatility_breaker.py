"""
Wave 38: VolatilityBreaker
If the current ATR (Average True Range proxy over last 20 ticks) exceeds
2.5x the baseline ATR (average over last 100 ticks), block new entries
for 90 seconds to avoid entering during extreme volatility spikes.
This complements Wave 20 (Spike Filter) which checks single-tick spikes.
Wave 38 looks at sustained elevated volatility over a rolling window.
"""

import math
import threading
import time
from collections import deque


class VolatilityBreaker:
    """
    Monitors rolling ATR vs baseline ATR.
    If ATR_current / ATR_baseline >= SPIKE_RATIO: block entries for BLOCK_SECONDS.
    Prevents trading during sustained high-volatility periods (e.g. news aftermath).
    """

    SHORT_WINDOW = 20          # Ticks for current ATR
    LONG_WINDOW = 100          # Ticks for baseline ATR
    SPIKE_RATIO = 2.5          # Trigger if current ATR >= 2.5x baseline
    BLOCK_SECONDS = 90         # Block duration on trigger
    MIN_TICKS = 25             # Minimum ticks before checking

    def __init__(self):
        self._lock = threading.RLock()
        self._short_prices = deque(maxlen=self.SHORT_WINDOW + 1)
        self._long_prices = deque(maxlen=self.LONG_WINDOW + 1)
        self._block_until = 0.0
        self._current_atr = 0.0
        self._baseline_atr = 0.0
        self._last_ratio = 0.0
        self.total_spikes = 0
        self.total_blocks = 0
        self._tick_count = 0

    def reset(self):
        """Reset internal buffers and unblock."""
        with self._lock:
            self._short_prices.clear()
            self._long_prices.clear()
            self._block_until = 0.0
            self._current_atr = 0.0
            self._baseline_atr = 0.0
            self._last_ratio = 0.0
            self.total_spikes = 0
            self.total_blocks = 0
            self._tick_count = 0

    def update(self, price: float, now_ts: float = None):
        """Feed current price each tick."""
        if (
            price is None
            or isinstance(price, bool)
            or not isinstance(price, (int, float))
            or not math.isfinite(price)
            or price <= 0
        ):
            return

        with self._lock:
            self._short_prices.append(float(price))
            self._long_prices.append(float(price))
            self._tick_count += 1

            if self._tick_count >= self.MIN_TICKS:
                self._evaluate(now_ts)

    def _calc_atr(self, prices) -> float:
        """Simple ATR proxy: mean absolute tick-to-tick change."""
        if len(prices) < 2:
            return 0.0
        changes = []
        for i in range(1, len(prices)):
            p1, p2 = prices[i - 1], prices[i]
            if math.isfinite(p1) and math.isfinite(p2):
                changes.append(abs(p2 - p1))
        return sum(changes) / len(changes) if changes else 0.0

    def _evaluate(self, now_ts: float = None):
        short_list = list(self._short_prices)
        long_list = list(self._long_prices)
        self._current_atr = self._calc_atr(short_list)
        self._baseline_atr = self._calc_atr(long_list)

        if self._baseline_atr <= 0:
            return

        ratio = self._current_atr / self._baseline_atr
        self._last_ratio = ratio

        if ratio >= self.SPIKE_RATIO:
            now = now_ts if now_ts is not None else time.time()
            if now >= self._block_until:
                self.total_spikes += 1
                self.total_blocks += 1
            self._block_until = max(self._block_until, now + self.BLOCK_SECONDS)

    def is_entry_blocked(self, now_ts: float = None) -> bool:
        """Returns True if volatility block is active."""
        now = now_ts if now_ts is not None else time.time()
        with self._lock:
            return now < self._block_until

    def seconds_remaining(self, now_ts: float = None) -> float:
        now = now_ts if now_ts is not None else time.time()
        with self._lock:
            return max(0.0, self._block_until - now)

    def info(self, now_ts: float = None) -> dict:
        now = now_ts if now_ts is not None else time.time()
        with self._lock:
            return {
                "short_window_ticks": self.SHORT_WINDOW,
                "long_window_ticks": self.LONG_WINDOW,
                "spike_ratio_threshold": self.SPIKE_RATIO,
                "block_seconds": self.BLOCK_SECONDS,
                "currently_blocked": now < self._block_until,
                "seconds_remaining": round(max(0.0, self._block_until - now), 1),
                "current_atr": round(self._current_atr, 4),
                "baseline_atr": round(self._baseline_atr, 4),
                "last_ratio": round(self._last_ratio, 3),
                "total_spikes": self.total_spikes,
                "total_blocks": self.total_blocks,
            }


# Module-level singleton
volatility_breaker = VolatilityBreaker()
