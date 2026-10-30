"""
Wave 483: Multi-Level Order Book Skewness Elasticity Guard
==========================================================
Institutional Quantitative Mathematical Formulation:
Under Cartea, Jaimungal & Ricci (2014) "Algorithmic and High-Frequency Trading",
Biais, Hillion & Spatt (1995), and Gould et al. (2013), depth across multiple price levels
k = 1, ..., K in a Limit Order Book (LOB) exhibits asymmetric elasticity under informed flow.

Let the discrete price levels and volumes on bid and ask sides be:
    Bid: {(p_k^b, V_k^b)}_{k=1}^K, where p_1^b > p_2^b > ... > p_K^b
    Ask: {(p_k^a, V_k^a)}_{k=1}^K, where p_1^a < p_2^a < ... < p_K^a

1. Normalized Distance Metric:
   delta_k^b = 1.0 + |p_1^b - p_k^b| / tick_size
   delta_k^a = 1.0 + |p_k^a - p_1^a| / tick_size

2. Depth Elasticity Center of Mass (Mean Volume Distance):
   D_bar_bid = sum_{k=1}^K (delta_k^b * V_k^b) / max(sum_{k=1}^K V_k^b, 1e-6)
   D_bar_ask = sum_{k=1}^K (delta_k^a * V_k^a) / max(sum_{k=1}^K V_k^a, 1e-6)

   When D_bar_bid is high, bid liquidity is hollowed out at the top of the book and sitting
   deep, indicating acute vulnerability to downward price slippage.

3. Order Book Skewness Elasticity Ratio:
   xi_skew = (D_bar_bid - D_bar_ask) / (D_bar_bid + D_bar_ask) in (-1.0, 1.0)

   - xi_skew > 0: Bid depth is pushed deeper than ask depth (bid top-of-book hollow).
   - xi_skew < 0: Ask depth is pushed deeper than bid depth (ask top-of-book hollow).

4. Elasticity Velocity:
   v_xi(t) = (xi_skew(t) - xi_skew(t - Delta t)) / Delta t

Circuit Breakers:
1. SKEWNESS_CRITICAL_HALT: |xi_skew(t)| >= skew_critical_threshold (default: >= 0.85) -> HALT_ALL
2. ELASTICITY_VELOCITY_BREACH: |v_xi(t)| >= max_velocity_threshold (default: >= 1.80 s^-1) -> HALT_ALL
3. Asymmetric Hollowing Protection:
   - xi_skew(t) >= skew_warning_threshold (default: >= 0.65) -> BLOCK_BUY
   - xi_skew(t) <= -skew_warning_threshold (default: <= -0.65) -> BLOCK_SELL
"""

import math
import time
from typing import List, Dict, Any, Optional


class Wave483OrderbookSkewnessElasticityGuard:
    """
    Monitors multi-level limit order book depth skewness, center-of-mass elasticity,
    and rapid book evacuation velocity to protect against predatory quote manipulation.
    """

    def __init__(
        self,
        skew_warning_threshold: float = 0.65,
        skew_critical_threshold: float = 0.85,
        max_velocity_threshold: float = 1.80,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.35 <= skew_warning_threshold <= 0.80):
            raise ValueError(f"skew_warning_threshold must be in [0.35, 0.80], got {skew_warning_threshold}")
        if not (0.70 <= skew_critical_threshold <= 0.98):
            raise ValueError(f"skew_critical_threshold must be in [0.70, 0.98], got {skew_critical_threshold}")
        if skew_warning_threshold >= skew_critical_threshold:
            raise ValueError("skew_warning_threshold must be strictly less than skew_critical_threshold")
        if not (0.50 <= max_velocity_threshold <= 5.0):
            raise ValueError(f"max_velocity_threshold must be in [0.50, 5.0], got {max_velocity_threshold}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.skew_warning_threshold: float = skew_warning_threshold
        self.skew_critical_threshold: float = skew_critical_threshold
        self.max_velocity_threshold: float = max_velocity_threshold
        self.cooldown_sec: float = cooldown_sec

        # State tracking
        self.last_xi_skew: Optional[float] = None
        self.last_timestamp: Optional[float] = None
        self.breaker_active: bool = False
        self.breaker_tripped_at: float = 0.0
        self.last_trip_reason: str = "NONE"

    def reset(self) -> None:
        """Reset temporal state."""
        self.last_xi_skew = None
        self.last_timestamp = None
        self.breaker_active = False
        self.breaker_tripped_at = 0.0
        self.last_trip_reason = "NONE"

    def evaluate(
        self,
        bid_prices: List[float],
        bid_volumes: List[float],
        ask_prices: List[float],
        ask_volumes: List[float],
        tick_size: float = 0.01,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Evaluate order book depth elasticity across levels.
        """
        now = time.time() if timestamp is None else float(timestamp)

        # Validate input dimensions
        if len(bid_prices) != len(bid_volumes):
            raise ValueError(f"bid_prices length ({len(bid_prices)}) != bid_volumes length ({len(bid_volumes)})")
        if len(ask_prices) != len(ask_volumes):
            raise ValueError(f"ask_prices length ({len(ask_prices)}) != ask_volumes length ({len(ask_volumes)})")
        if len(bid_prices) < 2:
            raise ValueError(f"bid_prices must contain at least 2 levels, got {len(bid_prices)}")
        if len(ask_prices) < 2:
            raise ValueError(f"ask_prices must contain at least 2 levels, got {len(ask_prices)}")
        if tick_size <= 0.0:
            raise ValueError(f"tick_size must be positive, got {tick_size}")

        # Check existing cooldown
        if self.breaker_active:
            elapsed = now - self.breaker_tripped_at
            if elapsed < self.cooldown_sec:
                return {
                    "action": "HALT_ALL",
                    "circuit_breaker": True,
                    "reason": f"COOLDOWN_ACTIVE: {self.last_trip_reason} ({elapsed:.2f}s < {self.cooldown_sec}s)",
                    "xi_skew": self.last_xi_skew or 0.0,
                    "velocity": 0.0,
                    "d_bid": 0.0,
                    "d_ask": 0.0
                }
            else:
                self.breaker_active = False
                self.last_trip_reason = "NONE"

        # Check total volume
        tot_bid_vol = sum(max(0.0, float(v)) for v in bid_volumes)
        tot_ask_vol = sum(max(0.0, float(v)) for v in ask_volumes)

        if tot_bid_vol <= 1e-9 or tot_ask_vol <= 1e-9:
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": "ZERO_LIQUIDITY_DETECTED",
                "xi_skew": 0.0,
                "velocity": 0.0,
                "d_bid": 0.0,
                "d_ask": 0.0
            }

        p1_b = float(bid_prices[0])
        p1_a = float(ask_prices[0])

        # Distance weighting
        # delta_k^b = 1.0 + |p1_b - p_k^b| / tick_size
        weighted_bid_dist = sum(
            (1.0 + abs(p1_b - float(p)) / tick_size) * max(0.0, float(v))
            for p, v in zip(bid_prices, bid_volumes)
        )
        weighted_ask_dist = sum(
            (1.0 + abs(float(p) - p1_a) / tick_size) * max(0.0, float(v))
            for p, v in zip(ask_prices, ask_volumes)
        )

        d_bar_bid = weighted_bid_dist / tot_bid_vol
        d_bar_ask = weighted_ask_dist / tot_ask_vol

        denom = d_bar_bid + d_bar_ask
        xi_skew = (d_bar_bid - d_bar_ask) / denom if denom > 1e-9 else 0.0

        # Calculate temporal elasticity velocity
        velocity = 0.0
        if self.last_xi_skew is not None and self.last_timestamp is not None:
            dt = now - self.last_timestamp
            if dt > 1e-5:
                velocity = (xi_skew - self.last_xi_skew) / dt

        self.last_xi_skew = xi_skew
        self.last_timestamp = now

        # Circuit Breaker Evaluation
        abs_skew = abs(xi_skew)
        abs_vel = abs(velocity)

        if abs_skew >= self.skew_critical_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"SKEWNESS_CRITICAL_HALT: |xi_skew|={abs_skew:.3f} >= {self.skew_critical_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "xi_skew": xi_skew,
                "velocity": velocity,
                "d_bid": d_bar_bid,
                "d_ask": d_bar_ask
            }

        if abs_vel >= self.max_velocity_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"ELASTICITY_VELOCITY_BREACH: |velocity|={abs_vel:.3f}/s >= {self.max_velocity_threshold:.3f}/s"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "xi_skew": xi_skew,
                "velocity": velocity,
                "d_bid": d_bar_bid,
                "d_ask": d_bar_ask
            }

        # Asymmetric warning thresholds
        if xi_skew >= self.skew_warning_threshold:
            return {
                "action": "BLOCK_BUY",
                "circuit_breaker": False,
                "reason": f"BID_HOLLOWING_RISK: xi_skew={xi_skew:.3f} >= {self.skew_warning_threshold:.3f}",
                "xi_skew": xi_skew,
                "velocity": velocity,
                "d_bid": d_bar_bid,
                "d_ask": d_bar_ask
            }

        if xi_skew <= -self.skew_warning_threshold:
            return {
                "action": "BLOCK_SELL",
                "circuit_breaker": False,
                "reason": f"ASK_HOLLOWING_RISK: xi_skew={xi_skew:.3f} <= -{self.skew_warning_threshold:.3f}",
                "xi_skew": xi_skew,
                "velocity": velocity,
                "d_bid": d_bar_bid,
                "d_ask": d_bar_ask
            }

        return {
            "action": "ALLOW_ALL",
            "circuit_breaker": False,
            "reason": "NORMAL_ELASTICITY_EQUILIBRIUM",
            "xi_skew": xi_skew,
            "velocity": velocity,
            "d_bid": d_bar_bid,
            "d_ask": d_bar_ask
        }
