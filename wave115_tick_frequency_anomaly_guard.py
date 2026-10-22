"""
wave115_tick_frequency_anomaly_guard.py
-----------------------------------------
Guard: High-Frequency Tick Burst Anomaly Guard

Detects abnormal quote feed surges, algorithmic spamming, or news shockwaves
by calculating the arrival frequency of price ticks over a rolling time window.

Logic:
- Appends time.monotonic() timestamps of incoming ticks to a rolling deque.
- Prunes timestamps older than WINDOW_SECONDS (default: 5.0s).
- Computes frequency: len(deque) / WINDOW_SECONDS (ticks/sec).
- If tick frequency >= MAX_TICKS_PER_SEC (default: 25.0 ticks/s), triggers
  a cooldown block for COOLDOWN_SECONDS (default: 45.0s).
- Fail-closed on corrupted inputs (ignored).
- Thread-safe: threading.RLock() on all shared state.

Aliases (required):
  is_entry_blocked()        -> bool
  is_blocked()              -> bool   (alias)
  record_tick()             -> None
  update()                  -> None   (alias for record_tick)
  reset()                   -> None
"""

import threading
import time
from collections import deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SECONDS: float = 5.0        # rolling time evaluation window
MAX_TICKS_PER_SEC: float = 25.0    # 25 ticks/sec threshold (125 ticks in 5s)
COOLDOWN_SECONDS: float = 45.0     # duration of block on burst anomaly


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_tick_times: deque = deque()
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_tick() -> None:
    """Record receipt of a price tick and evaluate arrival frequency."""
    now = time.monotonic()
    cutoff = now - WINDOW_SECONDS

    global _blocked_until
    with _lock:
        _tick_times.append(now)
        while _tick_times and _tick_times[0] < cutoff:
            _tick_times.popleft()

        frequency = len(_tick_times) / WINDOW_SECONDS
        if frequency >= MAX_TICKS_PER_SEC:
            _blocked_until = now + COOLDOWN_SECONDS


def update() -> None:
    """Alias for record_tick()."""
    record_tick()


def is_entry_blocked() -> bool:
    """Return True if high-frequency tick burst anomaly is active."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Clear recorded tick timestamps and reset active block."""
    global _blocked_until
    with _lock:
        _tick_times.clear()
        _blocked_until = 0.0
