"""
Wave 428 -- Price Drift Velocity & Trend Exhaustion Guard
=========================================================
Monitors short-horizon directional price velocity v_t and deceleration shocks:
    v_t = (P_t - P_{t-1}) / Delta t
    a_t = (v_t - v_{t-1}) / Delta t
Detects parabolic sweep exhaustion: when a strong directional sweep attains extreme
velocity |v_t| >= `max_drift_velocity` and immediately hits an adverse deceleration wall
(a_t * v_t < 0 with |a_t| >= `min_exhaustion_accel`), the institutional sweep has exhausted
book depth and a violent mean-reverting counter-shock is imminent.

Methodology
-----------
* Observes midprice ticks: (bid, ask, timestamp).
* Computes instantaneous velocity v_t and discrete acceleration a_t.
* If |v_t| >= `max_drift_velocity` and a_t * v_t < -1.0 and abs(a_t) >= `min_exhaustion_accel`,
  blocks with PARABOLIC_DRIFT_EXHAUSTION.
* If |v_t| >= `max_drift_velocity` * 1.5, blocks with VELOCITY_SURGE_DECELERATION_SHOCK.

Blocking reasons
----------------
PARABOLIC_DRIFT_EXHAUSTION          -- terminal velocity surge accompanied by acute deceleration
VELOCITY_SURGE_DECELERATION_SHOCK   -- extreme directional price velocity exceeded safety ceiling
INPUT_VALIDATION_ERROR              -- non-positive prices, bid >= ask, non-monotonic ts

Public API (standardised)
-------------------------
update(bid, ask, timestamp)    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
current_velocity               -> float
current_acceleration           -> float
"""

from __future__ import annotations

import threading
import time
from typing import Optional

__all__ = ["Wave428PriceDriftVelocityExhaustionGuard"]

_REASON_EXHAUSTION = "PARABOLIC_DRIFT_EXHAUSTION"
_REASON_SURGE = "VELOCITY_SURGE_DECELERATION_SHOCK"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave428PriceDriftVelocityExhaustionGuard:
    """Price Drift Velocity and Trend Exhaustion Guard."""

    def __init__(
        self,
        max_drift_velocity: float = 8.0,
        min_exhaustion_accel: float = 15.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            max_drift_velocity <= 0.0
            or min_exhaustion_accel <= 0.0
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave428PriceDriftVelocityExhaustionGuard")

        self._max_vel = float(max_drift_velocity)
        self._min_accel = float(min_exhaustion_accel)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_mid: Optional[float] = None
        self._last_ts: Optional[float] = None
        self._last_vel: Optional[float] = None
        self._current_vel: float = 0.0
        self._current_accel: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def current_velocity(self) -> float:
        with self._lock:
            return self._current_vel

    @property
    def current_acceleration(self) -> float:
        with self._lock:
            return self._current_accel

    def reset(self) -> None:
        with self._lock:
            self._last_mid = None
            self._last_ts = None
            self._last_vel = None
            self._current_vel = 0.0
            self._current_accel = 0.0
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

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            mid = (float(bid) + float(ask)) / 2.0
            ts = float(timestamp)

            if self._last_mid is not None and self._last_ts is not None:
                dt = max(ts - self._last_ts, 1e-4)
                vel = (mid - self._last_mid) / dt
                self._current_vel = vel

                if self._last_vel is not None:
                    accel = (vel - self._last_vel) / dt
                    self._current_accel = accel

                    # Check parabolic exhaustion: high speed in previous tick, sharp reversal
                    if abs(self._last_vel) >= self._max_vel and (accel * self._last_vel < 0.0) and abs(accel) >= self._min_accel:
                        self._block(_REASON_EXHAUSTION, ts)
                    elif abs(vel) >= self._max_vel * 1.5:
                        self._block(_REASON_SURGE, ts)

                self._last_vel = vel

            self._last_mid = mid
            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
