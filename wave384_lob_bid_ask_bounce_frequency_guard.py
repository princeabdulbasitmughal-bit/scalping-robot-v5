"""
Wave 384 -- LOB Bid-Ask Bounce Frequency Guard
===============================================
Monitors rapid micro-price bouncing where the top-of-book bid or ask flickers
back and forth between identical prices across adjacent ticks.
Excessive bounce rates indicate high-frequency quote flickering, queue dancing,
or predatory latency pinging.

Methodology
-----------
* Observes best bid and ask at each tick.
* A bounce occurs at tick t if:
    (bid_t == bid_{t-2} and bid_t != bid_{t-1}) or
    (ask_t == ask_{t-2} and ask_t != ask_{t-1})
* Maintains a rolling window of recent bounce indicators over `window_size` ticks.
* If bounce frequency >= `bounce_rate_threshold`, blocks trading for `cooldown_seconds`.

Blocking reasons
----------------
HIGH_BOUNCE_FREQUENCY  -- excessive rapid quote alternation/flickering
INPUT_VALIDATION_ERROR -- malformed price inputs

Public API (standardised)
-------------------------
update(bid, ask, timestamp)    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave384LOBBidAskBounceFrequencyGuard"]

_REASON_BOUNCE = "HIGH_BOUNCE_FREQUENCY"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave384LOBBidAskBounceFrequencyGuard:
    """LOB bid-ask quote bounce and flickering frequency guard."""

    def __init__(
        self,
        window_size: int = 20,
        bounce_rate_threshold: float = 0.50,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 3 or not (0.0 < bounce_rate_threshold <= 1.0):
            raise ValueError("Invalid parameters for Wave384LOBBidAskBounceFrequencyGuard")
        self._window_size = int(window_size)
        self._bounce_thresh = float(bounce_rate_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._bids: deque[float] = deque(maxlen=3)
        self._asks: deque[float] = deque(maxlen=3)
        self._bounces: deque[int] = deque(maxlen=self._window_size)
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(self, bid: float, ask: float, timestamp: float) -> None:
        with self._lock:
            for val in (bid, ask, timestamp):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._block(_REASON_VAL)
                    return

            if bid <= 0.0 or ask <= 0.0 or ask <= bid:
                self._block(_REASON_VAL)
                return

            b = float(bid)
            a = float(ask)

            self._bids.append(b)
            self._asks.append(a)

            if len(self._bids) == 3:
                is_bid_bounce = (self._bids[2] == self._bids[0]) and (self._bids[2] != self._bids[1])
                is_ask_bounce = (self._asks[2] == self._asks[0]) and (self._asks[2] != self._asks[1])
                bounce = 1 if (is_bid_bounce or is_ask_bounce) else 0
                self._bounces.append(bounce)

                if len(self._bounces) >= self._window_size:
                    rate = sum(self._bounces) / len(self._bounces)
                    if rate >= self._bounce_thresh:
                        self._block(_REASON_BOUNCE)

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
            self._bids.clear()
            self._asks.clear()
            self._bounces.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
