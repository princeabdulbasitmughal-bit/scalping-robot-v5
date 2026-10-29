"""
Wave 450: Apex Sovereign Canopy Master Synthesizer Guard
========================================================
Institutional Quantitative Mathematical Formulation:
Wave 450 represents the ultimate milestone and sovereign apex of the entire
High-Frequency Scalping Risk Canopy (Waves 441 to 449). It synthesizes 9 orthogonal
microstructure risk dimensions into a single unified institutional fragility tensor:

Vector 1: Realized Kernel Volatility Jump (Wave 441)      - Weight: 0.12
Vector 2: Depth Recovery Half-Life (Wave 442)            - Weight: 0.11
Vector 3: Cross-Asset Lead-Lag Transfer (Wave 443)       - Weight: 0.10
Vector 4: Price Impact Decay Asymmetry (Wave 444)        - Weight: 0.11
Vector 5: Apex Sovereign Canopy Sub-Matrix (Wave 445)     - Weight: 0.12
Vector 6: Rough Volatility Hurst Exponent (Wave 446)     - Weight: 0.12
Vector 7: Queue Cancellation Intensity Hazard (Wave 447) - Weight: 0.10
Vector 8: Cross-Impact Propagator (Wave 448)             - Weight: 0.11
Vector 9: Liquidity Black Hole Horizon (Wave 449)        - Weight: 0.11

The composite institutional fragility score is:
    C_apex = sum_{k=1}^9 w_k * Phi_k

Where each normalized fragility metric Phi_k in [0, 1].

Safety Invariant:
1. Composite Fragility Breached: If C_apex >= critical_composite_threshold (default: 0.65),
   trading is immediately halted across all pairs.
2. Concurrent Multi-Vector Spike: If 3 or more individual risk vectors exceed 0.80
   simultaneously, a hard sovereign lock is engaged even if the linear composite is below 0.65.
"""

import math
from typing import Dict, Any, Optional


class Wave450ApexSovereignCanopyMasterSynthesizerGuard:
    """
    Master institutional risk synthesizer unifying all 9 Apex Canopy microstructural guards
    (Waves 441 to 449) into a single high-frequency execution circuit breaker.
    """

    WEIGHTS = {
        "kernel_jump": 0.12,
        "depth_half_life": 0.11,
        "lead_lag_transfer": 0.10,
        "impact_decay_asymmetry": 0.11,
        "canopy_submatrix": 0.12,
        "rough_hurst": 0.12,
        "queue_cancellation": 0.10,
        "cross_impact": 0.11,
        "black_hole_horizon": 0.11,
    }

    def __init__(
        self,
        critical_composite_threshold: float = 0.65,
        multi_vector_trigger_count: int = 3,
        vector_spike_threshold: float = 0.80
    ) -> None:
        if not (0.30 <= critical_composite_threshold <= 0.95):
            raise ValueError(f"critical_composite_threshold must be in [0.30, 0.95], got {critical_composite_threshold}")
        if multi_vector_trigger_count < 2 or multi_vector_trigger_count > 9:
            raise ValueError(f"multi_vector_trigger_count must be in [2, 9], got {multi_vector_trigger_count}")
        if not (0.50 <= vector_spike_threshold <= 0.99):
            raise ValueError(f"vector_spike_threshold must be in [0.50, 0.99], got {vector_spike_threshold}")

        self.critical_composite_threshold: float = critical_composite_threshold
        self.multi_vector_trigger_count: int = multi_vector_trigger_count
        self.vector_spike_threshold: float = vector_spike_threshold

        # Current vector state (all normalized to [0, 1])
        self.vectors: Dict[str, float] = {k: 0.0 for k in self.WEIGHTS}
        self.composite_score: float = 0.0
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_timestamp: float = 0.0

    def update(
        self,
        kernel_jump: float,
        depth_half_life: float,
        lead_lag_transfer: float,
        impact_decay_asymmetry: float,
        canopy_submatrix: float,
        rough_hurst: float,
        queue_cancellation: float,
        cross_impact: float,
        black_hole_horizon: float,
        timestamp: float
    ) -> bool:
        """
        Ingest all 9 normalized fragility indicators in [0, 1] and evaluate master lockout.
        Returns True if trading is blocked, False otherwise.
        """
        raw_inputs = {
            "kernel_jump": kernel_jump,
            "depth_half_life": depth_half_life,
            "lead_lag_transfer": lead_lag_transfer,
            "impact_decay_asymmetry": impact_decay_asymmetry,
            "canopy_submatrix": canopy_submatrix,
            "rough_hurst": rough_hurst,
            "queue_cancellation": queue_cancellation,
            "cross_impact": cross_impact,
            "black_hole_horizon": black_hole_horizon,
        }

        for name, val in raw_inputs.items():
            if val < 0.0 or not math.isfinite(val):
                raise ValueError(f"{name} must be non-negative and finite, got {val}")

        if self._last_timestamp > 0.0 and timestamp <= self._last_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._last_timestamp}")

        self._last_timestamp = timestamp

        # Clamp all vectors to [0, 1]
        self.vectors = {k: min(1.0, float(raw_inputs[k])) for k in self.WEIGHTS}

        # Calculate composite score
        self.composite_score = sum(self.vectors[k] * self.WEIGHTS[k] for k in self.WEIGHTS)

        # Count individual vector spikes
        spikes = [k for k, v in self.vectors.items() if v >= self.vector_spike_threshold]

        # Evaluate safety invariants
        if self.composite_score >= self.critical_composite_threshold:
            self._is_blocked = True
            self._block_reason = (
                f"APEX_SOVEREIGN_CANOPY_COLLAPSE: Composite fragility {self.composite_score:.4f} >= "
                f"threshold {self.critical_composite_threshold:.4f}"
            )
        elif len(spikes) >= self.multi_vector_trigger_count:
            self._is_blocked = True
            self._block_reason = (
                f"MULTI_VECTOR_CONVERGENCE_BURST: {len(spikes)} vectors breached spike threshold "
                f"({', '.join(spikes)})"
            )
        else:
            self._is_blocked = False
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked by the Master Synthesizer Guard."""
        return self._is_blocked

    def is_entry_blocked(self, side: str = "BUY") -> bool:
        """OmniTrade interface compatibility."""
        return self._is_blocked

    @property
    def block_reason(self) -> str:
        return self._block_reason

    def get_telemetry(self) -> Dict[str, Any]:
        """Telemetry metadata for institutional risk auditing."""
        return {
            "guard": "Wave450ApexSovereignCanopyMasterSynthesizerGuard",
            "composite_fragility_score": round(self.composite_score, 5),
            "critical_threshold": self.critical_composite_threshold,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason,
            "vectors": {k: round(v, 4) for k, v in self.vectors.items()},
            "canopy_milestone": "Wave 450 Grand Apex Complete (Waves 441-449 Fully Integrated)"
        }

    def reset(self) -> None:
        """Reset internal state."""
        self.vectors = {k: 0.0 for k in self.WEIGHTS}
        self.composite_score = 0.0
        self._is_blocked = False
        self._block_reason = ""
        self._last_timestamp = 0.0
