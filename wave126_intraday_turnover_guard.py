"""
wave126_intraday_turnover_guard.py
------------------------------------
Guard: Intraday Gross Notional Turnover Guard

Enforces an aggregate ceiling on daily traded volume (turnover in lots) during
the current UTC trading day to cap cumulative exchange fees, broker commissions,
and excessive churning.

Logic:
- Accumulates lot volume of all executed orders within the current UTC day.
- Resets automatically at UTC midnight.
- If cumulative lots >= MAX_DAILY_LOTS (default: 50.0 lots), blocks entries
  for the remainder of the UTC trading day.
- Fail-closed: invalid, non-numeric, or negative lot sizes ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()             -> bool
  is_blocked()                   -> bool   (alias)
  record_trade_lots(lots)        -> None
  update(lots)                   -> None   (alias)
  reset()                        -> None
"""

import math
import threading
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_DAILY_LOTS: float = 50.0       # max gross lots permitted per UTC day


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_cumulative_lots: float = 0.0
_day_utc: int = -1                 # UTC date ordinal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today_ordinal() -> int:
    return datetime.now(tz=timezone.utc).toordinal()


def _check_rollover() -> None:
    global _cumulative_lots, _day_utc
    today = _today_ordinal()
    if _day_utc != today:
        _cumulative_lots = 0.0
        _day_utc = today


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_trade_lots(lots) -> None:
    """Record executed trade lot volume for the current UTC day."""
    if isinstance(lots, bool) or not isinstance(lots, (int, float)):
        return
    if math.isnan(lots) or math.isinf(lots) or lots <= 0.0:
        return

    l = float(lots)

    global _cumulative_lots
    with _lock:
        _check_rollover()
        _cumulative_lots += l


def update(lots) -> None:
    """Alias for record_trade_lots()."""
    record_trade_lots(lots)


def is_entry_blocked() -> bool:
    """Return True if daily turnover has met or exceeded the daily limit."""
    with _lock:
        _check_rollover()
        return _cumulative_lots >= MAX_DAILY_LOTS


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Reset accumulated lots and day tracking."""
    global _cumulative_lots, _day_utc
    with _lock:
        _cumulative_lots = 0.0
        _day_utc = -1
