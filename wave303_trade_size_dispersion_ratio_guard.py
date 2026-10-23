"""
wave303_trade_size_dispersion_ratio_guard.py
---------------------------------------------
Guard: High-Frequency Trade Size Robust Dispersion Ratio & Algorithmic Slicing / Whale Shock Guard

Monitors trade size distribution scale via Normalized Median Absolute Deviation (NMAD),
detecting algorithmic slicing degeneracy (TWAP/VWAP icebergs) and heavy-tailed whale outlier shocks
(Hampel 1974; Rousseeuw & Croux 1993; Biais, Hillion & Spatt 1995; Easley, Lopez de Prado & O'Hara 2012):
    Rolling Trade Sizes:          V_1, V_2, ..., V_N in lots
    Median Trade Size:            \\tilde{V} = median(V)
    Median Absolute Deviation:    MAD = median(|V_i - \\tilde{V}|)
    Normalized Scale Estimator:   NMAD = 1.4826 * MAD
    Rolling Mean Trade Size:      \\bar{V} = (1 / N) * sum_{i=1}^N V_i
    Robust Dispersion Ratio:      R_{disp} = NMAD / max(\\bar{V}, 1e-4)

Under natural, multi-participant liquid trading:
    - Order flow comprises heterogeneous retail, institutional, and speculative flow:
      R_{disp} in [0.25, 1.80].

Under predatory algorithmic slicing or institutional whale dumping:
    1) Algorithmic Slicing Degeneracy (TWAP/VWAP icebergs):
       Predatory algorithms slice large parent orders into near-identical child clips,
       causing MAD -> 0.0 and R_{disp} <= MIN_DISPERSION_RATIO (default: 0.10)
       over rolling N >= MIN_SAMPLES (default: 12 trades).
    2) Dispersion Explosion:
       Extreme volatility and heterogeneous panic sweeps cause
       R_{disp} >= MAX_DISPERSION_RATIO (default: 3.50) with \\bar{V} >= MIN_MEAN_VOLUME (default: 2.50 lots).
    3) Acute Outlier Whale / Slicing Streak:
       Instantaneous trade size V_t >= ACUTE_WHALE_LOTS (default: 15.0 lots) with V_t >= 12.0 * NMAD,
       OR an unbroken streak of >= ACUTE_IDENTICAL_STREAK (default: 8) identical trade sizes.

Trading against active predatory slicing or massive whale sweeps creates adverse selection,
queue exhaustion, and severe fill penalties.

When slicing degeneracy, dispersion explosion, or an acute whale shock is detected, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade size via record_trade_size(trade_size, ts=None) or
  direct metrics via record_dispersion_metrics(dispersion_ratio, sample_count=None, ts=None).
- Rolling window of WINDOW_SIZE = 25 trades.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive trade sizes are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_size(trade_size, ts=None)                                                       -> None
  record_dispersion_metrics(dispersion_ratio, sample_count=None, ts=None)                       -> None
  update(trade_size, ts=None)                                                                  -> None   (alias)
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


class Wave303TradeSizeDispersionRatioGuard:
    """
    Guards against trade size algorithmic slicing degeneracy, NMAD scale explosion, and acute whale prints.
    """

    MIN_DISPERSION_RATIO: float = 0.10
    MAX_DISPERSION_RATIO: float = 3.50
    MIN_SAMPLES: int = 12
    MIN_MEAN_VOLUME: float = 2.50
    ACUTE_WHALE_LOTS: float = 15.0
    ACUTE_IDENTICAL_STREAK: int = 8
    WINDOW_SIZE: int = 25
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        min_dispersion_ratio: float = MIN_DISPERSION_RATIO,
        max_dispersion_ratio: float = MAX_DISPERSION_RATIO,
        min_samples: int = MIN_SAMPLES,
        min_mean_volume: float = MIN_MEAN_VOLUME,
        acute_whale_lots: float = ACUTE_WHALE_LOTS,
        acute_identical_streak: int = ACUTE_IDENTICAL_STREAK,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.min_dispersion_ratio = float(min_dispersion_ratio)
        self.max_dispersion_ratio = float(max_dispersion_ratio)
        self.min_samples = int(min_samples)
        self.min_mean_volume = float(min_mean_volume)
        self.acute_whale_lots = float(acute_whale_lots)
        self.acute_identical_streak = int(acute_identical_streak)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._trade_sizes = collections.deque(maxlen=self.window_size)

        self._last_size: Optional[float] = None
        self._identical_streak: int = 0

        self._latest_dispersion_ratio: float = 0.50
        self._latest_nmad: float = 0.0
        self._latest_mean: float = 0.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _calculate_dispersion(self) -> tuple[float, float, float]:
        if not self._trade_sizes:
            return 0.0, 0.0, 0.50

        sizes = list(self._trade_sizes)
        mean_val = statistics.fmean(sizes)

        if len(sizes) < 3:
            return 0.0, mean_val, 0.50

        med = statistics.median(sizes)
        devs = [abs(x - med) for x in sizes]
        mad = statistics.median(devs)
        nmad = 1.4826 * mad

        denom = max(mean_val, 1e-4)
        disp_ratio = nmad / denom
        return nmad, mean_val, disp_ratio

    def _check_and_trigger_block(
        self,
        disp_ratio: float,
        mean_val: float,
        nmad: float,
        acute_trade: float,
        identical_streak: int,
        count: int,
    ) -> bool:
        # 1. Acute identical slicing streak
        if identical_streak >= self.acute_identical_streak:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_IDENTICAL_SLICING_STREAK: streak={identical_streak} >= {self.acute_identical_streak} "
                f"size={acute_trade:.2f} lots"
            )
            return True

        # 2. Acute outlier whale print
        if acute_trade >= self.acute_whale_lots:
            ref_scale = max(nmad, 0.10)
            if acute_trade >= 12.0 * ref_scale or acute_trade >= self.acute_whale_lots * 1.5:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = (
                    f"ACUTE_OUTLIER_WHALE: size={acute_trade:.2f} >= {self.acute_whale_lots:.2f} lots "
                    f"(scale={ref_scale:.2f})"
                )
                return True

        if count >= self.min_samples:
            # 3. Slicing degeneracy (near zero dispersion)
            if disp_ratio <= self.min_dispersion_ratio:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = (
                    f"SLICING_DEGENERACY: R_disp={disp_ratio:.4f} <= {self.min_dispersion_ratio:.4f} "
                    f"(mean={mean_val:.2f} lots, N={count})"
                )
                return True

            # 4. Dispersion explosion
            if disp_ratio >= self.max_dispersion_ratio and mean_val >= self.min_mean_volume:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = (
                    f"DISPERSION_EXPLOSION: R_disp={disp_ratio:.4f} >= {self.max_dispersion_ratio:.4f} "
                    f"(mean={mean_val:.2f} >= {self.min_mean_volume:.2f} lots)"
                )
                return True

        return False

    def record_trade_size(self, trade_size: float, ts: Optional[float] = None) -> None:
        """
        Record individual trade size in lots and evaluate robust dispersion ratio.
        """
        with self._lock:
            if not self._is_valid_num(trade_size) or trade_size <= 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_TRADE_SIZE_INPUT"
                return

            size = float(trade_size)
            self._trade_sizes.append(size)
            self._sample_count += 1

            if self._last_size is not None and abs(size - self._last_size) < 1e-6:
                self._identical_streak += 1
            else:
                self._identical_streak = 1
            self._last_size = size

            nmad, mean_val, disp_ratio = self._calculate_dispersion()
            self._latest_nmad = nmad
            self._latest_mean = mean_val
            self._latest_dispersion_ratio = disp_ratio

            self._check_and_trigger_block(
                disp_ratio,
                mean_val,
                nmad,
                size,
                self._identical_streak,
                len(self._trade_sizes),
            )

    def record_dispersion_metrics(
        self,
        dispersion_ratio: float,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed dispersion ratio.
        """
        with self._lock:
            if not self._is_valid_num(dispersion_ratio) or dispersion_ratio < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_DISPERSION_METRIC"
                return

            disp = float(dispersion_ratio)
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_dispersion_ratio = disp
            self._sample_count = cnt

            self._check_and_trigger_block(
                disp,
                self.min_mean_volume + 1.0,
                0.5,
                self.acute_whale_lots + 1.0 if disp >= 5.0 else 1.0,
                self.acute_identical_streak if disp <= 0.02 else 0,
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

    def get_dispersion_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "dispersion_ratio": float(self._latest_dispersion_ratio),
                "nmad": float(self._latest_nmad),
                "mean_size": float(self._latest_mean),
                "sample_count": int(self._sample_count),
                "identical_streak": int(self._identical_streak),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_dispersion_metrics()

    def reset(self) -> None:
        with self._lock:
            self._trade_sizes.clear()
            self._last_size = None
            self._identical_streak = 0
            self._latest_dispersion_ratio = 0.50
            self._latest_nmad = 0.0
            self._latest_mean = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
