"""
Wave 430 -- Grand Sovereign Zenith Synthesizer Guard
====================================================
The pinnacle sovereign synthesizer presiding over the complete quantitative
architecture of Waves 401 through 430. Synthesizes 8 high-order institutional
microstructure risk vectors:
  1. Flow-Induced Market Impact Decay Risk (Wave 426)
  2. Cross-Tier Depth Co-Movement Decoupling Risk (Wave 427)
  3. Price Drift Velocity & Parabolic Exhaustion Risk (Wave 428)
  4. Orderbook Queue Depletion Half-Life Risk (Wave 429)
  5. Imperial Invariant Composite Fragility Risk (Wave 425)
  6. Realized Quarticity & Tail Jump Risk (Wave 423)
  7. Spread Asymmetry & Defense Shading Risk (Wave 418)
  8. Trade Flow Clustered Dispersion Risk (Wave 417)

Computes the normalized Zenith Fragility Index Omega in [0, 1]. Enforces an
impenetrable multi-canopy defense across all high-frequency execution pipelines
during systemic market dislocations and liquidity collapse.

Methodology
-----------
* Evaluates weighted composite score:
    Omega = (1/8) * sum_{i=1}^8 r_i
* Detects multi-vector convergence when count(r_i >= 0.70) >= convergence_count_threshold.
* If Omega >= critical_zenith_threshold, blocks with ZENITH_SOVEREIGN_RISK_SPIKE.
* If multi-vector convergence fires, blocks with ZENITH_MULTI_VECTOR_CONVERGENCE_LOCKOUT.

Blocking reasons
----------------
ZENITH_SOVEREIGN_RISK_SPIKE               -- composite zenith fragility index breached limit
ZENITH_MULTI_VECTOR_CONVERGENCE_LOCKOUT   -- simultaneous multi-dimensional risk invariants tripped
INPUT_VALIDATION_ERROR                    -- inputs outside [0, 1], non-numeric, or non-monotonic ts

Public API (standardised)
-------------------------
update(...)                    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
zenith_score                   -> float
"""

from __future__ import annotations

import threading
import time
from typing import Optional

__all__ = ["Wave430GrandSovereignZenithSynthesizerGuard"]

_REASON_SPIKE = "ZENITH_SOVEREIGN_RISK_SPIKE"
_REASON_LOCKOUT = "ZENITH_MULTI_VECTOR_CONVERGENCE_LOCKOUT"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave430GrandSovereignZenithSynthesizerGuard:
    """Grand Sovereign Zenith Synthesizer Guard."""

    def __init__(
        self,
        critical_zenith_threshold: float = 0.65,
        convergence_count_threshold: int = 4,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if (
            not (0.20 <= critical_zenith_threshold <= 0.95)
            or not (2 <= convergence_count_threshold <= 8)
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave430GrandSovereignZenithSynthesizerGuard")

        self._critical_threshold = float(critical_zenith_threshold)
        self._convergence_threshold = int(convergence_count_threshold)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._zenith_score: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def zenith_score(self) -> float:
        with self._lock:
            return self._zenith_score

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._zenith_score = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(
        self,
        impact_decay_risk: float,
        cross_tier_decoupling_risk: float,
        drift_exhaustion_risk: float,
        queue_depletion_risk: float,
        imperial_fragility_risk: float,
        quarticity_jump_risk: float,
        spread_asymmetry_risk: float,
        trade_burst_risk: float,
        timestamp: float,
    ) -> None:
        with self._lock:
            signals = [
                impact_decay_risk,
                cross_tier_decoupling_risk,
                drift_exhaustion_risk,
                queue_depletion_risk,
                imperial_fragility_risk,
                quarticity_jump_risk,
                spread_asymmetry_risk,
                trade_burst_risk,
            ]
            if (
                any(not isinstance(s, (int, float)) or not (0.0 <= s <= 1.0) for s in signals)
                or not isinstance(timestamp, (int, float))
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if (isinstance(timestamp, (int, float)) and timestamp > 0) else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)
            omega = sum(float(s) for s in signals) / 8.0
            self._zenith_score = omega

            high_count = sum(1 for s in signals if s >= 0.70)

            if high_count >= self._convergence_threshold:
                self._block(_REASON_LOCKOUT, ts)
            elif omega >= self._critical_threshold:
                self._block(_REASON_SPIKE, ts)

            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
