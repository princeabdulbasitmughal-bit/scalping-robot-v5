"""
Wave 433 -- Asymmetric Trade Flow Poisson Arrival Intensity Guard
=================================================================
Monitors directional trade flow arrival intensity across buyer-initiated
and seller-initiated executions. An extreme asymmetry in arrival intensity
(lambda_buy vs lambda_sell) during high-frequency bursts signals aggressive
institutional sweeping and one-sided inventory depletion.

Methodology
-----------
* Tracks discrete trade arrivals over rolling window.
* Evaluates directional intensities:
    lambda_buy = count(buy_trades) / dt
    lambda_sell = count(sell_trades) / dt
    lambda_total = lambda_buy + lambda_sell
* Computes Normalized Intensity Asymmetry:
    I_asym = |lambda_buy - lambda_sell| / (lambda_total + eps)
* If lambda_total >= `min_burst_intensity` and I_asym >= `max_asymmetry_ratio`,
  blocks with ASYMMETRIC_TRADE_FLOW_IMBALANCE.
* If lambda_total >= `extreme_arrival_ceiling`, blocks with EXTREME_FLOW_ARRIVAL_SUPERNOVA.

Blocking reasons
----------------
ASYMMETRIC_TRADE_FLOW_IMBALANCE   -- aggressive one-sided arrival intensity spike
EXTREME_FLOW_ARRIVAL_SUPERNOVA    -- total trade arrival rate breached safety ceiling
INPUT_VALIDATION_ERROR            -- invalid trade signs, non-numeric, or non-monotonic timestamps

Public API (standardised)
-------------------------
update(volume, is_buy, timestamp)   -> None
is_blocked(current_time=None)       -> bool
is_entry_blocked(bid, ask, ts=None) -> bool
reset()                             -> None
last_reason                         -> str
arrival_asymmetry                   -> float
total_arrival_intensity             -> float
"""

from __future__ import annotations

import collections
import threading
import time
from typing import Deque, Optional, Tuple

__all__ = ["Wave433AsymmetricTradeFlowArrivalIntensityGuard"]

_REASON_ASYM = "ASYMMETRIC_TRADE_FLOW_IMBALANCE"
_REASON_CEIL = "EXTREME_FLOW_ARRIVAL_SUPERNOVA"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave433AsymmetricTradeFlowArrivalIntensityGuard:
    """Wave 433: Asymmetric Trade Flow Arrival Intensity Guard."""

    def __init__(
        self,
        window_seconds: float = 2.0,
        max_asymmetry_ratio: float = 0.75,
        min_burst_intensity: float = 8.0,
        extreme_arrival_ceiling: float = 80.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            window_seconds <= 0.1
            or not (0.20 <= max_asymmetry_ratio <= 0.99)
            or min_burst_intensity <= 0.0
            or extreme_arrival_ceiling <= min_burst_intensity
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave433AsymmetricTradeFlowArrivalIntensityGuard")

        self._window_sec = float(window_seconds)
        self._max_asym = float(max_asymmetry_ratio)
        self._min_burst = float(min_burst_intensity)
        self._extreme_ceil = float(extreme_arrival_ceiling)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._trades: Deque[Tuple[float, bool, float]] = collections.deque()  # (ts, is_buy, volume)
        self._asymmetry: float = 0.0
        self._total_intensity: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def arrival_asymmetry(self) -> float:
        with self._lock:
            return self._asymmetry

    @property
    def total_arrival_intensity(self) -> float:
        with self._lock:
            return self._total_intensity

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._trades.clear()
            self._asymmetry = 0.0
            self._total_intensity = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(self, volume: float, is_buy: bool, timestamp: float) -> None:
        with self._lock:
            if (
                not isinstance(volume, (int, float))
                or not isinstance(is_buy, bool)
                or not isinstance(timestamp, (int, float))
                or volume <= 0.0
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if (isinstance(timestamp, (int, float)) and timestamp > 0) else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)
            self._trades.append((ts, is_buy, float(volume)))

            # Prune old trades outside rolling window
            cutoff = ts - self._window_sec
            while self._trades and self._trades[0][0] < cutoff:
                self._trades.popleft()

            if len(self._trades) >= 2:
                dt = ts - self._trades[0][0]
                if dt > 1e-4:
                    buy_count = sum(1 for _, b, _ in self._trades if b)
                    sell_count = sum(1 for _, b, _ in self._trades if not b)
                    lam_buy = buy_count / dt
                    lam_sell = sell_count / dt
                    lam_tot = lam_buy + lam_sell
                    self._total_intensity = lam_tot

                    eps = 1e-5
                    asym = abs(lam_buy - lam_sell) / (lam_tot + eps)
                    self._asymmetry = asym

                    if lam_tot >= self._extreme_ceil:
                        self._block(_REASON_CEIL, ts)
                    elif lam_tot >= self._min_burst and asym >= self._max_asym:
                        self._block(_REASON_ASYM, ts)

            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
