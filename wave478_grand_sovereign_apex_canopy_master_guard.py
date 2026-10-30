"""
Wave 478: Grand Sovereign Apex Canopy Master Guard
==================================================
Institutional Quantitative Mathematical Formulation:
Synthesizes the 7 quantitative microstructure and macro-econometric hazard invariants
developed across Waves 471 through 477 into the Grand Sovereign Apex Risk Canopy:

The 7 Orthogonal Dimensions:
1. Replenishment Half-Life Decay (Wave 471):
   Phi_1 = min(1.0, max(0.0, (t_1/2 - 0.50) / 3.0))               (weight w_1 = 0.15)
2. Cross-Asset Flow Dispersion (Wave 472):
   Phi_2 = min(1.0, max(0.0, sigma_disp / 3.50))                   (weight w_2 = 0.15)
3. Cross-Venue Queue Divergence (Wave 473):
   Phi_3 = min(1.0, max(0.0, Delta_I / 1.60))                      (weight w_3 = 0.15)
4. Macro-Microstructure Synthesis (Wave 474):
   Phi_4 = min(1.0, max(0.0, Omega_474))                           (weight w_4 = 0.15)
5. Queue Cancellation Velocity (Wave 475):
   Phi_5 = min(1.0, max(0.0, v_cancel / 3.00))                     (weight w_5 = 0.15)
6. Markov Flow Entropy Collapse (Wave 476):
   Phi_6 = min(1.0, max(0.0, (0.85 - H_markov) / 0.50))           (weight w_6 = 0.15)
7. Cross-Asset Granger Causality (Wave 477):
   Phi_7 = min(1.0, max(0.0, Gamma_cross / 0.50))                  (weight w_7 = 0.10)

The Grand Apex Master Composite Index Omega_{478}(t) is:
    Omega_{478}(t) = sum_{k=1}^7 w_k * Phi_k(t) in [0.0, 1.0]

Circuit Breakers:
1. Grand Sovereign Apex Canopy Breach:
   Omega_{478}(t) > critical_canopy_threshold (default: > 0.65)
2. Dual Hazard Spike Trigger:
   Count(Phi_k >= dual_spike_threshold) >= 2 (default: >= 2 metrics at >= 0.85)

When triggered, the guard freezes all order routing across MT5 and OmniTrade,
ensuring capital protection against compound multi-dimensional market shocks.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave478GrandSovereignApexCanopyMasterGuard:
    """
    Grand Sovereign Apex Master Synthesizer consolidating replenishment decay,
    flow dispersion, venue divergence, canopy synthesis, cancellation velocity,
    Markov flow entropy, and Granger causality into an unbreachable risk canopy.
    """

    WEIGHTS = np.array([0.15, 0.15, 0.15, 0.15, 0.15, 0.15, 0.10], dtype=np.float64)

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

        # State telemetry
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
        replenishment_halflife: float = 0.50,
        cross_asset_dispersion: float = 0.50,
        cross_venue_divergence: float = 0.20,
        macro_canopy_omega: float = 0.10,
        cancellation_velocity: float = 0.20,
        markov_entropy: float = 0.85,
        granger_intensity: float = 0.05,
        timestamp: float = 0.0
    ) -> bool:
        """
        Record instantaneous metrics from Waves 471 through 477.
        Returns True if trading is blocked, False otherwise.
        """
        inputs = [
            replenishment_halflife, cross_asset_dispersion, cross_venue_divergence,
            macro_canopy_omega, cancellation_velocity, markov_entropy, granger_intensity
        ]
        for x in inputs:
            if not math.isfinite(x):
                raise ValueError("All inputs must be finite numbers")
            if x < 0.0:
                raise ValueError("All inputs must be non-negative")
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
        phi_1 = min(1.0, max(0.0, (replenishment_halflife - 0.50) / 3.0))
        phi_2 = min(1.0, max(0.0, cross_asset_dispersion / 3.50))
        phi_3 = min(1.0, max(0.0, cross_venue_divergence / 1.60))
        phi_4 = min(1.0, max(0.0, macro_canopy_omega))
        phi_5 = min(1.0, max(0.0, cancellation_velocity / 3.00))
        phi_6 = min(1.0, max(0.0, (0.85 - markov_entropy) / 0.50))
        phi_7 = min(1.0, max(0.0, granger_intensity / 0.50))

        phi_arr = np.array([phi_1, phi_2, phi_3, phi_4, phi_5, phi_6, phi_7], dtype=np.float64)
        self.composite_canopy_index = float(np.dot(self.WEIGHTS, phi_arr))

        self.sub_metrics = {
            "replenishment_decay_risk": round(float(phi_1), 4),
            "cross_asset_dispersion_risk": round(float(phi_2), 4),
            "cross_venue_divergence_risk": round(float(phi_3), 4),
            "macro_canopy_risk": round(float(phi_4), 4),
            "cancellation_velocity_risk": round(float(phi_5), 4),
            "markov_entropy_risk": round(float(phi_6), 4),
            "granger_causality_risk": round(float(phi_7), 4)
        }

        self.spike_count = int(np.sum(phi_arr >= self.dual_spike_threshold))

        # Evaluate Circuit Breakers
        canopy_breached = (self.composite_canopy_index > self.critical_canopy_threshold)
        dual_spike_breached = (self.spike_count >= 2)

        if canopy_breached or dual_spike_breached:
            self._is_blocked = True
            self.blocked_side = "ALL"
            self._last_breach_time = timestamp

            trigger = "GRAND_SOVEREIGN_CANOPY_BREACH" if canopy_breached else "DUAL_HAZARD_SPIKE_BREACH"
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
            "guard": "Wave478GrandSovereignApexCanopyMasterGuard",
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
