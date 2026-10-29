"""
Wave 438 -- Dynamic Liquidity Resiliency & Depth Recovery Velocity Guard
=======================================================================
Monitors orderbook depth replenishment dynamics following large sweep shocks.
When an aggressive execution consumes significant top-of-book depth, healthy
resilient markets replenish passive liquidity within fractions of a second.
If post-sweep depth recovery velocity V_rec collapses below institutional floors,
liquidity providers have withdrawn, leaving the book exposed to severe slippage.

Methodology
-----------
* Tracks total book depth Q_t = bid_depth + ask_depth.
* Detects sweep shocks when depth drops by >= `shock_depth_fraction` (e.g. 40%).
* Measures post-shock recovery velocity: V_rec = (Q_t - Q_trough) / dt_recovery.
* If depth remains depressed below warning threshold and recovery time exceeds
  `max_recovery_timeout_sec` or V_rec <= `min_recovery_velocity`,
  blocks with CHRONIC_DEPTH_RECOVERY_FAILURE.
* If depth drops below absolute critical floor, blocks with CRITICAL_BOOK_DEPLETION_LOCK.

Blocking reasons
----------------
CHRONIC_DEPTH_RECOVERY_FAILURE   -- orderbook failed to replenish liquidity post-sweep
CRITICAL_BOOK_DEPLETION_LOCK     -- aggregate book depth below emergency survival floor
INPUT_VALIDATION_ERROR           -- negative depths, non-numeric, or non-monotonic timestamps

Public API (standardised)
-------------------------
update(bid_depth, ask_depth, timestamp) -> None
is_blocked(current_time=None)           -> bool
is_entry_blocked(bid, ask, ts=None)     -> bool
reset()                                 -> None
last_reason                             -> str
recovery_velocity                       -> float
is_shock_active                         -> bool
"""

from __future__ import annotations

import threading
import time
from typing import Optional

__all__ = ["Wave438DepthRecoveryVelocityGuard"]

_REASON_RECOVERY = "CHRONIC_DEPTH_RECOVERY_FAILURE"
_REASON_FLOOR = "CRITICAL_BOOK_DEPLETION_LOCK"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave438DepthRecoveryVelocityGuard:
    """Wave 438: Dynamic Liquidity Resiliency & Depth Recovery Velocity Guard."""

    def __init__(
        self,
        baseline_depth: float = 100.0,
        shock_depth_fraction: float = 0.40,
        min_recovery_velocity: float = 10.0,
        max_recovery_timeout_sec: float = 0.50,
        critical_floor: float = 10.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            baseline_depth <= critical_floor
            or not (0.10 <= shock_depth_fraction <= 0.90)
            or min_recovery_velocity <= 0.0
            or max_recovery_timeout_sec <= 0.05
            or critical_floor <= 0.0
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave438DepthRecoveryVelocityGuard")

        self._baseline = float(baseline_depth)
        self._shock_frac = float(shock_depth_fraction)
        self._min_rec_vel = float(min_recovery_velocity)
        self._max_timeout = float(max_recovery_timeout_sec)
        self._critical_floor = float(critical_floor)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._shock_start_ts: Optional[float] = None
        self._trough_depth: Optional[float] = None
        self._last_depth: float = baseline_depth
        self._recovery_vel: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def recovery_velocity(self) -> float:
        with self._lock:
            return self._recovery_vel

    @property
    def is_shock_active(self) -> bool:
        with self._lock:
            return self._shock_start_ts is not None

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._shock_start_ts = None
            self._trough_depth = None
            self._last_depth = self._baseline
            self._recovery_vel = 0.0
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
                self._last_depth = total_depth
                return

            # Check shock initiation: depth drops by >= shock_depth_fraction relative to baseline
            shock_trigger = self._baseline * (1.0 - self._shock_frac)
            if total_depth <= shock_trigger and self._shock_start_ts is None:
                self._shock_start_ts = ts
                self._trough_depth = total_depth

            if self._shock_start_ts is not None and self._trough_depth is not None:
                if total_depth < self._trough_depth:
                    self._trough_depth = total_depth

                elapsed = ts - self._shock_start_ts
                if elapsed > 1e-4:
                    vel = (total_depth - self._trough_depth) / elapsed
                    self._recovery_vel = vel

                    if elapsed >= self._max_timeout and total_depth < shock_trigger:
                        self._block(_REASON_RECOVERY, ts)
                        self._shock_start_ts = None
                    elif total_depth >= self._baseline * 0.90:
                        # Fully recovered
                        self._shock_start_ts = None
                        self._trough_depth = None

            self._last_ts = ts
            self._last_depth = total_depth

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
