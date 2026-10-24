"""
Wave 347 -- Trade Arrival Self-Exciting Hawkes Intensity Guard
==============================================================
Monitors trade arrival clustering using a 1D self-exciting Hawkes process:
    lambda(t) = mu + sum_{t_i < t} alpha * exp(-beta * (t - t_i))

Recursive formulation at arrival t_k:
    lambda(t_k) = (lambda(t_{k-1}) - mu) * exp(-beta * (t_k - t_{k-1})) + mu + alpha

When predatory algo sweeps or panic liquidation cascades hit the order book,
the instantaneous trade arrival intensity lambda(t) spikes above intensity_threshold
into a supercritical cascade. The guard detects this runaway clustering and
preemptively locks out market orders to avoid extreme adverse selection.

Blocking reasons
----------------
HAWKES_SUPERCRITICAL_INTENSITY  -- lambda(t) >= intensity_threshold
INPUT_VALIDATION_ERROR          -- Non-positive, boolean or non-numeric inputs

Public API
----------
update(timestamp)              -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
"""

from __future__ import annotations

import math
import threading
import time
from typing import Optional

__all__ = ["Wave347TradeArrivalSelfExcitingHawkesIntensityGuard"]

_REASON_HAWKES = "HAWKES_SUPERCRITICAL_INTENSITY"
_REASON_VAL    = "INPUT_VALIDATION_ERROR"


class Wave347TradeArrivalSelfExcitingHawkesIntensityGuard:
    """Self-exciting Hawkes point process intensity guard for trade arrival bursts."""

    def __init__(
        self,
        mu: float = 1.0,
        alpha: float = 3.0,
        beta: float = 4.0,
        intensity_threshold: float = 15.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if mu <= 0 or alpha <= 0 or beta <= 0 or intensity_threshold <= mu:
            raise ValueError("Invalid parameters for Hawkes Intensity Guard.")
        self._mu = float(mu)
        self._alpha = float(alpha)
        self._beta = float(beta)
        self._threshold = float(intensity_threshold)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._last_ts: Optional[float] = None
        self._intensity: float = self._mu
        self._blocked_until = 0.0
        self._blocked_until_sim = 0.0
        self._last_reason = ""

    def update(self, timestamp: float) -> None:
        with self._lock:
            # Type and boolean validation
            if isinstance(timestamp, bool):
                self._block(time.monotonic(), _REASON_VAL)
                return
            if not isinstance(timestamp, (int, float)):
                self._block(time.monotonic(), _REASON_VAL)
                return

            ts = float(timestamp)

            if self._last_ts is not None:
                dt = ts - self._last_ts
                if dt < 0:
                    self._block(ts, _REASON_VAL)
                    self._last_ts = ts
                    return

                # Exponential decay since previous event
                decay = math.exp(-self._beta * dt)
                self._intensity = (self._intensity - self._mu) * decay + self._mu + self._alpha
            else:
                self._intensity = self._mu + self._alpha

            self._last_ts = ts

            if self._intensity >= self._threshold:
                self._block(ts, _REASON_HAWKES)

    def _block(self, timestamp: float, reason: str) -> None:
        now_mono = time.monotonic()
        self._blocked_until = now_mono + self._cooldown
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool) and timestamp > 0:
            self._blocked_until_sim = timestamp + self._cooldown
        else:
            self._blocked_until_sim = self._blocked_until
        self._last_reason = reason

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            if current_time is not None:
                return current_time < self._blocked_until_sim
            return time.monotonic() < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: float) -> bool:
        return self.is_blocked(ts)

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._intensity = self._mu
            self._blocked_until = 0.0
            self._blocked_until_sim = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def current_intensity(self) -> float:
        with self._lock:
            return self._intensity
