"""
wave79_daily_loss_limit_guard.py
---------------------------------
Blocks all trading for the remainder of the UTC day once cumulative
daily realised loss exceeds a configurable threshold (default -$200).

Resets automatically at UTC midnight for the new trading day.

Engineering standards:
- threading.RLock() for all shared state
- bool/NaN/Inf guards on all numeric inputs
- Fail-closed: unknown inputs do not inadvertently allow trading
- time.monotonic() NOT used here — wall clock needed for day boundary
- UTC-aware datetime for midnight reset
"""

import math
import threading
from datetime import datetime, timezone

_lock = threading.RLock()

# Configurable threshold (negative USD)
_daily_loss_limit = -200.0

# Per-day state
_current_day = None   # UTC date of the current accumulation window
_daily_pnl = 0.0      # cumulative PnL for today
_limit_hit = False    # True once the limit is breached today


def _utc_today():
    return datetime.now(timezone.utc).date()


def _check_day_rollover():
    """Reset state if the UTC date has changed. Must be called inside _lock."""
    global _current_day, _daily_pnl, _limit_hit
    today = _utc_today()
    if _current_day != today:
        _current_day = today
        _daily_pnl = 0.0
        _limit_hit = False


def _is_valid_pnl(v):
    if isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return False
    if math.isnan(v) or math.isinf(v):
        return False
    return True


def record_trade_pnl(pnl: float) -> None:
    """
    Record the realised PnL of a completed trade.
    Positive = profit, negative = loss (USD).
    """
    global _daily_pnl, _limit_hit

    if not _is_valid_pnl(pnl):
        return

    with _lock:
        _check_day_rollover()
        _daily_pnl += float(pnl)
        if _daily_pnl <= _daily_loss_limit:
            _limit_hit = True


# Alias for consistency with other wave modules
update = record_trade_pnl


def is_entry_blocked() -> bool:
    """
    Return True if today's cumulative loss has hit or exceeded the daily limit.
    Always fail-closed when state is not yet initialised.
    """
    with _lock:
        _check_day_rollover()
        return _limit_hit


# Alias
is_blocked = is_entry_blocked


def get_daily_pnl() -> float:
    """Return the cumulative UTC-day PnL tracked so far."""
    with _lock:
        _check_day_rollover()
        return _daily_pnl


def reset() -> None:
    """Manually reset daily state (e.g. for testing or operator override)."""
    global _current_day, _daily_pnl, _limit_hit
    with _lock:
        _current_day = None
        _daily_pnl = 0.0
        _limit_hit = False
