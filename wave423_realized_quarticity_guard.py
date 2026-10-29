"""
Wave 423 -- Realized Tri-Power Quarticity (TPQ) & Vol-of-Vol Guard
==================================================================
Measures the jump-robust continuous volatility-of-volatility (vol-of-vol) using
Barndorff-Nielsen and Shephard's (2004, 2006) Realized Tri-Power Quarticity (TPQ):
    TPQ = N * (mu_{4/3}^{-3} / (N - 2)) * sum_{i=3}^N |r_i|^{4/3} * |r_{i-1}|^{4/3} * |r_{i-2}|^{4/3}
where mu_{4/3} = 2^{2/3} * Gamma(7/6) / Gamma(1/2) approx 0.83086, mu_{4/3}^{-3} approx 1.7408.
Unlike standard realized quarticity (RQ), TPQ is invariant to discrete jump breaks,
isolating true diffusion variance instability. Supercritical TPQ warns of an imminent
volatility shock before midprice breakout.

Methodology
-----------
* Observes midprice returns r_i = ln(P_i / P_{i-1}) over rolling window N (`window_size`).
* Evaluates Realized Variance: RV = sum_{i=1}^N r_i^2.
* Evaluates Tri-Power Quarticity TPQ.
* Evaluates normalized quarticity ratio: Q_ratio = TPQ / max(RV^2, 1e-14).
* If TPQ >= `max_tpq_threshold`, blocks with SUPERCRITICAL_REALIZED_QUARTICITY.
* If Q_ratio >= `max_tpq_ratio` and TPQ > 1e-8, blocks with VOL_OF_VOL_TURBULENCE_SPIKE.

Blocking reasons
----------------
SUPERCRITICAL_REALIZED_QUARTICITY -- continuous diffusion vol-of-vol exceeded critical bound
VOL_OF_VOL_TURBULENCE_SPIKE       -- normalized quarticity-to-variance ratio reveals turbulence
INPUT_VALIDATION_ERROR            -- non-positive prices, bid >= ask, non-monotonic ts

Public API (standardised)
-------------------------
update(bid, ask, timestamp)    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
tpq                            -> float
quarticity_ratio               -> float
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave423RealizedQuarticityGuard"]

_REASON_QUARTICITY = "SUPERCRITICAL_REALIZED_QUARTICITY"
_REASON_TURBULENCE = "VOL_OF_VOL_TURBULENCE_SPIKE"
_REASON_VAL = "INPUT_VALIDATION_ERROR"
_MU_4_3_INV_CUBED = 1.74081  # (2^(2/3) * Gamma(7/6) / Gamma(1/2))^(-3)
_FOUR_THIRDS = 4.0 / 3.0


class Wave423RealizedQuarticityGuard:
    """Realized Tri-Power Quarticity Guard."""

    def __init__(
        self,
        window_size: int = 15,
        max_tpq_threshold: float = 1e-4,
        max_tpq_ratio: float = 6.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            window_size < 5
            or max_tpq_threshold <= 0.0
            or max_tpq_ratio <= 1.0
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave423RealizedQuarticityGuard")

        self._window_size = int(window_size)
        self._max_tpq = float(max_tpq_threshold)
        self._max_ratio = float(max_tpq_ratio)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_mid: Optional[float] = None
        self._last_ts: Optional[float] = None
        self._returns: deque[float] = deque(maxlen=self._window_size)
        self._tpq: float = 0.0
        self._q_ratio: float = 1.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def tpq(self) -> float:
        with self._lock:
            return self._tpq

    @property
    def quarticity_ratio(self) -> float:
        with self._lock:
            return self._q_ratio

    def reset(self) -> None:
        with self._lock:
            self._last_mid = None
            self._last_ts = None
            self._returns.clear()
            self._tpq = 0.0
            self._q_ratio = 1.0
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
                    rv = sum(r * r for r in self._returns)

                    # Compute Tri-Power Quarticity
                    tp_sum = sum(
                        (abs(self._returns[i]) ** _FOUR_THIRDS)
                        * (abs(self._returns[i - 1]) ** _FOUR_THIRDS)
                        * (abs(self._returns[i - 2]) ** _FOUR_THIRDS)
                        for i in range(2, n)
                    )
                    tpq = float(n) * (_MU_4_3_INV_CUBED / float(n - 2)) * tp_sum
                    self._tpq = tpq

                    q_ratio = tpq / max(rv * rv, 1e-14)
                    self._q_ratio = q_ratio

                    if tpq >= self._max_tpq:
                        self._block(_REASON_QUARTICITY, ts)
                    elif q_ratio >= self._max_ratio and tpq > 1e-8:
                        self._block(_REASON_TURBULENCE, ts)

            self._last_mid = mid
            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
