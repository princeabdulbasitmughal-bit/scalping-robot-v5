"""
Wave 491: High-Frequency Limit Order Book Pressure Gradient & Evaporation Velocity Guard
========================================================================================
Institutional Quantitative Mathematical Formulation:
Under Cont, Kukanov & Stoikov (2014) "The Price Impact of Order Book Events",
Stoikov (2018), and Lehalle & Mounjid (2017), high-frequency order book price dynamics
are governed by the spatial distribution of depth and its temporal evaporation velocity:

1. Weighted Depth Pressure:
   w_k = exp(-gamma * (k - 1)), for level k in {1, ..., K} (default gamma = 0.40)
   Pi_bid = sum_{k=1}^K w_k * V_k^b
   Pi_ask = sum_{k=1}^K w_k * V_k^a

   Normalized Pressure Imbalance:
   I_pressure = (Pi_bid - Pi_ask) / max(Pi_bid + Pi_ask, 1e-9) in [-1.0, 1.0]

2. Spatial Pressure Gradient (Top vs Deep Concentration):
   grad_bid = (V_1^b - V_K^b) / max(sum_{k=1}^K V_k^b, 1e-9) in [-1.0, 1.0]
   grad_ask = (V_1^a - V_K^a) / max(sum_{k=1}^K V_k^a, 1e-9) in [-1.0, 1.0]
   grad_net = grad_bid - grad_ask in [-2.0, 2.0]

3. Liquidity Evaporation Velocity:
   v_evap(t) = (I_pressure(t) - I_pressure(t - Delta t)) / Delta t

Circuit Breakers:
1. PRESSURE_GRADIENT_CRITICAL: |I_pressure| >= max_pressure_imbalance (default: >= 0.85) -> HALT_ALL
2. SPATIAL_GRADIENT_BREACH: |grad_net| >= max_gradient_breach (default: >= 1.40) -> HALT_ALL
3. FLASH_EVAPORATION_VELOCITY: |v_evap| >= max_evap_velocity (default: >= 1.80 s^-1) -> HALT_ALL
4. Directional Liquidity Evaporation Overrides:
   - I_pressure <= -0.65 or grad_bid <= -0.60 -> BLOCK_BUY (bid side hollowed / collapsing)
   - I_pressure >= 0.65 or grad_ask <= -0.60 -> BLOCK_SELL (ask side hollowed / collapsing)
"""

import math
import time
import numpy as np
from typing import List, Dict, Any, Optional


class Wave491LobPressureGradientEvaporationGuard:
    """
    Monitors high-frequency order book spatial pressure gradients, exponential depth weights,
    and flash liquidity evaporation velocity to protect against predatory cancellations.
    """

    def __init__(
        self,
        max_pressure_imbalance: float = 0.85,
        max_gradient_breach: float = 1.40,
        max_evap_velocity: float = 1.80,
        gamma: float = 0.40,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.50 <= max_pressure_imbalance <= 0.95):
            raise ValueError(f"max_pressure_imbalance must be in [0.50, 0.95], got {max_pressure_imbalance}")
        if not (0.80 <= max_gradient_breach <= 1.90):
            raise ValueError(f"max_gradient_breach must be in [0.80, 1.90], got {max_gradient_breach}")
        if not (0.50 <= max_evap_velocity <= 5.0):
            raise ValueError(f"max_evap_velocity must be in [0.50, 5.0], got {max_evap_velocity}")
        if not (0.10 <= gamma <= 1.50):
            raise ValueError(f"gamma must be in [0.10, 1.50], got {gamma}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.max_pressure_imbalance: float = max_pressure_imbalance
        self.max_gradient_breach: float = max_gradient_breach
        self.max_evap_velocity: float = max_evap_velocity
        self.gamma: float = gamma
        self.cooldown_sec: float = cooldown_sec

        # State tracking
        self.last_i_pressure: Optional[float] = None
        self.last_timestamp: Optional[float] = None
        self.breaker_active: bool = False
        self.breaker_tripped_at: float = 0.0
        self.last_trip_reason: str = "NONE"

    def reset(self) -> None:
        """Reset temporal state."""
        self.last_i_pressure = None
        self.last_timestamp = None
        self.breaker_active = False
        self.breaker_tripped_at = 0.0
        self.last_trip_reason = "NONE"

    def evaluate(
        self,
        bid_volumes: List[float],
        ask_volumes: List[float],
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Evaluate order book pressure gradients and liquidity evaporation velocity.
        """
        now = time.time() if timestamp is None else float(timestamp)

        # Dimension validations
        if len(bid_volumes) != len(ask_volumes):
            raise ValueError(f"bid_volumes length ({len(bid_volumes)}) != ask_volumes length ({len(ask_volumes)})")
        if len(bid_volumes) < 2:
            raise ValueError(f"Must provide at least 2 book levels, got {len(bid_volumes)}")

        # Check existing cooldown
        if self.breaker_active:
            elapsed = now - self.breaker_tripped_at
            if elapsed < self.cooldown_sec:
                return {
                    "action": "HALT_ALL",
                    "circuit_breaker": True,
                    "reason": f"COOLDOWN_ACTIVE: {self.last_trip_reason} ({elapsed:.2f}s < {self.cooldown_sec}s)",
                    "i_pressure": self.last_i_pressure or 0.0,
                    "grad_net": 0.0,
                    "v_evap": 0.0
                }
            else:
                self.breaker_active = False
                self.last_trip_reason = "NONE"

        k_levels = len(bid_volumes)
        weights = np.exp(-self.gamma * np.arange(k_levels, dtype=np.float64))

        bv = np.maximum(0.0, np.array(bid_volumes, dtype=np.float64))
        av = np.maximum(0.0, np.array(ask_volumes, dtype=np.float64))

        tot_bv = float(np.sum(bv))
        tot_av = float(np.sum(av))

        if tot_bv < 1e-9 or tot_av < 1e-9:
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": "ZERO_LIQUIDITY_DETECTED",
                "i_pressure": 0.0,
                "grad_net": 0.0,
                "v_evap": 0.0
            }

        pi_bid = float(np.sum(weights * bv))
        pi_ask = float(np.sum(weights * av))

        denom_pi = pi_bid + pi_ask
        i_pressure = (pi_bid - pi_ask) / denom_pi if denom_pi > 1e-9 else 0.0

        # Spatial pressure gradients
        grad_bid = (bv[0] - bv[-1]) / tot_bv
        grad_ask = (av[0] - av[-1]) / tot_av
        grad_net = grad_bid - grad_ask

        # Evaporation velocity
        v_evap = 0.0
        if self.last_i_pressure is not None and self.last_timestamp is not None:
            dt = now - self.last_timestamp
            if dt > 1e-5:
                v_evap = (i_pressure - self.last_i_pressure) / dt

        self.last_i_pressure = i_pressure
        self.last_timestamp = now

        # Circuit Breakers Evaluation
        abs_pressure = abs(i_pressure)
        abs_grad = abs(grad_net)
        abs_evap = abs(v_evap)

        if abs_evap >= self.max_evap_velocity:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"FLASH_EVAPORATION_VELOCITY: |v_evap|={abs_evap:.3f}/s >= {self.max_evap_velocity:.3f}/s"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "i_pressure": i_pressure,
                "grad_net": grad_net,
                "v_evap": v_evap
            }

        if abs_pressure >= self.max_pressure_imbalance:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"PRESSURE_GRADIENT_CRITICAL: |I_pressure|={abs_pressure:.3f} >= {self.max_pressure_imbalance:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "i_pressure": i_pressure,
                "grad_net": grad_net,
                "v_evap": v_evap
            }

        if abs_grad >= self.max_gradient_breach:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"SPATIAL_GRADIENT_BREACH: |grad_net|={abs_grad:.3f} >= {self.max_gradient_breach:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "i_pressure": i_pressure,
                "grad_net": grad_net,
                "v_evap": v_evap
            }

        # Directional Overrides
        buy_toxic = (i_pressure <= -0.65) or (grad_bid <= -0.60)
        sell_toxic = (i_pressure >= 0.65) or (grad_ask <= -0.60)

        if buy_toxic and sell_toxic:
            return {
                "action": "HALT_ALL",
                "circuit_breaker": False,
                "reason": "BILATERAL_PRESSURE_COLLAPSE",
                "i_pressure": i_pressure,
                "grad_net": grad_net,
                "v_evap": v_evap
            }

        if buy_toxic:
            return {
                "action": "BLOCK_BUY",
                "circuit_breaker": False,
                "reason": f"BID_DEPTH_EVAPORATION (I_pressure={i_pressure:.2f}, grad_bid={grad_bid:.2f})",
                "i_pressure": i_pressure,
                "grad_net": grad_net,
                "v_evap": v_evap
            }

        if sell_toxic:
            return {
                "action": "BLOCK_SELL",
                "circuit_breaker": False,
                "reason": f"ASK_DEPTH_EVAPORATION (I_pressure={i_pressure:.2f}, grad_ask={grad_ask:.2f})",
                "i_pressure": i_pressure,
                "grad_net": grad_net,
                "v_evap": v_evap
            }

        return {
            "action": "ALLOW_ALL",
            "circuit_breaker": False,
            "reason": "BALANCED_PRESSURE_EQUILIBRIUM",
            "i_pressure": i_pressure,
            "grad_net": grad_net,
            "v_evap": v_evap
        }
