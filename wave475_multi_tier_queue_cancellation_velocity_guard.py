"""
Wave 475: Multi-Tier Queue Cancellation Velocity Guard
======================================================
Institutional Quantitative Mathematical Formulation:
Under Hautsch & Huang (2014) "The Market Impact of Large Orders", Hasbrouck & Saar (2009)
"Low-Latency Trading", and Cartea & Jaimungal (2014) "Risk Metrics and Fine Tuning of
High-Frequency Trading Strategies", resting limit orders are removed either via trade execution
or order cancellation.

A sudden burst of cancellations unaccompanied by executions represents phantom liquidity,
quote flashing, or predatory spoofing intended to lure retail momentum orders into a trap.

Let Q_k(t) be resting depth at tier k in {1, ..., K}, and E_k(t) be executed volume in interval Delta t.
The non-execution cancellation volume at level k is:
    C_k(t) = max(0.0, Q_k(t - Delta t) - Q_k(t) - E_k(t))

1. Aggregate Cancellation Velocity:
   V_{cancel}(t) = sum_{k=1}^K C_k(t) / Delta t   (lots / sec)

2. Relative Cancellation Velocity:
   v_{cancel}^{rel}(t) = V_{cancel}(t) / max(D_{base}(t), epsilon)   (sec^-1)
   When v_{cancel}^{rel}(t) > max_cancellation_velocity (default: > 2.50 sec^-1),
   liquidity is vanishing due to algorithmic quote withdrawal.

3. Order Cancellation Ratio:
   R_{cancel}(t) = sum C_k(t) / max(sum C_k(t) + sum E_k(t), epsilon) in [0.0, 1.0]
   When R_{cancel}(t) > max_cancel_ratio (default: > 0.92) during volume surges,
   the order book is dominated by phantom/flickering quotes.

4. Directional Cancellation Asymmetry:
   A_{cancel}(t) = (V_{cancel}^{bid} - V_{cancel}^{ask}) / max(max(V_{cancel}^{bid}, V_{cancel}^{ask}), 1e-4)
   - When A_{cancel}(t) > 0.70: Bids are being pulled rapidly -> BUY entries toxic (bid rug-pull).
   - When A_{cancel}(t) < -0.70: Asks are being pulled rapidly -> SELL entries toxic (ask rug-pull).
   - When both sides experience cancellation bursts: ALL entries blocked.

When triggered, the guard freezes execution routing to prevent fills into evaporating phantom books.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave475MultiTierQueueCancellationVelocityGuard:
    """
    Monitors multi-tier orderbook cancellations, relative cancellation velocity,
    and cancellation asymmetry to defend against spoofing and phantom liquidity rug-pulls.
    """

    def __init__(
        self,
        max_cancellation_velocity: float = 2.50,
        max_cancel_ratio: float = 0.92,
        asymmetry_threshold: float = 0.70,
        min_burst_volume: float = 10.0,
        cooldown_sec: float = 2.0
    ) -> None:
        if max_cancellation_velocity <= 0.50:
            raise ValueError(f"max_cancellation_velocity must be > 0.50, got {max_cancellation_velocity}")
        if not (0.70 <= max_cancel_ratio <= 0.99):
            raise ValueError(f"max_cancel_ratio must be in [0.70, 0.99], got {max_cancel_ratio}")
        if not (0.40 <= asymmetry_threshold <= 0.95):
            raise ValueError(f"asymmetry_threshold must be in [0.40, 0.95], got {asymmetry_threshold}")
        if min_burst_volume <= 1.0:
            raise ValueError(f"min_burst_volume must be > 1.0, got {min_burst_volume}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.max_cancellation_velocity: float = max_cancellation_velocity
        self.max_cancel_ratio: float = max_cancel_ratio
        self.asymmetry_threshold: float = asymmetry_threshold
        self.min_burst_volume: float = min_burst_volume
        self.cooldown_sec: float = cooldown_sec

        # Telemetry metrics
        self.cancellation_velocity: float = 0.0
        self.cancellation_ratio: float = 0.0
        self.cancellation_asymmetry: float = 0.0
        self.bid_cancel_rate: float = 0.0
        self.ask_cancel_rate: float = 0.0
        self.blocked_side: Optional[str] = None
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0
        self._last_timestamp: float = -1.0

        # State buffers
        self._prev_bid_depths: Optional[List[float]] = None
        self._prev_ask_depths: Optional[List[float]] = None

    def update(
        self,
        bid_depths: List[float],
        ask_depths: List[float],
        executed_bid_volume: float = 0.0,
        executed_ask_volume: float = 0.0,
        timestamp: float = 0.0
    ) -> bool:
        """
        Record instantaneous multi-tier bid and ask depths and executed trade volumes.
        Returns True if trading is blocked, False otherwise.
        """
        if len(bid_depths) != len(ask_depths):
            raise ValueError("bid_depths and ask_depths must have equal length")
        if len(bid_depths) < 2:
            raise ValueError("bid_depths and ask_depths must contain at least 2 levels")
        for b, a in zip(bid_depths, ask_depths):
            if not (math.isfinite(b) and math.isfinite(a)):
                raise ValueError("All depth values must be finite numbers")
            if b < 0.0 or a < 0.0:
                raise ValueError("Depths must be non-negative")
        if not (math.isfinite(executed_bid_volume) and math.isfinite(executed_ask_volume)):
            raise ValueError("Executed volumes must be finite")
        if executed_bid_volume < 0.0 or executed_ask_volume < 0.0:
            raise ValueError("Executed volumes must be non-negative")
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

        if self._prev_bid_depths is None or dt <= 0.0:
            self._prev_bid_depths = list(bid_depths)
            self._prev_ask_depths = list(ask_depths)
            self._is_blocked = False
            self.blocked_side = None
            self._block_reason = "INITIALIZING"
            return False

        # Calculate cancelled volume per side
        prev_bid_tot = sum(self._prev_bid_depths)
        curr_bid_tot = sum(bid_depths)
        prev_ask_tot = sum(self._prev_ask_depths)
        curr_ask_tot = sum(ask_depths)

        bid_drop = max(0.0, prev_bid_tot - curr_bid_tot)
        ask_drop = max(0.0, prev_ask_tot - curr_ask_tot)

        # Cancellations are drops in depth not accounted for by executions
        bid_cancel_vol = max(0.0, bid_drop - executed_bid_volume)
        ask_cancel_vol = max(0.0, ask_drop - executed_ask_volume)
        total_cancel_vol = bid_cancel_vol + ask_cancel_vol
        total_exec_vol = executed_bid_volume + executed_ask_volume

        self.bid_cancel_rate = bid_cancel_vol / dt
        self.ask_cancel_rate = ask_cancel_vol / dt
        total_cancel_rate = total_cancel_vol / dt

        base_depth = max(0.5 * (prev_bid_tot + prev_ask_tot), 1e-4)
        self.cancellation_velocity = total_cancel_rate / base_depth

        # Order cancellation ratio
        denom_flow = total_cancel_vol + total_exec_vol
        self.cancellation_ratio = (total_cancel_vol / denom_flow) if denom_flow > 1e-4 else 0.0

        # Cancellation asymmetry: A_{cancel} in [-1.0, 1.0]
        max_rate = max(self.bid_cancel_rate, self.ask_cancel_rate, 1e-4)
        self.cancellation_asymmetry = (self.bid_cancel_rate - self.ask_cancel_rate) / max_rate

        self._prev_bid_depths = list(bid_depths)
        self._prev_ask_depths = list(ask_depths)

        # Evaluate Circuit Breakers
        vel_breached = (self.cancellation_velocity > self.max_cancellation_velocity and total_cancel_vol >= self.min_burst_volume)
        spoof_breached = (self.cancellation_ratio > self.max_cancel_ratio and total_cancel_vol >= self.min_burst_volume)

        if vel_breached or spoof_breached:
            self._is_blocked = True
            self._last_breach_time = timestamp

            # Directional attribution
            if abs(self.cancellation_asymmetry) > self.asymmetry_threshold:
                if self.cancellation_asymmetry > self.asymmetry_threshold:
                    self.blocked_side = "BUY" # Bids cancelled heavily -> buying is toxic (rug-pull)
                    side_note = "BID_CANCELLATION_RUGPULL"
                else:
                    self.blocked_side = "SELL" # Asks cancelled heavily -> selling is toxic (short squeeze)
                    side_note = "ASK_CANCELLATION_RUGPULL"
            else:
                self.blocked_side = "ALL"
                side_note = "BILATERAL_CANCELLATION_EXPLOSION"

            trigger = "CANCELLATION_VELOCITY_EXPLOSION" if vel_breached else "SPOOFING_PHANTOM_LIQUIDITY_SURGE"
            self._block_reason = (
                f"{trigger}: v_rel={self.cancellation_velocity:.2f}/s (max={self.max_cancellation_velocity:.2f}/s), "
                f"R_cancel={self.cancellation_ratio:.2f} (max={self.max_cancel_ratio:.2f}), "
                f"vol={total_cancel_vol:.1f} lots, asym={self.cancellation_asymmetry:.2f} [{side_note}], blocked: {self.blocked_side}"
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
            "guard": "Wave475MultiTierQueueCancellationVelocityGuard",
            "cancellation_velocity": round(self.cancellation_velocity, 4),
            "cancellation_ratio": round(self.cancellation_ratio, 4),
            "cancellation_asymmetry": round(self.cancellation_asymmetry, 4),
            "bid_cancel_rate": round(self.bid_cancel_rate, 2),
            "ask_cancel_rate": round(self.ask_cancel_rate, 2),
            "max_cancellation_velocity": self.max_cancellation_velocity,
            "max_cancel_ratio": self.max_cancel_ratio,
            "blocked_side": self.blocked_side,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason
        }

    def reset(self) -> None:
        """Reset internal state."""
        self.cancellation_velocity = 0.0
        self.cancellation_ratio = 0.0
        self.cancellation_asymmetry = 0.0
        self.bid_cancel_rate = 0.0
        self.ask_cancel_rate = 0.0
        self.blocked_side = None
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
        self._last_timestamp = -1.0
        self._prev_bid_depths = None
        self._prev_ask_depths = None
