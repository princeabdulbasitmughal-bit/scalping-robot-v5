"""
Wave 429 -- Orderbook Queue Thickness Depletion Half-Life Guard
================================================================
Models exponential queue depth consumption under heavy predatory execution:
    Q(t) = Q_0 * exp(-lambda_{deplete} * t)
    t_{1/2} = ln(2) / lambda_{deplete}
When aggressive market sweeps consume the limit order book at an exponential rate,
the half-life of available queue depth collapses to sub-hundred-millisecond levels.
Ultra-short queue half-lives reveal vaporizing liquidity and imminent vacuum slippage.

Methodology
-----------
* Observes aggregate top-of-book depth Q_t = bid_queue + ask_queue at timestamp t.
* When depth undergoes a net decline (Q_t < Q_{t-1}), calculates instantaneous decay rate:
    lambda = ln(Q_{t-1} / Q_t) / dt
* Queue half-life: t_{1/2} = ln(2) / max(lambda, 1e-4) in seconds.
* If t_{1/2} <= `min_half_life_sec`, blocks with RAPID_QUEUE_HALF_LIFE_COLLAPSE.
* If Q_t <= 0.25 * Q_{t-1} and dt <= 0.20s, blocks with VAPORIZING_QUEUE_DEPTH.

Blocking reasons
----------------
RAPID_QUEUE_HALF_LIFE_COLLAPSE -- exponential queue depletion half-life fell below limit
VAPORIZING_QUEUE_DEPTH         -- catastrophic single-tick collapse of available book depth
INPUT_VALIDATION_ERROR         -- non-positive queue depth, invalid ts, or non-monotonic ts

Public API (standardised)
-------------------------
update(bid_queue, ask_queue, timestamp) -> None
is_blocked(current_time=None)           -> bool
is_entry_blocked(bid, ask, ts)          -> bool
reset()                                 -> None
last_reason                             -> str
half_life_sec                           -> float
"""

from __future__ import annotations

import math
import threading
import time
from typing import Optional

__all__ = ["Wave429QueueThicknessDepletionHalfLifeGuard"]

_REASON_HALFLIFE = "RAPID_QUEUE_HALF_LIFE_COLLAPSE"
_REASON_VAPORIZE = "VAPORIZING_QUEUE_DEPTH"
_REASON_VAL = "INPUT_VALIDATION_ERROR"
_LN_2 = math.log(2.0)


class Wave429QueueThicknessDepletionHalfLifeGuard:
    """Queue Thickness Depletion Half-Life Guard."""

    def __init__(
        self,
        min_half_life_sec: float = 0.08,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if min_half_life_sec <= 0.0 or cooldown_seconds <= 0.0:
            raise ValueError("Invalid parameters for Wave429QueueThicknessDepletionHalfLifeGuard")

        self._min_half_life = float(min_half_life_sec)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_q: Optional[float] = None
        self._last_ts: Optional[float] = None
        self._half_life_sec: float = 10.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def half_life_sec(self) -> float:
        with self._lock:
            return self._half_life_sec

    def reset(self) -> None:
        with self._lock:
            self._last_q = None
            self._last_ts = None
            self._half_life_sec = 10.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(self, bid_queue: float, ask_queue: float, timestamp: float) -> None:
        with self._lock:
            if (
                not isinstance(bid_queue, (int, float))
                or not isinstance(ask_queue, (int, float))
                or not isinstance(timestamp, (int, float))
                or bid_queue <= 0.0
                or ask_queue <= 0.0
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if timestamp > 0 else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            q_t = float(bid_queue + ask_queue)
            ts = float(timestamp)

            if self._last_q is not None and self._last_ts is not None:
                dt = max(ts - self._last_ts, 1e-4)

                if q_t < self._last_q:
                    # Depletion occurred
                    decay_ratio = self._last_q / q_t
                    lam = math.log(decay_ratio) / dt

                    if lam > 0.0:
                        t_half = _LN_2 / lam
                        self._half_life_sec = t_half

                        # Check vaporizing collapse (> 75% drop in sub-200ms)
                        if q_t <= 0.25 * self._last_q and dt <= 0.20:
                            self._block(_REASON_VAPORIZE, ts)
                        elif t_half <= self._min_half_life:
                            self._block(_REASON_HALFLIFE, ts)

            self._last_q = q_t
            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
