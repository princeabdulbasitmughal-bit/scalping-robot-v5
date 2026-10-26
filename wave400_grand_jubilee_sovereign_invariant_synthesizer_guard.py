"""
Wave 400 -- Grand Jubilee Sovereign Invariant Synthesizer Guard
==============================================================
The Master Synthesizer of the 400-Wave Quantitative Canopy.
Synthesizes the core microstructural dimensions across order flow toxicity,
price impact elasticity, non-linear curvature, multi-level entropy,
and liquidity spread dynamics into a unified Sovereign Invariant Composite Index.

Methodology
-----------
* Observes 5 normalized risk signals:
    1. spread_risk   in [0, 1] -- spread widening relative to baseline
    2. vpin_toxicity in [0, 1] -- volume-synchronized toxicity
    3. price_impact  in [0, 1] -- Kyle's lambda elasticity
    4. acceleration  in [0, 1] -- second-order non-linear trajectory curvature
    5. entropy_loss  in [0, 1] -- (1.0 - normalized Shannon entropy)
* Computes weighted Sovereign Composite Risk Score:
    Omega = sum(w_i * signal_i)
* Thresholds:
    - If Omega >= `critical_composite_threshold` -> blocks with `GRAND_JUBILEE_SOVEREIGN_RISK_BREACH`.
    - If count(signal_i >= `individual_veto_threshold`) >= `max_veto_signals` -> blocks with `MULTI_INVARIANT_CONSENSUS_VETO`.

Blocking reasons
----------------
GRAND_JUBILEE_SOVEREIGN_RISK_BREACH -- unified composite risk index exceeded critical threshold
MULTI_INVARIANT_CONSENSUS_VETO      -- multiple sub-invariants simultaneously tripped veto limits
INPUT_VALIDATION_ERROR              -- signals out of bounds [0, 1], invalid timestamp, non-numeric

Public API (standardised)
-------------------------
update(spread_risk, vpin, price_impact, acceleration, entropy_loss, timestamp) -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
composite_score                -> float
"""

from __future__ import annotations

import threading
import time
from typing import Optional, Sequence

__all__ = ["Wave400GrandJubileeSovereignInvariantSynthesizerGuard"]

_REASON_BREACH = "GRAND_JUBILEE_SOVEREIGN_RISK_BREACH"
_REASON_VETO = "MULTI_INVARIANT_CONSENSUS_VETO"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave400GrandJubileeSovereignInvariantSynthesizerGuard:
    """Wave 400 Grand Jubilee Sovereign Invariant Synthesizer Guard."""

    def __init__(
        self,
        weights: Optional[Sequence[float]] = None,
        critical_composite_threshold: float = 0.70,
        individual_veto_threshold: float = 0.85,
        max_veto_signals: int = 3,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if weights is None:
            self._weights = [0.20, 0.20, 0.20, 0.20, 0.20]
        else:
            if len(weights) != 5 or not math_isclose_one(sum(weights)):
                raise ValueError("Weights must have length 5 and sum to 1.0")
            self._weights = [float(w) for w in weights]

        if not (0.0 < critical_composite_threshold <= 1.0) or not (0.0 < individual_veto_threshold <= 1.0):
            raise ValueError("Invalid thresholds for Wave400GrandJubileeSovereignInvariantSynthesizerGuard")
        if max_veto_signals < 1 or max_veto_signals > 5 or cooldown_seconds <= 0.0:
            raise ValueError("Invalid veto signals count or cooldown")

        self._crit_thresh = float(critical_composite_threshold)
        self._veto_thresh = float(individual_veto_threshold)
        self._max_veto = int(max_veto_signals)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._last_composite: float = 0.0
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(
        self,
        spread_risk: float,
        vpin: float,
        price_impact: float,
        acceleration: float,
        entropy_loss: float,
        timestamp: float,
    ) -> None:
        with self._lock:
            signals = (spread_risk, vpin, price_impact, acceleration, entropy_loss)
            for val in signals + (timestamp,):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._block(_REASON_VAL)
                    return

            for s in signals:
                if s < 0.0 or s > 1.0:
                    self._block(_REASON_VAL)
                    return

            omega = sum(w * float(s) for w, s in zip(self._weights, signals))
            self._last_composite = omega

            veto_count = sum(1 for s in signals if float(s) >= self._veto_thresh)

            if omega >= self._crit_thresh:
                self._block(_REASON_BREACH)
            elif veto_count >= self._max_veto:
                self._block(_REASON_VETO)

    def _block(self, reason: str) -> None:
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason = reason

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            t = time.monotonic() if current_time is None else current_time
            return t < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: float) -> bool:
        return self.is_blocked(ts)

    def reset(self) -> None:
        with self._lock:
            self._last_composite = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def composite_score(self) -> float:
        with self._lock:
            return self._last_composite


def math_isclose_one(val: float) -> bool:
    return abs(val - 1.0) < 1e-6
