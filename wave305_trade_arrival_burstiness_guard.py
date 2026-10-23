"""
wave305_trade_arrival_burstiness_guard.py
-----------------------------------------
Guard: High-Frequency Trade Arrival Microsecond Burstiness Parameter (B-Score) Guard

Monitors trade arrival time-series burstiness parameter B and coefficient of variation (CV),
detecting extreme microsecond predatory clustering cascades and algorithmic barrages
(Goh & Barabasi 2008; Malmgren et al. 2008; Karsai et al. 2012; Pacurar 2008):
    Inter-Arrival Duration:       tau_i = max(t_i - t_{i-1}, 1e-4) in seconds
    Sample Mean Duration:         mu_tau = (1 / N) * sum_{i=1}^N tau_i
    Sample Standard Deviation:    sigma_tau = sqrt((1 / (N - 1)) * sum_{i=1}^N (tau_i - mu_tau)^2)
    Coefficient of Variation:     CV = sigma_tau / max(mu_tau, 1e-4)
    Burstiness Parameter:         B = (sigma_tau - mu_tau) / (sigma_tau + mu_tau) = (CV - 1) / (CV + 1)
                                  where B in [-1, +1]

Under homogeneous Poisson or regular arrival processes:
    - Poisson (memoryless):       CV = 1.0, B = 0.0
    - Periodic / regular:         CV < 1.0, B < 0.0
    - Mild natural clustering:    B in [0.05, 0.45]

Under predatory algorithmic barrages, news arrival cascades, or queue racing:
    - Inter-arrivals concentrate into intense microsecond bursts followed by long dead intervals:
        1) Burstiness Parameter Surge:
           Rolling burstiness B >= MAX_BURSTINESS (default: 0.65, CV >= 4.71)
           with rapid mean arrival mu_tau <= MAX_MEAN_DURATION_SEC (default: 0.25s)
           over rolling N >= MIN_SAMPLES (default: 15 trades).
        2) Acute Hyper-Burst Shock:
           Instantaneous B >= ACUTE_BURSTINESS (default: 0.85, CV >= 12.33)
           OR an unbroken streak of >= ACUTE_MICRO_STREAK (default: 6) trades with tau <= 10 ms.

Trading during intense arrival burstiness exposes orders to sub-millisecond front-running,
predatory spoof racing, and immediate adverse price movement.

When burstiness parameter surge or an acute hyper-burst shock is detected, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade arrivals via record_trade_arrival(ts=None) or record_duration(duration_sec, ts=None)
  or direct metrics via record_burstiness_metrics(b_score, mean_duration=None, sample_count=None, ts=None).
- Rolling window of WINDOW_SIZE = 25 durations.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative durations are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_arrival(ts=None)                                                                -> None
  record_duration(duration_sec, ts=None)                                                       -> None
  record_burstiness_metrics(b_score, mean_duration=None, sample_count=None, ts=None)           -> None
  update(duration_sec, ts=None)                                                                -> None   (alias)
  get_burstiness_metrics()                                                                     -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave305TradeArrivalBurstinessGuard:
    """
    Guards against trade arrival microsecond burstiness surges, high-CV clustering, and queue racing.
    """

    MAX_BURSTINESS: float = 0.65
    MIN_SAMPLES: int = 15
    MAX_MEAN_DURATION_SEC: float = 0.25
    ACUTE_BURSTINESS: float = 0.85
    ACUTE_MICRO_STREAK: int = 6
    ACUTE_MICRO_DURATION_SEC: float = 0.010
    WINDOW_SIZE: int = 25
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_burstiness: float = MAX_BURSTINESS,
        min_samples: int = MIN_SAMPLES,
        max_mean_duration_sec: float = MAX_MEAN_DURATION_SEC,
        acute_burstiness: float = ACUTE_BURSTINESS,
        acute_micro_streak: int = ACUTE_MICRO_STREAK,
        acute_micro_duration_sec: float = ACUTE_MICRO_DURATION_SEC,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_burstiness = float(max_burstiness)
        self.min_samples = int(min_samples)
        self.max_mean_duration_sec = float(max_mean_duration_sec)
        self.acute_burstiness = float(acute_burstiness)
        self.acute_micro_streak = int(acute_micro_streak)
        self.acute_micro_duration_sec = float(acute_micro_duration_sec)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._durations = collections.deque(maxlen=self.window_size)

        self._last_ts: Optional[float] = None
        self._micro_streak: int = 0

        self._latest_b: float = 0.0
        self._latest_cv: float = 1.0
        self._latest_mean_duration: float = 1.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _calculate_burstiness(self) -> tuple[float, float, float]:
        if len(self._durations) < 3:
            return 0.0, 1.0, 1.0

        durs = list(self._durations)
        mu = statistics.fmean(durs)
        sd = statistics.stdev(durs)

        cv = sd / max(mu, 1e-4)
        b_score = (cv - 1.0) / (cv + 1.0)
        # Clamp B to [-1.0, 1.0]
        b_score = max(-1.0, min(1.0, b_score))
        return b_score, cv, mu

    def _check_and_trigger_block(
        self,
        b_score: float,
        cv: float,
        mu: float,
        micro_streak: int,
        count: int,
    ) -> bool:
        # 1. Acute microsecond barrage streak
        if micro_streak >= self.acute_micro_streak:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_MICRO_BARRAGE_STREAK: streak={micro_streak} >= {self.acute_micro_streak} "
                f"trades with tau <= {self.acute_micro_duration_sec * 1000:.1f}ms"
            )
            return True

        # 2. Acute hyper-burst shock
        if b_score >= self.acute_burstiness and count >= 5:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_HYPER_BURST_SHOCK: B={b_score:.3f} >= {self.acute_burstiness:.3f} "
                f"(CV={cv:.2f}, N={count})"
            )
            return True

        # 3. Burstiness parameter surge
        if count >= self.min_samples and b_score >= self.max_burstiness and mu <= self.max_mean_duration_sec:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"BURSTINESS_PARAMETER_SURGE: B={b_score:.3f} >= {self.max_burstiness:.3f} "
                f"with mean_tau={mu:.3f} <= {self.max_mean_duration_sec:.3f}s over N={count} trades"
            )
            return True

        return False

    def record_duration(self, duration_sec: float, ts: Optional[float] = None) -> None:
        """
        Record inter-arrival duration in seconds and evaluate arrival burstiness.
        """
        with self._lock:
            if not self._is_valid_num(duration_sec) or duration_sec <= 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_DURATION_INPUT"
                return

            tau = float(duration_sec)
            self._durations.append(tau)
            self._sample_count += 1

            if tau <= self.acute_micro_duration_sec:
                self._micro_streak += 1
            else:
                self._micro_streak = 0

            b_score, cv, mu = self._calculate_burstiness()
            self._latest_b = b_score
            self._latest_cv = cv
            self._latest_mean_duration = mu

            self._check_and_trigger_block(
                b_score,
                cv,
                mu,
                self._micro_streak,
                len(self._durations),
            )

    def record_trade_arrival(self, ts: Optional[float] = None) -> None:
        """
        Record trade arrival timestamp and compute elapsed duration.
        """
        with self._lock:
            now_ts = float(ts) if (self._is_valid_num(ts) and ts >= 0.0) else time.time()
            if self._last_ts is not None:
                duration = max(now_ts - self._last_ts, 1e-4)
                self.record_duration(duration, ts=now_ts)
            self._last_ts = now_ts

    def record_burstiness_metrics(
        self,
        b_score: float,
        mean_duration: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed burstiness metrics.
        """
        with self._lock:
            if not self._is_valid_num(b_score) or b_score < -1.0 or b_score > 1.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_BURSTINESS_METRIC"
                return

            b = float(b_score)
            mu = float(mean_duration) if (self._is_valid_num(mean_duration) and mean_duration >= 0.0) else 0.10
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            # Compute CV from B: CV = (1 + B) / (1 - B)
            cv = (1.0 + b) / max(1.0 - b, 1e-4)

            self._latest_b = b
            self._latest_cv = cv
            self._latest_mean_duration = mu
            self._sample_count = cnt

            self._check_and_trigger_block(
                b,
                cv,
                mu,
                self.acute_micro_streak if b >= 0.95 else 0,
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

    def get_burstiness_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "burstiness_parameter": float(self._latest_b),
                "coefficient_of_variation": float(self._latest_cv),
                "mean_duration_sec": float(self._latest_mean_duration),
                "micro_streak": int(self._micro_streak),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_burstiness_metrics()

    def reset(self) -> None:
        with self._lock:
            self._durations.clear()
            self._last_ts = None
            self._micro_streak = 0
            self._latest_b = 0.0
            self._latest_cv = 1.0
            self._latest_mean_duration = 1.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
