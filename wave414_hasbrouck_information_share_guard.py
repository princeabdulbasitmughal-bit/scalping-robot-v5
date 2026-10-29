"""
Wave 414 -- Hasbrouck Permanent-Transitory Information Share Guard
==================================================================
Decomposes observed price return variance into permanent variance (fundamental price
discovery) versus transitory variance (microstructural bounce & order-flow friction)
using Joel Hasbrouck's (1991, 1995) econometric market microstructure model.
When transitory noise dominates total variance (Information Share collapses), market
orders are filled entirely against predatory bid-ask spread churn without true directional drift.

Methodology
-----------
* Observes midprice returns r_t = ln(P_t / P_{t-1}) over rolling window N (`window_size`).
* Sample variance: Var(r_t) = (1/N) * sum((r_t - mu)^2).
* Lag-1 autocovariance: gamma_1 = (1/(N-1)) * sum((r_t - mu)*(r_{t-1} - mu)).
* Under the Roll model, gamma_1 = -sigma_{noise}^2.
* Estimated noise variance: sigma_{noise}^2 = max(0.0, -gamma_1).
* Estimated permanent variance: sigma_{perm}^2 = max(0.0, Var(r_t) - 2.0 * sigma_{noise}^2).
* Information Share: IS = sigma_{perm}^2 / (Var(r_t) + 1e-14).
* Noise Ratio: NR = min(1.0, 2.0 * sigma_{noise}^2 / (Var(r_t) + 1e-14)).
* If NR >= `max_noise_ratio`, blocks with MICROSTRUCTURE_NOISE_DOMINANCE.
* If IS <= `min_info_share`, blocks with INFORMATION_SHARE_COLLAPSE.

Blocking reasons
----------------
MICROSTRUCTURE_NOISE_DOMINANCE -- transitory bounce noise represents majority of variance
INFORMATION_SHARE_COLLAPSE     -- fundamental price discovery vanished into spread friction
INPUT_VALIDATION_ERROR         -- non-positive prices, bid >= ask, non-monotonic ts

Public API (standardised)
-------------------------
update(bid, ask, timestamp)    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
information_share              -> float
noise_ratio                    -> float
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave414HasbrouckInformationShareGuard"]

_REASON_NOISE = "MICROSTRUCTURE_NOISE_DOMINANCE"
_REASON_COLLAPSE = "INFORMATION_SHARE_COLLAPSE"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave414HasbrouckInformationShareGuard:
    """Hasbrouck Permanent-Transitory Information Share Guard."""

    def __init__(
        self,
        window_size: int = 15,
        max_noise_ratio: float = 0.75,
        min_info_share: float = 0.20,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            window_size < 6
            or not (0.20 <= max_noise_ratio <= 0.98)
            or not (0.02 <= min_info_share <= 0.80)
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave414HasbrouckInformationShareGuard")

        self._window_size = int(window_size)
        self._max_noise_ratio = float(max_noise_ratio)
        self._min_info_share = float(min_info_share)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_mid: Optional[float] = None
        self._last_ts: Optional[float] = None
        self._returns: deque[float] = deque(maxlen=self._window_size)
        self._info_share: float = 1.0
        self._noise_ratio: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def information_share(self) -> float:
        with self._lock:
            return self._info_share

    @property
    def noise_ratio(self) -> float:
        with self._lock:
            return self._noise_ratio

    def reset(self) -> None:
        with self._lock:
            self._last_mid = None
            self._last_ts = None
            self._returns.clear()
            self._info_share = 1.0
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
                    var_r = sum((r - mean_r) ** 2 for r in self._returns) / n

                    if var_r > 1e-14:
                        cov_1 = sum(
                            (self._returns[i] - mean_r) * (self._returns[i - 1] - mean_r)
                            for i in range(1, n)
                        ) / (n - 1)

                        sigma_noise_sq = max(0.0, -cov_1)
                        sigma_perm_sq = max(0.0, var_r - 2.0 * sigma_noise_sq)

                        is_ratio = sigma_perm_sq / var_r
                        noise_ratio = min(1.0, (2.0 * sigma_noise_sq) / var_r)

                        self._info_share = is_ratio
                        self._noise_ratio = noise_ratio

                        if noise_ratio >= self._max_noise_ratio:
                            self._block(_REASON_NOISE, ts)
                        elif is_ratio <= self._min_info_share:
                            self._block(_REASON_COLLAPSE, ts)

            self._last_mid = mid
            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
