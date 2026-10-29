"""
Wave 442 -- Orderbook Depth Recovery Half-Life Elasticity Guard
===============================================================
Evaluates the parametric half-life of orderbook depth replenishment post-liquidity shock.
Following aggressive order sweeps, depth recovery toward asymptotic equilibrium Q_inf
is modeled via exponential replenishment:
    Q(t) = Q_inf - (Q_inf - Q_0) * exp(-lambda * t)
The implied replenishment half-life:
    t_{1/2} = ln(2) / lambda
indicates the speed of liquidity repair. If replenishment half-life exceeds
institutional safety ceilings, the orderbook exhibits chronic elasticity friction,
exposing subsequent orders to severe execution penalties.

Methodology
-----------
* Tracks total depth Q_t = bid_depth + ask_depth.
* Detects depth depletion when Q_t <= `depletion_trigger_depth`.
* Evaluates empirical replenishment half-life:
    lambda = (1 / dt) * ln((Q_target - Q_0) / (Q_target - Q_t + eps))
    t_{1/2} = ln(2) / max(eps, lambda)
* If t_{1/2} >= `max_half_life_sec` and Q_t < `Q_target * 0.85`,
  blocks with SLUGGISH_DEPTH_RECOVERY_HALF_LIFE.
* If Q_t <= `critical_floor`, blocks with EMERGENCY_DEPTH_FLOOR_BREACH.

Blocking reasons
----------------
SLUGGISH_DEPTH_RECOVERY_HALF_LIFE -- depth replenishment half-life exceeded maximum tolerance
EMERGENCY_DEPTH_FLOOR_BREACH      -- book depth dropped below absolute survival floor
INPUT_VALIDATION_ERROR            -- negative depths, non-numeric, or non-monotonic timestamps

Public API (standardised)
-------------------------
update(bid_depth, ask_depth, timestamp) -> None
is_blocked(current_time=None)           -> bool
is_entry_blocked(bid, ask, ts=None)     -> bool
reset()                                 -> None
last_reason                             -> str
half_life_sec                           -> float
"""

from __future__ import annotations

import math
import threading
import time
from typing import Optional

__all__ = ["Wave442DepthRecoveryHalfLifeGuard"]

_REASON_SLUGGISH = "SLUGGISH_DEPTH_RECOVERY_HALF_LIFE"
_REASON_FLOOR = "EMERGENCY_DEPTH_FLOOR_BREACH"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave442DepthRecoveryHalfLifeGuard:
    """Wave 442: Orderbook Depth Recovery Half-Life Elasticity Guard."""

    def __init__(
        self,
        target_equilibrium_depth: float = 100.0,
        depletion_trigger_depth: float = 50.0,
        max_half_life_sec: float = 0.80,
        critical_floor: float = 10.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            target_equilibrium_depth <= depletion_trigger_depth
            or depletion_trigger_depth <= critical_floor
            or max_half_life_sec <= 0.05
            or critical_floor <= 0.0
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave442DepthRecoveryHalfLifeGuard")

        self._target_depth = float(target_equilibrium_depth)
        self._trigger_depth = float(depletion_trigger_depth)
        self._max_half_life = float(max_half_life_sec)
        self._critical_floor = float(critical_floor)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._depletion_start_ts: Optional[float] = None
        self._initial_depth: Optional[float] = None
        self._half_life: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def half_life_sec(self) -> float:
        with self._lock:
            return self._half_life

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._depletion_start_ts = None
            self._initial_depth = None
            self._half_life = 0.0
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

            if total_depth <= self._critical_floor:
                self._block(_REASON_FLOOR, ts)
                self._last_ts = ts
                return

            # Check if entering depletion state
            if total_depth <= self._trigger_depth and self._depletion_start_ts is None:
                self._depletion_start_ts = ts
                self._initial_depth = total_depth

            if self._depletion_start_ts is not None and self._initial_depth is not None:
                elapsed = ts - self._depletion_start_ts
                if elapsed > 1e-4:
                    rem_init = max(1.0, self._target_depth - self._initial_depth)
                    rem_curr = max(0.1, self._target_depth - total_depth)

                    if rem_curr < rem_init:
                        # Depth is replenishing
                        lam = (1.0 / elapsed) * math.log(rem_init / rem_curr)
                        t_half = math.log(2.0) / max(1e-4, lam)
                        self._half_life = t_half

                        if t_half >= self._max_half_life and total_depth < self._target_depth * 0.85:
                            self._block(_REASON_SLUGGISH, ts)
                    else:
                        # Depth is failing to replenish or deteriorating further
                        self._half_life = 999.0
                        if elapsed >= self._max_half_life:
                            self._block(_REASON_SLUGGISH, ts)

                if total_depth >= self._target_depth * 0.90:
                    # Successfully replenished
                    self._depletion_start_ts = None
                    self._initial_depth = None

            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
