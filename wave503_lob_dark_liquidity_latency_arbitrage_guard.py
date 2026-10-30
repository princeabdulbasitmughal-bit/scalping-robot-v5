"""
Wave 503: High-Frequency Limit Order Book Dark Liquidity Latency Arbitrage & Fill Probability Hazard Guard
========================================================================================================
Institutional Quantitative Mathematical Formulation:
Under Moallemi & Saglam (2013), Budish, Cramton & Shim (2015), and Zhu (2014),
fragmented liquidity trading across lit order books and off-exchange dark venues exposes
passive quotes to high-frequency cross-venue latency arbitrage and asymmetric adverse selection:

1. Cross-Venue Latency Arbitrage Dislocation Velocity:
   Given lit price P_lit, dark midquote P_dark, and inter-venue network latency tau (ms):
       Delta_P_arb = P_lit - P_dark  (pips)
       v_arb = |Delta_P_arb| / max(tau, 0.05)  (pips / ms)

2. Asymmetric Dark Fill Probability Hazard:
   When lit prices move before dark pool orders execute, passive executions suffer adverse selection:
       P(Fill | Adverse) >> P(Fill | Favorable)
   Directional Fill Asymmetry Ratio (F_asym):
       F_asym = P(Fill | Adverse) / max(P(Fill | Favorable), 0.01) in [0.0, 10.0]

3. Composite Stale Sniping Fragility Index (Psi_sniping):
       Psi_sniping = 0.50 * min(1.0, max(0.0, abs(F_asym - 1.0) / 2.50))
                   + 0.50 * min(1.0, max(0.0, (v_arb - 0.40) / 1.20)) in [0.0, 1.0]

Circuit Breakers:
1. LATENCY_ARBITRAGE_SNIPING: v_arb >= max_arb_velocity_threshold (default: >= 1.50 pips/ms) or Psi_sniping >= critical_sniping_threshold (default: >= 0.70) -> HALT_ALL
2. DARK_FILL_TOXICITY_ASYMMETRY: F_asym >= max_fill_asym_threshold (default: >= 3.20) -> HALT_ALL
3. Asymmetric Directional Toxicity Overrides:
   - Delta_P_arb <= -delta_arb_warning (default: <= -0.80 pips) or F_asym_buy >= 2.20 -> BLOCK_BUY
   - Delta_P_arb >= delta_arb_warning (default: >= 0.80 pips) or F_asym_sell >= 2.20 -> BLOCK_SELL
"""

import math
import time
import numpy as np
from typing import List, Dict, Any, Optional


class Wave503LobDarkLiquidityLatencyArbitrageGuard:
    """
    Monitors cross-venue latency arbitrage dislocations, dark pool adverse selection fill ratios,
    and stale limit order sniping hazards in fragmented high-frequency markets.
    """

    def __init__(
        self,
        max_arb_velocity_threshold: float = 1.50,
        max_fill_asym_threshold: float = 3.20,
        critical_sniping_threshold: float = 0.70,
        delta_arb_warning: float = 0.80,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.80 <= max_arb_velocity_threshold <= 3.50):
            raise ValueError(f"max_arb_velocity_threshold must be in [0.80, 3.50], got {max_arb_velocity_threshold}")
        if not (2.00 <= max_fill_asym_threshold <= 5.00):
            raise ValueError(f"max_fill_asym_threshold must be in [2.00, 5.00], got {max_fill_asym_threshold}")
        if not (0.45 <= critical_sniping_threshold <= 0.90):
            raise ValueError(f"critical_sniping_threshold must be in [0.45, 0.90], got {critical_sniping_threshold}")
        if not (0.40 <= delta_arb_warning <= 2.00):
            raise ValueError(f"delta_arb_warning must be in [0.40, 2.00], got {delta_arb_warning}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.max_arb_velocity_threshold: float = max_arb_velocity_threshold
        self.max_fill_asym_threshold: float = max_fill_asym_threshold
        self.critical_sniping_threshold: float = critical_sniping_threshold
        self.delta_arb_warning: float = delta_arb_warning
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

    def calculate_arbitrage_metrics(
        self,
        p_lit: float,
        p_dark: float,
        tau_ms: float = 0.50
    ) -> Dict[str, float]:
        """
        Calculates price disparity Delta_P_arb and arbitrage velocity v_arb.
        """
        if p_lit <= 0.0 or p_dark <= 0.0:
            raise ValueError("Prices must be strictly positive")
        if tau_ms <= 0.0:
            raise ValueError("tau_ms must be strictly positive")

        delta_p = p_lit - p_dark
        effective_tau = max(tau_ms, 0.05)
        v_arb = abs(delta_p) / effective_tau

        return {
            "delta_p": delta_p,
            "v_arb": v_arb,
            "tau_ms": tau_ms
        }

    def evaluate(
        self,
        v_arb: float,
        f_asym: float = 1.0,
        delta_p_arb: float = 0.0,
        f_asym_buy: float = 1.0,
        f_asym_sell: float = 1.0,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Evaluates cross-venue arbitrage velocity, dark fill asymmetry, and sniping hazard.
        """
        now = time.time() if timestamp is None else float(timestamp)

        # Input validations
        if not (0.0 <= v_arb <= 20.0):
            raise ValueError(f"v_arb must be in [0.0, 20.0], got {v_arb}")
        if not (0.0 <= f_asym <= 20.0):
            raise ValueError(f"f_asym must be in [0.0, 20.0], got {f_asym}")
        if not (-10.0 <= delta_p_arb <= 10.0):
            raise ValueError(f"delta_p_arb must be in [-10.0, 10.0], got {delta_p_arb}")

        # Check existing cooldown
        if self.breaker_active:
            elapsed = now - self.breaker_tripped_at
            if elapsed < self.cooldown_sec:
                return {
                    "action": "HALT_ALL",
                    "circuit_breaker": True,
                    "reason": f"COOLDOWN_ACTIVE: {self.last_trip_reason} ({elapsed:.2f}s < {self.cooldown_sec}s)",
                    "v_arb": v_arb,
                    "f_asym": f_asym,
                    "psi_sniping": 1.0,
                    "delta_p_arb": delta_p_arb
                }
            else:
                self.breaker_active = False
                self.last_trip_reason = "NONE"

        # Calculate composite sniping fragility index Psi_sniping in [0.0, 1.0]
        phi_f = min(1.0, max(0.0, abs(f_asym - 1.0) / 2.50))
        phi_v = min(1.0, max(0.0, (v_arb - 0.40) / 1.20))
        psi_sniping = float(np.clip(0.50 * phi_f + 0.50 * phi_v, 0.0, 1.0))

        # 1. Critical Latency Arbitrage Breaker
        if v_arb >= self.max_arb_velocity_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"LATENCY_ARBITRAGE_SNIPING: v_arb={v_arb:.3f} >= {self.max_arb_velocity_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "v_arb": v_arb,
                "f_asym": f_asym,
                "psi_sniping": psi_sniping,
                "delta_p_arb": delta_p_arb
            }

        if psi_sniping >= self.critical_sniping_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"SNIPING_FRAGILITY_CRITICAL: psi_sniping={psi_sniping:.3f} >= {self.critical_sniping_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "v_arb": v_arb,
                "f_asym": f_asym,
                "psi_sniping": psi_sniping,
                "delta_p_arb": delta_p_arb
            }

        # 2. Critical Dark Pool Adverse Fill Asymmetry
        if f_asym >= self.max_fill_asym_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"DARK_FILL_TOXICITY_ASYMMETRY: f_asym={f_asym:.3f} >= {self.max_fill_asym_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "v_arb": v_arb,
                "f_asym": f_asym,
                "psi_sniping": psi_sniping,
                "delta_p_arb": delta_p_arb
            }

        # 3. Asymmetric Directional Toxicity Overrides
        buy_toxic = (delta_p_arb <= -self.delta_arb_warning) or (f_asym_buy >= 2.20)
        sell_toxic = (delta_p_arb >= self.delta_arb_warning) or (f_asym_sell >= 2.20)

        if buy_toxic and sell_toxic:
            return {
                "action": "HALT_ALL",
                "circuit_breaker": False,
                "reason": "BILATERAL_SNIPING_RISK",
                "v_arb": v_arb,
                "f_asym": f_asym,
                "psi_sniping": psi_sniping,
                "delta_p_arb": delta_p_arb
            }

        if buy_toxic:
            return {
                "action": "BLOCK_BUY",
                "circuit_breaker": False,
                "reason": f"BUY_SIDE_SNIPING_HAZARD (delta_p_arb={delta_p_arb:.2f}, f_asym_buy={f_asym_buy:.2f})",
                "v_arb": v_arb,
                "f_asym": f_asym,
                "psi_sniping": psi_sniping,
                "delta_p_arb": delta_p_arb
            }

        if sell_toxic:
            return {
                "action": "BLOCK_SELL",
                "circuit_breaker": False,
                "reason": f"SELL_SIDE_SNIPING_HAZARD (delta_p_arb={delta_p_arb:.2f}, f_asym_sell={f_asym_sell:.2f})",
                "v_arb": v_arb,
                "f_asym": f_asym,
                "psi_sniping": psi_sniping,
                "delta_p_arb": delta_p_arb
            }

        return {
            "action": "ALLOW_ALL",
            "circuit_breaker": False,
            "reason": "DARK_LIT_EQUILIBRIUM_ACTIVE",
            "v_arb": v_arb,
            "f_asym": f_asym,
            "psi_sniping": psi_sniping,
            "delta_p_arb": delta_p_arb
        }
