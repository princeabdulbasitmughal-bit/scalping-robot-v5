"""
Wave 58: Price Range Filter
=============================
Tracks the high and low of intraday price action (reset at UTC midnight).
If the daily price range (high - low) is less than the minimum threshold
in pips, the market is too quiet/flat — blocks all entries.

API:
    price_range_filter.update(price: float, now_dt: Optional[datetime] = None)
    price_range_filter.is_entry_blocked(now_dt: Optional[datetime] = None) -> bool
    price_range_filter.get_range_pips(now_dt: Optional[datetime] = None) -> float
    price_range_filter.info(now_dt: Optional[datetime] = None) -> dict
"""

import math
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, Tuple, Any

logger = logging.getLogger(__name__)

_DEFAULT_MIN_RANGE_PIPS = 5.0   # minimum daily range required to trade
_PIP = 0.1                       # XAUUSD: 1 pip = $0.10
_DEFAULT_MIN_TICKS = 50          # minimum ticks before range filter activates


class PriceRangeFilter:
    """
    Maintains rolling intraday high/low. Blocks entry when the range
    is below `min_range_pips`, indicating a dead/flat session.
    Thread-safe with RLock and supports deterministic datetime injection.
    """

    def __init__(
        self,
        min_range_pips: float = _DEFAULT_MIN_RANGE_PIPS,
        pip_value: float = _PIP,
        min_ticks: int = _DEFAULT_MIN_TICKS,
    ):
        try:
            self.min_range_pips = float(min_range_pips) if math.isfinite(float(min_range_pips)) and float(min_range_pips) >= 0 else _DEFAULT_MIN_RANGE_PIPS
        except (ValueError, TypeError):
            self.min_range_pips = _DEFAULT_MIN_RANGE_PIPS

        try:
            self.pip_value = float(pip_value) if math.isfinite(float(pip_value)) and float(pip_value) > 0 else _PIP
        except (ValueError, TypeError):
            self.pip_value = _PIP

        try:
            self.min_ticks = max(1, int(min_ticks))
        except (ValueError, TypeError):
            self.min_ticks = _DEFAULT_MIN_TICKS

        self._day_high: float = 0.0
        self._day_low: float = float('inf')
        self._last_day_str: str = ""
        self._ticks_today: int = 0
        self._total_blocks: int = 0
        self._lock = threading.RLock()

    def reset(self) -> None:
        """Thread-safe reset of intraday tracking state."""
        with self._lock:
            self._day_high = 0.0
            self._day_low = float('inf')
            self._last_day_str = ""
            self._ticks_today = 0
            self._total_blocks = 0

    def _normalize_dt(self, dt: Optional[datetime]) -> datetime:
        if dt is None:
            return datetime.now(timezone.utc)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _maybe_reset_day(self, now_dt: Optional[datetime] = None) -> None:
        """Reset high/low at UTC midnight."""
        dt = self._normalize_dt(now_dt)
        today_str = dt.strftime("%Y-%m-%d")
        if today_str != self._last_day_str:
            self._day_high = 0.0
            self._day_low = float('inf')
            self._ticks_today = 0
            self._last_day_str = today_str

    # ------------------------------------------------------------------
    # Feed API
    # ------------------------------------------------------------------

    def update(self, price: Any, now_dt: Optional[datetime] = None) -> None:
        """Call each tick with latest price."""
        if price is None or isinstance(price, bool):
            return
        try:
            p = float(price)
            if not math.isfinite(p) or p <= 0:
                return
        except (ValueError, TypeError):
            return

        try:
            with self._lock:
                self._maybe_reset_day(now_dt)
                if p > self._day_high:
                    self._day_high = p
                if p < self._day_low:
                    self._day_low = p
                self._ticks_today += 1
        except Exception as exc:
            logger.debug(f"[WAVE58] update error: {exc}")

    # ------------------------------------------------------------------
    # Gate API
    # ------------------------------------------------------------------

    def get_range_pips(self, now_dt: Optional[datetime] = None) -> float:
        """Current intraday range in pips."""
        try:
            with self._lock:
                self._maybe_reset_day(now_dt)
                if self._day_high == 0.0 or math.isinf(self._day_low) or self._day_high < self._day_low:
                    return 0.0
                return round((self._day_high - self._day_low) / self.pip_value, 2)
        except Exception:
            return 0.0

    def is_entry_blocked(self, now_dt: Optional[datetime] = None) -> bool:
        """Returns True if the daily range is too small to trade."""
        try:
            with self._lock:
                self._maybe_reset_day(now_dt)
                # Need at least min_ticks before judging the market as flat
                if self._ticks_today < self.min_ticks:
                    return False
                if self._day_high == 0.0 or math.isinf(self._day_low):
                    return False
                range_pips = (self._day_high - self._day_low) / self.pip_value
                if range_pips < self.min_range_pips:
                    self._total_blocks += 1
                    logger.info(
                        f"[WAVE58] FLAT MARKET: daily range {range_pips:.2f} pips "
                        f"< min {self.min_range_pips:.1f} pips -> ENTRY BLOCKED"
                    )
                    return True
                return False
        except Exception as exc:
            logger.debug(f"[WAVE58] is_entry_blocked error: {exc}")
            return True  # fail-closed

    def is_blocked(self, now_dt: Optional[datetime] = None) -> bool:
        """Standard alias for is_entry_blocked."""
        return self.is_entry_blocked(now_dt=now_dt)

    def is_trading_allowed(self, now_dt: Optional[datetime] = None) -> Tuple[bool, str]:
        """Returns (True, '') if clear, (False, reason) if blocked."""
        blocked = self.is_entry_blocked(now_dt=now_dt)
        if blocked:
            with self._lock:
                r_pips = self.get_range_pips(now_dt=now_dt)
                return False, f"FLAT_MARKET: daily range {r_pips:.1f}p < {self.min_range_pips:.1f}p"
        return True, ""

    # ------------------------------------------------------------------
    # Info API
    # ------------------------------------------------------------------

    def info(self, now_dt: Optional[datetime] = None) -> dict:
        try:
            with self._lock:
                self._maybe_reset_day(now_dt)
                range_pips = self.get_range_pips(now_dt=now_dt)
                return {
                    "wave": 58,
                    "name": "PriceRangeFilter",
                    "day_high": round(self._day_high, 3) if self._day_high > 0 else None,
                    "day_low": round(self._day_low, 3) if not math.isinf(self._day_low) else None,
                    "range_pips": range_pips,
                    "min_range_pips": self.min_range_pips,
                    "ticks_today": self._ticks_today,
                    "min_ticks": self.min_ticks,
                    "day_utc": self._last_day_str,
                    "is_blocked": range_pips < self.min_range_pips if self._ticks_today >= self.min_ticks else False,
                    "total_blocks": self._total_blocks,
                }
        except Exception:
            return {"wave": 58, "name": "PriceRangeFilter", "error": "info_failed"}


# Module-level singleton
price_range_filter = PriceRangeFilter()
