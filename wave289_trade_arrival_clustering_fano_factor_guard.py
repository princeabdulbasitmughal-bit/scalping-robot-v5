"""
wave289_trade_arrival_clustering_fano_factor_guard.py
-----------------------------------------------------
Guard: High-Frequency Trade Arrival Counting Fano Factor & Super-Poisson Overclustering Guard

Monitors trade arrival counting statistics, point process dispersion, and super-Poisson overclustering
(Fano 1947; Teich & Lowen 1994; Daley & Vere-Jones 2003; Engle & Lunde 2003):
    Counting Bin:              Delta T = 1.0 second
    Trade Count in Bin k:      N_k
    Mean Bin Count:            mu_N = (1 / K) * sum_{k=1}^K N_k  (trades / bin)
    Count Variance:            sigma^2_N = (1 / (K - 1)) * sum_{k=1}^K (N_k - mu_N)^2
    Fano Factor:               F = sigma^2_N / max(mu_N, 0.10)

Under stationary, memoryless Poisson trade arrival processes:
    - Mean equals variance, giving a baseline Fano factor F ~ 1.00.
    - Arrival fluctuations are stochastic and independent without heavy clustering.

During high-frequency algorithmic avalanches, predatory front-running cascades, or liquidity panic:
    - Trades burst into dense clusters followed by quiet pauses, causing massive overdispersion:
        1) Fano Factor Overclustering Surge:
           Fano factor F >= MAX_FANO_FACTOR (default: 3.80)
           with mean arrival intensity mu_N >= MIN_MEAN_COUNT (default: 3.0 trades/bin)
           over rolling K >= MIN_BINS (default: 8 counting bins).
        2) Acute Arrival Avalanche:
           Instantaneous single-bin trade count N_k >= ACUTE_BIN_COUNT (default: 22 trades in 1.0s).

Entering trades during super-Poisson arrival cascades guarantees extreme queue competition,
severe latency disadvantage, and execution against informed order flow.

When overclustering surge or an acute arrival avalanche is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade arrivals via record_trade_arrival(ts=None) or bin counts via record_bin_count(trade_count, ts=None) or
  direct metrics via record_fano_metrics(fano_factor, mean_count=None, acute_count=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 15 counting bins.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative counts are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_arrival(ts=None)                                                                -> None
  record_bin_count(trade_count, ts=None)                                                       -> None
  record_fano_metrics(fano_factor, mean_count=None, acute_count=None, sample_count=None)        -> None
  update(trade_count, ts=None)                                                                 -> None   (alias)
  get_fano_metrics()                                                                           -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave289TradeArrivalClusteringFanoFactorGuard:
    """
    Guards against high-frequency trade arrival super-Poisson clustering, Fano factor surges, and count avalanches.
    """

    MAX_FANO_FACTOR: float = 3.80
    MIN_MEAN_COUNT: float = 3.0
    MIN_BINS: int = 8
    ACUTE_BIN_COUNT: int = 22
    BIN_INTERVAL_SEC: float = 1.0
    WINDOW_SIZE: int = 15
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_fano_factor: float = MAX_FANO_FACTOR,
        min_mean_count: float = MIN_MEAN_COUNT,
        min_bins: int = MIN_BINS,
        acute_bin_count: int = ACUTE_BIN_COUNT,
        bin_interval_sec: float = BIN_INTERVAL_SEC,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_fano_factor = float(max_fano_factor)
        self.min_mean_count = float(min_mean_count)
        self.min_bins = int(min_bins)
        self.acute_bin_count = int(acute_bin_count)
        self.bin_interval_sec = float(bin_interval_sec)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._bin_history = collections.deque(maxlen=self.window_size)

        self._current_bin_start: Optional[float] = None
        self._current_bin_count: int = 0

        self._latest_count: int = 0
        self._latest_fano: float = 1.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _check_and_trigger_block(
        self,
        fano: float,
        mean_cnt: float,
        acute_cnt: int,
        sample_count: int,
    ) -> bool:
        # 1. Acute arrival avalanche in a single bin
        if acute_cnt >= self.acute_bin_count:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_ARRIVAL_AVALANCHE: bin_count={acute_cnt} >= {self.acute_bin_count} trades"
            )
            return True

        # 2. Fano factor overclustering surge
        if (
            sample_count >= self.min_bins
            and fano >= self.max_fano_factor
            and mean_cnt >= self.min_mean_count
        ):
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"FANO_OVERCLUSTERING_SURGE: fano={fano:.2f} >= {self.max_fano_factor:.2f}, "
                f"mean_count={mean_cnt:.2f} >= {self.min_mean_count:.2f} (K={sample_count})"
            )
            return True

        return False

    def record_bin_count(self, trade_count: int, ts: Optional[float] = None) -> None:
        """
        Record the number of trades executed within a single completed bin interval.
        """
        with self._lock:
            if not self._is_valid_num(trade_count) or trade_count < 0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_BIN_COUNT"
                return

            cnt = int(trade_count)
            self._latest_count = cnt
            self._bin_history.append(cnt)
            self._sample_count += 1

            n = len(self._bin_history)
            if n >= 2:
                mean_cnt = statistics.mean(self._bin_history)
                var_cnt = statistics.variance(self._bin_history)
                fano = var_cnt / max(mean_cnt, 0.10)
            else:
                mean_cnt = float(cnt)
                fano = 1.0

            self._latest_fano = fano

            self._check_and_trigger_block(
                fano,
                mean_cnt,
                cnt,
                n,
            )

    def record_trade_arrival(self, ts: Optional[float] = None) -> None:
        """
        Record a live trade arrival timestamp and aggregate into time bins.
        """
        with self._lock:
            now_ts = float(ts) if (self._is_valid_num(ts) and ts >= 0.0) else time.time()
            if self._current_bin_start is None:
                self._current_bin_start = now_ts
                self._current_bin_count = 1
            elif now_ts - self._current_bin_start < self.bin_interval_sec:
                self._current_bin_count += 1
                # Check for acute avalanche during live accumulation
                if self._current_bin_count >= self.acute_bin_count:
                    self._check_and_trigger_block(
                        self._latest_fano,
                        float(self._current_bin_count),
                        self._current_bin_count,
                        len(self._bin_history),
                    )
            else:
                # Close previous bin
                self.record_bin_count(self._current_bin_count, ts=self._current_bin_start)
                self._current_bin_start = now_ts
                self._current_bin_count = 1

    def record_fano_metrics(
        self,
        fano_factor: float,
        mean_count: Optional[float] = None,
        acute_count: Optional[int] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed Fano factor metrics.
        """
        with self._lock:
            if not self._is_valid_num(fano_factor) or fano_factor < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_FANO_METRIC"
                return

            f = float(fano_factor)
            m_cnt = float(mean_count) if (self._is_valid_num(mean_count) and mean_count >= 0.0) else self.min_mean_count + 1.0
            a_cnt = int(acute_count) if (self._is_valid_num(acute_count) and acute_count >= 0) else 0
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_bins

            self._latest_fano = f
            self._latest_count = a_cnt
            self._sample_count = cnt

            self._check_and_trigger_block(
                f,
                m_cnt,
                a_cnt,
                cnt,
            )

    def update(self, trade_count: int, ts: Optional[float] = None) -> None:
        """Alias for record_bin_count."""
        self.record_bin_count(trade_count, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_fano_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if len(self._bin_history) >= 2:
                mean_cnt = statistics.mean(self._bin_history)
                fano = statistics.variance(self._bin_history) / max(mean_cnt, 0.10)
            else:
                mean_cnt = float(self._latest_count)
                fano = self._latest_fano

            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "fano_factor": float(fano),
                "mean_bin_count": float(mean_cnt),
                "latest_bin_count": int(self._latest_count),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_fano_metrics()

    def reset(self) -> None:
        with self._lock:
            self._bin_history.clear()
            self._current_bin_start = None
            self._current_bin_count = 0
            self._latest_count = 0
            self._latest_fano = 1.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
