"""
Wave 488: Imperial Millennium Apex Microstructure Sovereign Master Guard
========================================================================
Institutional Quantitative Mathematical Formulation:
Imperial Millennium Apex Sovereign Master Synthesizer consolidating the full 7-dimensional
spectrum of high-frequency market microstructure risk, order book elasticity, non-linear impact,
and Kyle Lambda adverse selection (Waves 481 - 487) into an unassailable sovereign canopy:

The 7 Orthogonal Risk Pillars (14.29% equal weight each):
1. Hawkes Branching Spectral Radius (Wave 481):
   Phi_1 = min(1.0, max(0.0, hawkes_spectral_radius / 0.88))                  (w_1 = 1/7)
2. 3D Order Book Resilience Fragility (Wave 482):
   Phi_2 = min(1.0, max(0.0, resilience_fragility / 0.70))                    (w_2 = 1/7)
3. Order Book Depth Skewness Elasticity (Wave 483):
   Phi_3 = min(1.0, max(0.0, abs(xi_skew) / 0.75))                            (w_3 = 1/7)
4. Apex Sovereign Canopy Baseline (Wave 484):
   Phi_4 = min(1.0, max(0.0, omega_484 / 0.65))                               (w_4 = 1/7)
5. Non-Linear Market Impact Fragility (Wave 485):
   Phi_5 = min(1.0, max(0.0, psi_impact / 0.70))                              (w_5 = 1/7)
6. Grand Jubilee Canopy Master Synthesis (Wave 486):
   Phi_6 = min(1.0, max(0.0, omega_486 / 0.65))                               (w_6 = 1/7)
7. Kyle Lambda Adverse Selection Information Share (Wave 487):
   Phi_7 = min(1.0, max(0.0, s_info / 0.75))                                  (w_7 = 1/7)

The Master Imperial Millennium Canopy Hazard Index Omega_{488}(t) is:
    Omega_{488}(t) = sum_{k=1}^7 w_k * Phi_k(t) in [0.0, 1.0]

Circuit Breakers:
1. Apex Millennium Canopy Breach:
   Omega_{488}(t) >= critical_canopy_threshold (default: >= 0.65) -> HALT_ALL
2. Dual Hazard Spike Trigger:
   Count(Phi_k >= dual_spike_threshold) >= 2 (default: >= 2 metrics at >= 0.85) -> HALT_ALL
3. Asymmetric Directional Toxicity Override:
   - When buy-side toxic (lambda_skew >= 0.65 or alpha_buy >= 0.75 or xi_skew >= 0.70 or eta_buy >= 0.85): BLOCK_BUY
   - When sell-side toxic (lambda_skew <= -0.65 or alpha_sell >= 0.75 or xi_skew <= -0.70 or eta_sell >= 0.85): BLOCK_SELL
"""

import math
import time
import numpy as np
from typing import List, Dict, Any, Optional


class Wave488ImperialMillenniumApexMicrostructureMasterGuard:
    """
    Apex Imperial Millennium Microstructure Master Synthesizer consolidating
    7 orthogonal frontiers of quantitative risk into an unbreachable defense canopy.
    """

    WEIGHTS = np.full(7, 1.0 / 7.0, dtype=np.float64)

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
        """Reset temporal state."""
        self.breaker_active = False
        self.breaker_tripped_at = 0.0
        self.last_trip_reason = "NONE"

    def evaluate(
        self,
        hawkes_spectral_radius: float,
        resilience_fragility: float,
        xi_skew: float,
        omega_484: float,
        psi_impact: float,
        omega_486: float,
        s_info: float,
        lambda_skew: float = 0.0,
        alpha_buy: float = 0.50,
        alpha_sell: float = 0.50,
        hawkes_eta_buy: float = 0.0,
        hawkes_eta_sell: float = 0.0,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Synthesize the 7 microstructure pillars into the apex Millennium canopy hazard index.
        """
        now = time.time() if timestamp is None else float(timestamp)

        # Input range validations
        if not (0.0 <= hawkes_spectral_radius <= 2.0):
            raise ValueError(f"hawkes_spectral_radius must be in [0.0, 2.0], got {hawkes_spectral_radius}")
        if not (0.0 <= resilience_fragility <= 1.0):
            raise ValueError(f"resilience_fragility must be in [0.0, 1.0], got {resilience_fragility}")
        if not (-1.0 <= xi_skew <= 1.0):
            raise ValueError(f"xi_skew must be in [-1.0, 1.0], got {xi_skew}")
        if not (0.0 <= omega_484 <= 1.0):
            raise ValueError(f"omega_484 must be in [0.0, 1.0], got {omega_484}")
        if not (0.0 <= psi_impact <= 1.0):
            raise ValueError(f"psi_impact must be in [0.0, 1.0], got {psi_impact}")
        if not (0.0 <= omega_486 <= 1.0):
            raise ValueError(f"omega_486 must be in [0.0, 1.0], got {omega_486}")
        if not (0.0 <= s_info <= 1.0):
            raise ValueError(f"s_info must be in [0.0, 1.0], got {s_info}")
        if not (-1.0 <= lambda_skew <= 1.0):
            raise ValueError(f"lambda_skew must be in [-1.0, 1.0], got {lambda_skew}")

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
        phi_1 = min(1.0, max(0.0, hawkes_spectral_radius / 0.88))
        phi_2 = min(1.0, max(0.0, resilience_fragility / 0.70))
        phi_3 = min(1.0, max(0.0, abs(xi_skew) / 0.75))
        phi_4 = min(1.0, max(0.0, omega_484 / 0.65))
        phi_5 = min(1.0, max(0.0, psi_impact / 0.70))
        phi_6 = min(1.0, max(0.0, omega_486 / 0.65))
        phi_7 = min(1.0, max(0.0, s_info / 0.75))

        pillar_hazards = [phi_1, phi_2, phi_3, phi_4, phi_5, phi_6, phi_7]
        omega_canopy = float(np.dot(self.WEIGHTS, pillar_hazards))

        # Check dual hazard spikes
        spikes_count = sum(1 for p in pillar_hazards if p >= self.dual_spike_threshold)

        # 1. Apex Sovereign Canopy Breach
        if omega_canopy >= self.critical_canopy_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"IMPERIAL_MILLENNIUM_BREACH: Omega_{488}={omega_canopy:.3f} >= {self.critical_canopy_threshold:.3f}"
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
        buy_toxic = (lambda_skew >= 0.65) or (alpha_buy >= 0.75) or (xi_skew >= 0.70) or (hawkes_eta_buy >= 0.85)
        sell_toxic = (lambda_skew <= -0.65) or (alpha_sell >= 0.75) or (xi_skew <= -0.70) or (hawkes_eta_sell >= 0.85)

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
                "reason": f"BUY_SIDE_TOXICITY (lambda_skew={lambda_skew:.2f}, alpha_buy={alpha_buy:.2f}, xi_skew={xi_skew:.2f})",
                "omega_canopy": omega_canopy,
                "pillar_hazards": pillar_hazards,
                "spikes_count": spikes_count
            }

        if sell_toxic:
            return {
                "action": "BLOCK_SELL",
                "circuit_breaker": False,
                "reason": f"SELL_SIDE_TOXICITY (lambda_skew={lambda_skew:.2f}, alpha_sell={alpha_sell:.2f}, xi_skew={xi_skew:.2f})",
                "omega_canopy": omega_canopy,
                "pillar_hazards": pillar_hazards,
                "spikes_count": spikes_count
            }

        return {
            "action": "ALLOW_ALL",
            "circuit_breaker": False,
            "reason": "ALL_7_PILLARS_STABLE_EQUILIBRIUM",
            "omega_canopy": omega_canopy,
            "pillar_hazards": pillar_hazards,
            "spikes_count": spikes_count
        }
