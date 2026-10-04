"""
Wave 45: LondonOpenBooster
During the London Open spike window (07:00-08:00 UTC), lower the entry score
threshold by 10% to increase entry frequency during peak liquidity.
This is advisory — it modifies the min_score passed to the signal gate.
"""

import time
import datetime
import logging

logger = logging.getLogger(__name__)

_LONDON_OPEN_START_UTC = 7    # 07:00 UTC
_LONDON_OPEN_END_UTC   = 8    # 08:00 UTC
_SCORE_DISCOUNT        = 0.10  # reduce threshold by 10% during window


class LondonOpenBooster:
    """Boosts trade entry frequency during the London open spike window."""

    def __init__(self,
                 start_hour_utc: int = _LONDON_OPEN_START_UTC,
                 end_hour_utc: int   = _LONDON_OPEN_END_UTC,
                 score_discount: float = _SCORE_DISCOUNT):
        self._start = start_hour_utc
        self._end   = end_hour_utc
        self._discount = score_discount

    def _in_london_open(self) -> bool:
        utc_hour = datetime.datetime.utcnow().hour
        return self._start <= utc_hour < self._end

    def adjust_min_score(self, min_score: float) -> float:
        """Return (possibly reduced) min_score for signal gate.
        Lower = easier to enter = more trades during London open."""
        if self._in_london_open():
            adjusted = min_score * (1.0 - self._discount)
            logger.info(
                f"[WAVE45] London Open Booster active — "
                f"min_score {min_score:.2f} -> {adjusted:.2f} (-{self._discount*100:.0f}%)"
            )
            return adjusted
        return min_score

    def is_active(self) -> bool:
        return self._in_london_open()

    def info(self) -> dict:
        active = self._in_london_open()
        return {
            "london_open_active": active,
            "window_utc": f"{self._start:02d}:00-{self._end:02d}:00",
            "score_discount_pct": self._discount * 100,
        }


# Module-level singleton
london_open_booster = LondonOpenBooster()
