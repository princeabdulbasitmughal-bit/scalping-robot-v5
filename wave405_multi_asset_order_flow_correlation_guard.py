"""
Wave 405 -- Sovereign Multi-Asset Order Flow Correlation Guard
=============================================================
Monitors rolling Pearson correlation of signed trade returns between the primary
asset (e.g., Gold XAUUSD) and a benchmark correlated proxy (e.g., Silver XAGUSD or DXY).
A sharp decoupling or sign inversion in cross-asset co-movement reveals isolated
microstructural distress, liquidity fracture, or toxic predatory sweeps.

Methodology
-----------
* Observes primary return r_1 and correlated proxy return r_2 at timestamp t.
* Maintains a rolling window of return pairs of size `window_size`.
* Computes sample Pearson correlation coefficient:
    rho = Cov(r_1, r_2) / (Std(r_1) * Std(r_2))
* If rho <= `min_correlation_threshold`, blocks with `CROSS_ASSET_CORRELATION_DECOUPLING`.
* If |rho - rho_last| >= `max_correlation_drift`, blocks with `CROSS_ASSET_CORRELATION_DECOUPLING`.

Blocking reasons
----------------
CROSS_ASSET_CORRELATION_DECOUPLING -- cross-asset correlation collapsed or inverted
INPUT_VALIDATION_ERROR             -- non-numeric returns or invalid timestamp

Public API (standardised)
-------------------------
update(primary_return, proxy_return, timestamp) -> None
is_blocked(current_time=None)                   -> bool
is_entry_blocked(bid, ask, ts)                  -> bool
reset()                                         -> None
last_reason                                     -> str
current_correlation                             -> float
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave405MultiAssetOrderFlowCorrelationGuard"]

_REASON_DECOUPLE = "CROSS_ASSET_CORRELATION_DECOUPLING"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave405MultiAssetOrderFlowCorrelationGuard:
    """Multi-asset order flow correlation guard."""

    def __init__(
        self,
        window_size: int = 15,
        min_correlation_threshold: float = 0.30,
        max_correlation_drift: float = 0.60,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 5 or not (-1.0 <= min_correlation_threshold < 1.0) or cooldown_seconds <= 0.0:
            raise ValueError("Invalid parameters for Wave405MultiAssetOrderFlowCorrelationGuard")
        self._window_size = int(window_size)
        self._min_corr = float(min_correlation_threshold)
        self._max_drift = float(max_correlation_drift)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._pairs: deque[tuple[float, float]] = deque(maxlen=self._window_size)
        self._last_corr: Optional[float] = None
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(self, primary_return: float, proxy_return: float, timestamp: float) -> None:
        with self._lock:
            for val in (primary_return, proxy_return, timestamp):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._block(_REASON_VAL)
                    return

            r1 = float(primary_return)
            r2 = float(proxy_return)
            self._pairs.append((r1, r2))

            if len(self._pairs) >= self._window_size:
                n = len(self._pairs)
                m1 = sum(x for x, _ in self._pairs) / n
                m2 = sum(y for _, y in self._pairs) / n

                cov = sum((x - m1) * (y - m2) for x, y in self._pairs) / n
                var1 = sum((x - m1) ** 2 for x, _ in self._pairs) / n
                var2 = sum((y - m2) ** 2 for _, y in self._pairs) / n

                if var1 > 1e-12 and var2 > 1e-12:
                    rho = cov / (math.sqrt(var1) * math.sqrt(var2))
                    # Clamp numerical bounds
                    rho = max(-1.0, min(1.0, rho))

                    if rho <= self._min_corr:
                        self._block(_REASON_DECOUPLE)
                    elif self._last_corr is not None:
                        drift = abs(rho - self._last_corr)
                        if drift >= self._max_drift:
                            self._block(_REASON_DECOUPLE)

                    self._last_corr = rho

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
            self._pairs.clear()
            self._last_corr = None
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def current_correlation(self) -> float:
        with self._lock:
            return 1.0 if self._last_corr is None else self._last_corr
