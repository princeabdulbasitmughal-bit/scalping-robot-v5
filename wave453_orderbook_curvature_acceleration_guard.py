"""
Wave 453: Orderbook Micro-Structural Curvature Acceleration Guard
================================================================
Institutional Quantitative Mathematical Formulation:
Under Gould et al. (2013) "Limit Order Books" and Biais et al. (1995), the aggregated
order book depth profile Q(x) as a function of tick price distance x = |p - p_mid|
exhibits characteristic non-linear geometric shape:
    Q(x) = alpha * x + (1/2) * kappa * x^2 + O(x^3)

Where:
- alpha = dQ/dx is the liquidity density at the inside spread.
- kappa = d^2Q/dx^2 is the orderbook curvature (liquidity cushion convexity).

In stationary liquid books, kappa > 0 (convex accumulation of depth buffers against large sweeps).
During predatory spoofing pullbacks or sudden institutional liquidity withdrawal,
kappa collapses into a deep concave cliff (kappa < 0), and the instantaneous curvature acceleration:
    a_kappa(t) = [kappa(t) - kappa(t - dt)] / max(dt, epsilon)
spikes violently negative (a_kappa < -max_curvature_acceleration, default: < -2.50 s^-1).

This signals that depth behind the top-of-book is rapidly vanishing, creating a hollow
order book where any market order will suffer severe slippage. The guard triggers an immediate
lockout upon detection of concave curvature acceleration cliffs.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave453OrderbookCurvatureAccelerationGuard:
    """
    Evaluates order book depth curvature kappa and curvature acceleration a_kappa
    to detect liquidity cliff formation and predatory depth withdrawal.
    """

    def __init__(
        self,
        window_size: int = 20,
        min_kappa_floor: float = -1.50,
        max_negative_acceleration: float = 2.50
    ) -> None:
        if window_size < 10:
            raise ValueError(f"window_size must be >= 10, got {window_size}")
        if min_kappa_floor >= 0.0:
            raise ValueError(f"min_kappa_floor must be negative, got {min_kappa_floor}")
        if max_negative_acceleration <= 0.10:
            raise ValueError(f"max_negative_acceleration must be > 0.10, got {max_negative_acceleration}")

        self.window_size: int = window_size
        self.min_kappa_floor: float = min_kappa_floor
        self.max_negative_acceleration: float = max_negative_acceleration

        # History buffers
        self._kappas: List[float] = []
        self._timestamps: List[float] = []

        # Current state
        self.current_kappa: float = 0.50
        self.curvature_acceleration: float = 0.0
        self._is_blocked: bool = False
        self._block_reason: str = ""

    def update(self, tier_depths: List[float], tier_distances: List[float], timestamp: float) -> bool:
        """
        Record cumulative tier depths Q and price distances x from midprice.
        Returns True if trading is blocked, False otherwise.
        """
        if len(tier_depths) < 3 or len(tier_distances) < 3:
            raise ValueError("tier_depths and tier_distances must have at least 3 levels")
        if len(tier_depths) != len(tier_distances):
            raise ValueError("tier_depths and tier_distances must have identical length")
        if any(d < 0.0 or not math.isfinite(d) for d in tier_depths):
            raise ValueError("All tier_depths must be non-negative and finite")
        if any(x <= 0.0 or not math.isfinite(x) for x in tier_distances):
            raise ValueError("All tier_distances must be positive and finite")
        if self._timestamps and timestamp <= self._timestamps[-1]:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._timestamps[-1]}")

        # Polynomial fit: Q(x) = c0 + c1 * x + c2 * x^2
        # Curvature kappa = 2 * c2
        x = np.array(tier_distances, dtype=np.float64)
        y = np.array(tier_depths, dtype=np.float64)

        try:
            poly = np.polyfit(x, y, deg=2)
            c2 = float(poly[0])
            kappa = 2.0 * c2
        except Exception:
            kappa = 0.0

        self.current_kappa = kappa
        self._kappas.append(kappa)
        self._timestamps.append(float(timestamp))

        if len(self._kappas) > self.window_size:
            self._kappas.pop(0)
            self._timestamps.pop(0)

        if len(self._kappas) < 3:
            self._is_blocked = False
            self._block_reason = "INSUFFICIENT_DATA"
            return False

        # Calculate curvature acceleration a_kappa = d(kappa)/dt
        dt = max(1e-4, timestamp - self._timestamps[-2])
        d_kappa = self._kappas[-1] - self._kappas[-2]
        self.curvature_acceleration = float(d_kappa / dt)

        # Safety evaluation
        if self.current_kappa < self.min_kappa_floor:
            self._is_blocked = True
            self._block_reason = (
                f"ORDERBOOK_HOLLOW_CLIFF: Curvature kappa={self.current_kappa:.3f} < "
                f"floor {self.min_kappa_floor:.3f} (severe concave depth hollow)"
            )
        elif self.curvature_acceleration < -self.max_negative_acceleration:
            self._is_blocked = True
            self._block_reason = (
                f"RAPID_DEPTH_CURVATURE_COLLAPSE: Curvature acceleration {self.curvature_acceleration:.2f} s^-1 < "
                f"cap -{self.max_negative_acceleration:.2f} s^-1"
            )
        else:
            self._is_blocked = False
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked by the Curvature Acceleration Guard."""
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
            "guard": "Wave453OrderbookCurvatureAccelerationGuard",
            "current_kappa": round(self.current_kappa, 4),
            "curvature_acceleration_hz": round(self.curvature_acceleration, 4),
            "min_kappa_floor": self.min_kappa_floor,
            "max_negative_acceleration": self.max_negative_acceleration,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason,
            "sample_depth": len(self._kappas)
        }

    def reset(self) -> None:
        """Reset internal buffer state."""
        self._kappas.clear()
        self._timestamps.clear()
        self.current_kappa = 0.50
        self.curvature_acceleration = 0.0
        self._is_blocked = False
        self._block_reason = ""
