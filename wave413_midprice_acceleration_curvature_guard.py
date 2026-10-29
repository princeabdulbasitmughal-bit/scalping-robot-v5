"""
Wave 413 -- Midprice Acceleration Curvature Guard
=================================================
Monitors continuous midprice velocity, acceleration, and geometric trajectory curvature:
    v_t = (P_t - P_{t-1}) / Delta t
    a_t = (v_t - v_{t-1}) / Delta t
    kappa_t = |a_t| / (1 + v_t^2)^{1.5}
Sudden surges in kinematic acceleration or trajectory curvature reveal aggressive predatory
sweeps, quote stuffing, or latency-arbitrage liquidity withdrawals before quote exhaustion.

Methodology
-----------
* Observes midprice P_t = (bid + ask) / 2.0 and monotonic timestamps t.
* Calculates instantaneous velocity v_t and acceleration a_t.
* Computes non-linear differential geometric curvature kappa_t.
* If |a_t| >= `max_acceleration`, blocks with MIDPRICE_ACCELERATION_SPIKE.
* If kappa_t >= `max_curvature`, blocks with NONLINEAR_CURVATURE_INSTABILITY.

Blocking reasons
----------------
MIDPRICE_ACCELERATION_SPIKE        -- discrete midprice acceleration exceeded physical limits
NONLINEAR_CURVATURE_INSTABILITY    -- geometric path curvature reveals microstructural distress
INPUT_VALIDATION_ERROR             -- non-positive price, bid >= ask, non-monotonic ts

Public API (standardised)
-------------------------
update(bid, ask, timestamp)    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
current_acceleration           -> float
current_curvature              -> float
"""

from __future__ import annotations

import math
import threading
import time
from typing import Optional

__all__ = ["Wave413MidpriceAccelerationCurvatureGuard"]

_REASON_ACCEL = "MIDPRICE_ACCELERATION_SPIKE"
_REASON_CURV = "NONLINEAR_CURVATURE_INSTABILITY"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave413MidpriceAccelerationCurvatureGuard:
    """Midprice Acceleration and Geometric Curvature Guard."""

    def __init__(
        self,
        max_acceleration: float = 30.0,
        max_curvature: float = 25.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if max_acceleration <= 0.0 or max_curvature <= 0.0 or cooldown_seconds <= 0.0:
            raise ValueError("Invalid parameters for Wave413MidpriceAccelerationCurvatureGuard")

        self._max_accel = float(max_acceleration)
        self._max_curv = float(max_curvature)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._prev_mid: Optional[float] = None
        self._prev_ts: Optional[float] = None
        self._prev_vel: Optional[float] = None
        self._current_accel: float = 0.0
        self._current_curv: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def current_acceleration(self) -> float:
        with self._lock:
            return self._current_accel

    @property
    def current_curvature(self) -> float:
        with self._lock:
            return self._current_curv

    def reset(self) -> None:
        with self._lock:
            self._prev_mid = None
            self._prev_ts = None
            self._prev_vel = None
            self._current_accel = 0.0
            self._current_curv = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(self, bid: float, ask: float, timestamp: float) -> None:
        with self._lock:
            if (
                not isinstance(bid, (int, float))
                or not isinstance(ask, (int, float))
                or not isinstance(timestamp, (int, float))
                or bid <= 0.0
                or ask <= 0.0
                or bid >= ask
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if timestamp > 0 else None)
                return

            if self._prev_ts is not None and timestamp < self._prev_ts:
                self._block(_REASON_VAL, timestamp)
                return

            mid = (float(bid) + float(ask)) / 2.0
            ts = float(timestamp)

            if self._prev_mid is not None and self._prev_ts is not None:
                dt = ts - self._prev_ts
                if dt > 1e-6:
                    vel = (mid - self._prev_mid) / dt

                    if self._prev_vel is not None:
                        accel = (vel - self._prev_vel) / dt
                        self._current_accel = accel

                        curv = abs(accel) / ((1.0 + vel * vel) ** 1.5)
                        self._current_curv = curv

                        if abs(accel) >= self._max_accel:
                            self._block(_REASON_ACCEL, ts)
                        elif curv >= self._max_curv:
                            self._block(_REASON_CURV, ts)

                    self._prev_vel = vel

            self._prev_mid = mid
            self._prev_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
