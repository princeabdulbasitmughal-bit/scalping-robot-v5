"""
Wave 374 -- LOB Micro-Price Mean-Reversion Speed Guard
======================================================
Monitors the mean-reversion velocity of the depth-weighted micro-price towards
its local moving average. Sluggish reversion indicates structural adverse-selection
drift, while hyperactive reversion indicates high-frequency microstructure noise.

Methodology
-----------
* Computes depth-weighted micro-price:
    micro_price = (bid * ask_size + ask * bid_size) / (bid_size + ask_size)
* Tracks rolling micro-price series over `window_size` observations.
* Computes deviation from moving average: dev_i = micro_price_i - mean(micro_price)
* Estimates lag-1 autocorrelation phi = cov(dev_t, dev_{t-1}) / var(dev_{t-1}).
* Mean-reversion speed = 1.0 - phi.
* Blocks if reversion speed < `min_reversion_speed` (trend/drift regime) or
  reversion speed > `max_reversion_speed` (excessive whipsaw).

Blocking reasons
----------------
SLOW_MICROPRICE_REVERSION -- micro-price drifts persistently without reverting
NOISY_MICROPRICE          -- excessive rapid alternation/noise
INSUFFICIENT_VARIANCE     -- zero or near-zero variance in series
INPUT_VALIDATION_ERROR    -- malformed inputs

Public API (standardised)
-------------------------
update(bid, ask, bid_size, ask_size, timestamp) -> None
is_blocked(current_time=None)                   -> bool
is_entry_blocked(bid, ask, ts)                  -> bool
reset()                                         -> None
last_reason                                     -> str
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave374LOBMicropriceMeanReversionSpeedGuard"]

_REASON_SLOW = "SLOW_MICROPRICE_REVERSION"
_REASON_NOISY = "NOISY_MICROPRICE"
_REASON_VAR = "INSUFFICIENT_VARIANCE"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave374LOBMicropriceMeanReversionSpeedGuard:
    """Micro-price mean-reversion speed and persistence guard."""

    def __init__(
        self,
        window_size: int = 20,
        min_reversion_speed: float = 0.05,
        max_reversion_speed: float = 0.95,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if window_size < 5 or min_reversion_speed < 0 or max_reversion_speed <= min_reversion_speed:
            raise ValueError("Invalid parameters for Wave374LOBMicropriceMeanReversionSpeedGuard")
        self._window_size = int(window_size)
        self._min_speed = float(min_reversion_speed)
        self._max_speed = float(max_reversion_speed)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._micro_prices: deque[float] = deque(maxlen=self._window_size)
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(
        self,
        bid: float,
        ask: float,
        bid_size: float,
        ask_size: float,
        timestamp: float,
    ) -> None:
        with self._lock:
            for val in (bid, ask, bid_size, ask_size, timestamp):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._block(_REASON_VAL)
                    return

            if bid <= 0.0 or ask <= 0.0 or ask <= bid:
                self._block(_REASON_VAL)
                return
            if bid_size <= 0.0 or ask_size <= 0.0:
                self._block(_REASON_VAL)
                return

            tot_size = bid_size + ask_size
            micro = (bid * ask_size + ask * bid_size) / tot_size
            self._micro_prices.append(micro)

            if len(self._micro_prices) >= self._window_size:
                prices = list(self._micro_prices)
                n = len(prices)
                m = sum(prices) / n
                devs = [p - m for p in prices]

                var_x = sum(d * d for d in devs[:-1]) / (n - 1)
                if var_x < 1e-15:
                    self._block(_REASON_VAR)
                    return

                cov = sum(devs[i] * devs[i + 1] for i in range(n - 1)) / (n - 1)
                phi = cov / var_x
                speed = 1.0 - phi

                if speed < self._min_speed:
                    self._block(_REASON_SLOW)
                elif speed > self._max_speed:
                    self._block(_REASON_NOISY)

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
            self._micro_prices.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
