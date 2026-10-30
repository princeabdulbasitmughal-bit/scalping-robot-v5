"""
Wave 470: Multi-Tier Depth Curvature Acceleration Canopy Guard
=============================================================
Institutional Quantitative Mathematical Formulation:
Under Biais, Hillion & Spatt (1995), Bouchaud, Mézard & Potters (2002) "Statistical
Properties of Stock Order Books: Empirical Results and Models", and Cont & Kukanov (2014),
order book resilience against aggressive order flow is determined by the geometric
profile of resting volume as a function of distance delta = |P_k - P_mid| from the midprice.

Let Q(delta) be the cumulative depth profile across K discrete price tiers (k = 1, ..., K):
1. Discrete Liquidity Slope (First Derivative):
   S(delta_k) = [Q(delta_k) - Q(delta_{k-1})] / [delta_k - delta_{k-1}]
2. Discrete Depth Curvature (Second Derivative):
   kappa(delta_k) = [S(delta_k) - S(delta_{k-1})] / [delta_k - delta_{k-1}]

Microstructure Geometry:
- Healthy Resilience (kappa > 0, strictly convex):
  Volume thickens exponentially away from the inside quotes, forming an impenetrable cushion.
- Liquidity Cliff / Air Pocket (kappa < -1.20, deeply concave):
  Volume evaporates at outer levels. The order book is a fragile hollow shell. Any aggressive
  institutional sweep slices through all levels with severe flash slippage.

Temporal Curvature Acceleration:
The temporal rate of change of curvature is:
   alpha_kappa(t) = d(kappa) / dt = [kappa(t) - kappa(t - Delta t)] / Delta t  (sec^-1)
When alpha_kappa(t) < max_curvature_degradation_velocity (e.g., < -2.20 sec^-1), resting orders
are being cancelled or swept at an accelerating rate, indicating an imminent structural breakdown.

Canopy Synthesis:
Unifies Bid/Ask Curvature, Temporal Degradation Acceleration, and Upstream Liquidity
Black Hole Contraction (Wave 469) into a composite curvature canopy fragility index:
   Omega_{470}(t) = 0.40 * Phi_{concave} + 0.35 * Phi_{accel} + 0.25 * Phi_{blackhole}

Circuit Breakers:
1. CURVATURE_CONCAVITY_CLIFF: kappa_min(t) < min_curvature_floor (default: < -1.50)
2. CURVATURE_ACCELERATION_BURST: alpha_kappa(t) < max_negative_acceleration (default: < -2.20 sec^-1)
3. CANOPY_CURVATURE_FRAGILITY_BREACH: Omega_{470}(t) > critical_canopy_threshold (default: > 0.65)

When triggered, the guard immediately freezes order routing, shielding capital from execution into air pockets.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave470DepthCurvatureAccelerationCanopyGuard:
    """
    Evaluates multi-tier orderbook curvature, temporal curvature acceleration,
    and synthesizes upstream liquidity collapse metrics into a robust canopy defense.
    """

    def __init__(
        self,
        critical_canopy_threshold: float = 0.65,
        min_curvature_floor: float = -1.50,
        max_negative_acceleration: float = -2.20,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.40 <= critical_canopy_threshold <= 0.90):
            raise ValueError(f"critical_canopy_threshold must be in [0.40, 0.90], got {critical_canopy_threshold}")
        if min_curvature_floor > -0.50:
            raise ValueError(f"min_curvature_floor must be <= -0.50, got {min_curvature_floor}")
        if max_negative_acceleration > -0.50:
            raise ValueError(f"max_negative_acceleration must be <= -0.50, got {max_negative_acceleration}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.critical_canopy_threshold: float = critical_canopy_threshold
        self.min_curvature_floor: float = min_curvature_floor
        self.max_negative_acceleration: float = max_negative_acceleration
        self.cooldown_sec: float = cooldown_sec

        # Telemetry metrics
        self.bid_curvature: float = 0.0
        self.ask_curvature: float = 0.0
        self.min_curvature: float = 0.0
        self.curvature_acceleration: float = 0.0
        self.composite_canopy_index: float = 0.0
        self.blocked_side: Optional[str] = None
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0
        self._last_timestamp: float = -1.0
        self._prev_curvature: Optional[float] = None

    def _compute_curvature(self, depths: List[float], tick_distances: List[float]) -> float:
        """
        Compute discrete second derivative (curvature) of cumulative depth profile.
        Requires at least 3 discrete depth levels.
        """
        q = np.cumsum(depths)
        deltas = np.array(tick_distances, dtype=np.float64)

        # First derivative (slopes)
        d_deltas = np.diff(deltas)
        d_deltas = np.where(d_deltas <= 0.0, 1e-4, d_deltas)
        slopes = np.diff(q) / d_deltas

        # Second derivative (curvature)
        if len(slopes) < 2:
            return 0.0
        d_deltas_mid = (d_deltas[:-1] + d_deltas[1:]) * 0.5
        d_deltas_mid = np.where(d_deltas_mid <= 0.0, 1e-4, d_deltas_mid)
        curvatures = np.diff(slopes) / d_deltas_mid
        return float(np.mean(curvatures))

    def update(
        self,
        bid_depths: List[float],
        ask_depths: List[float],
        tick_distances: List[float],
        upstream_blackhole_risk: float = 0.10,
        timestamp: float = 0.0
    ) -> bool:
        """
        Update the model with multi-tier LOB depth vectors and upstream blackhole risk.
        Returns True if trading is blocked, False otherwise.
        """
        if len(bid_depths) < 3 or len(ask_depths) < 3 or len(tick_distances) < 3:
            raise ValueError("bid_depths, ask_depths, and tick_distances must contain at least 3 levels")
        if not math.isfinite(upstream_blackhole_risk) or upstream_blackhole_risk < 0.0:
            raise ValueError("upstream_blackhole_risk must be non-negative and finite")
        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._last_timestamp >= 0.0 and timestamp <= self._last_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._last_timestamp}")

        dt = (timestamp - self._last_timestamp) if self._last_timestamp >= 0.0 else 0.0
        self._last_timestamp = timestamp

        # Check cooldown from prior breach
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        self.bid_curvature = self._compute_curvature(bid_depths, tick_distances)
        self.ask_curvature = self._compute_curvature(ask_depths, tick_distances)
        self.min_curvature = min(self.bid_curvature, self.ask_curvature)

        # Compute temporal acceleration of curvature
        if self._prev_curvature is not None and dt > 0.0:
            self.curvature_acceleration = (self.min_curvature - self._prev_curvature) / dt
        else:
            self.curvature_acceleration = 0.0
        self._prev_curvature = self.min_curvature

        # Normalize components into risk scores [0.0, 1.0]
        concavity_risk = min(1.0, max(0.0, -self.min_curvature / 2.0))
        accel_risk = min(1.0, max(0.0, -self.curvature_acceleration / 3.0))
        blackhole_risk = min(1.0, max(0.0, upstream_blackhole_risk))

        # Composite canopy index Omega_{470}
        self.composite_canopy_index = (
            0.40 * concavity_risk +
            0.35 * accel_risk +
            0.25 * blackhole_risk
        )

        # Evaluate Circuit Breakers
        cliff_breached = (self.min_curvature < self.min_curvature_floor)
        accel_breached = (self.curvature_acceleration < self.max_negative_acceleration)
        canopy_breached = (self.composite_canopy_index > self.critical_canopy_threshold)

        if cliff_breached or accel_breached or canopy_breached:
            self._is_blocked = True
            self._last_breach_time = timestamp

            # Directional attribution
            if cliff_breached and not canopy_breached:
                if self.bid_curvature < self.min_curvature_floor and self.ask_curvature >= self.min_curvature_floor:
                    self.blocked_side = "BUY"
                    side_note = "BID_CURVATURE_CLIFF"
                elif self.ask_curvature < self.min_curvature_floor and self.bid_curvature >= self.min_curvature_floor:
                    self.blocked_side = "SELL"
                    side_note = "ASK_CURVATURE_CLIFF"
                else:
                    self.blocked_side = "ALL"
                    side_note = "BILATERAL_CURVATURE_CLIFF"
            else:
                self.blocked_side = "ALL"
                side_note = "COMPOSITE_CANOPY_COLLAPSE"

            trigger = (
                "CURVATURE_CONCAVITY_CLIFF" if cliff_breached else
                ("CURVATURE_ACCELERATION_BURST" if accel_breached else "CANOPY_CURVATURE_FRAGILITY_BREACH")
            )
            self._block_reason = (
                f"{trigger}: kappa_min={self.min_curvature:.3f} (floor={self.min_curvature_floor:.3f}), "
                f"alpha_kappa={self.curvature_acceleration:.2f}/s (max_neg={self.max_negative_acceleration:.2f}/s), "
                f"Omega={self.composite_canopy_index:.3f} [{side_note}], blocked: {self.blocked_side}"
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
            "guard": "Wave470DepthCurvatureAccelerationCanopyGuard",
            "bid_curvature": round(self.bid_curvature, 4),
            "ask_curvature": round(self.ask_curvature, 4),
            "min_curvature": round(self.min_curvature, 4),
            "curvature_acceleration": round(self.curvature_acceleration, 4),
            "composite_canopy_index": round(self.composite_canopy_index, 4),
            "critical_canopy_threshold": self.critical_canopy_threshold,
            "min_curvature_floor": self.min_curvature_floor,
            "max_negative_acceleration": self.max_negative_acceleration,
            "blocked_side": self.blocked_side,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason
        }

    def reset(self) -> None:
        """Reset internal state."""
        self.bid_curvature = 0.0
        self.ask_curvature = 0.0
        self.min_curvature = 0.0
        self.curvature_acceleration = 0.0
        self.composite_canopy_index = 0.0
        self.blocked_side = None
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
        self._last_timestamp = -1.0
        self._prev_curvature = None
