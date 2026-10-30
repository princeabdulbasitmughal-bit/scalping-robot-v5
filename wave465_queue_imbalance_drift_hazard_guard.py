"""
Wave 465: Markovian Queue Imbalance Drift & Replenishment Boundary Hazard Guard
==============================================================================
Institutional Quantitative Mathematical Formulation:
Under Cont & de Larrard (2013) "Price Dynamics in a Markovian Limit Order Book",
and Cartea, Jaimungal & Penalva (2015), the instantaneous top-of-book queue state
(q_b, q_a) governs the transition probability of the next discrete price movement.

The Normalized Top-of-Book Queue Imbalance is:
    I(t) = (q_b(t) - q_a(t)) / (q_b(t) + q_a(t) + epsilon)   in [-1.0, 1.0]

Under high-frequency queue dynamics, the Imbalance Drift Velocity measures the rate
of structural liquidity asymmetry shift:
    v_I(t) = (I(t) - I(t - Delta t)) / Delta t   (1/sec)

In balanced, healthy two-sided markets:
- Mean imbalance fluctuates symmetrically around zero: |I(t)| < 0.40.
- Imbalance drift velocity is bounded: |v_I(t)| < 1.50 s^-1.
- Both bid and ask queues maintain adequate buffer depth: min(q_b, q_a) > min_queue_size.

Pathological Regimes:
1. Asymmetric Queue Flash Drift:
   |v_I(t)| > max_drift_velocity (default: > 3.0 s^-1) and |I(t)| > 0.60
   Rapid one-sided queue pulling or aggressive market sweeping shifts book imbalance
   at high velocity, signaling imminent adverse tick repricing.
2. Critical Replenishment Boundary Hazard:
   |I(t)| > critical_imbalance (default: > 0.85) and min(q_b, q_a) < min_queue_size (default: < 5.0)
   The thin side queue is nearly exhausted; any incoming market order causes an immediate
   discrete price tick through the spread.

When queue imbalance drift breaches safety limits, the guard blocks trade entry on the
exhausted/depleted side, preventing adverse fills during one-sided price runs.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave465QueueImbalanceDriftHazardGuard:
    """
    Evaluates top-of-book queue imbalance I(t), drift velocity v_I(t), and boundary
    exhaustion to guard against predatory sweeps and adverse queue selection.
    """

    def __init__(
        self,
        critical_imbalance: float = 0.85,
        max_drift_velocity: float = 3.00,
        min_queue_size: float = 5.0,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.50 <= critical_imbalance <= 0.98):
            raise ValueError(f"critical_imbalance must be in [0.50, 0.98], got {critical_imbalance}")
        if max_drift_velocity <= 0.50:
            raise ValueError(f"max_drift_velocity must be > 0.50, got {max_drift_velocity}")
        if min_queue_size < 1.0:
            raise ValueError(f"min_queue_size must be >= 1.0, got {min_queue_size}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.critical_imbalance: float = critical_imbalance
        self.max_drift_velocity: float = max_drift_velocity
        self.min_queue_size: float = min_queue_size
        self.cooldown_sec: float = cooldown_sec

        # State tracking
        self._prev_imbalance: Optional[float] = None
        self._prev_timestamp: float = -1.0

        # State telemetry
        self.current_imbalance: float = 0.0
        self.drift_velocity: float = 0.0
        self.thin_queue_size: float = 0.0
        self.blocked_side: Optional[str] = None
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0

    def update(self, bid_queue: float, ask_queue: float, timestamp: float) -> bool:
        """
        Record instantaneous top-of-book resting bid and ask queue sizes.
        Returns True if trading is blocked, False otherwise.
        """
        for q, name in [(bid_queue, "bid_queue"), (ask_queue, "ask_queue")]:
            if not math.isfinite(q) or q < 0.0:
                raise ValueError(f"{name} must be non-negative and finite, got {q}")

        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._prev_timestamp >= 0.0 and timestamp <= self._prev_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._prev_timestamp}")

        total_queue = bid_queue + ask_queue
        if total_queue < 1e-6:
            self.current_imbalance = 0.0
        else:
            self.current_imbalance = float((bid_queue - ask_queue) / total_queue)

        self.thin_queue_size = float(min(bid_queue, ask_queue))

        # Check cooldown
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._prev_imbalance = self.current_imbalance
            self._prev_timestamp = timestamp
            self._is_blocked = True
            return True

        if self._prev_imbalance is None:
            self._prev_imbalance = self.current_imbalance
            self._prev_timestamp = timestamp
            self._is_blocked = False
            self._block_reason = "INITIALIZING"
            self.blocked_side = None
            return False

        dt = timestamp - self._prev_timestamp
        if dt < 1e-6:
            dt = 1e-6

        # Compute imbalance drift velocity
        self.drift_velocity = float((self.current_imbalance - self._prev_imbalance) / dt)

        # Update historical state
        self._prev_imbalance = self.current_imbalance
        self._prev_timestamp = timestamp

        # Evaluate Circuit Breakers
        rapid_drift = (abs(self.drift_velocity) > self.max_drift_velocity and abs(self.current_imbalance) > 0.60)
        boundary_exhaustion = (abs(self.current_imbalance) > self.critical_imbalance and self.thin_queue_size < self.min_queue_size)

        if rapid_drift or boundary_exhaustion:
            self._is_blocked = True
            self._last_breach_time = timestamp

            # Determine toxic adverse selection direction:
            # Positive imbalance (bid >> ask) -> Ask queue is depleted -> Upward tick expected -> Shorting is toxic
            # Negative imbalance (ask >> bid) -> Bid queue is depleted -> Downward tick expected -> Buying is toxic
            if self.current_imbalance > 0:
                self.blocked_side = "SELL" # Depleted ask side, buying pressure dominant
            else:
                self.blocked_side = "BUY"  # Depleted bid side, selling pressure dominant

            trigger = "QUEUE_IMBALANCE_RAPID_DRIFT" if rapid_drift else "CRITICAL_QUEUE_DEPLETION_HAZARD"
            self._block_reason = (
                f"{trigger}: I={self.current_imbalance:.2%}, v_I={self.drift_velocity:.2f}/s, "
                f"thin_q={self.thin_queue_size:.1f} < {self.min_queue_size:.1f} (blocked: {self.blocked_side})"
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
        """OmniTrade interface compatibility. Checks if a specific order side is blocked."""
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
            "guard": "Wave465QueueImbalanceDriftHazardGuard",
            "current_imbalance": round(self.current_imbalance, 4),
            "drift_velocity": round(self.drift_velocity, 4),
            "thin_queue_size": round(self.thin_queue_size, 2),
            "critical_imbalance": self.critical_imbalance,
            "max_drift_velocity": self.max_drift_velocity,
            "min_queue_size": self.min_queue_size,
            "blocked_side": self.blocked_side,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason
        }

    def reset(self) -> None:
        """Reset internal state."""
        self._prev_imbalance = None
        self._prev_timestamp = -1.0
        self.current_imbalance = 0.0
        self.drift_velocity = 0.0
        self.thin_queue_size = 0.0
        self.blocked_side = None
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
