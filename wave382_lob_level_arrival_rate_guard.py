"""
Wave 382 -- LOB Level Arrival Rate Guard
=========================================
Monitors the arrival velocity of newly created price levels in the LOB.
An abnormally rapid arrival of discrete price levels signals multi-level spoofing,
quote flooding, or micro-level quote flickering.

Methodology
-----------
* Observes snapshots of active price levels: `bid_levels` and `ask_levels`.
* Compares current levels with the previous level set to determine novel price steps.
* Records timestamps of newly created price levels within a rolling window of `window_seconds`.
* Computes level arrival rate = len(recent_new_levels) / window_seconds.
* If arrival rate >= `max_arrival_rate`, blocks trading for `cooldown_seconds`.

Blocking reasons
----------------
LEVEL_ARRIVAL_RATE_BREACH -- excessive rate of new price level generation
INPUT_VALIDATION_ERROR    -- malformed list or non-numeric level inputs

Public API (standardised)
-------------------------
update(bid_levels, ask_levels, timestamp) -> None
is_blocked(current_time=None)             -> bool
is_entry_blocked(bid, ask, ts)            -> bool
reset()                                   -> None
last_reason                               -> str
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional, Sequence

__all__ = ["Wave382LOBLevelArrivalRateGuard"]

_REASON_LEVELS = "LEVEL_ARRIVAL_RATE_BREACH"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave382LOBLevelArrivalRateGuard:
    """LOB discrete price level arrival frequency and spoofing guard."""

    def __init__(
        self,
        window_seconds: float = 1.0,
        max_arrival_rate: float = 20.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_seconds <= 0.0 or max_arrival_rate <= 0.0:
            raise ValueError("Invalid parameters for Wave382LOBLevelArrivalRateGuard")
        self._window_seconds = float(window_seconds)
        self._max_arrival_rate = float(max_arrival_rate)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._prev_levels: Optional[set[float]] = None
        self._arrivals: deque[float] = deque()  # timestamps of novel levels
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(
        self,
        bid_levels: Sequence[float],
        ask_levels: Sequence[float],
        timestamp: float,
    ) -> None:
        with self._lock:
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                self._block(_REASON_VAL)
                return

            if not isinstance(bid_levels, (list, tuple)) or not isinstance(ask_levels, (list, tuple)):
                self._block(_REASON_VAL)
                return

            try:
                current_levels: set[float] = set()
                for lvl in bid_levels:
                    if isinstance(lvl, bool) or not isinstance(lvl, (int, float)) or lvl <= 0.0:
                        self._block(_REASON_VAL)
                        return
                    current_levels.add(round(float(lvl), 7))

                for lvl in ask_levels:
                    if isinstance(lvl, bool) or not isinstance(lvl, (int, float)) or lvl <= 0.0:
                        self._block(_REASON_VAL)
                        return
                    current_levels.add(round(float(lvl), 7))
            except Exception:
                self._block(_REASON_VAL)
                return

            ts = float(timestamp)

            if self._prev_levels is not None:
                new_levels_count = len(current_levels - self._prev_levels)
                for _ in range(new_levels_count):
                    self._arrivals.append(ts)

                # Evict stale arrivals
                cutoff = ts - self._window_seconds
                while self._arrivals and self._arrivals[0] < cutoff:
                    self._arrivals.popleft()

                rate = len(self._arrivals) / self._window_seconds
                if rate >= self._max_arrival_rate:
                    self._block(_REASON_LEVELS)

            self._prev_levels = current_levels

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
            self._prev_levels = None
            self._arrivals.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
