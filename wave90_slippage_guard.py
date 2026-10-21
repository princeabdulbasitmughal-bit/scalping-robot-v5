"""
wave90_slippage_guard.py
--------------------------
Tracks actual vs expected fill price slippage per trade.
Blocks new entries for a cooldown period when the rolling average
slippage exceeds a configurable threshold (default 3.0 pips),
indicating broker execution quality degradation.

Slippage (pips) = abs(actual_fill - expected_fill) / pip_size

Engineering standards:
- threading.RLock() for all shared state
- bool/NaN/Inf guards on all numeric inputs
- actual_fill <= 0 or expected_fill <= 0 -> silently ignored
- Fail-closed during warmup (fewer than min_samples)
- time.monotonic() for cooldown timer
- Rolling deque for O(1) mean slippage
"""

import math
import threading
import time
from collections import deque

_lock = threading.RLock()

_pip_size        = 0.0001   # pip size for forex majors
_max_avg_slippage_pips = 3.0
_window_size     = 20
_min_samples     = 5
_cooldown_sec    = 60.0

_slippages: deque = deque(maxlen=_window_size)
_blocked_until: float = 0.0


def _is_valid_price(v) -> bool:
    if isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return False
    if math.isnan(v) or math.isinf(v):
        return False
    return v > 0


def record_fill(expected_fill: float, actual_fill: float) -> None:
    """
    Record a trade fill. Computes slippage in pips and updates
    the rolling average. Triggers a block if average exceeds threshold.
    """
    global _blocked_until

    if not _is_valid_price(expected_fill) or not _is_valid_price(actual_fill):
        return

    slip_pips = abs(actual_fill - expected_fill) / _pip_size

    with _lock:
        _slippages.append(slip_pips)

        if len(_slippages) < _min_samples:
            return

        avg_slip = sum(_slippages) / len(_slippages)
        if avg_slip >= _max_avg_slippage_pips:
            _blocked_until = time.monotonic() + _cooldown_sec


# Alias
update = record_fill


def is_entry_blocked() -> bool:
    """
    Return True if average slippage is too high (cooldown active),
    or still in warmup (fail-closed).
    """
    with _lock:
        if len(_slippages) < _min_samples:
            return True
        return time.monotonic() < _blocked_until


# Alias
is_blocked = is_entry_blocked


def get_avg_slippage_pips() -> float:
    """Return current rolling average slippage in pips, or -1.0 in warmup."""
    with _lock:
        if len(_slippages) < _min_samples:
            return -1.0
        return sum(_slippages) / len(_slippages)


def reset() -> None:
    """Clear all slippage history and cooldown."""
    global _blocked_until
    with _lock:
        _slippages.clear()
        _blocked_until = 0.0
