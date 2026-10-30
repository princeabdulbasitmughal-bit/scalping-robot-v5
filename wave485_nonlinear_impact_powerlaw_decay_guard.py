"""
Wave 485: Non-Linear Market Impact Curvature & Power-Law Decay Guard
====================================================================
Institutional Quantitative Mathematical Formulation:
Under Almgren, Thum, Hauptmann & Li (2005) "Direct Estimation of Equity Market Impact",
Bouchaud, Gefen, Potters & Wyart (2004), and Gatheral (2010), institutional trade execution
causes non-linear price dislocation governed by the concave square-root law of market impact:

    I(Q) = Y * sigma * (Q / V_0)^alpha

where:
    - Q is trade volume, V_0 is baseline ADV / volume scale.
    - alpha is the market impact curvature exponent (theoretically alpha ~ 0.50).
    - Under normal liquid conditions, impact is strictly sub-linear (alpha <= 0.60).
    - When alpha > 0.80, order book depth is hollowed out, causing catastrophic super-linear slippage.

Furthermore, post-trade price impact relaxes according to a power-law propagator kernel:
    G(t) = G_0 * (1 + t / tau)^(-beta)

where:
    - beta is the power-law relaxation decay exponent (empirically beta ~ 0.40 - 0.60).
    - If beta < 0.15, the price dislocation fails to decay (permanent adverse selection / liquidity desertion).

Composite Impact Fragility Index:
    Psi_impact = 0.50 * min(1.0, max(0.0, (alpha_eff - 0.50) / 0.40))
               + 0.50 * min(1.0, max(0.0, (0.50 - beta_eff) / 0.40)) in [0.0, 1.0]

Circuit Breakers:
1. IMPACT_FRAGILITY_CRITICAL: Psi_impact >= critical_fragility_threshold (default: >= 0.70) -> HALT_ALL
2. SUPERLINEAR_IMPACT_BREACH: alpha_eff >= max_curvature_threshold (default: >= 0.88) -> HALT_ALL
3. Asymmetric Impact Toxicity:
   - alpha_buy >= 0.75 and alpha_sell < 0.60 -> BLOCK_BUY
   - alpha_sell >= 0.75 and alpha_buy < 0.60 -> BLOCK_SELL
"""

import math
import time
import numpy as np
from typing import List, Dict, Any, Optional


class Wave485NonlinearImpactPowerlawDecayGuard:
    """
    Monitors market impact curvature exponents, non-linear slippage scaling,
    and power-law propagator relaxation to protect execution against illiquid adverse selection.
    """

    def __init__(
        self,
        critical_fragility_threshold: float = 0.70,
        max_curvature_threshold: float = 0.88,
        min_decay_threshold: float = 0.15,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.45 <= critical_fragility_threshold <= 0.90):
            raise ValueError(f"critical_fragility_threshold must be in [0.45, 0.90], got {critical_fragility_threshold}")
        if not (0.70 <= max_curvature_threshold <= 1.20):
            raise ValueError(f"max_curvature_threshold must be in [0.70, 1.20], got {max_curvature_threshold}")
        if not (0.05 <= min_decay_threshold <= 0.35):
            raise ValueError(f"min_decay_threshold must be in [0.05, 0.35], got {min_decay_threshold}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.critical_fragility_threshold: float = critical_fragility_threshold
        self.max_curvature_threshold: float = max_curvature_threshold
        self.min_decay_threshold: float = min_decay_threshold
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

    def estimate_curvature(
        self,
        volumes: List[float],
        price_dislocations: List[float]
    ) -> float:
        """
        Estimate the empirical impact curvature exponent alpha via log-linear OLS:
        log(|Delta P|) = log(c) + alpha * log(Q)
        """
        if len(volumes) != len(price_dislocations):
            raise ValueError(f"volumes length ({len(volumes)}) != price_dislocations length ({len(price_dislocations)})")
        if len(volumes) < 3:
            raise ValueError(f"Must provide at least 3 points for impact regression, got {len(volumes)}")

        valid_v = []
        valid_dp = []
        for v, dp in zip(volumes, price_dislocations):
            if v > 1e-6 and abs(dp) > 1e-6:
                valid_v.append(float(v))
                valid_dp.append(abs(float(dp)))

        if len(valid_v) < 3:
            return 0.50  # Default theoretical square-root benchmark

        log_q = np.log(np.array(valid_v, dtype=np.float64))
        log_dp = np.log(np.array(valid_dp, dtype=np.float64))

        # Check for zero variance in log_q
        if np.var(log_q) < 1e-9:
            return 0.50

        slope, _ = np.polyfit(log_q, log_dp, deg=1)
        return float(max(0.10, min(1.50, slope)))

    def evaluate(
        self,
        alpha_eff: float,
        beta_eff: float,
        alpha_buy: float = 0.50,
        alpha_sell: float = 0.50,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Evaluate non-linear market impact curvature and propagator decay exponents.
        """
        now = time.time() if timestamp is None else float(timestamp)

        # Range validations
        if not (0.05 <= alpha_eff <= 2.0):
            raise ValueError(f"alpha_eff must be in [0.05, 2.0], got {alpha_eff}")
        if not (0.0 <= beta_eff <= 2.0):
            raise ValueError(f"beta_eff must be in [0.0, 2.0], got {beta_eff}")
        if not (0.05 <= alpha_buy <= 2.0):
            raise ValueError(f"alpha_buy must be in [0.05, 2.0], got {alpha_buy}")
        if not (0.05 <= alpha_sell <= 2.0):
            raise ValueError(f"alpha_sell must be in [0.05, 2.0], got {alpha_sell}")

        # Check existing cooldown
        if self.breaker_active:
            elapsed = now - self.breaker_tripped_at
            if elapsed < self.cooldown_sec:
                return {
                    "action": "HALT_ALL",
                    "circuit_breaker": True,
                    "reason": f"COOLDOWN_ACTIVE: {self.last_trip_reason} ({elapsed:.2f}s < {self.cooldown_sec}s)",
                    "psi_impact": 1.0,
                    "alpha_eff": alpha_eff,
                    "beta_eff": beta_eff
                }
            else:
                self.breaker_active = False
                self.last_trip_reason = "NONE"

        # Calculate normalized impact fragility Psi_impact in [0.0, 1.0]
        # Curvature hazard: 0.50 is ideal, 0.90 is severe
        term_alpha = min(1.0, max(0.0, (alpha_eff - 0.50) / 0.40))
        # Relaxation decay hazard: 0.50 is healthy, <= 0.10 is zero recovery
        term_beta = min(1.0, max(0.0, (0.50 - beta_eff) / 0.40))

        psi_impact = 0.50 * term_alpha + 0.50 * term_beta

        # 1. Super-Linear Impact Breach
        if alpha_eff >= self.max_curvature_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"SUPERLINEAR_IMPACT_BREACH: alpha_eff={alpha_eff:.3f} >= {self.max_curvature_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "psi_impact": psi_impact,
                "alpha_eff": alpha_eff,
                "beta_eff": beta_eff
            }

        # 2. Critical Impact Fragility
        if psi_impact >= self.critical_fragility_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"IMPACT_FRAGILITY_CRITICAL: Psi_impact={psi_impact:.3f} >= {self.critical_fragility_threshold:.3f} (decay beta={beta_eff:.3f})"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "psi_impact": psi_impact,
                "alpha_eff": alpha_eff,
                "beta_eff": beta_eff
            }

        # 3. Asymmetric Impact Toxicity Overrides
        buy_toxic = (alpha_buy >= 0.75) and (alpha_sell < 0.60)
        sell_toxic = (alpha_sell >= 0.75) and (alpha_buy < 0.60)

        if buy_toxic and sell_toxic:
            return {
                "action": "HALT_ALL",
                "circuit_breaker": False,
                "reason": "BILATERAL_SUPERLINEAR_IMPACT",
                "psi_impact": psi_impact,
                "alpha_eff": alpha_eff,
                "beta_eff": beta_eff
            }

        if buy_toxic:
            return {
                "action": "BLOCK_BUY",
                "circuit_breaker": False,
                "reason": f"BUY_IMPACT_SUPERLINEAR_TOXICITY (alpha_buy={alpha_buy:.2f})",
                "psi_impact": psi_impact,
                "alpha_eff": alpha_eff,
                "beta_eff": beta_eff
            }

        if sell_toxic:
            return {
                "action": "BLOCK_SELL",
                "circuit_breaker": False,
                "reason": f"SELL_IMPACT_SUPERLINEAR_TOXICITY (alpha_sell={alpha_sell:.2f})",
                "psi_impact": psi_impact,
                "alpha_eff": alpha_eff,
                "beta_eff": beta_eff
            }

        return {
            "action": "ALLOW_ALL",
            "circuit_breaker": False,
            "reason": "SUB_LINEAR_IMPACT_EQUILIBRIUM",
            "psi_impact": psi_impact,
            "alpha_eff": alpha_eff,
            "beta_eff": beta_eff
        }
