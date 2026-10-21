"""
wave89_position_size_guard.py
------------------------------
Validates requested lot size before a new entry is allowed.
Blocks if the requested lot size is:
  - zero or negative
  - exceeds the configured maximum (default 2.0 lots)
  - not a valid finite positive number

This is a synchronous single-call guard (no rolling window).
Call check_lot_size(lots) before submitting an order.

Engineering standards:
- threading.RLock() for all shared state
- bool/NaN/Inf guards on all numeric inputs
- Fail-closed: invalid lot size -> always blocks
- time.monotonic() for cooldown after oversized order attempt
- No warmup required
"""

import math
import threading
import time

_lock = threading.RLock()

_max_lot_size = 2.0      # maximum allowed position size in lots
_min_lot_size = 0.01     # minimum valid lot size (micro-lot floor)
_cooldown_sec = 30.0     # cooldown after an oversized attempt

_blocked_until: float = 0.0
_last_rejected_size: float = 0.0


def _is_valid_lots(v) -> bool:
    if isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return False
    if math.isnan(v) or math.isinf(v):
        return False
    return True


def check_lot_size(lots: float) -> bool:
    """
    Validate a requested lot size.
    Returns True if the size is acceptable (not blocked).
    Returns False and activates a cooldown if the size is invalid/oversized.
    Also callable as update() for module convention.
    """
    global _blocked_until, _last_rejected_size

    if not _is_valid_lots(lots):
        with _lock:
            _last_rejected_size = 0.0
            _blocked_until = time.monotonic() + _cooldown_sec
        return False

    lots = float(lots)

    if lots < _min_lot_size or lots > _max_lot_size:
        with _lock:
            _last_rejected_size = lots
            _blocked_until = time.monotonic() + _cooldown_sec
        return False

    return True


def update(lots: float) -> None:
    """Alias that records a lot-size validation attempt (module convention)."""
    check_lot_size(lots)


def is_entry_blocked() -> bool:
    """Return True if the last lot-size check failed and cooldown is active."""
    with _lock:
        return time.monotonic() < _blocked_until


# Alias
is_blocked = is_entry_blocked


def get_last_rejected_size() -> float:
    """Return the lot size of the most recent rejected attempt."""
    with _lock:
        return _last_rejected_size


def reset() -> None:
    """Clear cooldown and rejection state."""
    global _blocked_until, _last_rejected_size
    with _lock:
        _blocked_until = 0.0
        _last_rejected_size = 0.0
