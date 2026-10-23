"""
wave321_trade_size_lognormal_truncation_guard.py
------------------------------------------------
Guard: High-Frequency Trade Size Log-Normal Truncation & Upper Lot Wall Guard

Monitors empirical trade size log-distribution skewness gamma_1 and artificial ceiling clamping,
guarding against deterministic parent order lot capping, iceberg truncation walls, and broker-enforced size clipping
(Malevergne, Pisarenko & Sornette 2005; Mitzenmacher 2004; Clauset, Shalizi & Newman 2009):
    Trade Sizes:                  V_1, V_2, ..., V_N in lots
    Log-Transformed Sizes:        y_i = ln(V_i)
    Log-Size Mean & Std:          mu_y = mean(y), sigma_y = std(y)
    Log-Size Skewness:            gamma_1 = (1 / N) * sum_{i=1}^N ((y_i - mu_y) / sigma_y)^3

Under natural multi-participant trading:
    - Trade sizes follow an unconstrained log-normal or moderately heavy-tailed distribution:
      gamma_1 in [-0.65, +0.65] (near zero skew in log-space).

Under artificial ceiling truncation or institutional lot capping:
    - Large parent orders are clamped at an artificial upper barrier:
        1) Upper Lot Truncation Skew:
           Severe negative log-skewness gamma_1 <= MIN_LOG_SKEWNESS (default: -1.40)
           with substantial mean trade size \\bar{V} >= MIN_MEAN_VOLUME (default: 2.00 lots)
           over rolling N >= MIN_SAMPLES (default: 15 trades).
        2) Acute Truncation Ceiling Streak:
           An unbroken streak of >= ACUTE_CEILING_STREAK (default: 8) consecutive trades
           hitting an identical ceiling size V >= ACUTE_MIN_CEILING_LOTS (default: 5.00 lots).

Trading against an active lot truncation wall guarantees stepping into an ongoing massive parent order disposal,
facing aggressive quote exhaustion and adverse fills.

When log-normal truncation skew or an acute truncation ceiling streak is detected, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade size via record_trade_size(trade_size, ts=None) or
  direct metrics via record_truncation_metrics(log_skewness, mean_volume=None, sample_count=None, ts=None).
- Rolling window of WINDOW_SIZE = 25 trades.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive trade sizes are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_size(trade_size, ts=None)                                                       -> None
  record_truncation_metrics(log_skewness, mean_volume=None, sample_count=None, ts=None)        -> None
  update(trade_size, ts=None)                                                                  -> None   (alias)
  get_truncation_metrics()                                                                     -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave321TradeSizeLognormalTruncationGuard:
    """
    Guards against trade size log-normal truncation skewness, artificial upper lot walls, and iceberg ceiling clamping.
    """

    MIN_LOG_SKEWNESS: float = -1.40
    MIN_MEAN_VOLUME: float = 2.00
    MIN_SAMPLES: int = 15
    ACUTE_CEILING_STREAK: int = 8
    ACUTE_MIN_CEILING_LOTS: float = 5.00
    WINDOW_SIZE: int = 25
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        min_log_skewness: float = MIN_LOG_SKEWNESS,
        min_mean_volume: float = MIN_MEAN_VOLUME,
        min_samples: int = MIN_SAMPLES,
        acute_ceiling_streak: int = ACUTE_CEILING_STREAK,
        acute_min_ceiling_lots: float = ACUTE_MIN_CEILING_LOTS,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.min_log_skewness = float(min_log_skewness)
        self.min_mean_volume = float(min_mean_volume)
        self.min_samples = int(min_samples)
        self.acute_ceiling_streak = int(acute_ceiling_streak)
        self.acute_min_ceiling_lots = float(acute_min_ceiling_lots)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._sizes = collections.deque(maxlen=self.window_size)

        self._last_size: Optional[float] = None
        self._ceiling_streak: int = 0

        self._latest_skewness: float = 0.0
        self._latest_mean_volume: float = 1.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _calculate_skewness(self) -> tuple[float, float]:
        n = len(self._sizes)
        if n < 4:
            return 0.0, 1.0

        sizes = list(self._sizes)
        mean_v = statistics.fmean(sizes)

        y = [math.log(max(v, 1e-4)) for v in sizes]
        mu_y = statistics.fmean(y)
        sd_y = statistics.stdev(y)

        if sd_y <= 1e-6:
            return 0.0, mean_v

        skew = sum(((val - mu_y) / sd_y) ** 3 for val in y) / n
        return skew, mean_v

    def _check_and_trigger_block(
        self,
        skewness: float,
        mean_vol: float,
        last_size: float,
        ceiling_streak: int,
        count: int,
    ) -> bool:
        # 1. Acute truncation ceiling streak
        if ceiling_streak >= self.acute_ceiling_streak and last_size >= self.acute_min_ceiling_lots:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_TRUNCATION_CEILING_STREAK: streak={ceiling_streak} >= {self.acute_ceiling_streak} "
                f"trades at ceiling={last_size:.2f} >= {self.acute_min_ceiling_lots:.2f} lots"
            )
            return True

        # 2. Upper lot truncation skew
        if count >= self.min_samples and skewness <= self.min_log_skewness and mean_vol >= self.min_mean_volume:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"LOGNORMAL_TRUNCATION_SKEW: gamma_1={skewness:.3f} <= {self.min_log_skewness:.3f} "
                f"with mean_vol={mean_vol:.2f} >= {self.min_mean_volume:.2f} lots over N={count}"
            )
            return True

        return False

    def record_trade_size(self, trade_size: float, ts: Optional[float] = None) -> None:
        """
        Record individual trade size in lots and evaluate log-distribution skewness.
        """
        with self._lock:
            if not self._is_valid_num(trade_size) or trade_size <= 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_TRADE_SIZE_INPUT"
                return

            size = float(trade_size)
            self._sizes.append(size)
            self._sample_count += 1

            if self._last_size is not None and abs(size - self._last_size) < 1e-4:
                self._ceiling_streak += 1
            else:
                self._ceiling_streak = 1
            self._last_size = size

            skew, mean_v = self._calculate_skewness()
            self._latest_skewness = skew
            self._latest_mean_volume = mean_v

            self._check_and_trigger_block(
                skew,
                mean_v,
                size,
                self._ceiling_streak,
                len(self._sizes),
            )

    def record_truncation_metrics(
        self,
        log_skewness: float,
        mean_volume: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed log-size skewness metrics.
        """
        with self._lock:
            if not self._is_valid_num(log_skewness):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_SKEWNESS_METRIC"
                return

            skw = float(log_skewness)
            m_v = float(mean_volume) if (self._is_valid_num(mean_volume) and mean_volume >= 0.0) else (self.min_mean_volume + 1.0)
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_skewness = skw
            self._latest_mean_volume = m_v
            self._sample_count = cnt

            self._check_and_trigger_block(
                skw,
                m_v,
                self.acute_min_ceiling_lots + 1.0 if skw <= -3.0 else 1.0,
                self.acute_ceiling_streak if skw <= -3.0 else 0,
                cnt,
            )

    def update(self, trade_size: float, ts: Optional[float] = None) -> None:
        """Alias for record_trade_size."""
        self.record_trade_size(trade_size, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_truncation_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "log_skewness": float(self._latest_skewness),
                "mean_volume": float(self._latest_mean_volume),
                "ceiling_streak": int(self._ceiling_streak),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_truncation_metrics()

    def reset(self) -> None:
        with self._lock:
            self._sizes.clear()
            self._last_size = None
            self._ceiling_streak = 0
            self._latest_skewness = 0.0
            self._latest_mean_volume = 1.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
