"""
wave118_tick_jitter_guard.py
------------------------------
Guard: Tick Arrival Jitter (Latency Variance) Guard

Monitors the timing stability of market quote ticks by computing the sample
standard deviation (jitter) of inter-arrival times between successive ticks.
Erratic inter-arrival times indicate packet loss, broker queue bottlenecks,
or bufferbloat on the network connection.

Logic:
- Records monotonic timestamps of consecutive ticks.
- Computes inter-arrival intervals (delta_t = t_curr - t_prev).
- Maintains a rolling deque of last WINDOW_SIZE intervals.
- When len(deque) >= MIN_SAMPLES (default: 10), computes sample std-dev of intervals (jitter).
- If jitter >= MAX_JITTER_SECONDS (default: 0.50s = 500ms jitter std-dev),
  blocks entries for COOLDOWN_SECONDS (default: 60.0s).
- Fail-closed: invalid or non-numeric timestamps ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()        -> bool
  is_blocked()              -> bool   (alias)
  record_tick(ts=None)      -> None
  update(ts=None)           -> None   (alias)
  reset()                   -> None
"""

import math
import threading
import time
from collections import deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 20              # rolling window of inter-arrival intervals
MIN_SAMPLES: int = 10              # minimum intervals needed for evaluation
MAX_JITTER_SECONDS: float = 0.50   # 500ms standard deviation threshold
COOLDOWN_SECONDS: float = 60.0     # duration of block on jitter spike


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_last_tick_time: float = -1.0
_intervals: deque = deque(maxlen=WINDOW_SIZE)
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _calc_std(samples) -> float:
    n = len(samples)
    if n < 2:
        return 0.0
    mean = sum(samples) / n
    var = sum((x - mean) ** 2 for x in samples) / (n - 1)
    return math.sqrt(var)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_tick(ts=None) -> None:
    """Record receipt of a tick. Optionally accepts an explicit monotonic timestamp."""
    if ts is not None:
        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
            return
        if math.isnan(ts) or math.isinf(ts) or ts <= 0.0:
            return
        now = float(ts)
    else:
        now = time.monotonic()

    global _last_tick_time, _blocked_until
    with _lock:
        if _last_tick_time > 0.0:
            delta = now - _last_tick_time
            if delta >= 0.0:
                _intervals.append(delta)
                if len(_intervals) >= MIN_SAMPLES:
                    jitter = _calc_std(_intervals)
                    if jitter >= MAX_JITTER_SECONDS:
                        _blocked_until = now + COOLDOWN_SECONDS
        _last_tick_time = now


def update(ts=None) -> None:
    """Alias for record_tick()."""
    record_tick(ts=ts)


def is_entry_blocked() -> bool:
    """Return True if high tick arrival jitter is currently blocking entries."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Reset timing history and active block."""
    global _last_tick_time, _blocked_until
    with _lock:
        _last_tick_time = -1.0
        _intervals.clear()
        _blocked_until = 0.0
