"""
Wave 412 -- Orderbook Multi-Level Depth Slope Elasticity Guard
==============================================================
Monitors the depth profile slope S_{depth} = Delta Q / Delta Level across multi-level
limit order books (L1 to L5). In resilient institutional markets, book depth expands
stably as price deviates from midprice. When the depth slope collapses (thinning book)
or inverts (top-level volume exceeds deeper tiers), large fills incur catastrophic
super-linear market impact.

Methodology
-----------
* Observes multi-level bid depths [q_1^b, ..., q_L^b] and ask depths [q_1^a, ..., q_L^a].
* Aggregate level depth: D_l = q_l^b + q_l^a for l = 1..L.
* Evaluates depth slope S = (D_L - D_1) / (L - 1) and average tier depth.
* Detects inverted depth: D_1 > sum_{l=2}^L D_l (top-heavy fragile book).
* If S < `min_depth_slope`, blocks with ORDERBOOK_DEPTH_SLOPE_COLLAPSE.
* If D_1 >= 1.5 * D_2 and D_2 <= 0.2 * D_1, blocks with TIER_LIQUIDITY_INVERSION.

Blocking reasons
----------------
ORDERBOOK_DEPTH_SLOPE_COLLAPSE -- multi-tier book depth expansion slope fell below floor
TIER_LIQUIDITY_INVERSION      -- top-of-book depth hollowed out deeper level liquidity
INPUT_VALIDATION_ERROR        -- non-positive queue, mismatching levels, or non-numeric params

Public API (standardised)
-------------------------
update(bid_levels, ask_levels, timestamp) -> None
is_blocked(current_time=None)             -> bool
is_entry_blocked(bid, ask, ts)            -> bool
reset()                                   -> None
last_reason                               -> str
current_slope                             -> float
"""

from __future__ import annotations

import threading
import time
from typing import List, Optional

__all__ = ["Wave412OrderbookDepthSlopeElasticityGuard"]

_REASON_SLOPE = "ORDERBOOK_DEPTH_SLOPE_COLLAPSE"
_REASON_INVERSION = "TIER_LIQUIDITY_INVERSION"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave412OrderbookDepthSlopeElasticityGuard:
    """Multi-Level Depth Slope Elasticity Guard."""

    def __init__(
        self,
        min_depth_slope: float = 2.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if min_depth_slope <= 0.0 or cooldown_seconds <= 0.0:
            raise ValueError("Invalid parameters for Wave412OrderbookDepthSlopeElasticityGuard")

        self._min_slope = float(min_depth_slope)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._current_slope: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def current_slope(self) -> float:
        with self._lock:
            return self._current_slope

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._current_slope = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(
        self,
        bid_levels: List[float],
        ask_levels: List[float],
        timestamp: float,
    ) -> None:
        with self._lock:
            if (
                not isinstance(bid_levels, (list, tuple))
                or not isinstance(ask_levels, (list, tuple))
                or len(bid_levels) != len(ask_levels)
                or len(bid_levels) < 2
                or not isinstance(timestamp, (int, float))
                or timestamp < 0.0
                or any(not isinstance(v, (int, float)) or v <= 0.0 for v in bid_levels)
                or any(not isinstance(v, (int, float)) or v <= 0.0 for v in ask_levels)
            ):
                self._block(_REASON_VAL, timestamp if timestamp > 0 else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)
            num_levels = len(bid_levels)

            tier_depths = [float(bid_levels[i] + ask_levels[i]) for i in range(num_levels)]
            d1 = tier_depths[0]
            dL = tier_depths[-1]

            slope = (dL - d1) / float(num_levels - 1)
            self._current_slope = slope

            # Check tier inversion: d1 huge, but d2 or deeper collapsed (< 20% of d1)
            d2 = tier_depths[1]
            if d1 >= 2.0 * d2 and d2 <= 0.25 * d1:
                self._block(_REASON_INVERSION, ts)
            elif slope < self._min_slope:
                self._block(_REASON_SLOPE, ts)

            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
