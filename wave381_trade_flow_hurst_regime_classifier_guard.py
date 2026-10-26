"""
Wave 381 -- Trade Flow Hurst Exponent Regime Classifier Guard
==============================================================
Estimates the Hurst exponent (H) of the signed trade volume series via rescaled
range (R/S) analysis. Classifies the market regime into anti-persistent mean-reverting
(H < h_low), random walk (H ~ 0.50), or persistent trending (H > h_high).

Methodology
-----------
* Accumulates signed volumes: sv = +volume (buy), -volume (sell).
* Over rolling window of `window_size` trades:
    1. Mean m = sum(sv) / N
    2. Cumulative deviations Y_t = sum_{i=1}^t (sv_i - m)
    3. Range R = max(Y) - min(Y)
    4. Sample standard deviation S = sqrt(sum((sv - m)^2) / N)
    5. Rescaled range = R / max(S, 1e-12)
    6. Hurst exponent H = ln(R/S) / ln(N)
* Blocks if H < `h_low` (erratic anti-persistent whipsaw flow).
* Blocks if H > `h_high` (extreme persistent one-directional trend sweep).

Blocking reasons
----------------
ANTIPERSISTENT_FLOW   -- H < h_low (severe mean-reverting choppiness)
PERSISTENT_FLOW       -- H > h_high (severe one-sided trend persistence)
INSUFFICIENT_VARIANCE -- zero variance in trade volumes
INPUT_VALIDATION_ERROR-- malformed inputs

Public API (standardised)
-------------------------
update(volume, side, timestamp) -> None
is_blocked(current_time=None)   -> bool
is_entry_blocked(bid, ask, ts)  -> bool
reset()                         -> None
last_reason                     -> str
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave381TradeFlowHurstRegimeClassifierGuard"]

_REASON_ANTI = "ANTIPERSISTENT_FLOW"
_REASON_PERSIST = "PERSISTENT_FLOW"
_REASON_VAR = "INSUFFICIENT_VARIANCE"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave381TradeFlowHurstRegimeClassifierGuard:
    """Trade flow Hurst exponent regime classifier and memory persistence guard."""

    def __init__(
        self,
        window_size: int = 30,
        h_low: float = 0.35,
        h_high: float = 0.75,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if window_size < 10 or h_low <= 0.0 or h_high <= h_low:
            raise ValueError("Invalid parameters for Wave381TradeFlowHurstRegimeClassifierGuard")
        self._window_size = int(window_size)
        self._h_low = float(h_low)
        self._h_high = float(h_high)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._signed_vols: deque[float] = deque(maxlen=self._window_size)
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

            sv = float(volume) if side == "buy" else -float(volume)
            self._signed_vols.append(sv)

            if len(self._signed_vols) >= self._window_size:
                vols = list(self._signed_vols)
                n = len(vols)
                m = sum(vols) / n

                # Variance & Std
                var_s = sum((x - m) ** 2 for x in vols) / n
                if var_s < 1e-15:
                    self._block(_REASON_VAR)
                    return
                s = math.sqrt(var_s)

                # Cumulative deviations
                cum_dev = 0.0
                min_dev = 0.0
                max_dev = 0.0
                for x in vols:
                    cum_dev += (x - m)
                    if cum_dev < min_dev:
                        min_dev = cum_dev
                    if cum_dev > max_dev:
                        max_dev = cum_dev

                r = max_dev - min_dev
                rs = r / max(s, 1e-12)

                if rs > 1e-9 and n > 1:
                    h = math.log(rs) / math.log(n)
                    if h < self._h_low:
                        self._block(_REASON_ANTI)
                    elif h > self._h_high:
                        self._block(_REASON_PERSIST)

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
            self._signed_vols.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
