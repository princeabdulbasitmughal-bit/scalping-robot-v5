"""
wave315_trade_arrival_hawkes_branching_ratio_guard.py
-----------------------------------------------------
Guard: High-Frequency Trade Arrival Hawkes Self-Excitation Branching Ratio Guard

Monitors empirical trade arrival Hawkes self-excitation branching ratio eta and critical cascade clustering,
guarding against reflexive algorithmic feedback loops, endogenous trade avalanches, and supercritical flash cascades
(Hawkes 1971; Bacry, Delattre, Hoffmann & Muzy 2013; Hardiman, Bercot & Bouchaud 2013; Bowsher 2007):
    Hawkes Intensity:             lambda(t) = mu_0 + sum_{t_i < t} alpha * exp(-beta * (t - t_i))
    Branching Ratio:              eta = alpha / beta
    Count Binning:                N_k = trade count in bin k of size Delta t = 0.050s (50 ms)
    Empirical Branching Ratio:    eta = Cov(N_k, N_{k-1}) / Var(N_k)

Under normal exogenous order arrival:
    - Order arrivals are predominantly Poisson or weakly clustered:
      eta <= 0.45  (subcritical, stable).

Under reflexive algorithmic cascades or high-frequency feedback loops:
    - Endogenous child trades trigger further child orders in runaway chains:
        1) Critical Branching Surge:
           Rolling branching ratio eta >= MAX_BRANCHING_RATIO (default: 0.88)
           with active trading \\bar{N} >= MIN_MEAN_BIN_TRADES (default: 1.5 trades/bin)
           over rolling K >= MIN_BINS (default: 20 bins).
        2) Super-Critical Explosive Cascade:
           Instantaneous branching ratio eta >= CRITICAL_CASCADE_ETA (default: 1.05)
           with rapid inter-arrival duration \\bar{tau} <= 0.025s.
        3) Acute Reflexive Burst Streak:
           An unbroken streak of >= ACUTE_BIN_STREAK (default: 6) consecutive bins with >= 5 trades/bin.

Trading during critical branching regimes guarantees entering directly into self-reinforcing cascading dumps
or algorithmic liquidity vacuum runs.

When critical branching surge, supercritical cascade, or an acute reflexive streak is detected, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade arrival via record_trade_arrival(ts=None) or record_bin_count(count, ts=None) or
  direct metrics via record_branching_metrics(branching_ratio, mean_bin_trades=None, sample_count=None, ts=None).
- Rolling window of WINDOW_BINS = 30 count bins.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, negative counts or timestamps are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_arrival(ts=None)                                                                -> None
  record_bin_count(count, ts=None)                                                             -> None
  record_branching_metrics(branching_ratio, mean_bin_trades=None, sample_count=None, ts=None)   -> None
  update(count, ts=None)                                                                       -> None   (alias)
  get_branching_metrics()                                                                      -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave315TradeArrivalHawkesBranchingRatioGuard:
    """
    Guards against Hawkes self-excitation criticality, endogenous algorithmic avalanches, and flash cascades.
    """

    MAX_BRANCHING_RATIO: float = 0.88
    CRITICAL_CASCADE_ETA: float = 1.05
    MIN_BINS: int = 20
    MIN_MEAN_BIN_TRADES: float = 1.5
    ACUTE_BIN_STREAK: int = 6
    ACUTE_MIN_TRADES_PER_BIN: int = 5
    BIN_SIZE_SEC: float = 0.050
    WINDOW_BINS: int = 30
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_branching_ratio: float = MAX_BRANCHING_RATIO,
        critical_cascade_eta: float = CRITICAL_CASCADE_ETA,
        min_bins: int = MIN_BINS,
        min_mean_bin_trades: float = MIN_MEAN_BIN_TRADES,
        acute_bin_streak: int = ACUTE_BIN_STREAK,
        acute_min_trades_per_bin: int = ACUTE_MIN_TRADES_PER_BIN,
        bin_size_sec: float = BIN_SIZE_SEC,
        window_bins: int = WINDOW_BINS,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_branching_ratio = float(max_branching_ratio)
        self.critical_cascade_eta = float(critical_cascade_eta)
        self.min_bins = int(min_bins)
        self.min_mean_bin_trades = float(min_mean_bin_trades)
        self.acute_bin_streak = int(acute_bin_streak)
        self.acute_min_trades_per_bin = int(acute_min_trades_per_bin)
        self.bin_size_sec = float(bin_size_sec)
        self.window_bins = int(window_bins)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._bin_counts = collections.deque(maxlen=self.window_bins)

        self._current_bin_t0: Optional[float] = None
        self._current_bin_trades: int = 0
        self._dense_bin_streak: int = 0

        self._latest_eta: float = 0.20
        self._latest_mean_bin_trades: float = 1.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _estimate_branching_ratio(self) -> tuple[float, float]:
        n = len(self._bin_counts)
        if n < 4:
            return 0.20, 1.0

        counts = list(self._bin_counts)
        mean_c = statistics.fmean(counts)

        x = counts[:-1]
        y = counts[1:]
        m_x = statistics.fmean(x)
        m_y = statistics.fmean(y)

        var_x = sum((val - m_x) ** 2 for val in x)
        if var_x <= 1e-6:
            return 0.0, mean_c

        cov_xy = sum((x[i] - m_x) * (y[i] - m_y) for i in range(len(x)))
        eta = cov_xy / var_x
        eta = max(0.0, min(1.50, eta))
        return eta, mean_c

    def _check_and_trigger_block(
        self,
        eta: float,
        mean_bin: float,
        dense_streak: int,
        count: int,
    ) -> bool:
        # 1. Acute dense reflexive burst streak
        if dense_streak >= self.acute_bin_streak:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_REFLEXIVE_BURST_STREAK: streak={dense_streak} >= {self.acute_bin_streak} "
                f"bins with >= {self.acute_min_trades_per_bin} trades/bin"
            )
            return True

        # 2. Super-critical explosive cascade
        if count >= 10 and eta >= self.critical_cascade_eta and mean_bin >= self.min_mean_bin_trades:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"SUPER_CRITICAL_CASCADE: eta={eta:.3f} >= {self.critical_cascade_eta:.3f} "
                f"with mean_bin={mean_bin:.2f} trades/bin"
            )
            return True

        # 3. Critical branching surge
        if count >= self.min_bins and eta >= self.max_branching_ratio and mean_bin >= self.min_mean_bin_trades:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"CRITICAL_BRANCHING_SURGE: eta={eta:.3f} >= {self.max_branching_ratio:.3f} "
                f"over K={count} bins (mean_bin={mean_bin:.2f} trades/bin)"
            )
            return True

        return False

    def record_bin_count(self, count: int, ts: Optional[float] = None) -> None:
        """
        Record discrete trade arrival count in a completed time bin.
        """
        with self._lock:
            if not self._is_valid_num(count) or count < 0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_BIN_COUNT_INPUT"
                return

            cnt = int(count)
            self._bin_counts.append(cnt)
            self._sample_count += 1

            if cnt >= self.acute_min_trades_per_bin:
                self._dense_bin_streak += 1
            else:
                self._dense_bin_streak = 0

            eta, mean_bin = self._estimate_branching_ratio()
            self._latest_eta = eta
            self._latest_mean_bin_trades = mean_bin

            self._check_and_trigger_block(
                eta,
                mean_bin,
                self._dense_bin_streak,
                len(self._bin_counts),
            )

    def record_trade_arrival(self, ts: Optional[float] = None) -> None:
        """
        Record instantaneous trade arrival timestamp into sliding time bins.
        """
        with self._lock:
            now_ts = float(ts) if (self._is_valid_num(ts) and ts >= 0.0) else time.time()

            if self._current_bin_t0 is None:
                self._current_bin_t0 = now_ts
                self._current_bin_trades = 1
                return

            elapsed = now_ts - self._current_bin_t0
            if elapsed >= self.bin_size_sec:
                # Close out current bin
                self.record_bin_count(self._current_bin_trades, ts=now_ts)
                self._current_bin_t0 = now_ts
                self._current_bin_trades = 1
            else:
                self._current_bin_trades += 1

    def record_branching_metrics(
        self,
        branching_ratio: float,
        mean_bin_trades: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed Hawkes branching ratio metrics.
        """
        with self._lock:
            if not self._is_valid_num(branching_ratio) or branching_ratio < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_BRANCHING_METRIC"
                return

            eta = float(branching_ratio)
            mean_b = float(mean_bin_trades) if (self._is_valid_num(mean_bin_trades) and mean_bin_trades >= 0.0) else (self.min_mean_bin_trades + 1.0)
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_bins

            self._latest_eta = eta
            self._latest_mean_bin_trades = mean_b
            self._sample_count = cnt

            self._check_and_trigger_block(
                eta,
                mean_b,
                self.acute_bin_streak if eta >= 1.20 else 0,
                cnt,
            )

    def update(self, count: int, ts: Optional[float] = None) -> None:
        """Alias for record_bin_count."""
        self.record_bin_count(count, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_branching_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "branching_ratio_eta": float(self._latest_eta),
                "mean_bin_trades": float(self._latest_mean_bin_trades),
                "dense_bin_streak": int(self._dense_bin_streak),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_branching_metrics()

    def reset(self) -> None:
        with self._lock:
            self._bin_counts.clear()
            self._current_bin_t0 = None
            self._current_bin_trades = 0
            self._dense_bin_streak = 0
            self._latest_eta = 0.20
            self._latest_mean_bin_trades = 1.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
