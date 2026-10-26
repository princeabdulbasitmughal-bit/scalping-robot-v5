"""
Wave 391 -- Trade Flow Gamma Scalping Detection Guard
======================================================
Detects market-maker gamma scalping and predatory high-frequency delta hedging:
rapidly alternating trade execution directions clustered within an unnaturally
compressed, tight price range.

Methodology
-----------
* Observes trade executions: price, volume, side ('buy'/'sell').
* Tracks recent trade sides and prices over a rolling window of `window_size` trades.
* Computes:
    1. Alternation count: transitions where side_i != side_{i-1}.
    2. Price range: max(prices) - min(prices).
* If alternation_count >= `min_alternations` AND price_range <= `max_price_range`,
  detects gamma scalping market-making churn and blocks trading for `cooldown_seconds`.

Blocking reasons
----------------
GAMMA_SCALPING_PATTERN -- high direction alternation inside tight price range
INPUT_VALIDATION_ERROR -- malformed price, volume, side, or timestamp

Public API (standardised)
-------------------------
update(price, volume, side, timestamp) -> None
is_blocked(current_time=None)          -> bool
is_entry_blocked(bid, ask, ts)         -> bool
reset()                                -> None
last_reason                            -> str
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave391TradeFlowGammaScalpingDetectionGuard"]

_REASON_GAMMA = "GAMMA_SCALPING_PATTERN"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave391TradeFlowGammaScalpingDetectionGuard:
    """Trade flow gamma scalping and tight-range churning detection guard."""

    def __init__(
        self,
        window_size: int = 10,
        min_alternations: int = 6,
        max_price_range: float = 0.0005,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if window_size < 4 or min_alternations >= window_size or max_price_range <= 0.0:
            raise ValueError("Invalid parameters for Wave391TradeFlowGammaScalpingDetectionGuard")
        self._window_size = int(window_size)
        self._min_alt = int(min_alternations)
        self._max_range = float(max_price_range)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._prices: deque[float] = deque(maxlen=self._window_size)
        self._sides: deque[str] = deque(maxlen=self._window_size)
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(self, price: float, volume: float, side: str, timestamp: float) -> None:
        with self._lock:
            for val in (price, volume, timestamp):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._block(_REASON_VAL)
                    return

            if price <= 0.0 or volume <= 0.0 or side not in ("buy", "sell"):
                self._block(_REASON_VAL)
                return

            p = float(price)
            s = str(side)

            self._prices.append(p)
            self._sides.append(s)

            if len(self._prices) >= self._window_size:
                p_range = max(self._prices) - min(self._prices)
                sides_list = list(self._sides)
                alt_count = sum(1 for i in range(len(sides_list) - 1) if sides_list[i] != sides_list[i + 1])

                if alt_count >= self._min_alt and p_range <= self._max_range:
                    self._block(_REASON_GAMMA)

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
            self._prices.clear()
            self._sides.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
