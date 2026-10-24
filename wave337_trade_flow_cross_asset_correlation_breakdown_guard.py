"""
Wave 337 — Trade Flow Cross-Asset Correlation Breakdown Guard
=============================================================
Monitors the rolling Pearson correlation between two parallel trade-flow
signed-volume streams (e.g. ES vs NQ, or EUR/USD vs GBP/USD).

Methodology
-----------
* Collect pairs (x_i, y_i) of signed volumes (signed by trade side).
* Maintain a rolling window of the last `window_size` paired observations.
* Compute Pearson r over the window.
* Block when |r| < `decorrelation_threshold` (historically correlated
  instruments have decoupled — a regime-change warning).

Blocking reasons
----------------
CROSS_ASSET_DECORRELATION — |r| falls below threshold after window fills
INSUFFICIENT_VARIANCE      — one stream has zero variance (degenerate)
INPUT_VALIDATION_ERROR     — malformed arguments

Public API (standardised)
-------------------------
update(x_volume, y_volume, timestamp)  -> None
is_blocked(current_time=None)          -> bool
is_entry_blocked(bid, ask, ts)         -> bool
reset()                                -> None
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave337TradeFlowCrossAssetCorrelationBreakdownGuard"]

_REASON_DECORR = "CROSS_ASSET_DECORRELATION"
_REASON_VAR    = "INSUFFICIENT_VARIANCE"
_REASON_VAL    = "INPUT_VALIDATION_ERROR"


class Wave337TradeFlowCrossAssetCorrelationBreakdownGuard:
    """Cross-asset signed-volume Pearson correlation breakdown guard."""

    def __init__(
        self,
        window_size: int = 20,
        decorrelation_threshold: float = 0.30,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if window_size < 4 or not (0 <= decorrelation_threshold < 1):
            raise ValueError("Invalid cross-asset correlation guard parameters.")
        self._window        = int(window_size)
        self._thresh        = float(decorrelation_threshold)
        self._cooldown      = float(cooldown_seconds)

        self._lock          = threading.RLock()
        self._xs: deque     = deque(maxlen=window_size)
        self._ys: deque     = deque(maxlen=window_size)
        self._blocked_until = 0.0
        self._last_reason   = ""

    # ------------------------------------------------------------------
    def update(self, x_volume: float, y_volume: float, timestamp: float) -> None:
        with self._lock:
            for v in (x_volume, y_volume):
                if isinstance(v, bool):
                    self._block(timestamp, _REASON_VAL)
                    return
                if not isinstance(v, (int, float)):
                    self._block(timestamp, _REASON_VAL)
                    return

            self._xs.append(float(x_volume))
            self._ys.append(float(y_volume))

            if len(self._xs) < self._window:
                return

            xs = list(self._xs)
            ys = list(self._ys)
            n  = len(xs)
            mx = sum(xs) / n
            my = sum(ys) / n
            cov = sum((xi - mx) * (yi - my) for xi, yi in zip(xs, ys)) / n
            vx  = sum((xi - mx) ** 2 for xi in xs) / n
            vy  = sum((yi - my) ** 2 for yi in ys) / n

            if vx < 1e-15 or vy < 1e-15:
                self._block(timestamp, _REASON_VAR)
                return

            r = cov / (math.sqrt(vx) * math.sqrt(vy))
            if abs(r) < self._thresh:
                self._block(timestamp, _REASON_DECORR)

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
            self._xs.clear()
            self._ys.clear()
            self._blocked_until = 0.0
            self._last_reason   = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
