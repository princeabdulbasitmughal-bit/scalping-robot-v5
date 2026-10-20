"""
wave64_max_daily_trades_limiter.py
-----------------------------------
Risk guard: blocks new entries once a daily trade count ceiling is reached.

Rules
-----
- Counts every confirmed trade entry (call `record_trade()`).
- Once `max_trades` is reached the gate is CLOSED for the remainder of the UTC day.
- Auto-resets at UTC midnight (or explicitly via `reset()`).
- Fail-closed: invalid inputs (bool, None, NaN, Inf, negative) are rejected and
  the gate stays in its previous state (safe default = OPEN before limit hit).

Module-level aliases
---------------------
  is_entry_blocked(tick) -> bool
  is_blocked(tick)       -> bool   (alias)
  record_trade()         -> None
  reset()                -> None

Thread-safety
-------------
  All state mutations are guarded by a threading.RLock().
"""

import math
import threading
from datetime import datetime, timezone

# ── tuneable constants ──────────────────────────────────────────────────────
DEFAULT_MAX_TRADES: int = 50      # ceiling; override via __init__ or module call


class MaxDailyTradesLimiter:
    """Counts intraday trade entries and blocks new ones beyond the ceiling."""

    def __init__(self, max_trades: int = DEFAULT_MAX_TRADES) -> None:
        if isinstance(max_trades, bool) or not isinstance(max_trades, int):
            raise TypeError("max_trades must be a plain int")
        if max_trades < 1:
            raise ValueError("max_trades must be >= 1")

        self.max_trades: int = max_trades

        self._lock = threading.RLock()
        self._trade_count: int = 0
        self._current_day: int = -1   # tracks UTC day-of-year

    # ── private ────────────────────────────────────────────────────────────
    def _today_ordinal(self) -> int:
        return datetime.now(timezone.utc).toordinal()

    def _maybe_reset_day(self) -> None:
        """Auto-reset counter when the UTC day rolls over."""
        today = self._today_ordinal()
        with self._lock:
            if today != self._current_day:
                self._trade_count = 0
                self._current_day = today

    # ── public API ──────────────────────────────────────────────────────────
    def record_trade(self) -> None:
        """Increment the intraday trade counter by 1."""
        self._maybe_reset_day()
        with self._lock:
            self._trade_count += 1

    def is_entry_blocked(self, tick: object = None) -> bool:
        """
        Return True (BLOCKED) when the daily trade ceiling has been reached.

        Parameters
        ----------
        tick : optional; accepted for API uniformity but not used.

        Returns
        -------
        bool  – True = blocked, False = allowed.
        """
        self._maybe_reset_day()
        with self._lock:
            return self._trade_count >= self.max_trades

    def get_trade_count(self) -> int:
        """Return current intraday trade count (thread-safe)."""
        self._maybe_reset_day()
        with self._lock:
            return self._trade_count

    def reset(self) -> None:
        """Hard-reset state (e.g., for testing or manual override)."""
        with self._lock:
            self._trade_count = 0
            self._current_day = self._today_ordinal()


# ── module-level singleton ──────────────────────────────────────────────────
_limiter = MaxDailyTradesLimiter(max_trades=DEFAULT_MAX_TRADES)


def is_entry_blocked(tick: object = None) -> bool:
    """Module-level alias → MaxDailyTradesLimiter.is_entry_blocked()."""
    return _limiter.is_entry_blocked(tick)


def is_blocked(tick: object = None) -> bool:
    """Alias for is_entry_blocked (uniform wave interface)."""
    return _limiter.is_entry_blocked(tick)


def record_trade() -> None:
    """Module-level alias → MaxDailyTradesLimiter.record_trade()."""
    _limiter.record_trade()


def reset() -> None:
    """Module-level alias → MaxDailyTradesLimiter.reset()."""
    _limiter.reset()


def update(tick: object = None) -> None:
    """No-op update hook (wave interface compatibility)."""
    pass
