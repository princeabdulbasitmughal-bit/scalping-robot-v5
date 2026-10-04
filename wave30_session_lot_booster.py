"""
Wave 30: Session Lot Booster
Boosts position size by a configurable multiplier during peak London+NY overlap
(12:00–15:00 UTC) when volatility and win conditions are favourable.

Activation conditions (ALL must be true):
  - Current UTC time is within overlap window
  - vol_index >= min_vol_index (default 1.3)
  - win_rate_pct >= min_win_rate (default 55.0)
"""

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
        self._start_h = overlap_start_utc
        self._end_h = overlap_end_utc
        self._boost = boost_multiplier
        self._min_vol = min_vol_index
        self._min_wr = min_win_rate
        self._total_boosts: int = 0
        self._last_boosted: bool = False
        self._created_at: float = time.time()

    def _in_overlap(self) -> bool:
        utc_hour = datetime.now(timezone.utc).hour
        return self._start_h <= utc_hour < self._end_h

    def apply_boost(self, lot: float, vol_index: float = 1.0,
                    win_rate_pct: float = 50.0) -> float:
        """
        Returns boosted lot if all conditions are met, else unchanged lot.
        Always respects the caller's max_lot_size cap — callers must enforce that.
        """
        if self._in_overlap() and vol_index >= self._min_vol and win_rate_pct >= self._min_wr:
            boosted = round(lot * self._boost, 2)
            if not self._last_boosted:
                self._total_boosts += 1
            self._last_boosted = True
            return max(boosted, lot)  # never reduce
        self._last_boosted = False
        return lot

    def info(self) -> dict:
        utc_hour = datetime.now(timezone.utc).hour
        return {
            "in_overlap_window": self._in_overlap(),
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
