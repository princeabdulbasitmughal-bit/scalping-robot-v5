"""
Wave 431 -- Liquidity Replenishment Acceleration Decay Guard
============================================================
Presides over high-frequency limit order book liquidity replenishment dynamics.
Following trade executions and depth depletion, market makers replenish liquidity
at velocity v_rep = dQ / dt. If the replenishment acceleration a_rep = dv_rep / dt
collapses into deep negative territory, passive liquidity providers are fleeing,
signalling an impending liquidity vacuum and extreme execution slippage.

Methodology
-----------
* Tracks total depth Q_t = bid_depth + ask_depth.
* Computes replenishment velocity: v_t = (Q_t - Q_{t-1}) / dt.
* Computes replenishment acceleration: a_t = (v_t - v_{t-1}) / dt.
* If total depth is below `depth_warning_threshold` and a_t <= `min_acceleration_threshold`,
  blocks with REPLENISHMENT_ACCELERATION_COLLAPSE.
* If total depth drops below `critical_floor_threshold`, blocks with VACUUM_LIQUIDITY_FLOOR_BREACH.

Blocking reasons
----------------
REPLENISHMENT_ACCELERATION_COLLAPSE -- replenishment acceleration plunged into negative flight
VACUUM_LIQUIDITY_FLOOR_BREACH       -- aggregate book depth below absolute survival floor
INPUT_VALIDATION_ERROR              -- negative depths, non-numeric, or non-monotonic timestamps

Public API (standardised)
-------------------------
update(bid_depth, ask_depth, timestamp) -> None
is_blocked(current_time=None)           -> bool
is_entry_blocked(bid, ask, ts=None)     -> bool
reset()                                 -> None
last_reason                             -> str
replenishment_velocity                  -> float
replenishment_acceleration              -> float
"""

from __future__ import annotations

import threading
import time
from typing import Optional

__all__ = ["Wave431LiquidityReplenishmentAccelerationGuard"]

_REASON_ACCEL = "REPLENISHMENT_ACCELERATION_COLLAPSE"
_REASON_FLOOR = "VACUUM_LIQUIDITY_FLOOR_BREACH"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave431LiquidityReplenishmentAccelerationGuard:
    """Wave 431: Liquidity Replenishment Acceleration Decay Guard."""

    def __init__(
        self,
        min_acceleration_threshold: float = -50.0,
        depth_warning_threshold: float = 100.0,
        critical_floor_threshold: float = 10.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            min_acceleration_threshold >= 0.0
            or depth_warning_threshold <= critical_floor_threshold
            or critical_floor_threshold <= 0.0
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave431LiquidityReplenishmentAccelerationGuard")

        self._min_accel = float(min_acceleration_threshold)
        self._depth_warn = float(depth_warning_threshold)
        self._critical_floor = float(critical_floor_threshold)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._last_depth: Optional[float] = None
        self._last_velocity: Optional[float] = None
        self._current_velocity: float = 0.0
        self._current_accel: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def replenishment_velocity(self) -> float:
        with self._lock:
            return self._current_velocity

    @property
    def replenishment_acceleration(self) -> float:
        with self._lock:
            return self._current_accel

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._last_depth = None
            self._last_velocity = None
            self._current_velocity = 0.0
            self._current_accel = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(self, bid_depth: float, ask_depth: float, timestamp: float) -> None:
        with self._lock:
            if (
                not isinstance(bid_depth, (int, float))
                or not isinstance(ask_depth, (int, float))
                or not isinstance(timestamp, (int, float))
                or bid_depth < 0.0
                or ask_depth < 0.0
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if (isinstance(timestamp, (int, float)) and timestamp > 0) else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)
            total_depth = float(bid_depth + ask_depth)

            if total_depth < self._critical_floor:
                self._block(_REASON_FLOOR, ts)
                self._last_ts = ts
                self._last_depth = total_depth
                return

            if self._last_ts is not None and self._last_depth is not None:
                dt = ts - self._last_ts
                if dt > 1e-6:
                    vel = (total_depth - self._last_depth) / dt
                    self._current_velocity = vel

                    if self._last_velocity is not None:
                        accel = (vel - self._last_velocity) / dt
                        self._current_accel = accel

                        if total_depth <= self._depth_warn and accel <= self._min_accel:
                            self._block(_REASON_ACCEL, ts)

                    self._last_velocity = vel

            self._last_ts = ts
            self._last_depth = total_depth

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
