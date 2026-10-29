"""
Wave 416 -- Queue Cancellation Ratio & Ghost Liquidity Guard
============================================================
Monitors high-frequency order cancellation-to-fill ratios and order lifetimes.
In toxic electronic microstructure, predatory algorithms post transient phantom limit
orders ("ghost liquidity") to probe institutional depth, canceling them within sub-
milliseconds. When the cancellation ratio spikes or average order lifetime collapses,
available book depth is illusory and aggressive market orders incur severe slippage.

Methodology
-----------
* Observes order events: (event_type in {"INSERT", "FILL", "CANCEL"}, lifetime_ms, timestamp).
* Maintains a rolling window of N events (`window_size`).
* Computes cancellation ratio:
    R_{cancel} = N_{cancel} / max(N_{fill} + N_{cancel}, 1)
* Computes average order lifetime:
    tau_{mean} = mean(lifetime_ms for CANCEL and FILL events)
* If R_{cancel} >= `max_cancellation_ratio`, blocks with EXCESS_QUEUE_CANCELLATION.
* If tau_{mean} <= `min_lifetime_ms` and R_{cancel} >= 0.50, blocks with GHOST_LIQUIDITY_COLLAPSE.

Blocking reasons
----------------
EXCESS_QUEUE_CANCELLATION -- cancellation ratio exceeded safety threshold
GHOST_LIQUIDITY_COLLAPSE  -- fleeting order lifetimes reveal phantom quote probing
INPUT_VALIDATION_ERROR    -- invalid event type, negative lifetime, or non-monotonic ts

Public API (standardised)
-------------------------
update(event_type, lifetime_ms, timestamp) -> None
is_blocked(current_time=None)              -> bool
is_entry_blocked(bid, ask, ts)             -> bool
reset()                                    -> None
last_reason                                -> str
cancellation_ratio                         -> float
mean_lifetime_ms                           -> float
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave416QueueCancellationRatioGuard"]

_REASON_CANCEL = "EXCESS_QUEUE_CANCELLATION"
_REASON_GHOST = "GHOST_LIQUIDITY_COLLAPSE"
_REASON_VAL = "INPUT_VALIDATION_ERROR"
_VALID_EVENTS = {"INSERT", "FILL", "CANCEL"}


class Wave416QueueCancellationRatioGuard:
    """Queue Cancellation Ratio and Ghost Liquidity Guard."""

    def __init__(
        self,
        window_size: int = 15,
        max_cancellation_ratio: float = 0.85,
        min_lifetime_ms: float = 50.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            window_size < 5
            or not (0.20 <= max_cancellation_ratio <= 0.98)
            or min_lifetime_ms <= 0.0
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave416QueueCancellationRatioGuard")

        self._window_size = int(window_size)
        self._max_cancel_ratio = float(max_cancellation_ratio)
        self._min_lifetime = float(min_lifetime_ms)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._events: deque[str] = deque(maxlen=self._window_size)
        self._lifetimes: deque[float] = deque(maxlen=self._window_size)
        self._cancellation_ratio: float = 0.0
        self._mean_lifetime_ms: float = 1000.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def cancellation_ratio(self) -> float:
        with self._lock:
            return self._cancellation_ratio

    @property
    def mean_lifetime_ms(self) -> float:
        with self._lock:
            return self._mean_lifetime_ms

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._events.clear()
            self._lifetimes.clear()
            self._cancellation_ratio = 0.0
            self._mean_lifetime_ms = 1000.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(self, event_type: str, lifetime_ms: float, timestamp: float) -> None:
        with self._lock:
            ev = str(event_type).upper() if isinstance(event_type, str) else ""
            if (
                ev not in _VALID_EVENTS
                or not isinstance(lifetime_ms, (int, float))
                or not isinstance(timestamp, (int, float))
                or lifetime_ms < 0.0
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if timestamp > 0 else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)
            self._events.append(ev)
            self._lifetimes.append(float(lifetime_ms))

            if len(self._events) >= self._window_size:
                cancels = sum(1 for e in self._events if e == "CANCEL")
                fills = sum(1 for e in self._events if e == "FILL")
                active = cancels + fills

                if active > 0:
                    cancel_ratio = cancels / float(active)
                    self._cancellation_ratio = cancel_ratio

                    avg_lifetime = sum(self._lifetimes) / float(len(self._lifetimes))
                    self._mean_lifetime_ms = avg_lifetime

                    if cancel_ratio >= self._max_cancel_ratio:
                        self._block(_REASON_CANCEL, ts)
                    elif avg_lifetime <= self._min_lifetime and cancel_ratio >= 0.50:
                        self._block(_REASON_GHOST, ts)

            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
