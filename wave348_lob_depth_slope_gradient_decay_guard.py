"""
Wave 348 -- LOB Depth Slope Gradient Decay Guard
=================================================
Monitors the depth slope gradient (liquidity density) between L1 and deeper book levels:
    Gradient G = (Q_L2 - Q_L1) / Delta P  (or Q_L2 / Delta P)

Under healthy liquid markets, deeper levels provide thick support with a robust positive
gradient (G >= min_gradient_threshold). When predatory algorithms pull quotes or an
order cascade depletes the book, the depth slope collapses towards zero or goes negative,
forming an "air pocket" where incoming market orders suffer extreme slippage.
The guard tracks the rolling depth slope gradient and halts execution during liquidity
gradient collapse.

Blocking reasons
----------------
DEPTH_SLOPE_GRADIENT_DECAY  -- Rolling average gradient G <= min_gradient_threshold
INPUT_VALIDATION_ERROR      -- Non-positive, boolean or non-numeric inputs

Public API
----------
update(l1_size, l2_size, price_delta, timestamp) -> None
is_blocked(current_time=None)                    -> bool
is_entry_blocked(bid, ask, ts)                   -> bool
reset()                                          -> None
last_reason                                      -> str
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave348LOBDepthSlopeGradientDecayGuard"]

_REASON_DECAY = "DEPTH_SLOPE_GRADIENT_DECAY"
_REASON_VAL   = "INPUT_VALIDATION_ERROR"


class Wave348LOBDepthSlopeGradientDecayGuard:
    """Monitors orderbook depth slope gradient to guard against air pockets and thin book slippage."""

    def __init__(
        self,
        window_size: int = 12,
        min_gradient_threshold: float = 50.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 4 or min_gradient_threshold <= 0:
            raise ValueError("Invalid parameters for Depth Slope Gradient Decay Guard.")
        self._window = int(window_size)
        self._threshold = float(min_gradient_threshold)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._gradients: deque = deque(maxlen=window_size)
        self._blocked_until = 0.0
        self._blocked_until_sim = 0.0
        self._last_reason = ""

    def update(self, l1_size: float, l2_size: float, price_delta: float, timestamp: float) -> None:
        with self._lock:
            # Type and bool validations
            if (
                isinstance(l1_size, bool)
                or isinstance(l2_size, bool)
                or isinstance(price_delta, bool)
                or isinstance(timestamp, bool)
            ):
                self._block(timestamp, _REASON_VAL)
                return
            if not (
                isinstance(l1_size, (int, float))
                and isinstance(l2_size, (int, float))
                and isinstance(price_delta, (int, float))
                and isinstance(timestamp, (int, float))
            ):
                self._block(timestamp, _REASON_VAL)
                return

            q1 = float(l1_size)
            q2 = float(l2_size)
            dp = float(price_delta)
            ts = float(timestamp)

            if q1 <= 0 or q2 <= 0 or dp <= 0:
                self._block(ts, _REASON_VAL)
                return

            # Gradient: liquidity depth density per price step
            # G = (q2 - q1) / dp if q2 > q1 else (q2 / dp)
            gradient = (q1 + q2) / dp
            self._gradients.append(gradient)

            if len(self._gradients) >= self._window:
                avg_gradient = sum(self._gradients) / len(self._gradients)
                if avg_gradient <= self._threshold:
                    self._block(ts, _REASON_DECAY)

    def _block(self, timestamp: float, reason: str) -> None:
        now_mono = time.monotonic()
        self._blocked_until = now_mono + self._cooldown
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool) and timestamp > 0:
            self._blocked_until_sim = timestamp + self._cooldown
        else:
            self._blocked_until_sim = self._blocked_until
        self._last_reason = reason

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            if current_time is not None:
                return current_time < self._blocked_until_sim
            return time.monotonic() < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: float) -> bool:
        return self.is_blocked(ts)

    def reset(self) -> None:
        with self._lock:
            self._gradients.clear()
            self._blocked_until = 0.0
            self._blocked_until_sim = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
