"""
Wave 422 -- Liquidity Replenishment Asymmetry & Skew Drift Guard
================================================================
Compares the replenishment velocities of the bid versus ask sides of the limit order
book following market consumption. When passive liquidity providers replenish one side
aggressively while letting the opposite side drain (asymmetry Lambda in [-1, +1]),
it signals structural market maker capital withdrawal anticipating an imminent toxic cascade.

Methodology
-----------
* Observes top-of-book depth: (bid_queue, ask_queue, timestamp).
* Computes positive incremental replenishment: Delta Q_{bid}^+ and Delta Q_{ask}^+.
* Evaluates replenishment velocities: v_{bid} = Delta Q_{bid}^+ / dt, v_{ask} = Delta Q_{ask}^+ / dt.
* Replenishment asymmetry index:
    Lambda = (v_{ask} - v_{bid}) / (v_{ask} + v_{bid} + 1e-6)
* Maintains rolling window of size N (`window_size`).
* If |Lambda| >= `max_asymmetry_threshold`, blocks with LIQUIDITY_REPLENISHMENT_ASYMMETRY.
* If average rolling asymmetry exceeds threshold, blocks with ONE_SIDED_LIQUIDITY_DRAIN.

Blocking reasons
----------------
LIQUIDITY_REPLENISHMENT_ASYMMETRY -- severe imbalance between bid and ask replenishment speed
ONE_SIDED_LIQUIDITY_DRAIN        -- persistent structural starvation of liquidity on one side
INPUT_VALIDATION_ERROR           -- non-positive queue depth, invalid ts, or non-monotonic ts

Public API (standardised)
-------------------------
update(bid_queue, ask_queue, timestamp) -> None
is_blocked(current_time=None)           -> bool
is_entry_blocked(bid, ask, ts)          -> bool
reset()                                 -> None
last_reason                             -> str
asymmetry_index                         -> float
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave422ReplenishmentAsymmetryGuard"]

_REASON_ASYM = "LIQUIDITY_REPLENISHMENT_ASYMMETRY"
_REASON_DRAIN = "ONE_SIDED_LIQUIDITY_DRAIN"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave422ReplenishmentAsymmetryGuard:
    """Liquidity Replenishment Asymmetry Guard."""

    def __init__(
        self,
        window_size: int = 10,
        max_asymmetry_threshold: float = 0.70,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            window_size < 3
            or not (0.20 <= max_asymmetry_threshold <= 0.95)
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave422ReplenishmentAsymmetryGuard")

        self._window_size = int(window_size)
        self._max_asym = float(max_asymmetry_threshold)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_bid_q: Optional[float] = None
        self._last_ask_q: Optional[float] = None
        self._last_ts: Optional[float] = None
        self._asymmetries: deque[float] = deque(maxlen=self._window_size)
        self._current_lambda: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def asymmetry_index(self) -> float:
        with self._lock:
            return self._current_lambda

    def reset(self) -> None:
        with self._lock:
            self._last_bid_q = None
            self._last_ask_q = None
            self._last_ts = None
            self._asymmetries.clear()
            self._current_lambda = 0.0
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

            ts = float(timestamp)
            bq = float(bid_queue)
            aq = float(ask_queue)

            if (
                self._last_bid_q is not None
                and self._last_ask_q is not None
                and self._last_ts is not None
            ):
                dt = max(ts - self._last_ts, 1e-4)
                # Compute replenishment speed (positive delta)
                v_bid = max(0.0, (bq - self._last_bid_q) / dt)
                v_ask = max(0.0, (aq - self._last_ask_q) / dt)

                denom = v_ask + v_bid
                if denom > 1e-6:
                    lambda_idx = (v_ask - v_bid) / denom
                    self._current_lambda = lambda_idx
                    self._asymmetries.append(lambda_idx)

                    if abs(lambda_idx) >= self._max_asym:
                        self._block(_REASON_ASYM, ts)
                    elif len(self._asymmetries) >= self._window_size:
                        avg_asym = sum(self._asymmetries) / float(len(self._asymmetries))
                        if abs(avg_asym) >= self._max_asym * 0.85:
                            self._block(_REASON_DRAIN, ts)

            self._last_bid_q = bq
            self._last_ask_q = aq
            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
