"""
wave358_lob_order_size_dispersion_guard.py
===========================================
WAVE 358 -- LOB Order Size Dispersion Guard
Batch 300 Landmark Module

Algorithm:
  - At each tick record total LOB depth = bid_depth + ask_depth.
  - Maintain a rolling window of the last window_size depth values.
  - Compute Coefficient of Variation (CoV) = std(depths) / mean(depths).
  - Block when CoV >= dispersion_threshold (erratic / manipulated order sizing).
  - Fail-closed on any invalid input.

Blocking reasons: ORDER_SIZE_DISPERSION_BREACH, INSUFFICIENT_VARIANCE,
                  INPUT_VALIDATION_ERROR
"""

import math
import threading
import time
from collections import deque


class Wave358LOBOrderSizeDispersionGuard:
    """LOB Order Size Dispersion Guard -- Wave 358."""

    ORDER_SIZE_DISPERSION_BREACH = "ORDER_SIZE_DISPERSION_BREACH"
    INSUFFICIENT_VARIANCE = "INSUFFICIENT_VARIANCE"
    INPUT_VALIDATION_ERROR = "INPUT_VALIDATION_ERROR"

    def __init__(
        self,
        window_size: int = 20,
        dispersion_threshold: float = 1.0,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if not isinstance(window_size, int) or isinstance(window_size, bool):
            raise TypeError("window_size must be a plain int")
        if window_size < 2:
            raise ValueError("window_size must be >= 2")
        if isinstance(dispersion_threshold, bool):
            raise TypeError("dispersion_threshold must be a float")
        if not isinstance(dispersion_threshold, (int, float)):
            raise TypeError("dispersion_threshold must be numeric")
        if dispersion_threshold <= 0:
            raise ValueError("dispersion_threshold must be > 0")
        if isinstance(cooldown_seconds, bool):
            raise TypeError("cooldown_seconds must be a float")
        if not isinstance(cooldown_seconds, (int, float)):
            raise TypeError("cooldown_seconds must be numeric")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")

        self._window_size = window_size
        self._dispersion_threshold = float(dispersion_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._depths: deque = deque(maxlen=window_size)
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
        """Clear all state; guard becomes open."""
        with self._lock:
            self._depths.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    def update(self, bid_depth, ask_depth, timestamp) -> None:
        """
        Record one tick of LOB depth data.

        Parameters
        ----------
        bid_depth  : numeric -- total bid-side order size
        ask_depth  : numeric -- total ask-side order size
        timestamp  : numeric -- monotonic timestamp (seconds)
        """
        with self._lock:
            # Validation order: bool check BEFORE numeric check
            if isinstance(bid_depth, bool):
                self._trip(self.INPUT_VALIDATION_ERROR)
                return
            if not isinstance(bid_depth, (int, float)):
                self._trip(self.INPUT_VALIDATION_ERROR)
                return
            if not math.isfinite(bid_depth) or bid_depth < 0:
                self._trip(self.INPUT_VALIDATION_ERROR)
                return

            if isinstance(ask_depth, bool):
                self._trip(self.INPUT_VALIDATION_ERROR)
                return
            if not isinstance(ask_depth, (int, float)):
                self._trip(self.INPUT_VALIDATION_ERROR)
                return
            if not math.isfinite(ask_depth) or ask_depth < 0:
                self._trip(self.INPUT_VALIDATION_ERROR)
                return

            if isinstance(timestamp, bool):
                self._trip(self.INPUT_VALIDATION_ERROR)
                return
            if not isinstance(timestamp, (int, float)):
                self._trip(self.INPUT_VALIDATION_ERROR)
                return
            if not math.isfinite(timestamp):
                self._trip(self.INPUT_VALIDATION_ERROR)
                return

            total_depth = float(bid_depth) + float(ask_depth)
            self._depths.append(total_depth)

            # Need full window before evaluating
            if len(self._depths) < self._window_size:
                return

            self._evaluate()

    def is_blocked(self, current_time=None) -> bool:
        """Return True if the guard is currently blocking."""
        with self._lock:
            if current_time is None:
                current_time = time.monotonic()
            if isinstance(current_time, bool):
                return True  # fail-closed on bad input
            if not isinstance(current_time, (int, float)):
                return True
            return current_time < self._blocked_until

    def is_entry_blocked(self, bid, ask, ts) -> bool:
        """Convenience wrapper: update then check block status."""
        self.update(bid, ask, ts)
        return self.is_blocked()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evaluate(self) -> None:
        """Compute CoV over the rolling window and trip if >= threshold."""
        depths = list(self._depths)
        n = len(depths)
        mean = sum(depths) / n
        if mean == 0.0:
            # Cannot compute CoV; treat as zero variance, no dispersion
            return
        variance = sum((d - mean) ** 2 for d in depths) / n
        std = math.sqrt(variance)
        cov = std / mean

        if cov >= self._dispersion_threshold:
            self._trip(self.ORDER_SIZE_DISPERSION_BREACH)

    def _trip(self, reason: str) -> None:
        self._last_reason = reason
        self._blocked_until = time.monotonic() + self._cooldown_seconds
