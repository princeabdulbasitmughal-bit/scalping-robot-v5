"""
Wave 409 -- Orderbook Micro-Price Skew & Drift Guard
====================================================
Computes the Sasha Stoikov (2018) institutional micro-price and queue asymmetry skew:
    P^{micro} = (Q_b * P_a + Q_a * P_b) / (Q_b + Q_a) = P_{mid} + (Spread / 2) * xi
where xi = (Q_b - Q_a) / (Q_b + Q_a) is the queue asymmetry ratio in [-1, +1].
Acute queue asymmetry or swift directional skew drift reveals severe one-sided quote
depletion and predatory inventory liquidation, causing extreme adverse fills.

Methodology
-----------
* Observes top-of-book quotes: bid, ask, bid_queue, ask_queue at timestamp t.
* Midprice: P_{mid} = (bid + ask) / 2.0; Spread: S = ask - bid.
* Micro-price skew ratio:
    xi = (bid_queue - ask_queue) / (bid_queue + ask_queue)
* Micro-price:
    P^{micro} = P_{mid} + (S / 2.0) * xi
* Tracks rolling window of skew ratios xi.
* Skew drift: Delta xi = |xi_t - xi_{t - window_size}|.
* If |xi| >= `max_skew_ratio`, blocks with MICROPRICE_ASYMMETRY_SKEW.
* If Delta xi >= `max_skew_drift`, blocks with SKEW_DRIFT_VELOCITY_SPIKE.

Blocking reasons
----------------
MICROPRICE_ASYMMETRY_SKEW   -- queue asymmetry ratio exceeded critical tolerance
SKEW_DRIFT_VELOCITY_SPIKE   -- rapid directional migration in book queue bias
INPUT_VALIDATION_ERROR      -- non-positive prices/depth, bid >= ask, non-monotonic ts

Public API (standardised)
-------------------------
update(bid, ask, bid_queue, ask_queue, timestamp) -> None
is_blocked(current_time=None)                     -> bool
is_entry_blocked(bid, ask, ts)                    -> bool
reset()                                           -> None
last_reason                                       -> str
current_skew                                      -> float
current_microprice                                -> float
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave409OrderbookMicropriceSkewDriftGuard"]

_REASON_SKEW = "MICROPRICE_ASYMMETRY_SKEW"
_REASON_DRIFT = "SKEW_DRIFT_VELOCITY_SPIKE"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave409OrderbookMicropriceSkewDriftGuard:
    """Orderbook Micro-Price Skew and Drift Guard."""

    def __init__(
        self,
        window_size: int = 10,
        max_skew_ratio: float = 0.80,
        max_skew_drift: float = 0.60,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            window_size < 3
            or not (0.20 <= max_skew_ratio <= 0.98)
            or not (0.20 <= max_skew_drift <= 1.50)
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave409OrderbookMicropriceSkewDriftGuard")

        self._window_size = int(window_size)
        self._max_skew = float(max_skew_ratio)
        self._max_drift = float(max_skew_drift)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._skews: deque[float] = deque(maxlen=self._window_size)
        self._current_skew: float = 0.0
        self._current_microprice: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def current_skew(self) -> float:
        with self._lock:
            return self._current_skew

    @property
    def current_microprice(self) -> float:
        with self._lock:
            return self._current_microprice

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._skews.clear()
            self._current_skew = 0.0
            self._current_microprice = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(
        self,
        bid: float,
        ask: float,
        bid_queue: float,
        ask_queue: float,
        timestamp: float,
    ) -> None:
        with self._lock:
            if (
                not isinstance(bid, (int, float))
                or not isinstance(ask, (int, float))
                or not isinstance(bid_queue, (int, float))
                or not isinstance(ask_queue, (int, float))
                or not isinstance(timestamp, (int, float))
                or bid <= 0.0
                or ask <= 0.0
                or bid >= ask
                or bid_queue <= 0.0
                or ask_queue <= 0.0
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if timestamp > 0 else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)
            p_bid = float(bid)
            p_ask = float(ask)
            q_bid = float(bid_queue)
            q_ask = float(ask_queue)

            mid = (p_bid + p_ask) / 2.0
            spread = p_ask - p_bid
            total_q = q_bid + q_ask

            skew = (q_bid - q_ask) / total_q
            microprice = mid + (spread / 2.0) * skew

            self._current_skew = skew
            self._current_microprice = microprice

            # Check skew drift against oldest in window
            if len(self._skews) >= self._window_size:
                oldest_skew = self._skews[0]
                drift = abs(skew - oldest_skew)
                if drift >= self._max_drift:
                    self._block(_REASON_DRIFT, ts)

            self._skews.append(skew)

            # Check absolute skew tolerance
            if abs(skew) >= self._max_skew:
                self._block(_REASON_SKEW, ts)

            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
