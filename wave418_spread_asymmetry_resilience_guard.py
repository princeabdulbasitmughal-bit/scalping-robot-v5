"""
Wave 418 -- Bid-Ask Spread Asymmetry & Quote Resilience Guard
=============================================================
Monitors defensive quote skewing by market makers relative to prevailing fair value P^*:
    S_{bid} = P^* - P_{bid}
    S_{ask} = P_{ask} - P^*
    zeta = (S_{ask} - S_{bid}) / (S_{ask} + S_{bid}) in [-1, +1]
In balanced microstructures, zeta approx 0.0. When informed flow arrives on one side of
the market, passive liquidity providers skew quotes defensively by widening the adverse
side and collapsing the passive side. Acute asymmetry warns of imminent directional toxicity.

Methodology
-----------
* Maintains exponential moving average (EMA) of midprice as fair value P^*.
* Evaluates instantaneous half-spreads S_{bid} and S_{ask}.
* Computes spread asymmetry index zeta in [-1, +1].
* Maintains a rolling window of size N (`window_size`).
* If |zeta| >= `max_asymmetry_threshold`, blocks with DEFENSIVE_SPREAD_ASYMMETRY.
* If zeta >= `max_asymmetry_threshold`, indicates ONE_SIDED_QUOTE_WIDENING (ask shaded up).
* If zeta <= -`max_asymmetry_threshold`, indicates ONE_SIDED_QUOTE_WIDENING (bid shaded down).

Blocking reasons
----------------
DEFENSIVE_SPREAD_ASYMMETRY -- quote skewing indicates market maker adverse selection protection
ONE_SIDED_QUOTE_WIDENING   -- acute one-sided spread widening reveals imminent directional sweep
INPUT_VALIDATION_ERROR     -- non-positive prices, bid >= ask, non-monotonic ts

Public API (standardised)
-------------------------
update(bid, ask, timestamp)    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
asymmetry_index                -> float
fair_value                     -> float
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave418SpreadAsymmetryResilienceGuard"]

_REASON_ASYMMETRY = "DEFENSIVE_SPREAD_ASYMMETRY"
_REASON_ONE_SIDED = "ONE_SIDED_QUOTE_WIDENING"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave418SpreadAsymmetryResilienceGuard:
    """Spread Asymmetry and Quote Resilience Guard."""

    def __init__(
        self,
        window_size: int = 10,
        max_asymmetry_threshold: float = 0.70,
        ema_alpha: float = 0.15,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            window_size < 3
            or not (0.20 <= max_asymmetry_threshold <= 0.95)
            or not (0.01 <= ema_alpha <= 0.90)
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave418SpreadAsymmetryResilienceGuard")

        self._window_size = int(window_size)
        self._max_asym = float(max_asymmetry_threshold)
        self._alpha = float(ema_alpha)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._fair_value: Optional[float] = None
        self._last_ts: Optional[float] = None
        self._asymmetries: deque[float] = deque(maxlen=self._window_size)
        self._current_zeta: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def asymmetry_index(self) -> float:
        with self._lock:
            return self._current_zeta

    @property
    def fair_value(self) -> float:
        with self._lock:
            return self._fair_value or 0.0

    def reset(self) -> None:
        with self._lock:
            self._fair_value = None
            self._last_ts = None
            self._asymmetries.clear()
            self._current_zeta = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(self, bid: float, ask: float, timestamp: float) -> None:
        with self._lock:
            if (
                not isinstance(bid, (int, float))
                or not isinstance(ask, (int, float))
                or not isinstance(timestamp, (int, float))
                or bid <= 0.0
                or ask <= 0.0
                or bid >= ask
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if timestamp > 0 else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            p_bid = float(bid)
            p_ask = float(ask)
            ts = float(timestamp)
            mid = (p_bid + p_ask) / 2.0

            if self._fair_value is None:
                self._fair_value = mid
            else:
                self._fair_value = self._alpha * mid + (1.0 - self._alpha) * self._fair_value

            fair = self._fair_value
            # Half-spreads relative to fair value
            s_bid = max(fair - p_bid, 1e-6)
            s_ask = max(p_ask - fair, 1e-6)

            zeta = (s_ask - s_bid) / (s_ask + s_bid)
            self._current_zeta = zeta
            self._asymmetries.append(zeta)

            if abs(zeta) >= self._max_asym:
                self._block(_REASON_ONE_SIDED, ts)
            elif len(self._asymmetries) >= self._window_size:
                avg_zeta = sum(self._asymmetries) / float(len(self._asymmetries))
                if abs(avg_zeta) >= self._max_asym * 0.85:
                    self._block(_REASON_ASYMMETRY, ts)

            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
