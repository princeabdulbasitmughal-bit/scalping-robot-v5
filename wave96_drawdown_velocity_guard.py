"""
wave96_drawdown_velocity_guard.py
----------------------------------
Guard: Drawdown Velocity Guard

Blocks new entries when the rate of equity decline (drawdown velocity)
exceeds a configurable threshold over a rolling time window.

Logic:
- Tracks timestamped equity snapshots in a rolling deque (window = 60 seconds).
- Computes velocity = (oldest_equity - latest_equity) / elapsed_seconds  [USD/s].
- If velocity > MAX_VELOCITY_USD_PER_SEC (default: 0.5 USD/s == $30/min),
  entry is blocked for COOLDOWN_SECONDS (default: 90s).
- Warmup: at least MIN_SAMPLES snapshots required before blocking can activate.
- Fail-closed: corrupted inputs treated as no-update (guard stays in last state).
- Thread-safe: threading.RLock() on all shared state.

Aliases:
  is_entry_blocked() -> bool
  is_blocked()       -> bool  (same)
  update(equity)     -> None
  reset()            -> None
"""

import math
import threading
import time
from collections import deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SECONDS: float = 60.0          # rolling equity snapshot window
MAX_VELOCITY_USD_PER_SEC: float = 0.50  # 0.5 USD/s == $30/min drawdown rate
COOLDOWN_SECONDS: float = 90.0        # block duration after threshold breach
MIN_SAMPLES: int = 3                  # minimum snapshots before blocking


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()

# deque of (monotonic_time, equity_usd)
_snapshots: deque = deque()

_blocked_until: float = 0.0   # time.monotonic() deadline


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update(equity) -> None:
    """Record a new equity snapshot.

    Args:
        equity: Current account equity in USD (int or float, finite, not bool).
    """
    if isinstance(equity, bool):
        return
    if not isinstance(equity, (int, float)):
        return
    if math.isnan(equity) or math.isinf(equity):
        return

    now = time.monotonic()
    with _lock:
        _snapshots.append((now, float(equity)))
        # Prune entries older than WINDOW_SECONDS
        cutoff = now - WINDOW_SECONDS
        while _snapshots and _snapshots[0][0] < cutoff:
            _snapshots.popleft()

        # Check velocity
        if len(_snapshots) < MIN_SAMPLES:
            return

        oldest_t, oldest_eq = _snapshots[0]
        latest_t, latest_eq = _snapshots[-1]
        elapsed = latest_t - oldest_t
        if elapsed <= 0.0:
            return

        # Positive velocity = equity is falling
        velocity = (oldest_eq - latest_eq) / elapsed

        if velocity > MAX_VELOCITY_USD_PER_SEC:
            global _blocked_until
            _blocked_until = now + COOLDOWN_SECONDS


def is_entry_blocked() -> bool:
    """Return True when drawdown velocity has recently breached the threshold."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Clear all state (use between tests or sessions)."""
    global _blocked_until
    with _lock:
        _snapshots.clear()
        _blocked_until = 0.0
