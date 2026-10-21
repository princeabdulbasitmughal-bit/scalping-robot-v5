"""
wave84_margin_level_guard.py
-----------------------------
Blocks new trade entries when the calculated margin level drops below
a safe threshold (default 200%).

Margin Level = (equity / margin_used) * 100

A margin level below 200% signals over-leverage risk. If margin_used
is zero (no open positions), margin level is considered infinite —
NOT blocked.

Engineering standards:
- threading.RLock() for all shared state
- bool/NaN/Inf guards on all numeric inputs
- Fail-closed: negative or zero equity with non-zero margin -> block
- time.monotonic() for cooldown after breach
- No warmup required
"""

import math
import threading
import time

_lock = threading.RLock()

_min_margin_level_pct = 200.0   # block below this margin level %
_cooldown_sec = 60.0

_equity: float = 0.0
_margin_used: float = 0.0
_blocked_until: float = 0.0


def _is_valid_value(v) -> bool:
    if isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return False
    if math.isnan(v) or math.isinf(v):
        return False
    return True


def update(equity: float, margin_used: float) -> None:
    """
    Update current equity and margin used, then evaluate margin level.
    Both values must be non-negative finite numbers.
    """
    global _equity, _margin_used, _blocked_until

    if not _is_valid_value(equity) or not _is_valid_value(margin_used):
        return
    if equity < 0 or margin_used < 0:
        return

    with _lock:
        _equity = float(equity)
        _margin_used = float(margin_used)

        if _margin_used == 0.0:
            # No positions open — margin level infinite, no block
            return

        margin_level_pct = (_equity / _margin_used) * 100.0
        if margin_level_pct < _min_margin_level_pct:
            _blocked_until = time.monotonic() + _cooldown_sec


def is_entry_blocked() -> bool:
    """Return True if margin level is dangerously low (cooldown active)."""
    with _lock:
        return time.monotonic() < _blocked_until


# Alias
is_blocked = is_entry_blocked


def get_margin_level_pct() -> float:
    """
    Return the current margin level percentage.
    Returns float('inf') if margin_used == 0.
    Returns -1.0 if state is not yet initialised.
    """
    with _lock:
        if _margin_used == 0.0:
            return float("inf")
        if _equity == 0.0 and _margin_used == 0.0:
            return -1.0
        return (_equity / _margin_used) * 100.0


def reset() -> None:
    """Reset all state."""
    global _equity, _margin_used, _blocked_until
    with _lock:
        _equity = 0.0
        _margin_used = 0.0
        _blocked_until = 0.0
