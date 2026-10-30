"""
Wave 455: Multi-Scale Microstructure Fragility Synthesizer Guard
================================================================
Institutional Quantitative Mathematical Formulation:
Wave 455 synthesizes the four foundational multi-scale and point-process microstructure
guards engineered across Waves 451 to 454:

Vector 1: Wavelet High-Frequency Energy Ratio (Wave 451)   - Weight: 0.25
Vector 2: Order Arrival Poisson Burstiness (Wave 452)     - Weight: 0.25
Vector 3: Orderbook Curvature Acceleration (Wave 453)     - Weight: 0.25
Vector 4: Volume-Synchronized Basis Divergence (Wave 454)  - Weight: 0.25

The composite multi-scale fragility index is:
    F_multiscale = 0.25 * Phi_wavelet + 0.25 * Phi_burst + 0.25 * Phi_curvature + 0.25 * Phi_divergence

Where each normalized component Phi_k in [0, 1].

Safety Invariants:
1. Linear Composite Breach: If F_multiscale >= critical_fragility_threshold (default: 0.65),
   trading is halted due to multi-scale microstructure degradation.
2. Dual-Vector Extreme Spike: If 2 or more vectors simultaneously exceed dual_spike_threshold
   (default: 0.85), an immediate hard sovereign lock is engaged even if the linear average is low.
"""

import math
from typing import Dict, Any, Optional


class Wave455MultiscaleFragilitySynthesizerGuard:
    """
    Synthesizes Wavelet Variance (W451), Poisson Burstiness (W452), Curvature Acceleration (W453),
    and Volume-Synchronized Divergence (W454) into a unified multi-scale risk circuit breaker.
    """

    WEIGHTS = {
        "wavelet_hf_energy": 0.25,
        "poisson_burstiness": 0.25,
        "curvature_acceleration": 0.25,
        "volume_divergence": 0.25,
    }

    def __init__(
        self,
        critical_fragility_threshold: float = 0.65,
        dual_spike_threshold: float = 0.85
    ) -> None:
        if not (0.30 <= critical_fragility_threshold <= 0.95):
            raise ValueError(f"critical_fragility_threshold must be in [0.30, 0.95], got {critical_fragility_threshold}")
        if not (0.50 <= dual_spike_threshold <= 0.99):
            raise ValueError(f"dual_spike_threshold must be in [0.50, 0.99], got {dual_spike_threshold}")

        self.critical_fragility_threshold: float = critical_fragility_threshold
        self.dual_spike_threshold: float = dual_spike_threshold

        # Normalized component states in [0, 1]
        self.vectors: Dict[str, float] = {k: 0.0 for k in self.WEIGHTS}
        self.composite_fragility: float = 0.0
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_timestamp: float = 0.0

    def update(
        self,
        wavelet_hf_energy: float,
        poisson_burstiness: float,
        curvature_acceleration: float,
        volume_divergence: float,
        timestamp: float
    ) -> bool:
        """
        Ingest normalized fragility components in [0, 1] and evaluate multi-scale circuit breaker.
        Returns True if trading is blocked, False otherwise.
        """
        raw = {
            "wavelet_hf_energy": wavelet_hf_energy,
            "poisson_burstiness": poisson_burstiness,
            "curvature_acceleration": curvature_acceleration,
            "volume_divergence": volume_divergence,
        }

        for k, v in raw.items():
            if v < 0.0 or not math.isfinite(v):
                raise ValueError(f"{k} must be non-negative and finite, got {v}")

        if self._last_timestamp > 0.0 and timestamp <= self._last_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._last_timestamp}")

        self._last_timestamp = timestamp
        self.vectors = {k: min(1.0, float(raw[k])) for k in self.WEIGHTS}

        # Calculate weighted composite
        self.composite_fragility = sum(self.vectors[k] * self.WEIGHTS[k] for k in self.WEIGHTS)

        # Count individual extreme spikes
        spikes = [k for k, v in self.vectors.items() if v >= self.dual_spike_threshold]

        # Evaluate safety invariants
        if self.composite_fragility >= self.critical_fragility_threshold:
            self._is_blocked = True
            self._block_reason = (
                f"MULTISCALE_FRAGILITY_COLLAPSE: Composite {self.composite_fragility:.4f} >= "
                f"threshold {self.critical_fragility_threshold:.4f}"
            )
        elif len(spikes) >= 2:
            self._is_blocked = True
            self._block_reason = (
                f"DUAL_VECTOR_EXTREME_CONVERGENCE: {len(spikes)} vectors breached extreme threshold "
                f"({', '.join(spikes)})"
            )
        else:
            self._is_blocked = False
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked by the Multi-Scale Fragility Synthesizer."""
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
            "guard": "Wave455MultiscaleFragilitySynthesizerGuard",
            "composite_fragility": round(self.composite_fragility, 5),
            "critical_threshold": self.critical_fragility_threshold,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason,
            "vectors": {k: round(v, 4) for k, v in self.vectors.items()}
        }

    def reset(self) -> None:
        """Reset internal state."""
        self.vectors = {k: 0.0 for k in self.WEIGHTS}
        self.composite_fragility = 0.0
        self._is_blocked = False
        self._block_reason = ""
        self._last_timestamp = 0.0
