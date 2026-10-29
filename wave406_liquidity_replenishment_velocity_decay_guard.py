"""
Wave 406 -- Sovereign Liquidity Replenishment Velocity Decay Guard
==================================================================
Monitors the velocity and latency with which top-of-book liquidity is replenished
following an aggressive market order sweep or cancellation shock. In resilient markets,
passive liquidity replenishes rapidly. When replenishment velocity decays or latency
spikes, it reveals structural provider withdrawal, preceding catastrophic slippage.

Methodology
-----------
* Observes aggregate top-of-book depth Q_t = bid_queue + ask_queue at timestamp t.
* Detects depth depletion events when Q_t < Q_{t-1} * (1 - depletion_fraction).
* Measures recovery time tau = t_recover - t_deplete and replenished volume Delta Q.
* Replenishment velocity: v_replenish = Delta Q / max(tau, 1e-4).
* If v_replenish < `min_velocity_threshold` or tau > `max_latency_sec`, blocks entries.

Blocking reasons
----------------
LIQUIDITY_REPLENISHMENT_DECAY -- replenishment velocity fell below safety floor
REPLENISHMENT_LATENCY_SPIKE  -- depth replenishment exceeded maximum latency window
INPUT_VALIDATION_ERROR       -- non-positive queue, non-monotonic timestamp or invalid params

Public API (standardised)
-------------------------
update(bid_queue, ask_queue, timestamp) -> None
is_blocked(current_time=None)           -> bool
is_entry_blocked(bid, ask, ts)          -> bool
reset()                                 -> None
last_reason                             -> str
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave406LiquidityReplenishmentVelocityDecayGuard"]

_REASON_VELOCITY_DECAY = "LIQUIDITY_REPLENISHMENT_DECAY"
_REASON_LATENCY_SPIKE = "REPLENISHMENT_LATENCY_SPIKE"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave406LiquidityReplenishmentVelocityDecayGuard:
    """LOB Liquidity Replenishment Velocity Decay Guard."""

    def __init__(
        self,
        window_size: int = 10,
        depletion_fraction: float = 0.25,
        min_velocity_threshold: float = 5.0,
        max_latency_sec: float = 2.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            window_size < 3
            or not (0.05 <= depletion_fraction < 0.95)
            or min_velocity_threshold <= 0.0
            or max_latency_sec <= 0.0
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave406LiquidityReplenishmentVelocityDecayGuard")

        self._window_size = int(window_size)
        self._depletion_fraction = float(depletion_fraction)
        self._min_velocity = float(min_velocity_threshold)
        self._max_latency = float(max_latency_sec)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_q: Optional[float] = None
        self._last_ts: Optional[float] = None
        self._depletion_ts: Optional[float] = None
        self._depletion_base_q: Optional[float] = None
        self._depletion_min_q: Optional[float] = None
        self._blocked_until: float = 0.0
        self._last_reason: str = ""
        self._velocities: deque[float] = deque(maxlen=self._window_size)

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    def reset(self) -> None:
        with self._lock:
            self._last_q = None
            self._last_ts = None
            self._depletion_ts = None
            self._depletion_base_q = None
            self._depletion_min_q = None
            self._blocked_until = 0.0
            self._last_reason = ""
            self._velocities.clear()

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
                # Check if a depletion shock occurs
                if q_t < self._last_q * (1.0 - self._depletion_fraction):
                    if self._depletion_ts is None:
                        self._depletion_ts = ts
                        self._depletion_base_q = self._last_q
                        self._depletion_min_q = q_t
                    else:
                        self._depletion_min_q = min(self._depletion_min_q or q_t, q_t)
                elif self._depletion_ts is not None and self._depletion_base_q is not None:
                    # Depletion is currently active; update minimum or check replenishment
                    if q_t < (self._depletion_min_q or q_t):
                        self._depletion_min_q = q_t

                    dt = ts - self._depletion_ts
                    if dt > self._max_latency:
                        # Replenishment took too long!
                        self._block(_REASON_LATENCY_SPIKE, ts)
                        self._depletion_ts = None
                        self._depletion_base_q = None
                        self._depletion_min_q = None
                    elif q_t >= self._depletion_base_q * 0.90:
                        # Recovered back to at least 90% of base
                        rec_volume = q_t - (self._depletion_min_q or 0.0)
                        velocity = rec_volume / max(dt, 1e-4)
                        self._velocities.append(velocity)
                        if velocity < self._min_velocity:
                            self._block(_REASON_VELOCITY_DECAY, ts)
                        self._depletion_ts = None
                        self._depletion_base_q = None
                        self._depletion_min_q = None

            self._last_q = q_t
            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
