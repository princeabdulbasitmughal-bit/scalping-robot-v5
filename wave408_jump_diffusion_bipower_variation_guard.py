"""
Wave 408 -- Jump Diffusion & Realized Bipower Variation (BV) Guard
==================================================================
Decomposes high-frequency midprice variation into continuous Brownian diffusion and
discontinuous Poisson jump components using Barndorff-Nielsen and Shephard (2004)
Realized Bipower Variation (BV). When discrete jumps dominate continuous diffusion,
adverse selection risk spikes exponentially, necessitating immediate trade suspension.

Methodology
-----------
* Observes midprice ticks P_t = (bid + ask) / 2.0 and log-returns r_i = ln(P_i / P_{i-1}).
* Maintains a rolling window of size N (`window_size`).
* Realized Variance:
    RV = sum_{i=1}^N r_i^2
* Realized Bipower Variation:
    BV = (pi / 2) * sum_{i=2}^N |r_i| * |r_{i-1}|
* Relative Jump Contribution:
    S_J = max(0.0, (RV - BV) / (RV + 1e-14))
* Jump Standard Deviation:
    sigma_diff = sqrt(max(BV / max(N - 1, 1), 1e-14))
* If S_J >= `max_jump_ratio`, blocks with JUMP_DIFFUSION_INTENSITY_SPIKE.
* If |r_current| >= `jump_sigma_mult` * sigma_diff, blocks with DISCONTINUOUS_PRICE_JUMP.

Blocking reasons
----------------
JUMP_DIFFUSION_INTENSITY_SPIKE -- jump variance proportion exceeded safety threshold
DISCONTINUOUS_PRICE_JUMP        -- single tick return exceeded jump sigma multiplier
INPUT_VALIDATION_ERROR         -- non-positive prices, bid >= ask, non-monotonic ts, non-numeric

Public API (standardised)
-------------------------
update(bid, ask, timestamp)     -> None
is_blocked(current_time=None)   -> bool
is_entry_blocked(bid, ask, ts)  -> bool
reset()                         -> None
last_reason                     -> str
jump_ratio                      -> float
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave408JumpDiffusionBipowerVariationGuard"]

_REASON_JUMP_SPIKE = "JUMP_DIFFUSION_INTENSITY_SPIKE"
_REASON_DISCONTINUOUS = "DISCONTINUOUS_PRICE_JUMP"
_REASON_VAL = "INPUT_VALIDATION_ERROR"
_PI_OVER_TWO = math.pi / 2.0


class Wave408JumpDiffusionBipowerVariationGuard:
    """Jump Diffusion and Realized Bipower Variation Guard."""

    def __init__(
        self,
        window_size: int = 20,
        max_jump_ratio: float = 0.40,
        jump_sigma_mult: float = 4.0,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if (
            window_size < 5
            or not (0.05 <= max_jump_ratio <= 0.95)
            or jump_sigma_mult <= 1.0
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave408JumpDiffusionBipowerVariationGuard")

        self._window_size = int(window_size)
        self._max_jump_ratio = float(max_jump_ratio)
        self._jump_sigma_mult = float(jump_sigma_mult)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_mid: Optional[float] = None
        self._last_ts: Optional[float] = None
        self._returns: deque[float] = deque(maxlen=self._window_size)
        self._jump_ratio: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def jump_ratio(self) -> float:
        with self._lock:
            return self._jump_ratio

    def reset(self) -> None:
        with self._lock:
            self._last_mid = None
            self._last_ts = None
            self._returns.clear()
            self._jump_ratio = 0.0
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

                if len(self._returns) >= self._window_size:
                    # Calculate RV and BV
                    rv = sum(r * r for r in self._returns)
                    bv = _PI_OVER_TWO * sum(
                        abs(self._returns[i]) * abs(self._returns[i - 1])
                        for i in range(1, len(self._returns))
                    )

                    s_jump = max(0.0, (rv - bv) / (rv + 1e-14))
                    self._jump_ratio = s_jump

                    sigma_diff = math.sqrt(max(bv / max(len(self._returns) - 1, 1), 1e-14))

                    # Test jump ratio spike
                    if s_jump >= self._max_jump_ratio:
                        self._block(_REASON_JUMP_SPIKE, ts)

                    # Test single-tick discontinuous jump
                    if abs(ret) >= self._jump_sigma_mult * sigma_diff and abs(ret) > 1e-5:
                        self._block(_REASON_DISCONTINUOUS, ts)

            self._last_mid = mid
            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
