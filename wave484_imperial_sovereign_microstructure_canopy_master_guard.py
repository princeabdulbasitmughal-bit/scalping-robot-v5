"""
Wave 484: Imperial Sovereign Microstructure Canopy Master Guard
===============================================================
Institutional Quantitative Mathematical Formulation:
Imperial Sovereign Apex Synthesizer integrating recent high-order microstructure
risk and order book elasticity dynamics (Waves 479 - 483) into an unbreachable 5-pillar canopy:

The 5 Orthogonal High-Frequency Risk Pillars (20.0% weight each):
1. Volume-Synchronized Flow Toxicity & VPIN (Wave 479):
   Phi_1 = min(1.0, max(0.0, vpin / 0.70))                                (weight w_1 = 0.20)
2. Grand Jubilee 8-Dimensional Sovereign Risk (Wave 480):
   Phi_2 = min(1.0, max(0.0, omega_480 / 0.65))                           (weight w_2 = 0.20)
3. Hawkes Cross-Excitation Branching Spectral Radius (Wave 481):
   Phi_3 = min(1.0, max(0.0, hawkes_spectral_radius / 0.88))              (weight w_3 = 0.20)
4. Microstructure 3D Resilience Fragility Tensor (Wave 482):
   Phi_4 = min(1.0, max(0.0, resilience_fragility / 0.70))                (weight w_4 = 0.20)
5. Multi-Level Order Book Skewness Elasticity (Wave 483):
   Phi_5 = min(1.0, max(0.0, abs(xi_skew) / 0.75))                        (weight w_5 = 0.20)

The Master Canopy Composite Hazard Index Omega_{484}(t) is:
    Omega_{484}(t) = sum_{k=1}^5 w_k * Phi_k(t) in [0.0, 1.0]

Circuit Breakers:
1. Imperial Sovereign Microstructure Canopy Breach:
   Omega_{484}(t) >= critical_canopy_threshold (default: >= 0.65) -> HALT_ALL
2. Dual Hazard Spike Trigger:
   Count(Phi_k >= dual_spike_threshold) >= 2 (default: >= 2 metrics at >= 0.85) -> HALT_ALL
3. Asymmetric Directional Toxicity Override:
   - When Hawkes runaway buy (eta_buy >= 0.85) or severe bid hollowing (xi_skew >= 0.70): BLOCK_BUY
   - When Hawkes runaway sell (eta_sell >= 0.85) or severe ask hollowing (xi_skew <= -0.70): BLOCK_SELL
"""

import math
import time
import numpy as np
from typing import List, Dict, Any, Optional


class Wave484ImperialSovereignMicrostructureCanopyMasterGuard:
    """
    Apex Imperial Sovereign Microstructure Canopy Master Synthesizer consolidating
    5 orthogonal frontiers of ultra-high-frequency risk into an impregnable defense canopy.
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

        # State tracking
        self.breaker_active: bool = False
        self.breaker_tripped_at: float = 0.0
        self.last_trip_reason: str = "NONE"

    def reset(self) -> None:
        """Reset temporal canopy state."""
        self.breaker_active = False
        self.breaker_tripped_at = 0.0
        self.last_trip_reason = "NONE"

    def evaluate(
        self,
        vpin: float,
        omega_480: float,
        hawkes_spectral_radius: float,
        resilience_fragility: float,
        xi_skew: float,
        hawkes_eta_buy: float = 0.0,
        hawkes_eta_sell: float = 0.0,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Synthesize the 5 high-frequency microstructure pillars into the apex canopy hazard index.
        """
        now = time.time() if timestamp is None else float(timestamp)

        # Input validations
        if not (0.0 <= vpin <= 1.0):
            raise ValueError(f"vpin must be in [0.0, 1.0], got {vpin}")
        if not (0.0 <= omega_480 <= 1.0):
            raise ValueError(f"omega_480 must be in [0.0, 1.0], got {omega_480}")
        if not (0.0 <= hawkes_spectral_radius <= 2.0):
            raise ValueError(f"hawkes_spectral_radius must be in [0.0, 2.0], got {hawkes_spectral_radius}")
        if not (0.0 <= resilience_fragility <= 1.0):
            raise ValueError(f"resilience_fragility must be in [0.0, 1.0], got {resilience_fragility}")
        if not (-1.0 <= xi_skew <= 1.0):
            raise ValueError(f"xi_skew must be in [-1.0, 1.0], got {xi_skew}")

        # Check existing cooldown
        if self.breaker_active:
            elapsed = now - self.breaker_tripped_at
            if elapsed < self.cooldown_sec:
                return {
                    "action": "HALT_ALL",
                    "circuit_breaker": True,
                    "reason": f"COOLDOWN_ACTIVE: {self.last_trip_reason} ({elapsed:.2f}s < {self.cooldown_sec}s)",
                    "omega_canopy": 1.0,
                    "pillar_hazards": [],
                    "spikes_count": 0
                }
            else:
                self.breaker_active = False
                self.last_trip_reason = "NONE"

        # Calculate normalized hazards Phi_k in [0.0, 1.0]
        phi_1 = min(1.0, max(0.0, vpin / 0.70))
        phi_2 = min(1.0, max(0.0, omega_480 / 0.65))
        phi_3 = min(1.0, max(0.0, hawkes_spectral_radius / 0.88))
        phi_4 = min(1.0, max(0.0, resilience_fragility / 0.70))
        phi_5 = min(1.0, max(0.0, abs(xi_skew) / 0.75))

        pillar_hazards = [phi_1, phi_2, phi_3, phi_4, phi_5]
        omega_canopy = float(np.dot(self.WEIGHTS, pillar_hazards))

        # Check for dual hazard spikes
        spikes_count = sum(1 for p in pillar_hazards if p >= self.dual_spike_threshold)

        # 1. Apex Sovereign Canopy Breach
        if omega_canopy >= self.critical_canopy_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"IMPERIAL_CANOPY_BREACH: Omega_{484}={omega_canopy:.3f} >= {self.critical_canopy_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "omega_canopy": omega_canopy,
                "pillar_hazards": pillar_hazards,
                "spikes_count": spikes_count
            }

        # 2. Dual Spike Trigger
        if spikes_count >= 2:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"DUAL_HAZARD_SPIKE: {spikes_count} pillars >= {self.dual_spike_threshold:.2f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "omega_canopy": omega_canopy,
                "pillar_hazards": pillar_hazards,
                "spikes_count": spikes_count
            }

        # 3. Asymmetric Directional Toxicity Overrides
        buy_toxic = (hawkes_eta_buy >= 0.85) or (xi_skew >= 0.70)
        sell_toxic = (hawkes_eta_sell >= 0.85) or (xi_skew <= -0.70)

        if buy_toxic and sell_toxic:
            return {
                "action": "HALT_ALL",
                "circuit_breaker": False,
                "reason": "BILATERAL_DIRECTIONAL_TOXICITY",
                "omega_canopy": omega_canopy,
                "pillar_hazards": pillar_hazards,
                "spikes_count": spikes_count
            }

        if buy_toxic:
            return {
                "action": "BLOCK_BUY",
                "circuit_breaker": False,
                "reason": f"BUY_SIDE_TOXICITY (eta_buy={hawkes_eta_buy:.2f}, xi_skew={xi_skew:.2f})",
                "omega_canopy": omega_canopy,
                "pillar_hazards": pillar_hazards,
                "spikes_count": spikes_count
            }

        if sell_toxic:
            return {
                "action": "BLOCK_SELL",
                "circuit_breaker": False,
                "reason": f"SELL_SIDE_TOXICITY (eta_sell={hawkes_eta_sell:.2f}, xi_skew={xi_skew:.2f})",
                "omega_canopy": omega_canopy,
                "pillar_hazards": pillar_hazards,
                "spikes_count": spikes_count
            }

        return {
            "action": "ALLOW_ALL",
            "circuit_breaker": False,
            "reason": "ALL_PILLARS_STABLE_EQUILIBRIUM",
            "omega_canopy": omega_canopy,
            "pillar_hazards": pillar_hazards,
            "spikes_count": spikes_count
        }
