"""
Wave 395 -- Non-Linear Midprice Acceleration Guard
==================================================
Monitors instantaneous second-order acceleration of the midprice trajectory.
Supercritical acceleration indicates sudden non-linear liquidity gaps,
flash crashes, or predatory quote jumping.

Methodology
-----------
* Observes top-of-book `bid` and `ask` prices with `timestamp`.
* Computes midprice: P_t = (bid + ask) / 2.0.
* Tracks velocity: v_t = (P_t - P_{t-1}) / (t - t_{t-1}).
* Tracks acceleration: a_t = (v_t - v_{t-1}) / (t - t_{t-1}).
* If |a_t| >= `acceleration_threshold`, blocks trading for `cooldown_seconds`.

Blocking reasons
----------------
MIDPRICE_SUPERCRITICAL_ACCELERATION -- excessive non-linear curvature in price path
INPUT_VALIDATION_ERROR              -- bid >= ask, non-positive price, dt <= 0, or non-numeric

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

__all__ = ["Wave395NonlinearMidpriceAccelerationGuard"]

_REASON_ACCEL = "MIDPRICE_SUPERCRITICAL_ACCELERATION"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave395NonlinearMidpriceAccelerationGuard:
    """Non-linear midprice second-order acceleration guard."""

    def __init__(
        self,
        acceleration_threshold: float = 50.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if acceleration_threshold <= 0.0 or cooldown_seconds <= 0.0:
            raise ValueError("Invalid parameters for Wave395NonlinearMidpriceAccelerationGuard")
        self._accel_threshold = float(acceleration_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._last_mid: Optional[float] = None
        self._last_time: Optional[float] = None
        self._last_velocity: Optional[float] = None
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

            velocity = (mid - self._last_mid) / dt

            if self._last_velocity is not None:
                acceleration = (velocity - self._last_velocity) / dt
                if abs(acceleration) >= self._accel_threshold:
                    self._block(_REASON_ACCEL)

            self._last_velocity = velocity
            self._last_mid = mid
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
            self._last_mid = None
            self._last_time = None
            self._last_velocity = None
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
