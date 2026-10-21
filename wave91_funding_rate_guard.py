"""
wave91_funding_rate_guard.py
------------------------------
Blocks new entries when the provided overnight swap/funding rate
(in pips per day) exceeds a configurable threshold (default 5.0 pips).

High swap rates erode carry on held positions and indicate unfavourable
broker conditions for overnight scalping.

update(swap_pips_per_day) must be called before each entry check.
The guard is purely threshold-based: no rolling window, no warmup.
First call initialises state; before any call -> fail-closed.

Engineering standards:
- threading.RLock() for all shared state
- bool/NaN/Inf guards on all numeric inputs
- Negative swap values accepted (negative = broker pays you)
- Fail-closed before first update call
- time.monotonic() for cooldown timer
"""

import math
import threading
import time

_lock = threading.RLock()

_max_swap_pips   = 5.0      # block when swap cost > this (absolute value)
_cooldown_sec    = 120.0

_last_swap_pips: float | None = None   # None = not yet initialised
_blocked_until: float = 0.0


def _is_valid_swap(v) -> bool:
    if isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return False
    if math.isnan(v) or math.isinf(v):
        return False
    return True


def update(swap_pips_per_day: float) -> None:
    """
    Update the current overnight swap/funding rate (pips/day).
    Positive = cost to hold, negative = broker pays you.
    Blocks if abs(swap) > threshold.
    """
    global _last_swap_pips, _blocked_until

    if not _is_valid_swap(swap_pips_per_day):
        return

    with _lock:
        _last_swap_pips = float(swap_pips_per_day)
        if abs(_last_swap_pips) > _max_swap_pips:
            _blocked_until = time.monotonic() + _cooldown_sec


def is_entry_blocked() -> bool:
    """
    Return True if funding rate is excessive (cooldown active),
    or if no swap data has been provided yet (fail-closed).
    """
    with _lock:
        if _last_swap_pips is None:
            return True   # fail-closed: no data
        return time.monotonic() < _blocked_until


# Alias
is_blocked = is_entry_blocked


def get_last_swap_pips() -> float:
    """Return the most recently recorded swap rate, or float('nan') if uninitialised."""
    with _lock:
        if _last_swap_pips is None:
            return float("nan")
        return _last_swap_pips


def reset() -> None:
    """Reset all state."""
    global _last_swap_pips, _blocked_until
    with _lock:
        _last_swap_pips = None
        _blocked_until = 0.0
