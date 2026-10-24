"""Wave 335: High-Frequency Trade Arrival Inter-Event Time Clustering & Power-Law Burstiness Guard.

Mathematical and Microstructural Context:
----------------------------------------
In high-frequency order flow dynamics (Engle & Russell 1998 ACD models; Goh & Barabasi 2008;
Biais, Hillion & Spatt 1995), trade arrival processes diverge drastically from standard Poisson
processes during predatory algorithmic sweeps and stop-loss cascades.

For a rolling window of N consecutive aggressive trades at timestamps t_1, t_2, ..., t_N:
    Inter-trade durations:  tau_i = t_i - t_{i-1} > 0
    Sample mean duration:   mu_tau = (1 / (N - 1)) * sum(tau_i)
    Sample standard dev:    sigma_tau = sqrt((1 / (N - 2)) * sum((tau_i - mu_tau)^2))
    Goh-Barabasi Burstiness Parameter:
        B = (sigma_tau - mu_tau) / (sigma_tau + mu_tau)   in [-1, +1]

Under regular / Poisson market regimes:
1. Periodic scheduled flow: sigma_tau -> 0 => B -> -1.
2. Standard memoryless Poisson flow: sigma_tau approx mu_tau => B approx 0.
3. Burstiness B <= 0.40 indicates healthy, non-predatory distributed arrival flow.

However, during informed institutional execution sweeps or algorithmic avalanche cascades:
1. Acute Inter-Event Burstiness Clustering (B >= 0.65 with compressed mu_tau <= 0.040s over N >= 15 trades):
   Signals heavy-tailed arrival clustering where hyper-concentrated trade bursts hit the order book.
2. Sub-100ms Trade Train Avalanche:
   >= 8 aggressive trades arriving within dt <= 0.10s with cumulative executed volume >= 10.0 lots.
3. Sub-Millisecond High-Frequency Stampede:
   >= 5 consecutive trades with tau_i <= 0.002s (2ms), indicating automated low-latency sniffing bots.

When any of these anomalies occur, the guard trips an execution block for
`cooldown_seconds` (default: 45.0s) to protect passive market maker orders against toxic adverse selection.

Thread Safety: Protected by threading.RLock.
Fail-Closed: Any non-numeric, NaN, infinite, non-positive volume or non-monotonic timestamps trip an immediate block.
"""

from collections import deque
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class Wave335TradeArrivalClusteringBurstinessGuard:
    """Wave 335: Trade Arrival Inter-Event Time Clustering & Burstiness Guard."""

    def __init__(
        self,
        window_size: int = 20,
        burstiness_threshold: float = 0.65,
        compressed_mean_duration_s: float = 0.040,
        train_trade_count: int = 8,
        train_time_window_s: float = 0.100,
        train_min_volume: float = 10.0,
        sub_ms_stampede_count: int = 5,
        sub_ms_threshold_s: float = 0.002,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 8:
            window_size = 20
        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)) or cooldown_seconds <= 0:
            cooldown_seconds = 45.0

        self.window_size = window_size
        self.burstiness_threshold = float(burstiness_threshold)
        self.compressed_mean_duration_s = float(compressed_mean_duration_s)
        self.train_trade_count = int(train_trade_count)
        self.train_time_window_s = float(train_time_window_s)
        self.train_min_volume = float(train_min_volume)
        self.sub_ms_stampede_count = int(sub_ms_stampede_count)
        self.sub_ms_threshold_s = float(sub_ms_threshold_s)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._durations: deque = deque(maxlen=self.window_size)
        self._recent_trades: deque = deque(maxlen=self.window_size)  # (timestamp, volume)
        self._sub_ms_consecutive: int = 0
        self._last_timestamp: Optional[float] = None
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""
        self._last_burstiness: float = 0.0
        self._last_mean_duration: float = 0.0
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
        current_time: Optional[float] = None,
    ) -> bool:
        """Process an incoming aggressive trade print with volume and arrival timestamp.

        Returns True if trading is blocked, False otherwise.
        """
        now = time.monotonic() if current_time is None else float(current_time)

        with self._lock:
            self._total_trades += 1

            v_vol = self._validate_numeric(trade_volume)
            if v_vol is None or v_vol <= 0.0:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = "FAIL_CLOSED: Non-numeric, NaN, or non-positive trade volume"
                self._total_violations += 1
                return True

            if self._last_timestamp is not None:
                tau = now - self._last_timestamp
                if tau <= 0.0:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = f"FAIL_CLOSED: Non-monotonic or duplicate timestamp (tau={tau:.6f}s)"
                    self._total_violations += 1
                    return True

                self._durations.append(tau)

                # Check sub-millisecond stampede count
                if tau <= self.sub_ms_threshold_s:
                    self._sub_ms_consecutive += 1
                    if self._sub_ms_consecutive >= self.sub_ms_stampede_count:
                        self._blocked_until = now + self.cooldown_seconds
                        self._last_block_reason = (
                            f"SUB_MS_STAMPEDE: {self._sub_ms_consecutive} consecutive trades <= "
                            f"{self.sub_ms_threshold_s * 1000.0:.1f}ms apart"
                        )
                        self._total_violations += 1
                        return True
                else:
                    self._sub_ms_consecutive = 0

            self._last_timestamp = now
            self._recent_trades.append((now, v_vol))

            # 1. Sub-100ms Trade Train Avalanche Check
            if len(self._recent_trades) >= self.train_trade_count:
                # Check recent window trades
                train_vol = 0.0
                train_cnt = 0
                for t_ts, t_sz in reversed(self._recent_trades):
                    if (now - t_ts) <= self.train_time_window_s:
                        train_vol += t_sz
                        train_cnt += 1
                    else:
                        break

                if train_cnt >= self.train_trade_count and train_vol >= self.train_min_volume:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"TRADE_TRAIN_AVALANCHE: {train_cnt} trades with volume {train_vol:.2f} lots "
                        f"within {self.train_time_window_s * 1000.0:.0f}ms (threshold: {self.train_min_volume:.1f} lots)"
                    )
                    self._total_violations += 1
                    return True

            # 2. Goh-Barabasi Burstiness Parameter Evaluation
            if len(self._durations) >= 12:
                n = len(self._durations)
                d_list = list(self._durations)
                mu_tau = sum(d_list) / n
                self._last_mean_duration = mu_tau

                var_tau = sum((x - mu_tau) ** 2 for x in d_list) / (n - 1)
                sigma_tau = math.sqrt(var_tau)

                if (sigma_tau + mu_tau) > 0.0:
                    b_param = (sigma_tau - mu_tau) / (sigma_tau + mu_tau)
                    self._last_burstiness = b_param

                    if b_param >= self.burstiness_threshold and mu_tau <= self.compressed_mean_duration_s:
                        self._blocked_until = now + self.cooldown_seconds
                        self._last_block_reason = (
                            f"TRADE_ARRIVAL_BURSTINESS_CLUSTERING: Burstiness B={b_param:.3f} >= "
                            f"{self.burstiness_threshold:.2f} with mean duration {mu_tau * 1000.0:.1f}ms <= "
                            f"{self.compressed_mean_duration_s * 1000.0:.1f}ms"
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
        """Reset internal history and state."""
        with self._lock:
            self._durations.clear()
            self._recent_trades.clear()
            self._sub_ms_consecutive = 0
            self._last_timestamp = None
            self._blocked_until = 0.0
            self._last_block_reason = ""
            self._last_burstiness = 0.0
            self._last_mean_duration = 0.0
            self._total_trades = 0
            self._total_violations = 0

    def get_status(self, current_time: Optional[float] = None) -> Dict[str, Any]:
        """Return diagnostic metrics and state dictionary."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            remaining_cooldown = max(0.0, self._blocked_until - now)
            return {
                "guard_name": "Wave335TradeArrivalClusteringBurstinessGuard",
                "is_blocked": now < self._blocked_until,
                "remaining_cooldown_s": round(remaining_cooldown, 3),
                "last_block_reason": self._last_block_reason,
                "last_burstiness": round(self._last_burstiness, 4),
                "last_mean_duration_ms": round(self._last_mean_duration * 1000.0, 2),
                "durations_buffer_fill": len(self._durations),
                "total_trades": self._total_trades,
                "total_violations": self._total_violations,
            }
