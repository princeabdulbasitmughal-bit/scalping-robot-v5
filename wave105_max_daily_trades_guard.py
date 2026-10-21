"""
wave105_max_daily_trades_guard.py
-----------------------------------
Guard: Maximum Daily Trade Count Guard

Blocks new entries once the number of completed trades for the current
UTC day reaches or exceeds MAX_TRADES_PER_DAY (default: 20), enforcing
a hard limit on trading frequency to prevent over-trading.

Logic:
- Maintains a counter of trades executed in the current UTC day.
- When trade_count >= MAX_TRADES_PER_DAY, entry is blocked.
- Resets automatically at UTC midnight.
- Fail-closed: N/A — counting trades is always valid; no numeric input needed.
- Thread-safe: threading.RLock() on all shared state.
- UTC midnight boundary via datetime (not monotonic).

Aliases (required):
  is_entry_blocked()   -> bool
  is_blocked()         -> bool   (alias)
  record_trade()       -> None   (increment daily trade counter by 1)
  update()             -> None   (alias for record_trade)
  reset()              -> None   (manual reset)
"""

import threading
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_TRADES_PER_DAY: int = 20   # maximum trades allowed per UTC day


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_trade_count: int = 0
_day_utc: int = -1   # UTC date ordinal; -1 = uninitialised


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today_ordinal() -> int:
    return datetime.now(tz=timezone.utc).toordinal()


def _check_day_rollover() -> None:
    global _trade_count, _day_utc
    today = _today_ordinal()
    if _day_utc != today:
        _trade_count = 0
        _day_utc = today


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_trade() -> None:
    """Increment the daily trade counter by one."""
    global _trade_count
    with _lock:
        _check_day_rollover()
        _trade_count += 1


def update() -> None:
    """Alias for record_trade()."""
    record_trade()


def is_entry_blocked() -> bool:
    """Return True when the daily trade count has reached MAX_TRADES_PER_DAY."""
    with _lock:
        _check_day_rollover()
        return _trade_count >= MAX_TRADES_PER_DAY


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Manually clear trade count and day marker."""
    global _trade_count, _day_utc
    with _lock:
        _trade_count = 0
        _day_utc = -1
