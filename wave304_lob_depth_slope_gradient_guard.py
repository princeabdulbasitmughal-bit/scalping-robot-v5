"""
wave304_lob_depth_slope_gradient_guard.py
-----------------------------------------
Guard: LOB Multi-Tier Cumulative Depth Slope & Liquidity Gradient Guard

Monitors limit order book multi-tier cumulative depth accumulation slope (liquidity gradient)
away from the inside quotes, guarding against hollow order books, liquidity vacuum traps, and step-function depletion
(Biais, Hillion & Spatt 1995; Bouchaud, Mezard & Potters 2002; Farmer, Patzelt & Zovko 2005; Hautsch & Huang 2012):
    Price Tiers:                  k = 1, 2, ..., K  (default K = 5 tiers)
    Tier Depth:                   q_k = (q_{bid,k} + q_{ask,k}) in lots
    Cumulative Depth:             Q_k = sum_{j=1}^k q_j
    Liquidity Gradient Slope:     S_{LOB} = (Q_K - Q_1) / (K - 1)  (lots / tick)
                                  or OLS slope beta = Cov(k, Q_k) / Var(k)
    Rolling Mean Gradient:        \\bar{S}_{LOB} = (1 / N) * sum_{i=1}^N S_{LOB, i}

Under healthy, deep liquid quoting conditions:
    - Order book accumulates thick liquidity behind the top-of-book quotes:
      \\bar{S}_{LOB} >= 2.50 lots/tick.

Under liquidity withdrawal, phantom quote flickering, or post-sweep vacuum traps:
    - Order book displays an extremely flat or hollow depth profile:
        1) Depleted Book Gradient:
           Rolling mean liquidity slope \\bar{S}_{LOB} <= MIN_GRADIENT_SLOPE (default: 0.80 lots/tick)
           over rolling N >= MIN_SAMPLES (default: 8 snapshots).
        2) Acute Liquidity Vacuum Shock:
           Instantaneous gradient S_{LOB} <= ACUTE_GRADIENT_SLOPE (default: 0.15 lots/tick)
           with inside spread S >= ACUTE_SPREAD_BPS (default: 2.20 bps),
           OR tier 2 through 4 cumulative depth <= ACUTE_MIN_OUTER_DEPTH (default: 1.00 lot).

Trading against a hollow, depleted liquidity gradient guarantees severe market impact,
massive slippage, and instantaneous cascading fills through empty order book levels.

When depleted liquidity gradient or an acute vacuum shock is detected, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests multi-tier book depths via record_lob_depths(bid_depths, ask_depths, spread_bps=None, ts=None)
  or direct metrics via record_slope_metrics(slope, spread_bps=None, sample_count=None, ts=None).
- Rolling window of WINDOW_SIZE = 20 snapshots.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative depths/spreads are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_lob_depths(bid_depths, ask_depths, spread_bps=None, ts=None)                          -> None
  record_slope_metrics(slope, spread_bps=None, sample_count=None, ts=None)                     -> None
  update(bid_depths, ask_depths, spread_bps=None, ts=None)                                     -> None   (alias)
  get_gradient_metrics()                                                                       -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional, Sequence


class Wave304LobDepthSlopeGradientGuard:
    """
    Guards against LOB multi-tier cumulative depth slope collapse, hollow order books, and vacuum traps.
    """

    MIN_GRADIENT_SLOPE: float = 0.80
    MIN_SAMPLES: int = 8
    ACUTE_GRADIENT_SLOPE: float = 0.15
    ACUTE_SPREAD_BPS: float = 2.20
    ACUTE_MIN_OUTER_DEPTH: float = 1.00
    WINDOW_SIZE: int = 20
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        min_gradient_slope: float = MIN_GRADIENT_SLOPE,
        min_samples: int = MIN_SAMPLES,
        acute_gradient_slope: float = ACUTE_GRADIENT_SLOPE,
        acute_spread_bps: float = ACUTE_SPREAD_BPS,
        acute_min_outer_depth: float = ACUTE_MIN_OUTER_DEPTH,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.min_gradient_slope = float(min_gradient_slope)
        self.min_samples = int(min_samples)
        self.acute_gradient_slope = float(acute_gradient_slope)
        self.acute_spread_bps = float(acute_spread_bps)
        self.acute_min_outer_depth = float(acute_min_outer_depth)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._slope_history = collections.deque(maxlen=self.window_size)

        self._latest_slope: float = 3.0
        self._latest_mean_slope: float = 3.0
        self._latest_spread: float = 1.0
        self._latest_outer_depth: float = 10.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _check_and_trigger_block(
        self,
        slope: float,
        mean_slope: float,
        spread_bps: float,
        outer_depth: float,
        sample_count: int,
    ) -> bool:
        # 1. Acute liquidity vacuum shock
        if slope <= self.acute_gradient_slope and spread_bps >= self.acute_spread_bps:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_LIQUIDITY_VACUUM: slope={slope:.3f} <= {self.acute_gradient_slope:.3f} lots/tick "
                f"with spread={spread_bps:.2f} >= {self.acute_spread_bps:.2f} bps"
            )
            return True

        # 2. Acute outer depth depletion
        if outer_depth <= self.acute_min_outer_depth and slope <= self.acute_gradient_slope * 2.0:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_OUTER_DEPTH_COLLAPSE: outer_depth={outer_depth:.2f} <= {self.acute_min_outer_depth:.2f} lots "
                f"(slope={slope:.3f})"
            )
            return True

        # 3. Rolling depleted book gradient
        if sample_count >= self.min_samples and mean_slope <= self.min_gradient_slope:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"DEPLETED_BOOK_GRADIENT: mean_slope={mean_slope:.3f} <= {self.min_gradient_slope:.3f} lots/tick "
                f"over N={sample_count} samples"
            )
            return True

        return False

    def record_lob_depths(
        self,
        bid_depths: Sequence[float],
        ask_depths: Sequence[float],
        spread_bps: Optional[float] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Record multi-tier limit order book bid and ask depths in lots.
        """
        with self._lock:
            if not isinstance(bid_depths, (list, tuple)) or not isinstance(ask_depths, (list, tuple)):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_LOB_DEPTH_INPUT"
                return

            if len(bid_depths) < 2 or len(ask_depths) < 2:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_LOB_DEPTH_INPUT"
                return

            for d in list(bid_depths) + list(ask_depths):
                if not self._is_valid_num(d) or d < 0.0:
                    now_mono = time.monotonic()
                    self._blocked_until = now_mono + self.cooldown_seconds
                    self._last_block_reason = "CORRUPTED_LOB_DEPTH_INPUT"
                    return

            spr = 1.0
            if spread_bps is not None:
                if not self._is_valid_num(spread_bps) or spread_bps < 0.0:
                    now_mono = time.monotonic()
                    self._blocked_until = now_mono + self.cooldown_seconds
                    self._last_block_reason = "CORRUPTED_SPREAD_INPUT"
                    return
                spr = float(spread_bps)

            num_tiers = min(len(bid_depths), len(ask_depths))
            combined_depths = [float(bid_depths[i]) + float(ask_depths[i]) for i in range(num_tiers)]

            # Cumulative depth
            cum_depths = []
            running_tot = 0.0
            for d in combined_depths:
                running_tot += d
                cum_depths.append(running_tot)

            # Gradient slope across tiers: delta Q / delta ticks
            slope = (cum_depths[-1] - cum_depths[0]) / max(num_tiers - 1, 1)

            # Outer depth (tiers 1 through end)
            outer_depth = sum(combined_depths[1:])

            self._slope_history.append(slope)
            self._sample_count += 1
            mean_slope = statistics.fmean(self._slope_history)

            self._latest_slope = slope
            self._latest_mean_slope = mean_slope
            self._latest_spread = spr
            self._latest_outer_depth = outer_depth

            self._check_and_trigger_block(
                slope,
                mean_slope,
                spr,
                outer_depth,
                len(self._slope_history),
            )

    def record_slope_metrics(
        self,
        slope: float,
        spread_bps: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed liquidity gradient slope.
        """
        with self._lock:
            if not self._is_valid_num(slope) or slope < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_SLOPE_METRIC"
                return

            slp = float(slope)
            spr = float(spread_bps) if (self._is_valid_num(spread_bps) and spread_bps >= 0.0) else 1.0
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_slope = slp
            self._latest_mean_slope = slp
            self._latest_spread = spr
            self._latest_outer_depth = slp * 3.0
            self._sample_count = cnt

            self._check_and_trigger_block(
                slp,
                slp,
                spr,
                slp * 3.0,
                cnt,
            )

    def update(
        self,
        bid_depths: Sequence[float],
        ask_depths: Sequence[float],
        spread_bps: Optional[float] = None,
        ts: Optional[float] = None,
    ) -> None:
        """Alias for record_lob_depths."""
        self.record_lob_depths(bid_depths, ask_depths, spread_bps=spread_bps, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_gradient_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "latest_slope": float(self._latest_slope),
                "mean_slope": float(self._latest_mean_slope),
                "latest_spread_bps": float(self._latest_spread),
                "outer_depth": float(self._latest_outer_depth),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_gradient_metrics()

    def reset(self) -> None:
        with self._lock:
            self._slope_history.clear()
            self._latest_slope = 3.0
            self._latest_mean_slope = 3.0
            self._latest_spread = 1.0
            self._latest_outer_depth = 10.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
