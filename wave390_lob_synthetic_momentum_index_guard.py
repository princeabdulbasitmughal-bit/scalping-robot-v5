"""
Wave 390 -- LOB Synthetic Momentum Index Guard
===============================================
Computes the Synthetic Momentum Index (SMI) combining order book queue depth ratio
and nominal bid-ask spread:
    SMI = (bid_depth / ask_depth) * (1.0 / spread_bps) * 100.0
Severe positive SMI spikes indicate one-sided buyer crowding; collapsing SMI
indicates severe seller overhang and withdrawal of resting bids.

Methodology
-----------
* Calculates SMI at each tick.
* Tracks a rolling window of recent SMI values of size `window_size`.
* If rolling mean SMI >= `upper_smi_threshold`, blocks with `SMI_UPPER_BREACH`.
* If rolling mean SMI <= `lower_smi_threshold`, blocks with `SMI_LOWER_BREACH`.

Blocking reasons
----------------
SMI_UPPER_BREACH       -- excessive bullish depth crowding and spread squeeze
SMI_LOWER_BREACH       -- severe bid exhaustion and bearish order book collapse
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

__all__ = ["Wave390LOBSyntheticMomentumIndexGuard"]

_REASON_UPPER = "SMI_UPPER_BREACH"
_REASON_LOWER = "SMI_LOWER_BREACH"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave390LOBSyntheticMomentumIndexGuard:
    """LOB synthetic momentum index (SMI) order book balance guard."""

    def __init__(
        self,
        window_size: int = 15,
        upper_smi_threshold: float = 500.0,
        lower_smi_threshold: float = 5.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 2 or upper_smi_threshold <= lower_smi_threshold or lower_smi_threshold <= 0.0:
            raise ValueError("Invalid parameters for Wave390LOBSyntheticMomentumIndexGuard")
        self._window_size = int(window_size)
        self._upper_thresh = float(upper_smi_threshold)
        self._lower_thresh = float(lower_smi_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._smi_history: deque[float] = deque(maxlen=self._window_size)
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
            spread_bps = max(((ask - bid) / mid) * 10_000.0, 1e-4)
            depth_ratio = float(bid_depth) / float(ask_depth)
            smi = (depth_ratio / spread_bps) * 100.0

            self._smi_history.append(smi)

            if len(self._smi_history) >= self._window_size:
                mean_smi = sum(self._smi_history) / len(self._smi_history)
                if mean_smi >= self._upper_thresh:
                    self._block(_REASON_UPPER)
                elif mean_smi <= self._lower_thresh:
                    self._block(_REASON_LOWER)

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
            self._smi_history.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
