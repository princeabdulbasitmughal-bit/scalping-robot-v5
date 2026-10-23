"""Wave 323: High-Frequency Trade Arrival Log-Time Self-Similarity & Hurst Exponent Guard.

Mathematical and Microstructural Context:
----------------------------------------
In high-frequency algorithmic markets, the arrival sequence of aggressive market orders
reflects the temporal clustering and self-similarity of market participants
(Mandelbrot 1968; Cont 2001; Cartea, Jaimungal & Penalva 2015).
Under the null hypothesis of uncoordinated, independent liquidity demand (standard Poisson
process), order arrivals exhibit short-memory dynamics with Hurst exponent H ~= 0.50.

However, during adversarial or predatory market conditions:
1. Antipersistent Machine Pinging (H <= H_low, e.g. 0.22 with rapid arrival tau_bar <= 0.15s):
   High-frequency pinging engines and sub-millisecond execution probes generate artificially
   alternating, mean-reverting inter-arrival times to scan for hidden resting liquidity or
   bait latency-sensitive market makers.
2. Hyper-Persistent Runaway Cascade (H >= H_high, e.g. 0.88 with rapid arrival tau_bar <= 0.20s):
   Aggressive orders trigger cascading stop-loss sweeps and algorithmic copycat loops,
   exhibiting heavy long-range dependence and impending order book collapse.
3. Acute Deterministic Slicing Streak:
   Consecutive trade intervals with virtually zero variance (|tau_i - tau_{i-1}| <= 1 ms)
   persisting across N_streak >= 6 trades, indicating hard-coded slicing loops (TWAP/VWAP).

Rescaled Range (R/S) Hurst Calculation:
---------------------------------------
Given a rolling window of N inter-arrival times tau_i:
    tau_bar = (1 / N) * sum(tau_i)
    Y_k = sum_{j=1}^k (tau_j - tau_bar)   for k = 1, ..., N
    R = max(Y_k) - min(Y_k)
    S = sqrt((1 / N) * sum((tau_i - tau_bar)^2))
    If S > 1e-9:
        R/S = R / S
        H = ln(R/S) / ln(N)
    Else:
        H = 0.0 (deterministic clock pacing)

When abnormal self-similarity or deterministic pinging is detected, the guard trips
an execution block for `cooldown_seconds` (default: 45.0s).

Thread Safety: Protected by threading.RLock.
Fail-Closed: Any non-numeric, NaN, infinite, or negative input trips an immediate block.
"""

from collections import deque
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class Wave323TradeArrivalSelfSimilarityHurstGuard:
    """Wave 323: Trade Arrival Self-Similarity & Hurst Exponent Guard."""

    def __init__(
        self,
        window_size: int = 20,
        h_low_threshold: float = 0.15,
        h_high_threshold: float = 0.65,
        rapid_arrival_threshold_s: float = 0.15,
        cascade_arrival_threshold_s: float = 0.20,
        identical_interval_tolerance_s: float = 0.001,
        identical_streak_threshold: int = 6,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 8:
            window_size = 20
        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)) or cooldown_seconds <= 0:
            cooldown_seconds = 45.0

        self.window_size = window_size
        self.h_low_threshold = float(h_low_threshold)
        self.h_high_threshold = float(h_high_threshold)
        self.rapid_arrival_threshold_s = float(rapid_arrival_threshold_s)
        self.cascade_arrival_threshold_s = float(cascade_arrival_threshold_s)
        self.identical_interval_tolerance_s = float(identical_interval_tolerance_s)
        self.identical_streak_threshold = int(identical_streak_threshold)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._inter_arrivals: deque = deque(maxlen=self.window_size)
        self._last_trade_timestamp: Optional[float] = None
        self._identical_streak: int = 0
        self._last_interval: float = 0.0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""
        self._last_calculated_hurst: float = 0.50
        self._total_trades: int = 0
        self._total_violations: int = 0

    def _validate_numeric(self, val: Any) -> Optional[float]:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return None
        fval = float(val)
        if math.isnan(fval) or math.isinf(fval):
            return None
        return fval

    def _calculate_hurst(self, intervals: List[float]) -> float:
        """Calculate the empirical Hurst exponent via Rescaled Range (R/S) analysis."""
        n = len(intervals)
        if n < 8:
            return 0.50

        mean_tau = sum(intervals) / n
        var_tau = sum((x - mean_tau) ** 2 for x in intervals) / n
        s = math.sqrt(var_tau)

        if s <= 1e-9:
            return 0.0  # Perfect determinism

        # Cumulative deviations starting from 0.0
        y_k = [0.0]
        running_sum = 0.0
        for x in intervals:
            running_sum += (x - mean_tau)
            y_k.append(running_sum)

        r = max(y_k) - min(y_k)
        if r <= 1e-9:
            return 0.0

        rs = r / s
        if rs <= 1.0:
            h = 0.0
        else:
            h = math.log(rs) / math.log(n)

        # Bound H to [0.0, 1.0]
        return max(0.0, min(1.0, h))

    def update(
        self,
        trade_volume: float,
        trade_timestamp: float,
        current_time: Optional[float] = None,
    ) -> bool:
        """Process a trade print and evaluate self-similarity & Hurst exponent.

        Returns True if trading is blocked, False otherwise.
        """
        now = time.monotonic() if current_time is None else float(current_time)

        with self._lock:
            self._total_trades += 1

            v_vol = self._validate_numeric(trade_volume)
            v_ts = self._validate_numeric(trade_timestamp)

            if v_vol is None or v_ts is None or v_vol <= 0.0:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = "FAIL_CLOSED: Non-numeric, NaN, infinite, or non-positive trade input"
                self._total_violations += 1
                return True

            if self._last_trade_timestamp is None:
                self._last_trade_timestamp = v_ts
                return now < self._blocked_until

            dt = v_ts - self._last_trade_timestamp
            if dt < 0.0:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = f"TIMESTAMP_INVERSION: Current ts {v_ts} < last ts {self._last_trade_timestamp}"
                self._total_violations += 1
                return True

            self._last_trade_timestamp = v_ts
            dt = max(1e-6, dt)  # Sub-microsecond clamp

            # Check for identical interval streak (deterministic slicing loop)
            if abs(dt - self._last_interval) <= self.identical_interval_tolerance_s:
                self._identical_streak += 1
            else:
                self._identical_streak = 1
            self._last_interval = dt

            if self._identical_streak >= self.identical_streak_threshold:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = (
                    f"DETERMINISTIC_SLICING_STREAK: {self._identical_streak} consecutive trades "
                    f"with identical interval {dt:.4f}s"
                )
                self._total_violations += 1
                return True

            self._inter_arrivals.append(dt)

            # Rolling Hurst analysis once buffer has sufficient depth
            if len(self._inter_arrivals) >= 12:
                intervals = list(self._inter_arrivals)
                mean_dt = sum(intervals) / len(intervals)
                h = self._calculate_hurst(intervals)
                self._last_calculated_hurst = h

                # 1. Antipersistent machine pinging
                if h <= self.h_low_threshold and mean_dt <= self.rapid_arrival_threshold_s:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"ANTIPERSISTENT_MACHINE_PINGING: Hurst H={h:.3f} <= {self.h_low_threshold:.2f} "
                        f"with mean dt {mean_dt:.4f}s <= {self.rapid_arrival_threshold_s:.2f}s"
                    )
                    self._total_violations += 1
                    return True

                # 2. Hyper-persistent runaway cascade
                if h >= self.h_high_threshold and mean_dt <= self.cascade_arrival_threshold_s:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"HYPER_PERSISTENT_RUNAWAY_CASCADE: Hurst H={h:.3f} >= {self.h_high_threshold:.2f} "
                        f"with mean dt {mean_dt:.4f}s <= {self.cascade_arrival_threshold_s:.2f}s"
                    )
                    self._total_violations += 1
                    return True

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
            self._inter_arrivals.clear()
            self._last_trade_timestamp = None
            self._identical_streak = 0
            self._last_interval = 0.0
            self._blocked_until = 0.0
            self._last_block_reason = ""
            self._last_calculated_hurst = 0.50
            self._total_trades = 0
            self._total_violations = 0

    def get_status(self, current_time: Optional[float] = None) -> Dict[str, Any]:
        """Return diagnostic metrics and state dictionary."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            remaining_cooldown = max(0.0, self._blocked_until - now)
            intervals = list(self._inter_arrivals)
            mean_dt = (sum(intervals) / len(intervals)) if intervals else 0.0

            return {
                "guard_name": "Wave323TradeArrivalSelfSimilarityHurstGuard",
                "is_blocked": now < self._blocked_until,
                "remaining_cooldown_s": round(remaining_cooldown, 3),
                "last_block_reason": self._last_block_reason,
                "hurst_exponent": round(self._last_calculated_hurst, 4),
                "rolling_mean_inter_arrival_s": round(mean_dt, 5),
                "identical_interval_streak": self._identical_streak,
                "buffer_fill": len(self._inter_arrivals),
                "total_trades": self._total_trades,
                "total_violations": self._total_violations,
            }
