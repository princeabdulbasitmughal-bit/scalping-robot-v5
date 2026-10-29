"""
Wave 436 -- Orderbook Level-2 Skew Decay Elasticity Guard
=========================================================
Monitors the responsiveness and decay elasticity of orderbook depth skew:
    S_t = (Q_bid - Q_ask) / (Q_bid + Q_ask + eps) in [-1, 1]
In a resilient market, price movements absorb and rebalance orderbook skew.
If skew remains persistently one-sided despite price changes (inelastic skew),
or if skew experiences violent whipsaw oscillations, passive market depth is
brittle and susceptible to cascading liquidation sweeps.

Methodology
-----------
* Tracks Level-2 bid and ask volumes and midprice.
* Evaluates instantaneous orderbook skew S_t.
* Evaluates rolling skew variance and decay elasticity over observation window.
* If |S_t| >= `critical_skew_threshold` and rolling skew variance <= `inelastic_variance_floor`,
  blocks with INELASTIC_ORDERBOOK_SKEW_LOCK.
* If rolling skew standard deviation >= `max_skew_whipsaw_std`, blocks with ERRATIC_SKEW_WHIPSAW.

Blocking reasons
----------------
INELASTIC_ORDERBOOK_SKEW_LOCK -- severe persistent one-sided book skew refusing to decay
ERRATIC_SKEW_WHIPSAW          -- violent high-frequency flip-flopping in book balance
INPUT_VALIDATION_ERROR        -- negative depths, non-numeric, or non-monotonic timestamps

Public API (standardised)
-------------------------
update(bid_depth, ask_depth, midprice, timestamp) -> None
is_blocked(current_time=None)                     -> bool
is_entry_blocked(bid, ask, ts=None)               -> bool
reset()                                           -> None
last_reason                                       -> str
current_skew                                      -> float
skew_volatility                                   -> float
"""

from __future__ import annotations

import collections
import math
import threading
import time
from typing import Deque, Optional

__all__ = ["Wave436OrderbookSkewDecayElasticityGuard"]

_REASON_LOCK = "INELASTIC_ORDERBOOK_SKEW_LOCK"
_REASON_WHIPSAW = "ERRATIC_SKEW_WHIPSAW"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave436OrderbookSkewDecayElasticityGuard:
    """Wave 436: Orderbook Level-2 Skew Decay Elasticity Guard."""

    def __init__(
        self,
        window_size: int = 15,
        critical_skew_threshold: float = 0.70,
        inelastic_variance_floor: float = 0.005,
        max_skew_whipsaw_std: float = 0.65,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            window_size < 5
            or not (0.30 <= critical_skew_threshold <= 0.95)
            or inelastic_variance_floor <= 0.0
            or max_skew_whipsaw_std <= 0.10
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave436OrderbookSkewDecayElasticityGuard")

        self._window_size = int(window_size)
        self._crit_skew = float(critical_skew_threshold)
        self._var_floor = float(inelastic_variance_floor)
        self._max_std = float(max_skew_whipsaw_std)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._skew_history: Deque[float] = collections.deque(maxlen=self._window_size)
        self._current_skew: float = 0.0
        self._skew_std: float = 0.0
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
    def skew_volatility(self) -> float:
        with self._lock:
            return self._skew_std

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._skew_history.clear()
            self._current_skew = 0.0
            self._skew_std = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(
        self,
        bid_depth: float,
        ask_depth: float,
        midprice: float,
        timestamp: float,
    ) -> None:
        with self._lock:
            if (
                not isinstance(bid_depth, (int, float))
                or not isinstance(ask_depth, (int, float))
                or not isinstance(midprice, (int, float))
                or not isinstance(timestamp, (int, float))
                or bid_depth < 0.0
                or ask_depth < 0.0
                or midprice <= 0.0
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if (isinstance(timestamp, (int, float)) and timestamp > 0) else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)
            eps = 1e-6
            tot = float(bid_depth + ask_depth)
            skew = (float(bid_depth) - float(ask_depth)) / (tot + eps)
            self._current_skew = skew
            self._skew_history.append(skew)

            if len(self._skew_history) >= self._window_size:
                skews = list(self._skew_history)
                mean_s = sum(skews) / self._window_size
                var_s = sum((s - mean_s) ** 2 for s in skews) / (self._window_size - 1)
                std_s = math.sqrt(max(0.0, var_s))
                self._skew_std = std_s

                if std_s >= self._max_std:
                    self._block(_REASON_WHIPSAW, ts)
                elif abs(skew) >= self._crit_skew and var_s <= self._var_floor:
                    self._block(_REASON_LOCK, ts)

            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
