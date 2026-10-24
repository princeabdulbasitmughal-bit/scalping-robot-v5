"""
Wave 340 -- LOB Depth-Weighted Mid-Price Skew Persistence Guard  [Landmark Wave 340]
====================================================================================
Monitors whether the depth-weighted mid-price (micro-price) is persistently
skewed away from the arithmetic mid-price.  Persistent skew indicates sustained
order-book imbalance and signals elevated adverse-selection risk.

Methodology
-----------
* micro_price = (bid * ask_size + ask * bid_size) / (bid_size + ask_size)
* skew_i      = micro_price_i - mid_price_i
* Maintain rolling deque of the last `window_size` skews.
* mean_skew   = mean(skews in window)
* std_skew    = std(skews in window)
* Persist index = |mean_skew| / max(std_skew, epsilon)   (signal-to-noise ratio)
* Block when persist_index >= `persist_threshold` AND
             |mean_skew| >= `min_skew_bps` * mid_price / 10000

Blocking reasons
----------------
MICRO_PRICE_SKEW_PERSISTENCE   -- skew is persistent and significant
INPUT_VALIDATION_ERROR         -- malformed arguments

Public API (standardised)
-------------------------
update(bid, ask, bid_size, ask_size, timestamp) -> None
is_blocked(current_time=None)                   -> bool
is_entry_blocked(bid, ask, ts)                  -> bool
reset()                                         -> None
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave340LOBDepthWeightedMidPriceSkewPersistenceGuard"]

_REASON_SKEW = "MICRO_PRICE_SKEW_PERSISTENCE"
_REASON_VAL  = "INPUT_VALIDATION_ERROR"
_EPS         = 1e-10


class Wave340LOBDepthWeightedMidPriceSkewPersistenceGuard:
    """Depth-weighted micro-price skew persistence guard."""

    def __init__(
        self,
        window_size: int = 20,
        persist_threshold: float = 2.0,
        min_skew_bps: float = 0.5,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if window_size < 4 or persist_threshold <= 0 or min_skew_bps <= 0:
            raise ValueError("Invalid micro-price skew persistence guard parameters.")
        self._window    = int(window_size)
        self._persist_t = float(persist_threshold)
        self._min_skew  = float(min_skew_bps)
        self._cooldown  = float(cooldown_seconds)

        self._lock      = threading.RLock()
        self._skews: deque = deque(maxlen=window_size)
        self._blocked_until = 0.0
        self._last_reason   = ""

    # ------------------------------------------------------------------
    def update(
        self,
        bid: float,
        ask: float,
        bid_size: float,
        ask_size: float,
        timestamp: float,
    ) -> None:
        with self._lock:
            for v in (bid, ask, bid_size, ask_size):
                if isinstance(v, bool):
                    self._block(timestamp, _REASON_VAL)
                    return
                if not isinstance(v, (int, float)):
                    self._block(timestamp, _REASON_VAL)
                    return
            if bid <= 0 or ask <= 0 or ask <= bid:
                self._block(timestamp, _REASON_VAL)
                return
            if bid_size <= 0 or ask_size <= 0:
                self._block(timestamp, _REASON_VAL)
                return

            mid         = (bid + ask) / 2.0
            total_size  = bid_size + ask_size
            micro_price = (bid * ask_size + ask * bid_size) / total_size
            skew        = micro_price - mid
            self._skews.append(skew)

            if len(self._skews) < self._window:
                return

            skews = list(self._skews)
            n     = len(skews)
            mean_s = sum(skews) / n
            var_s  = sum((s - mean_s) ** 2 for s in skews) / n
            std_s  = math.sqrt(var_s)

            persist_idx = abs(mean_s) / max(std_s, _EPS)
            min_skew_abs = self._min_skew * mid / 10_000.0

            if persist_idx >= self._persist_t and abs(mean_s) >= min_skew_abs:
                self._block(timestamp, _REASON_SKEW)

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
            self._skews.clear()
            self._blocked_until = 0.0
            self._last_reason   = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
