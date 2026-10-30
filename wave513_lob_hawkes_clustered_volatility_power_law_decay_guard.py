"""
Wave 513: High-Frequency Limit Order Book Power-Law Hawkes Self-Excitation & Memory Kernel Decay Singularity Guard
================================================================================================================
Institutional Quantitative Mathematical Formulation:
Under Bacry, Delattre, Hoffmann, and Muzy (2013), Hardiman, Bercot, and Bouchaud (2013), and Filimonov & Sornette (2012):
Standard exponential Hawkes kernels underestimate long-range temporal clustering of institutional limit order book
trades and cancellations. High-frequency order arrivals follow a power-law self-exciting memory kernel:

    lambda(t) = mu + sum_{t_i < t} phi(t - t_i),   where phi(t) = alpha_0 / (1 + t / t_0)^(1 + theta)

1. Endogeneity Branching Ratio (n_power):
   The total branching ratio represents the fraction of endogenous trades triggered by preceding trades:
       n_power = integral_0^infty phi(t) dt = (alpha_0 * t_0) / theta
   - n_power < 0.70: Stable exogenous regime (trades driven by fundamental information).
   - n_power in [0.70, 0.90): Reflexive market state with high endogenous feedback.
   - n_power >= max_branching_ratio (default: >= 0.90): Supercritical runaway flash-crash regime.

2. Memory Kernel Decay Singularity Exponent (theta):
   The power-law tail exponent theta governs how quickly reflexive shocks dissipate:
   - Calm markets maintain theta in [0.30, 0.70].
   - When theta <= min_theta_threshold (default: <= 0.15), memory decays with near-infinite persistence,
     trapping the order book in continuous self-propagating cascade loops.

3. Composite Power-Law Hawkes Fragility Index (Psi_hawkes_pl):
       Psi_hawkes_pl = 0.50 * min(1.0, max(0.0, (n_power - 0.60) / 0.30))
                     + 0.50 * min(1.0, max(0.0, (0.30 - theta) / 0.20)) in [0.0, 1.0]

Circuit Breakers:
1. SUPERCRITICAL_POWER_LAW_HAWKES_RUNAWAY: n_power >= max_branching_ratio (default: >= 0.90) or Psi_hawkes_pl >= critical_fragility_threshold (default: >= 0.70) -> HALT_ALL
2. MEMORY_DECAY_SINGULARITY_COLLAPSE: theta <= min_theta_threshold (default: <= 0.15) -> HALT_ALL
3. Asymmetric Directional Toxicity Overrides:
   - n_power >= 0.75 and hawkes_eta_buy >= 0.85 -> BLOCK_BUY (endogenous buyer herd cascade)
   - n_power >= 0.75 and hawkes_eta_sell >= 0.85 -> BLOCK_SELL (endogenous seller liquidation cascade)
"""

import math
import time
import numpy as np
from typing import List, Dict, Any, Optional


class Wave513LobHawkesClusteredVolatilityPowerLawDecayGuard:
    """
    Monitors power-law Hawkes self-excitation branching ratios and memory kernel decay singularity
    to eliminate exposure to supercritical endogenous liquidity flash crashes.
    """

    def __init__(
        self,
        max_branching_ratio: float = 0.90,
        min_theta_threshold: float = 0.15,
        critical_fragility_threshold: float = 0.70,
        warning_branching_ratio: float = 0.75,
        eta_warning_threshold: float = 0.85,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.70 <= max_branching_ratio <= 1.20):
            raise ValueError(f"max_branching_ratio must be in [0.70, 1.20], got {max_branching_ratio}")
        if not (0.05 <= min_theta_threshold <= 0.30):
            raise ValueError(f"min_theta_threshold must be in [0.05, 0.30], got {min_theta_threshold}")
        if not (0.45 <= critical_fragility_threshold <= 0.90):
            raise ValueError(f"critical_fragility_threshold must be in [0.45, 0.90], got {critical_fragility_threshold}")
        if not (0.50 <= warning_branching_ratio <= 0.88):
            raise ValueError(f"warning_branching_ratio must be in [0.50, 0.88], got {warning_branching_ratio}")
        if not (0.60 <= eta_warning_threshold <= 0.99):
            raise ValueError(f"eta_warning_threshold must be in [0.60, 0.99], got {eta_warning_threshold}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.max_branching_ratio: float = max_branching_ratio
        self.min_theta_threshold: float = min_theta_threshold
        self.critical_fragility_threshold: float = critical_fragility_threshold
        self.warning_branching_ratio: float = warning_branching_ratio
        self.eta_warning_threshold: float = eta_warning_threshold
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

    def estimate_power_law_branching(
        self,
        inter_arrival_times: List[float],
        t0_scale: float = 0.05
    ) -> Dict[str, float]:
        """
        Estimates power-law tail decay exponent theta and branching ratio n_power from inter-arrival times.
        """
        if len(inter_arrival_times) < 16:
            raise ValueError(f"Must provide at least 16 inter-arrival intervals, got {len(inter_arrival_times)}")
        if t0_scale <= 0.0:
            raise ValueError(f"t0_scale must be strictly positive, got {t0_scale}")

        arr = np.array(inter_arrival_times, dtype=np.float64)
        arr = np.maximum(arr, 1e-6)

        # Hill-type power-law estimation on large waiting times
        q75 = float(np.percentile(arr, 75))
        tail = arr[arr >= q75]
        if len(tail) > 4:
            theta = float(np.clip(1.0 / np.mean(np.log(tail / q75)), 0.08, 0.85))
        else:
            theta = 0.40

        # Estimate alpha_0 from average rate
        rate = 1.0 / float(np.mean(arr))
        alpha_0 = float(np.clip(rate * t0_scale * theta * 0.5, 0.01, 2.0))
        n_power = float(np.clip((alpha_0 * t0_scale) / max(theta, 1e-4), 0.05, 1.50))

        return {
            "theta": theta,
            "alpha_0": alpha_0,
            "n_power": n_power
        }

    def evaluate(
        self,
        n_power: float,
        theta: float = 0.40,
        hawkes_eta_buy: float = 0.0,
        hawkes_eta_sell: float = 0.0,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Evaluates power-law Hawkes branching ratio, memory decay singularity, and directional toxicity.
        """
        now = time.time() if timestamp is None else float(timestamp)

        # Input validations
        if not (0.0 <= n_power <= 3.0):
            raise ValueError(f"n_power must be in [0.0, 3.0], got {n_power}")
        if not (0.01 <= theta <= 2.0):
            raise ValueError(f"theta must be in [0.01, 2.0], got {theta}")
        if not (0.0 <= hawkes_eta_buy <= 1.0):
            raise ValueError(f"hawkes_eta_buy must be in [0.0, 1.0], got {hawkes_eta_buy}")
        if not (0.0 <= hawkes_eta_sell <= 1.0):
            raise ValueError(f"hawkes_eta_sell must be in [0.0, 1.0], got {hawkes_eta_sell}")

        # Check existing cooldown
        if self.breaker_active:
            elapsed = now - self.breaker_tripped_at
            if elapsed < self.cooldown_sec:
                return {
                    "action": "HALT_ALL",
                    "circuit_breaker": True,
                    "reason": f"COOLDOWN_ACTIVE: {self.last_trip_reason} ({elapsed:.2f}s < {self.cooldown_sec}s)",
                    "n_power": n_power,
                    "theta": theta,
                    "psi_hawkes_pl": 1.0
                }
            else:
                self.breaker_active = False
                self.last_trip_reason = "NONE"

        # Calculate composite fragility index Psi_hawkes_pl in [0.0, 1.0]
        phi_n = min(1.0, max(0.0, (n_power - 0.60) / 0.30))
        phi_theta = min(1.0, max(0.0, (0.30 - theta) / 0.20))
        psi_hawkes_pl = float(np.clip(0.50 * phi_n + 0.50 * phi_theta, 0.0, 1.0))

        # 1. Supercritical Power-Law Hawkes Runaway Breaker
        if n_power >= self.max_branching_ratio:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"SUPERCRITICAL_POWER_LAW_HAWKES_RUNAWAY: n_power={n_power:.3f} >= {self.max_branching_ratio:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "n_power": n_power,
                "theta": theta,
                "psi_hawkes_pl": psi_hawkes_pl
            }

        if psi_hawkes_pl >= self.critical_fragility_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"POWER_LAW_HAWKES_FRAGILITY_CRITICAL: psi_hawkes_pl={psi_hawkes_pl:.3f} >= {self.critical_fragility_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "n_power": n_power,
                "theta": theta,
                "psi_hawkes_pl": psi_hawkes_pl
            }

        # 2. Memory Decay Singularity Collapse Breaker
        if theta <= self.min_theta_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"MEMORY_DECAY_SINGULARITY_COLLAPSE: theta={theta:.3f} <= {self.min_theta_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "n_power": n_power,
                "theta": theta,
                "psi_hawkes_pl": psi_hawkes_pl
            }

        # 3. Asymmetric Directional Toxicity Overextensions
        if n_power >= self.warning_branching_ratio and hawkes_eta_buy >= self.eta_warning_threshold:
            return {
                "action": "BLOCK_BUY",
                "circuit_breaker": False,
                "reason": f"POWER_LAW_BUYER_HERD_CASCADE: n_power={n_power:.2f} >= {self.warning_branching_ratio:.2f} and eta_buy={hawkes_eta_buy:.2f} >= {self.eta_warning_threshold:.2f}",
                "n_power": n_power,
                "theta": theta,
                "psi_hawkes_pl": psi_hawkes_pl
            }

        if n_power >= self.warning_branching_ratio and hawkes_eta_sell >= self.eta_warning_threshold:
            return {
                "action": "BLOCK_SELL",
                "circuit_breaker": False,
                "reason": f"POWER_LAW_SELLER_LIQUIDATION_CASCADE: n_power={n_power:.2f} >= {self.warning_branching_ratio:.2f} and eta_sell={hawkes_eta_sell:.2f} >= {self.eta_warning_threshold:.2f}",
                "n_power": n_power,
                "theta": theta,
                "psi_hawkes_pl": psi_hawkes_pl
            }

        return {
            "action": "ALLOW_ALL",
            "circuit_breaker": False,
            "reason": "POWER_LAW_HAWKES_EQUILIBRIUM_SECURE",
            "n_power": n_power,
            "theta": theta,
            "psi_hawkes_pl": psi_hawkes_pl
        }
