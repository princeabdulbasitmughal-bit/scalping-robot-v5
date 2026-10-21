"""
wave85_consecutive_loss_guard.py
---------------------------------
Tracks consecutive losing trades and blocks new entries for a
cooling-off period (default 120s) once N consecutive losses are
recorded (default 5).

A winning trade resets the streak counter to zero.

Engineering standards:
- threading.RLock() for all shared state
- bool/NaN/Inf guards on all PnL inputs
- Fail-closed: corrupted PnL silently ignored (streak unchanged)
- time.monotonic() for cooldown timer
- Break-even (pnl == 0.0) treated as loss (conservative)
"""

import math
import threading
import time

_lock = threading.RLock()

_max_consecutive_losses = 5    # trigger after this many in a row
_cooldown_sec = 120.0

_consecutive_losses: int = 0
_blocked_until: float = 0.0


def _is_valid_pnl(v) -> bool:
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
    pnl > 0 -> win (resets streak)
    pnl <= 0 -> loss/break-even (increments streak)
    """
    global _consecutive_losses, _blocked_until

    if not _is_valid_pnl(pnl):
        return

    with _lock:
        if float(pnl) > 0.0:
            _consecutive_losses = 0
        else:
            _consecutive_losses += 1
            if _consecutive_losses >= _max_consecutive_losses:
                _blocked_until = time.monotonic() + _cooldown_sec


# Alias for wave module convention
update = record_trade_pnl


def is_entry_blocked() -> bool:
    """Return True if consecutive loss threshold has been hit (cooldown active)."""
    with _lock:
        return time.monotonic() < _blocked_until


# Alias
is_blocked = is_entry_blocked


def get_consecutive_losses() -> int:
    """Return the current consecutive loss count."""
    with _lock:
        return _consecutive_losses


def reset() -> None:
    """Reset streak and cooldown."""
    global _consecutive_losses, _blocked_until
    with _lock:
        _consecutive_losses = 0
        _blocked_until = 0.0
