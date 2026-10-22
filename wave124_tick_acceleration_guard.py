"""
wave124_tick_acceleration_guard.py
------------------------------------
Guard: Tick Price Acceleration (2nd Derivative) Guard

Monitors rapid nonlinear price acceleration (rate of change of tick velocity)
to detect explosive liquidity sweeps, stop-hunts, and news breakouts.

Logic:
- Records (monotonic_timestamp, price) pairs.
- Calculates instantaneous velocity v = (p2 - p1) / (t2 - t1).
- Calculates acceleration a = (v2 - v1) / (t2 - t1).
- If abs(acceleration) >= MAX_ACCELERATION (default: 5.0 pips/s^2),
  blocks entries for COOLDOWN_SECONDS (default: 30.0s).
- Warmup requires at least 3 timestamped ticks.
- Fail-closed: invalid or corrupted inputs ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()             -> bool
  is_blocked()                   -> bool   (alias)
  record_tick(price, ts=None)    -> None
  update(price, ts=None)         -> None   (alias)
  reset()                        -> None
"""

import math
import threading
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_ACCELERATION: float = 5.0     # 5.0 price units / sec^2
COOLDOWN_SECONDS: float = 30.0    # duration of block on acceleration burst


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_time: float = -1.0
_prev_price: float = -1.0
_prev_velocity: float = 0.0
_has_prev_velocity: bool = False
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_tick(price, ts=None) -> None:
    """Record a price tick and evaluate 2nd derivative acceleration."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    p = float(price)
    now = float(ts) if (ts is not None and isinstance(ts, (int, float)) and not isinstance(ts, bool)) else time.monotonic()

    global _prev_time, _prev_price, _prev_velocity, _has_prev_velocity, _blocked_until
    with _lock:
        if _prev_time < 0.0:
            _prev_time = now
            _prev_price = p
            _has_prev_velocity = False
            return

        dt = now - _prev_time
        if dt <= 0.0001:  # sub-millisecond duplicate or backward tick ignored
            return

        velocity = (p - _prev_price) / dt

        if _has_prev_velocity:
            acceleration = (velocity - _prev_velocity) / dt
            if abs(acceleration) >= MAX_ACCELERATION:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS

        _prev_velocity = velocity
        _has_prev_velocity = True
        _prev_time = now
        _prev_price = p


def update(price, ts=None) -> None:
    """Alias for record_tick()."""
    record_tick(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if extreme tick price acceleration is blocking entries."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Reset timing and velocity history, clearing active block."""
    global _prev_time, _prev_price, _prev_velocity, _has_prev_velocity, _blocked_until
    with _lock:
        _prev_time = -1.0
        _prev_price = -1.0
        _prev_velocity = 0.0
        _has_prev_velocity = False
        _blocked_until = 0.0
