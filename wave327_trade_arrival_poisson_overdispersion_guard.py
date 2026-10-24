"""Wave 327: High-Frequency Trade Arrival Cox Process & Poisson Overdispersion Index (Fano Factor) Guard.

Mathematical and Microstructural Context:
----------------------------------------
Under the classic null hypothesis of uncoordinated, independent liquidity demand,
trade arrival events follow a homogeneous Poisson point process.
For a Poisson process, the event count N in fixed time bins of duration Delta t
satisfies the equi-dispersion property: Var(N) = E[N].
The Fano Factor (Index of Dispersion, Cox 1955; Daley & Vere-Jones 2003; Hautsch 2012) is:
    F = Var(N) / E[N] ~= 1.0

However, in algorithmic financial markets:
1. Overdispersion Clustering & Hawkes Cascades (F >= 3.50 with lambda_bar >= 8.0 trades/s):
   High-frequency cascading orders and predatory stops produce extreme arrival clustering,
   signaling non-Poisson Doubly Stochastic / Cox process dynamics with heavy tail variance.
2. Underdispersion Anomaly / Robotic Clock Pacing (F <= 0.15 with lambda_bar >= 4.0 trades/s):
   Artificially uniform trade arrivals where Var(N) approaches zero, characteristic of
   rigid algorithmic TWAP/VWAP execution slicing loops and machine pinging.
3. Acute Count & Volume Blast:
   A single micro-bin experiencing explosive activity (N_k >= 25 trades with V_k >= 15.0 lots
   within Delta t = 0.50s), signaling an institutional execution avalanche.

When any of these anomalies occur, the guard trips an execution block for
`cooldown_seconds` (default: 45.0s) to protect against severe adverse selection.

Thread Safety: Protected by threading.RLock.
Fail-Closed: Any non-numeric, NaN, infinite, non-positive volume or inverted timestamp
trips an immediate block.
"""

from collections import deque
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class Wave327TradeArrivalPoissonOverdispersionGuard:
    """Wave 327: Trade Arrival Poisson Overdispersion (Fano Factor) Guard."""

    def __init__(
        self,
        bin_duration_s: float = 0.50,
        window_size_bins: int = 15,
        overdispersion_threshold: float = 3.50,
        underdispersion_threshold: float = 0.15,
        min_rate_overdispersed: float = 8.0,
        min_rate_underdispersed: float = 4.0,
        acute_bin_trade_count: int = 25,
        acute_bin_volume: float = 15.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if isinstance(bin_duration_s, bool) or not isinstance(bin_duration_s, (int, float)) or bin_duration_s <= 0:
            bin_duration_s = 0.50
        if isinstance(window_size_bins, bool) or not isinstance(window_size_bins, int) or window_size_bins < 4:
            window_size_bins = 15
        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)) or cooldown_seconds <= 0:
            cooldown_seconds = 45.0

        self.bin_duration_s = float(bin_duration_s)
        self.window_size_bins = window_size_bins
        self.overdispersion_threshold = float(overdispersion_threshold)
        self.underdispersion_threshold = float(underdispersion_threshold)
        self.min_rate_overdispersed = float(min_rate_overdispersed)
        self.min_rate_underdispersed = float(min_rate_underdispersed)
        self.acute_bin_trade_count = int(acute_bin_trade_count)
        self.acute_bin_volume = float(acute_bin_volume)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._bin_counts: deque = deque(maxlen=self.window_size_bins)
        self._current_bin_start: Optional[float] = None
        self._current_bin_trades: int = 0
        self._current_bin_volume: float = 0.0
        self._last_trade_time: Optional[float] = None
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""
        self._last_fano_factor: float = 1.0
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
        trade_timestamp: float,
        current_time: Optional[float] = None,
    ) -> bool:
        """Process a trade print and evaluate trade arrival Poisson dispersion.

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

            if self._last_trade_time is not None and v_ts < self._last_trade_time:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = (
                    f"TIMESTAMP_INVERSION: Current ts {v_ts} < prior {self._last_trade_time}"
                )
                self._total_violations += 1
                return True

            self._last_trade_time = v_ts

            if self._current_bin_start is None:
                self._current_bin_start = v_ts
                self._current_bin_trades = 1
                self._current_bin_volume = v_vol
                return now < self._blocked_until

            # Check if trade falls into current bin or rolls over
            if (v_ts - self._current_bin_start) < self.bin_duration_s:
                self._current_bin_trades += 1
                self._current_bin_volume += v_vol

                # Acute count & volume blast check
                if (
                    self._current_bin_trades >= self.acute_bin_trade_count
                    and self._current_bin_volume >= self.acute_bin_volume
                ):
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"ACUTE_COUNT_VOLUME_BLAST: {self._current_bin_trades} trades with "
                        f"{self._current_bin_volume:.2f} lots in bin {self.bin_duration_s:.2f}s"
                    )
                    self._total_violations += 1
                    return True

            else:
                # Close current bin, append to history
                self._bin_counts.append(self._current_bin_trades)

                # Reset new bin
                self._current_bin_start = v_ts
                self._current_bin_trades = 1
                self._current_bin_volume = v_vol

                # Evaluate rolling Fano factor
                if len(self._bin_counts) >= 8:
                    counts = list(self._bin_counts)
                    mean_n = sum(counts) / len(counts)
                    if mean_n > 0.0:
                        var_n = sum((x - mean_n) ** 2 for x in counts) / len(counts)
                        fano = var_n / mean_n
                        self._last_fano_factor = fano
                        lambda_rate = mean_n / self.bin_duration_s

                        # 1. Overdispersion surge
                        if fano >= self.overdispersion_threshold and lambda_rate >= self.min_rate_overdispersed:
                            self._blocked_until = now + self.cooldown_seconds
                            self._last_block_reason = (
                                f"POISSON_OVERDISPERSION_SURGE: Fano factor {fano:.2f} >= "
                                f"{self.overdispersion_threshold:.2f} with arrival rate "
                                f"{lambda_rate:.1f} trades/s"
                            )
                            self._total_violations += 1
                            return True

                        # 2. Underdispersion anomaly
                        if fano <= self.underdispersion_threshold and lambda_rate >= self.min_rate_underdispersed:
                            self._blocked_until = now + self.cooldown_seconds
                            self._last_block_reason = (
                                f"ROBOTIC_UNDERDISPERSION_ANOMALY: Fano factor {fano:.3f} <= "
                                f"{self.underdispersion_threshold:.2f} with arrival rate "
                                f"{lambda_rate:.1f} trades/s"
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
            self._bin_counts.clear()
            self._current_bin_start = None
            self._current_bin_trades = 0
            self._current_bin_volume = 0.0
            self._last_trade_time = None
            self._blocked_until = 0.0
            self._last_block_reason = ""
            self._last_fano_factor = 1.0
            self._total_trades = 0
            self._total_violations = 0

    def get_status(self, current_time: Optional[float] = None) -> Dict[str, Any]:
        """Return diagnostic metrics and state dictionary."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            remaining_cooldown = max(0.0, self._blocked_until - now)
            counts = list(self._bin_counts)
            mean_n = (sum(counts) / len(counts)) if counts else float(self._current_bin_trades)
            rate = mean_n / self.bin_duration_s

            return {
                "guard_name": "Wave327TradeArrivalPoissonOverdispersionGuard",
                "is_blocked": now < self._blocked_until,
                "remaining_cooldown_s": round(remaining_cooldown, 3),
                "last_block_reason": self._last_block_reason,
                "last_fano_factor": round(self._last_fano_factor, 4),
                "rolling_arrival_rate_trades_per_s": round(rate, 2),
                "current_bin_trades": self._current_bin_trades,
                "current_bin_volume": round(self._current_bin_volume, 3),
                "completed_bins_fill": len(self._bin_counts),
                "total_trades": self._total_trades,
                "total_violations": self._total_violations,
            }
