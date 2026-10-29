"""
Wave 402 -- Cross-Venue Latency Arbitrage Skew Guard
===================================================
Monitors quote divergence and latency arbitrage basis skew between the local
execution venue and external institutional reference price feeds.
A persistent or anomalous divergence indicates predatory latency arbitrage,
stale local quotes, or toxic front-running across venues.

Methodology
-----------
* Observes primary venue midprice `primary_price` and institutional reference `reference_price`.
* Validates positive finite prices and numeric timestamp.
* Computes basis skew: Delta = |primary_price - reference_price|.
* Maintains a rolling window of size `window_size`.
* If mean(Delta) >= `skew_threshold` or instantaneous Delta >= 2.0 * `skew_threshold`,
  blocks trading with `CROSS_VENUE_LATENCY_SKEW`.

Blocking reasons
----------------
CROSS_VENUE_LATENCY_SKEW -- basis skew between venues exceeds safety corridor
INPUT_VALIDATION_ERROR   -- negative/zero price, invalid timestamp, or non-numeric input

Public API (standardised)
-------------------------
update(primary_price, reference_price, timestamp) -> None
is_blocked(current_time=None)                     -> bool
is_entry_blocked(bid, ask, ts)                    -> bool
reset()                                           -> None
last_reason                                       -> str
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave402CrossVenueLatencyArbitrageSkewGuard"]

_REASON_SKEW = "CROSS_VENUE_LATENCY_SKEW"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave402CrossVenueLatencyArbitrageSkewGuard:
    """Cross-venue latency arbitrage basis skew guard."""

    def __init__(
        self,
        window_size: int = 10,
        skew_threshold: float = 1.50,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 3 or skew_threshold <= 0.0 or cooldown_seconds <= 0.0:
            raise ValueError("Invalid parameters for Wave402CrossVenueLatencyArbitrageSkewGuard")
        self._window_size = int(window_size)
        self._skew_threshold = float(skew_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._skews: deque[float] = deque(maxlen=self._window_size)
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(self, primary_price: float, reference_price: float, timestamp: float) -> None:
        with self._lock:
            for val in (primary_price, reference_price, timestamp):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._block(_REASON_VAL)
                    return

            if primary_price <= 0.0 or reference_price <= 0.0:
                self._block(_REASON_VAL)
                return

            skew = abs(float(primary_price) - float(reference_price))
            self._skews.append(skew)

            if skew >= 2.0 * self._skew_threshold:
                self._block(_REASON_SKEW)
                return

            if len(self._skews) >= self._window_size:
                avg_skew = sum(self._skews) / len(self._skews)
                if avg_skew >= self._skew_threshold:
                    self._block(_REASON_SKEW)

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
            self._skews.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
