"""
wave299_trade_volume_pareto_ratio_guard.py
------------------------------------------
Guard: Trade Volume 80/20 Pareto Concentration Ratio & Whale Dominance Guard

Monitors trade volume distribution skew, top-quintile volume concentration, and single-order whale dominance
(Pareto 1896; Newman 2005; Gabaix et al. 2006; Easley, Lopez de Prado & O'Hara 2012):
    Trade Volume Stream:         V = [v_1, v_2, ..., v_N] in lots
    Descending Order Statistics: V_{(1)} >= V_{(2)} >= ... >= V_{(N)}
    Top Quintile Count:          k = max(1, floor(0.20 * N))
    Top 20% Volume Share:        R_{pareto} = sum_{i=1}^k V_{(i)} / max(sum_{j=1}^N V_j, 0.10) in [0.20, 1.00]
    Single Whale Share:          D_{max} = V_{(1)} / max(sum_{j=1}^N V_j, 0.10) in [0.0, 1.00]

Under natural, heterogeneous market participation:
    - Order volume is distributed across a large base of retail and institutional participants:
      R_{pareto} in [0.40, 0.65], D_{max} <= 0.30.

During predatory institutional sweeps, iceberg unloads, or whale block trades:
    - Order volume concentrates almost exclusively into the largest 20% or a single block:
        1) Severe Pareto Volume Concentration:
           Pareto ratio R_{pareto} >= MAX_PARETO_RATIO (default: 0.82)
           with total volume V_{total} >= MIN_TOTAL_VOLUME (default: 20.0 lots)
           over rolling N >= MIN_TRADES (default: 15 trades).
        2) Acute Whale Block Dominance:
           Single whale share D_{max} >= ACUTE_BLOCK_SHARE (default: 0.50)
           with largest trade V_{(1)} >= ACUTE_MIN_BLOCK_SIZE (default: 15.0 lots)
           over rolling N >= ACUTE_MIN_TRADES (default: 10 trades).

Trading into heavily concentrated volume regimes exposes market orders to extreme adverse selection,
predatory whale front-running, and sudden depth evaporation.

When Pareto concentration or acute whale dominance is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade volume via record_trade_volume(volume_lots, ts=None) or
  direct metrics via record_pareto_metrics(pareto_ratio, whale_share=None, max_size=None, total_volume=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 25 trades.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive volumes are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_volume(volume_lots, ts=None)                                                    -> None
  record_pareto_metrics(pareto_ratio, whale_share=None, max_size=None, total_volume=None)      -> None
  update(volume_lots, ts=None)                                                                 -> None   (alias)
  get_pareto_metrics()                                                                         -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class Wave299TradeVolumeParetoRatioGuard:
    """
    Guards against trade volume Pareto 80/20 overconcentration, single whale dominance, and adverse selection.
    """

    MAX_PARETO_RATIO: float = 0.82
    MIN_TOTAL_VOLUME: float = 20.0
    MIN_TRADES: int = 15
    ACUTE_BLOCK_SHARE: float = 0.50
    ACUTE_MIN_BLOCK_SIZE: float = 15.0
    ACUTE_MIN_TRADES: int = 10
    WINDOW_SIZE: int = 25
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_pareto_ratio: float = MAX_PARETO_RATIO,
        min_total_volume: float = MIN_TOTAL_VOLUME,
        min_trades: int = MIN_TRADES,
        acute_block_share: float = ACUTE_BLOCK_SHARE,
        acute_min_block_size: float = ACUTE_MIN_BLOCK_SIZE,
        acute_min_trades: int = ACUTE_MIN_TRADES,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_pareto_ratio = float(max_pareto_ratio)
        self.min_total_volume = float(min_total_volume)
        self.min_trades = int(min_trades)
        self.acute_block_share = float(acute_block_share)
        self.acute_min_block_size = float(acute_min_block_size)
        self.acute_min_trades = int(acute_min_trades)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._volume_history = collections.deque(maxlen=self.window_size)

        self._latest_volume: float = 0.0
        self._latest_pareto_ratio: float = 0.50
        self._latest_whale_share: float = 0.20
        self._latest_max_size: float = 0.0
        self._latest_total_vol: float = 0.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _calculate_pareto(self, volumes: List[float]) -> Tuple[float, float, float, float]:
        n = len(volumes)
        if n == 0:
            return 0.50, 0.0, 0.0, 0.0
        total_vol = sum(volumes)
        if total_vol <= 1e-4:
            return 0.50, 0.0, 0.0, 0.0

        sorted_v = sorted(volumes, reverse=True)
        k = max(1, math.floor(0.20 * n))
        top_vol = sum(sorted_v[:k])
        pareto_ratio = top_vol / total_vol
        max_size = sorted_v[0]
        whale_share = max_size / total_vol

        return float(pareto_ratio), float(whale_share), float(max_size), float(total_vol)

    def _check_and_trigger_block(
        self,
        pareto_ratio: float,
        whale_share: float,
        max_size: float,
        total_vol: float,
        sample_count: int,
    ) -> bool:
        # 1. Acute whale block dominance
        if (
            sample_count >= self.acute_min_trades
            and whale_share >= self.acute_block_share
            and max_size >= self.acute_min_block_size
        ):
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_WHALE_DOMINANCE: whale_share={whale_share:.2f} >= {self.acute_block_share:.2f}, "
                f"max_size={max_size:.2f} >= {self.acute_min_block_size:.2f} lots (N={sample_count})"
            )
            return True

        # 2. Severe Pareto volume concentration
        if (
            sample_count >= self.min_trades
            and pareto_ratio >= self.max_pareto_ratio
            and total_vol >= self.min_total_volume
        ):
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"PARETO_VOLUME_CONCENTRATION: ratio={pareto_ratio:.2f} >= {self.max_pareto_ratio:.2f}, "
                f"total_vol={total_vol:.2f} >= {self.min_total_volume:.2f} lots (N={sample_count})"
            )
            return True

        return False

    def record_trade_volume(self, volume_lots: float, ts: Optional[float] = None) -> None:
        """
        Record a trade execution volume and update Pareto concentration statistics.
        """
        with self._lock:
            if not self._is_valid_num(volume_lots) or volume_lots <= 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_VOLUME_INPUT"
                return

            vol = float(volume_lots)
            self._latest_volume = vol
            self._volume_history.append(vol)
            self._sample_count += 1

            v_list = list(self._volume_history)
            pareto_ratio, whale_share, max_size, total_vol = self._calculate_pareto(v_list)

            self._latest_pareto_ratio = pareto_ratio
            self._latest_whale_share = whale_share
            self._latest_max_size = max_size
            self._latest_total_vol = total_vol

            self._check_and_trigger_block(
                pareto_ratio,
                whale_share,
                max_size,
                total_vol,
                len(v_list),
            )

    def record_pareto_metrics(
        self,
        pareto_ratio: float,
        whale_share: Optional[float] = None,
        max_size: Optional[float] = None,
        total_volume: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed Pareto volume metrics.
        """
        with self._lock:
            if not self._is_valid_num(pareto_ratio) or pareto_ratio < 0.0 or pareto_ratio > 1.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_PARETO_METRIC"
                return

            pr = float(pareto_ratio)
            ws = float(whale_share) if (self._is_valid_num(whale_share) and 0.0 <= whale_share <= 1.0) else 0.20
            ms = float(max_size) if (self._is_valid_num(max_size) and max_size >= 0.0) else 0.0
            tv = float(total_volume) if (self._is_valid_num(total_volume) and total_volume >= 0.0) else self.min_total_volume + 5.0
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_trades

            self._latest_pareto_ratio = pr
            self._latest_whale_share = ws
            self._latest_max_size = ms
            self._latest_total_vol = tv
            self._sample_count = cnt

            self._check_and_trigger_block(
                pr,
                ws,
                ms,
                tv,
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

    def get_pareto_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if self._volume_history:
                pareto_ratio, whale_share, max_size, total_vol = self._calculate_pareto(list(self._volume_history))
            else:
                pareto_ratio = self._latest_pareto_ratio
                whale_share = self._latest_whale_share
                max_size = self._latest_max_size
                total_vol = self._latest_total_vol

            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "pareto_ratio": float(pareto_ratio),
                "whale_share": float(whale_share),
                "max_trade_size_lots": float(max_size),
                "total_volume_lots": float(total_vol),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_pareto_metrics()

    def reset(self) -> None:
        with self._lock:
            self._volume_history.clear()
            self._latest_volume = 0.0
            self._latest_pareto_ratio = 0.50
            self._latest_whale_share = 0.20
            self._latest_max_size = 0.0
            self._latest_total_vol = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
