"""
Wave 449: Liquidity Black Hole Horizon Guard
============================================
Institutional Quantitative Mathematical Formulation:
Under Morris & Shin (2004) "Liquidity Black Holes" and Danielsson & Zigrand (2008),
severe market dislocations occur when traders operate under common risk constraints
(e.g., Value-at-Risk limits or dynamic delta hedging). When a critical market shock
occurs, forced liquidations trigger further price movements, causing other participants
to hit stop-losses simultaneously.

This feedback loop results in the complete evaporation of order book depth across all tiers:
    D(t) = sum_{k=1}^K (Q_k^{bid}(t) + Q_k^{ask}(t))

The relative depth evaporation rate across horizon tau is:
    Delta D_tau = [D(t) - D(t - tau)] / max(D(t - tau), epsilon)

The instantaneous depth evaporation velocity:
    v_evap(t) = - (1 / D(t)) * (dD(t) / dt)

When:
1. Cumulative depth contraction Delta D_tau < -max_depth_contraction_ratio (e.g. > 65% of
   aggregated liquidity vanishes within window tau), or
2. Depth evaporation velocity v_evap > max_evaporation_velocity (e.g. > 1.50 sec^-1),
the order book has entered the "Event Horizon" of a Liquidity Black Hole.

In this catastrophic state, slippage becomes unbounded and any market order will suffer
severe execution penalty. The guard mandates an instantaneous hard freeze on all trade submissions.
"""

import math
from typing import List, Dict, Any, Optional


class Wave449LiquidityBlackHoleHorizonGuard:
    """
    Guards against liquidity black holes, positive feedback orderbook evaporation cascades,
    and flash collapse regimes across all orderbook tiers.
    """

    def __init__(
        self,
        window_size: int = 25,
        max_depth_contraction_ratio: float = 0.65,
        max_evaporation_velocity: float = 1.50,
        min_depth_floor: float = 1.0
    ) -> None:
        if window_size < 10:
            raise ValueError(f"window_size must be >= 10, got {window_size}")
        if not (0.20 <= max_depth_contraction_ratio < 1.0):
            raise ValueError(f"max_depth_contraction_ratio must be in [0.20, 1.0), got {max_depth_contraction_ratio}")
        if max_evaporation_velocity <= 0.10:
            raise ValueError(f"max_evaporation_velocity must be > 0.10, got {max_evaporation_velocity}")

        self.window_size: int = window_size
        self.max_depth_contraction_ratio: float = max_depth_contraction_ratio
        self.max_evaporation_velocity: float = max_evaporation_velocity
        self.min_depth_floor: float = min_depth_floor

        # State history
        self._depth_history: List[float] = []
        self._timestamps: List[float] = []

        # Current state
        self.cumulative_contraction: float = 0.0
        self.evaporation_velocity: float = 0.0
        self._is_blocked: bool = False
        self._block_reason: str = ""

    def update(self, total_depth: float, timestamp: float) -> bool:
        """
        Record aggregated book depth and timestamp.
        Returns True if trading is blocked, False otherwise.
        """
        if total_depth < 0.0 or not math.isfinite(total_depth):
            raise ValueError(f"total_depth must be non-negative and finite, got {total_depth}")
        if self._timestamps and timestamp <= self._timestamps[-1]:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._timestamps[-1]}")

        self._depth_history.append(float(total_depth))
        self._timestamps.append(float(timestamp))

        if len(self._depth_history) > self.window_size:
            self._depth_history.pop(0)
            self._timestamps.pop(0)

        if len(self._depth_history) < 5:
            self._is_blocked = False
            self._block_reason = "INSUFFICIENT_DATA"
            return False

        current_d = self._depth_history[-1]
        prior_d = self._depth_history[0]
        dt = max(1e-4, timestamp - self._timestamps[-2])

        # Immediate floor breach check
        if current_d < self.min_depth_floor:
            self._is_blocked = True
            self._block_reason = (
                f"ABSOLUTE_LIQUIDITY_COLLAPSE: Book depth {current_d:.2f} < "
                f"minimum floor {self.min_depth_floor:.2f}"
            )
            return True

        # Cumulative contraction over window
        if prior_d > 1e-6:
            self.cumulative_contraction = (current_d - prior_d) / prior_d
        else:
            self.cumulative_contraction = 0.0

        # Instantaneous evaporation velocity
        prev_d = self._depth_history[-2]
        d_diff = current_d - prev_d
        if current_d > 1e-6:
            self.evaporation_velocity = max(0.0, - (d_diff / dt) / current_d)
        else:
            self.evaporation_velocity = 999.0

        # Safety evaluation
        if self.cumulative_contraction < -self.max_depth_contraction_ratio:
            self._is_blocked = True
            self._block_reason = (
                f"LIQUIDITY_BLACK_HOLE_EVENT_HORIZON: Cumulative depth contraction "
                f"{abs(self.cumulative_contraction):.1%} > threshold {self.max_depth_contraction_ratio:.1%}"
            )
        elif self.evaporation_velocity > self.max_evaporation_velocity:
            self._is_blocked = True
            self._block_reason = (
                f"CATASTROPHIC_DEPTH_EVAPORATION: Velocity {self.evaporation_velocity:.2f} s^-1 > "
                f"threshold {self.max_evaporation_velocity:.2f} s^-1"
            )
        else:
            self._is_blocked = False
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked by the Liquidity Black Hole Guard."""
        return self._is_blocked

    def is_entry_blocked(self, side: str = "BUY") -> bool:
        """OmniTrade interface compatibility."""
        return self._is_blocked

    @property
    def block_reason(self) -> str:
        return self._block_reason

    def get_telemetry(self) -> Dict[str, Any]:
        """Telemetry metadata for institutional risk auditing."""
        return {
            "guard": "Wave449LiquidityBlackHoleHorizonGuard",
            "cumulative_contraction_pct": round(self.cumulative_contraction * 100, 2),
            "evaporation_velocity_hz": round(self.evaporation_velocity, 4),
            "max_depth_contraction_ratio": self.max_depth_contraction_ratio,
            "max_evaporation_velocity": self.max_evaporation_velocity,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason,
            "current_depth": self._depth_history[-1] if self._depth_history else 0.0
        }

    def reset(self) -> None:
        """Reset internal buffer state."""
        self._depth_history.clear()
        self._timestamps.clear()
        self.cumulative_contraction = 0.0
        self.evaporation_velocity = 0.0
        self._is_blocked = False
        self._block_reason = ""
