"""
wave283_trade_volume_variance_burst_guard.py
--------------------------------------------
Guard: High-Frequency Trade Volume Realized Variance Shock & Heteroskedasticity Guard

Monitors short-term realized trade volume variance, long-term baseline dispersion, and volume volatility bursts
(Engle 1982; Andersen & Bollerslev 1997; Barndorff-Nielsen & Shephard 2002; Corsi 2009):
    Trade Volume Stream:        V = [v_1, v_2, ..., v_N] in lots
    Short-Term Vol Variance:    sigma^2_{short} = Var(V_{t-K:t})  (K = 10 trades)
    Long-Term Vol Variance:     sigma^2_{long}  = Var(V_{t-M:t})  (M = 30 trades)
    Realized Variance Ratio:    R_{sigma^2}     = sigma^2_{short} / max(sigma^2_{long}, 0.05)
    Short-Term Standard Dev:    sigma_{short}   = sqrt(sigma^2_{short})

Under stationary, regular institutional and retail trading conditions:
    - Volume distribution exhibits stable, predictable local dispersion:
      R_{sigma^2} in [0.40, 2.00], sigma_{short} <= 2.50 lots.

During predatory institutional sweeps, erratic algorithmic burst barrages, or liquidity regime shifts:
    - Trade volume exhibits explosive heteroskedastic variance shocks:
        1) Realized Volume Variance Ratio Surge:
           R_{sigma^2} >= MAX_VARIANCE_RATIO (default: 4.50)
           with mean volume \\bar{v}_{short} >= MIN_MEAN_VOLUME (default: 2.50 lots)
           over rolling N >= MIN_TRADES (default: 15 trades).
        2) Acute Volume Variance Shock:
           Short-term standard deviation sigma_{short} >= ACUTE_VOL_STD (default: 6.50 lots)
           over N >= ACUTE_MIN_TRADES (default: 8 trades).

Trading during high volume variance bursts exposes market orders to extreme non-linear price impact,
depth evaporation, and execution slippage blowouts.

When volume variance surge or an acute volume shock is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade volume via record_trade_volume(volume_lots, ts=None) or
  direct metrics via record_variance_metrics(variance_ratio, short_std=None, sample_count=None, ts=None).
- Maintains short-term history (WINDOW_SHORT = 10) and long-term history (WINDOW_LONG = 30).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive volumes are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_volume(volume_lots, ts=None)                                                    -> None
  record_variance_metrics(variance_ratio, short_std=None, sample_count=None, ts=None)          -> None
  update(volume_lots, ts=None)                                                                 -> None   (alias)
  get_variance_metrics()                                                                       -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave283TradeVolumeVarianceBurstGuard:
    """
    Guards against violent trade volume variance shocks, heteroskedasticity bursts, and liquidity regime shifts.
    """

    MAX_VARIANCE_RATIO: float = 4.50
    MIN_MEAN_VOLUME: float = 2.50
    MIN_TRADES: int = 15
    ACUTE_VOL_STD: float = 6.50
    ACUTE_MIN_TRADES: int = 8
    WINDOW_SHORT: int = 10
    WINDOW_LONG: int = 30
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_variance_ratio: float = MAX_VARIANCE_RATIO,
        min_mean_volume: float = MIN_MEAN_VOLUME,
        min_trades: int = MIN_TRADES,
        acute_vol_std: float = ACUTE_VOL_STD,
        acute_min_trades: int = ACUTE_MIN_TRADES,
        window_short: int = WINDOW_SHORT,
        window_long: int = WINDOW_LONG,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_variance_ratio = float(max_variance_ratio)
        self.min_mean_volume = float(min_mean_volume)
        self.min_trades = int(min_trades)
        self.acute_vol_std = float(acute_vol_std)
        self.acute_min_trades = int(acute_min_trades)
        self.window_short = int(window_short)
        self.window_long = int(window_long)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._short_history = collections.deque(maxlen=self.window_short)
        self._long_history = collections.deque(maxlen=self.window_long)

        self._latest_volume: float = 0.0
        self._latest_variance_ratio: float = 1.0
        self._latest_short_std: float = 0.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _check_and_trigger_block(
        self,
        var_ratio: float,
        short_std: float,
        mean_vol: float,
        sample_count: int,
    ) -> bool:
        # 1. Acute volume variance shock
        if sample_count >= self.acute_min_trades and short_std >= self.acute_vol_std:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_VOLUME_VARIANCE_SHOCK: short_std={short_std:.2f} >= {self.acute_vol_std:.2f} lots (N={sample_count})"
            )
            return True

        # 2. Volume variance ratio surge
        if (
            sample_count >= self.min_trades
            and var_ratio >= self.max_variance_ratio
            and mean_vol >= self.min_mean_volume
        ):
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"VOLUME_VARIANCE_RATIO_SURGE: ratio={var_ratio:.2f} >= {self.max_variance_ratio:.2f}, "
                f"mean_vol={mean_vol:.2f} >= {self.min_mean_volume:.2f} lots (N={sample_count})"
            )
            return True

        return False

    def record_trade_volume(self, volume_lots: float, ts: Optional[float] = None) -> None:
        """
        Record individual trade execution volume and update rolling variance statistics.
        """
        with self._lock:
            if not self._is_valid_num(volume_lots) or volume_lots <= 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_VOLUME_INPUT"
                return

            vol = float(volume_lots)
            self._latest_volume = vol
            self._short_history.append(vol)
            self._long_history.append(vol)
            self._sample_count += 1

            short_n = len(self._short_history)
            long_n = len(self._long_history)

            if short_n >= 2:
                short_var = statistics.variance(self._short_history)
                short_std = math.sqrt(short_var)
                short_mean = statistics.mean(self._short_history)
            else:
                short_var = 0.0
                short_std = 0.0
                short_mean = vol

            if long_n >= 2:
                long_var = statistics.variance(self._long_history)
            else:
                long_var = short_var

            var_ratio = short_var / max(long_var, 0.05)

            self._latest_variance_ratio = var_ratio
            self._latest_short_std = short_std

            self._check_and_trigger_block(
                var_ratio,
                short_std,
                short_mean,
                self._sample_count,
            )

    def record_variance_metrics(
        self,
        variance_ratio: float,
        short_std: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed volume variance metrics.
        """
        with self._lock:
            if not self._is_valid_num(variance_ratio) or variance_ratio < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_VARIANCE_METRIC"
                return

            ratio = float(variance_ratio)
            s_std = float(short_std) if (self._is_valid_num(short_std) and short_std >= 0.0) else 0.0
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_trades

            self._latest_variance_ratio = ratio
            self._latest_short_std = s_std
            self._sample_count = cnt

            self._check_and_trigger_block(
                ratio,
                s_std,
                self.min_mean_volume + 1.0,
                cnt,
            )

    def update(self, volume_lots: float, ts: Optional[float] = None) -> None:
        """Alias for record_trade_volume."""
        self.record_trade_volume(volume_lots, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_variance_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if len(self._short_history) >= 2:
                short_var = statistics.variance(self._short_history)
                short_std = math.sqrt(short_var)
                short_mean = statistics.mean(self._short_history)
            else:
                short_std = self._latest_short_std
                short_mean = self._latest_volume

            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "variance_ratio": float(self._latest_variance_ratio),
                "short_term_std_lots": float(short_std),
                "short_term_mean_lots": float(short_mean),
                "latest_volume_lots": float(self._latest_volume),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_variance_metrics()

    def reset(self) -> None:
        with self._lock:
            self._short_history.clear()
            self._long_history.clear()
            self._latest_volume = 0.0
            self._latest_variance_ratio = 1.0
            self._latest_short_std = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
