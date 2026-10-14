"""
Wave 58: Price Range Filter
=============================
Tracks the high and low of intraday price action (reset at UTC midnight).
If the daily price range (high - low) is less than the minimum threshold
in pips, the market is too quiet/flat — blocks all entries.

API:
    price_range_filter.update(price: float)
    price_range_filter.is_entry_blocked() -> bool
    price_range_filter.get_range_pips() -> float
    price_range_filter.info() -> dict
"""

import math
import logging
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_DEFAULT_MIN_RANGE_PIPS = 5.0   # minimum daily range required to trade
_PIP = 0.1                       # XAUUSD: 1 pip = $0.10


class PriceRangeFilter:
    """
    Maintains rolling intraday high/low. Blocks entry when the range
    is below `min_range_pips`, indicating a dead/flat session.
    """

    def __init__(self, min_range_pips: float = _DEFAULT_MIN_RANGE_PIPS,
                 pip_value: float = _PIP):
        self.min_range_pips = min_range_pips
        self.pip_value = max(pip_value, 1e-6)  # guard against zero pip_value
        self._day_high: float = 0.0
        self._day_low: float = float('inf')
        self._last_day: int = -1
        self._ticks_today: int = 0
        self._lock = threading.Lock()

    def _maybe_reset_day(self) -> None:
        """Reset high/low at UTC midnight."""
        today = datetime.now(timezone.utc).timetuple().tm_yday
        if today != self._last_day:
            self._day_high = 0.0
            self._day_low = float('inf')
            self._ticks_today = 0
            self._last_day = today

    # ------------------------------------------------------------------
    # Feed API
    # ------------------------------------------------------------------

    def update(self, price: float) -> None:
        """Call each tick with latest price."""
        try:
            if not math.isfinite(price):
                return
            with self._lock:
                self._maybe_reset_day()
                if price > self._day_high:
                    self._day_high = price
                if price < self._day_low:
                    self._day_low = price
                self._ticks_today += 1
        except Exception as exc:
            logger.debug(f"[WAVE58] update error: {exc}")

    # ------------------------------------------------------------------
    # Gate API
    # ------------------------------------------------------------------

    def get_range_pips(self) -> float:
        """Current intraday range in pips."""
        try:
            with self._lock:
                self._maybe_reset_day()
                if self._day_high == 0.0 or self._day_low == float('inf'):
                    return 0.0
                return (self._day_high - self._day_low) / self.pip_value
        except Exception:
            return 0.0

    def is_entry_blocked(self) -> bool:
        """Returns True if the daily range is too small to trade."""
        try:
            with self._lock:
                self._maybe_reset_day()
                # Need at least 50 ticks before judging the market as flat
                if self._ticks_today < 50:
                    return False
                if self._day_high == 0.0 or self._day_low == float('inf'):
                    return False
                range_pips = (self._day_high - self._day_low) / self.pip_value
                if range_pips < self.min_range_pips:
                    logger.info(
                        f"[WAVE58] FLAT MARKET: daily range {range_pips:.2f} pips "
                        f"< min {self.min_range_pips:.1f} pips -> ENTRY BLOCKED"
                    )
                    return True
                return False
        except Exception as exc:
            logger.debug(f"[WAVE58] is_entry_blocked error: {exc}")
            return True  # fail-closed

    # ------------------------------------------------------------------
    # Info API
    # ------------------------------------------------------------------

    def info(self) -> dict:
        try:
            with self._lock:
                self._maybe_reset_day()
                if self._day_high > 0 and self._day_low < float('inf'):
                    range_pips = round((self._day_high - self._day_low) / self.pip_value, 2)
                else:
                    range_pips = 0.0
                return {
                    "wave": 58,
                    "name": "PriceRangeFilter",
                    "day_high": round(self._day_high, 3) if self._day_high > 0 else None,
                    "day_low": round(self._day_low, 3) if self._day_low < float('inf') else None,
                    "range_pips": range_pips,
                    "min_range_pips": self.min_range_pips,
                    "entry_blocked": (
                        self._ticks_today >= 50 and range_pips < self.min_range_pips
                    ),
                    "ticks_today": self._ticks_today,
                }
        except Exception:
            return {"wave": 58, "error": "info_failed"}


# Module-level singleton
price_range_filter = PriceRangeFilter()
