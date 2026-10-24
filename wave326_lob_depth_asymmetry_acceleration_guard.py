"""Wave 326: Limit Order Book Multi-Level Depth Asymmetry Acceleration & Liquidity Evaporation Guard.

Mathematical and Microstructural Context:
----------------------------------------
In modern limit order books, the instantaneous normalized depth asymmetry (order book imbalance) is:
    I_t = (Q_b,t - Q_a,t) / (Q_b,t + Q_a,t) in [-1, +1]

While the velocity v_t = dI / dt measures the rate of queue shift, the second derivative
(imbalance acceleration / jerk) captures the mechanical force behind liquidity transitions:
    a_t = (v_t - v_{t-1}) / Delta t

Under normal market conditions:
1. Imbalance transitions are smooth as market makers adjust quotes continuously, keeping |a_t| small.

However, during predatory liquidity pulls, quote flickering, or flash crashes (Cartea & Jaimungal 2014;
Cont, Kukanov & Stoikov 2014; Biais et al. 1995):
1. Acute Imbalance Acceleration Shock (|a_t| >= 40.0 / s^2 within Delta t <= 0.10s):
   Signals violent, abrupt depth cancellation or predatory liquidity sweeps.
2. Rolling Acceleration Jerk (RMS(a) >= 15.0 / s^2 across N >= 10 ticks with spread >= 2.20 bps):
   Signals violent oscillating quote warfare or chaotic order book instability.
3. Unilateral Depth Collapse:
   Instantaneous evaporation where one queue drops by > 85% in <= 0.15s (Q_t <= 0.15 * Q_{t-1}
   with Q_{t-1} >= 2.0 lots) while the opposite queue remains elevated.

When any of these anomalies occur, the guard trips an execution block for
`cooldown_seconds` (default: 45.0s) to protect against severe adverse selection.

Thread Safety: Protected by threading.RLock.
Fail-Closed: Any non-numeric, NaN, infinite, or non-positive depth/spread inputs trip an immediate block.
"""

from collections import deque
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class Wave326LOBDepthAsymmetryAccelerationGuard:
    """Wave 326: LOB Depth Asymmetry Acceleration & Liquidity Evaporation Guard."""

    def __init__(
        self,
        window_size: int = 10,
        acute_accel_threshold: float = 40.0,
        rms_accel_threshold: float = 15.0,
        spread_threshold_bps: float = 2.20,
        collapse_ratio: float = 0.15,
        collapse_min_prior_depth: float = 2.0,
        collapse_time_window_s: float = 0.15,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 3:
            window_size = 10
        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)) or cooldown_seconds <= 0:
            cooldown_seconds = 45.0

        self.window_size = window_size
        self.acute_accel_threshold = float(acute_accel_threshold)
        self.rms_accel_threshold = float(rms_accel_threshold)
        self.spread_threshold_bps = float(spread_threshold_bps)
        self.collapse_ratio = float(collapse_ratio)
        self.collapse_min_prior_depth = float(collapse_min_prior_depth)
        self.collapse_time_window_s = float(collapse_time_window_s)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._accelerations: deque = deque(maxlen=self.window_size)
        self._last_imbalance: Optional[float] = None
        self._last_velocity: Optional[float] = None
        self._last_time: Optional[float] = None
        self._last_q_bid: Optional[float] = None
        self._last_q_ask: Optional[float] = None
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""
        self._last_acceleration: float = 0.0
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
        bid_price: float,
        ask_price: float,
        bid_depth: float,
        ask_depth: float,
        current_time: Optional[float] = None,
    ) -> bool:
        """Process an inside book snapshot and evaluate imbalance acceleration.

        Returns True if trading is blocked, False otherwise.
        """
        now = time.monotonic() if current_time is None else float(current_time)

        with self._lock:
            self._total_updates += 1

            v_bid = self._validate_numeric(bid_price)
            v_ask = self._validate_numeric(ask_price)
            v_qbid = self._validate_numeric(bid_depth)
            v_qask = self._validate_numeric(ask_depth)

            if v_bid is None or v_ask is None or v_qbid is None or v_qask is None:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = "FAIL_CLOSED: Non-numeric, NaN, or infinite price/depth input"
                self._total_violations += 1
                return True

            spread = v_ask - v_bid
            if spread <= 0.0 or v_qbid <= 0.0 or v_qask <= 0.0:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = (
                    f"FAIL_CLOSED: Invalid book state: spread={spread:.6f}, Q_bid={v_qbid}, Q_ask={v_qask}"
                )
                self._total_violations += 1
                return True

            mid_price = (v_bid + v_ask) / 2.0
            spread_bps = (spread / mid_price) * 10000.0
            imbalance = (v_qbid - v_qask) / (v_qbid + v_qask)

            if self._last_time is None:
                self._last_imbalance = imbalance
                self._last_time = now
                self._last_q_bid = v_qbid
                self._last_q_ask = v_qask
                return now < self._blocked_until

            dt = now - self._last_time
            if dt <= 0.0:
                dt = 1e-4  # Sub-millisecond clamp

            # 1. Unilateral Depth Collapse Check
            if dt <= self.collapse_time_window_s and self._last_q_bid is not None and self._last_q_ask is not None:
                bid_collapsed = (
                    self._last_q_bid >= self.collapse_min_prior_depth
                    and v_qbid <= self.collapse_ratio * self._last_q_bid
                )
                ask_collapsed = (
                    self._last_q_ask >= self.collapse_min_prior_depth
                    and v_qask <= self.collapse_ratio * self._last_q_ask
                )
                if bid_collapsed or ask_collapsed:
                    self._blocked_until = now + self.cooldown_seconds
                    side = "BID" if bid_collapsed else "ASK"
                    self._last_block_reason = (
                        f"UNILATERAL_DEPTH_COLLAPSE: {side} depth collapsed by > "
                        f"{int((1 - self.collapse_ratio) * 100)}% in {dt:.3f}s"
                    )
                    self._total_violations += 1
                    self._last_time = now
                    self._last_imbalance = imbalance
                    self._last_q_bid = v_qbid
                    self._last_q_ask = v_qask
                    return True

            velocity = (imbalance - self._last_imbalance) / dt

            if self._last_velocity is not None:
                acceleration = (velocity - self._last_velocity) / dt
                self._last_acceleration = acceleration

                # 2. Acute Imbalance Acceleration Shock
                if dt <= 0.10 and abs(acceleration) >= self.acute_accel_threshold:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"ACUTE_IMBALANCE_ACCELERATION_SHOCK: Acceleration |{acceleration:.2f}| /s^2 "
                        f">= threshold {self.acute_accel_threshold:.2f} /s^2 in {dt:.3f}s"
                    )
                    self._total_violations += 1
                    self._last_velocity = velocity
                    self._last_imbalance = imbalance
                    self._last_time = now
                    self._last_q_bid = v_qbid
                    self._last_q_ask = v_qask
                    return True

                self._accelerations.append(acceleration)

                # 3. Rolling Acceleration Jerk with elevated spread
                if len(self._accelerations) >= self.window_size and spread_bps >= self.spread_threshold_bps:
                    accels = list(self._accelerations)
                    rms_accel = math.sqrt(sum(a ** 2 for a in accels) / len(accels))
                    if rms_accel >= self.rms_accel_threshold:
                        self._blocked_until = now + self.cooldown_seconds
                        self._last_block_reason = (
                            f"ROLLING_ACCELERATION_JERK: RMS accel {rms_accel:.2f} /s^2 >= "
                            f"{self.rms_accel_threshold:.2f} /s^2 with spread {spread_bps:.2f} bps"
                        )
                        self._total_violations += 1
                        self._last_velocity = velocity
                        self._last_imbalance = imbalance
                        self._last_time = now
                        self._last_q_bid = v_qbid
                        self._last_q_ask = v_qask
                        return True

            self._last_velocity = velocity
            self._last_imbalance = imbalance
            self._last_time = now
            self._last_q_bid = v_qbid
            self._last_q_ask = v_qask

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
        """Reset internal buffers and block states."""
        with self._lock:
            self._accelerations.clear()
            self._last_imbalance = None
            self._last_velocity = None
            self._last_time = None
            self._last_q_bid = None
            self._last_q_ask = None
            self._blocked_until = 0.0
            self._last_block_reason = ""
            self._last_acceleration = 0.0
            self._total_updates = 0
            self._total_violations = 0

    def get_status(self, current_time: Optional[float] = None) -> Dict[str, Any]:
        """Return diagnostic metrics and state dictionary."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            remaining_cooldown = max(0.0, self._blocked_until - now)
            accels = list(self._accelerations)
            rms = math.sqrt(sum(a ** 2 for a in accels) / len(accels)) if accels else 0.0

            return {
                "guard_name": "Wave326LOBDepthAsymmetryAccelerationGuard",
                "is_blocked": now < self._blocked_until,
                "remaining_cooldown_s": round(remaining_cooldown, 3),
                "last_block_reason": self._last_block_reason,
                "last_acceleration": round(self._last_acceleration, 4),
                "rolling_rms_acceleration": round(rms, 4),
                "buffer_fill": len(self._accelerations),
                "total_updates": self._total_updates,
                "total_violations": self._total_violations,
            }
