"""
Wave 379 -- Trade Flow Realized Volatility Regime Guard
========================================================
Monitors high-frequency tick realized volatility (RV). Blocks execution during
both hyper-volatile risk regimes (flash events / news shocks) and abnormal
low-volatility stagnation regimes (liquidity freezes / pre-breakout traps).

Methodology
-----------
* Computes tick log-returns: r_i = ln(price_i / price_{i-1}).
* Maintains a rolling window of recent returns of size `window_size`.
* Calculates annualized realized volatility:
    RV = sqrt(sum(r_i^2)) * sqrt(annualization_factor)
* Blocks if RV >= `high_vol_threshold` (extreme volatility surge).
* Blocks if RV <= `low_vol_threshold` once window is fully populated (liquidity freeze).

Blocking reasons
----------------
HIGH_VOLATILITY_REGIME -- realized volatility exceeds safe operational upper bound
LOW_VOLATILITY_REGIME  -- realized volatility collapses below freeze threshold
INPUT_VALIDATION_ERROR -- non-numeric or non-positive price/timestamp inputs

Public API (standardised)
-------------------------
update(price, timestamp)       -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave379TradeFlowRealizedVolatilityRegimeGuard"]

_REASON_HIGH_VOL = "HIGH_VOLATILITY_REGIME"
_REASON_LOW_VOL = "LOW_VOLATILITY_REGIME"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave379TradeFlowRealizedVolatilityRegimeGuard:
    """Trade flow tick-level realized volatility regime guard."""

    def __init__(
        self,
        window_size: int = 20,
        high_vol_threshold: float = 0.50,
        low_vol_threshold: float = 0.001,
        annualization_factor: float = 252.0 * 6.5 * 3600.0,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if window_size < 3 or high_vol_threshold <= low_vol_threshold or low_vol_threshold < 0.0:
            raise ValueError("Invalid parameters for Wave379TradeFlowRealizedVolatilityRegimeGuard")
        self._window_size = int(window_size)
        self._high_vol = float(high_vol_threshold)
        self._low_vol = float(low_vol_threshold)
        self._ann_factor = float(annualization_factor)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._prev_price: Optional[float] = None
        self._returns: deque[float] = deque(maxlen=self._window_size)
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(self, price: float, timestamp: float) -> None:
        with self._lock:
            for val in (price, timestamp):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._block(_REASON_VAL)
                    return

            if price <= 0.0:
                self._block(_REASON_VAL)
                return

            p = float(price)

            if self._prev_price is not None and self._prev_price > 0.0:
                r = math.log(p / self._prev_price)
                self._returns.append(r)

                if len(self._returns) >= self._window_size:
                    ss = sum(x * x for x in self._returns)
                    rv = math.sqrt(ss) * math.sqrt(self._ann_factor)

                    if rv >= self._high_vol:
                        self._block(_REASON_HIGH_VOL)
                    elif rv <= self._low_vol:
                        self._block(_REASON_LOW_VOL)

            self._prev_price = p

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
            self._prev_price = None
            self._returns.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
