"""
wave359_trade_flow_levy_alpha_stable_tail_index_guard.py
=========================================================
WAVE 359 -- Trade Flow Levy Alpha-Stable Tail Index Guard
Batch 300 Landmark Module

Algorithm:
  - Collect absolute signed volumes |SV_i| from each trade tick.
  - Estimate tail index alpha via the Hill estimator:
      k = max(2, n // 4)
      Sort |SV| ascending: X_(1) <= ... <= X_(n)
      alpha_hat = ( (1/k) * sum_{i=1}^{k} log( X_(n-i+1) / X_(n-k) ) )^{-1}
  - Block when alpha_hat < alpha_low  (very heavy tail -- extreme events loom)
               or alpha_hat > alpha_high (too light tail -- anomalous regime)
  - Fail-closed on any invalid input.

Blocking reasons: HEAVY_TAIL_DETECTED, LIGHT_TAIL_DETECTED,
                  INSUFFICIENT_DATA, INPUT_VALIDATION_ERROR
"""

import math
import threading
import time
from collections import deque


class Wave359TradeFlowLevyAlphaStableTailIndexGuard:
    """Trade Flow Levy Alpha-Stable Tail Index Guard -- Wave 359."""

    HEAVY_TAIL_DETECTED = "HEAVY_TAIL_DETECTED"
    LIGHT_TAIL_DETECTED = "LIGHT_TAIL_DETECTED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INPUT_VALIDATION_ERROR = "INPUT_VALIDATION_ERROR"

    _VALID_SIDES = {"buy", "sell"}

    def __init__(
        self,
        window_size: int = 30,
        alpha_low: float = 1.2,
        alpha_high: float = 2.8,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if not isinstance(window_size, int) or isinstance(window_size, bool):
            raise TypeError("window_size must be a plain int")
        if window_size < 4:
            raise ValueError("window_size must be >= 4 (Hill estimator needs k>=2)")
        if isinstance(alpha_low, bool) or isinstance(alpha_high, bool):
            raise TypeError("alpha bounds must be numeric")
        if not isinstance(alpha_low, (int, float)):
            raise TypeError("alpha_low must be numeric")
        if not isinstance(alpha_high, (int, float)):
            raise TypeError("alpha_high must be numeric")
        if alpha_low <= 0:
            raise ValueError("alpha_low must be > 0")
        if alpha_high <= alpha_low:
            raise ValueError("alpha_high must be > alpha_low")
        if isinstance(cooldown_seconds, bool):
            raise TypeError("cooldown_seconds must be numeric")
        if not isinstance(cooldown_seconds, (int, float)):
            raise TypeError("cooldown_seconds must be numeric")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")

        self._window_size = window_size
        self._alpha_low = float(alpha_low)
        self._alpha_high = float(alpha_high)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._abs_volumes: deque = deque(maxlen=window_size)
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
            self._abs_volumes.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    def update(self, volume, side, timestamp) -> None:
        """
        Record one trade tick.

        Parameters
        ----------
        volume    : numeric -- trade volume (>= 0)
        side      : str     -- "buy" or "sell"
        timestamp : numeric -- monotonic timestamp (seconds)
        """
        with self._lock:
            # --- validate volume ---
            if isinstance(volume, bool):
                self._trip(self.INPUT_VALIDATION_ERROR)
                return
            if not isinstance(volume, (int, float)):
                self._trip(self.INPUT_VALIDATION_ERROR)
                return
            if not math.isfinite(volume) or volume < 0:
                self._trip(self.INPUT_VALIDATION_ERROR)
                return

            # --- validate side ---
            if not isinstance(side, str):
                self._trip(self.INPUT_VALIDATION_ERROR)
                return
            if side not in self._VALID_SIDES:
                self._trip(self.INPUT_VALIDATION_ERROR)
                return

            # --- validate timestamp ---
            if isinstance(timestamp, bool):
                self._trip(self.INPUT_VALIDATION_ERROR)
                return
            if not isinstance(timestamp, (int, float)):
                self._trip(self.INPUT_VALIDATION_ERROR)
                return
            if not math.isfinite(timestamp):
                self._trip(self.INPUT_VALIDATION_ERROR)
                return

            # Signed volume: buy = +volume, sell = -volume
            signed_vol = float(volume) if side == "buy" else -float(volume)
            abs_vol = abs(signed_vol)
            self._abs_volumes.append(abs_vol)

            if len(self._abs_volumes) < self._window_size:
                return

            self._evaluate()

    def is_blocked(self, current_time=None) -> bool:
        """Return True if the guard is currently blocking."""
        with self._lock:
            if current_time is None:
                current_time = time.monotonic()
            if isinstance(current_time, bool):
                return True
            if not isinstance(current_time, (int, float)):
                return True
            return current_time < self._blocked_until

    def is_entry_blocked(self, bid, ask, ts) -> bool:
        """
        Convenience wrapper compatible with the standard guard interface.
        Interprets bid as volume and ask as side label (cast to str).
        """
        self.update(bid, str(ask), ts)
        return self.is_blocked()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _hill_estimator(self, data: list) -> float:
        """
        Compute Hill tail-index estimator.

        Parameters
        ----------
        data : list of float -- |SV| values (must have len >= 4)

        Returns
        -------
        float -- estimated alpha (> 0), or raises ValueError on degenerate input
        """
        sorted_data = sorted(data)           # ascending
        n = len(sorted_data)
        k = max(2, n // 4)
        x_nk = sorted_data[n - k - 1]       # X_(n-k)  (0-indexed)

        if x_nk <= 0:
            raise ValueError("Pivot value X_(n-k) is <= 0; cannot compute Hill estimator")

        log_sum = 0.0
        for i in range(1, k + 1):
            x_i = sorted_data[n - i]         # X_(n-i+1) in 0-indexed = sorted_data[n-i]
            if x_i <= 0:
                raise ValueError("Non-positive order statistic encountered")
            log_sum += math.log(x_i / x_nk)

        if log_sum == 0.0:
            raise ValueError("Degenerate: all top-k values equal the pivot")

        alpha_hat = k / log_sum
        return alpha_hat

    def _evaluate(self) -> None:
        """Run Hill estimator and trip appropriate reason if out of bounds."""
        data = list(self._abs_volumes)

        # Filter out zero volumes (cannot take log of 0)
        nonzero = [v for v in data if v > 0]

        if len(nonzero) < 4:
            self._trip(self.INSUFFICIENT_DATA)
            return

        try:
            alpha_hat = self._hill_estimator(nonzero)
        except ValueError:
            self._trip(self.INSUFFICIENT_DATA)
            return

        if alpha_hat < self._alpha_low:
            self._trip(self.HEAVY_TAIL_DETECTED)
        elif alpha_hat > self._alpha_high:
            self._trip(self.LIGHT_TAIL_DETECTED)

    def _trip(self, reason: str) -> None:
        self._last_reason = reason
        self._blocked_until = time.monotonic() + self._cooldown_seconds
