"""
Wave 426 -- Flow-Induced Market Impact Decay Guard
==================================================
Based on Bouchaud, Mézard, and Potters (2004) propagator theory of transient market impact:
    I(t) = Y * (sigma / V) * Q^delta * G(t)
where G(t) approx t^{-gamma} is the power-law relaxation kernel. In resilient markets,
aggressive order execution causes immediate price impact that relaxes as new passive
liquidity arrives. If impact fails to decay (relaxation stall) or becomes permanently
entrenched, the market book has undergone structural liquidity dislocation.

Methodology
-----------
* Observes trade impact event: (impact_pips, elapsed_seconds, timestamp).
* Computes normalized relaxation decay rate:
    R_{decay} = (impact_initial - impact_current) / max(impact_initial, 1e-4)
* Evaluates decay velocity: v_{decay} = R_{decay} / max(elapsed_seconds, 1e-4).
* If after elapsed_seconds >= min_observation_sec, R_{decay} <= `min_decay_threshold`,
  blocks with PERMANENT_IMPACT_DISLOCATION.
* If decay velocity v_{decay} <= `min_decay_velocity`, blocks with IMPACT_RELAXATION_STALL.

Blocking reasons
----------------
PERMANENT_IMPACT_DISLOCATION -- market impact failed to relax, creating permanent distortion
IMPACT_RELAXATION_STALL      -- impact relaxation velocity collapsed below acceptable bounds
INPUT_VALIDATION_ERROR       -- negative impact/elapsed time, or non-monotonic ts

Public API (standardised)
-------------------------
update(impact_initial, impact_current, elapsed_sec, timestamp) -> None
is_blocked(current_time=None)                                 -> bool
is_entry_blocked(bid, ask, ts)                                -> bool
reset()                                                       -> None
last_reason                                                   -> str
decay_ratio                                                   -> float
"""

from __future__ import annotations

import threading
import time
from typing import Optional

__all__ = ["Wave426FlowInducedImpactDecayGuard"]

_REASON_PERM = "PERMANENT_IMPACT_DISLOCATION"
_REASON_STALL = "IMPACT_RELAXATION_STALL"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave426FlowInducedImpactDecayGuard:
    """Flow-Induced Market Impact Decay Guard."""

    def __init__(
        self,
        min_decay_threshold: float = 0.30,
        min_decay_velocity: float = 0.10,
        min_observation_sec: float = 1.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            not (0.05 <= min_decay_threshold <= 0.90)
            or min_decay_velocity <= 0.0
            or min_observation_sec <= 0.0
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave426FlowInducedImpactDecayGuard")

        self._min_decay = float(min_decay_threshold)
        self._min_velocity = float(min_decay_velocity)
        self._min_obs = float(min_observation_sec)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._decay_ratio: float = 1.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def decay_ratio(self) -> float:
        with self._lock:
            return self._decay_ratio

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._decay_ratio = 1.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(
        self,
        impact_initial: float,
        impact_current: float,
        elapsed_sec: float,
        timestamp: float,
    ) -> None:
        with self._lock:
            if (
                not isinstance(impact_initial, (int, float))
                or not isinstance(impact_current, (int, float))
                or not isinstance(elapsed_sec, (int, float))
                or not isinstance(timestamp, (int, float))
                or impact_initial <= 0.0
                or impact_current < 0.0
                or elapsed_sec < 0.0
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if timestamp > 0 else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)
            init_imp = float(impact_initial)
            curr_imp = float(impact_current)
            el_sec = float(elapsed_sec)

            # Decay ratio = fraction of initial impact that has dissipated
            decay = max(0.0, (init_imp - curr_imp) / init_imp)
            self._decay_ratio = decay

            if el_sec >= self._min_obs:
                velocity = decay / max(el_sec, 1e-4)

                if decay < self._min_decay:
                    self._block(_REASON_PERM, ts)
                elif velocity < self._min_velocity:
                    self._block(_REASON_STALL, ts)

            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
