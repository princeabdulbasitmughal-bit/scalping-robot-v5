"""
Wave 394 -- Cross-Impact Queue Disbalance Guard
===============================================
Monitors cross-impact order queue depth asymmetry between bid and ask top-of-book.
Extreme structural disbalance in resting queue depth signals predatory quote
cancellation, phantom liquidity, or imminent severe price slippage.

Methodology
-----------
* Observes resting queue sizes: `bid_queue` and `ask_queue`.
* Validates positive finite depth values and non-boolean numeric timestamps.
* Computes instantaneous queue balance ratio:
    R = bid_queue / (bid_queue + ask_queue)
* Maintains a rolling window of size `window_size`.
* If mean(R) >= `high_ratio_threshold` -> blocks with `EXTREME_QUEUE_ASYMMETRY`.
* If mean(R) <= `low_ratio_threshold`  -> blocks with `EXTREME_QUEUE_ASYMMETRY`.

Blocking reasons
----------------
EXTREME_QUEUE_ASYMMETRY -- persistent queue depth imbalance beyond safety corridor
INPUT_VALIDATION_ERROR  -- negative/zero depth, non-numeric timestamp or invalid params

Public API (standardised)
-------------------------
update(bid_queue, ask_queue, timestamp) -> None
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

__all__ = ["Wave394CrossImpactQueueDisbalanceGuard"]

_REASON_ASYMMETRY = "EXTREME_QUEUE_ASYMMETRY"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave394CrossImpactQueueDisbalanceGuard:
    """LOB Cross-Impact Queue Disbalance Guard."""

    def __init__(
        self,
        window_size: int = 15,
        high_ratio_threshold: float = 0.85,
        low_ratio_threshold: float = 0.15,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 3 or not (0.0 <= low_ratio_threshold < high_ratio_threshold <= 1.0):
            raise ValueError("Invalid parameters for Wave394CrossImpactQueueDisbalanceGuard")
        self._window_size = int(window_size)
        self._high_ratio = float(high_ratio_threshold)
        self._low_ratio = float(low_ratio_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._ratios: deque[float] = deque(maxlen=self._window_size)
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(self, bid_queue: float, ask_queue: float, timestamp: float) -> None:
        with self._lock:
            for val in (bid_queue, ask_queue, timestamp):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._block(_REASON_VAL)
                    return

            if bid_queue < 0.0 or ask_queue < 0.0 or (bid_queue + ask_queue) <= 0.0:
                self._block(_REASON_VAL)
                return

            total_depth = float(bid_queue + ask_queue)
            ratio = float(bid_queue) / total_depth
            self._ratios.append(ratio)

            if len(self._ratios) >= self._window_size:
                avg_ratio = sum(self._ratios) / len(self._ratios)
                if avg_ratio >= self._high_ratio or avg_ratio <= self._low_ratio:
                    self._block(_REASON_ASYMMETRY)

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
            self._ratios.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
