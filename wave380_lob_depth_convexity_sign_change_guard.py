"""
Wave 380 -- LOB Depth Convexity Sign-Change Guard  [LANDMARK WAVE 380]
======================================================================
Monitors the stability of the order book curvature (depth convexity).
Rapid alternation in the sign of the second derivative of depth signals
erratic queue replenishment, chaotic cancellations, and microstructure instability.

Methodology
-----------
* Tracks bid depth across consecutive ticks.
* Computes discrete second derivative:
    d2 = (bid_depth_t - 2 * bid_depth_{t-1} + bid_depth_{t-2})
* A convexity sign change is recorded if sign(d2_t) != sign(d2_{t-1}) (for non-zero d2).
* Maintains a rolling window of recent curvature transitions.
* If convexity sign-change frequency >= `sign_change_threshold`, blocks trading.

Blocking reasons
----------------
LOB_CONVEXITY_INSTABILITY -- rapid flipping in depth curvature second-derivative
INPUT_VALIDATION_ERROR    -- non-numeric or non-positive depth inputs

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

__all__ = ["Wave380LOBDepthConvexitySignChangeGuard"]

_REASON_INSTABILITY = "LOB_CONVEXITY_INSTABILITY"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave380LOBDepthConvexitySignChangeGuard:
    """LOB depth curvature and second-derivative convexity instability guard."""

    def __init__(
        self,
        window_size: int = 15,
        sign_change_threshold: float = 0.60,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 3 or not (0.0 < sign_change_threshold <= 1.0):
            raise ValueError("Invalid parameters for Wave380LOBDepthConvexitySignChangeGuard")
        self._window_size = int(window_size)
        self._thresh = float(sign_change_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._d0: Optional[float] = None
        self._d1: Optional[float] = None
        self._prev_sign: Optional[int] = None
        self._transitions: deque[int] = deque(maxlen=self._window_size)
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

            if self._d0 is not None and self._d1 is not None:
                d2 = bd - 2.0 * self._d1 + self._d0
                if abs(d2) > 1e-9:
                    curr_sign = 1 if d2 > 0 else -1
                    if self._prev_sign is not None:
                        is_change = 1 if curr_sign != self._prev_sign else 0
                        self._transitions.append(is_change)

                        if len(self._transitions) >= self._window_size:
                            rate = sum(self._transitions) / len(self._transitions)
                            if rate >= self._thresh:
                                self._block(_REASON_INSTABILITY)

                    self._prev_sign = curr_sign

            self._d0 = self._d1
            self._d1 = bd

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
            self._d0 = None
            self._d1 = None
            self._prev_sign = None
            self._transitions.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
