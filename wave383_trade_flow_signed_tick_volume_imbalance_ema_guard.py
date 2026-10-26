"""
Wave 383 -- Trade Flow Signed Tick Volume Imbalance EMA Guard
==============================================================
Monitors exponential moving average (EMA) of signed trade volume flow.
Prolonged directional pressure that drives the signed volume EMA beyond critical
threshold bounds indicates institutional execution programs (VWAP/TWAP sweeps)
or adverse flow accumulation.

Methodology
-----------
* Signed volume: sv = +volume (buy) or -volume (sell).
* Exponential smoothing:
    EMA_t = alpha * sv + (1.0 - alpha) * EMA_{t-1}
    where alpha = 2.0 / (ema_period + 1.0).
* Requires at least `min_warmup_ticks` ticks before evaluation.
* Blocks if |EMA_t| >= `imbalance_threshold`.

Blocking reasons
----------------
EMA_IMBALANCE_BREACH   -- signed volume EMA exceeds risk threshold
INPUT_VALIDATION_ERROR -- invalid volume, side, or timestamp

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

__all__ = ["Wave383TradeFlowSignedTickVolumeImbalanceEMAGuard"]

_REASON_EMA = "EMA_IMBALANCE_BREACH"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave383TradeFlowSignedTickVolumeImbalanceEMAGuard:
    """Trade flow signed volume exponential moving average imbalance guard."""

    def __init__(
        self,
        ema_period: int = 20,
        imbalance_threshold: float = 500.0,
        min_warmup_ticks: int = 10,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if ema_period < 2 or imbalance_threshold <= 0.0 or min_warmup_ticks < 1:
            raise ValueError("Invalid parameters for Wave383TradeFlowSignedTickVolumeImbalanceEMAGuard")
        self._ema_period = int(ema_period)
        self._alpha = 2.0 / (self._ema_period + 1.0)
        self._threshold = float(imbalance_threshold)
        self._min_warmup = int(min_warmup_ticks)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._ema: Optional[float] = None
        self._ticks_count = 0
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
            sv = v if side == "buy" else -v

            if self._ema is None:
                self._ema = sv
            else:
                self._ema = self._alpha * sv + (1.0 - self._alpha) * self._ema

            self._ticks_count += 1

            if self._ticks_count >= self._min_warmup:
                if abs(self._ema) >= self._threshold:
                    self._block(_REASON_EMA)

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
            self._ema = None
            self._ticks_count = 0
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
