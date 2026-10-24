"""
Wave 344 -- LOB Queue Depletion Hazard Rate Guard
==================================================
Monitors the instantaneous hazard rate of inside depth depletion on the bid and ask
queues:
    Hazard Rate lambda(t) = - (1 / Q(t)) * (Delta Q(t) / Delta t)

When predatory aggressive sweeps rapidly chew through resting liquidity without
replenishment, lambda(t) spikes. If lambda(t) >= hazard_rate_threshold over a rolling
window, the guard preemptively halts execution to prevent getting filled right before
an imminent book level wipeout.

Blocking reasons
----------------
QUEUE_DEPLETION_HAZARD  -- Bid or Ask depletion hazard rate >= hazard_rate_threshold
INPUT_VALIDATION_ERROR  -- Non-positive, boolean or non-numeric inputs

Public API
----------
update(bid_size, ask_size, timestamp) -> None
is_blocked(current_time=None)         -> bool
is_entry_blocked(bid, ask, ts)        -> bool
reset()                               -> None
last_reason                           -> str
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave344LOBQueueDepletionHazardRateGuard"]

_REASON_HAZARD = "QUEUE_DEPLETION_HAZARD"
_REASON_VAL    = "INPUT_VALIDATION_ERROR"


class Wave344LOBQueueDepletionHazardRateGuard:
    """Monitors inside queue depletion hazard rate to guard against book wipeout."""

    def __init__(
        self,
        window_size: int = 10,
        hazard_rate_threshold: float = 2.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 4 or hazard_rate_threshold <= 0:
            raise ValueError("Invalid parameters for Queue Depletion Hazard Rate Guard.")
        self._window = int(window_size)
        self._threshold = float(hazard_rate_threshold)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._prev_bid_size: Optional[float] = None
        self._prev_ask_size: Optional[float] = None
        self._prev_ts: Optional[float] = None
        self._bid_hazards: deque = deque(maxlen=window_size)
        self._ask_hazards: deque = deque(maxlen=window_size)
        self._blocked_until = 0.0
        self._blocked_until_sim = 0.0
        self._last_reason = ""

    def update(self, bid_size: float, ask_size: float, timestamp: float) -> None:
        with self._lock:
            # Type and bool validations
            if isinstance(bid_size, bool) or isinstance(ask_size, bool) or isinstance(timestamp, bool):
                self._block(timestamp, _REASON_VAL)
                return
            if not (isinstance(bid_size, (int, float)) and isinstance(ask_size, (int, float)) and isinstance(timestamp, (int, float))):
                self._block(timestamp, _REASON_VAL)
                return

            bs = float(bid_size)
            as_ = float(ask_size)
            ts = float(timestamp)

            if bs <= 0 or as_ <= 0:
                self._block(ts, _REASON_VAL)
                return

            if self._prev_ts is not None and self._prev_bid_size is not None and self._prev_ask_size is not None:
                dt = ts - self._prev_ts
                if dt <= 0:
                    self._block(ts, _REASON_VAL)
                    self._prev_ts = ts
                    return

                # Hazard rate: - (1 / Q_prev) * (Delta Q / dt)
                # Only positive when queue is depleting (Delta Q < 0)
                d_bid = bs - self._prev_bid_size
                lambda_bid = (-d_bid / (self._prev_bid_size * dt)) if d_bid < 0 else 0.0

                d_ask = as_ - self._prev_ask_size
                lambda_ask = (-d_ask / (self._prev_ask_size * dt)) if d_ask < 0 else 0.0

                self._bid_hazards.append(lambda_bid)
                self._ask_hazards.append(lambda_ask)

                if len(self._bid_hazards) >= self._window:
                    avg_bid_h = sum(self._bid_hazards) / len(self._bid_hazards)
                    avg_ask_h = sum(self._ask_hazards) / len(self._ask_hazards)

                    if avg_bid_h >= self._threshold or avg_ask_h >= self._threshold:
                        self._block(ts, _REASON_HAZARD)

            self._prev_bid_size = bs
            self._prev_ask_size = as_
            self._prev_ts = ts

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
            self._prev_bid_size = None
            self._prev_ask_size = None
            self._prev_ts = None
            self._bid_hazards.clear()
            self._ask_hazards.clear()
            self._blocked_until = 0.0
            self._blocked_until_sim = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
