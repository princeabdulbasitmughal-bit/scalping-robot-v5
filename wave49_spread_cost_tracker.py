"""
Wave 49: Spread Cost Tracker
Accumulates total spread cost (in USD) paid across all trades.
Logs daily spread cost; blocks new entries if single-day spread cost > $50.
"""

import threading
import time
from datetime import datetime


_MAX_DAILY_SPREAD_USD = 50.0      # block threshold per day
_LOT_USD_PER_PIP      = 1.0       # approximate: $1 per pip per 0.01 lot (XAUUSD)


class SpreadCostTracker:
    """Tracks cumulative spread cost and blocks trading when daily cap hit."""

    def __init__(self, max_daily_usd: float = _MAX_DAILY_SPREAD_USD):
        self._max_daily_usd  = max_daily_usd
        self._daily_cost_usd = 0.0
        self._total_cost_usd = 0.0
        self._trade_count    = 0
        self._current_day    = datetime.utcnow().date()
        self._lock           = threading.Lock()

    def _reset_if_new_day(self) -> None:
        today = datetime.utcnow().date()
        if today != self._current_day:
            self._daily_cost_usd = 0.0
            self._current_day    = today

    # ------------------------------------------------------------------
    def record_trade(self, spread_pips: float, lot_size: float) -> None:
        """Call after each trade open; spread_pips = entry spread in pips."""
        with self._lock:
            self._reset_if_new_day()
            # cost = spread_pips * lot_size * $100 per pip per lot (XAUUSD 0.01 lot = $1/pip)
            cost_usd = spread_pips * (lot_size / 0.01) * _LOT_USD_PER_PIP
            self._daily_cost_usd += cost_usd
            self._total_cost_usd += cost_usd
            self._trade_count    += 1

    def is_entry_blocked(self) -> bool:
        with self._lock:
            self._reset_if_new_day()
            return self._daily_cost_usd >= self._max_daily_usd

    def get_daily_cost(self) -> float:
        with self._lock:
            self._reset_if_new_day()
            return round(self._daily_cost_usd, 4)

    def info(self) -> dict:
        with self._lock:
            self._reset_if_new_day()
            return {
                "daily_spread_cost_usd":  round(self._daily_cost_usd, 4),
                "total_spread_cost_usd":  round(self._total_cost_usd, 4),
                "max_daily_usd":          self._max_daily_usd,
                "trade_count":            self._trade_count,
                "entry_blocked":          self._daily_cost_usd >= self._max_daily_usd,
            }


# Module-level singleton
spread_cost_tracker = SpreadCostTracker()
