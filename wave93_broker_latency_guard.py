"""
wave93_broker_latency_guard.py
--------------------------------
Tracks round-trip order acknowledgement latency (ms). Blocks new
entries when the rolling average latency exceeds a configurable
threshold (default 500ms), indicating connectivity or broker issues.

API:
  record_latency(ms)      -> call after each order ack received
  is_entry_blocked()      -> call before submitting a new order
  get_avg_latency_ms()    -> current rolling average
  reset()

Engineering standards:
- threading.RLock() for all shared state
- bool/NaN/Inf guards; negative or zero latency rejected
- Fail-closed during warmup (fewer than min_samples)
- time.monotonic() for cooldown timer
- Rolling deque for O(1) mean
"""

import math
import threading
import time
from collections import deque

_lock = threading.RLock()

_max_avg_latency_ms = 500.0   # block above this average
_window_size        = 10
_min_samples        = 5
_cooldown_sec       = 60.0

_latencies: deque = deque(maxlen=_window_size)
_blocked_until: float = 0.0


def _is_valid_ms(v) -> bool:
    if isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return False
    if math.isnan(v) or math.isinf(v):
        return False
    return v > 0


def record_latency(ms: float) -> None:
    """Record a single round-trip latency measurement in milliseconds."""
    global _blocked_until

    if not _is_valid_ms(ms):
        return

    with _lock:
        _latencies.append(float(ms))

        if len(_latencies) < _min_samples:
            return

        avg = sum(_latencies) / len(_latencies)
        if avg >= _max_avg_latency_ms:
            _blocked_until = time.monotonic() + _cooldown_sec


# Alias
update = record_latency


def is_entry_blocked() -> bool:
    """
    Return True if average latency exceeds threshold (cooldown active)
    or still in warmup (fail-closed).
    """
    with _lock:
        if len(_latencies) < _min_samples:
            return True
        return time.monotonic() < _blocked_until


# Alias
is_blocked = is_entry_blocked


def get_avg_latency_ms() -> float:
    """Return rolling average latency in ms, or -1.0 during warmup."""
    with _lock:
        if len(_latencies) < _min_samples:
            return -1.0
        return sum(_latencies) / len(_latencies)


def reset() -> None:
    """Clear all latency history and cooldown."""
    global _blocked_until
    with _lock:
        _latencies.clear()
        _blocked_until = 0.0
