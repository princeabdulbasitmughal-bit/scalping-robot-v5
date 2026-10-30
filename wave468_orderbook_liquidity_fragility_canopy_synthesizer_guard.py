"""
Wave 468: Grand Jubilee Apex Sovereign Canopy Master Synthesizer Guard
======================================================================
Institutional Quantitative Mathematical Formulation:
Synthesizes institutional microstructure invariants and hazard metrics across
Waves 461 through 467 into a unified 7-dimensional Sovereign Microstructure Canopy.

The 7 Orthogonal Risk Dimensions:
1. Shannon-Rényi Entropy Loss: E_H = 1.0 - H_norm (Wave 461, weight w_1 = 0.15)
2. Execution Latency Jitter Risk: J_L = min(1.0, CV_L / 1.50) (Wave 462, weight w_2 = 0.15)
3. Fourier HFT Spectral Pulse: P_spec = min(1.0, Pi_max / 5.0) (Wave 463, weight w_3 = 0.15)
4. Volumetric Liquidity Drain: D_vol = min(1.0, D_drain / 2.50) (Wave 464, weight w_4 = 0.15)
5. Queue Imbalance Asymmetry: I_queue = abs(I_t) (Wave 465, weight w_5 = 0.15)
6. Dynamic Spread Expansion: S_mult = min(1.0, max(0.0, R_spread - 1.0) / 2.0) (Wave 466, weight w_6 = 0.15)
7. Cross-Asset Spillover Pressure: Psi_cross = min(1.0, abs(Psi) / 3.0) (Wave 467, weight w_7 = 0.10)

The Master Composite Canopy Fragility Index Omega(t) is:
    Omega(t) = sum_{k=1}^7 w_k * Phi_k(t)   in [0.0, 1.0]

Circuit Breaker Triggers:
1. Apex Sovereign Canopy Breach:
   Omega(t) > critical_canopy_threshold (default: > 0.65)
2. Dual Microstructure Hazard Spike:
   Count(Phi_k >= dual_spike_threshold) >= 2 (default: >= 2 metrics at >= 0.85)

When the Sovereign Canopy breaches safety thresholds, the guard freezes all order routing
and trading legs across MT5 and OmniTrade, ensuring bulletproof capital preservation.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave468OrderbookLiquidityFragilityCanopySynthesizerGuard:
    """
    Grand Jubilee Master Synthesizer unifying order flow entropy, latency jitter,
    Fourier spectral pulses, drain velocity, queue imbalance, spread expansion,
    and cross-asset flow spillovers into an unbreachable sovereign risk canopy.
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
        self.blocked_side: Optional[str] = None
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0
        self._last_timestamp: float = -1.0

    def update(
        self,
        entropy_loss: float = 0.0,
        latency_jitter_risk: float = 0.0,
        spectral_pulse_risk: float = 0.0,
        drain_velocity_risk: float = 0.0,
        queue_imbalance_risk: float = 0.0,
        spread_expansion_risk: float = 0.0,
        cross_asset_spillover_risk: float = 0.0,
        timestamp: float = 0.0
    ) -> bool:
        """
        Record instantaneous sub-metric risk scores across all 7 dimensions.
        Returns True if trading is blocked, False otherwise.
        """
        metrics = [
            entropy_loss, latency_jitter_risk, spectral_pulse_risk,
            drain_velocity_risk, queue_imbalance_risk, spread_expansion_risk,
            cross_asset_spillover_risk
        ]

        for m in metrics:
            if not math.isfinite(m) or m < 0.0:
                raise ValueError("All risk inputs must be non-negative and finite")

        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._last_timestamp >= 0.0 and timestamp <= self._last_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._last_timestamp}")

        self._last_timestamp = timestamp

        # Check cooldown
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        bounded_metrics = np.clip(np.array(metrics, dtype=np.float64), 0.0, 1.0)
        self.composite_canopy_index = float(np.dot(self.WEIGHTS, bounded_metrics))

        self.sub_metrics = {
            "entropy_loss": round(float(bounded_metrics[0]), 4),
            "latency_jitter": round(float(bounded_metrics[1]), 4),
            "spectral_pulse": round(float(bounded_metrics[2]), 4),
            "drain_velocity": round(float(bounded_metrics[3]), 4),
            "queue_imbalance": round(float(bounded_metrics[4]), 4),
            "spread_expansion": round(float(bounded_metrics[5]), 4),
            "cross_asset_spillover": round(float(bounded_metrics[6]), 4),
        }

        # Evaluate Circuit Breakers
        canopy_breached = (self.composite_canopy_index > self.critical_canopy_threshold)
        spike_count = int(np.sum(bounded_metrics >= self.dual_spike_threshold))
        dual_spike_breached = (spike_count >= 2)

        if canopy_breached or dual_spike_breached:
            self._is_blocked = True
            self.blocked_side = "ALL"
            self._last_breach_time = timestamp

            trigger = "APEX_SOVEREIGN_CANOPY_BREACH" if canopy_breached else "DUAL_MICROSTRUCTURE_HAZARD_SPIKE"
            self._block_reason = (
                f"{trigger}: Omega={self.composite_canopy_index:.3f} > {self.critical_canopy_threshold:.3f} "
                f"(spikes={spike_count} >= 2, blocked: ALL)"
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
            "guard": "Wave468OrderbookLiquidityFragilityCanopySynthesizerGuard",
            "composite_canopy_index": round(self.composite_canopy_index, 4),
            "sub_metrics": self.sub_metrics,
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
        self.blocked_side = None
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
        self._last_timestamp = -1.0
