"""
Wave 392 -- LOB Liquidity Provision Ratio Guard
================================================
Monitors the ratio of passive liquidity maker executions to aggressive taker orders.
An extreme passive ratio indicates HFT liquidity entrapment with absent real demand,
whereas a severely collapsed passive ratio indicates aggressive momentum sweeps
consuming resting book liquidity.

Methodology
-----------
* Observes incoming execution classification: `is_passive` (True for maker, False for taker).
* Maintains a rolling window of recent execution classifications of size `window_size`.
* Computes Liquidity Provision Ratio (LPR):
    LPR = sum(is_passive) / len(window)
* If LPR >= `high_lpr_threshold`, blocks with `HIGH_PASSIVE_RATIO`.
* If LPR <= `low_lpr_threshold`, blocks with `LOW_PASSIVE_RATIO`.

Blocking reasons
----------------
HIGH_PASSIVE_RATIO     -- market dominated by passive algorithmic market making
LOW_PASSIVE_RATIO      -- aggressive taker sweeps draining resting liquidity
INPUT_VALIDATION_ERROR -- non-boolean is_passive or non-numeric timestamp

Public API (standardised)
-------------------------
update(is_passive, timestamp)  -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave392LOBLiquidityProvisionRatioGuard"]

_REASON_HIGH_LPR = "HIGH_PASSIVE_RATIO"
_REASON_LOW_LPR = "LOW_PASSIVE_RATIO"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave392LOBLiquidityProvisionRatioGuard:
    """LOB passive vs aggressive liquidity provision ratio guard."""

    def __init__(
        self,
        window_size: int = 20,
        high_lpr_threshold: float = 0.85,
        low_lpr_threshold: float = 0.15,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 4 or not (0.0 <= low_lpr_threshold < high_lpr_threshold <= 1.0):
            raise ValueError("Invalid parameters for Wave392LOBLiquidityProvisionRatioGuard")
        self._window_size = int(window_size)
        self._high_lpr = float(high_lpr_threshold)
        self._low_lpr = float(low_lpr_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._executions: deque[int] = deque(maxlen=self._window_size)
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(self, is_passive: bool, timestamp: float) -> None:
        with self._lock:
            if not isinstance(is_passive, bool):
                self._block(_REASON_VAL)
                return
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                self._block(_REASON_VAL)
                return

            self._executions.append(1 if is_passive else 0)

            if len(self._executions) >= self._window_size:
                lpr = sum(self._executions) / len(self._executions)
                if lpr >= self._high_lpr:
                    self._block(_REASON_HIGH_LPR)
                elif lpr <= self._low_lpr:
                    self._block(_REASON_LOW_LPR)

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
            self._executions.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
