"""
Wave 411 -- High-Frequency Return Autocorrelation Decay Guard
============================================================
Monitors high-frequency return autocorrelation structure. Under normal efficient market
conditions with bid-ask bounce (Roll 1984), lag-1 autocorrelation rho_1 is modestly negative
due to alternating bid/ask bounce. Excessive positive autocorrelation indicates predatory
institutional order splitting (e.g., VWAP/TWAP sweeps), while extreme negative autocorrelation
reveals hyper-oscillatory quote bouncing and microstructural breakdown.

Methodology
-----------
* Observes midprice returns r_t = ln(P_t / P_{t-1}) over rolling window N (`window_size`).
* Sample lag-k autocorrelation:
    rho_k = sum((r_t - mu)*(r_{t-k} - mu)) / sum((r_t - mu)^2)
* Evaluates lag-1 autocorrelation rho_1 and cumulative multi-lag persistence sum_{k=1}^3 |rho_k|.
* If rho_1 >= `max_positive_autocorr`, blocks with PERSISTENT_AUTOCORRELATION_SWEEP.
* If rho_1 <= -`max_negative_autocorr`, blocks with EXCESS_MICROSTRUCTURE_BOUNCE.
* If sum_{k=1}^3 |rho_k| >= `max_cumulative_autocorr`, blocks with PERSISTENT_AUTOCORRELATION_SWEEP.

Blocking reasons
----------------
PERSISTENT_AUTOCORRELATION_SWEEP -- strong directional persistence indicates algorithmic sweep
EXCESS_MICROSTRUCTURE_BOUNCE    -- extreme negative autocorrelation reveals violent quote churn
INPUT_VALIDATION_ERROR          -- non-positive prices, bid >= ask, non-monotonic ts

Public API (standardised)
-------------------------
update(bid, ask, timestamp)    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
rho_1                          -> float
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave411HighFrequencyReturnAutocorrelationGuard"]

_REASON_SWEEP = "PERSISTENT_AUTOCORRELATION_SWEEP"
_REASON_BOUNCE = "EXCESS_MICROSTRUCTURE_BOUNCE"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave411HighFrequencyReturnAutocorrelationGuard:
    """High-Frequency Return Autocorrelation Decay Guard."""

    def __init__(
        self,
        window_size: int = 15,
        max_positive_autocorr: float = 0.40,
        max_negative_autocorr: float = 0.70,
        max_cumulative_autocorr: float = 1.60,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            window_size < 6
            or not (0.10 <= max_positive_autocorr <= 0.90)
            or not (0.20 <= max_negative_autocorr <= 0.95)
            or max_cumulative_autocorr <= 0.50
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave411HighFrequencyReturnAutocorrelationGuard")

        self._window_size = int(window_size)
        self._max_pos_rho = float(max_positive_autocorr)
        self._max_neg_rho = float(max_negative_autocorr)
        self._max_cum_rho = float(max_cumulative_autocorr)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_mid: Optional[float] = None
        self._last_ts: Optional[float] = None
        self._returns: deque[float] = deque(maxlen=self._window_size)
        self._rho_1: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def rho_1(self) -> float:
        with self._lock:
            return self._rho_1

    def reset(self) -> None:
        with self._lock:
            self._last_mid = None
            self._last_ts = None
            self._returns.clear()
            self._rho_1 = 0.0
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

            mid = (float(bid) + float(ask)) / 2.0
            ts = float(timestamp)

            if self._last_mid is not None and self._last_mid > 0.0:
                ret = math.log(mid / self._last_mid)
                self._returns.append(ret)

                n = len(self._returns)
                if n >= self._window_size:
                    mean_r = sum(self._returns) / n
                    var_r = sum((r - mean_r) ** 2 for r in self._returns)

                    if var_r > 1e-14:
                        # Compute rho_1
                        cov_1 = sum(
                            (self._returns[i] - mean_r) * (self._returns[i - 1] - mean_r)
                            for i in range(1, n)
                        )
                        rho1 = cov_1 / var_r
                        self._rho_1 = rho1

                        # Compute rho_2 and rho_3 for cumulative persistence
                        cov_2 = sum(
                            (self._returns[i] - mean_r) * (self._returns[i - 2] - mean_r)
                            for i in range(2, n)
                        )
                        rho2 = cov_2 / var_r

                        cov_3 = sum(
                            (self._returns[i] - mean_r) * (self._returns[i - 3] - mean_r)
                            for i in range(3, n)
                        )
                        rho3 = cov_3 / var_r

                        cum_rho = abs(rho1) + abs(rho2) + abs(rho3)

                        if rho1 >= self._max_pos_rho:
                            self._block(_REASON_SWEEP, ts)
                        elif rho1 <= -self._max_neg_rho:
                            self._block(_REASON_BOUNCE, ts)
                        elif cum_rho >= self._max_cum_rho:
                            self._block(_REASON_SWEEP, ts)

            self._last_mid = mid
            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
