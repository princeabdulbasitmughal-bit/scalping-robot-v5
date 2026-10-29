"""
Wave 445 -- Apex Sovereign Canopy Synthesizer Guard
==================================================
The sovereign canopy synthesizer presiding over the complete quantitative architecture
of Waves 401 through 445. Synthesizes 8 high-order institutional microstructure vectors:
  1. Realized Kernel Noise Contamination Risk (Wave 441)
  2. Depth Recovery Half-Life Friction Risk (Wave 442)
  3. Cross-Asset Lead-Lag Propagation Delay Risk (Wave 443)
  4. Price Impact Decay Asymmetry Risk (Wave 444)
  5. Grand Jubilee Apex Canopy Fragility Risk (Wave 440)
  6. Orderbook Skew Decay Elasticity Risk (Wave 436)
  7. Volatility Drift Curvature Risk (Wave 437)
  8. Cross-Venue Arbitrage Divergence Risk (Wave 439)

Computes the normalized Apex Sovereign Canopy Fragility Index Omega in [0, 1].
Enforces multi-canopy defense across all high-frequency scalper execution engines
during systemic liquidity fracture, macro transmission shocks, and flash cascade dynamics.

Methodology
-----------
* Evaluates weighted composite score:
    Omega = (1/8) * sum_{i=1}^8 s_i
* Detects multi-vector convergence when count(s_i >= 0.70) >= convergence_count_threshold.
* If Omega >= critical_sovereign_threshold, blocks with APEX_SOVEREIGN_CANOPY_FRAGILITY_SPIKE.
* If multi-vector convergence fires, blocks with SOVEREIGN_CANOPY_MULTI_VECTOR_LOCKOUT.

Blocking reasons
----------------
APEX_SOVEREIGN_CANOPY_FRAGILITY_SPIKE -- composite sovereign canopy fragility index breached limit
SOVEREIGN_CANOPY_MULTI_VECTOR_LOCKOUT -- simultaneous multi-dimensional risk invariants tripped
INPUT_VALIDATION_ERROR                -- inputs outside [0, 1], non-numeric, or non-monotonic ts

Public API (standardised)
-------------------------
update(...)                    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
sovereign_score                -> float
"""

from __future__ import annotations

import threading
import time
from typing import Optional

__all__ = ["Wave445ApexSovereignCanopySynthesizerGuard"]

_REASON_FRAGILITY = "APEX_SOVEREIGN_CANOPY_FRAGILITY_SPIKE"
_REASON_LOCKOUT = "SOVEREIGN_CANOPY_MULTI_VECTOR_LOCKOUT"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave445ApexSovereignCanopySynthesizerGuard:
    """Apex Sovereign Canopy Synthesizer Guard."""

    def __init__(
        self,
        critical_sovereign_threshold: float = 0.65,
        convergence_count_threshold: int = 4,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if (
            not (0.20 <= critical_sovereign_threshold <= 0.95)
            or not (2 <= convergence_count_threshold <= 8)
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave445ApexSovereignCanopySynthesizerGuard")

        self._critical_threshold = float(critical_sovereign_threshold)
        self._convergence_threshold = int(convergence_count_threshold)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._sovereign_score: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def sovereign_score(self) -> float:
        with self._lock:
            return self._sovereign_score

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._sovereign_score = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(
        self,
        realized_kernel_noise_risk: float,
        depth_half_life_risk: float,
        lead_lag_propagation_risk: float,
        impact_decay_asymmetry_risk: float,
        apex_canopy_risk: float,
        orderbook_skew_risk: float,
        volatility_curvature_risk: float,
        cross_venue_divergence_risk: float,
        timestamp: float,
    ) -> None:
        with self._lock:
            signals = [
                realized_kernel_noise_risk,
                depth_half_life_risk,
                lead_lag_propagation_risk,
                impact_decay_asymmetry_risk,
                apex_canopy_risk,
                orderbook_skew_risk,
                volatility_curvature_risk,
                cross_venue_divergence_risk,
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
            self._sovereign_score = omega

            high_count = sum(1 for s in signals if s >= 0.70)

            if high_count >= self._convergence_threshold:
                self._block(_REASON_LOCKOUT, ts)
            elif omega >= self._critical_threshold:
                self._block(_REASON_FRAGILITY, ts)

            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
