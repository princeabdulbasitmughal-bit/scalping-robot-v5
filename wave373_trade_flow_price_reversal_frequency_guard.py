"""
Wave 373 -- Trade Flow Price Reversal Frequency Guard
======================================================
Monitors the frequency of high-frequency price reversals (choppiness / tick whipsawing).
An abnormally high reversal rate signals HFT pinging, bid-ask bouncing noise, or whipsaw regimes.

Methodology
-----------
* Records trade execution prices.
* Determines directional sign: +1 (up-tick), -1 (down-tick), 0 (flat).
* For consecutive non-zero price steps, a reversal is recorded if sign_i != sign_{i-1}.
* Maintains a rolling window of recent direction transitions.
* If reversal frequency >= `reversal_rate_threshold` with sufficient observations, block trading.

Blocking reasons
----------------
HIGH_REVERSAL_FREQUENCY -- excessive price direction alternations
INPUT_VALIDATION_ERROR  -- malformed inputs

Public API (standardised)
-------------------------
update(price, volume, timestamp) -> None
is_blocked(current_time=None)    -> bool
is_entry_blocked(bid, ask, ts)   -> bool
reset()                          -> None
last_reason                      -> str
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave373TradeFlowPriceReversalFrequencyGuard"]

_REASON_REVERSAL = "HIGH_REVERSAL_FREQUENCY"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave373TradeFlowPriceReversalFrequencyGuard:
    """Trade flow price reversal frequency and whipsaw detection guard."""

    def __init__(
        self,
        window_size: int = 20,
        reversal_rate_threshold: float = 0.70,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 3 or not (0.0 < reversal_rate_threshold <= 1.0):
            raise ValueError("Invalid parameters for Wave373TradeFlowPriceReversalFrequencyGuard")
        self._window_size = int(window_size)
        self._reversal_threshold = float(reversal_rate_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._prev_price: Optional[float] = None
        self._prev_sign: Optional[int] = None
        self._transitions: deque[int] = deque(maxlen=self._window_size)
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(self, price: float, volume: float, timestamp: float) -> None:
        with self._lock:
            for val in (price, volume, timestamp):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._block(_REASON_VAL)
                    return

            if price <= 0.0 or volume <= 0.0:
                self._block(_REASON_VAL)
                return

            p = float(price)

            if self._prev_price is not None:
                diff = p - self._prev_price
                if diff > 1e-12:
                    current_sign = 1
                elif diff < -1e-12:
                    current_sign = -1
                else:
                    current_sign = 0

                if current_sign != 0:
                    if self._prev_sign is not None:
                        is_rev = 1 if current_sign != self._prev_sign else 0
                        self._transitions.append(is_rev)

                        if len(self._transitions) >= self._window_size:
                            rev_rate = sum(self._transitions) / len(self._transitions)
                            if rev_rate >= self._reversal_threshold:
                                self._block(_REASON_REVERSAL)

                    self._prev_sign = current_sign

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
            self._prev_sign = None
            self._transitions.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
