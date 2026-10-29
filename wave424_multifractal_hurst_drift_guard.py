"""
Wave 424 -- Multifractal Hurst Drift & Spectrum Width Guard
===========================================================
Evaluates cross-scale multifractal non-linear dynamics using simplified Multifractal
Detrended Fluctuation Analysis (MF-DFA). Computes generalized scaling exponents:
    H(1): first moment (absolute deviation) scaling
    H(2): second moment (variance / standard Hurst) scaling
    Delta H = |H(1) - H(2)| : multifractal spectrum width
In monofractal Gaussian markets, H(1) approx H(2) approx 0.50 (Delta H approx 0).
When multi-scale liquidity cascades develop, non-linear coupling expands the multifractal
spectrum width (Delta H >= 0.25), warning of severe turbulence and scale-free slippage.

Methodology
-----------
* Observes midprice returns r_i over rolling window N (`window_size` = 16).
* Computes multi-scale variation at scales s_1 = 2 and s_2 = 4:
    F_1(s) = mean(|r_{i+s} - r_i|)
    F_2(s) = sqrt(mean((r_{i+s} - r_i)^2))
* Estimates scaling exponents:
    H(1) = ln(F_1(s_2) / max(F_1(s_1), 1e-12)) / ln(s_2 / s_1)
    H(2) = ln(F_2(s_2) / max(F_2(s_1), 1e-12)) / ln(s_2 / s_1)
* Evaluates spectrum width: Delta H = |H(1) - H(2)|.
* If Delta H >= `max_spectrum_width`, blocks with MULTIFRACTAL_SPECTRUM_EXPANSION.
* If H(2) <= 0.15 (extreme rough anti-persistence), blocks with MULTISCALE_VOLATILITY_CASCADE.

Blocking reasons
----------------
MULTIFRACTAL_SPECTRUM_EXPANSION -- multifractal spectrum width exceeded monofractal corridor
MULTISCALE_VOLATILITY_CASCADE   -- extreme rough anti-persistence in high-frequency scaling
INPUT_VALIDATION_ERROR          -- non-positive price, bid >= ask, non-monotonic ts

Public API (standardised)
-------------------------
update(bid, ask, timestamp)    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
multifractal_width             -> float
hurst_h2                       -> float
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave424MultifractalHurstDriftGuard"]

_REASON_EXPANSION = "MULTIFRACTAL_SPECTRUM_EXPANSION"
_REASON_CASCADE = "MULTISCALE_VOLATILITY_CASCADE"
_REASON_VAL = "INPUT_VALIDATION_ERROR"
_LN_2 = math.log(2.0)  # ln(s_2 / s_1) = ln(4 / 2) = ln(2)


class Wave424MultifractalHurstDriftGuard:
    """Multifractal Hurst Drift Guard."""

    def __init__(
        self,
        window_size: int = 16,
        max_spectrum_width: float = 0.25,
        min_h2_roughness: float = 0.15,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            window_size < 8
            or not (0.05 <= max_spectrum_width <= 0.80)
            or not (0.02 <= min_h2_roughness <= 0.40)
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave424MultifractalHurstDriftGuard")

        self._window_size = int(window_size)
        self._max_width = float(max_spectrum_width)
        self._min_h2 = float(min_h2_roughness)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_mid: Optional[float] = None
        self._last_ts: Optional[float] = None
        self._prices: deque[float] = deque(maxlen=self._window_size + 1)
        self._delta_h: float = 0.0
        self._h2: float = 0.50
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def multifractal_width(self) -> float:
        with self._lock:
            return self._delta_h

    @property
    def hurst_h2(self) -> float:
        with self._lock:
            return self._h2

    def reset(self) -> None:
        with self._lock:
            self._last_mid = None
            self._last_ts = None
            self._prices.clear()
            self._delta_h = 0.0
            self._h2 = 0.50
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
            self._prices.append(mid)

            n = len(self._prices)
            if n >= self._window_size:
                p_list = list(self._prices)
                # Compute multi-scale increments at scale s1=2 and s2=4
                diffs_s1 = [abs(p_list[i + 2] - p_list[i]) for i in range(len(p_list) - 2)]
                diffs_s2 = [abs(p_list[i + 4] - p_list[i]) for i in range(len(p_list) - 4)]

                if diffs_s1 and diffs_s2:
                    # Scale 1: s1 = 2
                    f1_s1 = sum(diffs_s1) / float(len(diffs_s1))
                    f2_s1 = math.sqrt(sum(d * d for d in diffs_s1) / float(len(diffs_s1)))

                    # Scale 2: s2 = 4
                    f1_s2 = sum(diffs_s2) / float(len(diffs_s2))
                    f2_s2 = math.sqrt(sum(d * d for d in diffs_s2) / float(len(diffs_s2)))

                    if f1_s1 > 1e-12 and f2_s1 > 1e-12 and f1_s2 > 1e-12 and f2_s2 > 1e-12:
                        h1 = math.log(f1_s2 / f1_s1) / _LN_2
                        h2 = math.log(f2_s2 / f2_s1) / _LN_2
                        delta_h = abs(h1 - h2)

                        self._h2 = h2
                        self._delta_h = delta_h

                        if delta_h >= self._max_width:
                            self._block(_REASON_EXPANSION, ts)
                        elif h2 <= self._min_h2:
                            self._block(_REASON_CASCADE, ts)

            self._last_mid = mid
            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
