"""
Wave 372 -- LOB Bid-Side Queue Exhaustion Guard
================================================
Monitors rapid depletion and drainage of resting bid liquidity in the LOB.
Sustained bid exhaustion indicates institutional selling or impending breakdown.

Methodology
-----------
* Track bid_depth and ask_depth at each tick.
* Compute single-tick bid exhaustion rate:
    rate = max(0.0, (prev_bid_depth - bid_depth) / prev_bid_depth)
* Over a rolling window of size `window_size`, calculate the mean exhaustion rate.
* If mean exhaustion rate >= `exhaustion_threshold`, block trading for `cooldown_seconds`.

Blocking reasons
----------------
BID_QUEUE_EXHAUSTION   -- rapid drain of resting bid depth exceeds threshold
INPUT_VALIDATION_ERROR -- malformed or invalid inputs

Public API (standardised)
-------------------------
update(bid_depth, ask_depth, timestamp) -> None
is_blocked(current_time=None)           -> bool
is_entry_blocked(bid, ask, ts)          -> bool
reset()                                 -> None
last_reason                             -> str
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave372LOBBidSideQueueExhaustionGuard"]

_REASON_EXHAUSTION = "BID_QUEUE_EXHAUSTION"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave372LOBBidSideQueueExhaustionGuard:
    """LOB bid-side queue exhaustion and depth drainage guard."""

    def __init__(
        self,
        window_size: int = 15,
        exhaustion_threshold: float = 0.20,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 2 or exhaustion_threshold <= 0:
            raise ValueError("Invalid parameters for Wave372LOBBidSideQueueExhaustionGuard")
        self._window_size = int(window_size)
        self._exhaustion_threshold = float(exhaustion_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._rates: deque[float] = deque(maxlen=self._window_size)
        self._prev_bid_depth: Optional[float] = None
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(self, bid_depth: float, ask_depth: float, timestamp: float) -> None:
        with self._lock:
            for val in (bid_depth, ask_depth, timestamp):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._block(_REASON_VAL)
                    return

            if bid_depth <= 0.0 or ask_depth <= 0.0:
                self._block(_REASON_VAL)
                return

            bd = float(bid_depth)

            if self._prev_bid_depth is not None and self._prev_bid_depth > 0.0:
                rate = max(0.0, (self._prev_bid_depth - bd) / self._prev_bid_depth)
                self._rates.append(rate)

                if len(self._rates) >= self._window_size:
                    mean_rate = sum(self._rates) / len(self._rates)
                    if mean_rate >= self._exhaustion_threshold:
                        self._block(_REASON_EXHAUSTION)

            self._prev_bid_depth = bd

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
            self._rates.clear()
            self._prev_bid_depth = None
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
