"""
Wave 507: High-Frequency Limit Order Book Non-Equilibrium Kramers-Moyal Expansion & Drift-Diffusion Jump Singularity Guard
========================================================================================================================
Institutional Quantitative Mathematical Formulation:
Under Risken (1996), Friedrich et al. (2011), and Peinke et al. (2004),
high-frequency limit order book price transitions and depth increments follow the continuous
stochastic Kramers-Moyal expansion:

    D^(k)(x) = lim_{tau -> 0} (1 / (k! * tau)) * E[ (x(t + tau) - x(t))^k | x(t) = x ]

1. First and Second Kramers-Moyal Coefficients (Drift & Diffusion):
       D^(1) = (1 / tau) * E[ Delta x ]
       D^(2) = (1 / (2 * tau)) * E[ (Delta x)^2 ]

2. Pawula Theorem & Fourth Kramers-Moyal Coefficient (D^(4)):
   By Pawula's Theorem (1967), if D^(4) = 0, then all higher-order coefficients D^(k) = 0 for k >= 3,
   confirming pure continuous Gaussian diffusion (Fokker-Planck).
   If D^(4) > 0, the process contains discontinuous jump singularities and non-Gaussian turbulence:
       D^(4) = (1 / (24 * tau)) * E[ (Delta x)^4 ]
       Q_pawula = D^(4) / max(D^(2) * var(Delta x), 1e-12) in [0.0, 20.0]

3. Composite Kramers-Moyal Fragility Index (Psi_km):
       Psi_km = 0.50 * min(1.0, max(0.0, (Q_pawula - 1.50) / 2.00))
              + 0.50 * min(1.0, max(0.0, (abs(D^(1)) - 0.50) / 1.00)) in [0.0, 1.0]

Circuit Breakers:
1. KRAMERS_MOYAL_JUMP_SINGULARITY: Q_pawula >= max_pawula_threshold (default: >= 3.50) or Psi_km >= critical_fragility_threshold (default: >= 0.70) -> HALT_ALL
2. TURBULENT_DRIFT_RUNAWAY: |D^(1)| >= max_drift_threshold (default: >= 1.20) -> HALT_ALL
3. Asymmetric Directional Toxicity Overrides:
   - D^(1) >= drift_warning_threshold (default: >= 0.75) -> BLOCK_BUY (parabolic runaway)
   - D^(1) <= -drift_warning_threshold (default: <= -0.75) -> BLOCK_SELL (liquidation flush)
"""

import math
import time
import numpy as np
from typing import List, Dict, Any, Optional


class Wave507LobKramersMoyalJumpSingularityGuard:
    """
    Monitors Kramers-Moyal drift and diffusion coefficients, Pawula theorem jump singularities,
    and non-equilibrium turbulence in high-frequency order book transitions.
    """

    def __init__(
        self,
        max_pawula_threshold: float = 3.50,
        max_drift_threshold: float = 1.20,
        critical_fragility_threshold: float = 0.70,
        drift_warning_threshold: float = 0.75,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (2.00 <= max_pawula_threshold <= 6.00):
            raise ValueError(f"max_pawula_threshold must be in [2.00, 6.00], got {max_pawula_threshold}")
        if not (0.60 <= max_drift_threshold <= 2.50):
            raise ValueError(f"max_drift_threshold must be in [0.60, 2.50], got {max_drift_threshold}")
        if not (0.45 <= critical_fragility_threshold <= 0.90):
            raise ValueError(f"critical_fragility_threshold must be in [0.45, 0.90], got {critical_fragility_threshold}")
        if not (0.30 <= drift_warning_threshold <= 1.50):
            raise ValueError(f"drift_warning_threshold must be in [0.30, 1.50], got {drift_warning_threshold}")
        if drift_warning_threshold >= max_drift_threshold:
            raise ValueError("drift_warning_threshold must be strictly less than max_drift_threshold")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.max_pawula_threshold: float = max_pawula_threshold
        self.max_drift_threshold: float = max_drift_threshold
        self.critical_fragility_threshold: float = critical_fragility_threshold
        self.drift_warning_threshold: float = drift_warning_threshold
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

    def calculate_km_coefficients(
        self,
        increments: List[float],
        tau_sec: float = 0.1
    ) -> Dict[str, float]:
        """
        Calculates Kramers-Moyal coefficients D^(1), D^(2), D^(4), and Pawula ratio Q_pawula.
        """
        if len(increments) < 6:
            raise ValueError(f"Must provide at least 6 increments for Kramers-Moyal analysis, got {len(increments)}")
        if tau_sec <= 0.0:
            raise ValueError("tau_sec must be strictly positive")

        dx = np.array(increments, dtype=np.float64)
        d1 = float(np.mean(dx) / tau_sec)
        d2 = float(np.mean(dx ** 2) / (2.0 * tau_sec))
        d4 = float(np.mean(dx ** 4) / (24.0 * tau_sec))
        var_dx = float(np.var(dx, ddof=1)) if len(dx) > 1 else 0.0

        denom = max(d2 * var_dx, 1e-12)
        q_pawula = float(np.clip(d4 / denom, 0.0, 20.0))

        return {
            "d1": d1,
            "d2": d2,
            "d4": d4,
            "q_pawula": q_pawula
        }

    def evaluate(
        self,
        q_pawula: float,
        d1_drift: float = 0.0,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Evaluates Pawula jump ratio, drift runaway, and directional drift bias.
        """
        now = time.time() if timestamp is None else float(timestamp)

        # Input validations
        if not (0.0 <= q_pawula <= 20.0):
            raise ValueError(f"q_pawula must be in [0.0, 20.0], got {q_pawula}")
        if not (-10.0 <= d1_drift <= 10.0):
            raise ValueError(f"d1_drift must be in [-10.0, 10.0], got {d1_drift}")

        # Check existing cooldown
        if self.breaker_active:
            elapsed = now - self.breaker_tripped_at
            if elapsed < self.cooldown_sec:
                return {
                    "action": "HALT_ALL",
                    "circuit_breaker": True,
                    "reason": f"COOLDOWN_ACTIVE: {self.last_trip_reason} ({elapsed:.2f}s < {self.cooldown_sec}s)",
                    "q_pawula": q_pawula,
                    "d1_drift": d1_drift,
                    "psi_km": 1.0
                }
            else:
                self.breaker_active = False
                self.last_trip_reason = "NONE"

        # Calculate composite fragility index Psi_km in [0.0, 1.0]
        phi_q = min(1.0, max(0.0, (q_pawula - 1.50) / 2.00))
        phi_drift = min(1.0, max(0.0, (abs(d1_drift) - 0.50) / 1.00))
        psi_km = float(np.clip(0.50 * phi_q + 0.50 * phi_drift, 0.0, 1.0))

        # 1. Critical Pawula Jump Singularity Breaker
        if q_pawula >= self.max_pawula_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"KRAMERS_MOYAL_JUMP_SINGULARITY: q_pawula={q_pawula:.3f} >= {self.max_pawula_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "q_pawula": q_pawula,
                "d1_drift": d1_drift,
                "psi_km": psi_km
            }

        if psi_km >= self.critical_fragility_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"KM_FRAGILITY_CRITICAL: psi_km={psi_km:.3f} >= {self.critical_fragility_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "q_pawula": q_pawula,
                "d1_drift": d1_drift,
                "psi_km": psi_km
            }

        # 2. Critical Turbulent Drift Runaway Breaker
        if abs(d1_drift) >= self.max_drift_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"TURBULENT_DRIFT_RUNAWAY: |d1_drift|={abs(d1_drift):.3f} >= {self.max_drift_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "q_pawula": q_pawula,
                "d1_drift": d1_drift,
                "psi_km": psi_km
            }

        # 3. Asymmetric Directional Drift Overextensions
        if d1_drift >= self.drift_warning_threshold:
            return {
                "action": "BLOCK_BUY",
                "circuit_breaker": False,
                "reason": f"PARABOLIC_DRIFT_EXHAUSTION: d1_drift={d1_drift:.2f} >= {self.drift_warning_threshold:.2f}",
                "q_pawula": q_pawula,
                "d1_drift": d1_drift,
                "psi_km": psi_km
            }

        if d1_drift <= -self.drift_warning_threshold:
            return {
                "action": "BLOCK_SELL",
                "circuit_breaker": False,
                "reason": f"LIQUIDATION_DRIFT_CASCADE: d1_drift={d1_drift:.2f} <= -{self.drift_warning_threshold:.2f}",
                "q_pawula": q_pawula,
                "d1_drift": d1_drift,
                "psi_km": psi_km
            }

        return {
            "action": "ALLOW_ALL",
            "circuit_breaker": False,
            "reason": "KM_EQUILIBRIUM_ACTIVE",
            "q_pawula": q_pawula,
            "d1_drift": d1_drift,
            "psi_km": psi_km
        }
