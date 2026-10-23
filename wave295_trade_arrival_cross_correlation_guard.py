"""
wave295_trade_arrival_cross_correlation_guard.py
------------------------------------------------
Guard: Buyer vs Seller Trade Arrival Cross-Correlation Asymmetry Guard

Monitors bivariate buyer vs seller trade arrival counts, cross-correlation decoupling, and one-sided flow concentration
(Bouchaud et al. 2009; Toke 2011; Bacry, Delattre, Hoffmann & Muzy 2013; Rambaldi et al. 2017):
    Time Bins:                   Delta T = 1.0 second
    Buyer Trades in Bin k:       B_k
    Seller Trades in Bin k:      S_k
    Cross-Correlation:           rho(B, S) = Cov(B, S) / (sigma_B * sigma_S) in [-1.0, +1.0]
    Dominant Fraction:           p_{max} = max(N_B, N_S) / max(N_B + N_S, 1) in [0.5, 1.0]

Under healthy, competitive two-way order flow:
    - Buyers and sellers mutually excite and interact across the book:
      rho(B, S) in [0.20, 0.70], with balanced participation p_{max} <= 0.70.

During predatory directional runs, informed sweeps, or liquidity provider panic:
    - Order flow decouples completely, where aggressive trading on one side suffocates the opposite:
        1) Buyer-Seller Flow Decoupling:
           Cross-correlation rho(B, S) <= MIN_CROSS_CORRELATION (default: -0.45)
           with combined trade count (sum B + sum S) >= MIN_TOTAL_TRADES (default: 20)
           over rolling K >= MIN_BINS (default: 8 counting bins).
        2) Acute One-Sided Trade Concentration:
           Dominant side concentration p_{max} >= ACUTE_CONCENTRATION (default: 0.92)
           over rolling N >= MIN_TRADES (default: 20 trades).

Trading counter to a decoupled, one-sided order flow avalanche guarantees severe adverse fills,
immediate inventory loss, and cascading trend losses.

When flow decoupling or acute one-sided concentration is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade execution via record_trade(direction, ts=None) or bin counts via record_bin_counts(buy_count, sell_count, ts=None) or
  direct metrics via record_correlation_metrics(cross_corr, dominant_fraction=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 12 counting bins and WINDOW_TRADES = 25 trades.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or invalid directions are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade(direction, ts=None)                                                             -> None
  record_bin_counts(buy_count, sell_count, ts=None)                                            -> None
  record_correlation_metrics(cross_corr, dominant_fraction=None, sample_count=None, ts=None)   -> None
  update(direction, ts=None)                                                                   -> None   (alias)
  get_correlation_metrics()                                                                    -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave295TradeArrivalCrossCorrelationGuard:
    """
    Guards against high-frequency buyer/seller cross-correlation decoupling and extreme one-sided flow.
    """

    MIN_CROSS_CORRELATION: float = -0.45
    MIN_TOTAL_TRADES: int = 20
    MIN_BINS: int = 8
    ACUTE_CONCENTRATION: float = 0.92
    MIN_TRADES: int = 20
    BIN_INTERVAL_SEC: float = 1.0
    WINDOW_BINS: int = 12
    WINDOW_TRADES: int = 25
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        min_cross_correlation: float = MIN_CROSS_CORRELATION,
        min_total_trades: int = MIN_TOTAL_TRADES,
        min_bins: int = MIN_BINS,
        acute_concentration: float = ACUTE_CONCENTRATION,
        min_trades: int = MIN_TRADES,
        bin_interval_sec: float = BIN_INTERVAL_SEC,
        window_bins: int = WINDOW_BINS,
        window_trades: int = WINDOW_TRADES,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.min_cross_correlation = float(min_cross_correlation)
        self.min_total_trades = int(min_total_trades)
        self.min_bins = int(min_bins)
        self.acute_concentration = float(acute_concentration)
        self.min_trades = int(min_trades)
        self.bin_interval_sec = float(bin_interval_sec)
        self.window_bins = int(window_bins)
        self.window_trades = int(window_trades)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._buy_bin_history = collections.deque(maxlen=self.window_bins)
        self._sell_bin_history = collections.deque(maxlen=self.window_bins)
        self._trade_directions = collections.deque(maxlen=self.window_trades)

        self._current_bin_start: Optional[float] = None
        self._current_buy_count: int = 0
        self._current_sell_count: int = 0

        self._latest_corr: float = 0.50
        self._latest_dominant_fraction: float = 0.50
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _calculate_cross_corr(self) -> float:
        n = len(self._buy_bin_history)
        if n < 3:
            return 0.50

        mean_b = statistics.mean(self._buy_bin_history)
        mean_s = statistics.mean(self._sell_bin_history)

        var_b = statistics.variance(self._buy_bin_history)
        var_s = statistics.variance(self._sell_bin_history)

        if var_b <= 1e-6 or var_s <= 1e-6:
            return 0.0

        cov = sum((b - mean_b) * (s - mean_s) for b, s in zip(self._buy_bin_history, self._sell_bin_history)) / (n - 1)
        r = cov / (math.sqrt(var_b) * math.sqrt(var_s))
        return min(max(float(r), -1.0), 1.0)

    def _check_and_trigger_block(
        self,
        corr: float,
        dom_frac: float,
        total_trades: int,
        n_bins: int,
        n_trades: int,
    ) -> bool:
        # 1. Acute one-sided trade concentration
        if n_trades >= self.min_trades and dom_frac >= self.acute_concentration:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_ONE_SIDED_FLOW: dominant_frac={dom_frac:.2f} >= {self.acute_concentration:.2f} (N={n_trades})"
            )
            return True

        # 2. Buyer-seller flow decoupling
        if (
            n_bins >= self.min_bins
            and total_trades >= self.min_total_trades
            and corr <= self.min_cross_correlation
        ):
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"BUYER_SELLER_DECOUPLING: cross_corr={corr:.2f} <= {self.min_cross_correlation:.2f}, "
                f"total_trades={total_trades} >= {self.min_total_trades} (K={n_bins})"
            )
            return True

        return False

    def record_bin_counts(self, buy_count: int, sell_count: int, ts: Optional[float] = None) -> None:
        """
        Record completed bin counts of buyer and seller trades.
        """
        with self._lock:
            if (
                not self._is_valid_num(buy_count)
                or not self._is_valid_num(sell_count)
                or buy_count < 0
                or sell_count < 0
            ):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_BIN_COUNTS"
                return

            b_cnt = int(buy_count)
            s_cnt = int(sell_count)

            self._buy_bin_history.append(b_cnt)
            self._sell_bin_history.append(s_cnt)
            self._sample_count += 1

            total_trades = sum(self._buy_bin_history) + sum(self._sell_bin_history)
            corr = self._calculate_cross_corr()
            self._latest_corr = corr

            self._check_and_trigger_block(
                corr,
                self._latest_dominant_fraction,
                total_trades,
                len(self._buy_bin_history),
                len(self._trade_directions),
            )

    def record_trade(self, direction: int, ts: Optional[float] = None) -> None:
        """
        Record individual trade execution direction (+1 buy, -1 sell) and bin accumulation.
        """
        with self._lock:
            if not self._is_valid_num(direction) or int(direction) not in (-1, 1):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_TRADE_DIRECTION"
                return

            d = int(direction)
            self._trade_directions.append(d)

            n_trades = len(self._trade_directions)
            n_buys = sum(1 for x in self._trade_directions if x == 1)
            n_sells = n_trades - n_buys
            dom_frac = max(n_buys, n_sells) / max(n_trades, 1)
            self._latest_dominant_fraction = dom_frac

            now_ts = float(ts) if (self._is_valid_num(ts) and ts >= 0.0) else time.time()
            if self._current_bin_start is None:
                self._current_bin_start = now_ts
                self._current_buy_count = 1 if d == 1 else 0
                self._current_sell_count = 1 if d == -1 else 0
            elif now_ts - self._current_bin_start < self.bin_interval_sec:
                if d == 1:
                    self._current_buy_count += 1
                else:
                    self._current_sell_count += 1
            else:
                self.record_bin_counts(self._current_buy_count, self._current_sell_count, ts=self._current_bin_start)
                self._current_bin_start = now_ts
                self._current_buy_count = 1 if d == 1 else 0
                self._current_sell_count = 1 if d == -1 else 0

            self._check_and_trigger_block(
                self._latest_corr,
                dom_frac,
                sum(self._buy_bin_history) + sum(self._sell_bin_history),
                len(self._buy_bin_history),
                n_trades,
            )

    def record_correlation_metrics(
        self,
        cross_corr: float,
        dominant_fraction: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed cross-correlation metrics.
        """
        with self._lock:
            if not self._is_valid_num(cross_corr) or cross_corr < -1.0 or cross_corr > 1.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_CORRELATION_METRIC"
                return

            r = float(cross_corr)
            df = float(dominant_fraction) if (self._is_valid_num(dominant_fraction) and 0.0 <= dominant_fraction <= 1.0) else 0.50
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_bins

            self._latest_corr = r
            self._latest_dominant_fraction = df
            self._sample_count = cnt

            self._check_and_trigger_block(
                r,
                df,
                self.min_total_trades + 10,
                cnt,
                self.min_trades if df >= self.acute_concentration else 1,
            )

    def update(self, direction: int, ts: Optional[float] = None) -> None:
        """Alias for record_trade."""
        self.record_trade(direction, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_correlation_metrics(self) -> Dict[str, Any]:
        with self._lock:
            corr = self._calculate_cross_corr() if len(self._buy_bin_history) >= 3 else self._latest_corr
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "cross_correlation": float(corr),
                "dominant_side_fraction": float(self._latest_dominant_fraction),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_correlation_metrics()

    def reset(self) -> None:
        with self._lock:
            self._buy_bin_history.clear()
            self._sell_bin_history.clear()
            self._trade_directions.clear()
            self._current_bin_start = None
            self._current_buy_count = 0
            self._current_sell_count = 0
            self._latest_corr = 0.50
            self._latest_dominant_fraction = 0.50
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
