"""
Wave 497: High-Frequency Limit Order Book Jump Diffusion & Lévy Flight Liquidity Shock Guard
==========================================================================================
Institutional Quantitative Mathematical Formulation:
Under Merton (1976), Kou (2002), Cont & Tankov (2004), and Barndorff-Nielsen & Shephard (2004, 2006),
high-frequency asset price and order book depth variations follow a jump-diffusion process:

    dX_t = mu * dt + sigma * dW_t + J_t * dN_t

where:
    - W_t is standard Brownian motion (continuous diffusive background noise).
    - N_t is a Poisson jump process with jump arrival intensity lambda_jump.
    - J_t is the jump size amplitude.
    - Fat-tailed liquidity shocks follow a heavy-tailed Lévy alpha-stable law with characteristic
      tail index alpha_levy in (0, 2.0], where alpha = 2.0 represents Gaussian diffusion, and
      alpha < 1.40 signals power-law catastrophic liquidity flight.

1. Non-Parametric Jump Identification via Realized Bipower Variation (BV):
   - Realized Quadratic Variation (QV):
         QV = sum_{i=1}^N (Delta X_i)^2
   - Realized Bipower Variation (BV) robust to jumps:
         BV = (pi / 2) * sum_{i=2}^N |Delta X_i| * |Delta X_{i-1}|
   - Jump Contribution Ratio (J_ratio):
         J_ratio = max(0.0, (QV - BV) / max(QV, 1e-12)) in [0.0, 1.0]

2. Heavy-Tailed Lévy Flight Index Estimation (Hill Tail Index):
   - Estimated from top k tail order statistics of absolute returns |Delta X|:
         alpha_levy = ( (1 / k) * sum_{j=1}^k ln(|Delta X|_{(j)} / |Delta X|_{(k+1)}) )^(-1)
   - Clamped to [0.50, 2.00].

3. Composite Jump Fragility Index (Psi_jump):
   Psi_jump = 0.50 * min(1.0, max(0.0, (J_ratio - 0.20) / 0.55))
            + 0.50 * min(1.0, max(0.0, (1.75 - alpha_levy) / 0.65)) in [0.0, 1.0]

Circuit Breakers:
1. LOB_JUMP_DIFFUSION_CRITICAL: J_ratio >= max_jratio_threshold (default: >= 0.75) or Psi_jump >= critical_fragility_threshold (default: >= 0.70) -> HALT_ALL
2. LEVY_FLIGHT_SHOCK: alpha_levy <= min_alpha_threshold (default: <= 1.30) and J_ratio >= 0.40 -> HALT_ALL
3. Asymmetric Jump Cascades:
   - Z_jump >= zjump_warning_threshold (default: >= 2.50) -> BLOCK_BUY (parabolic cascade / flash squeeze top)
   - Z_jump <= -zjump_warning_threshold (default: <= -2.50) -> BLOCK_SELL (flash liquidation cascade bottom)
"""

import math
import time
import numpy as np
from typing import List, Dict, Any, Optional


class Wave497LobJumpDiffusionLevyFlightGuard:
    """
    Monitors realized bipower jump variations, Lévy flight alpha tail exponents,
    and instantaneous discontinuous liquidity shocks in high-frequency order books.
    """

    def __init__(
        self,
        max_jratio_threshold: float = 0.75,
        min_alpha_threshold: float = 1.30,
        critical_fragility_threshold: float = 0.70,
        zjump_warning_threshold: float = 2.50,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.50 <= max_jratio_threshold <= 0.95):
            raise ValueError(f"max_jratio_threshold must be in [0.50, 0.95], got {max_jratio_threshold}")
        if not (0.80 <= min_alpha_threshold <= 1.60):
            raise ValueError(f"min_alpha_threshold must be in [0.80, 1.60], got {min_alpha_threshold}")
        if not (0.45 <= critical_fragility_threshold <= 0.90):
            raise ValueError(f"critical_fragility_threshold must be in [0.45, 0.90], got {critical_fragility_threshold}")
        if not (1.80 <= zjump_warning_threshold <= 3.50):
            raise ValueError(f"zjump_warning_threshold must be in [1.80, 3.50], got {zjump_warning_threshold}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.max_jratio_threshold: float = max_jratio_threshold
        self.min_alpha_threshold: float = min_alpha_threshold
        self.critical_fragility_threshold: float = critical_fragility_threshold
        self.zjump_warning_threshold: float = zjump_warning_threshold
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

    def estimate_bipower_jump(
        self,
        prices: List[float]
    ) -> Dict[str, float]:
        """
        Calculates Realized Quadratic Variation (QV), Realized Bipower Variation (BV),
        and Jump Contribution Ratio J_ratio = max(0, (QV - BV) / QV).
        """
        if len(prices) < 4:
            raise ValueError(f"Must provide at least 4 prices for jump estimation, got {len(prices)}")

        p = np.array(prices, dtype=np.float64)
        if np.any(p <= 0.0):
            raise ValueError("All prices must be strictly positive")

        returns = np.diff(np.log(p))
        n_ret = len(returns)
        if n_ret < 3:
            return {"qv": 0.0, "bv": 0.0, "j_ratio": 0.0}

        qv = float(np.sum(returns ** 2))
        bv = float((np.pi / 2.0) * np.sum(np.abs(returns[1:]) * np.abs(returns[:-1])))

        if qv > 1e-12:
            j_ratio = float(np.clip((qv - bv) / qv, 0.0, 1.0))
        else:
            j_ratio = 0.0

        return {
            "qv": qv,
            "bv": bv,
            "j_ratio": j_ratio
        }

    def estimate_levy_alpha(
        self,
        returns: List[float]
    ) -> float:
        """
        Estimates the tail index alpha_levy via Hill's estimator on the upper tail
        of absolute high-frequency returns. Returns value in [0.50, 2.00].
        """
        if len(returns) < 6:
            raise ValueError(f"Must provide at least 6 returns for Lévy alpha estimation, got {len(returns)}")

        abs_ret = np.sort(np.abs(np.array(returns, dtype=np.float64)))[::-1]
        # Filter near-zero values
        abs_ret = abs_ret[abs_ret > 1e-9]

        if len(abs_ret) < 4:
            return 2.0  # Gaussian baseline if insufficient variation

        k = max(2, int(np.floor(0.20 * len(abs_ret))))
        tail_vals = abs_ret[:k]
        threshold = abs_ret[k]

        if threshold <= 1e-12:
            return 2.0

        log_ratios = np.log(tail_vals / threshold)
        mean_log = float(np.mean(log_ratios))

        if mean_log <= 1e-6:
            return 2.0

        alpha_hill = 1.0 / mean_log
        return float(np.clip(alpha_hill, 0.50, 2.00))

    def evaluate(
        self,
        j_ratio: float,
        alpha_levy: float,
        z_jump: float = 0.0,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Evaluates jump diffusion ratio, tail alpha index, and directional jump score.
        """
        now = time.time() if timestamp is None else float(timestamp)

        # Input validations
        if not (0.0 <= j_ratio <= 1.0):
            raise ValueError(f"j_ratio must be in [0.0, 1.0], got {j_ratio}")
        if not (0.50 <= alpha_levy <= 2.00):
            raise ValueError(f"alpha_levy must be in [0.50, 2.00], got {alpha_levy}")
        if not (-10.0 <= z_jump <= 10.0):
            raise ValueError(f"z_jump must be in [-10.0, 10.0], got {z_jump}")

        # Check existing cooldown
        if self.breaker_active:
            elapsed = now - self.breaker_tripped_at
            if elapsed < self.cooldown_sec:
                return {
                    "action": "HALT_ALL",
                    "circuit_breaker": True,
                    "reason": f"COOLDOWN_ACTIVE: {self.last_trip_reason} ({elapsed:.2f}s < {self.cooldown_sec}s)",
                    "j_ratio": j_ratio,
                    "alpha_levy": alpha_levy,
                    "psi_jump": 1.0,
                    "z_jump": z_jump
                }
            else:
                self.breaker_active = False
                self.last_trip_reason = "NONE"

        # Compute composite jump fragility index Psi_jump in [0.0, 1.0]
        phi_j = min(1.0, max(0.0, (j_ratio - 0.20) / 0.55))
        phi_alpha = min(1.0, max(0.0, (1.75 - alpha_levy) / 0.65))
        psi_jump = float(np.clip(0.50 * phi_j + 0.50 * phi_alpha, 0.0, 1.0))

        # 1. Critical Jump Diffusion Breaker
        if j_ratio >= self.max_jratio_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"LOB_JUMP_DIFFUSION_CRITICAL: j_ratio={j_ratio:.3f} >= {self.max_jratio_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "j_ratio": j_ratio,
                "alpha_levy": alpha_levy,
                "psi_jump": psi_jump,
                "z_jump": z_jump
            }

        if psi_jump >= self.critical_fragility_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"JUMP_FRAGILITY_CRITICAL: psi_jump={psi_jump:.3f} >= {self.critical_fragility_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "j_ratio": j_ratio,
                "alpha_levy": alpha_levy,
                "psi_jump": psi_jump,
                "z_jump": z_jump
            }

        # 2. Lévy Flight Liquidity Shock
        if alpha_levy <= self.min_alpha_threshold and j_ratio >= 0.40:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"LEVY_FLIGHT_SHOCK: alpha={alpha_levy:.2f} <= {self.min_alpha_threshold:.2f} and j_ratio={j_ratio:.2f} >= 0.40"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "j_ratio": j_ratio,
                "alpha_levy": alpha_levy,
                "psi_jump": psi_jump,
                "z_jump": z_jump
            }

        # 3. Asymmetric Directional Jump Overextension
        if z_jump >= self.zjump_warning_threshold:
            return {
                "action": "BLOCK_BUY",
                "circuit_breaker": False,
                "reason": f"UPWARD_JUMP_EXHAUSTION: z_jump={z_jump:.2f} >= {self.zjump_warning_threshold:.2f}",
                "j_ratio": j_ratio,
                "alpha_levy": alpha_levy,
                "psi_jump": psi_jump,
                "z_jump": z_jump
            }

        if z_jump <= -self.zjump_warning_threshold:
            return {
                "action": "BLOCK_SELL",
                "circuit_breaker": False,
                "reason": f"DOWNWARD_JUMP_FLUSH: z_jump={z_jump:.2f} <= -{self.zjump_warning_threshold:.2f}",
                "j_ratio": j_ratio,
                "alpha_levy": alpha_levy,
                "psi_jump": psi_jump,
                "z_jump": z_jump
            }

        return {
            "action": "ALLOW_ALL",
            "circuit_breaker": False,
            "reason": "EQUILIBRIUM_DIFFUSION_ACTIVE",
            "j_ratio": j_ratio,
            "alpha_levy": alpha_levy,
            "psi_jump": psi_jump,
            "z_jump": z_jump
        }
