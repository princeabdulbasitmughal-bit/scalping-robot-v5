"""
Wave 474: Apex Macro-Microstructure Canopy Synthesizer Guard
============================================================
Institutional Quantitative Mathematical Formulation:
Synthesizes institutional quantitative microstructure invariants and macro cross-asset
flow metrics across Waves 469 through 473 into a 5-dimensional Apex Sovereign Canopy.

The 5 Orthogonal Dimensions:
1. Event Horizon Depth Contraction (Wave 469):
   Phi_1 = min(1.0, max(0.0, (0.70 - R_H) / 0.50))   (weight w_1 = 0.20)
2. Order Book Depth Curvature Concavity (Wave 470):
   Phi_2 = min(1.0, max(0.0, -kappa / 2.50))           (weight w_2 = 0.20)
3. Replenishment Half-Life Relaxation (Wave 471):
   Phi_3 = min(1.0, max(0.0, (t_1/2 - 0.50) / 3.0))   (weight w_3 = 0.20)
4. Cross-Asset Flow Dispersion (Wave 472):
   Phi_4 = min(1.0, max(0.0, sigma_flow / 3.50))       (weight w_4 = 0.20)
5. Cross-Venue Queue Imbalance Divergence (Wave 473):
   Phi_5 = min(1.0, max(0.0, Delta_I / 1.60))          (weight w_5 = 0.20)

The Master Apex Composite Canopy Index Omega_{474}(t) is:
    Omega_{474}(t) = sum_{k=1}^5 w_k * Phi_k(t) in [0.0, 1.0]

Circuit Breakers:
1. Apex Macro-Microstructure Canopy Breach:
   Omega_{474}(t) > critical_canopy_threshold (default: > 0.65)
2. Dual Hazard Spike Trigger:
   Count(Phi_k >= dual_spike_threshold) >= 2 (default: >= 2 metrics at >= 0.85)

When triggered, the guard executes an unbreachable freeze on all order routing legs
across MT5 and OmniTrade, shielding the fund from compound liquidity failure.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave474ApexMacroMicrostructureCanopySynthesizerGuard:
    """
    Grand Apex Master Synthesizer unifying depth event horizon contraction,
    orderbook curvature, replenishment half-life, multi-asset flow dispersion,
    and cross-venue queue divergence into an unbreachable risk defense.
    """

    WEIGHTS = np.array([0.20, 0.20, 0.20, 0.20, 0.20], dtype=np.float64)

    def __init__(
        self,
        critical_canopy_threshold: float = 0.65,
        dual_spike_threshold: float = 0.85,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.40 <= critical_canopy_threshold <= 0.90):
            raise ValueError(f"critical_canopy_threshold must be in [0.40, 0.90], got {critical_canopy_threshold}")
        if not (0.70 <= dual_spike_threshold <= 0.98):
            raise ValueError(f"dual_spike_threshold must be in [0.70, 0.98], got {dual_spike_threshold}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.critical_canopy_threshold: float = critical_canopy_threshold
        self.dual_spike_threshold: float = dual_spike_threshold
        self.cooldown_sec: float = cooldown_sec

        # Telemetry metrics
        self.composite_canopy_index: float = 0.0
        self.sub_metrics: Dict[str, float] = {}
        self.spike_count: int = 0
        self.blocked_side: Optional[str] = None
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0
        self._last_timestamp: float = -1.0

    def update(
        self,
        event_horizon_ratio: float = 1.0,
        depth_curvature: float = 1.0,
        replenishment_halflife: float = 0.50,
        cross_asset_dispersion: float = 0.50,
        cross_venue_divergence: float = 0.20,
        timestamp: float = 0.0
    ) -> bool:
        """
        Record instantaneous inputs from Waves 469 through 473.
        Returns True if trading is blocked, False otherwise.
        """
        inputs = [
            event_horizon_ratio, depth_curvature, replenishment_halflife,
            cross_asset_dispersion, cross_venue_divergence
        ]
        for x in inputs:
            if not math.isfinite(x):
                raise ValueError("All inputs must be finite numbers")
        if event_horizon_ratio < 0.0 or replenishment_halflife < 0.0 or cross_asset_dispersion < 0.0 or cross_venue_divergence < 0.0:
            raise ValueError("Ratio, half-life, dispersion, and divergence inputs must be non-negative")
        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._last_timestamp >= 0.0 and timestamp <= self._last_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._last_timestamp}")

        self._last_timestamp = timestamp

        # Check cooldown from prior breach
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        # Compute normalized risk scores in [0.0, 1.0]
        phi_1 = min(1.0, max(0.0, (0.70 - event_horizon_ratio) / 0.50))
        phi_2 = min(1.0, max(0.0, -depth_curvature / 2.50))
        phi_3 = min(1.0, max(0.0, (replenishment_halflife - 0.50) / 3.0))
        phi_4 = min(1.0, max(0.0, cross_asset_dispersion / 3.50))
        phi_5 = min(1.0, max(0.0, cross_venue_divergence / 1.60))

        phi_arr = np.array([phi_1, phi_2, phi_3, phi_4, phi_5], dtype=np.float64)
        self.composite_canopy_index = float(np.dot(self.WEIGHTS, phi_arr))

        self.sub_metrics = {
            "event_horizon_risk": round(float(phi_1), 4),
            "depth_curvature_risk": round(float(phi_2), 4),
            "replenishment_decay_risk": round(float(phi_3), 4),
            "cross_asset_dispersion_risk": round(float(phi_4), 4),
            "cross_venue_divergence_risk": round(float(phi_5), 4)
        }

        self.spike_count = int(np.sum(phi_arr >= self.dual_spike_threshold))

        # Evaluate Circuit Breakers
        canopy_breached = (self.composite_canopy_index > self.critical_canopy_threshold)
        dual_spike_breached = (self.spike_count >= 2)

        if canopy_breached or dual_spike_breached:
            self._is_blocked = True
            self.blocked_side = "ALL"
            self._last_breach_time = timestamp

            trigger = "APEX_CANOPY_FRAGILITY_BREACH" if canopy_breached else "DUAL_HAZARD_SPIKE_BREACH"
            self._block_reason = (
                f"{trigger}: Omega={self.composite_canopy_index:.3f} > {self.critical_canopy_threshold:.3f} "
                f"(spikes={self.spike_count} >= 2, blocked: ALL)"
            )
        else:
            self._is_blocked = False
            self.blocked_side = None
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked."""
        return self._is_blocked

    def is_entry_blocked(self, side: str = "BUY") -> bool:
        """OmniTrade interface compatibility. Blocks all entries when active."""
        return self._is_blocked

    @property
    def block_reason(self) -> str:
        return self._block_reason

    def get_telemetry(self) -> Dict[str, Any]:
        """Telemetry metadata for institutional risk auditing."""
        return {
            "guard": "Wave474ApexMacroMicrostructureCanopySynthesizerGuard",
            "composite_canopy_index": round(self.composite_canopy_index, 4),
            "sub_metrics": self.sub_metrics,
            "spike_count": self.spike_count,
            "critical_canopy_threshold": self.critical_canopy_threshold,
            "dual_spike_threshold": self.dual_spike_threshold,
            "blocked_side": self.blocked_side,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason
        }

    def reset(self) -> None:
        """Reset internal state."""
        self.composite_canopy_index = 0.0
        self.sub_metrics.clear()
        self.spike_count = 0
        self.blocked_side = None
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
        self._last_timestamp = -1.0
