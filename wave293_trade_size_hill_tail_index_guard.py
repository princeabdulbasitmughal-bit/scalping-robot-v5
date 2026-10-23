"""
wave293_trade_size_hill_tail_index_guard.py
-------------------------------------------
Guard: High-Frequency Trade Volume Pareto-Levy Heavy-Tail Index & Extreme Outlier Guard

Monitors trade size tail distribution, Hill power-law exponent, and catastrophic whale liquidity sweeps
(Hill 1975; Mandelbrot 1963; Gabaix et al. 2003, 2006; Clauset, Shalizi & Newman 2009):
    Trade Size Stream:            V = [v_1, v_2, ..., v_N] in lots
    Descending Order Statistics:  V_{(1)} >= V_{(2)} >= ... >= V_{(N)}
    Upper Tail Cutoff:            k = 8 upper order statistics
    Hill Tail Index:              alpha_{Hill} = [ (1 / k) * sum_{i=1}^k ln(V_{(i)} / V_{(k+1)}) ]^{-1}
    Max Trade Size:               V_{max} = V_{(1)}

Under stationary, Gaussian-like or moderate thin-tailed order flow:
    - Trade sizes exhibit finite moments with light or moderate tails:
      alpha_{Hill} >= 2.00 to 3.50.
    - Whale orders exceeding normal queue sizes are absent.

During predatory institutional sweeps, flash unhedging, or toxic liquidity clearing:
    - Order sizes enter a catastrophic infinite-variance Pareto regime (alpha <= 1.15):
        1) Heavy-Tail Power-Law Collapse:
           Hill tail index alpha_{Hill} <= MIN_HILL_INDEX (default: 1.15)
           with top trade V_{max} >= MIN_TOP_TRADE (default: 8.0 lots)
           over rolling N >= MIN_TRADES (default: 15 trades).
        2) Acute Extreme Whale Print:
           Instantaneous trade volume V >= ACUTE_WHALE_SIZE (default: 18.0 lots).

Trading during heavy-tail collapse exposes market makers to infinite-variance shocks,
immediate book clearing, and ruinous adverse execution.

When heavy-tail collapse or an acute whale print is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade size via record_trade_size(size_lots, ts=None) or
  direct metrics via record_tail_metrics(hill_index, max_size=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 25 trade sizes.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive sizes are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_size(size_lots, ts=None)                                                        -> None
  record_tail_metrics(hill_index, max_size=None, sample_count=None, ts=None)                   -> None
  update(size_lots, ts=None)                                                                   -> None   (alias)
  get_tail_metrics()                                                                           -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave293TradeSizeHillTailIndexGuard:
    """
    Guards against trade size Pareto heavy-tail collapse, infinite-variance shocks, and predatory whale prints.
    """

    MIN_HILL_INDEX: float = 1.15
    MIN_TOP_TRADE: float = 8.0
    MIN_TRADES: int = 15
    K_TAIL: int = 8
    ACUTE_WHALE_SIZE: float = 18.0
    WINDOW_SIZE: int = 25
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        min_hill_index: float = MIN_HILL_INDEX,
        min_top_trade: float = MIN_TOP_TRADE,
        min_trades: int = MIN_TRADES,
        k_tail: int = K_TAIL,
        acute_whale_size: float = ACUTE_WHALE_SIZE,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.min_hill_index = float(min_hill_index)
        self.min_top_trade = float(min_top_trade)
        self.min_trades = int(min_trades)
        self.k_tail = int(k_tail)
        self.acute_whale_size = float(acute_whale_size)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._size_history = collections.deque(maxlen=self.window_size)

        self._latest_size: float = 0.0
        self._latest_hill_index: float = 2.50
        self._latest_max_size: float = 0.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _calculate_hill_index(self, sizes: List[float]) -> float:
        n = len(sizes)
        k = self.k_tail
        if n < k + 1:
            return 3.00

        sorted_sizes = sorted(sizes, reverse=True)
        v_cutoff = max(sorted_sizes[k], 1e-4)

        log_sum = 0.0
        for i in range(k):
            ratio = max(sorted_sizes[i] / v_cutoff, 1.0)
            log_sum += math.log(ratio)

        if log_sum <= 1e-6:
            return 10.0  # Degenerate uniform sizes (very thin tails)

        hill = k / log_sum
        return float(hill)

    def _check_and_trigger_block(
        self,
        hill_index: float,
        max_size: float,
        acute_size: float,
        sample_count: int,
    ) -> bool:
        # 1. Acute extreme whale print
        if acute_size >= self.acute_whale_size:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_WHALE_PRINT: size={acute_size:.2f} >= {self.acute_whale_size:.2f} lots"
            )
            return True

        # 2. Heavy-tail power-law collapse
        if (
            sample_count >= self.min_trades
            and hill_index <= self.min_hill_index
            and max_size >= self.min_top_trade
        ):
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"HEAVY_TAIL_COLLAPSE: hill_alpha={hill_index:.2f} <= {self.min_hill_index:.2f}, "
                f"max_size={max_size:.2f} >= {self.min_top_trade:.2f} lots (N={sample_count})"
            )
            return True

        return False

    def record_trade_size(self, size_lots: float, ts: Optional[float] = None) -> None:
        """
        Record a trade execution size and update Hill tail exponent.
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

            sizes_list = list(self._size_history)
            hill = self._calculate_hill_index(sizes_list)
            max_size = max(sizes_list) if sizes_list else size

            self._latest_hill_index = hill
            self._latest_max_size = max_size

            self._check_and_trigger_block(
                hill,
                max_size,
                size,
                len(sizes_list),
            )

    def record_tail_metrics(
        self,
        hill_index: float,
        max_size: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed Hill tail index metrics.
        """
        with self._lock:
            if not self._is_valid_num(hill_index) or hill_index <= 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_HILL_METRIC"
                return

            hill = float(hill_index)
            mx = float(max_size) if (self._is_valid_num(max_size) and max_size >= 0.0) else self.min_top_trade + 2.0
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_trades

            self._latest_hill_index = hill
            self._latest_max_size = mx
            self._sample_count = cnt

            self._check_and_trigger_block(
                hill,
                mx,
                mx if mx >= self.acute_whale_size else 0.0,
                cnt,
            )

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

    def get_tail_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if len(self._size_history) >= self.k_tail + 1:
                hill = self._calculate_hill_index(list(self._size_history))
                max_sz = max(self._size_history)
            else:
                hill = self._latest_hill_index
                max_sz = self._latest_max_size

            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "hill_tail_index": float(hill),
                "max_trade_size_lots": float(max_sz),
                "latest_trade_size_lots": float(self._latest_size),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_tail_metrics()

    def reset(self) -> None:
        with self._lock:
            self._size_history.clear()
            self._latest_size = 0.0
            self._latest_hill_index = 2.50
            self._latest_max_size = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
