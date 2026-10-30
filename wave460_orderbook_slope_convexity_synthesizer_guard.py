"""
Wave 460: Dynamic Level-2 Order Book Slope Convexity Invariant Synthesizer Guard
================================================================================
Institutional Quantitative Mathematical Formulation:
Under Biais, Hillion & Spatt (1995) "An Empirical Analysis of the Limit Order Book",
Gould, Porter, Williams, McDonald, Fenn & Howison (2013), and Lehalle & Mounjid (2017),
the structural resilience and market-depth profile of a Limit Order Book (LOB) is governed
by its Cumulative Depth Function Q(delta) as a function of tick distance delta = |P - P_mid|.

For both Bid and Ask order books across top K levels (k = 1, ..., K):
1. First Derivative (Liquidity Density Slope):
   S_bid = dQ_bid / d(delta),  S_ask = dQ_ask / d(delta)
   Measures instantaneous rate of resting liquidity replenishment away from the spread.
2. Second Derivative (Microstructure Convexity):
   C_bid = d^2 Q_bid / d(delta)^2,  C_ask = d^2 Q_ask / d(delta)^2
   Healthy, institutional order books exhibit strictly POSITIVE convexity (C > 0),
   providing a protective cushion where depth grows convexly away from the midprice.

Pathological Regimes:
1. Concave Liquidity Cliff (C < -1.50):
   Depth thins out at outer levels, creating an inverted concave cliff. Any medium-sized
   market order punches through the book, causing catastrophic slippage and gap runs.
2. Slope Asymmetry Ratio (S_ask / max(S_bid, 1e-4) > 3.0x or < 0.33x):
   Extreme directional imbalance in depth slope preceding aggressive informed sweeps.

Grand Sovereign Synthesis (Waves 455 to 460 Canopy Master):
The Composite Microstructure Invariant Score I_composite unifies:
- LOB Slope and Convexity Fragility
- Multi-Scale Fragility Index (Wave 455)
- Jump-Diffusion Variance Ratio (Wave 456)
- Cross-Venue Kyle Lambda Divergence (Wave 457)
- Multi-Tier Queue Depletion Survival (Wave 458)
- Hawkes Supercritical Contagion Spectral Radius (Wave 459)

When I_composite > critical_threshold (default: > 0.68) or when C_side < min_convexity (default: < -1.80),
the guard trips the Sovereign Canopy Invariant Breaker, protecting capital from flash evaporation.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave460OrderbookSlopeConvexitySynthesizerGuard:
    """
    Evaluates order book slope, convexity, and synthesizes institutional microstructural
    invariants across Waves 455-460 into a master sovereign canopy defense.
    """

    def __init__(
        self,
        critical_composite_threshold: float = 0.68,
        min_convexity_floor: float = -1.80,
        max_slope_asymmetry_ratio: float = 3.20,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.40 <= critical_composite_threshold <= 0.90):
            raise ValueError(f"critical_composite_threshold must be in [0.40, 0.90], got {critical_composite_threshold}")
        if min_convexity_floor > -0.50:
            raise ValueError(f"min_convexity_floor must be <= -0.50, got {min_convexity_floor}")
        if max_slope_asymmetry_ratio <= 1.20:
            raise ValueError(f"max_slope_asymmetry_ratio must be > 1.20, got {max_slope_asymmetry_ratio}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.critical_composite_threshold: float = critical_composite_threshold
        self.min_convexity_floor: float = min_convexity_floor
        self.max_slope_asymmetry_ratio: float = max_slope_asymmetry_ratio
        self.cooldown_sec: float = cooldown_sec

        # Telemetry metrics
        self.bid_slope: float = 0.0
        self.ask_slope: float = 0.0
        self.bid_convexity: float = 0.0
        self.ask_convexity: float = 0.0
        self.slope_asymmetry: float = 1.0
        self.composite_invariant: float = 0.0
        self.blocked_side: Optional[str] = None
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0
        self._last_timestamp: float = -1.0

    def update(
        self,
        bid_depths: List[float],
        ask_depths: List[float],
        tick_distances: List[float],
        multiscale_fragility: float = 0.10,
        jump_variance_ratio: float = 0.05,
        kyle_divergence: float = 0.10,
        queue_depletion_hazard: float = 0.10,
        hawkes_spectral_radius: float = 0.20,
        timestamp: float = 0.0
    ) -> bool:
        """
        Update the model with LOB level depth arrays and upstream wave risk metrics.
        Returns True if trading is blocked, False otherwise.
        """
        if len(bid_depths) < 3 or len(ask_depths) < 3 or len(tick_distances) < 3:
            raise ValueError("Must provide at least 3 levels for bid/ask depths and distances")

        if len(bid_depths) != len(tick_distances) or len(ask_depths) != len(tick_distances):
            raise ValueError("Depth arrays and tick_distances array must have matching lengths")

        if self._last_timestamp >= 0.0 and timestamp <= self._last_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._last_timestamp}")

        for arr, name in [(bid_depths, "bid_depths"), (ask_depths, "ask_depths")]:
            for v in arr:
                if v < 0.0 or not math.isfinite(v):
                    raise ValueError(f"{name} values must be non-negative and finite")

        for d in tick_distances:
            if d <= 0.0 or not math.isfinite(d):
                raise ValueError("tick_distances must be strictly positive and finite")

        self._last_timestamp = timestamp

        # Cooldown check
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        # Cumulative Depth Profiles
        cum_bid = np.cumsum(np.array(bid_depths, dtype=np.float64))
        cum_ask = np.cumsum(np.array(ask_depths, dtype=np.float64))
        dist = np.array(tick_distances, dtype=np.float64)

        # 2nd-degree polynomial fit: Q(x) = c0 + c1*x + c2*x^2
        # Slope = c1, Convexity = 2*c2
        poly_bid = np.polyfit(dist, cum_bid, deg=2)
        poly_ask = np.polyfit(dist, cum_ask, deg=2)

        self.bid_slope = max(0.0, float(poly_bid[1]))
        self.bid_convexity = float(2.0 * poly_bid[0])

        self.ask_slope = max(0.0, float(poly_ask[1]))
        self.ask_convexity = float(2.0 * poly_ask[0])

        # Slope Asymmetry
        max_s = max(self.bid_slope, self.ask_slope, 1e-4)
        min_s = max(min(self.bid_slope, self.ask_slope), 1e-4)
        self.slope_asymmetry = float(max_s / min_s)

        # Level-2 Structural Fragility Score
        # Negative convexity adds to fragility
        conv_penalty = max(0.0, -self.bid_convexity) + max(0.0, -self.ask_convexity)
        norm_conv_penalty = min(1.0, conv_penalty / 4.0)

        # Asymmetry penalty
        norm_asym_penalty = min(1.0, max(0.0, self.slope_asymmetry - 1.0) / (self.max_slope_asymmetry_ratio - 1.0))

        # Grand Invariant Synthesis across Waves 455-460
        # Weights sum to 1.0:
        # L2 Convexity (15%), L2 Asymmetry (10%), Fragility (20%), Jump (15%), Kyle (20%), Hawkes (20%)
        self.composite_invariant = float(
            0.15 * norm_conv_penalty +
            0.10 * norm_asym_penalty +
            0.20 * min(1.0, multiscale_fragility) +
            0.15 * min(1.0, jump_variance_ratio * 2.0) +
            0.20 * min(1.0, kyle_divergence) +
            0.20 * min(1.0, hawkes_spectral_radius)
        )

        # Circuit Breaker Checks
        if self.bid_convexity < self.min_convexity_floor:
            self._is_blocked = True
            self.blocked_side = "BUY"
            self._last_breach_time = timestamp
            self._block_reason = (
                f"CONCAVE_LIQUIDITY_CLIFF_BID: Bid convexity C_bid={self.bid_convexity:.2f} < "
                f"floor {self.min_convexity_floor:.2f}"
            )
        elif self.ask_convexity < self.min_convexity_floor:
            self._is_blocked = True
            self.blocked_side = "SELL"
            self._last_breach_time = timestamp
            self._block_reason = (
                f"CONCAVE_LIQUIDITY_CLIFF_ASK: Ask convexity C_ask={self.ask_convexity:.2f} < "
                f"floor {self.min_convexity_floor:.2f}"
            )
        elif self.composite_invariant > self.critical_composite_threshold:
            self._is_blocked = True
            self.blocked_side = "ALL"
            self._last_breach_time = timestamp
            self._block_reason = (
                f"GRAND_SOVEREIGN_CANOPY_BREACH: Composite invariant I={self.composite_invariant:.3f} > "
                f"threshold {self.critical_composite_threshold:.3f}"
            )
        else:
            self._is_blocked = False
            self.blocked_side = None
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if any trading is blocked."""
        return self._is_blocked

    def is_entry_blocked(self, side: str = "BUY") -> bool:
        """OmniTrade interface compatibility."""
        if not self._is_blocked:
            return False
        if self.blocked_side in ("ALL", None):
            return True
        return side.upper() == self.blocked_side

    @property
    def block_reason(self) -> str:
        return self._block_reason

    def get_telemetry(self) -> Dict[str, Any]:
        """Telemetry metadata for institutional risk auditing."""
        return {
            "guard": "Wave460OrderbookSlopeConvexitySynthesizerGuard",
            "bid_slope": round(self.bid_slope, 4),
            "ask_slope": round(self.ask_slope, 4),
            "bid_convexity": round(self.bid_convexity, 4),
            "ask_convexity": round(self.ask_convexity, 4),
            "slope_asymmetry": round(self.slope_asymmetry, 2),
            "composite_invariant": round(self.composite_invariant, 4),
            "critical_composite_threshold": self.critical_composite_threshold,
            "min_convexity_floor": self.min_convexity_floor,
            "blocked_side": self.blocked_side,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason
        }

    def reset(self) -> None:
        """Reset internal buffers and state."""
        self.bid_slope = 0.0
        self.ask_slope = 0.0
        self.bid_convexity = 0.0
        self.ask_convexity = 0.0
        self.slope_asymmetry = 1.0
        self.composite_invariant = 0.0
        self.blocked_side = None
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
        self._last_timestamp = -1.0
