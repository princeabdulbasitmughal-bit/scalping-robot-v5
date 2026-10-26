"""
WAVE 351 -- Trade Flow Tick-Rule Autocorrelation Guard
=======================================================
Algorithm:
  - Classify each trade as up-tick (+1), down-tick (-1), or zero-tick (0)
    based on the price change vs the previous trade price.
  - Maintain a rolling deque of the last window_size tick signs.
  - Compute the lag-1 autocorrelation of the tick-sign series.
  - Block when |autocorrelation| >= autocorr_threshold, indicating a strong
    directional momentum regime.
Blocking reasons: TICK_AUTOCORRELATION_BREACH, INSUFFICIENT_VARIANCE,
                  INPUT_VALIDATION_ERROR
"""

import time
import threading
import math
from collections import deque


class Wave351TradeFlowTickRuleAutocorrelationGuard:
    """Trade Flow Tick-Rule Autocorrelation Guard (Wave 351)."""

    REASON_BREACH = "TICK_AUTOCORRELATION_BREACH"
    REASON_VARIANCE = "INSUFFICIENT_VARIANCE"
    REASON_INPUT = "INPUT_VALIDATION_ERROR"

    def __init__(
        self,
        window_size: int = 20,
        autocorr_threshold: float = 0.50,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if isinstance(window_size, bool) or not isinstance(window_size, int):
            raise TypeError("window_size must be a positive int")
        if window_size < 3:
            raise ValueError("window_size must be >= 3 (need at least lag-1 pairs)")
        if isinstance(autocorr_threshold, bool) or not isinstance(
            autocorr_threshold, (int, float)
        ):
            raise TypeError("autocorr_threshold must be a positive number")
        if not (0 < autocorr_threshold <= 1.0):
            raise ValueError("autocorr_threshold must be in (0, 1]")
        if isinstance(cooldown_seconds, bool) or not isinstance(
            cooldown_seconds, (int, float)
        ):
            raise TypeError("cooldown_seconds must be a positive number")
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be > 0")

        self._window_size = window_size
        self._autocorr_threshold = float(autocorr_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._tick_signs: deque = deque(maxlen=window_size)
        self._last_price: float | None = None
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    def reset(self) -> None:
        """Clear all rolling state and lift any active block."""
        with self._lock:
            self._tick_signs.clear()
            self._last_price = None
            self._blocked_until = 0.0
            self._last_reason = ""

    def update(self, price: float, volume: float, timestamp: float) -> None:
        """
        Ingest one trade tick.

        Parameters
        ----------
        price     : trade price (positive float)
        volume    : trade volume (positive float)
        timestamp : monotonic timestamp (positive float)
        """
        with self._lock:
            # --- Validation (fail-closed) ---
            for name, val in [
                ("price", price),
                ("volume", volume),
                ("timestamp", timestamp),
            ]:
                if isinstance(val, bool):
                    self._set_block(self.REASON_INPUT)
                    return
                if not isinstance(val, (int, float)):
                    self._set_block(self.REASON_INPUT)
                    return

            if price <= 0:
                self._set_block(self.REASON_INPUT)
                return
            if volume <= 0:
                self._set_block(self.REASON_INPUT)
                return
            if timestamp <= 0:
                self._set_block(self.REASON_INPUT)
                return

            # --- Tick-rule classification ---
            if self._last_price is not None:
                delta = price - self._last_price
                if delta > 0:
                    sign = 1
                elif delta < 0:
                    sign = -1
                else:
                    sign = 0
                self._tick_signs.append(sign)

            self._last_price = float(price)

            # --- Check autocorrelation (only when window is full) ---
            if len(self._tick_signs) >= self._window_size:
                acf = self._lag1_autocorr(list(self._tick_signs))
                if acf is None:
                    # Zero-variance series (all ticks identical) -- block conservatively
                    self._set_block(self.REASON_VARIANCE)
                elif abs(acf) >= self._autocorr_threshold:
                    self._set_block(self.REASON_BREACH)

    def is_blocked(self, current_time: float | None = None) -> bool:
        """Return True if a block is currently active."""
        if current_time is None:
            current_time = time.monotonic()
        with self._lock:
            return current_time < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: float) -> bool:
        """Convenience wrapper: validate price/ts then delegate to is_blocked."""
        if isinstance(bid, bool) or isinstance(ask, bool) or isinstance(ts, bool):
            with self._lock:
                self._set_block(self.REASON_INPUT)
            return True
        if (
            not isinstance(bid, (int, float))
            or not isinstance(ask, (int, float))
            or not isinstance(ts, (int, float))
        ):
            with self._lock:
                self._set_block(self.REASON_INPUT)
            return True
        if bid <= 0 or ask <= 0 or ts <= 0:
            with self._lock:
                self._set_block(self.REASON_INPUT)
            return True
        return self.is_blocked(current_time=ts)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_block(self, reason: str) -> None:
        """Set block (must be called with _lock held)."""
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason = reason

    @staticmethod
    def _lag1_autocorr(series: list) -> float | None:
        """
        Compute the Pearson lag-1 autocorrelation for a list of numbers.
        Returns None when the variance is zero (constant series).
        """
        n = len(series)
        if n < 2:
            return None

        mean = sum(series) / n
        variance = sum((x - mean) ** 2 for x in series) / n
        if variance < 1e-12:
            return None  # zero-variance -- signal INSUFFICIENT_VARIANCE

        # Lag-1 covariance using n-1 pairs
        cov = sum(
            (series[i] - mean) * (series[i + 1] - mean) for i in range(n - 1)
        ) / (n - 1)

        return cov / variance
