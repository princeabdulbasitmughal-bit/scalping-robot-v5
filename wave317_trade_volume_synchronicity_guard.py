"""
wave317_trade_volume_synchronicity_guard.py
-------------------------------------------
Guard: High-Frequency Trade Volume Synchronicity & Mechanical Impact Guard [Wave 317 - 3,000 Tests Milestone]

Monitors empirical volume-price synchronicity R^2 and mechanical impact correlation,
guarding against predatory synchronized institutional liquidation, mechanical sweeping, and acute whale dislocations
(Roll 1988; Morck, Yeung & Yu 2000; Durnev et al. 2003; Easley et al. 2012):
    Signed Trade Volume:          V_{signed, i} = s_i * V_i  (s_i in {+1, -1}, V_i in lots)
    Price Dislocation:            Delta p_i = (p_i - p_{i-1}) in bps
    Volume-Price Correlation:     r = Cov(V_{signed}, Delta p) / max(sigma_V * sigma_p, 1e-4)
    Synchronicity Coefficient:    R^2 = max(0.0, min(1.0, r^2))

Under natural two-sided retail and speculative flow:
    - Order flow contains substantial noise, limit order replenishment, and cross-flow:
      R^2 in [0.05, 0.50].

Under coordinated algorithmic dumping or predatory sweeping:
    - Trade volume exhibits overwhelming, mechanical correlation with directional price movement:
        1) Hyper-Synchronous Impact:
           Synchronicity R^2 >= MAX_SYNCHRONICITY_R2 (default: 0.82)
           with substantial total volume V_{total} >= MIN_TOTAL_VOLUME (default: 15.0 lots)
           over rolling N >= MIN_SAMPLES (default: 12 trades).
        2) Acute Synchronized Whale Impact:
           Single trade print V_t >= ACUTE_WHALE_VOLUME (default: 15.0 lots)
           instantly generating price dislocation |Delta p| >= ACUTE_PRICE_DISLOCATION_BPS (default: 4.00 bps).

Trading during hyper-synchronous liquidation guarantees stepping directly into active algorithmic execution programs,
suffering immediate mechanical market impact.

When hyper-synchronous impact or an acute synchronized whale impact is detected, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade dislocation pairs via record_trade_dislocation(sign, volume_lots, price_dislocation_bps, ts=None) or
  direct metrics via record_synchronicity_metrics(r_squared, total_volume=None, sample_count=None, ts=None).
- Rolling window of WINDOW_SIZE = 25 trades.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive volumes are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_dislocation(sign, volume_lots, price_dislocation_bps, ts=None)                  -> None
  record_synchronicity_metrics(r_squared, total_volume=None, sample_count=None, ts=None)        -> None
  update(sign, volume_lots, price_dislocation_bps, ts=None)                                    -> None   (alias)
  get_synchronicity_metrics()                                                                  -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave317TradeVolumeSynchronicityGuard:
    """
    Guards against trade volume hyper-synchronicity, predatory mechanical liquidation, and acute whale impacts.
    """

    MAX_SYNCHRONICITY_R2: float = 0.82
    MIN_SAMPLES: int = 12
    MIN_TOTAL_VOLUME: float = 15.0
    ACUTE_WHALE_VOLUME: float = 15.0
    ACUTE_PRICE_DISLOCATION_BPS: float = 4.00
    WINDOW_SIZE: int = 25
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_synchronicity_r2: float = MAX_SYNCHRONICITY_R2,
        min_samples: int = MIN_SAMPLES,
        min_total_volume: float = MIN_TOTAL_VOLUME,
        acute_whale_volume: float = ACUTE_WHALE_VOLUME,
        acute_price_dislocation_bps: float = ACUTE_PRICE_DISLOCATION_BPS,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_synchronicity_r2 = float(max_synchronicity_r2)
        self.min_samples = int(min_samples)
        self.min_total_volume = float(min_total_volume)
        self.acute_whale_volume = float(acute_whale_volume)
        self.acute_price_dislocation_bps = float(acute_price_dislocation_bps)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._events = collections.deque(maxlen=self.window_size)  # (signed_vol, disloc)

        self._latest_r2: float = 0.20
        self._latest_total_volume: float = 0.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _calculate_r2(self) -> tuple[float, float]:
        n = len(self._events)
        if n < 4:
            return 0.20, 0.0

        vols = [ev[0] for ev in self._events]
        dislocs = [ev[1] for ev in self._events]
        tot_vol = sum(abs(v) for v in vols)

        m_v = statistics.fmean(vols)
        m_d = statistics.fmean(dislocs)

        var_v = sum((v - m_v) ** 2 for v in vols)
        var_d = sum((d - m_d) ** 2 for d in dislocs)

        if var_v <= 1e-6 or var_d <= 1e-6:
            return 0.0, tot_vol

        cov_vd = sum((vols[i] - m_v) * (dislocs[i] - m_d) for i in range(n))
        r = cov_vd / math.sqrt(var_v * var_d)
        r2 = max(0.0, min(1.0, r ** 2))
        return r2, tot_vol

    def _check_and_trigger_block(
        self,
        r2: float,
        tot_vol: float,
        acute_vol: float,
        acute_disloc: float,
        count: int,
    ) -> bool:
        # 1. Acute synchronized whale impact
        if acute_vol >= self.acute_whale_volume and abs(acute_disloc) >= self.acute_price_dislocation_bps:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_SYNCHRONIZED_WHALE: volume={acute_vol:.2f} >= {self.acute_whale_volume:.2f} lots "
                f"with dislocation={abs(acute_disloc):.2f} >= {self.acute_price_dislocation_bps:.2f} bps"
            )
            return True

        # 2. Hyper-synchronous impact surge
        if count >= self.min_samples and r2 >= self.max_synchronicity_r2 and tot_vol >= self.min_total_volume:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"HYPER_SYNCHRONOUS_IMPACT: R2={r2:.3f} >= {self.max_synchronicity_r2:.3f} "
                f"with total_volume={tot_vol:.2f} >= {self.min_total_volume:.2f} lots over N={count}"
            )
            return True

        return False

    def record_trade_dislocation(
        self,
        sign: Any,
        volume_lots: float,
        price_dislocation_bps: float,
        ts: Optional[float] = None,
    ) -> None:
        """
        Record individual trade volume and resulting price movement in bps.
        """
        with self._lock:
            if not self._is_valid_num(volume_lots) or not self._is_valid_num(price_dislocation_bps) or volume_lots <= 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_DISLOCATION_INPUT"
                return

            val_sign = 0
            if isinstance(sign, bool):
                val_sign = 1 if sign else -1
            elif isinstance(sign, (int, float)):
                if not self._is_valid_num(sign):
                    now_mono = time.monotonic()
                    self._blocked_until = now_mono + self.cooldown_seconds
                    self._last_block_reason = "CORRUPTED_SIGN_INPUT"
                    return
                val_sign = 1 if sign > 0 else (-1 if sign < 0 else 0)
            elif isinstance(sign, str):
                s_lower = sign.strip().lower()
                if s_lower in ("buy", "b", "+1", "1"):
                    val_sign = 1
                elif s_lower in ("sell", "s", "-1"):
                    val_sign = -1
                else:
                    now_mono = time.monotonic()
                    self._blocked_until = now_mono + self.cooldown_seconds
                    self._last_block_reason = "CORRUPTED_SIGN_INPUT"
                    return
            else:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_SIGN_INPUT"
                return

            if val_sign == 0:
                return

            vol = float(volume_lots)
            signed_vol = val_sign * vol
            disloc = float(price_dislocation_bps)

            self._events.append((signed_vol, disloc))
            self._sample_count += 1

            r2, tot_vol = self._calculate_r2()
            self._latest_r2 = r2
            self._latest_total_volume = tot_vol

            self._check_and_trigger_block(
                r2,
                tot_vol,
                vol,
                disloc,
                len(self._events),
            )

    def record_synchronicity_metrics(
        self,
        r_squared: float,
        total_volume: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed volume-price synchronicity R^2.
        """
        with self._lock:
            if not self._is_valid_num(r_squared) or r_squared < 0.0 or r_squared > 1.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_SYNCHRONICITY_METRIC"
                return

            r2 = float(r_squared)
            tot_vol = float(total_volume) if (self._is_valid_num(total_volume) and total_volume >= 0.0) else (self.min_total_volume + 5.0)
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_r2 = r2
            self._latest_total_volume = tot_vol
            self._sample_count = cnt

            self._check_and_trigger_block(
                r2,
                tot_vol,
                self.acute_whale_volume + 2.0 if r2 >= 0.95 else 1.0,
                self.acute_price_dislocation_bps + 1.0 if r2 >= 0.95 else 0.5,
                cnt,
            )

    def update(
        self,
        sign: Any,
        volume_lots: float,
        price_dislocation_bps: float,
        ts: Optional[float] = None,
    ) -> None:
        """Alias for record_trade_dislocation."""
        self.record_trade_dislocation(sign, volume_lots, price_dislocation_bps, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_synchronicity_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "synchronicity_r2": float(self._latest_r2),
                "total_volume": float(self._latest_total_volume),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_synchronicity_metrics()

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._latest_r2 = 0.20
            self._latest_total_volume = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
