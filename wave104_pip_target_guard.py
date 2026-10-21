"""
wave104_pip_target_guard.py
-----------------------------
Guard: Daily Pip-Target Lock Guard

Blocks new entries once the cumulative pip profit for the trading day
has reached or exceeded a configurable daily pip target, preventing
over-trading when the daily goal is already achieved.

Logic:
- Maintains a running sum of realised pips for the current UTC day.
- When cumulative_pips >= DAILY_PIP_TARGET (default: 50 pips), entry
  is blocked for the remainder of the UTC day (resets at midnight UTC).
- A negative pip result reduces the cumulative total (losses allowed to
  recover the target).
- Fail-closed: bool/NaN/Inf inputs silently ignored.
- Thread-safe: threading.RLock() on all shared state.
- UTC midnight reset via datetime (not monotonic — wall-clock day boundary).

Aliases (required):
  is_entry_blocked()   -> bool
  is_blocked()         -> bool   (alias)
  add_pips(pips)       -> None   (record trade result in pips; can be negative)
  update(pips)         -> None   (alias for add_pips)
  reset()              -> None   (manual reset; also called automatically on new UTC day)
"""

import math
import threading
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DAILY_PIP_TARGET: float = 50.0   # daily pip goal; blocks when reached


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_cumulative_pips: float = 0.0
_day_utc: int = -1   # UTC date ordinal of the last recorded pip; -1 = uninitialised


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today_ordinal() -> int:
    """Return today's UTC date as an integer ordinal."""
    return datetime.now(tz=timezone.utc).toordinal()


def _check_day_rollover() -> None:
    """Reset cumulative pips if the UTC day has changed."""
    global _cumulative_pips, _day_utc
    today = _today_ordinal()
    if _day_utc != today:
        _cumulative_pips = 0.0
        _day_utc = today


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def add_pips(pips) -> None:
    """Record realised pip result of a completed trade.

    Args:
        pips: Pip profit/loss (positive = profit, negative = loss).
              Must be finite, not bool.
    """
    if isinstance(pips, bool):
        return
    if not isinstance(pips, (int, float)):
        return
    if math.isnan(pips) or math.isinf(pips):
        return

    global _cumulative_pips
    with _lock:
        _check_day_rollover()
        _cumulative_pips += float(pips)


def update(pips) -> None:
    """Alias for add_pips()."""
    add_pips(pips)


def is_entry_blocked() -> bool:
    """Return True when cumulative daily pips >= DAILY_PIP_TARGET."""
    with _lock:
        _check_day_rollover()
        return _cumulative_pips >= DAILY_PIP_TARGET


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Manually clear cumulative pip total and day marker."""
    global _cumulative_pips, _day_utc
    with _lock:
        _cumulative_pips = 0.0
        _day_utc = -1
