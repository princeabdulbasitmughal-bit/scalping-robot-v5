"""
Wave 444 -- Microstructure Price Impact Decay Asymmetry Guard
============================================================
Presides over asymmetric price impact relaxation dynamics between buyer-initiated
and seller-initiated executions. In balanced market environments, temporary price
impact relaxes symmetrically:
    gamma_buy(t) = I_0^+ * exp(-beta_buy * t)
    gamma_sell(t) = I_0^- * exp(-beta_sell * t)
When impact decay rates beta_buy and beta_sell diverge severely, one side of the
market exhibits persistent permanent impact while the opposite side quickly reverts.
This indicates institutional predatory accumulation or distribution.

Methodology
-----------
* Tracks realized decay speeds beta_buy and beta_sell across directional trades.
* Computes normalized impact decay asymmetry:
    A_decay = |beta_buy - beta_sell| / (beta_buy + beta_sell + eps)
* If A_decay >= `max_decay_asymmetry`, blocks with ASYMMETRIC_IMPACT_DECAY_DISTORTION.
* If either decay velocity is near-zero (decay_ratio < min_decay_ratio),
  blocks with PERMANENT_IMPACT_RESIDUAL_LOCK.

Blocking reasons
----------------
ASYMMETRIC_IMPACT_DECAY_DISTORTION -- severe divergence between buy-side and sell-side impact relaxation
PERMANENT_IMPACT_RESIDUAL_LOCK     -- one directional impact failed to decay (permanent adverse selection)
INPUT_VALIDATION_ERROR             -- negative impacts, non-numeric, or non-monotonic timestamps

Public API (standardised)
-------------------------
update(buy_initial, buy_current, sell_initial, sell_current, dt_sec, timestamp) -> None
is_blocked(current_time=None)       -> bool
is_entry_blocked(bid, ask, ts=None) -> bool
reset()                             -> None
last_reason                         -> str
decay_asymmetry                     -> float
"""

from __future__ import annotations

import threading
import time
from typing import Optional

__all__ = ["Wave444PriceImpactDecayAsymmetryGuard"]

_REASON_ASYM = "ASYMMETRIC_IMPACT_DECAY_DISTORTION"
_REASON_PERM = "PERMANENT_IMPACT_RESIDUAL_LOCK"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave444PriceImpactDecayAsymmetryGuard:
    """Wave 444: Microstructure Price Impact Decay Asymmetry Guard."""

    def __init__(
        self,
        max_decay_asymmetry: float = 0.65,
        min_decay_ratio: float = 0.20,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            not (0.20 <= max_decay_asymmetry <= 0.95)
            or not (0.01 <= min_decay_ratio <= 0.80)
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave444PriceImpactDecayAsymmetryGuard")

        self._max_asym = float(max_decay_asymmetry)
        self._min_ratio = float(min_decay_ratio)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._asymmetry: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def decay_asymmetry(self) -> float:
        with self._lock:
            return self._asymmetry

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._asymmetry = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(
        self,
        buy_initial: float,
        buy_current: float,
        sell_initial: float,
        sell_current: float,
        dt_sec: float,
        timestamp: float,
    ) -> None:
        with self._lock:
            if (
                not isinstance(buy_initial, (int, float))
                or not isinstance(buy_current, (int, float))
                or not isinstance(sell_initial, (int, float))
                or not isinstance(sell_current, (int, float))
                or not isinstance(dt_sec, (int, float))
                or not isinstance(timestamp, (int, float))
                or buy_initial <= 0.0
                or buy_current < 0.0
                or sell_initial <= 0.0
                or sell_current < 0.0
                or dt_sec <= 0.0
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if (isinstance(timestamp, (int, float)) and timestamp > 0) else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)
            dt = float(dt_sec)

            # Decay amounts: initial - current
            decay_buy = max(0.0, buy_initial - buy_current) / buy_initial
            decay_sell = max(0.0, sell_initial - sell_current) / sell_initial

            # Decay rates per second
            beta_buy = decay_buy / dt
            beta_sell = decay_sell / dt

            if decay_buy < self._min_ratio or decay_sell < self._min_ratio:
                self._block(_REASON_PERM, ts)
                self._last_ts = ts
                return

            eps = 1e-6
            asym = abs(beta_buy - beta_sell) / (beta_buy + beta_sell + eps)
            self._asymmetry = asym

            if asym >= self._max_asym:
                self._block(_REASON_ASYM, ts)

            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
