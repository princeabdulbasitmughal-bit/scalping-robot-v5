"""
Wave 427 -- Cross-Tier Depth Co-Movement Beta Guard
===================================================
Evaluates the statistical elasticity beta of deep-tier order book depth (L2 to L5)
relative to top-of-book (L1) depth innovations:
    Delta Q_{deep, t} = alpha + beta_{depth} * Delta Q_{top, t} + epsilon_t
In resilient, well-arbitraged institutional markets, deep book liquidity expands and
contracts in tandem with top-of-book flow (beta_{depth} approx 0.5 to 1.5).
When beta collapses to near zero or becomes negative, deep market makers have decoupled
their support from top-of-book quotes, creating an isolated, fragile facade.

Methodology
-----------
* Observes changes in L1 depth: Delta Q_{top} and L2..L5 cumulative depth: Delta Q_{deep}.
* Maintains a rolling window of size N (`window_size`).
* Evaluates sample covariance Cov(Delta Q_{top}, Delta Q_{deep}) and Var(Delta Q_{top}).
* Regression beta: beta_{depth} = Cov / max(Var, 1e-12).
* If beta_{depth} <= `min_depth_beta`, blocks with CROSS_TIER_DEPTH_DECOUPLING.
* If beta_{depth} >= `max_depth_beta`, blocks with DEEP_BOOK_LIQUIDITY_ISOLATION.

Blocking reasons
----------------
CROSS_TIER_DEPTH_DECOUPLING    -- deep-tier depth decoupled from top-of-book quote flow
DEEP_BOOK_LIQUIDITY_ISOLATION  -- excessive hyper-elastic deep queue expansion indicates spoofing
INPUT_VALIDATION_ERROR         -- non-positive queue, invalid delta, or non-monotonic ts

Public API (standardised)
-------------------------
update(q_top, q_deep, timestamp) -> None
is_blocked(current_time=None)    -> bool
is_entry_blocked(bid, ask, ts)   -> bool
reset()                          -> None
last_reason                      -> str
depth_beta                       -> float
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave427CrossTierDepthBetaGuard"]

_REASON_DECOUPLE = "CROSS_TIER_DEPTH_DECOUPLING"
_REASON_ISOLATION = "DEEP_BOOK_LIQUIDITY_ISOLATION"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave427CrossTierDepthBetaGuard:
    """Cross-Tier Depth Co-Movement Beta Guard."""

    def __init__(
        self,
        window_size: int = 12,
        min_depth_beta: float = 0.20,
        max_depth_beta: float = 2.50,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            window_size < 5
            or min_depth_beta <= -1.0
            or max_depth_beta <= min_depth_beta
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave427CrossTierDepthBetaGuard")

        self._window_size = int(window_size)
        self._min_beta = float(min_depth_beta)
        self._max_beta = float(max_depth_beta)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_top_q: Optional[float] = None
        self._last_deep_q: Optional[float] = None
        self._last_ts: Optional[float] = None
        self._deltas_top: deque[float] = deque(maxlen=self._window_size)
        self._deltas_deep: deque[float] = deque(maxlen=self._window_size)
        self._current_beta: float = 1.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def depth_beta(self) -> float:
        with self._lock:
            return self._current_beta

    def reset(self) -> None:
        with self._lock:
            self._last_top_q = None
            self._last_deep_q = None
            self._last_ts = None
            self._deltas_top.clear()
            self._deltas_deep.clear()
            self._current_beta = 1.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(self, q_top: float, q_deep: float, timestamp: float) -> None:
        with self._lock:
            if (
                not isinstance(q_top, (int, float))
                or not isinstance(q_deep, (int, float))
                or not isinstance(timestamp, (int, float))
                or q_top <= 0.0
                or q_deep <= 0.0
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if timestamp > 0 else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)
            top = float(q_top)
            deep = float(q_deep)

            if self._last_top_q is not None and self._last_deep_q is not None:
                d_top = top - self._last_top_q
                d_deep = deep - self._last_deep_q
                self._deltas_top.append(d_top)
                self._deltas_deep.append(d_deep)

                n = len(self._deltas_top)
                if n >= self._window_size:
                    mean_t = sum(self._deltas_top) / float(n)
                    mean_d = sum(self._deltas_deep) / float(n)

                    var_t = sum((x - mean_t) ** 2 for x in self._deltas_top)
                    cov_td = sum(
                        (self._deltas_top[i] - mean_t) * (self._deltas_deep[i] - mean_d)
                        for i in range(n)
                    )

                    if var_t > 1e-12:
                        beta = cov_td / var_t
                        self._current_beta = beta

                        if beta <= self._min_beta:
                            self._block(_REASON_DECOUPLE, ts)
                        elif beta >= self._max_beta:
                            self._block(_REASON_ISOLATION, ts)

            self._last_top_q = top
            self._last_deep_q = deep
            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
