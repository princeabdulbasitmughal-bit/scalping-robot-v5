"""
Wave 420 -- Apex Sovereign Resiliency & Multi-Horizon Guard
===========================================================
The crowning quantitative defense of the 420-Wave architecture. Evaluates structural
order book resiliency R in [0, 1] across multi-horizon dimensions:
    1. Spread Tightness Resiliency: R_{spread} = exp(-Spread / S_{base})
    2. Depth Thickness Resiliency:  R_{depth}  = min(1.0, (Q_b + Q_a) / Q_{base})
    3. Order Flow Balance:          R_{flow}   = 1.0 - |Imbalance|
    4. Kinematic Price Stability:   R_{stab}   = 1.0 - min(1.0, |v_{mid}| / v_{max})

When market shock strikes, a resilient book absorbs orders smoothly. If composite
resiliency R collapses or multiple pillars fail concurrently, market microstructure
fractures into catastrophic slippage, requiring immediate sovereign lockout.

Methodology
-----------
* Observes: (bid, ask, bid_queue, ask_queue, recent_buy_vol, recent_sell_vol, timestamp).
* Computes normalized sub-pillar resiliency scores R_{spread}, R_{depth}, R_{flow}, R_{stab}.
* Weighted aggregate resiliency: R = 0.30*R_{spread} + 0.30*R_{depth} + 0.25*R_{flow} + 0.15*R_{stab}.
* If R < `min_resiliency_threshold`, blocks with SOVEREIGN_RESILIENCY_COLLAPSE.
* If R_{spread} < 0.20 and R_{depth} < 0.20, blocks with MULTI_HORIZON_MICROSTRUCTURE_FRACTURE.

Blocking reasons
----------------
SOVEREIGN_RESILIENCY_COLLAPSE          -- composite market resiliency score fell below critical floor
MULTI_HORIZON_MICROSTRUCTURE_FRACTURE  -- simultaneous spread blow-out and depth evaporation
INPUT_VALIDATION_ERROR                 -- non-positive prices/depth, bid >= ask, non-monotonic ts

Public API (standardised)
-------------------------
update(...)                    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
resiliency_score               -> float
"""

from __future__ import annotations

import math
import threading
import time
from typing import Optional

__all__ = ["Wave420ApexSovereignResiliencyGuard"]

_REASON_COLLAPSE = "SOVEREIGN_RESILIENCY_COLLAPSE"
_REASON_FRACTURE = "MULTI_HORIZON_MICROSTRUCTURE_FRACTURE"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave420ApexSovereignResiliencyGuard:
    """Apex Sovereign Resiliency and Multi-Horizon Guard."""

    def __init__(
        self,
        min_resiliency_threshold: float = 0.35,
        base_spread: float = 0.05,
        base_depth: float = 100.0,
        max_mid_velocity: float = 2.0,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if (
            not (0.10 <= min_resiliency_threshold <= 0.90)
            or base_spread <= 0.0
            or base_depth <= 0.0
            or max_mid_velocity <= 0.0
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave420ApexSovereignResiliencyGuard")

        self._min_resiliency = float(min_resiliency_threshold)
        self._base_spread = float(base_spread)
        self._base_depth = float(base_depth)
        self._max_vel = float(max_mid_velocity)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_mid: Optional[float] = None
        self._last_ts: Optional[float] = None
        self._resiliency_score: float = 1.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def resiliency_score(self) -> float:
        with self._lock:
            return self._resiliency_score

    def reset(self) -> None:
        with self._lock:
            self._last_mid = None
            self._last_ts = None
            self._resiliency_score = 1.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(
        self,
        bid: float,
        ask: float,
        bid_queue: float,
        ask_queue: float,
        recent_buy_vol: float,
        recent_sell_vol: float,
        timestamp: float,
    ) -> None:
        with self._lock:
            if (
                not isinstance(bid, (int, float))
                or not isinstance(ask, (int, float))
                or not isinstance(bid_queue, (int, float))
                or not isinstance(ask_queue, (int, float))
                or not isinstance(recent_buy_vol, (int, float))
                or not isinstance(recent_sell_vol, (int, float))
                or not isinstance(timestamp, (int, float))
                or bid <= 0.0
                or ask <= 0.0
                or bid >= ask
                or bid_queue <= 0.0
                or ask_queue <= 0.0
                or recent_buy_vol < 0.0
                or recent_sell_vol < 0.0
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if timestamp > 0 else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)
            mid = (float(bid) + float(ask)) / 2.0
            spread = float(ask) - float(bid)
            total_depth = float(bid_queue) + float(ask_queue)
            total_vol = float(recent_buy_vol) + float(recent_sell_vol)

            # 1. Spread tightness resiliency
            r_spread = math.exp(-spread / self._base_spread)

            # 2. Depth thickness resiliency
            r_depth = min(1.0, total_depth / self._base_depth)

            # 3. Flow balance resiliency
            flow_imbalance = abs(float(recent_buy_vol) - float(recent_sell_vol)) / max(total_vol, 1e-6)
            r_flow = max(0.0, 1.0 - flow_imbalance)

            # 4. Kinematic stability resiliency
            v_mid = 0.0
            if self._last_mid is not None and self._last_ts is not None:
                dt = max(ts - self._last_ts, 1e-6)
                v_mid = abs(mid - self._last_mid) / dt
            r_stab = max(0.0, 1.0 - min(1.0, v_mid / self._max_vel))

            # Composite resiliency
            r_composite = 0.30 * r_spread + 0.30 * r_depth + 0.25 * r_flow + 0.15 * r_stab
            self._resiliency_score = r_composite

            # Multi-horizon fracture check
            if r_spread < 0.20 and r_depth < 0.20:
                self._block(_REASON_FRACTURE, ts)
            elif r_composite < self._min_resiliency:
                self._block(_REASON_COLLAPSE, ts)

            self._last_mid = mid
            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
