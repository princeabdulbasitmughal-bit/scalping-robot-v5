"""
Wave 396 -- Microstructure Burst Kurtosis Guard
===============================================
Monitors sample kurtosis of high-frequency price returns over a rolling window.
Excessive kurtosis indicates extreme leptokurtic return shocks, discontinuous jumps,
or predatory fat-tailed distribution anomalies.

Methodology
-----------
* Observes midprice returns: r_t = (P_t - P_{t-1}) / P_{t-1}.
* Maintains a rolling window of returns of size `window_size`.
* Computes sample kurtosis:
    m4 = mean((r_i - mean(r))^4)
    m2 = mean((r_i - mean(r))^2)
    kurtosis = m4 / (m2^2)
* If kurtosis >= `kurtosis_threshold`, blocks trading for `cooldown_seconds`.
* If variance is zero (no movement), kurtosis is well-behaved (no block).

Blocking reasons
----------------
SUPERCRITICAL_RETURN_KURTOSIS -- leptokurtic jump risk beyond safety ceiling
INPUT_VALIDATION_ERROR        -- invalid prices, non-monotonic timestamp, or non-numeric

Public API (standardised)
-------------------------
update(bid, ask, timestamp)    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave396MicrostructureBurstKurtosisGuard"]

_REASON_KURT = "SUPERCRITICAL_RETURN_KURTOSIS"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave396MicrostructureBurstKurtosisGuard:
    """Microstructure return distribution sample kurtosis guard."""

    def __init__(
        self,
        window_size: int = 20,
        kurtosis_threshold: float = 6.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 8 or kurtosis_threshold <= 1.0 or cooldown_seconds <= 0.0:
            raise ValueError("Invalid parameters for Wave396MicrostructureBurstKurtosisGuard")
        self._window_size = int(window_size)
        self._kurt_threshold = float(kurtosis_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._returns: deque[float] = deque(maxlen=self._window_size)
        self._last_mid: Optional[float] = None
        self._last_time: Optional[float] = None
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(self, bid: float, ask: float, timestamp: float) -> None:
        with self._lock:
            for val in (bid, ask, timestamp):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._block(_REASON_VAL)
                    return

            if bid <= 0.0 or ask <= 0.0 or bid >= ask:
                self._block(_REASON_VAL)
                return

            mid = (float(bid) + float(ask)) / 2.0
            ts = float(timestamp)

            if self._last_time is None or self._last_mid is None:
                self._last_mid = mid
                self._last_time = ts
                return

            dt = ts - self._last_time
            if dt <= 0.0:
                self._block(_REASON_VAL)
                return

            ret = (mid - self._last_mid) / self._last_mid
            self._returns.append(ret)
            self._last_mid = mid
            self._last_time = ts

            if len(self._returns) >= self._window_size:
                data = list(self._returns)
                n = len(data)
                mean_r = sum(data) / n
                m2 = sum((x - mean_r) ** 2 for x in data) / n
                if m2 > 1e-15:
                    m4 = sum((x - mean_r) ** 4 for x in data) / n
                    kurt = m4 / (m2 ** 2)
                    if kurt >= self._kurt_threshold:
                        self._block(_REASON_KURT)

    def _block(self, reason: str) -> None:
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason = reason

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            t = time.monotonic() if current_time is None else current_time
            return t < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: float) -> bool:
        return self.is_blocked(ts)

    def reset(self) -> None:
        with self._lock:
            self._returns.clear()
            self._last_mid = None
            self._last_time = None
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
