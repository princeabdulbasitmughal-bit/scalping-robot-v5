"""
Wave 469: Liquidity Black Hole Event Horizon Contraction Guard
=============================================================
Institutional Quantitative Mathematical Formulation:
Under Morris & Shin (2004) "Liquidity Black Holes", Danielsson & Shin (2003),
and Cont & Kukanov (2014) "Optimal Order Placement in Limit Order Books",
liquidity black holes emerge when endogenous feedback loops cause rapid evaporation
of resting order book volume. As market participants face risk constraints and
stop-loss cascades, depth contracts non-linearly toward zero, forming an "Event Horizon"
inside of which price impact becomes singular and execution costs explode.

Key Microstructural Invariants:
1. Aggregate Book Depth:
   D(t) = D_{bid}(t) + D_{ask}(t)

2. Rolling Baseline Depth:
   D_{base}(t) = Median_{tau in [t-W, t]} D(tau)

3. Event Horizon Contraction Ratio R_H(t):
   R_H(t) = D(t) / max(D_{base}(t), epsilon)
   When R_H(t) < critical_contraction_ratio (default: < 0.35, i.e., > 65% depth loss),
   the order book has breached the Event Horizon boundary.

4. Event Horizon Contraction Velocity v_H(t):
   v_H(t) = - dR_H / dt = [R_H(t - Delta t) - R_H(t)] / Delta t  (sec^-1)
   When v_H(t) > max_contraction_velocity (default: > 1.80 sec^-1), liquidity is
   evaporating faster than replenishment algorithms can respond.

5. Dynamic Book Asymmetry Ratio A(t):
   A(t) = D_{bid}(t) / max(D_{ask}(t), epsilon)
   - When A(t) < 1 / asymmetry_threshold: Bid-side vacuum -> SELL entries toxic.
   - When A(t) > asymmetry_threshold: Ask-side vacuum -> BUY entries toxic.
   - When general contraction occurs or both sides collapse: ALL entries blocked.

When the Event Horizon is breached, the guard executes an immediate hard freeze,
preventing execution into liquidity vacuums and halting all routing cascades.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave469LiquidityEventHorizonContractionGuard:
    """
    Monitors aggregate orderbook depth, event horizon contraction ratios,
    and instantaneous evaporation velocities to prevent executions inside
    liquidity black holes.
    """

    def __init__(
        self,
        window_size: int = 20,
        min_samples: int = 8,
        critical_contraction_ratio: float = 0.35,
        max_contraction_velocity: float = 1.80,
        asymmetry_ratio_threshold: float = 3.50,
        cooldown_sec: float = 2.0
    ) -> None:
        if window_size < 10:
            raise ValueError(f"window_size must be >= 10, got {window_size}")
        if min_samples < 5:
            raise ValueError(f"min_samples must be >= 5, got {min_samples}")
        if min_samples > window_size:
            raise ValueError(f"min_samples ({min_samples}) cannot exceed window_size ({window_size})")
        if not (0.10 <= critical_contraction_ratio <= 0.70):
            raise ValueError(f"critical_contraction_ratio must be in [0.10, 0.70], got {critical_contraction_ratio}")
        if max_contraction_velocity <= 0.20:
            raise ValueError(f"max_contraction_velocity must be > 0.20, got {max_contraction_velocity}")
        if asymmetry_ratio_threshold <= 1.50:
            raise ValueError(f"asymmetry_ratio_threshold must be > 1.50, got {asymmetry_ratio_threshold}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.window_size: int = window_size
        self.min_samples: int = min_samples
        self.critical_contraction_ratio: float = critical_contraction_ratio
        self.max_contraction_velocity: float = max_contraction_velocity
        self.asymmetry_ratio_threshold: float = asymmetry_ratio_threshold
        self.cooldown_sec: float = cooldown_sec

        # Historical state buffers
        self._depth_history: List[float] = []
        self._rh_history: List[float] = []
        self._time_history: List[float] = []

        # Current telemetry metrics
        self.current_depth: float = 0.0
        self.baseline_depth: float = 0.0
        self.contraction_ratio: float = 1.0
        self.contraction_velocity: float = 0.0
        self.asymmetry_ratio: float = 1.0
        self.blocked_side: Optional[str] = None
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0
        self._last_timestamp: float = -1.0

    def update(
        self,
        bid_depth: float,
        ask_depth: float,
        timestamp: float
    ) -> bool:
        """
        Record instantaneous bid and ask orderbook depth.
        Returns True if trading is blocked, False otherwise.
        """
        if not (math.isfinite(bid_depth) and math.isfinite(ask_depth)):
            raise ValueError("bid_depth and ask_depth must be finite numbers")
        if bid_depth < 0.0 or ask_depth < 0.0:
            raise ValueError("Depth values must be non-negative")
        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._last_timestamp >= 0.0 and timestamp <= self._last_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._last_timestamp}")

        total_depth = bid_depth + ask_depth
        dt = (timestamp - self._last_timestamp) if self._last_timestamp >= 0.0 else 0.0
        self._last_timestamp = timestamp

        # Check cooldown from prior breach
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        self._depth_history.append(total_depth)
        self._time_history.append(timestamp)
        if len(self._depth_history) > self.window_size:
            self._depth_history.pop(0)
            self._time_history.pop(0)

        self.current_depth = total_depth
        eps = 1e-6
        self.asymmetry_ratio = (bid_depth + eps) / (ask_depth + eps)

        if len(self._depth_history) < self.min_samples:
            self._is_blocked = False
            self.blocked_side = None
            self._block_reason = "INSUFFICIENT_SAMPLES"
            self.baseline_depth = float(np.median(self._depth_history)) if self._depth_history else 0.0
            self.contraction_ratio = 1.0
            self.contraction_velocity = 0.0
            self._rh_history.append(1.0)
            return False

        # Compute robust baseline depth via median over historical window
        self.baseline_depth = float(np.median(self._depth_history[:-1])) if len(self._depth_history) > 1 else total_depth
        base_denom = max(self.baseline_depth, eps)
        self.contraction_ratio = total_depth / base_denom

        self._rh_history.append(self.contraction_ratio)
        if len(self._rh_history) > self.window_size:
            self._rh_history.pop(0)

        # Compute contraction velocity
        if len(self._rh_history) >= 2 and dt > 0.0:
            prev_rh = self._rh_history[-2]
            self.contraction_velocity = max(0.0, (prev_rh - self.contraction_ratio) / dt)
        else:
            self.contraction_velocity = 0.0

        # Evaluate Circuit Breakers
        horizon_collapse = (self.contraction_ratio < self.critical_contraction_ratio)
        velocity_breach = (self.contraction_velocity > self.max_contraction_velocity)

        if horizon_collapse or velocity_breach:
            self._is_blocked = True
            self._last_breach_time = timestamp

            # Determine directional toxicity
            if self.asymmetry_ratio < (1.0 / self.asymmetry_ratio_threshold):
                self.blocked_side = "SELL"
                side_note = "BID_DEPTH_VACUUM"
            elif self.asymmetry_ratio > self.asymmetry_ratio_threshold:
                self.blocked_side = "BUY"
                side_note = "ASK_DEPTH_VACUUM"
            else:
                self.blocked_side = "ALL"
                side_note = "BILATERAL_EVENT_HORIZON_COLLAPSE"

            trigger = "EVENT_HORIZON_COLLAPSE" if horizon_collapse else "HORIZON_CONTRACTION_VELOCITY_BREACH"
            self._block_reason = (
                f"{trigger}: R_H={self.contraction_ratio:.3f} (thresh={self.critical_contraction_ratio:.3f}), "
                f"v_H={self.contraction_velocity:.2f}/s (max={self.max_contraction_velocity:.2f}/s), "
                f"asym={self.asymmetry_ratio:.2f} [{side_note}], blocked: {self.blocked_side}"
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
            "guard": "Wave469LiquidityEventHorizonContractionGuard",
            "current_depth": round(self.current_depth, 2),
            "baseline_depth": round(self.baseline_depth, 2),
            "contraction_ratio": round(self.contraction_ratio, 4),
            "contraction_velocity": round(self.contraction_velocity, 4),
            "asymmetry_ratio": round(self.asymmetry_ratio, 4),
            "critical_contraction_ratio": self.critical_contraction_ratio,
            "max_contraction_velocity": self.max_contraction_velocity,
            "blocked_side": self.blocked_side,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason
        }

    def reset(self) -> None:
        """Reset internal state."""
        self._depth_history.clear()
        self._rh_history.clear()
        self._time_history.clear()
        self.current_depth = 0.0
        self.baseline_depth = 0.0
        self.contraction_ratio = 1.0
        self.contraction_velocity = 0.0
        self.asymmetry_ratio = 1.0
        self.blocked_side = None
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
        self._last_timestamp = -1.0
