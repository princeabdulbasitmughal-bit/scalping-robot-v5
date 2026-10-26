"""
Wave 388 -- LOB Depth-Weighted Spread Guard
============================================
Monitors depth-imbalance-weighted effective spread (DWS).
When the order book experiences severe liquidity imbalance, crossing the spread
incurs elevated market-impact slippage well beyond the nominal quoted spread.

Methodology
-----------
* Computes nominal spread in basis points:
    spread_bps = ((ask - bid) / mid) * 10,000.0
* Computes depth imbalance:
    imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)  [-1, +1]
* Depth-weighted spread:
    DWS = spread_bps * (1.0 + imbalance^2)
* Maintains rolling window of last `window_size` DWS observations.
* Blocks if rolling mean DWS >= `dws_threshold_bps`.

Blocking reasons
----------------
DWS_BREACH             -- depth-weighted effective spread exceeds safe threshold
INPUT_VALIDATION_ERROR -- malformed price or depth inputs

Public API (standardised)
-------------------------
update(bid, ask, bid_depth, ask_depth, timestamp) -> None
is_blocked(current_time=None)                     -> bool
is_entry_blocked(bid, ask, ts)                    -> bool
reset()                                           -> None
last_reason                                       -> str
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave388LOBDepthWeightedSpreadGuard"]

_REASON_DWS = "DWS_BREACH"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave388LOBDepthWeightedSpreadGuard:
    """LOB depth-weighted spread (DWS) and effective liquidity penalty guard."""

    def __init__(
        self,
        window_size: int = 15,
        dws_threshold_bps: float = 4.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 2 or dws_threshold_bps <= 0.0:
            raise ValueError("Invalid parameters for Wave388LOBDepthWeightedSpreadGuard")
        self._window_size = int(window_size)
        self._dws_threshold = float(dws_threshold_bps)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._dws_history: deque[float] = deque(maxlen=self._window_size)
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(
        self,
        bid: float,
        ask: float,
        bid_depth: float,
        ask_depth: float,
        timestamp: float,
    ) -> None:
        with self._lock:
            for val in (bid, ask, bid_depth, ask_depth, timestamp):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._block(_REASON_VAL)
                    return

            if bid <= 0.0 or ask <= 0.0 or ask <= bid:
                self._block(_REASON_VAL)
                return
            if bid_depth <= 0.0 or ask_depth <= 0.0:
                self._block(_REASON_VAL)
                return

            mid = (bid + ask) / 2.0
            spread_bps = ((ask - bid) / mid) * 10_000.0
            tot_depth = bid_depth + ask_depth
            imbalance = (bid_depth - ask_depth) / tot_depth
            dws = spread_bps * (1.0 + imbalance * imbalance)

            self._dws_history.append(dws)

            if len(self._dws_history) >= self._window_size:
                mean_dws = sum(self._dws_history) / len(self._dws_history)
                if mean_dws >= self._dws_threshold:
                    self._block(_REASON_DWS)

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
            self._dws_history.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
