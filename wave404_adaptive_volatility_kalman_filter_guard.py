"""
Wave 404 -- Adaptive Volatility Kalman Filter Innovation Guard
=============================================================
Filters high-frequency market microstructure observations using a 1D state-space
adaptive Kalman filter. Tracks the Normalized Innovation Squared (NIS) residual.
Supercritical innovation spikes signal sudden non-linear discontinuous jump breaks,
bad quote prints, or acute structural regime transitions.

Methodology
-----------
* Observes midprice measurement: y_t = (bid + ask) / 2.0.
* State transition:
    x_{t|t-1} = x_{t-1}
    P_{t|t-1} = P_{t-1} + Q
* Innovation residual:
    nu_t = y_t - x_{t|t-1}
    S_t  = P_{t|t-1} + R
* Normalized Innovation Squared:
    NIS = (nu_t^2) / S_t
* State update:
    K_t = P_{t|t-1} / S_t
    x_t = x_{t|t-1} + K_t * nu_t
    P_t = (1 - K_t) * P_{t|t-1}
* If NIS >= `nis_threshold`, blocks trading for `cooldown_seconds`.

Blocking reasons
----------------
KALMAN_INNOVATION_OUTLIER -- normalized innovation residual exceeds chi-squared threshold
INPUT_VALIDATION_ERROR    -- non-positive price, bid >= ask, non-monotonic timestamp, or non-numeric

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
from typing import Optional

__all__ = ["Wave404AdaptiveVolatilityKalmanFilterGuard"]

_REASON_KALMAN = "KALMAN_INNOVATION_OUTLIER"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave404AdaptiveVolatilityKalmanFilterGuard:
    """1D Adaptive Kalman Filter innovation residual guard."""

    def __init__(
        self,
        q_process_noise: float = 0.01,
        r_measurement_noise: float = 0.05,
        nis_threshold: float = 16.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if q_process_noise <= 0.0 or r_measurement_noise <= 0.0 or nis_threshold <= 0.0 or cooldown_seconds <= 0.0:
            raise ValueError("Invalid parameters for Wave404AdaptiveVolatilityKalmanFilterGuard")
        self._q = float(q_process_noise)
        self._r = float(r_measurement_noise)
        self._nis_threshold = float(nis_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._x: Optional[float] = None
        self._p: float = 1.0
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

            if self._x is None:
                self._x = mid
                self._p = self._r
                self._last_time = ts
                return

            # Predict
            p_prior = self._p + self._q
            x_prior = self._x

            # Innovation
            nu = mid - x_prior
            s = p_prior + self._r
            nis = (nu * nu) / s

            # Check threshold
            if nis >= self._nis_threshold:
                self._block(_REASON_KALMAN)

            # Update
            k = p_prior / s
            self._x = x_prior + k * nu
            self._p = (1.0 - k) * p_prior
            self._last_time = ts

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
            self._x = None
            self._p = 1.0
            self._last_time = None
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
