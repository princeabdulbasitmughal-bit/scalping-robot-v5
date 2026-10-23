"""
wave309_trade_volume_zipf_tail_guard.py
---------------------------------------
Guard: High-Frequency Trade Volume Zipf / Pareto Tail Exponent & Whale Infiltration Guard

Monitors empirical trade size distribution Pareto / Zipf power-law tail index zeta,
guarding against infinite-variance heavy-tail whale regimes and predatory whale order infiltration
(Gabaix et al. 2003, 2006; Gopikrishnan et al. 2000; Malevergne, Pisarenko & Sornette 2005):
    Rolling Trade Sizes:          V_1, V_2, ..., V_N in lots
    Sorted Order Statistics:      V_{(1)} >= V_{(2)} >= ... >= V_{(N)}
    Tail Exponent Estimator:      zeta = k / sum_{i=1}^k ln(V_{(i)} / V_{(k+1)})
                                  (evaluated on top k = max(3, int(0.40 * N)) trades)
    Rolling Median Trade Size:    \\tilde{V} = median(V)

Under normal retail and balanced institutional order flow:
    - Trade size distribution follows a thin or moderately heavy Pareto tail:
      zeta in [1.30, 2.20], in accordance with the cubic law of market activity.

Under predatory institutional whale infiltration or panic block liquidation:
    - Tail index collapses into an extreme heavy-tail regime (zeta <= 1.0, infinite mean):
        1) Heavy-Tail Whale Regime:
           Empirical Pareto tail index zeta <= MIN_PARETO_INDEX (default: 0.95)
           over rolling N >= MIN_SAMPLES (default: 15 trades).
        2) Acute Whale Infiltration Shock:
           Single trade print V_t >= ACUTE_WHALE_LOTS (default: 18.0 lots)
           with V_t >= ACUTE_WHALE_RATIO * max(\\tilde{V}, 0.10) (default: 15.0x median size).

Trading into an active infinite-variance heavy-tail whale regime exposes retail orders to catastrophic
adverse queue sweeps, book hollowing, and massive slippage.

When heavy-tail whale regime or an acute whale infiltration shock is detected, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade size via record_trade_size(trade_size, ts=None) or
  direct metrics via record_tail_metrics(tail_index_zeta, median_size=None, sample_count=None, ts=None).
- Rolling window of WINDOW_SIZE = 30 trades.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive trade sizes are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_size(trade_size, ts=None)                                                       -> None
  record_tail_metrics(tail_index_zeta, median_size=None, sample_count=None, ts=None)             -> None
  update(trade_size, ts=None)                                                                  -> None   (alias)
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


class Wave309TradeVolumeZipfTailGuard:
    """
    Guards against trade size Pareto/Zipf heavy-tail collapse, infinite-variance whale regimes, and acute prints.
    """

    MIN_PARETO_INDEX: float = 0.95
    MIN_SAMPLES: int = 15
    ACUTE_WHALE_LOTS: float = 18.0
    ACUTE_WHALE_RATIO: float = 15.0
    WINDOW_SIZE: int = 30
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        min_pareto_index: float = MIN_PARETO_INDEX,
        min_samples: int = MIN_SAMPLES,
        acute_whale_lots: float = ACUTE_WHALE_LOTS,
        acute_whale_ratio: float = ACUTE_WHALE_RATIO,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.min_pareto_index = float(min_pareto_index)
        self.min_samples = int(min_samples)
        self.acute_whale_lots = float(acute_whale_lots)
        self.acute_whale_ratio = float(acute_whale_ratio)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._sizes = collections.deque(maxlen=self.window_size)

        self._latest_zeta: float = 1.50
        self._latest_median: float = 1.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _estimate_zeta(self) -> tuple[float, float]:
        n = len(self._sizes)
        if n < 5:
            return 1.50, 1.0

        sorted_sizes = sorted(self._sizes, reverse=True)
        med = statistics.median(sorted_sizes)

        k = max(3, int(0.40 * n))
        cutoff = sorted_sizes[k]

        log_ratios = [math.log(max(sorted_sizes[i] / max(cutoff, 1e-4), 1.0 + 1e-6)) for i in range(k)]
        denom = sum(log_ratios)
        if denom <= 1e-6:
            return 3.0, med

        zeta = k / denom
        return zeta, med

    def _check_and_trigger_block(
        self,
        zeta: float,
        median_size: float,
        acute_size: float,
        count: int,
    ) -> bool:
        # 1. Acute whale infiltration shock
        if acute_size >= self.acute_whale_lots:
            ref_med = max(median_size, 0.10)
            if acute_size >= self.acute_whale_ratio * ref_med or acute_size >= self.acute_whale_lots * 1.5:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = (
                    f"ACUTE_WHALE_INFILTRATION: size={acute_size:.2f} >= {self.acute_whale_lots:.2f} lots "
                    f"({acute_size / ref_med:.1f}x median={ref_med:.2f} lots)"
                )
                return True

        # 2. Heavy-tail whale regime
        if count >= self.min_samples and zeta <= self.min_pareto_index:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"HEAVY_TAIL_WHALE_REGIME: zeta={zeta:.3f} <= {self.min_pareto_index:.3f} "
                f"over N={count} trades (median={median_size:.2f} lots)"
            )
            return True

        return False

    def record_trade_size(self, trade_size: float, ts: Optional[float] = None) -> None:
        """
        Record individual trade size in lots and evaluate Pareto tail exponent.
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

            zeta, med = self._estimate_zeta()
            self._latest_zeta = zeta
            self._latest_median = med

            self._check_and_trigger_block(
                zeta,
                med,
                size,
                len(self._sizes),
            )

    def record_tail_metrics(
        self,
        tail_index_zeta: float,
        median_size: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed Pareto tail index metrics.
        """
        with self._lock:
            if not self._is_valid_num(tail_index_zeta) or tail_index_zeta <= 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_TAIL_METRIC"
                return

            z = float(tail_index_zeta)
            med = float(median_size) if (self._is_valid_num(median_size) and median_size > 0.0) else 1.0
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_zeta = z
            self._latest_median = med
            self._sample_count = cnt

            self._check_and_trigger_block(
                z,
                med,
                self.acute_whale_lots + 2.0 if z <= 0.50 else 1.0,
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

    def get_tail_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "tail_index_zeta": float(self._latest_zeta),
                "median_size": float(self._latest_median),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_tail_metrics()

    def reset(self) -> None:
        with self._lock:
            self._sizes.clear()
            self._latest_zeta = 1.50
            self._latest_median = 1.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
