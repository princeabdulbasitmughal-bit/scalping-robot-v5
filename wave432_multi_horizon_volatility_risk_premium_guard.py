"""
Wave 432 -- Multi-Horizon Volatility Risk Premium Guard
======================================================
Monitors the term structure of high-frequency realized volatility across dual
time horizons (short-horizon micro-volatility vs medium-horizon baseline volatility).
An explosive expansion in short-horizon volatility relative to the medium horizon
signals sudden asymmetric news arrival, impending gap events, or stop-loss cascade
unwinding.

Methodology
-----------
* Tracks midprice log returns: r_t = ln(mid_t / mid_{t-1}).
* Computes realized volatility over short window (N_short, e.g. 5 ticks) and
  medium window (N_medium, e.g. 20 ticks).
* Evaluates Volatility Risk Premium (VRP) ratio:
    VRP = sigma_short / (sigma_medium + eps)
* If VRP >= `max_vrp_ratio`, blocks with EXPLOSIVE_MICRO_VOLATILITY_JUMP.
* If sigma_short >= `critical_vol_ceiling`, blocks with VOLATILITY_CEILING_SUPERNOVA.

Blocking reasons
----------------
EXPLOSIVE_MICRO_VOLATILITY_JUMP -- short-horizon volatility violently decoupled from baseline
VOLATILITY_CEILING_SUPERNOVA    -- absolute short-horizon volatility exceeded extreme threshold
INPUT_VALIDATION_ERROR          -- bid >= ask, non-numeric, or non-monotonic timestamps

Public API (standardised)
-------------------------
update(bid, ask, timestamp)         -> None
is_blocked(current_time=None)       -> bool
is_entry_blocked(bid, ask, ts=None) -> bool
reset()                             -> None
last_reason                         -> str
vrp_ratio                           -> float
short_volatility                    -> float
medium_volatility                   -> float
"""

from __future__ import annotations

import collections
import math
import threading
import time
from typing import Deque, Optional

__all__ = ["Wave432MultiHorizonVolatilityRiskPremiumGuard"]

_REASON_VRP = "EXPLOSIVE_MICRO_VOLATILITY_JUMP"
_REASON_CEILING = "VOLATILITY_CEILING_SUPERNOVA"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave432MultiHorizonVolatilityRiskPremiumGuard:
    """Wave 432: Multi-Horizon Volatility Risk Premium Guard."""

    def __init__(
        self,
        short_window: int = 5,
        medium_window: int = 20,
        max_vrp_ratio: float = 2.80,
        critical_vol_ceiling: float = 0.02,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            short_window < 3
            or medium_window <= short_window
            or max_vrp_ratio <= 1.0
            or critical_vol_ceiling <= 0.0
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave432MultiHorizonVolatilityRiskPremiumGuard")

        self._short_w = int(short_window)
        self._med_w = int(medium_window)
        self._max_vrp = float(max_vrp_ratio)
        self._crit_vol = float(critical_vol_ceiling)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._last_mid: Optional[float] = None
        self._returns: Deque[float] = collections.deque(maxlen=self._med_w)
        self._short_vol: float = 0.0
        self._med_vol: float = 0.0
        self._vrp_ratio: float = 1.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def vrp_ratio(self) -> float:
        with self._lock:
            return self._vrp_ratio

    @property
    def short_volatility(self) -> float:
        with self._lock:
            return self._short_vol

    @property
    def medium_volatility(self) -> float:
        with self._lock:
            return self._med_vol

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._last_mid = None
            self._returns.clear()
            self._short_vol = 0.0
            self._med_vol = 0.0
            self._vrp_ratio = 1.0
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

                if len(self._returns) >= self._med_w:
                    short_rets = list(self._returns)[-self._short_w:]
                    mean_s = sum(short_rets) / self._short_w
                    var_s = sum((r - mean_s) ** 2 for r in short_rets) / (self._short_w - 1)
                    sig_s = math.sqrt(max(0.0, var_s))
                    self._short_vol = sig_s

                    med_rets = list(self._returns)
                    mean_m = sum(med_rets) / self._med_w
                    var_m = sum((r - mean_m) ** 2 for r in med_rets) / (self._med_w - 1)
                    sig_m = math.sqrt(max(0.0, var_m))
                    self._med_vol = sig_m

                    eps = 1e-7
                    vrp = sig_s / (sig_m + eps)
                    self._vrp_ratio = vrp

                    if sig_s >= self._crit_vol:
                        self._block(_REASON_CEILING, ts)
                    elif vrp >= self._max_vrp:
                        self._block(_REASON_VRP, ts)

            self._last_ts = ts
            self._last_mid = mid

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
