"""
Wave 341 -- Trade Flow Inter-Arrival Time Coefficient-of-Variation Guard
=========================================================================
Monitors the coefficient of variation (CoV = std / mean) of trade inter-arrival
times.  High CoV indicates bursty, clustered arrivals (consistent with informed
trading or algo bursts), while low CoV indicates overly regular arrivals
(potential wash trades or spoofing).

Methodology
-----------
* Record timestamps of each trade tick.
* Compute inter-arrival time delta_i = t_i - t_{i-1}.
* Over rolling window of `window_size` deltas:
  - CoV = std(deltas) / mean(deltas)
* Block when CoV >= `high_cov_threshold` (bursty regime) OR
             CoV <  `low_cov_threshold`  (suspiciously regular regime).

Blocking reasons
----------------
BURSTY_INTER_ARRIVAL    -- CoV >= high_cov_threshold
REGULAR_INTER_ARRIVAL   -- CoV < low_cov_threshold
INPUT_VALIDATION_ERROR  -- malformed arguments

Public API (standardised)
-------------------------
update(timestamp)              -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave341TradeFlowInterArrivalCovGuard"]

_REASON_BURST = "BURSTY_INTER_ARRIVAL"
_REASON_REG   = "REGULAR_INTER_ARRIVAL"
_REASON_VAL   = "INPUT_VALIDATION_ERROR"


class Wave341TradeFlowInterArrivalCovGuard:
    """Trade inter-arrival time coefficient-of-variation guard."""

    def __init__(
        self,
        window_size: int = 20,
        high_cov_threshold: float = 3.0,
        low_cov_threshold: float = 0.05,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 4 or high_cov_threshold <= 0 or low_cov_threshold < 0:
            raise ValueError("Invalid inter-arrival CoV guard parameters.")
        self._window    = int(window_size)
        self._high_cov  = float(high_cov_threshold)
        self._low_cov   = float(low_cov_threshold)
        self._cooldown  = float(cooldown_seconds)

        self._lock      = threading.RLock()
        self._prev_ts: Optional[float] = None
        self._deltas: deque = deque(maxlen=window_size)
        self._blocked_until = 0.0
        self._last_reason   = ""

    # ------------------------------------------------------------------
    def update(self, timestamp: float) -> None:
        with self._lock:
            if isinstance(timestamp, bool):
                self._block(time.monotonic(), _REASON_VAL)
                return
            if not isinstance(timestamp, (int, float)):
                self._block(time.monotonic(), _REASON_VAL)
                return

            ts = float(timestamp)
            if self._prev_ts is not None:
                delta = ts - self._prev_ts
                if delta < 0:
                    self._block(ts, _REASON_VAL)
                    self._prev_ts = ts
                    return
                if delta > 0:  # only add strictly positive deltas
                    self._deltas.append(delta)

            self._prev_ts = ts

            if len(self._deltas) < self._window:
                return

            deltas = list(self._deltas)
            n      = len(deltas)
            mean_d = sum(deltas) / n
            if mean_d <= 0:
                return
            var_d  = sum((d - mean_d) ** 2 for d in deltas) / n
            std_d  = math.sqrt(var_d)
            cov    = std_d / mean_d

            if cov >= self._high_cov:
                self._block(ts, _REASON_BURST)
            elif cov < self._low_cov:
                self._block(ts, _REASON_REG)

    def _block(self, timestamp: float, reason: str) -> None:
        self._blocked_until = time.monotonic() + self._cooldown
        self._last_reason   = reason

    # ------------------------------------------------------------------
    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            t = time.monotonic() if current_time is None else current_time
            return t < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: float) -> bool:
        return self.is_blocked(ts)

    def reset(self) -> None:
        with self._lock:
            self._prev_ts = None
            self._deltas.clear()
            self._blocked_until = 0.0
            self._last_reason   = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
