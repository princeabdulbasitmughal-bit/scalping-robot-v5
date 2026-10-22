"""
wave281_trade_size_clustering_dispersion_guard.py
-------------------------------------------------
Guard: Trade Size Gini Dispersion & Algorithmic Slicing Concentration Guard

Monitors high-frequency trade size distribution, Gini inequality coefficient, and child-order slicing concentration
(Gini 1912; Chordia, Roll & Subrahmanyam 2001; Gabaix et al. 2006; Easley, Lopez de Prado & O'Hara 2012):
    Trade Size Stream:         V = [v_1, v_2, ..., v_N] in lots
    Gini Dispersion Index:     G = sum_{i=1}^N sum_{j=1}^N |v_i - v_j| / (2 * N * sum_{i=1}^N v_i) in [0.0, 1.0]
    Max Trade Size:            V_{max} = max_{i} (v_i)
    Identical Size Streak:     L_{streak} = count of consecutive trades with identical lot size (|v_t - v_{t-1}| < 1e-5)

Under natural, competitive retail and institutional trading:
    - Order sizes vary organically across heterogeneous participants: Gini coefficient G in [0.25, 0.65].
    - Lot sizes rarely repeat identically for long streaks (L_{streak} <= 3 to 4).

During predatory algorithmic slicing, iceberg order execution, or toxic whale sweeps:
    - Order flow collapses into degenerate repetitive slices or extreme whale-dominated skew:
        1) Algorithmic Slicing Concentration:
           Gini coefficient G <= MIN_GINI_COEFFICIENT (default: 0.12)
           over rolling N >= MIN_TRADES (default: 15 trades), indicating deterministic iceberg slicing.
        2) Extreme Whale Skew:
           Gini coefficient G >= MAX_GINI_COEFFICIENT (default: 0.88)
           with V_{max} >= MIN_WHALE_SIZE (default: 12.0 lots) over N >= MIN_TRADES (15 trades).
        3) Acute Repeated Lot Streak:
           Identical trade size streak L_{streak} >= ACUTE_STREAK_LEN (default: 8 consecutive trades).

Entering trades during algorithmic slicing or whale execution risks severe queue bypass, front-running,
and catastrophic adverse fills.

When slicing concentration, whale skew, or an acute repeated streak is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade sizes via record_trade_size(size_lots, ts=None) or
  direct metrics via record_dispersion_metrics(gini_coeff, max_size=None, streak_len=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 25 trade sizes.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive sizes are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_size(size_lots, ts=None)                                                        -> None
  record_dispersion_metrics(gini_coeff, max_size=None, streak_len=None, sample_count=None)     -> None
  update(size_lots, ts=None)                                                                   -> None   (alias)
  get_dispersion_metrics()                                                                     -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave281TradeSizeClusteringDispersionGuard:
    """
    Guards against algorithmic iceberg slicing, degenerate lot size repetition, and whale-skewed flow.
    """

    MIN_GINI_COEFFICIENT: float = 0.12
    MAX_GINI_COEFFICIENT: float = 0.88
    MIN_WHALE_SIZE: float = 12.0
    MIN_TRADES: int = 15
    ACUTE_STREAK_LEN: int = 8
    WINDOW_SIZE: int = 25
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        min_gini_coefficient: float = MIN_GINI_COEFFICIENT,
        max_gini_coefficient: float = MAX_GINI_COEFFICIENT,
        min_whale_size: float = MIN_WHALE_SIZE,
        min_trades: int = MIN_TRADES,
        acute_streak_len: int = ACUTE_STREAK_LEN,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.min_gini_coefficient = float(min_gini_coefficient)
        self.max_gini_coefficient = float(max_gini_coefficient)
        self.min_whale_size = float(min_whale_size)
        self.min_trades = int(min_trades)
        self.acute_streak_len = int(acute_streak_len)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._size_history = collections.deque(maxlen=self.window_size)

        self._latest_size: float = 0.0
        self._last_size: Optional[float] = None
        self._current_streak: int = 0
        self._latest_gini: float = 0.50
        self._latest_max_size: float = 0.0
        self._sample_count: int = 0

        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _calculate_gini(self, sizes: List[float]) -> float:
        n = len(sizes)
        if n < 2:
            return 0.0
        total_sum = sum(sizes)
        if total_sum <= 0.0:
            return 0.0

        diff_sum = 0.0
        for i in range(n):
            for j in range(n):
                diff_sum += abs(sizes[i] - sizes[j])

        gini = diff_sum / (2.0 * n * total_sum)
        return min(max(gini, 0.0), 1.0)

    def _check_and_trigger_block(
        self, gini: float, max_size: float, streak: int, n_samples: int
    ) -> bool:
        # 1. Acute identical size streak
        if streak >= self.acute_streak_len:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_IDENTICAL_STREAK: streak={streak} >= {self.acute_streak_len}"
            )
            return True

        # 2. Algorithmic slicing concentration (low Gini)
        if n_samples >= self.min_trades and gini <= self.min_gini_coefficient:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ALGORITHMIC_SLICING_CONCENTRATION: gini={gini:.4f} <= {self.min_gini_coefficient:.4f} (N={n_samples})"
            )
            return True

        # 3. Extreme whale inequality (high Gini + large max size)
        if (
            n_samples >= self.min_trades
            and gini >= self.max_gini_coefficient
            and max_size >= self.min_whale_size
        ):
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"WHALE_INEQUALITY_SKEW: gini={gini:.4f} >= {self.max_gini_coefficient:.4f}, "
                f"max_size={max_size:.2f} >= {self.min_whale_size:.2f} lots (N={n_samples})"
            )
            return True

        return False

    def record_trade_size(self, size_lots: float, ts: Optional[float] = None) -> None:
        """
        Record an incoming trade size and update Gini coefficient and repetition streak.
        """
        with self._lock:
            if not self._is_valid_num(size_lots) or size_lots <= 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_TRADE_SIZE"
                return

            size = float(size_lots)
            self._latest_size = size
            self._size_history.append(size)
            self._sample_count += 1

            if self._last_size is not None and abs(size - self._last_size) < 1e-5:
                self._current_streak += 1
            else:
                self._current_streak = 1
            self._last_size = size

            sizes_list = list(self._size_history)
            gini = self._calculate_gini(sizes_list)
            max_size = max(sizes_list) if sizes_list else size

            self._latest_gini = gini
            self._latest_max_size = max_size

            self._check_and_trigger_block(gini, max_size, self._current_streak, len(sizes_list))

    def record_dispersion_metrics(
        self,
        gini_coeff: float,
        max_size: Optional[float] = None,
        streak_len: Optional[int] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed Gini dispersion metrics.
        """
        with self._lock:
            if not self._is_valid_num(gini_coeff) or gini_coeff < 0.0 or gini_coeff > 1.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_GINI_METRIC"
                return

            gini = float(gini_coeff)
            mx = float(max_size) if (self._is_valid_num(max_size) and max_size >= 0.0) else 0.0
            stk = int(streak_len) if (self._is_valid_num(streak_len) and streak_len >= 0) else 1
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_trades

            self._latest_gini = gini
            self._latest_max_size = mx
            self._current_streak = stk
            self._sample_count = cnt

            self._check_and_trigger_block(gini, mx, stk, cnt)

    def update(self, size_lots: float, ts: Optional[float] = None) -> None:
        """Alias for record_trade_size."""
        self.record_trade_size(size_lots, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_dispersion_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if len(self._size_history) >= 2:
                sizes_list = list(self._size_history)
                gini = self._calculate_gini(sizes_list)
                max_sz = max(sizes_list)
                mean_sz = statistics.mean(sizes_list)
            else:
                gini = self._latest_gini
                max_sz = self._latest_max_size
                mean_sz = self._latest_size

            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "gini_coefficient": float(gini),
                "max_trade_size_lots": float(max_sz),
                "mean_trade_size_lots": float(mean_sz),
                "identical_streak_len": int(self._current_streak),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_dispersion_metrics()

    def reset(self) -> None:
        with self._lock:
            self._size_history.clear()
            self._latest_size = 0.0
            self._last_size = None
            self._current_streak = 0
            self._latest_gini = 0.50
            self._latest_max_size = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
