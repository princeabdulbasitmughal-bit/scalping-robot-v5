"""
Wave 376 -- LOB Asymmetric Depth Replenishment Guard
=====================================================
Monitors unequal replenishment dynamics between bid and ask book depths.
Severe asymmetry where one side replenishes significantly faster than the other
signals directional institutional queue positioning or unilateral liquidity withdrawal.

Methodology
-----------
* Tracks changes in depth:
    delta_bid = bid_depth_t - bid_depth_{t-1}
    delta_ask = ask_depth_t - ask_depth_{t-1}
* Asymmetry delta = delta_bid - delta_ask.
* Maintains rolling window of last `window_size` delta observations.
* Computes mean replenishment asymmetry over window.
* Blocks if mean asymmetry >= `positive_threshold` (aggressive bid accumulation)
  or <= `negative_threshold` (aggressive ask accumulation).

Blocking reasons
----------------
BID_REPLENISHMENT_ASYMMETRY -- bids refilling significantly faster than asks
ASK_REPLENISHMENT_ASYMMETRY -- asks refilling significantly faster than bids
INPUT_VALIDATION_ERROR      -- malformed or negative inputs

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

__all__ = ["Wave376LOBAsymmetricDepthReplenishmentGuard"]

_REASON_BID_ASYMM = "BID_REPLENISHMENT_ASYMMETRY"
_REASON_ASK_ASYMM = "ASK_REPLENISHMENT_ASYMMETRY"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave376LOBAsymmetricDepthReplenishmentGuard:
    """LOB asymmetric depth replenishment and book loading guard."""

    def __init__(
        self,
        window_size: int = 15,
        positive_threshold: float = 100.0,
        negative_threshold: float = -100.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 2 or positive_threshold <= 0.0 or negative_threshold >= 0.0:
            raise ValueError("Invalid parameters for Wave376LOBAsymmetricDepthReplenishmentGuard")
        self._window_size = int(window_size)
        self._pos_thresh = float(positive_threshold)
        self._neg_thresh = float(negative_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._prev_bid: Optional[float] = None
        self._prev_ask: Optional[float] = None
        self._asymmetries: deque[float] = deque(maxlen=self._window_size)
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
            ad = float(ask_depth)

            if self._prev_bid is not None and self._prev_ask is not None:
                delta_b = bd - self._prev_bid
                delta_a = ad - self._prev_ask
                asymm = delta_b - delta_a
                self._asymmetries.append(asymm)

                if len(self._asymmetries) >= self._window_size:
                    mean_asymm = sum(self._asymmetries) / len(self._asymmetries)
                    if mean_asymm >= self._pos_thresh:
                        self._block(_REASON_BID_ASYMM)
                    elif mean_asymm <= self._neg_thresh:
                        self._block(_REASON_ASK_ASYMM)

            self._prev_bid = bd
            self._prev_ask = ad

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
            self._prev_bid = None
            self._prev_ask = None
            self._asymmetries.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
