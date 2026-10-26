"""
Wave 378 -- LOB Quote Cancellation Storm Guard
===============================================
Detects rapid bursts of quote cancellations relative to total quote submissions.
A cancellation storm (e.g., >80% cancels in 2 seconds) signals algorithmic quote
stuffing, phantom liquidity evaporation, or spoofing retractions.

Methodology
-----------
* Tracks quote submissions and cancellations within a rolling time window of `window_seconds`.
* At each event (submission or cancel), evicts events older than (now - window_seconds).
* Cancellation ratio = cancel_count / max(total_events, 1).
* If total_events >= `min_quote_count` and cancellation ratio >= `cancel_ratio_threshold`,
  blocks trading for `cooldown_seconds`.

Blocking reasons
----------------
CANCELLATION_STORM_DETECTED -- excessive cancellation fraction in short window
INPUT_VALIDATION_ERROR      -- malformed arguments

Public API (standardised)
-------------------------
add_quote(is_cancel, timestamp) -> None
update(is_cancel, timestamp)    -> None
is_blocked(current_time=None)   -> bool
is_entry_blocked(bid, ask, ts)  -> bool
reset()                         -> None
last_reason                     -> str
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave378LOBQuoteCancellationStormGuard"]

_REASON_STORM = "CANCELLATION_STORM_DETECTED"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave378LOBQuoteCancellationStormGuard:
    """LOB quote cancellation storm and phantom liquidity retreat guard."""

    def __init__(
        self,
        window_seconds: float = 2.0,
        cancel_ratio_threshold: float = 0.80,
        min_quote_count: int = 10,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_seconds <= 0.0 or not (0.0 < cancel_ratio_threshold <= 1.0) or min_quote_count < 2:
            raise ValueError("Invalid parameters for Wave378LOBQuoteCancellationStormGuard")
        self._window_seconds = float(window_seconds)
        self._cancel_threshold = float(cancel_ratio_threshold)
        self._min_quotes = int(min_quote_count)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._events: deque[tuple[float, bool]] = deque()  # (ts, is_cancel)
        self._blocked_until = 0.0
        self._last_reason = ""

    def add_quote(self, is_cancel: bool, timestamp: float) -> None:
        with self._lock:
            if not isinstance(is_cancel, bool):
                self._block(_REASON_VAL)
                return
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                self._block(_REASON_VAL)
                return

            ts = float(timestamp)
            self._events.append((ts, is_cancel))

            # Evict stale events
            cutoff = ts - self._window_seconds
            while self._events and self._events[0][0] < cutoff:
                self._events.popleft()

            total = len(self._events)
            if total >= self._min_quotes:
                cancels = sum(1 for _, c in self._events if c)
                ratio = cancels / total
                if ratio >= self._cancel_threshold:
                    self._block(_REASON_STORM)

    def update(self, is_cancel: bool, timestamp: float) -> None:
        self.add_quote(is_cancel, timestamp)

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
            self._events.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
