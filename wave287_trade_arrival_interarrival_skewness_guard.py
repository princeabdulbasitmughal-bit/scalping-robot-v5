"""
wave287_trade_arrival_interarrival_skewness_guard.py
----------------------------------------------------
Guard: Trade Arrival Inter-Event Duration Skewness & Clustering Asymmetry Guard

Monitors high-frequency trade arrival durations, distributional skewness, and microsecond cascade clustering
(Engle & Russell 1998; Zhang, Russell & Tsay 2001; Pacurar 2008; Bauwens & Hautsch 2009):
    Inter-Arrival Duration:       tau_i = max(t_i - t_{i-1}, 1e-4) in seconds
    Mean Duration:                \\bar{tau} = (1 / N) * sum_{i=1}^N tau_i
    Standard Deviation:           sigma_tau = sqrt( (1 / (N - 1)) * sum_{i=1}^N (tau_i - \\bar{tau})^2 )
    Duration Skewness:            gamma_1 = [N / ((N-1)(N-2))] * sum_{i=1}^N ((tau_i - \\bar{tau}) / sigma_tau)^3
    Micro-Cluster Cascade Streak: count of consecutive trades with tau_i <= ACUTE_CASCADE_INTERVAL_SEC (20 ms)

Under regular Poisson or renewal arrival regimes:
    - Trade durations follow exponential or mild Weibull distributions with moderate positive skewness:
      gamma_1 in [1.20, 2.80], with rare microsecond bursts.

During predatory high-frequency sweeping, deterministic slicing, or algorithmic avalanche cascades:
    - Trades bunch into ultra-tight microsecond bunches followed by long pauses, causing duration skewness to explode:
        1) Inter-Arrival Duration Skewness Explosion:
           Duration skewness gamma_1 >= MAX_SKEWNESS (default: 4.20)
           with mean duration \\bar{tau} <= MIN_MEAN_DURATION (default: 0.35s)
           over rolling N >= MIN_TRADES (default: 15 trade intervals).
        2) Acute Micro-Cluster Cascade Streak:
           Consecutive trades with duration tau_i <= ACUTE_CASCADE_INTERVAL_SEC (0.020s = 20ms)
           reaching streak length L_{streak} >= ACUTE_STREAK_LEN (default: 8 trades).

Executing during extreme arrival clustering risks severe front-running, high-frequency quote racing,
and adverse fills from latency-advantaged algorithms.

When duration skewness explosion or an acute cascade streak is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade arrival via record_trade_arrival(ts=None) or record_duration(duration_sec, ts=None) or
  direct metrics via record_skewness_metrics(skewness, mean_duration=None, streak_len=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 25 duration observations.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative durations are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_arrival(ts=None)                                                                -> None
  record_duration(duration_sec, ts=None)                                                       -> None
  record_skewness_metrics(skewness, mean_duration=None, streak_len=None, sample_count=None)     -> None
  update(duration_sec, ts=None)                                                                -> None   (alias)
  get_skewness_metrics()                                                                       -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave287TradeArrivalInterarrivalSkewnessGuard:
    """
    Guards against high-frequency trade arrival clustering, duration skewness explosions, and microsecond cascades.
    """

    MAX_SKEWNESS: float = 4.20
    MIN_MEAN_DURATION: float = 0.35
    MIN_TRADES: int = 15
    ACUTE_CASCADE_INTERVAL_SEC: float = 0.020
    ACUTE_STREAK_LEN: int = 8
    WINDOW_SIZE: int = 25
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_skewness: float = MAX_SKEWNESS,
        min_mean_duration: float = MIN_MEAN_DURATION,
        min_trades: int = MIN_TRADES,
        acute_cascade_interval_sec: float = ACUTE_CASCADE_INTERVAL_SEC,
        acute_streak_len: int = ACUTE_STREAK_LEN,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_skewness = float(max_skewness)
        self.min_mean_duration = float(min_mean_duration)
        self.min_trades = int(min_trades)
        self.acute_cascade_interval_sec = float(acute_cascade_interval_sec)
        self.acute_streak_len = int(acute_streak_len)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._duration_history = collections.deque(maxlen=self.window_size)

        self._last_ts: Optional[float] = None
        self._cascade_streak: int = 0

        self._latest_duration: float = 0.0
        self._latest_skewness: float = 1.50
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _calculate_skewness(self, durations: List[float]) -> float:
        n = len(durations)
        if n < 3:
            return 0.0
        mean = statistics.mean(durations)
        variance = statistics.variance(durations)
        if variance <= 1e-9:
            return 0.0
        std = math.sqrt(variance)

        m3 = sum((x - mean) ** 3 for x in durations) / n
        skew = (m3 / (std ** 3)) * ((n * (n - 1)) ** 0.5) / (n - 2)
        return float(skew)

    def _check_and_trigger_block(
        self,
        skewness: float,
        mean_dur: float,
        streak: int,
        sample_count: int,
    ) -> bool:
        # 1. Acute micro-cluster cascade streak
        if streak >= self.acute_streak_len:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_CASCADE_STREAK: streak={streak} >= {self.acute_streak_len} "
                f"(interval <= {self.acute_cascade_interval_sec * 1000:.1f}ms)"
            )
            return True

        # 2. Inter-arrival duration skewness explosion
        if (
            sample_count >= self.min_trades
            and skewness >= self.max_skewness
            and mean_dur <= self.min_mean_duration
        ):
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"DURATION_SKEWNESS_EXPLOSION: skew={skewness:.2f} >= {self.max_skewness:.2f}, "
                f"mean_dur={mean_dur:.3f}s <= {self.min_mean_duration:.3f}s (N={sample_count})"
            )
            return True

        return False

    def record_duration(self, duration_sec: float, ts: Optional[float] = None) -> None:
        """
        Record an observed inter-arrival duration in seconds.
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

            if dur <= self.acute_cascade_interval_sec:
                self._cascade_streak += 1
            else:
                self._cascade_streak = 0

            dur_list = list(self._duration_history)
            mean_dur = statistics.mean(dur_list) if dur_list else dur
            skewness = self._calculate_skewness(dur_list) if len(dur_list) >= 3 else 1.50
            self._latest_skewness = skewness

            self._check_and_trigger_block(
                skewness,
                mean_dur,
                self._cascade_streak,
                len(dur_list),
            )

    def record_trade_arrival(self, ts: Optional[float] = None) -> None:
        """
        Record a trade arrival event and compute elapsed duration since the previous trade.
        """
        with self._lock:
            now_ts = float(ts) if (self._is_valid_num(ts) and ts >= 0.0) else time.time()
            if self._last_ts is not None:
                duration = max(now_ts - self._last_ts, 1e-4)
                self.record_duration(duration, ts=now_ts)
            self._last_ts = now_ts

    def record_skewness_metrics(
        self,
        skewness: float,
        mean_duration: Optional[float] = None,
        streak_len: Optional[int] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed skewness metrics.
        """
        with self._lock:
            if not self._is_valid_num(skewness):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_SKEWNESS_METRIC"
                return

            skew = float(skewness)
            mean_d = float(mean_duration) if (self._is_valid_num(mean_duration) and mean_duration >= 0.0) else 0.20
            stk = int(streak_len) if (self._is_valid_num(streak_len) and streak_len >= 0) else 0
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_trades

            self._latest_skewness = skew
            self._cascade_streak = stk
            self._sample_count = cnt

            self._check_and_trigger_block(
                skew,
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

    def get_skewness_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if len(self._duration_history) >= 3:
                dur_list = list(self._duration_history)
                skewness = self._calculate_skewness(dur_list)
                mean_dur = statistics.mean(dur_list)
            else:
                skewness = self._latest_skewness
                mean_dur = self._latest_duration

            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "duration_skewness": float(skewness),
                "mean_duration_sec": float(mean_dur),
                "cascade_streak_len": int(self._cascade_streak),
                "latest_duration_sec": float(self._latest_duration),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_skewness_metrics()

    def reset(self) -> None:
        with self._lock:
            self._duration_history.clear()
            self._last_ts = None
            self._cascade_streak = 0
            self._latest_duration = 0.0
            self._latest_skewness = 1.50
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
