"""
wave140_order_imbalance_acceleration_guard.py
---------------------------------------------
Guard: Order Flow Cumulative Volume Delta Acceleration Guard

Monitors the second derivative (acceleration) of order flow cumulative delta:
    v_t = d(CVD)/dt
    a_t = d(v)/dt = d^2(CVD)/dt^2
A violent surge in order flow acceleration indicates institutional liquidity
sweeps, stop cascades, or predatory momentum algorithms aggressively eating
order book inventory.

Logic:
- Records signed incremental trade volume (positive for buy aggressor, negative for sell aggressor).
- Tracks cumulative volume delta (CVD) and evaluation timestamps.
- Computes velocity:
    v = delta_lots / dt
- Computes acceleration:
    a = (v_curr - v_prev) / dt
- If abs(a) >= MAX_DELTA_ACCEL (default: 5.0 lots/s^2) with dt >= 0.01s:
    blocks entries for COOLDOWN_SECONDS (default: 45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: non-numeric, boolean, NaN, and Inf inputs are ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()             -> bool
  is_blocked()                   -> bool   (alias)
  record_delta(delta, ts=None)   -> None
  update(delta, ts=None)         -> None   (alias)
  get_current_acceleration()     -> float
  reset()                        -> None
"""

import math
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_DELTA_ACCEL: float = 5.0           # acceleration limit in lots / sec^2
COOLDOWN_SECONDS: float = 45.0         # duration of protective block on acceleration shock
MIN_DT: float = 0.005                  # minimum time delta to avoid microsecond noise


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_time: Optional[float] = None
_prev_velocity: float = 0.0
_current_acceleration: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_delta(delta, ts=None) -> None:
    """Record signed trade lot volume and evaluate order flow delta acceleration."""
    if isinstance(delta, bool) or not isinstance(delta, (int, float)):
        return
    if math.isnan(delta) or math.isinf(delta):
        return

    d_vol = float(delta)
    now = float(ts) if (ts is not None and isinstance(ts, (int, float)) and not isinstance(ts, bool)) else time.monotonic()

    global _prev_time, _prev_velocity, _current_acceleration, _blocked_until
    with _lock:
        if _prev_time is None:
            _prev_time = now
            _prev_velocity = 0.0
            _current_acceleration = 0.0
            return

        dt = now - _prev_time
        if dt >= MIN_DT:
            velocity = d_vol / dt
            accel = (velocity - _prev_velocity) / dt
            _current_acceleration = accel
            _prev_velocity = velocity
            _prev_time = now

            if abs(accel) >= MAX_DELTA_ACCEL:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(delta, ts=None) -> None:
    """Alias for record_delta()."""
    record_delta(delta, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if delta acceleration has activated an entry block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_current_acceleration() -> float:
    """Return the most recently computed order flow acceleration."""
    with _lock:
        return _current_acceleration


def reset() -> None:
    """Reset delta tracking, velocity, acceleration, and active block."""
    global _prev_time, _prev_velocity, _current_acceleration, _blocked_until
    with _lock:
        _prev_time = None
        _prev_velocity = 0.0
        _current_acceleration = 0.0
        _blocked_until = 0.0
