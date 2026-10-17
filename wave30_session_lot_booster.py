"""
Wave 30: Session Lot Booster
Boosts position size by a configurable multiplier during peak London+NY overlap
(12:00–15:00 UTC) when volatility and win conditions are favourable.

Activation conditions (ALL must be true):
  - Current UTC time is within overlap window
  - vol_index >= min_vol_index (default 1.3)
  - win_rate_pct >= min_win_rate (default 55.0)
"""

import math
import threading
import time
from datetime import datetime, timezone


class SessionLotBooster:
    def __init__(
        self,
        overlap_start_utc: int = 12,
        overlap_end_utc: int = 15,
        boost_multiplier: float = 1.2,
        min_vol_index: float = 1.3,
        min_win_rate: float = 55.0,
    ):
        self._lock = threading.RLock()
        self._start_h = overlap_start_utc
        self._end_h = overlap_end_utc
        self._boost = boost_multiplier
        self._min_vol = min_vol_index
        self._min_wr = min_win_rate
        self._total_boosts: int = 0
        self._last_boosted: bool = False
        self._created_at: float = time.time()

    def reset(self) -> None:
        """Reset internal telemetry and booster state."""
        with self._lock:
            self._total_boosts = 0
            self._last_boosted = False

    def _in_overlap(self, now_dt: datetime = None) -> bool:
        dt = now_dt or datetime.now(timezone.utc)
        utc_hour = dt.hour
        if self._start_h <= self._end_h:
            return self._start_h <= utc_hour < self._end_h
        return utc_hour >= self._start_h or utc_hour < self._end_h

    def apply_boost(
        self,
        lot: float,
        vol_index: float = 1.0,
        win_rate_pct: float = 50.0,
        now_dt: datetime = None,
    ) -> float:
        """
        Returns boosted lot if all conditions are met, else unchanged lot.
        Always respects the caller's max_lot_size cap — callers must enforce that.
        """
        if (
            lot is None
            or not isinstance(lot, (int, float))
            or not math.isfinite(lot)
            or lot <= 0
        ):
            return lot

        if not isinstance(vol_index, (int, float)) or not math.isfinite(vol_index):
            safe_vol = 1.0
        else:
            safe_vol = float(vol_index)

        if not isinstance(win_rate_pct, (int, float)) or not math.isfinite(win_rate_pct):
            safe_wr = 0.0
        else:
            safe_wr = float(win_rate_pct)

        with self._lock:
            if self._in_overlap(now_dt) and safe_vol >= self._min_vol and safe_wr >= self._min_wr:
                boosted = round(float(lot) * self._boost, 2)
                if not self._last_boosted:
                    self._total_boosts += 1
                self._last_boosted = True
                return max(boosted, float(lot))  # never reduce
            self._last_boosted = False
            return float(lot)

    def info(self, now_dt: datetime = None) -> dict:
        dt = now_dt or datetime.now(timezone.utc)
        utc_hour = dt.hour
        with self._lock:
            return {
                "in_overlap_window": self._in_overlap(now_dt=dt),
                "overlap_hours_utc": f"{self._start_h:02d}:00-{self._end_h:02d}:00",
                "boost_multiplier": self._boost,
                "min_vol_index_required": self._min_vol,
                "min_win_rate_required": self._min_wr,
                "currently_boosted": self._last_boosted,
                "total_boosts": self._total_boosts,
                "utc_hour": utc_hour,
            }


# Module-level singleton
session_lot_booster = SessionLotBooster(
    overlap_start_utc=12,
    overlap_end_utc=15,
    boost_multiplier=1.2,
    min_vol_index=1.3,
    min_win_rate=55.0,
)
