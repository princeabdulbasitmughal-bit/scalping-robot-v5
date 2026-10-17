"""
Wave 49: Spread Cost Tracker
Accumulates total spread cost (in USD) paid across all trades.
Logs daily spread cost; blocks new entries if single-day spread cost > $50.
"""

import math
import threading
import time
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple, Any

logger = logging.getLogger(__name__)

_MAX_DAILY_SPREAD_USD = 50.0      # block threshold per day
_LOT_USD_PER_PIP      = 1.0       # approximate: $1 per pip per 0.01 lot (XAUUSD)


class SpreadCostTracker:
    """
    Tracks cumulative spread cost and blocks trading when daily cap hit.
    Thread-safe with RLock and supports deterministic datetime injection.
    """

    def __init__(self, max_daily_usd: float = _MAX_DAILY_SPREAD_USD):
        try:
            m = float(max_daily_usd)
            self._max_daily_usd = m if math.isfinite(m) and m > 0 else _MAX_DAILY_SPREAD_USD
        except (ValueError, TypeError):
            self._max_daily_usd = _MAX_DAILY_SPREAD_USD

        self._daily_cost_usd = 0.0
        self._total_cost_usd = 0.0
        self._trade_count    = 0
        self._current_day_str = ""
        self._total_blocks   = 0
        self._lock           = threading.RLock()

    @property
    def daily_cost_usd(self) -> float:
        with self._lock:
            return round(self._daily_cost_usd, 2)

    @property
    def total_cost_usd(self) -> float:
        with self._lock:
            return round(self._total_cost_usd, 2)

    def reset(self) -> None:
        """Thread-safe reset of cumulative spread costs and trade counts."""
        with self._lock:
            self._daily_cost_usd = 0.0
            self._total_cost_usd = 0.0
            self._trade_count    = 0
            self._current_day_str = ""
            self._total_blocks   = 0

    def _normalize_dt(self, dt: Optional[datetime]) -> datetime:
        if dt is None:
            return datetime.now(timezone.utc)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _reset_if_new_day(self, now_dt: Optional[datetime] = None) -> None:
        dt = self._normalize_dt(now_dt)
        today_str = dt.strftime("%Y-%m-%d")
        if today_str != self._current_day_str:
            self._daily_cost_usd = 0.0
            self._current_day_str = today_str

    # ------------------------------------------------------------------
    def record_trade(self, spread_pips: Any, lot_size: Any, now_dt: Optional[datetime] = None) -> None:
        """Call after each trade open; spread_pips = entry spread in pips."""
        if spread_pips is None or lot_size is None or isinstance(spread_pips, bool) or isinstance(lot_size, bool):
            return
        try:
            sp = float(spread_pips)
            lot = float(lot_size)
            if not math.isfinite(sp) or not math.isfinite(lot) or lot <= 0 or sp < 0:
                return
        except (ValueError, TypeError):
            return

        with self._lock:
            self._reset_if_new_day(now_dt)
            # cost = spread_pips * lot_size * $100 per pip per lot (XAUUSD 0.01 lot = $1/pip)
            cost_usd = sp * (lot / 0.01) * _LOT_USD_PER_PIP
            self._daily_cost_usd += cost_usd
            self._total_cost_usd += cost_usd
            self._trade_count    += 1

    def is_entry_blocked(self, now_dt: Optional[datetime] = None) -> bool:
        """Return True if daily spread cost limit is exceeded."""
        try:
            with self._lock:
                self._reset_if_new_day(now_dt)
                blocked = self._daily_cost_usd >= self._max_daily_usd
                if blocked:
                    self._total_blocks += 1
                    logger.warning(
                        f"[WAVE49] Daily spread cost ${self._daily_cost_usd:.2f} >= "
                        f"${self._max_daily_usd:.2f} limit -> ENTRY BLOCKED"
                    )
                return blocked
        except Exception as exc:
            logger.debug(f"[WAVE49] is_entry_blocked error: {exc}")
            return True  # fail-closed

    def is_blocked(self, now_dt: Optional[datetime] = None) -> bool:
        """Standard alias for is_entry_blocked."""
        return self.is_entry_blocked(now_dt=now_dt)

    def is_trading_allowed(self, now_dt: Optional[datetime] = None) -> Tuple[bool, str]:
        """Returns (True, '') if clear, (False, reason) if blocked."""
        blocked = self.is_entry_blocked(now_dt=now_dt)
        if blocked:
            with self._lock:
                return False, f"SPREAD_CAP: daily cost ${self._daily_cost_usd:.2f} >= ${self._max_daily_usd:.2f}"
        return True, ""

    def get_daily_cost(self, now_dt: Optional[datetime] = None) -> float:
        with self._lock:
            self._reset_if_new_day(now_dt)
            return round(self._daily_cost_usd, 4)

    def info(self, now_dt: Optional[datetime] = None) -> dict:
        with self._lock:
            self._reset_if_new_day(now_dt)
            return {
                "wave": 49,
                "name": "SpreadCostTracker",
                "daily_spread_cost_usd":  round(self._daily_cost_usd, 4),
                "total_spread_cost_usd":  round(self._total_cost_usd, 4),
                "max_daily_usd":          self._max_daily_usd,
                "trade_count":            self._trade_count,
                "entry_blocked":          self._daily_cost_usd >= self._max_daily_usd,
                "total_blocks":           self._total_blocks,
                "current_day":            self._current_day_str,
            }


# Module-level singleton
spread_cost_tracker = SpreadCostTracker()
