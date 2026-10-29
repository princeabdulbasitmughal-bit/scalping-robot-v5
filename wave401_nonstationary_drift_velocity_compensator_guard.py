"""
Wave 401 -- Non-Stationary Drift Velocity Compensator Guard
==========================================================
Monitors rolling non-stationary drift velocity of the midprice trajectory.
Supercritical directional drift velocity indicates runaway momentum runs,
liquidity vacuums, or macroeconomic announcement shockwaves.

Methodology
-----------
* Observes midprice P_t = (bid + ask) / 2.0 with timestamp t.
* Computes instantaneous velocity: v_i = (P_t - P_{t-1}) / (t - t_{t-1}).
* Maintains a rolling window of recent velocities of size `window_size`.
* Calculates mean drift velocity: mu = sum(v_i) / len(v_i).
* If |mu| >= `drift_velocity_threshold`, blocks trading for `cooldown_seconds`.

Blocking reasons
----------------
SUPERCRITICAL_DRIFT_VELOCITY -- persistent directional drift velocity exceeds safety bound
INPUT_VALIDATION_ERROR       -- invalid price, non-monotonic timestamp, or non-numeric input

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

__all__ = ["Wave401NonstationaryDriftVelocityCompensatorGuard"]

_REASON_DRIFT = "SUPERCRITICAL_DRIFT_VELOCITY"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave401NonstationaryDriftVelocityCompensatorGuard:
    """Rolling non-stationary drift velocity guard."""

    def __init__(
        self,
        window_size: int = 15,
        drift_velocity_threshold: float = 2.5,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 3 or drift_velocity_threshold <= 0.0 or cooldown_seconds <= 0.0:
            raise ValueError("Invalid parameters for Wave401NonstationaryDriftVelocityCompensatorGuard")
        self._window_size = int(window_size)
        self._drift_threshold = float(drift_velocity_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._velocities: deque[float] = deque(maxlen=self._window_size)
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

            v = (mid - self._last_mid) / dt
            self._velocities.append(v)
            self._last_mid = mid
            self._last_time = ts

            if len(self._velocities) >= self._window_size:
                avg_v = sum(self._velocities) / len(self._velocities)
                if abs(avg_v) >= self._drift_threshold:
                    self._block(_REASON_DRIFT)

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
            self._velocities.clear()
            self._last_mid = None
            self._last_time = None
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
