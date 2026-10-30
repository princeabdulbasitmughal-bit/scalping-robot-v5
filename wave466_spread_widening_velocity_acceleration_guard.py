"""
Wave 466: Dynamic Bid-Ask Spread Widening Velocity & Acceleration Guard
=======================================================================
Institutional Quantitative Mathematical Formulation:
Under Roll (1984) "A Simple Implicit Measure of the Effective Bid-Ask Spread",
Amihud & Mendelson (1986), and Hasbrouck (2007) "Empirical Market Microstructure",
the instantaneous bid-ask spread S(t) = P_ask(t) - P_bid(t) reflects market-maker
inventory risk and adverse selection premium.

Across discrete time step Delta t = t - t_prev:
1. Spread Widening Velocity (pips/sec or $/sec):
    v_S(t) = (S(t) - S(t_prev)) / Delta t

2. Spread Widening Acceleration (pips/sec^2):
    a_S(t) = (v_S(t) - v_S(t_prev)) / Delta t

3. Normalized Spread Multiple:
    R_spread(t) = S(t) / max(S_baseline, 1e-4)

In normal institutional trading conditions:
- Spreads are tight and stationary: S(t) ~ baseline_spread (e.g. 1.5 - 2.5 pips on XAUUSD).
- Spread widening velocity is bounded: |v_S(t)| < 5.0 pips/sec.
- Market-making quotes provide steady two-sided liquidity.

Pathological Regimes:
1. Flash Spread Explosion:
   v_S(t) > max_spread_velocity (default: > 12.0 pips/sec) and R_spread > 2.0x
   Market makers pull resting quotes simultaneously, blowing the spread wide open.
2. Exponential Widening Acceleration:
   a_S(t) > max_spread_acceleration (default: > 25.0 pips/sec^2) and R_spread > 1.8x
   Spread expansion is accelerating, signaling an incoming liquidity black hole or news cascade.
3. Hard Spread Ceiling Breach:
   S(t) > max_absolute_spread (default: > 8.0 pips)
   Absolute spread exceeds the economic break-even threshold for high-frequency scalping.

When spread expansion breaches safety limits, the guard immediately freezes order submission,
preventing execution into massive slippage and wide spread penalties.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave466SpreadWideningVelocityAccelerationGuard:
    """
    Evaluates dynamic bid-ask spread widening velocity, acceleration, and multiple
    to protect against market-maker quote pulling and execution slippage traps.
    """

    def __init__(
        self,
        baseline_spread_pips: float = 2.0,
        max_spread_velocity: float = 12.0,
        max_spread_acceleration: float = 25.0,
        max_absolute_spread_pips: float = 8.0,
        cooldown_sec: float = 2.0
    ) -> None:
        if baseline_spread_pips <= 0.1:
            raise ValueError(f"baseline_spread_pips must be > 0.1, got {baseline_spread_pips}")
        if max_spread_velocity <= 1.0:
            raise ValueError(f"max_spread_velocity must be > 1.0, got {max_spread_velocity}")
        if max_spread_acceleration <= 2.0:
            raise ValueError(f"max_spread_acceleration must be > 2.0, got {max_spread_acceleration}")
        if max_absolute_spread_pips <= baseline_spread_pips:
            raise ValueError(f"max_absolute_spread_pips must be > baseline_spread_pips ({baseline_spread_pips}), got {max_absolute_spread_pips}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.baseline_spread_pips: float = baseline_spread_pips
        self.max_spread_velocity: float = max_spread_velocity
        self.max_spread_acceleration: float = max_spread_acceleration
        self.max_absolute_spread_pips: float = max_absolute_spread_pips
        self.cooldown_sec: float = cooldown_sec

        # State tracking
        self._prev_spread: Optional[float] = None
        self._prev_timestamp: float = -1.0
        self._prev_velocity: float = 0.0

        # State telemetry
        self.current_spread: float = 0.0
        self.spread_velocity: float = 0.0
        self.spread_acceleration: float = 0.0
        self.spread_multiple: float = 1.0
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0

    def update(self, spread_pips: float, timestamp: float) -> bool:
        """
        Record instantaneous bid-ask spread in pips.
        Returns True if trading is blocked, False otherwise.
        """
        if not math.isfinite(spread_pips) or spread_pips < 0.0:
            raise ValueError(f"spread_pips must be non-negative and finite, got {spread_pips}")

        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._prev_timestamp >= 0.0 and timestamp <= self._prev_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._prev_timestamp}")

        self.current_spread = float(spread_pips)
        self.spread_multiple = float(self.current_spread / max(self.baseline_spread_pips, 1e-4))

        # Check cooldown
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._prev_spread = self.current_spread
            self._prev_timestamp = timestamp
            self._is_blocked = True
            return True

        if self._prev_spread is None:
            self._prev_spread = self.current_spread
            self._prev_timestamp = timestamp
            self._is_blocked = False
            self._block_reason = "INITIALIZING"
            return False

        dt = timestamp - self._prev_timestamp
        if dt < 1e-6:
            dt = 1e-6

        # Velocity and Acceleration
        d_spread = self.current_spread - self._prev_spread
        self.spread_velocity = float(d_spread / dt)
        self.spread_acceleration = float((self.spread_velocity - self._prev_velocity) / dt)

        # Update state
        self._prev_spread = self.current_spread
        self._prev_timestamp = timestamp
        self._prev_velocity = self.spread_velocity

        # Evaluate Circuit Breakers
        ceiling_breached = (self.current_spread > self.max_absolute_spread_pips)
        flash_explosion = (self.spread_velocity > self.max_spread_velocity and self.spread_multiple > 2.0)
        accel_spike = (self.spread_acceleration > self.max_spread_acceleration and self.spread_multiple > 1.8)

        if ceiling_breached:
            self._is_blocked = True
            self._last_breach_time = timestamp
            self._block_reason = (
                f"HARD_SPREAD_CEILING_BREACH: Spread {self.current_spread:.2f} pips > "
                f"ceiling {self.max_absolute_spread_pips:.2f} pips ({self.spread_multiple:.1f}x baseline)"
            )
        elif flash_explosion:
            self._is_blocked = True
            self._last_breach_time = timestamp
            self._block_reason = (
                f"SPREAD_EXPLOSION_VELOCITY: Widening velocity {self.spread_velocity:.2f} pips/s > "
                f"threshold {self.max_spread_velocity:.2f} pips/s (spread={self.current_spread:.2f} pips)"
            )
        elif accel_spike:
            self._is_blocked = True
            self._last_breach_time = timestamp
            self._block_reason = (
                f"EXPONENTIAL_SPREAD_ACCELERATION: Accel {self.spread_acceleration:.2f} pips/s^2 > "
                f"cap {self.max_spread_acceleration:.2f} pips/s^2 (velocity={self.spread_velocity:.2f} pips/s)"
            )
        else:
            self._is_blocked = False
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked."""
        return self._is_blocked

    def is_entry_blocked(self, side: str = "BUY") -> bool:
        """OmniTrade interface compatibility. Blocks both BUY and SELL when active."""
        return self._is_blocked

    @property
    def block_reason(self) -> str:
        return self._block_reason

    def get_telemetry(self) -> Dict[str, Any]:
        """Telemetry metadata for institutional risk auditing."""
        return {
            "guard": "Wave466SpreadWideningVelocityAccelerationGuard",
            "current_spread": round(self.current_spread, 3),
            "spread_velocity": round(self.spread_velocity, 3),
            "spread_acceleration": round(self.spread_acceleration, 3),
            "spread_multiple": round(self.spread_multiple, 2),
            "baseline_spread_pips": self.baseline_spread_pips,
            "max_spread_velocity": self.max_spread_velocity,
            "max_spread_acceleration": self.max_spread_acceleration,
            "max_absolute_spread_pips": self.max_absolute_spread_pips,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason
        }

    def reset(self) -> None:
        """Reset internal state."""
        self._prev_spread = None
        self._prev_timestamp = -1.0
        self._prev_velocity = 0.0
        self.current_spread = 0.0
        self.spread_velocity = 0.0
        self.spread_acceleration = 0.0
        self.spread_multiple = 1.0
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
