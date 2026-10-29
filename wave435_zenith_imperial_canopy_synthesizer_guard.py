"""
Wave 435 -- Zenith Imperial Canopy Synthesizer Guard
====================================================
The supreme sovereign synthesizer presiding over the complete quantitative architecture
of Waves 401 through 435. Synthesizes 8 high-order institutional microstructure vectors:
  1. Replenishment Acceleration Decay Risk (Wave 431)
  2. Multi-Horizon Volatility Risk Premium Risk (Wave 432)
  3. Asymmetric Trade Flow Arrival Imbalance (Wave 433)
  4. Hawkes Jump Avalanche Excitation Risk (Wave 434)
  5. Zenith Composite Fragility Risk (Wave 430)
  6. Queue Depletion Half-Life Risk (Wave 429)
  7. Price Drift Velocity Exhaustion Risk (Wave 428)
  8. Cross-Tier Depth Beta Decoupling Risk (Wave 427)

Computes the normalized Zenith Imperial Canopy Fragility Index Xi in [0, 1].
Enforces multi-canopy defense across all high-frequency scalper execution engines
during systemic liquidity fracture and flash cascade dynamics.

Methodology
-----------
* Evaluates weighted composite score:
    Xi = (1/8) * sum_{i=1}^8 s_i
* Detects multi-vector convergence when count(s_i >= 0.70) >= convergence_count_threshold.
* If Xi >= critical_canopy_threshold, blocks with ZENITH_IMPERIAL_CANOPY_FRAGILITY_SPIKE.
* If multi-vector convergence fires, blocks with CANOPY_MULTI_VECTOR_CONVERGENCE_LOCKOUT.

Blocking reasons
----------------
ZENITH_IMPERIAL_CANOPY_FRAGILITY_SPIKE    -- composite canopy fragility index breached limit
CANOPY_MULTI_VECTOR_CONVERGENCE_LOCKOUT   -- simultaneous multi-dimensional risk invariants tripped
INPUT_VALIDATION_ERROR                    -- inputs outside [0, 1], non-numeric, or non-monotonic ts

Public API (standardised)
-------------------------
update(...)                    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
canopy_score                   -> float
"""

from __future__ import annotations

import threading
import time
from typing import Optional

__all__ = ["Wave435ZenithImperialCanopySynthesizerGuard"]

_REASON_FRAGILITY = "ZENITH_IMPERIAL_CANOPY_FRAGILITY_SPIKE"
_REASON_LOCKOUT = "CANOPY_MULTI_VECTOR_CONVERGENCE_LOCKOUT"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave435ZenithImperialCanopySynthesizerGuard:
    """Zenith Imperial Canopy Synthesizer Guard."""

    def __init__(
        self,
        critical_canopy_threshold: float = 0.65,
        convergence_count_threshold: int = 4,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if (
            not (0.20 <= critical_canopy_threshold <= 0.95)
            or not (2 <= convergence_count_threshold <= 8)
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave435ZenithImperialCanopySynthesizerGuard")

        self._critical_threshold = float(critical_canopy_threshold)
        self._convergence_threshold = int(convergence_count_threshold)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._canopy_score: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def canopy_score(self) -> float:
        with self._lock:
            return self._canopy_score

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._canopy_score = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(
        self,
        replenishment_accel_risk: float,
        vrp_jump_risk: float,
        arrival_asymmetry_risk: float,
        hawkes_jump_risk: float,
        zenith_fragility_risk: float,
        queue_depletion_risk: float,
        drift_exhaustion_risk: float,
        cross_tier_beta_risk: float,
        timestamp: float,
    ) -> None:
        with self._lock:
            signals = [
                replenishment_accel_risk,
                vrp_jump_risk,
                arrival_asymmetry_risk,
                hawkes_jump_risk,
                zenith_fragility_risk,
                queue_depletion_risk,
                drift_exhaustion_risk,
                cross_tier_beta_risk,
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
            xi = sum(float(s) for s in signals) / 8.0
            self._canopy_score = xi

            high_count = sum(1 for s in signals if s >= 0.70)

            if high_count >= self._convergence_threshold:
                self._block(_REASON_LOCKOUT, ts)
            elif xi >= self._critical_threshold:
                self._block(_REASON_FRAGILITY, ts)

            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
