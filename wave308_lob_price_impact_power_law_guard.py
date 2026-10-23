"""
wave308_lob_price_impact_power_law_guard.py
-------------------------------------------
Guard: LOB Price Impact Power-Law Exponent Guard

Monitors empirical price impact power-law exponent delta, guarding against super-linear price impact breakdown,
fragile order book feedback loops, and flash illiquidity shocks
(Bouchaud et al. 2004, 2009; Almgren et al. 2005; Bershova & Rakhlin 2013; Donier et al. 2015):
    Trade Size:                   V_i in lots
    Observed Price Impact:        Delta p_i = |p_i - p_{i-1}| in bps
    Power-Law Impact Relation:    Delta p = C * V^delta  =>  ln(Delta p) = ln(C) + delta * ln(V)
    OLS Power-Law Exponent:       delta = Cov(ln(V), ln(Delta p)) / Var(ln(V))
    Rolling Mean Exponent:        \\bar{delta} = (1 / N) * sum_{j=1}^N delta_j

Under normal liquid equilibrium:
    - Empirical price impact obeys the universal concave square-root law:
      delta in [0.40, 0.65], absorbing volume sub-linearly.

Under fragile order books, liquidity black holes, or predatory adverse selection:
    - Price impact explodes super-linearly as book depth evaporates:
        1) Super-Linear Impact Surge:
           Rolling impact exponent \\bar{delta} >= MAX_IMPACT_EXPONENT (default: 1.15)
           with average impact Delta p >= MIN_MEAN_IMPACT_BPS (default: 2.50 bps)
           over rolling N >= MIN_SAMPLES (default: 10 impact events).
        2) Acute Impact Blowout Shock:
           Small/moderate trade V <= 2.00 lots generates acute price shock Delta p >= ACUTE_IMPACT_BPS (default: 4.50 bps).

Trading into super-linear price impact guarantees massive slippage penalties and explosive market impact losses.

When super-linear impact surge or an acute impact blowout is detected, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade impact pairs via record_trade_impact(volume_lots, impact_bps, ts=None) or
  direct metrics via record_impact_metrics(exponent_delta, mean_impact_bps=None, sample_count=None, ts=None).
- Rolling window of WINDOW_SIZE = 25 events.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive volumes or negative impacts are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_impact(volume_lots, impact_bps, ts=None)                                        -> None
  record_impact_metrics(exponent_delta, mean_impact_bps=None, sample_count=None, ts=None)      -> None
  update(volume_lots, impact_bps, ts=None)                                                     -> None   (alias)
  get_impact_metrics()                                                                         -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave308LobPriceImpactPowerLawGuard:
    """
    Guards against LOB super-linear price impact breakdown, fragile depth feedback, and flash illiquidity shocks.
    """

    MAX_IMPACT_EXPONENT: float = 1.15
    MIN_SAMPLES: int = 10
    MIN_MEAN_IMPACT_BPS: float = 2.50
    ACUTE_IMPACT_BPS: float = 4.50
    ACUTE_MAX_VOLUME_LOTS: float = 2.00
    WINDOW_SIZE: int = 25
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_impact_exponent: float = MAX_IMPACT_EXPONENT,
        min_samples: int = MIN_SAMPLES,
        min_mean_impact_bps: float = MIN_MEAN_IMPACT_BPS,
        acute_impact_bps: float = ACUTE_IMPACT_BPS,
        acute_max_volume_lots: float = ACUTE_MAX_VOLUME_LOTS,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_impact_exponent = float(max_impact_exponent)
        self.min_samples = int(min_samples)
        self.min_mean_impact_bps = float(min_mean_impact_bps)
        self.acute_impact_bps = float(acute_impact_bps)
        self.acute_max_volume_lots = float(acute_max_volume_lots)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._events = collections.deque(maxlen=self.window_size)

        self._latest_exponent: float = 0.50
        self._latest_mean_impact: float = 1.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _estimate_exponent(self) -> tuple[float, float]:
        n = len(self._events)
        if n < 4:
            return 0.50, 1.0

        vols = [math.log(max(v, 1e-3)) for v, _ in self._events]
        imps = [math.log(max(imp, 1e-3)) for _, imp in self._events]
        raw_imps = [imp for _, imp in self._events]

        mean_v = statistics.fmean(vols)
        mean_i = statistics.fmean(imps)
        mean_raw_imp = statistics.fmean(raw_imps)

        var_v = sum((x - mean_v) ** 2 for x in vols)
        if var_v <= 1e-6:
            return 0.50, mean_raw_imp

        cov_vi = sum((vols[i] - mean_v) * (imps[i] - mean_i) for i in range(n))
        exponent = cov_vi / var_v
        return exponent, mean_raw_imp

    def _check_and_trigger_block(
        self,
        exponent: float,
        mean_impact: float,
        acute_volume: float,
        acute_impact: float,
        count: int,
    ) -> bool:
        # 1. Acute impact blowout shock
        if acute_volume <= self.acute_max_volume_lots and acute_impact >= self.acute_impact_bps:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_IMPACT_BLOWOUT: impact={acute_impact:.2f} >= {self.acute_impact_bps:.2f} bps "
                f"for volume={acute_volume:.2f} <= {self.acute_max_volume_lots:.2f} lots"
            )
            return True

        # 2. Super-linear impact surge
        if count >= self.min_samples and exponent >= self.max_impact_exponent and mean_impact >= self.min_mean_impact_bps:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"SUPER_LINEAR_IMPACT_SURGE: delta={exponent:.3f} >= {self.max_impact_exponent:.3f} "
                f"with mean_impact={mean_impact:.2f} >= {self.min_mean_impact_bps:.2f} bps over N={count}"
            )
            return True

        return False

    def record_trade_impact(self, volume_lots: float, impact_bps: float, ts: Optional[float] = None) -> None:
        """
        Record individual trade volume and resulting price impact in bps.
        """
        with self._lock:
            if not self._is_valid_num(volume_lots) or not self._is_valid_num(impact_bps) or volume_lots <= 0.0 or impact_bps < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_IMPACT_INPUT"
                return

            vol = float(volume_lots)
            imp = float(impact_bps)

            self._events.append((vol, imp))
            self._sample_count += 1

            exponent, mean_imp = self._estimate_exponent()
            self._latest_exponent = exponent
            self._latest_mean_impact = mean_imp

            self._check_and_trigger_block(
                exponent,
                mean_imp,
                vol,
                imp,
                len(self._events),
            )

    def record_impact_metrics(
        self,
        exponent_delta: float,
        mean_impact_bps: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed power-law impact metrics.
        """
        with self._lock:
            if not self._is_valid_num(exponent_delta):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_EXPONENT_METRIC"
                return

            delta = float(exponent_delta)
            m_imp = float(mean_impact_bps) if (self._is_valid_num(mean_impact_bps) and mean_impact_bps >= 0.0) else (self.min_mean_impact_bps + 0.5)
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_exponent = delta
            self._latest_mean_impact = m_imp
            self._sample_count = cnt

            self._check_and_trigger_block(
                delta,
                m_imp,
                1.0,
                self.acute_impact_bps + 1.0 if delta >= 2.0 else 0.5,
                cnt,
            )

    def update(self, volume_lots: float, impact_bps: float, ts: Optional[float] = None) -> None:
        """Alias for record_trade_impact."""
        self.record_trade_impact(volume_lots, impact_bps, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_impact_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "exponent_delta": float(self._latest_exponent),
                "mean_impact_bps": float(self._latest_mean_impact),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_impact_metrics()

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._latest_exponent = 0.50
            self._latest_mean_impact = 1.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
