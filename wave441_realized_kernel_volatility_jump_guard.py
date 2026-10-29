"""
Wave 441 -- Realized Microstructural Kernel Volatility Jump Guard
=================================================================
Presides over high-frequency volatility estimation robust to market microstructure noise.
Applies the Barndorff-Nielsen Realized Kernel estimator with Parzen weight functions:
    RK = gamma_0 + 2 * sum_{h=1}^H k(h / H) * gamma_h
where gamma_h is the sample autocovariance of tick returns at lag h.
By comparing classical Realized Variance (RV) with Realized Kernel (RK), the guard
evaluates the Microstructure Noise Contamination Ratio:
    zeta = (RV - RK) / (RK + eps)
When zeta spikes, market noise (bid-ask bounce, quote stuffing) is violently
distorting the price formation process.

Methodology
-----------
* Tracks rolling tick midprice log returns r_t.
* Computes Realized Variance RV = sum(r_t^2).
* Computes Realized Kernel RK with lag truncation H = 3 and Parzen kernel weights.
* Evaluates noise contamination ratio zeta = max(0, RV - RK) / (RK + eps).
* If zeta >= `max_noise_ratio`, blocks with REALIZED_KERNEL_NOISE_CONTAMINATION.
* If RK >= `critical_kernel_ceiling`, blocks with KERNEL_VOLATILITY_SUPERNOVA.

Blocking reasons
----------------
REALIZED_KERNEL_NOISE_CONTAMINATION -- microstructure noise overwhelms fundamental variance
KERNEL_VOLATILITY_SUPERNOVA         -- noise-free realized kernel volatility breached ceiling
INPUT_VALIDATION_ERROR              -- bid >= ask, non-numeric, or non-monotonic timestamps

Public API (standardised)
-------------------------
update(bid, ask, timestamp)         -> None
is_blocked(current_time=None)       -> bool
is_entry_blocked(bid, ask, ts=None) -> bool
reset()                             -> None
last_reason                         -> str
noise_ratio                         -> float
realized_kernel                     -> float
"""

from __future__ import annotations

import collections
import math
import threading
import time
from typing import Deque, Optional

__all__ = ["Wave441RealizedKernelVolatilityJumpGuard"]

_REASON_NOISE = "REALIZED_KERNEL_NOISE_CONTAMINATION"
_REASON_CEIL = "KERNEL_VOLATILITY_SUPERNOVA"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave441RealizedKernelVolatilityJumpGuard:
    """Wave 441: Realized Microstructural Kernel Volatility Jump Guard."""

    def __init__(
        self,
        window_size: int = 15,
        max_lags: int = 3,
        max_noise_ratio: float = 2.0,
        critical_kernel_ceiling: float = 0.015,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            window_size <= max_lags * 2
            or max_lags < 1
            or max_noise_ratio <= 0.1
            or critical_kernel_ceiling <= 0.0
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave441RealizedKernelVolatilityJumpGuard")

        self._window_size = int(window_size)
        self._max_lags = int(max_lags)
        self._max_noise = float(max_noise_ratio)
        self._crit_ceil = float(critical_kernel_ceiling)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._last_mid: Optional[float] = None
        self._returns: Deque[float] = collections.deque(maxlen=self._window_size)
        self._rk: float = 0.0
        self._noise_ratio: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def noise_ratio(self) -> float:
        with self._lock:
            return self._noise_ratio

    @property
    def realized_kernel(self) -> float:
        with self._lock:
            return self._rk

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._last_mid = None
            self._returns.clear()
            self._rk = 0.0
            self._noise_ratio = 0.0
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
                or ask <= bid
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if (isinstance(timestamp, (int, float)) and timestamp > 0) else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)
            mid = (float(bid) + float(ask)) / 2.0

            if self._last_mid is not None and self._last_mid > 0.0:
                ret = math.log(mid / self._last_mid)
                self._returns.append(ret)

                if len(self._returns) >= self._window_size:
                    rets = list(self._returns)
                    n = len(rets)

                    # Classical Realized Variance: gamma_0
                    gamma_0 = sum(r * r for r in rets)

                    # Autocovariances gamma_h with Parzen kernel weights
                    rk = gamma_0
                    h_max = self._max_lags
                    for h in range(1, h_max + 1):
                        gamma_h = sum(rets[i] * rets[i - h] for i in range(h, n))
                        # Parzen weight: k(x) = 1 - 6x^2 + 6x^3 for 0 <= x <= 0.5
                        x = h / (h_max + 1)
                        if x <= 0.5:
                            weight = 1.0 - 6.0 * (x**2) + 6.0 * (x**3)
                        else:
                            weight = 2.0 * ((1.0 - x) ** 3)
                        rk += 2.0 * weight * gamma_h

                    rk = max(1e-8, rk)
                    self._rk = rk

                    # Noise ratio: (RV - RK) / RK
                    noise = max(0.0, gamma_0 - rk) / rk
                    self._noise_ratio = noise

                    if math.sqrt(rk) >= self._crit_ceil:
                        self._block(_REASON_CEIL, ts)
                    elif noise >= self._max_noise:
                        self._block(_REASON_NOISE, ts)

            self._last_ts = ts
            self._last_mid = mid

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
