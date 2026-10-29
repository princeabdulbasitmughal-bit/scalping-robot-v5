"""
Wave 437 -- Non-Stationary Realized Volatility Drift Curvature Guard
==================================================================
Monitors second-order acceleration (curvature) in realized volatility:
    kappa_sigma = d^2 sigma / dt^2
While steady volatility expansion can be accommodated through wider spreads,
parabolic curvature in volatility dynamics signals a non-linear volatility shockwave
often associated with unexpected liquidity vacuum collapses or flash cascades.

Methodology
-----------
* Tracks short-window realized volatility sigma_t from midprice returns.
* Evaluates volatility velocity: v_t = (sigma_t - sigma_{t-1}) / dt.
* Evaluates volatility curvature: kappa_t = (v_t - v_{t-1}) / dt.
* If kappa_t >= `max_curvature_threshold` and sigma_t >= `vol_activation_floor`,
  blocks with PARABOLIC_VOLATILITY_CURVATURE_EXPLOSION.
* If sigma_t >= `extreme_vol_cutoff`, blocks with EXTREME_VOLATILITY_REGIME_LOCKOUT.

Blocking reasons
----------------
PARABOLIC_VOLATILITY_CURVATURE_EXPLOSION -- volatility accelerating quadratically into shockwave
EXTREME_VOLATILITY_REGIME_LOCKOUT        -- absolute realized volatility breached survival ceiling
INPUT_VALIDATION_ERROR                   -- bid >= ask, non-numeric, or non-monotonic timestamps

Public API (standardised)
-------------------------
update(bid, ask, timestamp)         -> None
is_blocked(current_time=None)       -> bool
is_entry_blocked(bid, ask, ts=None) -> bool
reset()                             -> None
last_reason                         -> str
current_volatility                  -> float
volatility_curvature                -> float
"""

from __future__ import annotations

import collections
import math
import threading
import time
from typing import Deque, Optional

__all__ = ["Wave437VolatilityDriftCurvatureGuard"]

_REASON_CURV = "PARABOLIC_VOLATILITY_CURVATURE_EXPLOSION"
_REASON_EXTREME = "EXTREME_VOLATILITY_REGIME_LOCKOUT"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave437VolatilityDriftCurvatureGuard:
    """Wave 437: Non-Stationary Realized Volatility Drift Curvature Guard."""

    def __init__(
        self,
        return_window: int = 5,
        max_curvature_threshold: float = 2.50,
        vol_activation_floor: float = 0.0005,
        extreme_vol_cutoff: float = 0.015,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            return_window < 3
            or max_curvature_threshold <= 0.0
            or vol_activation_floor <= 0.0
            or extreme_vol_cutoff <= vol_activation_floor
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave437VolatilityDriftCurvatureGuard")

        self._ret_w = int(return_window)
        self._max_curv = float(max_curvature_threshold)
        self._vol_floor = float(vol_activation_floor)
        self._extreme_vol = float(extreme_vol_cutoff)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._last_mid: Optional[float] = None
        self._returns: Deque[float] = collections.deque(maxlen=self._ret_w)
        self._last_vol: Optional[float] = None
        self._last_vol_vel: Optional[float] = None
        self._current_vol: float = 0.0
        self._current_curv: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def current_volatility(self) -> float:
        with self._lock:
            return self._current_vol

    @property
    def volatility_curvature(self) -> float:
        with self._lock:
            return self._current_curv

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._last_mid = None
            self._returns.clear()
            self._last_vol = None
            self._last_vol_vel = None
            self._current_vol = 0.0
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
                or ask <= bid
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if (isinstance(timestamp, (int, float)) and timestamp > 0) else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)
            mid = (float(bid) + float(ask)) / 2.0

            if self._last_mid is not None and self._last_mid > 0.0:
                ret = math.log(mid / self._last_mid)
                self._returns.append(ret)

                if len(self._returns) >= self._ret_w:
                    rets = list(self._returns)
                    mean_r = sum(rets) / self._ret_w
                    var_r = sum((r - mean_r) ** 2 for r in rets) / (self._ret_w - 1)
                    sig = math.sqrt(max(0.0, var_r))
                    self._current_vol = sig

                    if sig >= self._extreme_vol:
                        self._block(_REASON_EXTREME, ts)
                    elif self._last_ts is not None and self._last_vol is not None:
                        dt = ts - self._last_ts
                        if dt > 1e-5:
                            vol_vel = (sig - self._last_vol) / dt
                            if self._last_vol_vel is not None:
                                curv = (vol_vel - self._last_vol_vel) / dt
                                self._current_curv = curv

                                if sig >= self._vol_floor and curv >= self._max_curv:
                                    self._block(_REASON_CURV, ts)

                            self._last_vol_vel = vol_vel

                    self._last_vol = sig

            self._last_ts = ts
            self._last_mid = mid

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
