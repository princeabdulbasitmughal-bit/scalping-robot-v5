"""
wave75_time_of_day_pnl_guard.py
---------------------------------
Risk guard: tracks cumulative PnL aggregated by UTC hour-of-day and blocks
trading during hours that have historically produced net-negative results.

Rules
-----
- Maintains a dict of {hour (0-23): cumulative_pnl}.
- `record_trade_pnl(pnl)` adds the current UTC hour's PnL to the ledger.
- `is_entry_blocked()` returns True when the CURRENT UTC hour's cumulative
  PnL is below `-loss_threshold` (i.e., that hour is a net loser).
- A minimum number of trades per hour is required before blocking activates
  for that hour (`min_trades_per_hour`).
- Fail-closed: invalid PnL inputs raise; gate stays OPEN for unrecorded hours.

Module-level aliases
---------------------
  is_entry_blocked(tick)     -> bool
  is_blocked(tick)           -> bool
  record_trade_pnl(pnl)      -> None
  update(tick)               -> None   (no-op; wave interface)
  reset()                    -> None

Thread-safety
-------------
  All state mutations are guarded by a threading.RLock().
"""

import math
import threading
from datetime import datetime, timezone
from typing import Dict

DEFAULT_LOSS_THRESHOLD:    float = 50.0   # USD net loss per hour to trigger block
DEFAULT_MIN_TRADES_HOUR:   int   = 5      # minimum trades before that hour can block


class TimeOfDayPnlGuard:
    """Blocks entries during UTC hours with chronic net losses."""

    def __init__(
        self,
        loss_threshold: float = DEFAULT_LOSS_THRESHOLD,
        min_trades_per_hour: int = DEFAULT_MIN_TRADES_HOUR,
    ) -> None:
        if isinstance(loss_threshold, bool):
            raise TypeError("loss_threshold must not be bool")
        if not isinstance(loss_threshold, (int, float)):
            raise TypeError("loss_threshold must be numeric")
        if math.isnan(loss_threshold) or math.isinf(loss_threshold):
            raise ValueError("loss_threshold must not be NaN/Inf")
        if loss_threshold <= 0:
            raise ValueError("loss_threshold must be > 0")

        if isinstance(min_trades_per_hour, bool) or not isinstance(min_trades_per_hour, int):
            raise TypeError("min_trades_per_hour must be a plain int")
        if min_trades_per_hour < 1:
            raise ValueError("min_trades_per_hour must be >= 1")

        self.loss_threshold = float(loss_threshold)
        self.min_trades_per_hour = min_trades_per_hour

        self._lock = threading.RLock()
        # hour -> (cumulative_pnl, trade_count)
        self._hourly: Dict[int, list] = {h: [0.0, 0] for h in range(24)}

    @staticmethod
    def _validate_pnl(val: object) -> float:
        if isinstance(val, bool):
            raise TypeError("pnl must not be bool")
        if not isinstance(val, (int, float)):
            raise TypeError("pnl must be numeric")
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            raise ValueError("pnl must not be NaN/Inf")
        return v

    @staticmethod
    def _current_hour() -> int:
        return datetime.now(timezone.utc).hour

    def record_trade_pnl(self, pnl: object) -> None:
        """
        Record a completed trade's PnL for the current UTC hour.

        Parameters
        ----------
        pnl : float — realized profit (positive) or loss (negative) in account currency.
        """
        p = self._validate_pnl(pnl)
        hour = self._current_hour()
        with self._lock:
            self._hourly[hour][0] += p
            self._hourly[hour][1] += 1

    def is_entry_blocked(self, tick: object = None) -> bool:
        """
        Return True (BLOCKED) if the current UTC hour has net PnL below
        -loss_threshold AND has enough recorded trades.
        """
        hour = self._current_hour()
        with self._lock:
            cum_pnl, trade_count = self._hourly[hour]
            if trade_count < self.min_trades_per_hour:
                return False   # not enough data for this hour → allow
            return cum_pnl <= -self.loss_threshold

    def get_hourly_pnl(self, hour: int) -> float:
        """Return cumulative PnL for a specific UTC hour (0-23)."""
        if not isinstance(hour, int) or isinstance(hour, bool):
            raise TypeError("hour must be a plain int")
        if not (0 <= hour <= 23):
            raise ValueError("hour must be 0-23")
        with self._lock:
            return self._hourly[hour][0]

    def get_hourly_trade_count(self, hour: int) -> int:
        """Return trade count for a specific UTC hour."""
        if not isinstance(hour, int) or isinstance(hour, bool):
            raise TypeError("hour must be a plain int")
        if not (0 <= hour <= 23):
            raise ValueError("hour must be 0-23")
        with self._lock:
            return self._hourly[hour][1]

    def reset(self) -> None:
        """Clear all hourly PnL records."""
        with self._lock:
            for h in range(24):
                self._hourly[h] = [0.0, 0]


# ── module-level singleton ──────────────────────────────────────────────────
_guard = TimeOfDayPnlGuard()


def is_entry_blocked(tick: object = None) -> bool:
    return _guard.is_entry_blocked(tick)


def is_blocked(tick: object = None) -> bool:
    return _guard.is_entry_blocked(tick)


def record_trade_pnl(pnl: object) -> None:
    _guard.record_trade_pnl(pnl)


def update(tick: object = None) -> None:
    """No-op update hook (wave interface compatibility)."""
    pass


def reset() -> None:
    _guard.reset()
