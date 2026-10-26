"""
Wave 375 -- Trade Flow Order Splitting Detection Guard
======================================================
Detects algorithmic child-order slicing and order splitting (e.g., TWAP/VWAP execution
sweeps slicing a parent order into numerous small same-direction executions).

Methodology
-----------
* Examines incoming trade executions: volume and side ('buy' or 'sell').
* A trade is classified as a split candidate if volume <= `small_trade_threshold`.
* Tracks consecutive split-candidate executions in the identical direction.
* If the run-length of identical-direction small trades reaches or exceeds
  `max_split_sequence`, blocks trading for `cooldown_seconds`.

Blocking reasons
----------------
ORDER_SPLITTING_DETECTED -- sustained run of child-order slicing on same side
INPUT_VALIDATION_ERROR   -- invalid side, volume, or timestamp

Public API (standardised)
-------------------------
update(volume, side, timestamp) -> None
is_blocked(current_time=None)   -> bool
is_entry_blocked(bid, ask, ts)  -> bool
reset()                         -> None
last_reason                     -> str
"""

from __future__ import annotations

import threading
import time
from typing import Optional

__all__ = ["Wave375TradeFlowOrderSplittingDetectionGuard"]

_REASON_SPLIT = "ORDER_SPLITTING_DETECTED"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave375TradeFlowOrderSplittingDetectionGuard:
    """Trade flow order splitting and child-order execution burst guard."""

    def __init__(
        self,
        small_trade_threshold: float = 10.0,
        max_split_sequence: int = 8,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if small_trade_threshold <= 0.0 or max_split_sequence < 2:
            raise ValueError("Invalid parameters for Wave375TradeFlowOrderSplittingDetectionGuard")
        self._small_thresh = float(small_trade_threshold)
        self._max_seq = int(max_split_sequence)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._consecutive_count = 0
        self._current_side: Optional[str] = None
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(self, volume: float, side: str, timestamp: float) -> None:
        with self._lock:
            for val in (volume, timestamp):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._block(_REASON_VAL)
                    return

            if volume <= 0.0 or side not in ("buy", "sell"):
                self._block(_REASON_VAL)
                return

            v = float(volume)
            s = str(side)

            if v <= self._small_thresh:
                if self._current_side == s:
                    self._consecutive_count += 1
                else:
                    self._current_side = s
                    self._consecutive_count = 1

                if self._consecutive_count >= self._max_seq:
                    self._block(_REASON_SPLIT)
            else:
                # Large trade breaks the split sequence
                self._consecutive_count = 0
                self._current_side = None

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
            self._consecutive_count = 0
            self._current_side = None
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
