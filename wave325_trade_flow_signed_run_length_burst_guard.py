"""Wave 325: High-Frequency Trade Flow Signed Consecutive Run-Length & Toxic Barrage Guard.

Mathematical and Microstructural Context:
----------------------------------------
In balanced financial markets, trade arrival signs epsilon_t in {-1, +1} (buy/sell)
exhibit rapid mean-reversion with run lengths L_run distributed geometrically
with expected value E[L_run] ~= 2.0 (Biais et al. 1995; Hasbrouck 1991; Cont 2001).

However, during predatory execution sweeps, stop-loss cascading cascades, or large Iceberg orders:
1. Toxic Run-Length & Volume Sweep (L_run >= 8 with V_run >= 12.0 lots):
   A continuous, uninterrupted sequence of aggressive trades on one side exhausting
   the inside depth and signaling severe asymmetric information.
2. Rolling Run-Length Concentration (mean(L_run) >= 4.2 across N >= 8 distinct runs):
   Persistent clustering of long runs indicating prolonged unilateral order flow
   toxicity where passive market making faces heavy inventory adverse selection.
3. Acute In-Run Volume Acceleration (V_t >= 2.5 * V_{t-1} with V_t >= 5.0 lots):
   Aggressive in-run sizing spikes indicating a predatory participant ramping up
   execution intensity to punch through resting liquidity barriers.

When any of these conditions are met, the guard trips an execution block for
`cooldown_seconds` (default: 45.0s).

Thread Safety: Protected by threading.RLock.
Fail-Closed: Any non-numeric, NaN, infinite, non-positive volume or invalid trade sign
trips an immediate block.
"""

from collections import deque
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class Wave325TradeFlowSignedRunLengthBurstGuard:
    """Wave 325: Trade Flow Signed Consecutive Run-Length & Toxic Barrage Guard."""

    def __init__(
        self,
        max_run_length: int = 8,
        max_run_volume: float = 12.0,
        run_history_window: int = 8,
        mean_run_length_threshold: float = 4.2,
        acceleration_factor: float = 2.5,
        acceleration_min_volume: float = 5.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if isinstance(max_run_length, bool) or not isinstance(max_run_length, int) or max_run_length < 3:
            max_run_length = 8
        if isinstance(run_history_window, bool) or not isinstance(run_history_window, int) or run_history_window < 4:
            run_history_window = 8
        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)) or cooldown_seconds <= 0:
            cooldown_seconds = 45.0

        self.max_run_length = max_run_length
        self.max_run_volume = float(max_run_volume)
        self.run_history_window = run_history_window
        self.mean_run_length_threshold = float(mean_run_length_threshold)
        self.acceleration_factor = float(acceleration_factor)
        self.acceleration_min_volume = float(acceleration_min_volume)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._completed_run_lengths: deque = deque(maxlen=self.run_history_window)
        self._current_run_sign: Optional[int] = None
        self._current_run_length: int = 0
        self._current_run_volume: float = 0.0
        self._last_trade_volume: float = 0.0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""
        self._total_trades: int = 0
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
        trade_volume: float,
        trade_sign: int,
        current_time: Optional[float] = None,
    ) -> bool:
        """Process an aggressive trade print and evaluate run-length toxicity.

        trade_sign: +1 for Buy, -1 for Sell.
        Returns True if trading is blocked, False otherwise.
        """
        now = time.monotonic() if current_time is None else float(current_time)

        with self._lock:
            self._total_trades += 1

            v_vol = self._validate_numeric(trade_volume)
            v_sign = self._validate_numeric(trade_sign)

            if v_vol is None or v_sign is None or v_vol <= 0.0 or v_sign not in (-1.0, 1.0):
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = (
                    f"FAIL_CLOSED: Invalid trade input: vol={trade_volume}, sign={trade_sign}"
                )
                self._total_violations += 1
                return True

            sign_int = 1 if v_sign > 0 else -1

            if self._current_run_sign is None:
                # First trade starts initial run
                self._current_run_sign = sign_int
                self._current_run_length = 1
                self._current_run_volume = v_vol
                self._last_trade_volume = v_vol
                return now < self._blocked_until

            if sign_int == self._current_run_sign:
                # Continuation of current run
                self._current_run_length += 1
                self._current_run_volume += v_vol

                # 1. Acute In-Run Volume Acceleration
                if (
                    v_vol >= self.acceleration_min_volume
                    and self._last_trade_volume > 0.0
                    and (v_vol / self._last_trade_volume) >= self.acceleration_factor
                ):
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"ACUTE_IN_RUN_VOLUME_ACCELERATION: Volume surge {v_vol:.2f} >= "
                        f"{self.acceleration_factor:.1f}x prior {self._last_trade_volume:.2f} "
                        f"during {self._current_run_length}-trade run"
                    )
                    self._total_violations += 1
                    self._last_trade_volume = v_vol
                    return True

                self._last_trade_volume = v_vol

                # 2. Toxic Run-Length & Volume Sweep
                if (
                    self._current_run_length >= self.max_run_length
                    and self._current_run_volume >= self.max_run_volume
                ):
                    self._blocked_until = now + self.cooldown_seconds
                    side_str = "BUY" if sign_int > 0 else "SELL"
                    self._last_block_reason = (
                        f"TOXIC_RUN_LENGTH_SWEEP: {self._current_run_length} consecutive {side_str} trades "
                        f"with cumulative volume {self._current_run_volume:.2f} lots >= {self.max_run_volume:.2f}"
                    )
                    self._total_violations += 1
                    return True

            else:
                # Run ended, record completed run length
                self._completed_run_lengths.append(self._current_run_length)

                # Check rolling run-length concentration
                if len(self._completed_run_lengths) >= self.run_history_window:
                    mean_len = sum(self._completed_run_lengths) / len(self._completed_run_lengths)
                    if mean_len >= self.mean_run_length_threshold:
                        self._blocked_until = now + self.cooldown_seconds
                        self._last_block_reason = (
                            f"RUN_LENGTH_CONCENTRATION: Mean run length {mean_len:.2f} >= "
                            f"{self.mean_run_length_threshold:.2f} across {len(self._completed_run_lengths)} runs"
                        )
                        self._total_violations += 1
                        # Start new run
                        self._current_run_sign = sign_int
                        self._current_run_length = 1
                        self._current_run_volume = v_vol
                        self._last_trade_volume = v_vol
                        return True

                # Start new run
                self._current_run_sign = sign_int
                self._current_run_length = 1
                self._current_run_volume = v_vol
                self._last_trade_volume = v_vol

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
        """Reset internal buffers and state."""
        with self._lock:
            self._completed_run_lengths.clear()
            self._current_run_sign = None
            self._current_run_length = 0
            self._current_run_volume = 0.0
            self._last_trade_volume = 0.0
            self._blocked_until = 0.0
            self._last_block_reason = ""
            self._total_trades = 0
            self._total_violations = 0

    def get_status(self, current_time: Optional[float] = None) -> Dict[str, Any]:
        """Return diagnostic metrics and state dictionary."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            remaining_cooldown = max(0.0, self._blocked_until - now)
            runs_list = list(self._completed_run_lengths)
            mean_run = (sum(runs_list) / len(runs_list)) if runs_list else float(self._current_run_length)

            return {
                "guard_name": "Wave325TradeFlowSignedRunLengthBurstGuard",
                "is_blocked": now < self._blocked_until,
                "remaining_cooldown_s": round(remaining_cooldown, 3),
                "last_block_reason": self._last_block_reason,
                "current_run_sign": self._current_run_sign,
                "current_run_length": self._current_run_length,
                "current_run_volume": round(self._current_run_volume, 3),
                "rolling_mean_run_length": round(mean_run, 3),
                "completed_runs_fill": len(self._completed_run_lengths),
                "total_trades": self._total_trades,
                "total_violations": self._total_violations,
            }
