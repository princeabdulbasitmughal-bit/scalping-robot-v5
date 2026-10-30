"""
Wave 495: Transient Cross-Sectional Momentum Dislocation & Mean-Reversion Half-Life Guard
========================================================================================
Institutional Quantitative Mathematical Formulation:
Under Moskowitz, Ooi & Pedersen (2012) "Time series momentum", Lo & MacKinlay (1990),
and Avellaneda & Lee (2010), high-frequency asset price deviations from fair value
follow an Ornstein-Uhlenbeck (OU) mean-reverting process:

    dX_t = -theta * (X_t - mu) * dt + sigma * dW_t

where:
    - X_t = ln(P_t / P_fair) is the log dislocation.
    - theta > 0 is the mean reversion speed.
    - t_halflife = ln(2) / theta is the mean-reversion half-life (seconds).

1. Dislocation Z-Score:
   Z_t = (X_t - mu_X) / max(sigma_X, 1e-6)

2. Half-Life Decay Failure:
   - Normal HFT mean-reversion half-life: t_halflife in [0.5, 3.0] s.
   - When t_halflife > 8.0 s, mean reversion breaks down into persistent trending momentum.

3. Composite Momentum Fragility Index:
   Psi_momentum = 0.50 * min(1.0, max(0.0, (|Z_t| - 2.0) / 1.50))
                + 0.50 * min(1.0, max(0.0, (t_halflife - 3.0) / 5.0)) in [0.0, 1.0]

Circuit Breakers:
1. MOMENTUM_DISLOCATION_CRITICAL: |Z_t| >= max_zscore_threshold (default: >= 3.20) -> HALT_ALL
2. MEAN_REVERSION_COLLAPSE: t_halflife >= max_halflife_threshold and |Z_t| >= 2.20 (default: >= 8.0s) -> HALT_ALL
3. Directional Overextension Overrides:
   - Z_t >= zscore_warning_threshold (default: >= 2.20) -> BLOCK_BUY (parabolic blow-off top)
   - Z_t <= -zscore_warning_threshold (default: <= -2.20) -> BLOCK_SELL (flush liquidation bottom)
"""

import math
import time
import numpy as np
from typing import List, Dict, Any, Optional


class Wave495TransientMomentumDislocationHalflifeGuard:
    """
    Monitors Ornstein-Uhlenbeck mean-reversion half-lives, momentum dislocation Z-scores,
    and persistent directional price runaway to protect contrarian execution.
    """

    def __init__(
        self,
        max_zscore_threshold: float = 3.20,
        zscore_warning_threshold: float = 2.20,
        max_halflife_threshold: float = 8.0,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (2.50 <= max_zscore_threshold <= 5.0):
            raise ValueError(f"max_zscore_threshold must be in [2.50, 5.0], got {max_zscore_threshold}")
        if not (1.50 <= zscore_warning_threshold <= 3.0):
            raise ValueError(f"zscore_warning_threshold must be in [1.50, 3.0], got {zscore_warning_threshold}")
        if zscore_warning_threshold >= max_zscore_threshold:
            raise ValueError("zscore_warning_threshold must be strictly less than max_zscore_threshold")
        if not (4.0 <= max_halflife_threshold <= 20.0):
            raise ValueError(f"max_halflife_threshold must be in [4.0, 20.0], got {max_halflife_threshold}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.max_zscore_threshold: float = max_zscore_threshold
        self.zscore_warning_threshold: float = zscore_warning_threshold
        self.max_halflife_threshold: float = max_halflife_threshold
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

    def estimate_ou_parameters(
        self,
        series: List[float],
        dt: float = 0.1
    ) -> Dict[str, float]:
        """
        Estimate OU theta and half-life via AR(1) discrete regression:
        X_{t} = a + b * X_{t-1} + e
        theta = -ln(b) / dt,  t_halflife = ln(2) / theta
        """
        if len(series) < 6:
            raise ValueError(f"Must provide at least 6 points for OU estimation, got {len(series)}")
        if dt <= 0.0:
            raise ValueError(f"dt must be positive, got {dt}")

        x = np.array(series, dtype=np.float64)
        x_lag = x[:-1]
        x_lead = x[1:]

        var_lag = float(np.var(x_lag, ddof=1))
        if var_lag < 1e-9:
            return {"theta": 1.0, "t_halflife": math.log(2.0), "z_score": 0.0}

        cov = float(np.cov(x_lag, x_lead)[0, 1])
        b = cov / var_lag

        # Cap b to (0.001, 0.999) for stable positive theta
        b = max(0.001, min(0.999, b))
        theta = -math.log(b) / dt
        t_halflife = math.log(2.0) / max(theta, 1e-6)

        mu_x = float(np.mean(x))
        std_x = float(np.std(x, ddof=1))
        z_score = (x[-1] - mu_x) / max(std_x, 1e-6)

        return {
            "theta": float(theta),
            "t_halflife": float(t_halflife),
            "z_score": float(z_score)
        }

    def evaluate(
        self,
        z_score: float,
        t_halflife: float,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Evaluate dislocation Z-score and mean-reversion half-life.
        """
        now = time.time() if timestamp is None else float(timestamp)

        # Range validations
        if not (-10.0 <= z_score <= 10.0):
            raise ValueError(f"z_score must be in [-10.0, 10.0], got {z_score}")
        if t_halflife < 0.0:
            raise ValueError(f"t_halflife must be non-negative, got {t_halflife}")

        # Check existing cooldown
        if self.breaker_active:
            elapsed = now - self.breaker_tripped_at
            if elapsed < self.cooldown_sec:
                return {
                    "action": "HALT_ALL",
                    "circuit_breaker": True,
                    "reason": f"COOLDOWN_ACTIVE: {self.last_trip_reason} ({elapsed:.2f}s < {self.cooldown_sec}s)",
                    "z_score": z_score,
                    "t_halflife": t_halflife,
                    "psi_momentum": 1.0
                }
            else:
                self.breaker_active = False
                self.last_trip_reason = "NONE"

        abs_z = abs(z_score)

        term_z = min(1.0, max(0.0, (abs_z - 2.0) / 1.50))
        term_hl = min(1.0, max(0.0, (t_halflife - 3.0) / 5.0))
        psi_momentum = 0.50 * term_z + 0.50 * term_hl

        # 1. Critical Dislocation Breach
        if abs_z >= self.max_zscore_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"MOMENTUM_DISLOCATION_CRITICAL: |Z|={abs_z:.2f} >= {self.max_zscore_threshold:.2f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "z_score": z_score,
                "t_halflife": t_halflife,
                "psi_momentum": psi_momentum
            }

        # 2. Mean-Reversion Collapse (Stalled Reversion under Dislocation)
        if t_halflife >= self.max_halflife_threshold and abs_z >= self.zscore_warning_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"MEAN_REVERSION_COLLAPSE: t_1/2={t_halflife:.2f}s >= {self.max_halflife_threshold:.1f}s and |Z|={abs_z:.2f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "z_score": z_score,
                "t_halflife": t_halflife,
                "psi_momentum": psi_momentum
            }

        # 3. Directional Overextensions
        if z_score >= self.zscore_warning_threshold:
            return {
                "action": "BLOCK_BUY",
                "circuit_breaker": False,
                "reason": f"PARABOLIC_BLOWOFF_TOP: Z={z_score:.2f} >= {self.zscore_warning_threshold:.2f}",
                "z_score": z_score,
                "t_halflife": t_halflife,
                "psi_momentum": psi_momentum
            }

        if z_score <= -self.zscore_warning_threshold:
            return {
                "action": "BLOCK_SELL",
                "circuit_breaker": False,
                "reason": f"LIQUIDATION_FLUSH_BOTTOM: Z={z_score:.2f} <= -{self.zscore_warning_threshold:.2f}",
                "z_score": z_score,
                "t_halflife": t_halflife,
                "psi_momentum": psi_momentum
            }

        return {
            "action": "ALLOW_ALL",
            "circuit_breaker": False,
            "reason": "MEAN_REVERTING_EQUILIBRIUM",
            "z_score": z_score,
            "t_halflife": t_halflife,
            "psi_momentum": psi_momentum
        }
