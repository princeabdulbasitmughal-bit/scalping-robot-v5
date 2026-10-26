"""
Wave 377 -- Trade Flow Kelly Criterion Regime Guard
====================================================
Monitors empirical win/loss probability skew and theoretical Kelly leverage bounds
from trade flow price movement outcomes. Extreme win or loss clustering indicates
strongly trending regimes or extreme adverse-selection conditions.

Methodology
-----------
* Observes sequential trade executions and subsequent tick price movements:
    A buy is considered favourable (+1) if next price > execution price,
    unfavourable (0) if next price < execution price.
    A sell is favourable (+1) if next price < execution price,
    unfavourable (0) if next price > execution price.
* Over a rolling window of recent outcomes, computes empirical win rate p.
* Full Kelly fraction f* = 2p - 1.
* Blocks if |f*| >= `kelly_threshold` (e.g. 0.60, representing a severe 80/20 directional skew).

Blocking reasons
----------------
KELLY_REGIME_EXTREME   -- directional flow outcome probability exceeds Kelly bound
INPUT_VALIDATION_ERROR -- malformed inputs or non-numeric values

Public API (standardised)
-------------------------
update(volume, side, price, timestamp) -> None
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

__all__ = ["Wave377TradeFlowKellyCriterionRegimeGuard"]

_REASON_KELLY = "KELLY_REGIME_EXTREME"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave377TradeFlowKellyCriterionRegimeGuard:
    """Trade flow empirical Kelly criterion skew guard."""

    def __init__(
        self,
        window_size: int = 20,
        kelly_threshold: float = 0.60,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if window_size < 5 or not (0.0 < kelly_threshold <= 1.0):
            raise ValueError("Invalid parameters for Wave377TradeFlowKellyCriterionRegimeGuard")
        self._window_size = int(window_size)
        self._kelly_thresh = float(kelly_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._prev_price: Optional[float] = None
        self._prev_side: Optional[str] = None
        self._outcomes: deque[int] = deque(maxlen=self._window_size)
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(self, volume: float, side: str, price: float, timestamp: float) -> None:
        with self._lock:
            for val in (volume, price, timestamp):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._block(_REASON_VAL)
                    return

            if volume <= 0.0 or price <= 0.0 or side not in ("buy", "sell"):
                self._block(_REASON_VAL)
                return

            p = float(price)
            s = str(side)

            if self._prev_price is not None and self._prev_side is not None:
                diff = p - self._prev_price
                if abs(diff) > 1e-12:
                    if self._prev_side == "buy":
                        outcome = 1 if diff > 0 else 0
                    else:
                        outcome = 1 if diff < 0 else 0
                    self._outcomes.append(outcome)

                    if len(self._outcomes) >= self._window_size:
                        win_rate = sum(self._outcomes) / len(self._outcomes)
                        kelly_fraction = 2.0 * win_rate - 1.0
                        if abs(kelly_fraction) >= self._kelly_thresh:
                            self._block(_REASON_KELLY)

            self._prev_price = p
            self._prev_side = s

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
            self._prev_side = None
            self._outcomes.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
