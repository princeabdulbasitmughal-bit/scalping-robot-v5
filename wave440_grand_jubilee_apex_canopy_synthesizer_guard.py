"""
Wave 440 -- Grand Jubilee Apex Canopy Synthesizer Guard
======================================================
The apex sovereign synthesizer presiding over the complete quantitative architecture
of Waves 401 through 440. Synthesizes 8 high-order institutional microstructure vectors:
  1. Orderbook Level-2 Skew Decay Elasticity Risk (Wave 436)
  2. Non-Stationary Realized Volatility Drift Curvature Risk (Wave 437)
  3. Dynamic Liquidity Resiliency & Depth Recovery Failure Risk (Wave 438)
  4. Cross-Exchange Spread Arbitrage Divergence Risk (Wave 439)
  5. Zenith Imperial Canopy Fragility Risk (Wave 435)
  6. Mid-Price Hawkes Jump Excitation Risk (Wave 434)
  7. Asymmetric Trade Flow Arrival Intensity Risk (Wave 433)
  8. Multi-Horizon Volatility Risk Premium Risk (Wave 432)

Computes the normalized Grand Jubilee Apex Canopy Fragility Index Psi in [0, 1].
Enforces multi-canopy defense across all high-frequency scalper execution engines
during systemic liquidity fracture, volatility shockwaves, and flash cascades.

Methodology
-----------
* Evaluates weighted composite score:
    Psi = (1/8) * sum_{i=1}^8 s_i
* Detects multi-vector convergence when count(s_i >= 0.70) >= convergence_count_threshold.
* If Psi >= critical_apex_threshold, blocks with GRAND_JUBILEE_APEX_CANOPY_FRAGILITY_SPIKE.
* If multi-vector convergence fires, blocks with APEX_CANOPY_MULTI_VECTOR_LOCKOUT.

Blocking reasons
----------------
GRAND_JUBILEE_APEX_CANOPY_FRAGILITY_SPIKE -- composite apex canopy fragility index breached limit
APEX_CANOPY_MULTI_VECTOR_LOCKOUT          -- simultaneous multi-dimensional risk invariants tripped
INPUT_VALIDATION_ERROR                    -- inputs outside [0, 1], non-numeric, or non-monotonic ts

Public API (standardised)
-------------------------
update(...)                    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
apex_score                     -> float
"""

from __future__ import annotations

import threading
import time
from typing import Optional

__all__ = ["Wave440GrandJubileeApexCanopySynthesizerGuard"]

_REASON_FRAGILITY = "GRAND_JUBILEE_APEX_CANOPY_FRAGILITY_SPIKE"
_REASON_LOCKOUT = "APEX_CANOPY_MULTI_VECTOR_LOCKOUT"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave440GrandJubileeApexCanopySynthesizerGuard:
    """Grand Jubilee Apex Canopy Synthesizer Guard."""

    def __init__(
        self,
        critical_apex_threshold: float = 0.65,
        convergence_count_threshold: int = 4,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if (
            not (0.20 <= critical_apex_threshold <= 0.95)
            or not (2 <= convergence_count_threshold <= 8)
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave440GrandJubileeApexCanopySynthesizerGuard")

        self._critical_threshold = float(critical_apex_threshold)
        self._convergence_threshold = int(convergence_count_threshold)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._apex_score: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def apex_score(self) -> float:
        with self._lock:
            return self._apex_score

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._apex_score = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(
        self,
        orderbook_skew_risk: float,
        volatility_curvature_risk: float,
        depth_recovery_failure_risk: float,
        cross_venue_divergence_risk: float,
        zenith_canopy_risk: float,
        hawkes_jump_risk: float,
        trade_flow_asymmetry_risk: float,
        vrp_explosive_risk: float,
        timestamp: float,
    ) -> None:
        with self._lock:
            signals = [
                orderbook_skew_risk,
                volatility_curvature_risk,
                depth_recovery_failure_risk,
                cross_venue_divergence_risk,
                zenith_canopy_risk,
                hawkes_jump_risk,
                trade_flow_asymmetry_risk,
                vrp_explosive_risk,
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
            psi = sum(float(s) for s in signals) / 8.0
            self._apex_score = psi

            high_count = sum(1 for s in signals if s >= 0.70)

            if high_count >= self._convergence_threshold:
                self._block(_REASON_LOCKOUT, ts)
            elif psi >= self._critical_threshold:
                self._block(_REASON_FRAGILITY, ts)

            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
