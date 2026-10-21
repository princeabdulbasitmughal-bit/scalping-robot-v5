"""
wave81_tick_gap_guard.py
-------------------------
Detects abnormal price gaps between consecutive ticks (> threshold pips).
Blocks new entries for a cooldown period when a gap is detected to avoid
trading on stale prices or during flash-crash / spike conditions.

Engineering standards:
- threading.RLock() for all shared state
- bool/NaN/Inf guards on all numeric inputs
- Fail-closed on None/missing last price (warmup state is NOT blocked —
  first tick always accepted; gap requires at least 2 ticks)
- time.monotonic() for cooldown timer
- pip_size configurable (default 0.0001 for forex majors)
"""

import math
import threading
import time

_lock = threading.RLock()

# Configuration
_gap_threshold_pips = 10.0   # pips between consecutive ticks to trigger block
_pip_size = 0.0001            # pip size (0.0001 for EURUSD etc.)
_cooldown_sec = 45.0

# State
_last_price: float | None = None
_blocked_until: float = 0.0
_last_gap_pips: float = 0.0


def _is_valid_price(v) -> bool:
    if isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return False
    if math.isnan(v) or math.isinf(v):
        return False
    if v <= 0:
        return False
    return True


def update(price: float) -> None:
    """
    Feed a new tick price. If the gap from the previous tick exceeds the
    threshold, a cooldown block is activated.
    """
    global _last_price, _blocked_until, _last_gap_pips

    if not _is_valid_price(price):
        return

    with _lock:
        if _last_price is not None:
            gap_price = abs(price - _last_price)
            gap_pips = gap_price / _pip_size
            _last_gap_pips = gap_pips
            if gap_pips >= _gap_threshold_pips:
                _blocked_until = time.monotonic() + _cooldown_sec
        _last_price = float(price)


def is_entry_blocked() -> bool:
    """Return True if a large tick gap was recently detected (cooldown active)."""
    with _lock:
        return time.monotonic() < _blocked_until


# Alias
is_blocked = is_entry_blocked


def get_last_gap_pips() -> float:
    """Return the pip gap of the most recent tick pair (0.0 if fewer than 2 ticks)."""
    with _lock:
        return _last_gap_pips


def reset() -> None:
    """Reset all state."""
    global _last_price, _blocked_until, _last_gap_pips
    with _lock:
        _last_price = None
        _blocked_until = 0.0
        _last_gap_pips = 0.0
