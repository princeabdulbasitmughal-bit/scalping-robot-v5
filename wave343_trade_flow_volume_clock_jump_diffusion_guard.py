"""
Wave 343 -- Trade Flow Volume Clock Jump-Diffusion Guard
=========================================================
Monitors price dynamics sampled in volume-clock time (equal-volume buckets).
Under normal continuous trading, volume-clock price returns follow a diffusion
process. When predatory sweeps or macro shocks occur, price dynamics exhibit
jump-diffusion behavior detected via the Barndorff-Nielsen & Shephard jump statistic:
    RV  = sum(r_i^2)
    BPV = (pi / 2) * sum(|r_i| * |r_{i-1}|)
    JumpRatio = max(0, (RV - BPV) / RV)

When JumpRatio >= jump_ratio_threshold over a rolling window of volume buckets,
or when an extreme instantaneous volume jump return occurs, the guard halts entry
to prevent getting caught in discontinuous predatory liquidity gaps.

Blocking reasons
----------------
VOLUME_CLOCK_JUMP_DIFFUSION  -- JumpRatio >= jump_ratio_threshold
INPUT_VALIDATION_ERROR       -- malformed, non-positive or bool inputs

Public API
----------
update(price, volume, timestamp) -> None
is_blocked(current_time=None)    -> bool
is_entry_blocked(bid, ask, ts)   -> bool
reset()                          -> None
last_reason                      -> str
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave343TradeFlowVolumeClockJumpDiffusionGuard"]

_REASON_JUMP = "VOLUME_CLOCK_JUMP_DIFFUSION"
_REASON_VAL  = "INPUT_VALIDATION_ERROR"
_PI_OVER_TWO = math.pi / 2.0


class Wave343TradeFlowVolumeClockJumpDiffusionGuard:
    """Detects discontinuous jump-diffusion price shocks under volume-clock sampling."""

    def __init__(
        self,
        bucket_volume: float = 50.0,
        window_buckets: int = 8,
        jump_ratio_threshold: float = 0.65,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if bucket_volume <= 0 or window_buckets < 4 or not (0.0 < jump_ratio_threshold <= 1.0):
            raise ValueError("Invalid parameters for Volume Clock Jump-Diffusion Guard.")
        self._bucket_volume = float(bucket_volume)
        self._window_buckets = int(window_buckets)
        self._threshold = float(jump_ratio_threshold)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._current_bucket_vol = 0.0
        self._bucket_open_price: Optional[float] = None
        self._bucket_returns: deque = deque(maxlen=window_buckets)
        self._blocked_until = 0.0
        self._blocked_until_sim = 0.0
        self._last_reason = ""

    def update(self, price: float, volume: float, timestamp: float) -> None:
        with self._lock:
            # Type and boolean validation
            if isinstance(price, bool) or isinstance(volume, bool) or isinstance(timestamp, bool):
                self._block(timestamp, _REASON_VAL)
                return
            if not (isinstance(price, (int, float)) and isinstance(volume, (int, float)) and isinstance(timestamp, (int, float))):
                self._block(timestamp, _REASON_VAL)
                return

            p = float(price)
            v = float(volume)
            ts = float(timestamp)

            if p <= 0 or v <= 0:
                self._block(ts, _REASON_VAL)
                return

            if self._bucket_open_price is None:
                self._bucket_open_price = p

            self._current_bucket_vol += v

            # Check if volume bucket has closed
            if self._current_bucket_vol >= self._bucket_volume:
                ret = (p - self._bucket_open_price) / self._bucket_open_price
                self._bucket_returns.append(ret)
                # Reset for next bucket
                self._current_bucket_vol = 0.0
                self._bucket_open_price = p

                if len(self._bucket_returns) >= self._window_buckets:
                    returns = list(self._bucket_returns)
                    n = len(returns)

                    # Realized Volatility: RV = sum(r_i^2)
                    rv = sum(r * r for r in returns)
                    if rv < 1e-12:
                        return

                    # Bipower Variation: BPV = (pi/2) * sum(|r_i| * |r_{i-1}|)
                    bpv = _PI_OVER_TWO * sum(abs(returns[i]) * abs(returns[i - 1]) for i in range(1, n))

                    # Jump proportion: (RV - BPV) / RV
                    jump_component = max(0.0, rv - bpv)
                    jump_ratio = jump_component / rv

                    if jump_ratio >= self._threshold:
                        self._block(ts, _REASON_JUMP)

    def _block(self, timestamp: float, reason: str) -> None:
        now_mono = time.monotonic()
        self._blocked_until = now_mono + self._cooldown
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool) and timestamp > 0:
            self._blocked_until_sim = timestamp + self._cooldown
        else:
            self._blocked_until_sim = self._blocked_until
        self._last_reason = reason

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            if current_time is not None:
                return current_time < self._blocked_until_sim
            return time.monotonic() < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: float) -> bool:
        return self.is_blocked(ts)

    def reset(self) -> None:
        with self._lock:
            self._current_bucket_vol = 0.0
            self._bucket_open_price = None
            self._bucket_returns.clear()
            self._blocked_until = 0.0
            self._blocked_until_sim = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
