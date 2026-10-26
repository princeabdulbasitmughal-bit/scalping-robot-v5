"""
Wave 398 -- Fractional Brownian Motion Roughness Guard
======================================================
Monitors the local Hurst roughness exponent H of high-frequency price trajectories
via a two-scale variogram estimator. Ultra-rough trajectories (H < 0.15) indicate
turbulent sub-diffusive microstructural noise and severe inventory whiplash,
while supercritical anti-persistence destabilizes standard scalping bounds.

Methodology
-----------
* Observes midprice P_t at regular or sampled time intervals.
* Tracks price differences at scale tau=1 (delta_1 = P_t - P_{t-1}) and
  scale tau=2 (delta_2 = P_t - P_{t-2}).
* Computes second-moment variograms:
    V(1) = mean(delta_1^2)
    V(2) = mean(delta_2^2)
* Local Hurst parameter:
    H = 0.5 * log2(V(2) / V(1))
* Corridors: [min_hurst, max_hurst]. If H < min_hurst or H > max_hurst,
  blocks trading with `ROUGH_VOLATILITY_ANOMALY`.

Blocking reasons
----------------
ROUGH_VOLATILITY_ANOMALY -- local Hurst exponent outside stability corridor
INPUT_VALIDATION_ERROR   -- invalid prices, non-monotonic timestamp, or non-numeric

Public API (standardised)
-------------------------
update(bid, ask, timestamp)    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave398FBMRoughnessGuard"]

_REASON_ROUGH = "ROUGH_VOLATILITY_ANOMALY"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave398FBMRoughnessGuard:
    """Fractional Brownian Motion (fBM) Roughness and Variogram Guard."""

    def __init__(
        self,
        window_size: int = 24,
        min_hurst: float = 0.15,
        max_hurst: float = 0.85,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 12 or not (0.0 < min_hurst < max_hurst < 1.0) or cooldown_seconds <= 0.0:
            raise ValueError("Invalid parameters for Wave398FBMRoughnessGuard")
        self._window_size = int(window_size)
        self._min_h = float(min_hurst)
        self._max_h = float(max_hurst)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._prices: deque[float] = deque(maxlen=self._window_size)
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

            ts = float(timestamp)
            if self._last_time is not None and ts <= self._last_time:
                self._block(_REASON_VAL)
                return

            mid = (float(bid) + float(ask)) / 2.0
            self._prices.append(mid)
            self._last_time = ts

            if len(self._prices) >= self._window_size:
                p = list(self._prices)
                # scale tau = 1
                v1_sum = sum((p[i] - p[i - 1]) ** 2 for i in range(1, len(p)))
                v1 = v1_sum / (len(p) - 1)

                # scale tau = 2
                v2_sum = sum((p[i] - p[i - 2]) ** 2 for i in range(2, len(p)))
                v2 = v2_sum / (len(p) - 2)

                if v1 > 1e-14:
                    if v2 <= 1e-14:
                        # Extreme anti-persistence collapse (H -> 0.0)
                        h = 0.0
                        if h <= self._min_h or h >= self._max_h:
                            self._block(_REASON_ROUGH)
                    else:
                        ratio = v2 / v1
                        if ratio > 0.0:
                            h = 0.5 * math.log2(ratio)
                            if h <= self._min_h or h >= self._max_h:
                                self._block(_REASON_ROUGH)

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
            self._prices.clear()
            self._last_time = None
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
