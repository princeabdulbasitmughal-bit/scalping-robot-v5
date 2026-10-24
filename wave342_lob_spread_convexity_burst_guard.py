"""
Wave 342 -- LOB Spread Convexity Burst Guard
=============================================
Monitors the second difference (spread convexity / acceleration) of the
bid-ask spread:
    Spread S_t = Ask_t - Bid_t
    Velocity  Delta S_t = S_t - S_{t-1}
    Convexity Delta^2 S_t = Delta S_t - Delta S_{t-1} = S_t - 2*S_{t-1} + S_{t-2}

A sharp positive spike in spread convexity indicates an explosive liquidity vacuum
or predatory sweep, triggering preemptive protection before toxic slippage occurs.

Blocking reasons
----------------
SPREAD_CONVEXITY_BURST   -- Convexity z-score >= convexity_threshold
CROSSED_QUOTES_ERROR     -- bid >= ask
INPUT_VALIDATION_ERROR   -- malformed or non-positive inputs

Public API
----------
update(bid, ask, timestamp)    -> None
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

__all__ = ["Wave342LOBSpreadConvexityBurstGuard"]

_REASON_BURST   = "SPREAD_CONVEXITY_BURST"
_REASON_CROSSED = "CROSSED_QUOTES_ERROR"
_REASON_VAL     = "INPUT_VALIDATION_ERROR"


class Wave342LOBSpreadConvexityBurstGuard:
    """Detects explosive spread acceleration and liquidity vacuums via spread convexity."""

    def __init__(
        self,
        window_size: int = 15,
        convexity_threshold: float = 3.5,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 5 or convexity_threshold <= 0:
            raise ValueError("Invalid parameters for Spread Convexity Burst Guard.")
        self._window = int(window_size)
        self._threshold = float(convexity_threshold)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._spread_history: deque = deque(maxlen=window_size + 2)
        self._convexity_history: deque = deque(maxlen=window_size)
        self._blocked_until = 0.0
        self._blocked_until_sim = 0.0
        self._last_reason = ""

    def update(self, bid: float, ask: float, timestamp: float) -> None:
        with self._lock:
            # Type and bool validations
            if isinstance(bid, bool) or isinstance(ask, bool) or isinstance(timestamp, bool):
                self._block(timestamp, _REASON_VAL)
                return
            if not (isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and isinstance(timestamp, (int, float))):
                self._block(timestamp, _REASON_VAL)
                return

            b = float(bid)
            a = float(ask)
            ts = float(timestamp)

            if b <= 0 or a <= 0:
                self._block(ts, _REASON_VAL)
                return

            if b >= a:
                self._block(ts, _REASON_CROSSED)
                return

            spread = a - b
            self._spread_history.append(spread)

            if len(self._spread_history) >= 3:
                s_t = self._spread_history[-1]
                s_t1 = self._spread_history[-2]
                s_t2 = self._spread_history[-3]
                # Second difference: acceleration of spread expansion
                convexity = s_t - 2.0 * s_t1 + s_t2
                self._convexity_history.append(convexity)

                if len(self._convexity_history) >= self._window:
                    convs = list(self._convexity_history)
                    n = len(convs)
                    mean_c = sum(convs) / n
                    var_c = sum((c - mean_c) ** 2 for c in convs) / n
                    std_c = math.sqrt(var_c)

                    if std_c > 1e-8:
                        z_score = (convexity - mean_c) / std_c
                        if z_score >= self._threshold:
                            self._block(ts, _REASON_BURST)

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
            self._spread_history.clear()
            self._convexity_history.clear()
            self._blocked_until = 0.0
            self._blocked_until_sim = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
