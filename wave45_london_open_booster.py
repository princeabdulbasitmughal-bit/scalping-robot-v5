"""
Wave 45: LondonOpenBooster
During the London Open spike window (07:00-08:00 UTC), lower the entry score
threshold by a configurable discount (default 10%) to increase entry frequency
during peak liquidity.
This is advisory — it modifies the min_score passed to the signal gate.
"""

from __future__ import annotations
import math
import threading
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

_LONDON_OPEN_START_UTC: int = 7     # 07:00 UTC
_LONDON_OPEN_END_UTC: int   = 8     # 08:00 UTC
_DEFAULT_SCORE_DISCOUNT: float = 0.10  # 10% discount
_MIN_SCORE_DISCOUNT: float = 0.0    # 0% discount floor
_MAX_SCORE_DISCOUNT: float = 0.50   # 50% max safe discount cap


class LondonOpenBooster:
    """
    Boosts trade entry frequency during the London open spike window.
    Thread-safe and supports deterministic datetime injection for backtesting.
    """

    def __init__(
        self,
        start_hour_utc: int = _LONDON_OPEN_START_UTC,
        end_hour_utc: int = _LONDON_OPEN_END_UTC,
        score_discount: float = _DEFAULT_SCORE_DISCOUNT,
        discount: Optional[float] = None,
        **kwargs,
    ):
        self._lock = threading.Lock()
        self._start: int = int(start_hour_utc) % 24
        self._end: int = int(end_hour_utc) % 24
        eff_discount = discount if discount is not None else score_discount
        self._discount: float = self._clamp_discount(eff_discount)

        # Telemetry & State
        self._total_boosts: int = 0
        self._last_boosted: bool = False
        self._last_original_score: Optional[float] = None
        self._last_adjusted_score: Optional[float] = None
        self._last_boost_time_utc: Optional[str] = None

    @staticmethod
    def _clamp_discount(discount: float) -> float:
        """Sanitize and clamp discount to [_MIN_SCORE_DISCOUNT, _MAX_SCORE_DISCOUNT]."""
        if not isinstance(discount, (int, float)) or not math.isfinite(discount):
            return _DEFAULT_SCORE_DISCOUNT
        return max(_MIN_SCORE_DISCOUNT, min(_MAX_SCORE_DISCOUNT, float(discount)))

    @property
    def multiplier(self) -> float:
        """Effective score multiplier, e.g. 0.90 for a 10% discount."""
        with self._lock:
            return round(1.0 - self._discount, 4)

    def reset(self) -> None:
        """Reset internal telemetry and state counters."""
        with self._lock:
            self._total_boosts = 0
            self._last_boosted = False
            self._last_original_score = None
            self._last_adjusted_score = None
            self._last_boost_time_utc = None

    def _in_london_open(self, now_dt: Optional[datetime] = None) -> bool:
        """
        Check if given datetime (or current UTC time) falls inside the window.
        Correctly handles midnight wrap-around.
        """
        if now_dt is None:
            now_dt = datetime.now(timezone.utc)
        elif now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)
        else:
            now_dt = now_dt.astimezone(timezone.utc)

        utc_hour = now_dt.hour
        if self._start <= self._end:
            return self._start <= utc_hour < self._end
        return utc_hour >= self._start or utc_hour < self._end

    def is_active(self, now_dt: Optional[datetime] = None) -> bool:
        """Public query if London Open Booster is currently active."""
        with self._lock:
            return self._in_london_open(now_dt)

    def adjust_min_score(
        self,
        min_score: float,
        now_dt: Optional[datetime] = None,
    ) -> float:
        """
        Return (possibly reduced) min_score for signal gate.
        Lower = easier to enter = more trades during London open.
        """
        if (
            min_score is None
            or isinstance(min_score, bool)
            or not isinstance(min_score, (int, float))
            or not math.isfinite(min_score)
            or min_score <= 0
        ):
            return min_score

        with self._lock:
            if self._in_london_open(now_dt):
                mult = max(0.50, min(1.0, 1.0 - self._discount))
                adjusted = round(float(min_score) * mult, 4)
                # Output sanity check: never raise score, never fall <= 0
                adjusted = max(0.0001, min(float(min_score), adjusted))

                if not self._last_boosted:
                    self._total_boosts += 1
                    logger.info(
                        f"[WAVE45] London Open Booster active — "
                        f"min_score {min_score:.2f} -> {adjusted:.2f} (-{self._discount*100:.0f}%)"
                    )
                else:
                    logger.debug(
                        f"[WAVE45] London Open Boost applied: {min_score:.4f} -> {adjusted:.4f}"
                    )

                self._last_boosted = True
                self._last_original_score = float(min_score)
                self._last_adjusted_score = adjusted
                now_str = (now_dt or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S UTC")
                self._last_boost_time_utc = now_str
                return adjusted

            self._last_boosted = False
            return float(min_score)

    def info(self, now_dt: Optional[datetime] = None) -> Dict[str, Any]:
        """Return standardized telemetry dictionary for omnicommand and live_status."""
        try:
            with self._lock:
                active = self._in_london_open(now_dt)
                if now_dt is None:
                    utc_dt = datetime.now(timezone.utc)
                elif now_dt.tzinfo is None:
                    utc_dt = now_dt.replace(tzinfo=timezone.utc)
                else:
                    utc_dt = now_dt.astimezone(timezone.utc)

                return {
                    "wave": 45,
                    "name": "LondonOpenBooster",
                    "trading_allowed": True,
                    "london_open_active": active,
                    "currently_boosted": self._last_boosted,
                    "window_utc": f"{self._start:02d}:00-{self._end:02d}:00",
                    "score_discount_pct": round(self._discount * 100, 2),
                    "score_multiplier": round(1.0 - self._discount, 4),
                    "total_boosts": self._total_boosts,
                    "last_original_score": self._last_original_score,
                    "last_adjusted_score": self._last_adjusted_score,
                    "last_boost_time_utc": self._last_boost_time_utc,
                    "utc_hour": utc_dt.hour,
                }
        except Exception as exc:
            logger.error(f"[WAVE45] info() failed: {exc}", exc_info=True)
            return {
                "wave": 45,
                "name": "LondonOpenBooster",
                "trading_allowed": True,
                "error": str(exc),
            }


# Module-level singleton
london_open_booster = LondonOpenBooster()
