"""Wave 322: LOB Minimum Tick Discretization & Spread Step Quantization Anomaly Guard.

Mathematical and Microstructural Context:
----------------------------------------
In modern electronic central limit order books, price quotes are strictly constrained
to discrete increments defined by the minimum price variation (tick size Delta_tick),
established by exchange rules (Harris 1994; O'Hara 2015; Hasbrouck 2007).
The instantaneous bid-ask spread is therefore an integer multiple of tick steps:
    S_t = a_t - b_t
    k_t = S_t / Delta_tick

Under normal market conditions:
1. k_t in {1, 2, 3, ...} with fractional tick residual delta_t = |k_t - round(k_t)| ~= 0.0.
2. Under abnormal microstructure conditions or market feed corruption:
   a. Fractional Sub-Penny Residuals (delta_t >= delta_max, e.g. 0.05):
      Indicates synthetic sub-penny quotes, cross-broker feed desynchronization,
      or dark pool / internalization quote injection leaking into lit books.
   b. Inverted / Zero-Spread Crossings (k_t < 0.95 or S_t <= 0):
      Indicates crossed or locked order book conditions where ask <= bid,
      violating no-arbitrage bounds and causing severe execution rejections.
   c. Quantization Pinning / Collusion Grid Lock:
      Spread is artificially widened and rigidly pegged to an elevated multiple
      (k_bar >= 4.5 ticks) with near-zero step variance (std(k) <= 0.05) over N >= 10 ticks,
      signaling predatory market maker quote freezing or quote stuffing.
   d. Acute Quantization Step Blowout:
      Single-tick spread expansion exceeding k_max (e.g. k_t >= 8.0 ticks),
      signaling acute liquidity exhaustion across the inner book.

When any of these anomalies occur, the guard trips an execution block for
`cooldown_seconds` (default: 45.0s) to protect high-frequency scalpers from
adverse selection and execution failures.

Thread Safety: Protected by threading.RLock.
Fail-Closed: Any non-numeric, NaN, infinite, or boolean input trips an immediate block.
"""

from collections import deque
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class Wave322LOBSpreadStepQuantizationGuard:
    """Wave 322: Limit Order Book Spread Step Quantization Anomaly Guard."""

    def __init__(
        self,
        tick_size: float = 0.0001,
        window_size: int = 12,
        max_fractional_residual: float = 0.05,
        min_tick_ratio: float = 0.95,
        pinning_step_threshold: float = 4.5,
        pinning_std_max: float = 0.05,
        acute_step_threshold: float = 8.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if isinstance(tick_size, bool) or not isinstance(tick_size, (int, float)) or tick_size <= 0:
            tick_size = 0.0001
        if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 3:
            window_size = 12
        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)) or cooldown_seconds <= 0:
            cooldown_seconds = 45.0

        self.tick_size = float(tick_size)
        self.window_size = window_size
        self.max_fractional_residual = float(max_fractional_residual)
        self.min_tick_ratio = float(min_tick_ratio)
        self.pinning_step_threshold = float(pinning_step_threshold)
        self.pinning_std_max = float(pinning_std_max)
        self.acute_step_threshold = float(acute_step_threshold)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._spread_steps: deque = deque(maxlen=self.window_size)
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""
        self._last_step_multiple: float = 1.0
        self._last_fractional_residual: float = 0.0
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
        current_time: Optional[float] = None,
    ) -> bool:
        """Process a top-of-book quote update and assess spread quantization integrity.

        Returns True if trading is blocked, False otherwise.
        """
        now = time.monotonic() if current_time is None else float(current_time)

        with self._lock:
            self._total_updates += 1

            v_bid = self._validate_numeric(bid_price)
            v_ask = self._validate_numeric(ask_price)

            if v_bid is None or v_ask is None:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = "FAIL_CLOSED: Non-numeric, NaN, or infinite price input"
                self._total_violations += 1
                return True

            spread = v_ask - v_bid
            if spread <= 0.0:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = f"LOB_CROSSED_OR_LOCKED: Spread {spread:.6f} <= 0 (Ask {v_ask} <= Bid {v_bid})"
                self._total_violations += 1
                return True

            k = spread / self.tick_size
            self._last_step_multiple = k
            nearest_int = round(k)
            residual = abs(k - nearest_int)
            self._last_fractional_residual = residual

            # 1. Inverted / sub-tick spread check
            if k < self.min_tick_ratio:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = f"SUB_TICK_ANOMALY: Spread {k:.3f} ticks < minimum {self.min_tick_ratio:.2f}"
                self._total_violations += 1
                return True

            # 2. Acute step blowout
            if k >= self.acute_step_threshold:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = (
                    f"ACUTE_SPREAD_STEP_BLOWOUT: Spread {k:.2f} ticks >= threshold {self.acute_step_threshold:.2f}"
                )
                self._total_violations += 1
                return True

            # 3. Fractional sub-penny quantization violation
            if residual > self.max_fractional_residual:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = (
                    f"QUANTIZATION_RESIDUAL_VIOLATION: Spread {k:.4f} ticks has residual "
                    f"{residual:.4f} > {self.max_fractional_residual:.4f}"
                )
                self._total_violations += 1
                return True

            self._spread_steps.append(k)

            # 4. Rolling quantization pinning / collusion lock
            if len(self._spread_steps) >= self.window_size:
                steps_list = list(self._spread_steps)
                mean_k = sum(steps_list) / len(steps_list)
                var_k = sum((x - mean_k) ** 2 for x in steps_list) / len(steps_list)
                std_k = math.sqrt(var_k)

                if mean_k >= self.pinning_step_threshold and std_k <= self.pinning_std_max:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"SPREAD_QUANTIZATION_PINNING: Mean step {mean_k:.2f} >= {self.pinning_step_threshold:.2f} "
                        f"with rigid std {std_k:.4f} <= {self.pinning_std_max:.4f}"
                    )
                    self._total_violations += 1
                    return True

            # Check if currently active block is ongoing
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
            self._spread_steps.clear()
            self._blocked_until = 0.0
            self._last_block_reason = ""
            self._last_step_multiple = 1.0
            self._last_fractional_residual = 0.0
            self._total_updates = 0
            self._total_violations = 0

    def get_status(self, current_time: Optional[float] = None) -> Dict[str, Any]:
        """Return diagnostic metrics and state dictionary."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            remaining_cooldown = max(0.0, self._blocked_until - now)
            steps_list = list(self._spread_steps)
            mean_k = (sum(steps_list) / len(steps_list)) if steps_list else 1.0
            var_k = (sum((x - mean_k) ** 2 for x in steps_list) / len(steps_list)) if steps_list else 0.0
            std_k = math.sqrt(var_k)

            return {
                "guard_name": "Wave322LOBSpreadStepQuantizationGuard",
                "is_blocked": now < self._blocked_until,
                "remaining_cooldown_s": round(remaining_cooldown, 3),
                "last_block_reason": self._last_block_reason,
                "tick_size": self.tick_size,
                "last_step_multiple": round(self._last_step_multiple, 4),
                "last_fractional_residual": round(self._last_fractional_residual, 4),
                "rolling_mean_step": round(mean_k, 3),
                "rolling_std_step": round(std_k, 4),
                "buffer_fill": len(self._spread_steps),
                "total_updates": self._total_updates,
                "total_violations": self._total_violations,
            }
