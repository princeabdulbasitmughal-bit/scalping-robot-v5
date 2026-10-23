"""
wave286_lob_spread_variance_ratio_guard.py
------------------------------------------
Guard: LOB Inside Spread Realized Variance Ratio & Microstructure Instability Guard

Monitors bid-ask spread short-term realized variance, baseline volatility, and spread flickering shocks
(Roll 1984; Glosten 1987; Hasbrouck 1999; Wyart et al. 2008):
    Contemporaneous Spread:       S_t = (Ask_t - Bid_t) / Mid_t * 10,000 in bps
    Short-Term Spread Variance:   sigma^2_{S,short} = Var(S_{t-K:t})  (K = 8 ticks)
    Long-Term Spread Variance:    sigma^2_{S,long}  = Var(S_{t-M:t})  (M = 24 ticks)
    Spread Variance Ratio:        R_{sigma_S^2}     = sigma^2_{S,short} / max(sigma^2_{S,long}, 0.05)
    Short-Term Standard Dev:      sigma_{S,short}   = sqrt(sigma^2_{S,short}) in bps

Under stationary, continuous market liquidity conditions:
    - Bid-ask spread fluctuates mildly around a stable equilibrium value:
      R_{sigma_S^2} <= 2.20, sigma_{S,short} <= 0.80 bps.

During aggressive quote flickering, phantom depth cancellations, or liquidity provider stress:
    - Inside spread undergoes violent variance expansion:
        1) Spread Variance Ratio Surge:
           R_{sigma_S^2} >= MAX_VARIANCE_RATIO (default: 4.50)
           with mean spread \\bar{S}_{short} >= MIN_MEAN_SPREAD_BPS (default: 2.00 bps)
           over rolling N >= MIN_SAMPLES (default: 12 observations).
        2) Acute Spread Volatility Shock:
           Short-term spread standard deviation sigma_{S,short} >= ACUTE_SPREAD_STD_BPS (default: 2.20 bps)
           over N >= ACUTE_MIN_SAMPLES (default: 6 observations).

Executing trades into high spread variance regimes guarantees severe fill price uncertainty,
frequent fill rejects, and extreme slippage.

When spread variance surge or an acute spread volatility shock is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests spread via record_spread_bps(spread_bps, ts=None) or
  direct metrics via record_spread_variance(variance_ratio, short_std=None, sample_count=None, ts=None).
- Maintains short-term history (WINDOW_SHORT = 8) and long-term history (WINDOW_LONG = 24).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative spread values are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_spread_bps(spread_bps, ts=None)                                                       -> None
  record_spread_variance(variance_ratio, short_std=None, sample_count=None, ts=None)           -> None
  update(spread_bps, ts=None)                                                                  -> None   (alias)
  get_spread_variance_metrics()                                                                -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, Optional


class Wave286LobSpreadVarianceRatioGuard:
    """
    Guards against violent bid-ask spread variance shocks, quote flickering, and execution price instability.
    """

    MAX_VARIANCE_RATIO: float = 4.50
    MIN_MEAN_SPREAD_BPS: float = 2.00
    MIN_SAMPLES: int = 12
    ACUTE_SPREAD_STD_BPS: float = 2.20
    ACUTE_MIN_SAMPLES: int = 6
    WINDOW_SHORT: int = 8
    WINDOW_LONG: int = 24
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_variance_ratio: float = MAX_VARIANCE_RATIO,
        min_mean_spread_bps: float = MIN_MEAN_SPREAD_BPS,
        min_samples: int = MIN_SAMPLES,
        acute_spread_std_bps: float = ACUTE_SPREAD_STD_BPS,
        acute_min_samples: int = ACUTE_MIN_SAMPLES,
        window_short: int = WINDOW_SHORT,
        window_long: int = WINDOW_LONG,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_variance_ratio = float(max_variance_ratio)
        self.min_mean_spread_bps = float(min_mean_spread_bps)
        self.min_samples = int(min_samples)
        self.acute_spread_std_bps = float(acute_spread_std_bps)
        self.acute_min_samples = int(acute_min_samples)
        self.window_short = int(window_short)
        self.window_long = int(window_long)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._short_history = collections.deque(maxlen=self.window_short)
        self._long_history = collections.deque(maxlen=self.window_long)

        self._latest_spread: float = 0.0
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
        mean_spr: float,
        sample_count: int,
    ) -> bool:
        # 1. Acute spread volatility shock
        if sample_count >= self.acute_min_samples and short_std >= self.acute_spread_std_bps:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_SPREAD_VOLATILITY_SHOCK: short_std={short_std:.2f}bps >= {self.acute_spread_std_bps:.2f}bps (N={sample_count})"
            )
            return True

        # 2. Spread variance ratio surge
        if (
            sample_count >= self.min_samples
            and var_ratio >= self.max_variance_ratio
            and mean_spr >= self.min_mean_spread_bps
        ):
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"SPREAD_VARIANCE_RATIO_SURGE: ratio={var_ratio:.2f} >= {self.max_variance_ratio:.2f}, "
                f"mean_spread={mean_spr:.2f}bps >= {self.min_mean_spread_bps:.2f}bps (N={sample_count})"
            )
            return True

        return False

    def record_spread_bps(self, spread_bps: float, ts: Optional[float] = None) -> None:
        """
        Record instantaneous bid-ask spread in basis points.
        """
        with self._lock:
            if not self._is_valid_num(spread_bps) or spread_bps < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_SPREAD_INPUT"
                return

            spr = float(spread_bps)
            self._latest_spread = spr
            self._short_history.append(spr)
            self._long_history.append(spr)
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
                short_mean = spr

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

    def record_spread_variance(
        self,
        variance_ratio: float,
        short_std: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed spread variance metrics.
        """
        with self._lock:
            if not self._is_valid_num(variance_ratio) or variance_ratio < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_SPREAD_VARIANCE_METRIC"
                return

            ratio = float(variance_ratio)
            s_std = float(short_std) if (self._is_valid_num(short_std) and short_std >= 0.0) else 0.0
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_variance_ratio = ratio
            self._latest_short_std = s_std
            self._sample_count = cnt

            self._check_and_trigger_block(
                ratio,
                s_std,
                self.min_mean_spread_bps + 0.50,
                cnt,
            )

    def update(self, spread_bps: float, ts: Optional[float] = None) -> None:
        """Alias for record_spread_bps."""
        self.record_spread_bps(spread_bps, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_spread_variance_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if len(self._short_history) >= 2:
                short_var = statistics.variance(self._short_history)
                short_std = math.sqrt(short_var)
                short_mean = statistics.mean(self._short_history)
            else:
                short_std = self._latest_short_std
                short_mean = self._latest_spread

            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "spread_variance_ratio": float(self._latest_variance_ratio),
                "short_term_spread_std_bps": float(short_std),
                "short_term_mean_spread_bps": float(short_mean),
                "latest_spread_bps": float(self._latest_spread),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_spread_variance_metrics()

    def reset(self) -> None:
        with self._lock:
            self._short_history.clear()
            self._long_history.clear()
            self._latest_spread = 0.0
            self._latest_variance_ratio = 1.0
            self._latest_short_std = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
