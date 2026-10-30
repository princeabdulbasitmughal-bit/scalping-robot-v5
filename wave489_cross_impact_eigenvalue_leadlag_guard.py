"""
Wave 489: Cross-Impact Matrix Eigenvalue & Lead-Lag Asymmetry Guard
===================================================================
Institutional Quantitative Mathematical Formulation:
Under Schneider & Lillo (2019) "Cross-impact and market stability",
Wang, Bouchaud & Potters (2016), and Gatheral (2010), price movements in a multi-asset /
multi-venue electronic market are driven by cross-impact order flow:

    Delta P = Lambda * Q + epsilon

where:
    - Lambda is the N x N cross-impact matrix.
    - S = 0.5 * (Lambda + Lambda^T) is the symmetric market response matrix.
    - A = 0.5 * (Lambda - Lambda^T) is the anti-symmetric lead-lag matrix.

1. Cross-Impact Asymmetry Ratio (Lead-Lag Divergence):
   chi_asym = ||A||_F / max(||S||_F, 1e-9) in [0.0, infinity)
   When chi_asym > 0.60, non-conservative order flow forces predatory cross-asset price manipulation.

2. Spectral Radius of Cross-Impact:
   lambda_max = max_k |eig_k(Lambda)|
   When lambda_max >= 0.85, cross-asset impact feedback loops threaten liquidity cascading collapse.

3. Directional Lead-Lag Distortion:
   - When cross-impact induces asymmetric adverse price swings against buy orders: BLOCK_BUY
   - When cross-impact induces asymmetric adverse price swings against sell orders: BLOCK_SELL

Circuit Breakers:
1. CROSS_IMPACT_SPECTRAL_CRITICAL: lambda_max >= max_spectral_threshold (default: >= 0.85) -> HALT_ALL
2. LEAD_LAG_ASYMMETRY_BREACH: chi_asym >= max_asymmetry_threshold (default: >= 0.65) -> HALT_ALL
3. Asymmetric Cross Distortion:
   - cross_buy_distortion >= 0.60 -> BLOCK_BUY
   - cross_sell_distortion >= 0.60 -> BLOCK_SELL
"""

import math
import time
import numpy as np
from typing import List, Dict, Any, Optional


class Wave489CrossImpactEigenvalueLeadlagGuard:
    """
    Monitors cross-impact matrix eigenvalues, spectral radius, and anti-symmetric
    lead-lag price manipulation dynamics to protect multi-asset execution.
    """

    def __init__(
        self,
        max_spectral_threshold: float = 0.85,
        max_asymmetry_threshold: float = 0.65,
        distortion_threshold: float = 0.60,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.50 <= max_spectral_threshold <= 1.20):
            raise ValueError(f"max_spectral_threshold must be in [0.50, 1.20], got {max_spectral_threshold}")
        if not (0.30 <= max_asymmetry_threshold <= 1.50):
            raise ValueError(f"max_asymmetry_threshold must be in [0.30, 1.50], got {max_asymmetry_threshold}")
        if not (0.30 <= distortion_threshold <= 0.90):
            raise ValueError(f"distortion_threshold must be in [0.30, 0.90], got {distortion_threshold}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.max_spectral_threshold: float = max_spectral_threshold
        self.max_asymmetry_threshold: float = max_asymmetry_threshold
        self.distortion_threshold: float = distortion_threshold
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

    def compute_matrix_metrics(self, lambda_matrix: List[List[float]]) -> Dict[str, float]:
        """
        Compute Frobenius norms of symmetric/anti-symmetric components and spectral radius.
        """
        mat = np.array(lambda_matrix, dtype=np.float64)
        if mat.ndim != 2 or mat.shape[0] != mat.shape[1]:
            raise ValueError(f"lambda_matrix must be a square 2D matrix, got shape {mat.shape}")
        if mat.shape[0] < 2:
            raise ValueError(f"lambda_matrix dimension must be at least 2x2, got {mat.shape}")

        s_mat = 0.5 * (mat + mat.T)
        a_mat = 0.5 * (mat - mat.T)

        frob_s = float(np.linalg.norm(s_mat, 'fro'))
        frob_a = float(np.linalg.norm(a_mat, 'fro'))

        chi_asym = frob_a / frob_s if frob_s > 1e-9 else 0.0

        # Eigenvalues of Lambda
        eigs = np.linalg.eigvals(mat)
        spectral_radius = float(np.max(np.abs(eigs)))

        return {
            "spectral_radius": float(spectral_radius),
            "chi_asym": float(chi_asym),
            "frob_s": float(frob_s),
            "frob_a": float(frob_a)
        }

    def evaluate(
        self,
        spectral_radius: float,
        chi_asym: float,
        cross_buy_distortion: float = 0.0,
        cross_sell_distortion: float = 0.0,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Evaluate cross-impact spectral radius and lead-lag asymmetry.
        """
        now = time.time() if timestamp is None else float(timestamp)

        # Range validations
        if not (0.0 <= spectral_radius <= 3.0):
            raise ValueError(f"spectral_radius must be in [0.0, 3.0], got {spectral_radius}")
        if not (0.0 <= chi_asym <= 5.0):
            raise ValueError(f"chi_asym must be in [0.0, 5.0], got {chi_asym}")
        if not (0.0 <= cross_buy_distortion <= 1.0):
            raise ValueError(f"cross_buy_distortion must be in [0.0, 1.0], got {cross_buy_distortion}")
        if not (0.0 <= cross_sell_distortion <= 1.0):
            raise ValueError(f"cross_sell_distortion must be in [0.0, 1.0], got {cross_sell_distortion}")

        # Check existing cooldown
        if self.breaker_active:
            elapsed = now - self.breaker_tripped_at
            if elapsed < self.cooldown_sec:
                return {
                    "action": "HALT_ALL",
                    "circuit_breaker": True,
                    "reason": f"COOLDOWN_ACTIVE: {self.last_trip_reason} ({elapsed:.2f}s < {self.cooldown_sec}s)",
                    "spectral_radius": spectral_radius,
                    "chi_asym": chi_asym
                }
            else:
                self.breaker_active = False
                self.last_trip_reason = "NONE"

        # 1. Spectral Radius Critical Breaker
        if spectral_radius >= self.max_spectral_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"CROSS_IMPACT_SPECTRAL_CRITICAL: lambda_max={spectral_radius:.3f} >= {self.max_spectral_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "spectral_radius": spectral_radius,
                "chi_asym": chi_asym
            }

        # 2. Lead-Lag Asymmetry Breach
        if chi_asym >= self.max_asymmetry_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"LEAD_LAG_ASYMMETRY_BREACH: chi_asym={chi_asym:.3f} >= {self.max_asymmetry_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "spectral_radius": spectral_radius,
                "chi_asym": chi_asym
            }

        # 3. Directional Lead-Lag Overrides
        buy_toxic = cross_buy_distortion >= self.distortion_threshold
        sell_toxic = cross_sell_distortion >= self.distortion_threshold

        if buy_toxic and sell_toxic:
            return {
                "action": "HALT_ALL",
                "circuit_breaker": False,
                "reason": "BILATERAL_CROSS_IMPACT_DISTORTION",
                "spectral_radius": spectral_radius,
                "chi_asym": chi_asym
            }

        if buy_toxic:
            return {
                "action": "BLOCK_BUY",
                "circuit_breaker": False,
                "reason": f"CROSS_BUY_DISTORTION ({cross_buy_distortion:.2f} >= {self.distortion_threshold:.2f})",
                "spectral_radius": spectral_radius,
                "chi_asym": chi_asym
            }

        if sell_toxic:
            return {
                "action": "BLOCK_SELL",
                "circuit_breaker": False,
                "reason": f"CROSS_SELL_DISTORTION ({cross_sell_distortion:.2f} >= {self.distortion_threshold:.2f})",
                "spectral_radius": spectral_radius,
                "chi_asym": chi_asym
            }

        return {
            "action": "ALLOW_ALL",
            "circuit_breaker": False,
            "reason": "CROSS_IMPACT_STABLE_EQUILIBRIUM",
            "spectral_radius": spectral_radius,
            "chi_asym": chi_asym
        }
