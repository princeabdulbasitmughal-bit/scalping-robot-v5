"""
Wave 482: Microstructure Resilience Recovery Tensor Guard
=========================================================
Institutional Quantitative Mathematical Formulation:
Under Large (2007) "Measuring the Resiliency of an Electronic Limit Order Book",
Biais, Hillion & Spatt (1995), and Gould et al. (2013), Limit Order Book resilience
quantifies the rate and completeness with which the order book recovers to its equilibrium
state following aggressive liquidity-consuming market orders.

Let the 3-dimensional order book state vector R(t) = [R_{spread}(t), R_{bid}(t), R_{ask}(t)] be:
1. Relative Spread Expansion:
   R_{spread}(t) = (Spread(t) - Spread_{med}) / max(Spread_{med}, 1e-4)
   When R_{spread}(t) > 2.0, spread has widened to over 3.0x its baseline value.

2. Relative Depth Ratios:
   R_{bid}(t) = D_{bid}(t) / max(D_{bid,base}, 1e-4) in [0.0, infinity)
   R_{ask}(t) = D_{ask}(t) / max(D_{ask,base}, 1e-4) in [0.0, infinity)

3. Composite Resilience Fragility Index:
   Psi_{resilience}(t) = 0.40 * min(1.0, max(0.0, R_{spread} / 2.50))
                       + 0.30 * min(1.0, max(0.0, 1.0 - R_{bid}))
                       + 0.30 * min(1.0, max(0.0, 1.0 - R_{ask})) in [0.0, 1.0]

Circuit Breakers:
1. RESILIENCE_BREAKDOWN_EXPANSION: Psi_{resilience}(t) > critical_resilience_threshold (default: > 0.70)
2. SPREAD_EXPLOSION_BREACH: R_{spread}(t) > max_spread_expansion (default: > 2.50)
3. Directional Depth Paralysis:
   - When R_{bid}(t) < 0.25 and R_{ask}(t) >= 0.60: Bid side paralyzed -> BUY entries toxic.
   - When R_{ask}(t) < 0.25 and R_{bid}(t) >= 0.60: Ask side paralyzed -> SELL entries toxic.
   - When bilateral recovery breaks down: ALL entries blocked.

When triggered, the guard isolates trade routing, ensuring execution stops until LOB resilience recovers.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave482MicrostructureResilienceRecoveryTensorGuard:
    """
    Monitors multidimensional orderbook resilience, spread expansion ratios,
    and depth replenishment tensors to prevent trading during liquidity recovery paralysis.
    """

    def __init__(
        self,
        critical_resilience_threshold: float = 0.70,
        max_spread_expansion: float = 2.50,
        paralysis_depth_floor: float = 0.25,
        healthy_depth_floor: float = 0.60,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.45 <= critical_resilience_threshold <= 0.90):
            raise ValueError(f"critical_resilience_threshold must be in [0.45, 0.90], got {critical_resilience_threshold}")
        if not (1.0 <= max_spread_expansion <= 6.0):
            raise ValueError(f"max_spread_expansion must be in [1.0, 6.0], got {max_spread_expansion}")
        if not (0.10 <= paralysis_depth_floor <= 0.40):
            raise ValueError(f"paralysis_depth_floor must be in [0.10, 0.40], got {paralysis_depth_floor}")
        if not (0.50 <= healthy_depth_floor <= 0.85):
            raise ValueError(f"healthy_depth_floor must be in [0.50, 0.85], got {healthy_depth_floor}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.critical_resilience_threshold: float = critical_resilience_threshold
        self.max_spread_expansion: float = max_spread_expansion
        self.paralysis_depth_floor: float = paralysis_depth_floor
        self.healthy_depth_floor: float = healthy_depth_floor
        self.cooldown_sec: float = cooldown_sec

        # Telemetry metrics
        self.spread_expansion_ratio: float = 0.0
        self.bid_depth_ratio: float = 1.0
        self.ask_depth_ratio: float = 1.0
        self.composite_resilience_fragility: float = 0.0
        self.sub_metrics: Dict[str, float] = {}

        self.blocked_side: Optional[str] = None
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0
        self._last_timestamp: float = -1.0

    def update(
        self,
        current_spread: float,
        baseline_spread: float,
        current_bid_depth: float,
        baseline_bid_depth: float,
        current_ask_depth: float,
        baseline_ask_depth: float,
        timestamp: float = 0.0
    ) -> bool:
        """
        Record instantaneous spread and depth values against their rolling equilibrium baselines.
        Returns True if trading is blocked, False otherwise.
        """
        inputs = [
            current_spread, baseline_spread, current_bid_depth,
            baseline_bid_depth, current_ask_depth, baseline_ask_depth
        ]
        for x in inputs:
            if not math.isfinite(x):
                raise ValueError("All spread and depth inputs must be finite numbers")
            if x <= 0.0:
                raise ValueError("Spread and depth inputs must be strictly positive")
        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._last_timestamp >= 0.0 and timestamp <= self._last_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._last_timestamp}")

        self._last_timestamp = timestamp

        # Check cooldown from prior breach
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        # Compute relative ratios
        self.spread_expansion_ratio = max(0.0, (current_spread - baseline_spread) / baseline_spread)
        self.bid_depth_ratio = current_bid_depth / baseline_bid_depth
        self.ask_depth_ratio = current_ask_depth / baseline_ask_depth

        # Normalized risk scores
        phi_spread = min(1.0, max(0.0, self.spread_expansion_ratio / 2.50))
        phi_bid = min(1.0, max(0.0, 1.0 - self.bid_depth_ratio))
        phi_ask = min(1.0, max(0.0, 1.0 - self.ask_depth_ratio))

        self.composite_resilience_fragility = float(0.40 * phi_spread + 0.30 * phi_bid + 0.30 * phi_ask)

        self.sub_metrics = {
            "phi_spread": round(phi_spread, 4),
            "phi_bid": round(phi_bid, 4),
            "phi_ask": round(phi_ask, 4)
        }

        # Evaluate Circuit Breakers
        spread_breached = (self.spread_expansion_ratio > self.max_spread_expansion)
        fragility_breached = (self.composite_resilience_fragility > self.critical_resilience_threshold)
        bid_paralyzed = (self.bid_depth_ratio < self.paralysis_depth_floor and self.ask_depth_ratio >= self.healthy_depth_floor)
        ask_paralyzed = (self.ask_depth_ratio < self.paralysis_depth_floor and self.bid_depth_ratio >= self.healthy_depth_floor)

        if spread_breached or fragility_breached or bid_paralyzed or ask_paralyzed:
            self._is_blocked = True
            self._last_breach_time = timestamp

            # Directional attribution
            if bid_paralyzed and not ask_paralyzed and not spread_breached:
                self.blocked_side = "BUY" # Bid side paralyzed -> buying is toxic
                side_note = "BID_RESILIENCE_PARALYSIS"
            elif ask_paralyzed and not bid_paralyzed and not spread_breached:
                self.blocked_side = "SELL" # Ask side paralyzed -> selling is toxic
                side_note = "ASK_RESILIENCE_PARALYSIS"
            else:
                self.blocked_side = "ALL"
                side_note = "BILATERAL_RESILIENCE_COLLAPSE"

            trigger = (
                "SPREAD_EXPLOSION_BREACH" if spread_breached else
                ("RESILIENCE_BREAKDOWN_EXPANSION" if fragility_breached else
                ("BID_RESILIENCE_PARALYSIS" if bid_paralyzed else "ASK_RESILIENCE_PARALYSIS"))
            )
            self._block_reason = (
                f"{trigger}: R_spread={self.spread_expansion_ratio:.2f} (max={self.max_spread_expansion:.2f}), "
                f"Psi={self.composite_resilience_fragility:.3f} (crit={self.critical_resilience_threshold:.3f}), "
                f"R_bid={self.bid_depth_ratio:.2f}, R_ask={self.ask_depth_ratio:.2f} [{side_note}], blocked: {self.blocked_side}"
            )
        else:
            self._is_blocked = False
            self.blocked_side = None
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked."""
        return self._is_blocked

    def is_entry_blocked(self, side: str = "BUY") -> bool:
        """OmniTrade interface compatibility. Checks if specific side is blocked."""
        if not self._is_blocked:
            return False
        if self.blocked_side == "ALL":
            return True
        return self.blocked_side == side.upper()

    @property
    def block_reason(self) -> str:
        return self._block_reason

    def get_telemetry(self) -> Dict[str, Any]:
        """Telemetry metadata for institutional risk auditing."""
        return {
            "guard": "Wave482MicrostructureResilienceRecoveryTensorGuard",
            "spread_expansion_ratio": round(self.spread_expansion_ratio, 4),
            "bid_depth_ratio": round(self.bid_depth_ratio, 4),
            "ask_depth_ratio": round(self.ask_depth_ratio, 4),
            "composite_resilience_fragility": round(self.composite_resilience_fragility, 4),
            "sub_metrics": self.sub_metrics,
            "max_spread_expansion": self.max_spread_expansion,
            "critical_resilience_threshold": self.critical_resilience_threshold,
            "blocked_side": self.blocked_side,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason
        }

    def reset(self) -> None:
        """Reset internal state."""
        self.spread_expansion_ratio = 0.0
        self.bid_depth_ratio = 1.0
        self.ask_depth_ratio = 1.0
        self.composite_resilience_fragility = 0.0
        self.sub_metrics.clear()
        self.blocked_side = None
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
        self._last_timestamp = -1.0
