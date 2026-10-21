"""
wave83_price_deviation_guard.py
---------------------------------
Compares the current bid/ask midpoint to a rolling simple mean of
recent midpoints (proxy VWAP). Blocks new entries when the deviation
exceeds a threshold (default 0.5%) — indicating abnormal pricing,
flash-spike, or broker feed anomaly.

Engineering standards:
- threading.RLock() for all shared state
- bool/NaN/Inf guards on all numeric inputs; bid < ask enforced
- Fail-closed during warmup (requires window_size ticks)
- time.monotonic() for cooldown timer
- Rolling deque for O(1) mean update
"""

import math
import threading
import time
from collections import deque

_lock = threading.RLock()

_window_size = 20           # number of midpoints in rolling mean
_deviation_pct = 0.5        # % deviation from mean that triggers block
_cooldown_sec = 60.0

_midpoints: deque = deque(maxlen=_window_size)
_blocked_until: float = 0.0


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


def update(bid: float, ask: float) -> None:
    """
    Feed a new bid/ask pair. Computes the midpoint, updates the rolling
    mean, and triggers a cooldown if the deviation is too large.
    """
    global _blocked_until

    if not _is_valid_price(bid) or not _is_valid_price(ask):
        return
    if bid >= ask:
        return  # degenerate tick: reject

    mid = (bid + ask) / 2.0

    with _lock:
        # Warmup: accumulate without blocking
        if len(_midpoints) < _window_size:
            _midpoints.append(mid)
            return

        mean = sum(_midpoints) / _window_size
        if mean == 0.0:
            _midpoints.append(mid)
            return

        deviation_pct = abs(mid - mean) / mean * 100.0
        _midpoints.append(mid)

        if deviation_pct >= _deviation_pct:
            _blocked_until = time.monotonic() + _cooldown_sec


def is_entry_blocked() -> bool:
    """
    Return True if the latest midpoint deviated too far from the rolling mean,
    or if still in warmup phase (fail-closed).
    """
    with _lock:
        if len(_midpoints) < _window_size:
            return True   # warmup -> fail-closed
        return time.monotonic() < _blocked_until


# Alias
is_blocked = is_entry_blocked


def get_rolling_mean() -> float:
    """Return the current rolling mean of midpoints, or -1.0 in warmup."""
    with _lock:
        if len(_midpoints) < _window_size:
            return -1.0
        return sum(_midpoints) / _window_size


def reset() -> None:
    """Clear rolling state and cooldown."""
    global _blocked_until
    with _lock:
        _midpoints.clear()
        _blocked_until = 0.0
