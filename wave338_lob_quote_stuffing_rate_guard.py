"""
Wave 338 — LOB Quote Stuffing Rate Guard
=========================================
Detects quote stuffing: abnormally high rate of LOB updates (quote inserts /
cancels) relative to the rate of actual trades.

Methodology
-----------
* Track quote-update events and trade events over a rolling time window
  of `window_seconds`.
* Compute stuffing_ratio = n_quotes / max(n_trades, 1).
* Block when:
  (a) stuffing_ratio >= `stuffing_ratio_threshold` AND
  (b) n_quotes >= `min_quote_count` (avoids noise on thin books)

Blocking reasons
----------------
QUOTE_STUFFING_DETECTED  — ratio threshold breached
INPUT_VALIDATION_ERROR   — malformed arguments

Public API (standardised)
-------------------------
add_quote(timestamp)                   -> None
add_trade(timestamp)                   -> None
is_blocked(current_time=None)          -> bool
is_entry_blocked(bid, ask, ts)         -> bool
reset()                                -> None
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave338LOBQuoteStuffingRateGuard"]

_REASON_STUFF = "QUOTE_STUFFING_DETECTED"
_REASON_VAL   = "INPUT_VALIDATION_ERROR"


class Wave338LOBQuoteStuffingRateGuard:
    """Quote-stuffing rate guard based on rolling quote/trade ratio."""

    def __init__(
        self,
        window_seconds: float = 1.0,
        stuffing_ratio_threshold: float = 50.0,
        min_quote_count: int = 20,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_seconds <= 0 or stuffing_ratio_threshold <= 0 or min_quote_count < 1:
            raise ValueError("Invalid quote stuffing guard parameters.")
        self._window      = float(window_seconds)
        self._ratio_thr   = float(stuffing_ratio_threshold)
        self._min_quotes  = int(min_quote_count)
        self._cooldown    = float(cooldown_seconds)

        self._lock        = threading.RLock()
        self._quotes: deque = deque()   # timestamps
        self._trades: deque = deque()   # timestamps
        self._blocked_until = 0.0
        self._last_reason   = ""

    # ------------------------------------------------------------------
    def _evict(self, now: float) -> None:
        cutoff = now - self._window
        while self._quotes and self._quotes[0] <= cutoff:
            self._quotes.popleft()
        while self._trades and self._trades[0] <= cutoff:
            self._trades.popleft()

    def add_quote(self, timestamp: float) -> None:
        with self._lock:
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                self._block(time.monotonic(), _REASON_VAL)
                return
            self._quotes.append(float(timestamp))
            self._evict(float(timestamp))
            self._evaluate(float(timestamp))

    def add_trade(self, timestamp: float) -> None:
        with self._lock:
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                self._block(time.monotonic(), _REASON_VAL)
                return
            self._trades.append(float(timestamp))
            self._evict(float(timestamp))

    def _evaluate(self, timestamp: float) -> None:
        n_q = len(self._quotes)
        n_t = len(self._trades)
        if n_q < self._min_quotes:
            return
        ratio = n_q / max(n_t, 1)
        if ratio >= self._ratio_thr:
            self._block(timestamp, _REASON_STUFF)

    def _block(self, timestamp: float, reason: str) -> None:
        self._blocked_until = time.monotonic() + self._cooldown
        self._last_reason   = reason

    # ------------------------------------------------------------------
    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            t = time.monotonic() if current_time is None else current_time
            return t < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: float) -> bool:
        return self.is_blocked(ts)

    def reset(self) -> None:
        with self._lock:
            self._quotes.clear()
            self._trades.clear()
            self._blocked_until = 0.0
            self._last_reason   = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
