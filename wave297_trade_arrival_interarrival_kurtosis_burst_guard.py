"""
wave297_trade_arrival_interarrival_kurtosis_burst_guard.py
----------------------------------------------------------
Guard: High-Frequency Trade Arrival Duration Heavy-Tailed Excess Kurtosis & Flash Burst Guard

Monitors trade arrival duration distribution, sample excess kurtosis, and microsecond flash burst cascades
(Engle & Russell 1998; Zhang, Russell & Tsay 2001; Bauwens & Giot 2000; Pacurar 2008):
    Inter-Arrival Duration:       tau_i = max(t_i - t_{i-1}, 1e-4) in seconds
    Mean Duration:                \\bar{tau} = (1 / N) * sum_{i=1}^N tau_i
    Standard Deviation:           sigma_tau = sqrt( (1 / (N - 1)) * sum_{i=1}^N (tau_i - \\bar{tau})^2 )
    Sample Excess Kurtosis:       kappa = [N(N+1) / ((N-1)(N-2)(N-3))] * sum ((tau_i - \\bar{tau}) / sigma_tau)^4
                                          - [3(N-1)^2 / ((N-2)(N-3))]
    Microsecond Flash Streak:     count of consecutive trades with tau_i <= ACUTE_BURST_INTERVAL_SEC (10 ms)

Under standard exponential or mild renewal arrival processes:
    - Duration distributions have well-behaved, moderate kurtosis (kappa ~ 3.0 to 6.0).
    - Clusters dissipate predictably without extreme outlier delays.

During predatory flash sweeping, algorithmic burst cascades, or latency race avalanches:
    - Arrival durations exhibit extreme leptokurtic heavy-tailed kurtosis bursts (kappa >= 12.0):
        1) Arrival Duration Kurtosis Burst Explosion:
           Excess kurtosis kappa >= MAX_EXCESS_KURTOSIS (default: 12.0)
           with mean duration \\bar{tau} <= MIN_MEAN_DURATION (default: 0.30s)
           over rolling N >= MIN_TRADES (default: 15 trade intervals).
        2) Acute Microsecond Flash Burst Streak:
           Consecutive trades with duration tau_i <= ACUTE_BURST_INTERVAL_SEC (0.010s = 10ms)
           reaching streak length L_{streak} >= ACUTE_STREAK_LEN (default: 8 trades).

Executing during kurtosis burst regimes exposes scalping orders to extreme adverse queue selection,
predatory order book bypass, and sudden liquidity dry-ups.

When duration kurtosis explosion or an acute flash burst streak is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests arrival via record_trade_arrival(ts=None) or record_duration(duration_sec, ts=None) or
  direct metrics via record_kurtosis_metrics(excess_kurtosis, mean_duration=None, streak_len=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 25 duration observations.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative durations are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_arrival(ts=None)                                                                -> None
  record_duration(duration_sec, ts=None)                                                       -> None
  record_kurtosis_metrics(excess_kurtosis, mean_duration=None, streak_len=None, sample_count=None) -> None
  update(duration_sec, ts=None)                                                                -> None   (alias)
  get_kurtosis_metrics()                                                                       -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave297TradeArrivalInterarrivalKurtosisBurstGuard:
    """
    Guards against high-frequency arrival duration kurtosis bursts, leptokurtic clustering, and flash cascades.
    """

    MAX_EXCESS_KURTOSIS: float = 12.0
    MIN_MEAN_DURATION: float = 0.30
    MIN_TRADES: int = 15
    ACUTE_BURST_INTERVAL_SEC: float = 0.010
    ACUTE_STREAK_LEN: int = 8
    WINDOW_SIZE: int = 25
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_excess_kurtosis: float = MAX_EXCESS_KURTOSIS,
        min_mean_duration: float = MIN_MEAN_DURATION,
        min_trades: int = MIN_TRADES,
        acute_burst_interval_sec: float = ACUTE_BURST_INTERVAL_SEC,
        acute_streak_len: int = ACUTE_STREAK_LEN,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_excess_kurtosis = float(max_excess_kurtosis)
        self.min_mean_duration = float(min_mean_duration)
        self.min_trades = int(min_trades)
        self.acute_burst_interval_sec = float(acute_burst_interval_sec)
        self.acute_streak_len = int(acute_streak_len)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._duration_history = collections.deque(maxlen=self.window_size)

        self._last_ts: Optional[float] = None
        self._flash_streak: int = 0

        self._latest_duration: float = 0.0
        self._latest_kurtosis: float = 3.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _calculate_kurtosis(self, durations: List[float]) -> float:
        n = len(durations)
        if n < 4:
            return 3.0
        mean = statistics.mean(durations)
        variance = statistics.variance(durations)
        if variance <= 1e-9:
            return 0.0
        std = math.sqrt(variance)

        m4 = sum((x - mean) ** 4 for x in durations)
        term1 = (n * (n + 1)) / ((n - 1) * (n - 2) * (n - 3)) * (m4 / (std ** 4))
        term2 = (3 * ((n - 1) ** 2)) / ((n - 2) * (n - 3))
        return float(term1 - term2)

    def _check_and_trigger_block(
        self,
        kurtosis: float,
        mean_dur: float,
        streak: int,
        sample_count: int,
    ) -> bool:
        # 1. Acute microsecond flash burst streak
        if streak >= self.acute_streak_len:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_FLASH_BURST_STREAK: streak={streak} >= {self.acute_streak_len} "
                f"(interval <= {self.acute_burst_interval_sec * 1000:.1f}ms)"
            )
            return True

        # 2. Arrival duration excess kurtosis explosion
        if (
            sample_count >= self.min_trades
            and kurtosis >= self.max_excess_kurtosis
            and mean_dur <= self.min_mean_duration
        ):
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"DURATION_KURTOSIS_BURST_EXPLOSION: kurtosis={kurtosis:.2f} >= {self.max_excess_kurtosis:.2f}, "
                f"mean_dur={mean_dur:.3f}s <= {self.min_mean_duration:.3f}s (N={sample_count})"
            )
            return True

        return False

    def record_duration(self, duration_sec: float, ts: Optional[float] = None) -> None:
        """
        Record an observed trade inter-arrival duration.
        """
        with self._lock:
            if not self._is_valid_num(duration_sec) or duration_sec < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_DURATION_INPUT"
                return

            dur = max(float(duration_sec), 1e-4)
            self._latest_duration = dur
            self._duration_history.append(dur)
            self._sample_count += 1

            if dur <= self.acute_burst_interval_sec:
                self._flash_streak += 1
            else:
                self._flash_streak = 0

            dur_list = list(self._duration_history)
            mean_dur = statistics.mean(dur_list) if dur_list else dur
            kurtosis = self._calculate_kurtosis(dur_list) if len(dur_list) >= 4 else 3.0
            self._latest_kurtosis = kurtosis

            self._check_and_trigger_block(
                kurtosis,
                mean_dur,
                self._flash_streak,
                len(dur_list),
            )

    def record_trade_arrival(self, ts: Optional[float] = None) -> None:
        """
        Record a trade arrival event and compute elapsed duration since previous trade.
        """
        with self._lock:
            now_ts = float(ts) if (self._is_valid_num(ts) and ts >= 0.0) else time.time()
            if self._last_ts is not None:
                duration = max(now_ts - self._last_ts, 1e-4)
                self.record_duration(duration, ts=now_ts)
            self._last_ts = now_ts

    def record_kurtosis_metrics(
        self,
        excess_kurtosis: float,
        mean_duration: Optional[float] = None,
        streak_len: Optional[int] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed kurtosis metrics.
        """
        with self._lock:
            if not self._is_valid_num(excess_kurtosis):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_KURTOSIS_METRIC"
                return

            kurt = float(excess_kurtosis)
            mean_d = float(mean_duration) if (self._is_valid_num(mean_duration) and mean_duration >= 0.0) else 0.20
            stk = int(streak_len) if (self._is_valid_num(streak_len) and streak_len >= 0) else 0
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_trades

            self._latest_kurtosis = kurt
            self._flash_streak = stk
            self._sample_count = cnt

            self._check_and_trigger_block(
                kurt,
                mean_d,
                stk,
                cnt,
            )

    def update(self, duration_sec: float, ts: Optional[float] = None) -> None:
        """Alias for record_duration."""
        self.record_duration(duration_sec, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_kurtosis_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if len(self._duration_history) >= 4:
                dur_list = list(self._duration_history)
                kurt = self._calculate_kurtosis(dur_list)
                mean_dur = statistics.mean(dur_list)
            else:
                kurt = self._latest_kurtosis
                mean_dur = self._latest_duration

            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "excess_kurtosis": float(kurt),
                "mean_duration_sec": float(mean_dur),
                "flash_streak_len": int(self._flash_streak),
                "latest_duration_sec": float(self._latest_duration),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_kurtosis_metrics()

    def reset(self) -> None:
        with self._lock:
            self._duration_history.clear()
            self._last_ts = None
            self._flash_streak = 0
            self._latest_duration = 0.0
            self._latest_kurtosis = 3.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
