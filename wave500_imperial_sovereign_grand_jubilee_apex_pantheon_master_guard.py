"""
Wave 500: Imperial Sovereign Grand Jubilee Apex Pantheon Master Canopy Fortress Guard
===================================================================================
Institutional Quantitative Mathematical Formulation:
Historical Milestone Apex Pantheon Synthesizer consolidating the comprehensive
13-dimensional continuum of high-frequency quantitative microstructure risk,
Hawkes self-excitation, order book resilience, cross-impact, iceberg depth,
momentum dislocation half-life, jump-diffusion Lévy flight, and information entropy decay:

The 13 Balanced Quantitative Risk Pillars (7.692% equal weight each, w_k = 1/13):
1. Hawkes Branching Spectral Radius (Wave 481):
   Phi_1 = min(1.0, max(0.0, hawkes_spectral_radius / 0.88))                  (w_1 = 1/13)
2. 3D Order Book Resilience Fragility (Wave 482):
   Phi_2 = min(1.0, max(0.0, resilience_fragility / 0.70))                    (w_2 = 1/13)
3. Order Book Depth Skewness Elasticity (Wave 483):
   Phi_3 = min(1.0, max(0.0, abs(xi_skew) / 0.75))                            (w_3 = 1/13)
4. Apex Sovereign Canopy Baseline (Wave 484):
   Phi_4 = min(1.0, max(0.0, omega_484 / 0.65))                               (w_4 = 1/13)
5. Non-Linear Market Impact Fragility (Wave 485):
   Phi_5 = min(1.0, max(0.0, psi_impact / 0.70))                              (w_5 = 1/13)
6. Grand Jubilee Canopy Master Synthesis (Wave 486):
   Phi_6 = min(1.0, max(0.0, omega_486 / 0.65))                               (w_6 = 1/13)
7. Kyle Lambda Information Share (Wave 487):
   Phi_7 = min(1.0, max(0.0, s_info / 0.75))                                  (w_7 = 1/13)
8. Cross-Impact Spectral Radius (Wave 489):
   Phi_8 = min(1.0, max(0.0, cross_spectral_radius / 0.85))                   (w_8 = 1/13)
9. Limit Order Book Pressure Imbalance (Wave 491):
   Phi_9 = min(1.0, max(0.0, abs(i_pressure) / 0.75))                         (w_9 = 1/13)
10. Hidden Iceberg Liquidity Reserve Ratio (Wave 493):
   Phi_10 = min(1.0, max(0.0, max(r_bid, r_ask) / 4.0))                      (w_10 = 1/13)
11. Transient Momentum Dislocation & Half-Life Fragility (Wave 495):
   Phi_11 = min(1.0, max(0.0, psi_momentum / 0.70))                          (w_11 = 1/13)
12. Jump Diffusion & Lévy Flight Fragility (Wave 497):
   Phi_12 = min(1.0, max(0.0, psi_jump / 0.70))                              (w_12 = 1/13)
13. Shannon & Tsallis Information Entropy Decay Fragility (Wave 499):
   Phi_13 = min(1.0, max(0.0, psi_entropy / 0.70))                           (w_13 = 1/13)

The Master Pantheon Canopy Hazard Index Omega_{500}(t) is:
    Omega_{500}(t) = sum_{k=1}^{13} (1/13) * Phi_k(t) in [0.0, 1.0]

Circuit Breakers:
1. Apex Pantheon Canopy Breach:
   Omega_{500}(t) >= critical_canopy_threshold (default: >= 0.65) -> HALT_ALL
2. Dual Hazard Spike Trigger:
   Count(Phi_k >= dual_spike_threshold) >= 2 (default: >= 2 metrics at >= 0.85) -> HALT_ALL
3. Asymmetric Directional Toxicity Overrides:
   - When buy-side toxic (h_ask <= 0.35 or z_jump >= 2.50 or z_score >= 2.20 or r_ask >= 2.50 or i_pressure <= -0.65 or cross_buy_distortion >= 0.60 or lambda_skew >= 0.65 or alpha_buy >= 0.75 or xi_skew >= 0.70 or hawkes_eta_buy >= 0.85): BLOCK_BUY
   - When sell-side toxic (h_bid <= 0.35 or z_jump <= -2.50 or z_score <= -2.20 or r_bid >= 2.50 or i_pressure >= 0.65 or cross_sell_distortion >= 0.60 or lambda_skew <= -0.65 or alpha_sell >= 0.75 or xi_skew <= -0.70 or hawkes_eta_sell >= 0.85): BLOCK_SELL
"""

import math
import time
import numpy as np
from typing import List, Dict, Any, Optional


class Wave500ImperialSovereignGrandJubileeApexPantheonMasterGuard:
    """
    Historical Milestone Apex Pantheon Master Fortress Synthesizer consolidating
    13 orthogonal frontiers of quantitative risk into the ultimate sovereign defense canopy.
    """

    WEIGHTS = np.full(13, 1.0 / 13.0, dtype=np.float64)

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
        """Reset internal circuit breaker states."""
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
        cross_spectral_radius: float,
        i_pressure: float,
        psi_momentum: float,
        psi_jump: float,
        psi_entropy: float,
        r_bid: float = 0.0,
        r_ask: float = 0.0,
        z_score: float = 0.0,
        z_jump: float = 0.0,
        h_bid: float = 0.70,
        h_ask: float = 0.70,
        cross_buy_distortion: float = 0.0,
        cross_sell_distortion: float = 0.0,
        lambda_skew: float = 0.0,
        alpha_buy: float = 0.50,
        alpha_sell: float = 0.50,
        hawkes_eta_buy: float = 0.0,
        hawkes_eta_sell: float = 0.0,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Synthesize all 13 microstructure pillars into the apex Pantheon canopy hazard index.
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
        if not (0.0 <= cross_spectral_radius <= 3.0):
            raise ValueError(f"cross_spectral_radius must be in [0.0, 3.0], got {cross_spectral_radius}")
        if not (-1.0 <= i_pressure <= 1.0):
            raise ValueError(f"i_pressure must be in [-1.0, 1.0], got {i_pressure}")
        if not (0.0 <= psi_momentum <= 1.0):
            raise ValueError(f"psi_momentum must be in [0.0, 1.0], got {psi_momentum}")
        if not (0.0 <= psi_jump <= 1.0):
            raise ValueError(f"psi_jump must be in [0.0, 1.0], got {psi_jump}")
        if not (0.0 <= psi_entropy <= 1.0):
            raise ValueError(f"psi_entropy must be in [0.0, 1.0], got {psi_entropy}")

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
        phi_8 = min(1.0, max(0.0, cross_spectral_radius / 0.85))
        phi_9 = min(1.0, max(0.0, abs(i_pressure) / 0.75))
        phi_10 = min(1.0, max(0.0, max(r_bid, r_ask) / 4.0))
        phi_11 = min(1.0, max(0.0, psi_momentum / 0.70))
        phi_12 = min(1.0, max(0.0, psi_jump / 0.70))
        phi_13 = min(1.0, max(0.0, psi_entropy / 0.70))

        pillar_hazards = [
            phi_1, phi_2, phi_3, phi_4, phi_5, phi_6,
            phi_7, phi_8, phi_9, phi_10, phi_11, phi_12, phi_13
        ]
        omega_canopy = float(np.dot(self.WEIGHTS, pillar_hazards))

        # Check dual hazard spikes
        spikes_count = sum(1 for p in pillar_hazards if p >= self.dual_spike_threshold)

        # 1. Apex Pantheon Canopy Breach
        if omega_canopy >= self.critical_canopy_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"IMPERIAL_PANTHEON_BREACH: Omega_{500}={omega_canopy:.3f} >= {self.critical_canopy_threshold:.3f}"
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
        buy_toxic = (
            (h_ask <= 0.35)
            or (z_jump >= 2.50)
            or (z_score >= 2.20)
            or (r_ask >= 2.50)
            or (i_pressure <= -0.65)
            or (cross_buy_distortion >= 0.60)
            or (lambda_skew >= 0.65)
            or (alpha_buy >= 0.75)
            or (xi_skew >= 0.70)
            or (hawkes_eta_buy >= 0.85)
        )
        sell_toxic = (
            (h_bid <= 0.35)
            or (z_jump <= -2.50)
            or (z_score <= -2.20)
            or (r_bid >= 2.50)
            or (i_pressure >= 0.65)
            or (cross_sell_distortion >= 0.60)
            or (lambda_skew <= -0.65)
            or (alpha_sell >= 0.75)
            or (xi_skew <= -0.70)
            or (hawkes_eta_sell >= 0.85)
        )

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
                "reason": f"BUY_SIDE_TOXICITY (h_ask={h_ask:.2f}, z_jump={z_jump:.2f}, z_score={z_score:.2f}, r_ask={r_ask:.2f})",
                "omega_canopy": omega_canopy,
                "pillar_hazards": pillar_hazards,
                "spikes_count": spikes_count
            }

        if sell_toxic:
            return {
                "action": "BLOCK_SELL",
                "circuit_breaker": False,
                "reason": f"SELL_SIDE_TOXICITY (h_bid={h_bid:.2f}, z_jump={z_jump:.2f}, z_score={z_score:.2f}, r_bid={r_bid:.2f})",
                "omega_canopy": omega_canopy,
                "pillar_hazards": pillar_hazards,
                "spikes_count": spikes_count
            }

        return {
            "action": "ALLOW_ALL",
            "circuit_breaker": False,
            "reason": "ALL_13_PILLARS_STABLE_EQUILIBRIUM",
            "omega_canopy": omega_canopy,
            "pillar_hazards": pillar_hazards,
            "spikes_count": spikes_count
        }
