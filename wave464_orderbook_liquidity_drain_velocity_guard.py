"""
Wave 464: Multi-Level Volumetric Liquidity Drain Velocity Vector Guard
======================================================================
Institutional Quantitative Mathematical Formulation:
Under Cartea, Jaimungal & Penalva (2015) "Algorithmic and High-Frequency Trading"
and Stoikov (2018) "The Micro-Price: a High-Frequency Estimator of Future Prices",
the instantaneous evacuation of depth across multiple Limit Order Book (LOB) tiers
reveals aggressive hidden sweep orders and predatory liquidity withdrawal.

Let V(t) = [V_1(t), ..., V_K(t)]^T be the resting depth vector across top K=5 levels.
Over time interval Delta t = t - t_{prev}:
1. Per-Tier Liquidity Evacuation Rate (lots/sec or shares/sec):
    d_k(t) = max(0.0, -(V_k(t) - V_k(t - Delta t)) / Delta t)

2. Normalized Proportional Drain Velocity (1/sec):
    d_hat_k(t) = d_k(t) / max(V_k(t - Delta t), 1.0)

3. Composite Weighted Multi-Level Drain Velocity:
    D_drain(t) = sum_{k=1}^K w_k * d_hat_k(t)
    where w = [0.35, 0.25, 0.20, 0.12, 0.08] for tiers 1 to 5

4. Drain Acceleration (1/sec^2):
    a_drain = (D_drain(t) - D_drain(t_prev)) / Delta t

In calm, institutional markets:
- Replenishment matches or exceeds drainage: D_drain < 0.50 s^-1.
- Depth changes smoothly without sudden multi-level collapse.

Pathological Regimes:
1. Flash Volumetric Evacuation (Predatory Sweep / Depth Pulling):
   D_drain > max_drain_velocity (default: > 2.20 s^-1)
   More than 200% of prevailing resting book depth is being drained or cancelled per second.
2. Exponential Drain Acceleration:
   a_drain > max_drain_acceleration (default: > 3.50 s^-2) and D_drain > 1.20 s^-1
   The rate of liquidity depletion is rapidly accelerating, indicating an incoming cascade.

When multi-level drain velocity breaches safety thresholds, the guard freezes active
quoting and order dispatch to prevent severe adverse execution fills.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave464OrderbookLiquidityDrainVelocityGuard:
    """
    Evaluates multi-level limit order book volumetric drainage velocity and acceleration
    to protect against predatory sweeps and sudden depth collapse.
    """

    NUM_LEVELS = 5
    DEFAULT_WEIGHTS = np.array([0.35, 0.25, 0.20, 0.12, 0.08], dtype=np.float64)

    def __init__(
        self,
        max_drain_velocity: float = 2.20,
        max_drain_acceleration: float = 3.50,
        cooldown_sec: float = 2.0
    ) -> None:
        if max_drain_velocity <= 0.50:
            raise ValueError(f"max_drain_velocity must be > 0.50, got {max_drain_velocity}")
        if max_drain_acceleration <= 0.50:
            raise ValueError(f"max_drain_acceleration must be > 0.50, got {max_drain_acceleration}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.max_drain_velocity: float = max_drain_velocity
        self.max_drain_acceleration: float = max_drain_acceleration
        self.cooldown_sec: float = cooldown_sec

        # State tracking
        self._prev_depths: Optional[np.ndarray] = None
        self._prev_timestamp: float = -1.0
        self._prev_drain_velocity: float = 0.0

        # State telemetry
        self.drain_velocity: float = 0.0
        self.drain_acceleration: float = 0.0
        self.tier_drain_rates: List[float] = [0.0] * self.NUM_LEVELS
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0

    def update(self, depths: List[float], timestamp: float) -> bool:
        """
        Record a new snapshot of resting depth across top 5 levels.
        Returns True if trading is blocked, False otherwise.
        """
        if len(depths) < self.NUM_LEVELS:
            raise ValueError(f"depths must contain at least {self.NUM_LEVELS} levels, got {len(depths)}")

        for d in depths[:self.NUM_LEVELS]:
            if not math.isfinite(d) or d < 0.0:
                raise ValueError(f"depth values must be non-negative and finite, got {d}")

        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._prev_timestamp >= 0.0 and timestamp <= self._prev_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._prev_timestamp}")

        curr_depths = np.array(depths[:self.NUM_LEVELS], dtype=np.float64)

        # Check cooldown
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._prev_depths = curr_depths
            self._prev_timestamp = timestamp
            self._is_blocked = True
            return True

        if self._prev_depths is None:
            self._prev_depths = curr_depths
            self._prev_timestamp = timestamp
            self._is_blocked = False
            self._block_reason = "INITIALIZING"
            return False

        dt = timestamp - self._prev_timestamp
        if dt < 1e-6:
            dt = 1e-6

        # Calculate per-tier drainage velocity
        depth_change = curr_depths - self._prev_depths
        evacuation = np.maximum(0.0, -depth_change) # positive if depth decreased
        drain_rates_raw = evacuation / dt
        norm_drain_rates = drain_rates_raw / np.maximum(self._prev_depths, 1.0)

        self.tier_drain_rates = [round(float(x), 4) for x in norm_drain_rates]

        # Composite weighted drain velocity
        self.drain_velocity = float(np.dot(self.DEFAULT_WEIGHTS, norm_drain_rates))

        # Drain acceleration
        self.drain_acceleration = float((self.drain_velocity - self._prev_drain_velocity) / dt)

        # Update historical state
        self._prev_depths = curr_depths
        self._prev_timestamp = timestamp
        self._prev_drain_velocity = self.drain_velocity

        # Evaluate Circuit Breakers
        flash_evacuation = (self.drain_velocity > self.max_drain_velocity)
        drain_accel_spike = (
            self.drain_acceleration > self.max_drain_acceleration and
            self.drain_velocity > 1.20
        )

        if flash_evacuation:
            self._is_blocked = True
            self._last_breach_time = timestamp
            self._block_reason = (
                f"FLASH_LIQUIDITY_EVACUATION: Drain velocity {self.drain_velocity:.2f}/s > "
                f"cap {self.max_drain_velocity:.2f}/s (T1={norm_drain_rates[0]:.1f}/s)"
            )
        elif drain_accel_spike:
            self._is_blocked = True
            self._last_breach_time = timestamp
            self._block_reason = (
                f"EXPONENTIAL_DRAIN_ACCELERATION: Accel {self.drain_acceleration:.2f}/s^2 > "
                f"cap {self.max_drain_acceleration:.2f}/s^2 (velocity={self.drain_velocity:.2f}/s)"
            )
        else:
            self._is_blocked = False
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked."""
        return self._is_blocked

    def is_entry_blocked(self, side: str = "BUY") -> bool:
        """OmniTrade interface compatibility. Blocks all entries when active."""
        return self._is_blocked

    @property
    def block_reason(self) -> str:
        return self._block_reason

    def get_telemetry(self) -> Dict[str, Any]:
        """Telemetry metadata for institutional risk auditing."""
        return {
            "guard": "Wave464OrderbookLiquidityDrainVelocityGuard",
            "drain_velocity": round(self.drain_velocity, 4),
            "drain_acceleration": round(self.drain_acceleration, 4),
            "tier_drain_rates": self.tier_drain_rates,
            "max_drain_velocity": self.max_drain_velocity,
            "max_drain_acceleration": self.max_drain_acceleration,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason
        }

    def reset(self) -> None:
        """Reset internal state."""
        self._prev_depths = None
        self._prev_timestamp = -1.0
        self._prev_drain_velocity = 0.0
        self.drain_velocity = 0.0
        self.drain_acceleration = 0.0
        self.tier_drain_rates = [0.0] * self.NUM_LEVELS
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
