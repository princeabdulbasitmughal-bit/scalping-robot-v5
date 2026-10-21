"""
wave82_order_rate_guard.py
---------------------------
Rate-limits order submissions to prevent runaway entry loops.
Blocks new entries when the number of orders submitted in the
last 60 seconds exceeds a configurable maximum (default 10).

Uses a sliding deque of monotonic timestamps — no wall clock needed.

Engineering standards:
- threading.RLock() for all shared state
- bool/NaN/Inf guards on all numeric inputs
- Fail-closed: if max_orders_per_window <= 0, always block
- time.monotonic() throughout
- No warmup required (starts unblocked with empty deque)
"""

import math
import threading
import time
from collections import deque

_lock = threading.RLock()

_window_sec = 60.0          # rolling window in seconds
_max_orders = 10            # max allowed orders inside the window

# Monotonic timestamps of recent order submissions
_order_times: deque = deque()


def record_order() -> None:
    """Call once each time an order is submitted."""
    with _lock:
        _order_times.append(time.monotonic())


# Alias for wave module convention
update = record_order


def _prune(now: float) -> None:
    """Remove timestamps outside the rolling window. Must be called inside _lock."""
    cutoff = now - _window_sec
    while _order_times and _order_times[0] <= cutoff:
        _order_times.popleft()


def is_entry_blocked() -> bool:
    """Return True if order count in the last window exceeds the limit."""
    with _lock:
        if _max_orders <= 0:
            return True
        _prune(time.monotonic())
        return len(_order_times) >= _max_orders


# Alias
is_blocked = is_entry_blocked


def get_order_count() -> int:
    """Return the number of orders recorded in the current rolling window."""
    with _lock:
        _prune(time.monotonic())
        return len(_order_times)


def reset() -> None:
    """Clear all recorded order timestamps."""
    with _lock:
        _order_times.clear()
