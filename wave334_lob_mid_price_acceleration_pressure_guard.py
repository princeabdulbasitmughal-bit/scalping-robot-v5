"""Wave 334: Limit Order Book Mid-Price Acceleration & Order Book Pressure Disparity Guard.

Mathematical and Microstructural Context:
----------------------------------------
In limit order book microstructure (Cont, Kukanov & Stoikov 2014; Stoikov 2018; Biais, Hillion & Spatt 1995),
order flow imbalance (OFI) and queue disparity at the inside quotes drive high-frequency price dynamics.
For consecutive mid-prices P_{t-2}, P_{t-1}, P_t at timestamps t_{t-2}, t_{t-1}, t_t:
    Mid-price:            P_t = (b_t + a_t) / 2.0
    Mid-price velocity:   v_t = (P_t - P_{t-1}) / (t_t - t_{t-1})   (in bps/second)
    Mid-price acceleration: a_t = (v_t - v_{t-1}) / (t_t - t_{t-1}) (in bps/second^2)
    Order book pressure disparity: Pi_t = (Q_b - Q_a) / (Q_b + Q_a) in [-1, +1]

Under steady two-sided liquidity provisioning:
1. Mid-price changes are diffusional with low acceleration (|a_t| <= 2.0 bps/s^2).
2. Inside queue sizes remain balanced (|Pi_t| <= 0.60).

However, during violent liquidity extraction or quote depletion events:
1. Acute Mid-Price Acceleration & Pressure Decoupling (|a_t| >= 4.5 bps/s^2 with |Pi_t| >= 0.75):
   Signals non-linear predatory quote sweeping where aggressive orders rapidly chew through book depth.
2. Inside Liquidity Cliff:
   Total inside depth (Q_b + Q_a) collapses by >= 75% compared to rolling baseline over dt <= 0.20s.
3. Crossed Book or Zero Spread (b_t >= a_t):
   Immediate arbitrage or feed dysfunction.

When any of these anomalies occur, the guard trips an execution block for
`cooldown_seconds` (default: 45.0s) to protect against severe execution slippage.

Thread Safety: Protected by threading.RLock.
Fail-Closed: Any non-numeric, NaN, infinite, non-positive price/size inputs or non-monotonic timestamps
trip an immediate block.
"""

from collections import deque
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class Wave334LOBMidPriceAccelerationPressureGuard:
    """Wave 334: LOB Mid-Price Acceleration & Queue Pressure Disparity Guard."""

    def __init__(
        self,
        window_size: int = 15,
        acceleration_threshold_bps_s2: float = 4.5,
        pressure_disparity_threshold: float = 0.75,
        liquidity_cliff_drop_pct: float = 0.75,
        min_depth_sample_count: int = 5,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 5:
            window_size = 15
        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)) or cooldown_seconds <= 0:
            cooldown_seconds = 45.0

        self.window_size = window_size
        self.acceleration_threshold_bps_s2 = float(acceleration_threshold_bps_s2)
        self.pressure_disparity_threshold = float(pressure_disparity_threshold)
        self.liquidity_cliff_drop_pct = float(liquidity_cliff_drop_pct)
        self.min_depth_sample_count = int(min_depth_sample_count)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._price_history: deque = deque(maxlen=self.window_size)  # (timestamp, mid_price)
        self._velocity_history: deque = deque(maxlen=self.window_size)  # (timestamp, velocity_bps_s)
        self._depth_history: deque = deque(maxlen=self.window_size)  # total_depth
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""
        self._last_acceleration: float = 0.0
        self._last_pressure_disparity: float = 0.0
        self._total_updates: int = 0
        self._total_violations: int = 0

    def _validate_numeric(self, val: Any) -> Optional[float]:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return None
        fval = float(val)
        if math.isnan(fval) or math.isinf(fval):
            return None
        return fval

    def update(
        self,
        best_bid: float,
        best_ask: float,
        bid_size: float,
        ask_size: float,
        current_time: Optional[float] = None,
    ) -> bool:
        """Update guard with latest L1 top-of-book quote and depth.

        Returns True if trading is blocked, False otherwise.
        """
        now = time.monotonic() if current_time is None else float(current_time)

        with self._lock:
            self._total_updates += 1

            v_bid = self._validate_numeric(best_bid)
            v_ask = self._validate_numeric(best_ask)
            v_b_sz = self._validate_numeric(bid_size)
            v_a_sz = self._validate_numeric(ask_size)

            if v_bid is None or v_ask is None or v_b_sz is None or v_a_sz is None:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = "FAIL_CLOSED: Non-numeric, NaN, or Infinite price/size parameter"
                self._total_violations += 1
                return True

            if v_bid <= 0.0 or v_ask <= 0.0 or v_b_sz <= 0.0 or v_a_sz <= 0.0:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = "FAIL_CLOSED: Non-positive price or size parameter"
                self._total_violations += 1
                return True

            if v_bid >= v_ask:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = (
                    f"CROSSED_OR_LOCKED_BOOK: Best bid {v_bid:.5f} >= Best ask {v_ask:.5f}"
                )
                self._total_violations += 1
                return True

            # Mid price and inside depth
            mid = (v_bid + v_ask) / 2.0
            total_depth = v_b_sz + v_a_sz
            pressure = (v_b_sz - v_a_sz) / total_depth
            self._last_pressure_disparity = pressure

            # Check timestamp ordering
            if self._price_history:
                prev_time, prev_mid = self._price_history[-1]
                dt = now - prev_time
                if dt <= 0.0:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = f"FAIL_CLOSED: Non-increasing or zero dt {dt:.6f}s"
                    self._total_violations += 1
                    return True

                # Velocity in bps/second
                dp_bps = ((mid - prev_mid) / prev_mid) * 10000.0
                vel_bps_s = dp_bps / dt

                # Compute acceleration if previous velocity exists
                if self._velocity_history:
                    prev_vel_time, prev_vel = self._velocity_history[-1]
                    d_vel_t = now - prev_vel_time
                    if d_vel_t > 0.0:
                        accel_bps_s2 = (vel_bps_s - prev_vel) / d_vel_t
                        self._last_acceleration = accel_bps_s2

                        # 1. Acute Acceleration & Pressure Disparity Check
                        if (
                            abs(accel_bps_s2) >= self.acceleration_threshold_bps_s2
                            and abs(pressure) >= self.pressure_disparity_threshold
                        ):
                            self._blocked_until = now + self.cooldown_seconds
                            self._last_block_reason = (
                                f"ACUTE_MID_PRICE_ACCELERATION: Accel {accel_bps_s2:.2f} bps/s^2 >= "
                                f"{self.acceleration_threshold_bps_s2:.2f} with Queue Pressure {pressure:.2f}"
                            )
                            self._total_violations += 1
                            return True

                self._velocity_history.append((now, vel_bps_s))

            # 2. Inside Liquidity Cliff Check
            if len(self._depth_history) >= self.min_depth_sample_count:
                avg_depth = sum(self._depth_history) / len(self._depth_history)
                if avg_depth > 0.0:
                    depth_drop = (avg_depth - total_depth) / avg_depth
                    if depth_drop >= self.liquidity_cliff_drop_pct:
                        self._blocked_until = now + self.cooldown_seconds
                        self._last_block_reason = (
                            f"INSIDE_LIQUIDITY_CLIFF: Depth drop {depth_drop * 100:.1f}% >= "
                            f"{self.liquidity_cliff_drop_pct * 100:.1f}% (current: {total_depth:.1f}, baseline: {avg_depth:.1f})"
                        )
                        self._total_violations += 1
                        return True

            self._price_history.append((now, mid))
            self._depth_history.append(total_depth)

            return now < self._blocked_until

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        """Return True if the guard is currently blocking entries."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            return now < self._blocked_until

    def is_entry_blocked(self, current_time: Optional[float] = None) -> bool:
        """Alias for is_blocked."""
        return self.is_blocked(current_time)

    def reset(self) -> None:
        """Reset internal history and state."""
        with self._lock:
            self._price_history.clear()
            self._velocity_history.clear()
            self._depth_history.clear()
            self._blocked_until = 0.0
            self._last_block_reason = ""
            self._last_acceleration = 0.0
            self._last_pressure_disparity = 0.0
            self._total_updates = 0
            self._total_violations = 0

    def get_status(self, current_time: Optional[float] = None) -> Dict[str, Any]:
        """Return diagnostic metrics and state dictionary."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            remaining_cooldown = max(0.0, self._blocked_until - now)
            return {
                "guard_name": "Wave334LOBMidPriceAccelerationPressureGuard",
                "is_blocked": now < self._blocked_until,
                "remaining_cooldown_s": round(remaining_cooldown, 3),
                "last_block_reason": self._last_block_reason,
                "last_acceleration_bps_s2": round(self._last_acceleration, 4),
                "last_pressure_disparity": round(self._last_pressure_disparity, 4),
                "price_buffer_fill": len(self._price_history),
                "depth_buffer_fill": len(self._depth_history),
                "total_updates": self._total_updates,
                "total_violations": self._total_violations,
            }
